"""VertiSea ground station — live telemetry display and SD log loader.

Packet layouts, the SD log parser and CSV export live in `vertisea_protocol.py`, which has
no GUI dependencies. This module is the Tkinter/matplotlib front end only: it renders live
radio/USB telemetry and drives the parser behind the "Load BIN File" button.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from collections import deque
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import serial
import serial.tools.list_ports
import json
import math
import os
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from PIL import ImageGrab

# Single source of truth for everything on the read side of the binary protocol.
# Only the radio-facing type IDs are imported: the SD-only types are used exclusively by
# the parser, and importing them here would create a second place to keep in sync.
from vertisea_protocol import (
    TYPE_BME, TYPE_GPS, TYPE_TELEM_IMU, TYPE_STATUS, TYPE_RPM,
    TYPE_CURRENT_STATS, TYPE_BATTERY_VOLTAGE,
    parse_binary_file, write_csvs_from_parsed,
)
from vertisea_live import LiveRecorder, TelemetryParser, TimestampClock, current_interval_stats


class VertiSeaGUI:
    DISPLAY_SECONDS = 60.0
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
        self.paused = False
        self._frozen_view = None
        self._live_display_values = None
        self._telemetry_parser = TelemetryParser()
        self._timestamp_clock = TimestampClock()
        self.recorder = None
        self.recording_error = None
        self.session_directory = Path(__file__).resolve().parent / "sessions"
        self._last_import_sources = None
        self._last_session_path = None
        self._closing = False
        root.protocol("WM_DELETE_WINDOW", self.close_window)

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
        tk.Button(conn_frame, text="Disconnect", command=self.disconnect_serial).pack(side=tk.LEFT)

        # "Load BIN File" button — opens a file dialog and parses the SD binary log
        tk.Button(
            conn_frame, text="Load BIN File",
            command=self.load_bin_file,
            bg="#2060a0", fg="white", font=("TkDefaultFont", 9, "bold")
        ).pack(side=tk.LEFT, padx=(10, 0))
        session_frame = tk.Frame(root)
        session_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 5))
        tk.Button(session_frame, text="Import Session", command=self.import_session_dialog).pack(side=tk.LEFT)
        tk.Button(session_frame, text="Analyze Cycle", command=self.analyze_cycle_dialog).pack(side=tk.LEFT)
        tk.Button(session_frame, text="Data Explorer", command=self.data_explorer_dialog).pack(side=tk.LEFT, padx=5)
        self.pause_button = tk.Button(conn_frame, text="Pause", command=self.toggle_pause)
        self.pause_button.pack(side=tk.LEFT, padx=(5, 0))
        tk.Button(conn_frame, text="Snapshot", command=self.save_snapshot).pack(side=tk.LEFT)

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
        self.time_data       = deque(maxlen=1200)
        self.pitch_data      = deque(maxlen=1200)   # fixed IMU pitch
        self.roll_data       = deque(maxlen=1200)   # fixed IMU roll
        self.disp_data       = deque(maxlen=1200)   # vertical displacement
        self.stab_pitch_data = deque(maxlen=1200)   # stabilized IMU pitch
        self.stab_roll_data  = deque(maxlen=1200)   # stabilized IMU roll
        # IMU tilt-difference (fixed minus stabilized) — mechanical input proxy
        self.diff_pitch_data = deque(maxlen=1200)   # fix_pitch − stab_pitch (°)
        self.diff_roll_data  = deque(maxlen=1200)   # fix_roll  − stab_roll  (°)
        # RPM (arrives as separate TYPE_RPM packets — own time axis)
        self.rpm_time_data   = deque(maxlen=1200)
        self.rpm_data        = deque(maxlen=1200)   # rotor RPM
        self._latest_battery_v = None
        self._latest_i_avg_mA = None
        self._latest_battery_time = None
        self._previous_current_stats = None
        self.charging_time_data = deque(maxlen=600)
        self.charging_current_data = deque(maxlen=600)
        self.charging_power_data = deque(maxlen=600)
        self.battery_time_data = deque(maxlen=300)
        self.battery_voltage_data = deque(maxlen=300)

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
        self.imu_ax.set_title("Pendulum IMU: pitch & roll", fontsize=10)
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
        self.mech_ax.set_title("Tilt difference & rotor RPM", fontsize=10)
        self.mech_ax.set_ylabel("pendulum − buoy (°)", color="tab:red")
        self.mech_ax2.set_ylabel("RPM", color="tab:blue")
        self.mech_ax.tick_params(axis="y", labelcolor="tab:red")
        self.mech_ax2.tick_params(axis="y", labelcolor="tab:blue")
        self.mech_ax.set_ylim(-60, 60)
        self.mech_ax2.set_ylim(0, 1800)
        self.mech_ax2.set_yticks([0, 600, 1200, 1800])
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
        self.stab_ax.set_title("Buoy IMU: pitch & roll", fontsize=10)
        self.stab_ax.set_ylabel("degrees")
        self.stab_ax.set_ylim(-60, 60)
        self.stab_line_pitch, = self.stab_ax.plot([], [], label="pitch", color="tab:blue")
        self.stab_line_roll,  = self.stab_ax.plot([], [], label="roll",  color="tab:orange")
        self.stab_ax.legend(loc="upper right")
        stab_fig.tight_layout()
        stab_canvas = FigureCanvasTkAgg(stab_fig, master=plot_frame)
        stab_canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        self.stab_canvas = stab_canvas

        charging_fig = Figure(figsize=(5, 3.5))
        self.charging_current_ax, self.charging_power_ax, self.battery_ax = \
            charging_fig.subplots(3, 1, sharex=True)
        self.charging_current_ax.set_title("Battery-side charging", fontsize=10)
        self.charging_current_ax.set_ylabel("I (mA)")
        self.charging_power_ax.set_ylabel("P (mW)")
        self.battery_ax.set_ylabel("Battery (V)")
        self.battery_ax.set_xlabel("Time since boot (s)")
        self.charging_current_ax.set_ylim(0, 200)
        self.charging_current_ax.set_yticks([0, 50, 100, 150, 200])
        self.charging_power_ax.set_ylim(0, 800)
        self.charging_power_ax.set_yticks([0, 200, 400, 600, 800])
        self.battery_ax.set_ylim(0, 4.0)
        self.battery_ax.set_yticks([0, 2, 4])
        self.charging_current_line, = self.charging_current_ax.plot(
            [], [], color="tab:green", drawstyle="steps-post")
        self.charging_power_line, = self.charging_power_ax.plot(
            [], [], color="tab:red", drawstyle="steps-post")
        self.battery_line, = self.battery_ax.plot([], [], color="tab:blue")
        for axis in (self.charging_current_ax, self.charging_power_ax, self.battery_ax):
            axis.margins(y=0.1)
            axis.grid(alpha=0.2)
        charging_fig.tight_layout()
        self.charging_canvas = FigureCanvasTkAgg(charging_fig, master=plot_frame)
        self.charging_canvas.get_tk_widget().grid(row=1, column=1, sticky="nsew")
        self._plot_axes = (
            self.imu_ax, self.stab_ax, self.mech_ax, self.mech_ax2,
            self.charging_current_ax, self.charging_power_ax, self.battery_ax,
        )
        self._plot_lines = (
            self.imu_line1, self.imu_line2, self.stab_line_pitch, self.stab_line_roll,
            self.mech_line_dpitch, self.mech_line_droll, self.mech_line_rpm,
            self.charging_current_line, self.charging_power_line, self.battery_line,
        )
        self._display_vars = (
            self.sats_var, self.lat_var, self.lon_var, self.press_var, self.hum_var,
            self.temp_var, self.current_var, self.battery_var, self.rpm_var,
            self.peak_var, self.charge_var, self.i2t_var, self.iavg_var,
            self.irms_var, self.power_var, self.window_var, self.drops_var,
        )
        self._set_time_limits(0)

        # Kick off the update loop
        self._update_job = root.after(100, self.update)

    # -----------------------------------------------------------------------
    def _set_time_limits(self, latest):
        end = max(self.DISPLAY_SECONDS, latest)
        for axis in self._plot_axes:
            axis.set_xlim(end - self.DISPLAY_SECONDS, end)

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.config(text="Resume" if self.paused else "Pause")
        if self.paused:
            self._frozen_view = (
                [(list(line.get_xdata()), list(line.get_ydata())) for line in self._plot_lines],
                [axis.get_xlim() for axis in self._plot_axes],
                [variable.get() for variable in self._display_vars],
                (self.sd_status_label.cget("text"), self.sd_status_label.cget("bg")),
            )
        else:
            self._frozen_view = None
            self._refresh_live_plots()
            if self._live_display_values is not None:
                values, sd_status = self._live_display_values
                for variable, value in zip(self._display_vars, values):
                    variable.set(value)
                self.sd_status_label.config(text=sd_status[0], bg=sd_status[1])

    def _refresh_live_plots(self):
        datasets = (
            (self.time_data, self.pitch_data), (self.time_data, self.roll_data),
            (self.time_data, self.stab_pitch_data), (self.time_data, self.stab_roll_data),
            (self.time_data, self.diff_pitch_data), (self.time_data, self.diff_roll_data),
            (self.rpm_time_data, self.rpm_data),
            (self.charging_time_data, self.charging_current_data),
            (self.charging_time_data, self.charging_power_data),
            (self.battery_time_data, self.battery_voltage_data),
        )
        for line, (times, values) in zip(self._plot_lines, datasets):
            line.set_data(times, values)
        latest = max((times[-1] for times, _ in datasets if times), default=0)
        self._set_time_limits(latest)
        for canvas in (self.imu_canvas, self.stab_canvas, self.mech_canvas, self.charging_canvas):
            canvas.draw_idle()

    def save_snapshot(self):
        try:
            directory = Path(__file__).resolve().parent / "snapshots"
            directory.mkdir(exist_ok=True)
            destination = directory / (datetime.now().strftime("vertisea_%Y%m%d_%H%M%S_%f") + ".png")
            self.root.update_idletasks()
            left, top = self.root.winfo_rootx(), self.root.winfo_rooty()
            bounds = (left, top, left + self.root.winfo_width(), top + self.root.winfo_height())
            if os.name == "nt":
                user32 = ctypes.windll.user32
                rectangle = wintypes.RECT()
                user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
                previous_context = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
                try:
                    if user32.GetWindowRect(self.root.winfo_id(), ctypes.byref(rectangle)):
                        bounds = (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom)
                finally:
                    if previous_context:
                        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous_context))
            image = ImageGrab.grab(
                bbox=bounds,
                all_screens=True,
            )
            image.save(destination)
            self.conn_status_var.set(f"Snapshot: {destination.name}")
            return destination
        except (OSError, RuntimeError) as error:
            messagebox.showerror("Snapshot failed", str(error))
            return None

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
            "BENCH SESSION (live IMU over USB, no SD card, nothing being logged)?\n"
            "Then this is the right port — click OK. It needs firmware built with "
            "TELEM_ENABLE 1, USB_TELEM 1 and USB_DEBUG 0, from 2026-09-12 or later "
            "(older builds halt in setup() when no card is present and never send "
            "anything).\n\n"
            "LOGGING RUN in progress? Then Cancel:\n\n"
            "1. Opening this port can RESET the board. The CH340E RTS line drives the "
            "Artemis reset pin. This program holds RTS/DTR low, but the Windows CH340 "
            "driver still changes the line state on open and on close, and a reset "
            "pulse can get through — restarting millis(), starting a new file, and "
            "holding the LED solid while setup() runs.\n\n"
            "2. Unless the firmware was built with USB_TELEM 1 and USB_DEBUG 0, this "
            "port carries debug TEXT, not telemetry packets — every field reads N/A "
            "no matter how long you wait.\n\n"
            "For a logging run, connect to the RFD900x modem, or use \"Load BIN File\" "
            "to read the SD log with no serial connection at all.")

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
            self._telemetry_parser = TelemetryParser()
            self._timestamp_clock = TimestampClock()
            self._previous_current_stats = None
            self._latest_battery_time = None
            self._latest_battery_v = None
            self._latest_i_avg_mA = None
            self.conn_status_var.set(f"Connected: {port}")
            self._start_recording(port)
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
        self._close_recording()
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass  # the device may already be gone; nothing useful to do about it
            self.ser = None

    def _recording_failed(self, error):
        self.recording_error = str(error)
        self.conn_status_var.set(f"RECORDING ERROR: {error}")
        messagebox.showerror("Live recording failed", str(error), parent=self.root)

    def _start_recording(self, port):
        self.recording_error = None
        destination = self.session_directory / (
            datetime.now().strftime("live_%Y%m%d_%H%M%S_%f") + ".h5")
        try:
            self.recorder = LiveRecorder(destination, port)
            self.conn_status_var.set(f"Connected: {port}; recording {destination.name}")
        except Exception as error:
            self.recorder = None
            self._recording_failed(error)

    def _close_recording(self, reason="serial_closed"):
        recorder, self.recorder = self.recorder, None
        if recorder is not None:
            try:
                recorder.close(reason)
            except Exception as error:
                self._recording_failed(error)

    def disconnect_serial(self):
        self._close_serial()
        if not self.recording_error:
            self.conn_status_var.set("Not connected")

    def close_window(self):
        self._closing = True
        if self._update_job is not None:
            self.root.after_cancel(self._update_job)
            self._update_job = None
        self._close_serial()
        self.root.destroy()

    def _on_link_lost(self, exc: Exception):
        """Handle the serial link disappearing mid-session (unplugged modem, driver reset).

        The GUI must keep running: a frozen-but-alive window is indistinguishable from a
        quiet sea state, which is the worst possible failure mode during a deployment.
        """
        self._close_recording("link_lost: " + str(exc))
        self._close_serial()
        self._set_sd_status(False)
        self.sd_status_label.config(text=" LINK LOST ", bg="red")
        self.conn_status_var.set(f"Disconnected: {type(exc).__name__}" +
                     (f"; RECORDING ERROR: {self.recording_error}" if self.recording_error else ""))

    def _monotonic_seconds(self, ts10: int) -> float:
        """Unwrap ts10 while retaining small out-of-order native timestamps."""
        return self._timestamp_clock.seconds(ts10)

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
        """Import a single SD BIN to HDF5; CSV export remains a protocol API/CLI."""
        bin_path = filedialog.askopenfilename(
            title="Select VertiSea SD binary log",
            filetypes=[("Binary log", "*.BIN *.bin"), ("All files", "*.*")]
        )
        if not bin_path:
            return  # user cancelled

        result = self._import_sources([bin_path])
        if result is not None:
            messagebox.showinfo("Session imported", self._session_summary(result), parent=self.root)
        return result

    @staticmethod
    def _session_summary(result):
        summary = result["summary"]
        lines = [f"HDF5: {result['output']}", f"Sources: {len(result['sources'])}",
                 f"Measured energy: {summary['gross_energy_mJ']:.6g} mJ",
                 f"Energy coverage: {summary['coverage_fraction']:.1%}",
                 f"Cycles: {len(result['cycles'])}"]
        if result["warnings"]:
            lines.append("Warnings:\n" + "\n".join(result["warnings"]))
        return "\n".join(lines)

    def _import_sources(self, sources, cycle_start=None, cycle_end=None):
        from vertisea_session import import_session
        output = filedialog.asksaveasfilename(
            title="HDF5 session output", defaultextension=".h5", initialdir=str(self.session_directory),
            initialfile="session.h5", filetypes=[("HDF5 session", "*.h5 *.hdf5")], parent=self.root)
        if not output:
            return None
        destination = Path(output).resolve()
        if self.recorder is not None and destination == self.recorder.path:
            messagebox.showerror("Output in use", "Cannot replace the active live recording.", parent=self.root)
            return None
        if destination.exists() and not messagebox.askyesno(
                "Replace session?", f"Overwrite {destination}?", parent=self.root):
            return None
        try:
            result = import_session(sources, output, cycle_start=cycle_start, cycle_end=cycle_end)
        except Exception as error:
            messagebox.showerror("Session import failed", str(error), parent=self.root)
            return None
        self._last_import_sources = [source["path"] for source in result["sources"]]
        self._last_session_path = result["output"]
        self.conn_status_var.set(f"Imported: {destination.name}")
        return result

    def import_session_dialog(self):
        sources = filedialog.askopenfilenames(
            title="Select ordered VertiSea BIN files", filetypes=[("Binary log", "*.BIN *.bin")],
            parent=self.root)
        if not sources:
            directory = filedialog.askdirectory(title="Select BIN directory", parent=self.root)
            if not directory:
                return None
            sources = [directory]
        result = self._import_sources(sources)
        if result is not None:
            messagebox.showinfo("Session imported", self._session_summary(result), parent=self.root)
        return result

    def data_explorer_dialog(self):
        from vertisea_explorer import open_explorer
        previous = Path(self._last_session_path) if self._last_session_path else None
        path = filedialog.askopenfilename(
            title="Open HDF5 Data Explorer", parent=self.root,
            initialdir=str(previous.parent if previous else self.session_directory),
            initialfile=previous.name if previous else "session.h5",
            filetypes=[("HDF5 session", "*.h5 *.hdf5")])
        if not path:
            return None
        window = open_explorer(self.root, path,
                               active_path=self.recorder.path if self.recorder is not None else None)
        if window is not None:
            self._last_session_path = str(Path(path).resolve())
        return window

    def analyze_cycle_dialog(self):
        if not self._last_import_sources:
            messagebox.showwarning("No imported session", "Import an SD BIN session first.", parent=self.root)
            return None
        start = simpledialog.askfloat("Cycle start", "Start (native boot seconds):", parent=self.root)
        if start is None:
            return None
        end = simpledialog.askfloat("Cycle end", "End (native boot seconds):", parent=self.root)
        if end is None:
            return None
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            messagebox.showerror("Invalid cycle", "Enter finite start < end seconds.", parent=self.root)
            return None
        result = self._import_sources(self._last_import_sources, start, end)
        if result is None:
            return None
        lines = [self._session_summary(result)]
        for cycle in result["cycles"]:
            lines.append(f"Cycle {cycle['cycle_id']} / source {cycle['segment_id']}: "
                         f"{cycle['gross_energy_mJ']:.6g} mJ; "
                         f"coverage {cycle['coverage_fraction']:.1%}; flags {cycle['flags']}")
        messagebox.showinfo("Cycle analysis", "\n".join(lines), parent=self.root)
        if result["cycles"]:
            self._show_cycle_figure(result)
        return result

    def _show_cycle_figure(self, result):
        import h5py
        try:
            with h5py.File(result["output"], "r") as archive:
                rows = [json.loads(value) for value in archive["derived/charging/records_json"].asstr()[:]]
                battery = {
                    "calibration": [json.loads(value) for value in archive["meta/battery_cal/records_json"].asstr()[:]],
                    "policy": str(archive["meta"].attrs["calibration_policy"]),
                    "chemistry": "not inferred; see source deployment metadata",
                }
            figure = Figure(figsize=(9, 7))
            axes = figure.subplots(3, 1, sharex=True)
            export_metadata = {"cycles": result["cycles"], "battery": battery,
                               "sources": result["sources"], "warnings": result["warnings"],
                               "rows": []}
            for cycle in result["cycles"]:
                selected = [row for row in rows if row["boot_id"] == cycle["boot_id"]
                            and row["segment_id"] == cycle["segment_id"]
                            and cycle["start_ms"] <= row["ts_ms"] <= cycle["end_ms"]]
                export_metadata["rows"].extend(selected)
                times = [row["ts_ms"] / 1000 for row in selected]
                energy = 0.0
                energies = []
                for index, row in enumerate(selected):
                    if index and row["interval_valid"]:
                        energy += row["energy_increment_mJ"]
                    energies.append(energy if row["interval_valid"] else math.nan)
                label = f"Cycle {cycle['cycle_id']}, source {cycle['segment_id']}"
                for axis, values in zip(axes, ([row["current_mA"] for row in selected],
                                               [row["power_mW"] for row in selected], energies)):
                    axis.plot(times, values, label=label)
            for axis, label in zip(axes, ("I (mA)", "P (mW)", "Measured E (mJ)")):
                axis.set_ylabel(label)
                axis.grid(alpha=0.2)
                axis.legend(fontsize=8)
            axes[-1].set_xlabel("Native boot time (s)")
            figure.suptitle("Battery-side cycle analysis")
            figure.tight_layout()
            window = tk.Toplevel(self.root)
            window.title("Cycle analysis")
            canvas = FigureCanvasTkAgg(figure, master=window)
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            canvas.draw()
            window.cycle_canvas = canvas
            tk.Label(window, text=f"Battery calibration records: {len(battery['calibration'])}; "
                     f"cycle flags: {[cycle['flags'] for cycle in result['cycles']]}").pack()
            tk.Button(window, text="Export Figure", command=lambda: self._export_cycle_figure(
                figure, export_metadata)).pack()
        except Exception as error:
            messagebox.showerror("Cycle plot failed", str(error), parent=self.root)

    def _export_cycle_figure(self, figure, metadata):
        output = filedialog.asksaveasfilename(title="Export cycle figure", defaultextension=".png",
                                             filetypes=[("PNG image", "*.png")], parent=self.root)
        if not output:
            return None
        try:
            figure.savefig(output, dpi=180, metadata={
                "Description": json.dumps(metadata, ensure_ascii=True, allow_nan=True)})
            return output
        except Exception as error:
            messagebox.showerror("Figure export failed", str(error), parent=self.root)
            return None

    def _plot_current_interval(self, timestamp, window_s, charge_mC, integ_s, n_samples,
                               i2t_mA2s=math.nan):
        previous = self._previous_current_stats
        current = dict(timestamp=timestamp, window_s=window_s, charge_mC=charge_mC,
                       integ_s=integ_s, n_samples=n_samples, i2t_mA2s=i2t_mA2s)
        result = current_interval_stats(previous, current, self._latest_battery_v,
                                        self._latest_battery_time)
        if previous is None or timestamp > previous["timestamp"]:
            self._previous_current_stats = current
        if previous is None:
            return
        self.charging_time_data.append(timestamp)
        self.charging_current_data.append(result["current_mA"])
        self.charging_power_data.append(result["power_mW"])
        self.charging_current_line.set_data(self.charging_time_data, self.charging_current_data)
        self.charging_power_line.set_data(self.charging_time_data, self.charging_power_data)
        for axis in (self.charging_current_ax, self.charging_power_ax):
            axis.relim()
            axis.autoscale_view()

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
            if not self._closing:
                self._update_job = self.root.after(100, self.update)

    def _update_once(self):
        if self.paused and self._live_display_values is not None:
            values, sd_status = self._live_display_values
            for variable, value in zip(self._display_vars, values):
                variable.set(value)
            self.sd_status_label.config(text=sd_status[0], bg=sd_status[1])
        # Read all available bytes from the serial port
        if self.ser and self.ser.in_waiting:
            chunk = self.ser.read(self.ser.in_waiting)
            if self.recorder is not None:
                try:
                    self.recorder.feed(chunk)
                except Exception as error:
                    self._close_recording("recording_error")
                    self._recording_failed(error)
            self.buffer.extend(chunk)

        # Canvases touched this tick. Drawing is deferred until the buffer is fully
        # drained: a matplotlib draw() costs tens of milliseconds, and doing three of
        # them per packet inside the loop meant redraw time could exceed the packet
        # arrival interval, so the backlog grew and the GUI stalled. (Issue 48)
        dirty = set()

        # Parse packets — consume as many complete packets as possible
        records = self._telemetry_parser.feed(bytes(self.buffer))
        self.buffer.clear()
        for record in records:
            p = record["packet_type"]
            t = record["timestamp"]

            # ---- TYPE_TELEM_IMU (0x06) — 13 bytes -------------------------
            # Payload: uint16 ts10,
            #          int16 fix_pitch_cdeg, int16 fix_roll_cdeg,  (centidegrees ×100)
            #          int16 vertDisp_mm,
            #          int16 stab_pitch_cdeg, int16 stab_roll_cdeg (centidegrees ×100)
            # Angle scale ×100 supports ±327.67° without int16 overflow.
            if p == TYPE_TELEM_IMU:
                pitch = record["pitch"]
                roll = record["roll"]
                disp = record["displacement_m"]
                stab_pitch = record["stab_pitch"]
                stab_roll = record["stab_roll"]
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
                self.mech_ax.autoscale_view()
                dirty.update((self.imu_canvas, self.stab_canvas, self.mech_canvas))
                continue

            # ---- TYPE_GPS (0x04) — 12 bytes (radio format) -----------------
            # Payload: uint16 ts10, uint8 sats, float lat, float lon
            elif p == TYPE_GPS:
                sats, lat, lon = record["satellites"], record["latitude"], record["longitude"]
                self.sats_var.set(str(sats))
                self.lat_var.set(f"{lat:.6f}")
                self.lon_var.set(f"{lon:.6f}")
                continue

            # ---- TYPE_BME (0x03) — 15 bytes (radio format) -----------------
            # Payload: uint16 ts10, float pressure (Pa), float humidity (%), float temp (°C)
            elif p == TYPE_BME:
                pres, hum, tmp = record["pressure"], record["humidity"], record["temperature"]
                self.press_var.set(f"{pres/100.0:.1f} hPa")
                self.hum_var.set(f"{hum:.1f} %")
                self.temp_var.set(f"{tmp:.1f} °C")
                continue

            # ---- TYPE_CURRENT_STATS (0x0F) — 27 bytes (radio format) -------
            # Payload: uint16 ts10, uint16 window_s, uint16 peak_mA,
            #          float charge_mC, float i2t_mA2s, float integ_s,
            #          uint32 n_samples, uint32 n_dropped
            elif p == TYPE_CURRENT_STATS:
                window_s, peak_mA = record["window_s"], record["peak_mA"]
                charge_mC, i2t_mA2s, integ_s = record["charge_mC"], record["i2t_mA2s"], record["integ_s"]
                n_samples, n_dropped = record["n_samples"], record["n_dropped"]

                self._plot_current_interval(
                    t, window_s, charge_mC, integ_s, n_samples, i2t_mA2s)
                dirty.add(self.charging_canvas)
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
                    if (self._latest_battery_v is not None and self._latest_battery_time is not None
                            and 0 <= t - self._latest_battery_time <= 2.5):
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
                if self._latest_battery_time is not None and t < self._latest_battery_time:
                    continue
                self._latest_battery_v = record["voltage_V"]
                self._latest_battery_time = t
                self.battery_time_data.append(self._latest_battery_time)
                self.battery_voltage_data.append(self._latest_battery_v)
                self.battery_line.set_data(self.battery_time_data, self.battery_voltage_data)
                self.battery_ax.relim()
                self.battery_ax.autoscale_view()
                dirty.add(self.charging_canvas)
                self.battery_var.set(f"{self._latest_battery_v:.3f} V")
                if (self._latest_i_avg_mA is not None and self._previous_current_stats is not None
                    and 0 <= t - self._previous_current_stats["timestamp"] <= 2.5):
                    self.power_var.set(
                        f"{self._latest_battery_v * self._latest_i_avg_mA:.3f} mW")
                continue

            # ---- TYPE_RPM (0x0C) — 5 bytes (radio format) ------------------
            # Payload: uint16 ts10, uint16 rpm
            elif p == TYPE_RPM:
                rpm = record["rpm"]
                self.rpm_var.set(f"{rpm} RPM")
                # Same wrap counter as every other ts10-bearing packet (Issue 49)
                self.rpm_time_data.append(t)
                self.rpm_data.append(rpm)
                # Update third plot — RPM (right axis)
                self.mech_line_rpm.set_data(self.rpm_time_data, self.rpm_data)
                self.mech_ax2.relim()
                self.mech_ax2.autoscale_view()
                dirty.add(self.mech_canvas)
                continue

            # ---- TYPE_STATUS (0x0B) — 4 bytes (radio only) -----------------
            # Payload: uint16 ts10, uint8 flags
            #   flags bit 0 = sdError (0=OK, 1=SD write failure)
            elif p == TYPE_STATUS:
                sd_ok = record["sd_ok"]
                self._set_sd_status(sd_ok)
                continue

        # One repaint per canvas per tick, after the buffer is drained. draw_idle() lets
        # Tk coalesce repaints instead of blocking here. (Issue 48)
        if self.paused:
            self._live_display_values = (
                [variable.get() for variable in self._display_vars],
                (self.sd_status_label.cget("text"), self.sd_status_label.cget("bg")),
            )
            line_data, limits, values, sd_status = self._frozen_view
            for line, (times, samples) in zip(self._plot_lines, line_data):
                line.set_data(times, samples)
            for axis, limit in zip(self._plot_axes, limits):
                axis.set_xlim(limit)
            for variable, value in zip(self._display_vars, values):
                variable.set(value)
            self.sd_status_label.config(text=sd_status[0], bg=sd_status[1])
        elif dirty:
            self._refresh_live_plots()


if __name__ == "__main__":
    root = tk.Tk()
    app = VertiSeaGUI(root)
    root.mainloop()
