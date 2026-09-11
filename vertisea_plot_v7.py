"""VertiSea ground station — live telemetry display and SD log loader.

Packet layouts, the SD log parser and CSV export live in `vertisea_protocol.py`, which has
no GUI dependencies. This module is the Tkinter/matplotlib front end only: it renders live
radio/USB telemetry and drives the parser behind the "Load BIN File" button.
"""

import tkinter as tk
from tkinter import filedialog, messagebox
from collections import deque
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import serial
import serial.tools.list_ports
import struct
import os

# Single source of truth for everything on the read side of the binary protocol.
# Only the radio-facing type IDs are imported: the SD-only types are used exclusively by
# the parser, and importing them here would create a second place to keep in sync.
from vertisea_protocol import (
    TYPE_BME, TYPE_GPS, TYPE_TELEM_IMU, TYPE_STATUS, TYPE_RPM,
    TYPE_CURRENT_STATS, TYPE_BATTERY_VOLTAGE,
    STATUS_FLAG_SD_ERROR, _CSV_SCHEMAS,
    parse_binary_file, write_csvs_from_parsed,
)


class VertiSeaGUI:
    # Placeholder shown in the port dropdown when no serial ports are enumerated.
    # connect_serial() rejects it rather than trying to open a port by this name.
    NO_PORTS = "<no serial ports>"

    # USB vendor IDs of the two USB-serial bridges that can appear in this system, and
    # they must not be confused for each other:
    #
    #   0x1A86 (WCH)  - the CH340E ON THE BUOY ITSELF. Its RTS line is wired to the
    #                   Artemis reset pin, so opening this port can reboot the board
    #                   mid-log. It also carries USB_DEBUG text, never telemetry packets
    #                   (telemetry goes out Serial1 to the radio unless USB_TELEM is set),
    #                   so connecting here shows N/A in every field AND risks the log.
    #   0x0403 (FTDI) - the RFD900x ground modem, which is the port this GUI is for.
    #
    # Detected rather than left to the operator because the failure is silent: the GUI
    # connects, reports "Connected", shows nothing, and the only visible symptom is on the
    # buoy - the heartbeat LED stops, because the board restarted into setup() (LED solid
    # on) or halted. That was observed on 2026-09-02 and again on 2026-09-11.
    BUOY_USB_VID = 0x1A86

    def __init__(self, root):
        self.root = root
        root.title("VertiSea Telemetry Monitor")
        self.ser = None
        self.buffer = bytearray()

        # ---- Connection controls -------------------------------------------
        conn_frame = tk.Frame(root)
        conn_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        tk.Label(conn_frame, text="COM Port:").pack(side=tk.LEFT)
        # tk.OptionMenu(master, variable, value, *values) takes `value` as a REQUIRED
        # positional argument, so `*ports` on an empty list raises TypeError before the
        # window is ever shown. That killed the documented offline workflow ("run the GUI,
        # click Load BIN File, no serial connection needed") on exactly the machines most
        # likely to use it — an analyst's laptop with no COM ports. (Issue 43)
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_var = tk.StringVar(value=ports[0] if ports else self.NO_PORTS)
        self.com_menu = tk.OptionMenu(conn_frame, self.port_var, *(ports or [self.NO_PORTS]))
        self.com_menu.pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(conn_frame, text="Refresh", command=self.refresh_ports).pack(side=tk.LEFT)
        tk.Button(conn_frame, text="Connect", command=self.connect_serial).pack(side=tk.LEFT)

        # "Load BIN File" button — opens a file dialog and parses the SD binary log
        tk.Button(
            conn_frame, text="Load BIN File",
            command=self.load_bin_file,
            bg="#2060a0", fg="white", font=("TkDefaultFont", 9, "bold")
        ).pack(side=tk.LEFT, padx=(10, 0))

        # Link state. Without this the only evidence of a dropped serial link was plots
        # that stopped moving — indistinguishable from a calm sea. (Issue 44)
        self.conn_status_var = tk.StringVar(value="Not connected")
        tk.Label(conn_frame, textvariable=self.conn_status_var, fg="#666666").pack(
            side=tk.LEFT, padx=(10, 0))

        # ---- Telemetry text fields -----------------------------------------
        info_frame = tk.Frame(root)
        info_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        # GPS fields
        gps_frame = tk.LabelFrame(info_frame, text="GPS")
        gps_frame.pack(side=tk.LEFT, padx=5)
        self.sats_var = tk.StringVar(value="N/A")
        self.lat_var  = tk.StringVar(value="N/A")
        self.lon_var  = tk.StringVar(value="N/A")
        for i, (lbl, var) in enumerate([("Sats:", self.sats_var),
                                         ("Lat:",  self.lat_var),
                                         ("Lon:",  self.lon_var)]):
            tk.Label(gps_frame, text=lbl).grid(row=i, column=0, sticky="e")
            tk.Label(gps_frame, textvariable=var).grid(row=i, column=1)

        # BME280 fields
        bme_frame = tk.LabelFrame(info_frame, text="BME280")
        bme_frame.pack(side=tk.LEFT, padx=5)
        self.press_var = tk.StringVar(value="N/A")
        self.hum_var   = tk.StringVar(value="N/A")
        self.temp_var  = tk.StringVar(value="N/A")
        for i, (lbl, var) in enumerate([("Pressure:", self.press_var),
                                         ("Humidity:", self.hum_var),
                                         ("Temp:",     self.temp_var)]):
            tk.Label(bme_frame, text=lbl).grid(row=i, column=0, sticky="e")
            tk.Label(bme_frame, textvariable=var).grid(row=i, column=1)

        # ---- System status panel -------------------------------------------
        status_frame = tk.LabelFrame(info_frame, text="System Status")
        status_frame.pack(side=tk.LEFT, padx=5)

        # SD card status indicator — green = OK, red = ERROR
        tk.Label(status_frame, text="SD Card:").grid(row=0, column=0, sticky="e", padx=(4, 2))
        self.sd_status_label = tk.Label(
            status_frame,
            text="  SD: OK  ",
            bg="green",
            fg="white",
            font=("TkDefaultFont", 10, "bold"),
            relief="raised",
            padx=4, pady=2
        )
        self.sd_status_label.grid(row=0, column=1, padx=(0, 4), pady=4)
        self._sd_ok = True  # track current state to avoid redundant redraws

        # Harvested current display
        tk.Label(status_frame, text="Current:").grid(row=1, column=0, sticky="e", padx=(4, 2))
        self.current_var = tk.StringVar(value="N/A")
        tk.Label(status_frame, textvariable=self.current_var).grid(row=1, column=1, sticky="w")

        # Battery voltage from the dedicated 1 Hz TYPE_BATTERY_VOLTAGE packet.
        tk.Label(status_frame, text="Battery:").grid(row=2, column=0, sticky="e", padx=(4, 2))
        self.battery_var = tk.StringVar(value="N/A")
        tk.Label(status_frame, textvariable=self.battery_var).grid(row=2, column=1, sticky="w")

        # Rotor RPM display (only populated when RPM_ENABLE=1 in firmware)
        tk.Label(status_frame, text="RPM:").grid(row=3, column=0, sticky="e", padx=(4, 2))
        self.rpm_var = tk.StringVar(value="N/A")
        tk.Label(status_frame, textvariable=self.rpm_var).grid(row=3, column=1, sticky="w")

        # ---- Harvested-energy panel (TYPE_CURRENT_STATS, 1 Hz) -------------
        # Peak current and the two accumulated integrals for the current 2-minute
        # window. The separate 1 Hz battery packet supplies voltage without
        # changing the verified TYPE_CURRENT_STATS layout; latest V × running
        # average I is displayed as average battery-side power.
        energy_frame = tk.LabelFrame(info_frame, text="Harvested (2 min window)")
        energy_frame.pack(side=tk.LEFT, padx=5)

        self.peak_var    = tk.StringVar(value="N/A")
        self.charge_var  = tk.StringVar(value="N/A")
        self.i2t_var     = tk.StringVar(value="N/A")
        self.iavg_var    = tk.StringVar(value="N/A")
        self.irms_var    = tk.StringVar(value="N/A")
        self.power_var   = tk.StringVar(value="N/A")
        self.window_var  = tk.StringVar(value="N/A")
        self.drops_var   = tk.StringVar(value="N/A")
        for i, (label, var) in enumerate((
            ("Peak I:",   self.peak_var),
            ("Avg I:",    self.iavg_var),
            ("RMS I:",    self.irms_var),
            ("Avg P:",    self.power_var),
            ("Charge:",   self.charge_var),
            ("\u222bI\u00b2dt:", self.i2t_var),
            ("Window:",   self.window_var),
            ("Dropped:",  self.drops_var),
        )):
            tk.Label(energy_frame, text=label).grid(row=i, column=0, sticky="e", padx=(4, 2))
            tk.Label(energy_frame, textvariable=var).grid(row=i, column=1, sticky="w")

        # ---- Rolling plot data (live telemetry via radio) ------------------
        self.time_data       = deque(maxlen=100)
        self.pitch_data      = deque(maxlen=100)   # fixed IMU pitch
        self.roll_data       = deque(maxlen=100)   # fixed IMU roll
        self.disp_data       = deque(maxlen=100)   # vertical displacement
        self.stab_pitch_data = deque(maxlen=100)   # stabilized IMU pitch
        self.stab_roll_data  = deque(maxlen=100)   # stabilized IMU roll
        # IMU tilt-difference (fixed minus stabilized) — mechanical input proxy
        self.diff_pitch_data = deque(maxlen=100)   # fix_pitch − stab_pitch (°)
        self.diff_roll_data  = deque(maxlen=100)   # fix_roll  − stab_roll  (°)
        # RPM (arrives as separate TYPE_RPM packets — own time axis)
        self.rpm_time_data   = deque(maxlen=100)
        self.rpm_data        = deque(maxlen=100)   # rotor RPM
        self._latest_battery_v = None
        self._latest_i_avg_mA = None

        # ts10 rollover compensation (fixes IDENTIFIED_ISSUES #16).
        # ts10 is uint16 (0–65535), representing millis()/10 (~655 s range).
        # When a backward jump is detected, add 65536 × 0.01 s to the offset.
        self._ts10_last   = 0
        self._ts10_offset = 0.0   # cumulative seconds added for each wrap

        # ---- Plot frames — 2×2 grid ----------------------------------------
        # Row 0: Fixed IMU (left) | Stabilized IMU (right)
        # Row 1: Mechanical input / RPM (left) | Placeholder (right)
        plot_frame = tk.Frame(root)
        plot_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.columnconfigure(1, weight=1)
        plot_frame.rowconfigure(0, weight=1)
        plot_frame.rowconfigure(1, weight=1)

        # Top-left — Fixed IMU Pitch & Roll (live radio telemetry)
        imu_fig = Figure(figsize=(5, 2.5))
        self.imu_ax = imu_fig.add_subplot(111)
        self.imu_ax.set_title("Attitude: Pitch & Roll (pendulum IMU — live radio)")
        self.imu_ax.set_ylabel("degrees")
        self.imu_ax.set_ylim(-60, 60)
        self.imu_line1, = self.imu_ax.plot([], [], label="pitch", color="tab:blue")
        self.imu_line2, = self.imu_ax.plot([], [], label="roll",  color="tab:orange")
        self.imu_ax.legend(loc="upper right")
        imu_fig.tight_layout()
        imu_canvas = FigureCanvasTkAgg(imu_fig, master=plot_frame)
        imu_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.imu_canvas = imu_canvas

        # Top-right — IMU tilt difference (left Y) vs Rotor RPM (right Y)
        # Left axis:  fix−stab pitch & roll difference (degrees) — mechanical input proxy
        # Right axis: rotor RPM from TYPE_RPM packets
        mech_fig = Figure(figsize=(5, 2.5))
        self.mech_ax  = mech_fig.add_subplot(111)  # left Y — tilt difference
        self.mech_ax2 = self.mech_ax.twinx()       # right Y — RPM
        self.mech_ax.set_title("Mechanical Input: IMU Tilt Difference & Rotor RPM")
        self.mech_ax.set_ylabel("pendulum − buoy (°)", color="tab:red")
        self.mech_ax2.set_ylabel("RPM", color="tab:blue")
        self.mech_ax.tick_params(axis="y", labelcolor="tab:red")
        self.mech_ax2.tick_params(axis="y", labelcolor="tab:blue")
        self.mech_ax.set_ylim(-60, 60)
        self.mech_ax2.set_ylim(0, 450)
        self.mech_line_dpitch, = self.mech_ax.plot([], [], label="Δpitch", color="tab:red",    linestyle="-")
        self.mech_line_droll,  = self.mech_ax.plot([], [], label="Δroll",  color="tab:orange", linestyle="--")
        self.mech_line_rpm,    = self.mech_ax2.plot([], [], label="RPM",   color="tab:blue",   linestyle="-")
        # Combined legend for both axes
        lines  = [self.mech_line_dpitch, self.mech_line_droll, self.mech_line_rpm]
        labels = ["Δpitch (°)", "Δroll (°)", "RPM"]  # tilt diff: pendulum − buoy
        self.mech_ax.legend(lines, labels, loc="upper right", fontsize=8)
        # Extra left/right margin so both y-axis labels are fully visible
        mech_fig.subplots_adjust(left=0.15, right=0.85)
        mech_canvas = FigureCanvasTkAgg(mech_fig, master=plot_frame)
        mech_canvas.get_tk_widget().grid(row=0, column=1, sticky="nsew")
        self.mech_canvas = mech_canvas
        self.mech_fig    = mech_fig

        # Bottom-left — Stabilized IMU Pitch & Roll (live radio telemetry)
        stab_fig = Figure(figsize=(5, 2.5))
        self.stab_ax = stab_fig.add_subplot(111)
        self.stab_ax.set_title("Attitude: Pitch & Roll (buoy IMU — live radio)")
        self.stab_ax.set_ylabel("degrees")
        self.stab_ax.set_ylim(-60, 60)
        self.stab_line_pitch, = self.stab_ax.plot([], [], label="pitch", color="tab:blue")
        self.stab_line_roll,  = self.stab_ax.plot([], [], label="roll",  color="tab:orange")
        self.stab_ax.legend(loc="upper right")
        stab_fig.tight_layout()
        stab_canvas = FigureCanvasTkAgg(stab_fig, master=plot_frame)
        stab_canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        self.stab_canvas = stab_canvas

        # Bottom-right — placeholder for future plot
        placeholder = tk.Frame(plot_frame, bg="#1a1a2e", relief="sunken", bd=2)
        placeholder.grid(row=1, column=1, sticky="nsew")
        tk.Label(
            placeholder,
            text="[ Future Plot ]",
            bg="#1a1a2e", fg="#555577",
            font=("TkDefaultFont", 12, "italic")
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Kick off the update loop
        root.after(100, self.update)

    # -----------------------------------------------------------------------
    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        menu = self.com_menu["menu"]
        menu.delete(0, "end")
        # Always leave at least the placeholder in the menu so the widget stays usable
        # and the selected value is never a stale port that has since disappeared.
        for p in (ports or [self.NO_PORTS]):
            menu.add_command(label=p, command=lambda v=p: self.port_var.set(v))
        self.port_var.set(ports[0] if ports else self.NO_PORTS)

    @staticmethod
    def _port_info(port):
        """The list_ports entry for *port*, or None if it has since disappeared."""
        try:
            for p in serial.tools.list_ports.comports():
                if p.device == port:
                    return p
        except Exception:
            pass
        return None

    def _confirm_if_buoy_port(self, port):
        """Warn before opening the buoy's own USB port. Returns True to proceed.

        Not a hard block: connecting to the buoy over USB is legitimate when the firmware
        is built with USB_TELEM 1 and USB_DEBUG 0, which is how telemetry is checked
        without a radio pair. It just must not be done by accident during a logging run.
        """
        info = self._port_info(port)
        if info is None or getattr(info, "vid", None) != self.BUOY_USB_VID:
            return True
        return messagebox.askokcancel(
            "That looks like the buoy, not the radio",
            f"{port} is a CH340 bridge — the USB port on the buoy itself, not the "
            f"RFD900x ground modem.\n\n"
            "Two things follow:\n\n"
            "1. Opening it can RESET the board. The CH340E RTS line drives the Artemis "
            "reset pin. This program holds RTS/DTR low, but the Windows CH340 driver "
            "still changes the line state on open and on close, and a reset pulse can "
            "get through. A reset mid-log restarts millis(), starts a new file, and "
            "stops the heartbeat LED while setup() runs (LED solid ON).\n\n"
            "2. Unless the firmware was built with USB_TELEM 1 and USB_DEBUG 0, this "
            "port carries debug TEXT, not telemetry packets — every field will read "
            "N/A no matter how long you wait.\n\n"
            "Connect to the RFD900x modem instead, or use \"Load BIN File\" to read the "
            "SD log, which needs no serial connection at all.\n\n"
            "Open it anyway?")

    def connect_serial(self):
        port = self.port_var.get()
        if not port or port == self.NO_PORTS:
            messagebox.showwarning(
                "No Port",
                "No serial port is selected.\n\n"
                "Plug in the RFD900x modem (or the buoy over USB), click Refresh, then "
                "Connect.\n\nParsing an SD log with \"Load BIN File\" does not need a "
                "serial connection.")
            return

        # Close any previously opened port first. Without this, clicking Connect twice
        # leaves the first handle open and owned by a dropped object; on Windows the port
        # stays locked until the process exits, so reconnecting fails with "access
        # denied" and the user has to restart the program. (Issue 50)
        self._close_serial()

        if not self._confirm_if_buoy_port(port):
            return

        try:
            # IMPORTANT — do not let pyserial assert RTS/DTR on open.
            #
            # The RedBoard Artemis Nano uses a CH340E whose RTS line is wired to
            # the Artemis reset pin (it is how the SVL bootloader is triggered).
            # pyserial asserts BOTH dtr and rts by default when opening a port,
            # so a plain serial.Serial(port, ...) REBOOTS THE BUOY — losing the
            # in-progress SD log, restarting millis(), and appending a second
            # session to the same file if the RTC minute has not rolled over.
            #
            # This was observed on 2026-09-02: connecting the GUI ~14 s after
            # power-up produced a log containing two complete boot sequences with
            # ts_ms resetting 10002 -> 591.
            #
            # Constructing with port=None defers opening, so rts/dtr can be
            # cleared BEFORE the port is opened. Setting them after the fact
            # would be too late — the reset pulse has already happened.
            self.ser = serial.Serial(baudrate=115200, timeout=0.1)
            self.ser.port = port
            try:
                self.ser.rts = False
                self.ser.dtr = False
            except (OSError, AttributeError, ValueError):
                # Some drivers/platforms reject setting these while closed.
                # Not fatal: fall through and open anyway rather than refusing
                # to connect at all.
                pass
            self.ser.open()
            self.buffer = bytearray()
            self.conn_status_var.set(f"Connected: {port}")
            messagebox.showinfo(
                "Connected",
                f"Opened {port} @115200 baud\n"
                "(RTS/DTR held low so the board is not reset)\n\n"
                "If no data arrives, check that the firmware was built with "
                "TELEM_ENABLE 1 — the committed default is 0, which transmits nothing.")
        except Exception as e:
            self.ser = None
            self.conn_status_var.set("Not connected")
            messagebox.showerror("Error", f"Could not open {port}:\n{e}")

    def _close_serial(self):
        """Close the serial port if one is open, swallowing driver errors."""
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass  # the device may already be gone; nothing useful to do about it
            self.ser = None

    def _on_link_lost(self, exc: Exception):
        """Handle the serial link disappearing mid-session (unplugged modem, driver reset).

        The GUI must keep running: a frozen-but-alive window is indistinguishable from a
        quiet sea state, which is the worst possible failure mode during a deployment.
        """
        self._close_serial()
        self._set_sd_status(False)
        self.sd_status_label.config(text=" LINK LOST ", bg="red")
        self.conn_status_var.set(f"Disconnected: {type(exc).__name__}")

    def _monotonic_seconds(self, ts10: int) -> float:
        """Convert a uint16 ts10 field to monotonic seconds since boot.

        ts10 is millis()/10 and wraps every 655.36 s. Every packet type that carries a
        ts10 must go through this one wrap counter — when only the 0x06 branch advanced
        `_ts10_last`, the 0x0C (RPM) series could land a full 655 s away from the attitude
        series around each wrap, because the two packets are emitted from different places
        in loop() and can straddle the boundary in either order. (Issue 49)
        """
        if ts10 < self._ts10_last:
            self._ts10_offset += 65536 * 0.01   # one full uint16 wrap = 655.36 s
        self._ts10_last = ts10
        return ts10 * 0.01 + self._ts10_offset

    def _set_sd_status(self, ok: bool):
        """Update the SD status indicator label colour and text."""
        if ok == self._sd_ok:
            return  # no change — skip redundant widget update
        self._sd_ok = ok
        if ok:
            self.sd_status_label.config(text="  SD: OK  ", bg="green")
        else:
            self.sd_status_label.config(text=" SD: ERROR ", bg="red")

    # -----------------------------------------------------------------------
    def load_bin_file(self):
        """Open a file dialog, parse the selected .BIN file, write CSVs, and
        update the lower plot with the stabilized IMU pitch & roll data."""
        bin_path = filedialog.askopenfilename(
            title="Select VertiSea SD binary log",
            filetypes=[("Binary log", "*.BIN *.bin"), ("All files", "*.*")]
        )
        if not bin_path:
            return  # user cancelled

        try:
            data = parse_binary_file(bin_path)
        except Exception as e:
            messagebox.showerror("Parse Error", f"Failed to parse {bin_path}:\n{e}")
            return

        # Write CSVs alongside the BIN file
        out_dir   = os.path.dirname(bin_path)
        base_name = os.path.splitext(os.path.basename(bin_path))[0]
        try:
            written = write_csvs_from_parsed(data, out_dir, base_name)
        except Exception as e:
            messagebox.showwarning("CSV Write Warning",
                                   f"Parsed OK but could not write CSVs:\n{e}")
            written = []

        # Report genuine parse warnings only. Informational messages live in
        # data['notes'] and are folded into the summary dialog instead, so that a
        # warning popup always means something actually needs attention.
        if data['errors']:
            messagebox.showwarning(
                "Parse Warnings",
                f"{len(data['errors'])} warning(s) during parse:\n" +
                "\n".join(data['errors'][:10]) +
                ("\n…" if len(data['errors']) > 10 else "")
            )

        bin_fname = base_name + ".BIN"

        # ---- Update upper plot with fixed IMU pitch & roll from BIN file ---
        fixed_records = data.get('fixed_imu', [])
        if fixed_records:
            t_s     = [r['ts_ms'] / 1000.0 for r in fixed_records]
            pitches = [r['pitch']           for r in fixed_records]
            rolls   = [r['roll']            for r in fixed_records]
            self.imu_line1.set_data(t_s, pitches)
            self.imu_line2.set_data(t_s, rolls)
            self.imu_ax.relim()
            self.imu_ax.autoscale_view()
            self.imu_ax.set_xlabel("time (s)")
            self.imu_ax.set_title(
                f"Attitude: Pitch & Roll (pendulum IMU — {bin_fname})"
            )
            self.imu_canvas.draw()

        # ---- Update lower plot with stabilized IMU pitch & roll ------------
        #
        # A log from an IMU_RAW_ONLY=1 build legitimately has no 0x02 records — the
        # firmware writes 0x12 instead — and that is the committed default. Warning about
        # it taught operators to dismiss the dialog without reading it. Say what actually
        # happened, only when there is genuinely no IMU data of either kind. (Issue 38)
        stab_records = data.get('stab_imu', [])
        if not stab_records:
            if data.get('imu_raw'):
                summary_note = (
                    "No on-board attitude in this log: it was recorded by an "
                    "IMU_RAW_ONLY=1 build, which logs uncalibrated TYPE_IMU_RAW (0x12) "
                    "records instead of TYPE_FIXED_IMU/TYPE_STAB_IMU. Recompute pitch and "
                    "roll offline from <base>_imuRaw.csv using <base>_calFixed.csv, "
                    "<base>_calStab.csv and <base>_lpfCal.csv. The attitude plots stay "
                    "empty — this is expected.")
            else:
                summary_note = (
                    "This log contains no IMU records of any kind (neither 0x01/0x02 nor "
                    "0x12). Check that the firmware's IMU init succeeded.")
            data.setdefault('notes', []).append(summary_note)
        else:
            t_s     = [r['ts_ms'] / 1000.0 for r in stab_records]
            pitches = [r['pitch']           for r in stab_records]
            rolls   = [r['roll']            for r in stab_records]
            self.stab_line_pitch.set_data(t_s, pitches)
            self.stab_line_roll.set_data(t_s, rolls)
            self.stab_ax.relim()
            self.stab_ax.autoscale_view()
            self.stab_ax.set_xlabel("time (s)")
            self.stab_ax.set_title(
                f"Attitude: Pitch & Roll (buoy IMU — {bin_fname})"
            )
            self.stab_canvas.draw()

        # Summary message. Driven by _CSV_SCHEMAS rather than a parallel hard-coded list,
        # so a newly added packet type appears here automatically. (Issue 51)
        summary_lines = [f"Parsed: {os.path.basename(bin_path)}"]
        for key in _CSV_SCHEMAS:
            n = len(data.get(key, []))
            if n:
                summary_lines.append(f"  {key}: {n:,} records")
        if written:
            summary_lines.append(f"\nCSVs written ({len(written)}):")
            for p in written:
                summary_lines.append(f"  {os.path.basename(p)}")
        if data.get('notes'):
            summary_lines.append("\nNotes:")
            for n in data['notes']:
                summary_lines.append(f"  {n}")
        messagebox.showinfo("Parse Complete", "\n".join(summary_lines))

    # -----------------------------------------------------------------------
    def update(self):
        """Tk poll tick: drain the serial buffer, then repaint at most once.

        Everything here is wrapped so that no exception can escape into Tk. An escaping
        exception is not merely logged — Tk never reaches the `root.after()` at the bottom,
        so the callback is never rescheduled and the whole GUI stops updating for good
        while still looking alive. The reschedule therefore lives in `finally`. (Issue 44)
        """
        try:
            self._update_once()
        except (serial.SerialException, OSError) as e:
            # Modem unplugged, driver reset, USB power glitch.
            self._on_link_lost(e)
        finally:
            # Schedule next update (100 ms poll interval). Must never be skipped.
            self.root.after(100, self.update)

    def _update_once(self):
        # Read all available bytes from the serial port
        if self.ser and self.ser.in_waiting:
            self.buffer.extend(self.ser.read(self.ser.in_waiting))

        # Canvases touched this tick. Drawing is deferred until the buffer is fully
        # drained: a matplotlib draw() costs tens of milliseconds, and doing three of
        # them per packet inside the loop meant redraw time could exceed the packet
        # arrival interval, so the backlog grew and the GUI stalled. (Issue 48)
        dirty = set()

        # Parse packets — consume as many complete packets as possible
        while len(self.buffer) >= 1:
            p = self.buffer[0]

            # ---- TYPE_TELEM_IMU (0x06) — 13 bytes -------------------------
            # Payload: uint16 ts10,
            #          int16 fix_pitch_cdeg, int16 fix_roll_cdeg,  (centidegrees ×100)
            #          int16 vertDisp_mm,
            #          int16 stab_pitch_cdeg, int16 stab_roll_cdeg (centidegrees ×100)
            # Angle scale ×100 supports ±327.67° without int16 overflow.
            if p == TYPE_TELEM_IMU:
                if len(self.buffer) < 13:
                    break  # wait for more data
                pkt = self.buffer[:13]
                del self.buffer[:13]
                _, ts10, pitch_cdeg, roll_cdeg, disp_mm, stab_pitch_cdeg, stab_roll_cdeg = \
                    struct.unpack('<BHhhhhh', pkt)
                # Monotonic seconds since boot, via the shared wrap counter
                # (fixes IDENTIFIED_ISSUES #16 and #49)
                t          = self._monotonic_seconds(ts10)
                pitch      = pitch_cdeg      / 100.0   # fixed IMU pitch (degrees)
                roll       = roll_cdeg       / 100.0   # fixed IMU roll  (degrees)
                disp       = disp_mm         / 1000.0  # vertical displacement (metres)
                stab_pitch = stab_pitch_cdeg / 100.0   # stabilized IMU pitch (degrees)
                stab_roll  = stab_roll_cdeg  / 100.0   # stabilized IMU roll  (degrees)
                self.time_data.append(t)
                self.pitch_data.append(pitch)
                self.roll_data.append(roll)
                self.disp_data.append(disp)
                self.stab_pitch_data.append(stab_pitch)
                self.stab_roll_data.append(stab_roll)
                # Tilt difference: fixed IMU minus stabilized IMU
                self.diff_pitch_data.append(pitch - stab_pitch)
                self.diff_roll_data.append(roll  - stab_roll)
                # Update upper plot — fixed IMU pitch & roll
                self.imu_line1.set_data(self.time_data, self.pitch_data)
                self.imu_line2.set_data(self.time_data, self.roll_data)
                self.imu_ax.relim()
                self.imu_ax.autoscale_view()
                # Update lower plot — stabilized IMU pitch & roll
                self.stab_line_pitch.set_data(self.time_data, self.stab_pitch_data)
                self.stab_line_roll.set_data(self.time_data, self.stab_roll_data)
                self.stab_ax.relim()
                self.stab_ax.autoscale_view()
                # Update third plot — tilt difference (left axis)
                self.mech_line_dpitch.set_data(self.time_data, self.diff_pitch_data)
                self.mech_line_droll.set_data(self.time_data, self.diff_roll_data)
                self.mech_ax.relim()
                self.mech_ax.autoscale_view(scaley=False)  # scroll x; y fixed at ±60°
                dirty.update((self.imu_canvas, self.stab_canvas, self.mech_canvas))
                continue

            # ---- TYPE_GPS (0x04) — 12 bytes (radio format) -----------------
            # Payload: uint16 ts10, uint8 sats, float lat, float lon
            elif p == TYPE_GPS:
                if len(self.buffer) < 12:
                    break
                pkt = self.buffer[:12]
                del self.buffer[:12]
                _, ts10, sats, lat, lon = struct.unpack('<BHBff', pkt)
                self.sats_var.set(str(sats))
                self.lat_var.set(f"{lat:.6f}")
                self.lon_var.set(f"{lon:.6f}")
                continue

            # ---- TYPE_BME (0x03) — 15 bytes (radio format) -----------------
            # Payload: uint16 ts10, float pressure (Pa), float humidity (%), float temp (°C)
            elif p == TYPE_BME:
                if len(self.buffer) < 15:
                    break
                pkt = self.buffer[:15]
                del self.buffer[:15]
                _, ts10, pres, hum, tmp = struct.unpack('<BHfff', pkt)
                self.press_var.set(f"{pres/100.0:.1f} hPa")
                self.hum_var.set(f"{hum:.1f} %")
                self.temp_var.set(f"{tmp:.1f} °C")
                continue

            # ---- TYPE_CURRENT_STATS (0x0F) — 27 bytes (radio format) -------
            # Payload: uint16 ts10, uint16 window_s, uint16 peak_mA,
            #          float charge_mC, float i2t_mA2s, float integ_s,
            #          uint32 n_samples, uint32 n_dropped
            elif p == TYPE_CURRENT_STATS:
                if len(self.buffer) < 27:
                    break
                pkt = self.buffer[:27]
                del self.buffer[:27]
                (_, ts10, window_s, peak_mA, charge_mC, i2t_mA2s, integ_s,
                 n_samples, n_dropped) = struct.unpack('<BHHHfffII', pkt)

                self.peak_var.set(f"{peak_mA} mA")
                self.charge_var.set(f"{charge_mC:.1f} mC")
                self.i2t_var.set(f"{i2t_mA2s:.1f} mA\u00b2s")

                # Average and RMS must be divided by the TRUE integration time
                # (integ_s), not the wall-clock window. When the sampler cannot
                # hit its requested rate the two differ substantially and using
                # window_s understates both by exactly that ratio.
                if integ_s > 0:
                    i_avg = charge_mC / integ_s
                    self._latest_i_avg_mA = i_avg
                    self.iavg_var.set(f"{i_avg:.3f} mA")
                    self.irms_var.set(f"{(i2t_mA2s / integ_s) ** 0.5:.3f} mA")
                    # The System Status "Current:" field used to come from the 5 Hz
                    # TYPE_CURRENT (0x0A) packet, which was retired because a point
                    # sample of a bursty signal reads ~2.1x high. It now shows the
                    # window average, which is unbiased. Labelled "avg" so it is not
                    # mistaken for an instantaneous reading.
                    self.current_var.set(f"{i_avg:.2f} mA avg")
                    if self._latest_battery_v is not None:
                        self.power_var.set(
                            f"{self._latest_battery_v * i_avg:.3f} mW")
                    else:
                        self.power_var.set("--")
                else:
                    self._latest_i_avg_mA = None
                    self.iavg_var.set("--")
                    self.irms_var.set("--")
                    self.current_var.set("--")
                    self.power_var.set("--")

                # Effective sample rate and duty give an immediate read on
                # whether the sampler is keeping up.
                if window_s > 0:
                    rate = n_samples / window_s
                    duty = 100.0 * integ_s / window_s
                    self.window_var.set(
                        f"{window_s}s  n={n_samples}  {rate:.0f}Hz  duty={duty:.0f}%")
                else:
                    self.window_var.set(f"{window_s}s  n={n_samples}")

                if n_dropped:
                    self.drops_var.set(f"{n_dropped}  (rate below request)")
                else:
                    self.drops_var.set("0")
                continue

            # ---- TYPE_BATTERY_VOLTAGE (0x14) — 5 bytes (radio format) ------
            # Payload: uint16 ts10, uint16 battery_mV. Calibration stays in the
            # SD-only 0x13 record; telemetry is already converted by firmware.
            elif p == TYPE_BATTERY_VOLTAGE:
                if len(self.buffer) < 5:
                    break
                pkt = self.buffer[:5]
                del self.buffer[:5]
                _, ts10, battery_mV = struct.unpack('<BHH', pkt)
                self._latest_battery_v = battery_mV / 1000.0
                self.battery_var.set(f"{self._latest_battery_v:.3f} V")
                if self._latest_i_avg_mA is not None:
                    self.power_var.set(
                        f"{self._latest_battery_v * self._latest_i_avg_mA:.3f} mW")
                continue

            # ---- TYPE_RPM (0x0C) — 5 bytes (radio format) ------------------
            # Payload: uint16 ts10, uint16 rpm
            elif p == TYPE_RPM:
                if len(self.buffer) < 5:
                    break
                pkt = self.buffer[:5]
                del self.buffer[:5]
                _, ts10, rpm = struct.unpack('<BHH', pkt)
                self.rpm_var.set(f"{rpm} RPM")
                # Same wrap counter as every other ts10-bearing packet (Issue 49)
                self.rpm_time_data.append(self._monotonic_seconds(ts10))
                self.rpm_data.append(rpm)
                # Update third plot — RPM (right axis)
                self.mech_line_rpm.set_data(self.rpm_time_data, self.rpm_data)
                self.mech_ax2.relim()
                self.mech_ax2.autoscale_view(scaley=False)  # scroll x; y fixed by set_ylim
                dirty.add(self.mech_canvas)
                continue

            # ---- TYPE_STATUS (0x0B) — 4 bytes (radio only) -----------------
            # Payload: uint16 ts10, uint8 flags
            #   flags bit 0 = sdError (0=OK, 1=SD write failure)
            elif p == TYPE_STATUS:
                if len(self.buffer) < 4:
                    break
                pkt = self.buffer[:4]
                del self.buffer[:4]
                _, ts10, flags = struct.unpack('<BHB', pkt)
                sd_ok = not bool(flags & STATUS_FLAG_SD_ERROR)
                self._set_sd_status(sd_ok)
                continue

            # ---- Unknown / out-of-sync byte --------------------------------
            # Drop one byte and try again. This handles framing errors and
            # any packet types not yet implemented in this parser.
            else:
                del self.buffer[0]
                continue

        # One repaint per canvas per tick, after the buffer is drained. draw_idle() lets
        # Tk coalesce repaints instead of blocking here. (Issue 48)
        for canvas in dirty:
            canvas.draw_idle()


if __name__ == "__main__":
    root = tk.Tk()
    app = VertiSeaGUI(root)
    root.mainloop()
