# Telemetry Ground Station — vertisea_plot_v7.py

> **Status:** Active development
> **Source file(s):** [`vertisea_plot_v7.py`](../vertisea_plot_v7.py)
> **Last reviewed:** 2026-08-18

## Purpose

A Python/Tkinter desktop application that receives binary telemetry packets from the
VertiSea buoy over a serial port connected to the ground-side RFD900x modem. It displays
live GPS position, BME280 environmental data, system status, and rolling plots of IMU
attitude, tilt difference, and rotor RPM. It also parses SD binary log files and exports
CSVs. It does **not** log live telemetry to disk — all persistent logging is done by the
firmware to the SD card.

---

## Dependencies

| Package | Why it is needed |
|---------|-----------------|
| `tkinter` (stdlib) | GUI framework — window, labels, buttons, frames |
| `matplotlib` | Rolling plot figures embedded in the Tkinter window |
| `pyserial` | Serial port enumeration and reading |
| `collections.deque` | Fixed-length rolling buffers for plot data |
| `struct` | Binary packet unpacking |

Install non-stdlib dependencies: `pip install pyserial matplotlib`

---

## Running the Script

```
python vertisea_plot_v7.py
```

### Radio link (normal field use)

1. Connect the ground-side RFD900x modem to the laptop via USB.
2. Select the COM port for the RFD900x modem from the dropdown.
3. Click **Connect**. The port opens at **115200 baud**.
4. Data begins populating as packets arrive.

### USB direct (bench / `USB_TELEM` mode)

> **Transport status (2026-09-03).** The **USB path is confirmed working** — this is the
> committed configuration (`USB_TELEM 1`, `TELEM_ENABLE 1`) and packets reach the GUI. The
> **RFD900 radio path has not been tested recently.** Because the packet layouts are identical
> on both transports, a radio problem would show up as byte loss or silence rather than as
> mis-decoded fields — the byte-scan parser is designed for exactly that, but it has not been
> re-verified against a live radio link.

When the firmware is flashed with `USB_TELEM 1` **and `USB_DEBUG 0`**, telemetry packets
are sent over the buoy's USB connection instead of the radio link. In this mode:

1. Connect the buoy directly to the laptop via USB.
2. Select the buoy's USB COM port from the dropdown.
3. Click **Connect**. The port opens at **115200 baud**.
4. Data begins populating as packets arrive — no RFD900x modems required.

> **Note:** `USB_DEBUG` takes priority over `USB_TELEM`, but **not** in favour of USB.
> When `USB_DEBUG 1`, telemetry goes to `Serial1` (radio) so that USB stays text-only.
> Setting both flags to `1` leaves `Serial1` uninitialised and telemetry is lost
> entirely — see the flag-combination caution in
> [`docs/firmware.md`](firmware.md). Use `USB_DEBUG 0` + `USB_TELEM 1` for USB telemetry.

---

## GUI Layout

```
┌───────────────────────────────────────────────────────────────────┐
│  COM Port: [dropdown]  [Refresh]  [Connect]  [Load BIN File]       │
├──────────────────┬──────────────────┬─────────────────────────────┤
│  GPS             │  BME280          │  System Status               │
│  Sats: N/A       │  Pressure: N/A   │  SD Card: [ SD: OK ]         │
│  Lat:  N/A       │  Humidity: N/A   │  Supercap: N/A               │
│  Lon:  N/A       │  Temp:     N/A   │  RPM:      N/A               │
├──────────────────┴──────────────────┴─────────────────────────────┤
│  [Rolling plot: Pendulum IMU pitch & roll — 100 samples]           │
├──────────────────────────────────┬────────────────────────────────┤
│  [Rolling dual-Y plot:           │  [ Future Plot ]               │
│   Pendulum−buoy tilt diff & RPM] │                                │
├──────────────────────────────────┴────────────────────────────────┤
│  [Rolling plot: Buoy IMU pitch & roll — 100 samples]               │
└───────────────────────────────────────────────────────────────────┘
```

---

## Packet Parsing

### Architecture

The parser is **frameless and byte-scanning**. There is no sync byte. The `update()`
method (called every 100 ms via `root.after`) reads all available bytes from the serial
port into `self.buffer` (a `bytearray`), then loops:

1. Inspect `buffer[0]` (the candidate type byte).
2. If it matches a known type **and** enough bytes are available for that packet, slice
   and unpack the packet, then `del buffer[:n]`.
3. Otherwise, drop one byte (`del buffer[0]`) and continue.

This design tolerates byte loss on the radio link without requiring a reset or
re-synchronisation signal.

### Parsed Packet Types

| Type byte | Struct format | Size | Fields extracted |
|-----------|--------------|------|-----------------|
| `0x06` (`TYPE_TELEM_IMU`) | `<BHhhhhh` | 13 bytes | type, ts10, fix_pitch_cdeg, fix_roll_cdeg, vertDisp_mm, stab_pitch_cdeg, stab_roll_cdeg |
| `0x04` (`TYPE_GPS`) | `<BHBff` | 12 bytes | type, ts10, sats, lat, lon |
| `0x03` (`TYPE_BME`) | `<BHfff` | 15 bytes | type, ts10, pressure, humidity, temperature |
| ~~`0x0A`~~ | — | — | **RETIRED 2026-09-03.** Was `TYPE_SUPERCAP` (voltage_mV), renamed `TYPE_CURRENT` (current_mA), then removed. The radio branch is deleted; the SD read path is kept for legacy logs. |
| `0x0F` (`TYPE_CURRENT_STATS`) | `<BHHHfffII` | 27 bytes | type, ts10, window_s, peak_mA, charge_mC, i2t_mA2s, integ_s, n_samples, n_dropped |
| `0x0B` (`TYPE_STATUS`) | `<BHB` | 4 bytes | type, ts10, flags (bit 0 = SD error) |
| `0x0C` (`TYPE_RPM`) | `<BHH` | 5 bytes | type, ts10, rpm (RPM_ENABLE=1 only) |

Angle fields use **centidegree** encoding (×100); divide by 100.0 to recover degrees.
Range: ±327.67°. `vertDisp_mm` uses ×1000 (mm); divide by 1000.0 for metres.

### Not Parsed

- All SD-only packet types (`0x01`, `0x02`, `0x05`, `0x07`, `0x08`, `0x09`) are never
  transmitted over radio and will never appear in the serial buffer.
- `TYPE_RPM` (`0x0C`) is only present when `RPM_ENABLE=1` is compiled into the firmware.

---

## Internal Design

### Data Structures

| Variable | Type | Description |
|----------|------|-------------|
| `self.buffer` | `bytearray` | Accumulates incoming serial bytes between `update()` calls |
| `self.ser` | `serial.Serial` or `None` | Active serial connection; `None` if not connected |
| `self.time_data` | `deque(maxlen=100)` | Timestamps (seconds) for rolling plots — updated by `TYPE_TELEM_IMU` |
| `self.pitch_data` | `deque(maxlen=100)` | Pendulum IMU pitch (degrees) from `TYPE_TELEM_IMU` |
| `self.roll_data` | `deque(maxlen=100)` | Pendulum IMU roll (degrees) from `TYPE_TELEM_IMU` |
| `self.disp_data` | `deque(maxlen=100)` | Vertical displacement (metres) from `TYPE_TELEM_IMU` |
| `self.stab_pitch_data` | `deque(maxlen=100)` | Buoy IMU pitch (degrees) from `TYPE_TELEM_IMU` |
| `self.stab_roll_data` | `deque(maxlen=100)` | Buoy IMU roll (degrees) from `TYPE_TELEM_IMU` |
| `self.diff_pitch_data` | `deque(maxlen=100)` | `pendulum_pitch − buoy_pitch` (°) — computed from `TYPE_TELEM_IMU` |
| `self.diff_roll_data` | `deque(maxlen=100)` | `pendulum_roll − buoy_roll` (°) — computed from `TYPE_TELEM_IMU` |
| `self.rpm_time_data` | `deque(maxlen=100)` | Timestamps (seconds) for RPM plot — updated by `TYPE_RPM` |
| `self.rpm_data` | `deque(maxlen=100)` | Rotor RPM from `TYPE_RPM` packets |
| `self.sats_var` | `tk.StringVar` | GPS satellite count display |
| `self.lat_var` | `tk.StringVar` | GPS latitude display |
| `self.lon_var` | `tk.StringVar` | GPS longitude display |
| `self.press_var` | `tk.StringVar` | BME280 pressure display |
| `self.hum_var` | `tk.StringVar` | BME280 humidity display |
| `self.temp_var` | `tk.StringVar` | BME280 temperature display |
| `self.supercap_var` | `tk.StringVar` | Supercapacitor voltage display |
| `self.rpm_var` | `tk.StringVar` | Rotor RPM numeric display (System Status panel) |

### Key Flows

**Connecting to the modem:**
1. User selects COM port and clicks Connect.
2. `connect_serial()` opens `serial.Serial(port, 115200, timeout=0.1)`.
3. `self.buffer` is reset to empty `bytearray()`.

**Update loop (every 100 ms):**
1. If `self.ser` is open and bytes are waiting, read all available bytes into `self.buffer`.
2. Parse loop: scan `buffer[0]`, match type, unpack if enough bytes present, update GUI
   variables and plot data, delete consumed bytes.
3. After parsing, reschedule via `root.after(100, self.update)`.

**Plot update:**
- All four plots have **fixed y-axis limits** set at initialisation:
  - Pendulum IMU pitch & roll: `set_ylim(-60, 60)` (°)
  - Buoy IMU pitch & roll: `set_ylim(-60, 60)` (°)
  - Mechanical input left axis (tilt difference): `set_ylim(-60, 60)` (°)
  - Mechanical input right axis (RPM): `set_ylim(0, 450)` RPM
- Live telemetry calls `relim()` + `autoscale_view(scaley=False)` on the mechanical-input
  axes so the **x-axis scrolls** with incoming data while the y-axis stays locked.
- The pendulum and buoy IMU axes also call `relim()` + `autoscale_view()` (y-axis free)
  so they expand if attitude exceeds ±60°.
- BIN-file load calls `autoscale_view()` and scales to the data range.
- `FigureCanvasTkAgg.draw()` redraws the canvas after each packet that updates plot data.
- Pendulum and buoy IMU plots are redrawn on each `TYPE_TELEM_IMU` packet (5 Hz radio / 10 Hz USB).
- Mechanical input (dual-Y) plot left axis is redrawn on `TYPE_TELEM_IMU`; right axis on `TYPE_RPM`.

**Top-right plot — "Mechanical Input: IMU Tilt Difference & Rotor RPM":**
- **Left Y-axis (red/orange):** `pendulum_pitch − buoy_pitch` and `pendulum_roll − buoy_roll` in
  degrees. Represents the relative tilt between the pendulum IMU and the
  buoy IMU — the mechanical energy input driving the TENG rotor.
- **Right Y-axis (blue):** Rotor RPM from `TYPE_RPM` packets (`RPM_ENABLE=1` only).
  When `RPM_ENABLE=0`, the RPM line is empty but the tilt-difference lines still work.
- Both axes use the `ts10` monotonic time base (with rollover compensation).

---

## Known Constraints and Gotchas

- **USB_TELEM mode:** when `USB_TELEM 1` is set in the firmware, the buoy's USB port
  carries binary telemetry packets (not human-readable text). Connecting the Arduino
  Serial Monitor while `USB_TELEM 1` is active will show garbled output — use the
  Python GUI instead. In this mode `TELEMETRY_RATE_HZ` is 10 Hz instead of 5 Hz.
- The rolling buffer size is fixed at `maxlen=100`. At 5 Hz telemetry this is 20 s of
  history; at 10 Hz (USB) it is 10 s. Change `maxlen` to adjust the visible window.
- **RPM plot time base:** `TYPE_RPM` packets reuse `self._ts10_offset`, which is only
  advanced by the `TYPE_TELEM_IMU` handler. If an RPM packet arrives between an IMU
  packet's rollover and the next IMU packet, its x-position can be off by one wrap
  (655.36 s) until the offset catches up. Harmless in practice at current rates.
- `root.after(100, self.update)` is rescheduled at the **end** of `update()`, not at a
  fixed interval. If parsing takes longer than 100 ms, the effective update rate drops.
  In practice this is not an issue at 115200 baud with small packets.
- Port enumeration (`serial.tools.list_ports.comports()`) runs at startup and on
  Refresh. It does not auto-detect new devices.
- There is no disconnect button. Closing the window terminates the process.

## Rejected Approaches

- **Framing with sync bytes** — not implemented because the firmware does not use them.
  The byte-scan approach is sufficient for the radio link quality.
- **Logging live telemetry to CSV** — rejected; all logging is the firmware's
  responsibility. The ground station is display-only for live data. SD binary logs can
  be parsed to CSV via the "Load BIN File" button.
- **Asyncio / threading for serial reads** — rejected in favour of the simpler
  `root.after` polling approach, which is adequate at 115200 baud.

## Open Issues / To-Do

- See [`IDENTIFIED_ISSUES.md`](../IDENTIFIED_ISSUES.md) for the full list.
- Consider adding a disconnect button and port status indicator.
