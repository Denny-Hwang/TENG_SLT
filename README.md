# VertiSea

Wave-energy buoy data-acquisition and telemetry system — Arctic TENG project, PNNL.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Hardware](#2-hardware)
3. [Prerequisites](#3-prerequisites)
4. [Firmware — Flashing the Buoy](#4-firmware--flashing-the-buoy)
5. [Ground Station — Live Telemetry Display](#5-ground-station--live-telemetry-display)
6. [Post-Deployment Data Processing](#6-post-deployment-data-processing)
7. [Magnetometer Calibration](#7-magnetometer-calibration)
8. [Output Files Reference](#8-output-files-reference)
9. [Things That Are Easy to Forget](#9-things-that-are-easy-to-forget)
10. [Quick Reference](#10-quick-reference)
11. [Appendix — Developer and Maintainer Notes](#11-appendix--developer-and-maintainer-notes)

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                  BUOY (SparkFun RedBoard Artemis Nano)          │
│                                                                 │
│  ISM330DHCX (fixed)  ──┐                                        │
│  ISM330DHCX (stab)   ──┤                                        │
│  MMC5983MA (mag)     ──┤── Madgwick AHRS ──► Binary packets     │
│  BME280 (env)        ──┤                         │              │
│  u-blox GNSS         ──┤                         ├──► SD card   │
│  RV8803 RTC          ──┘                         │   (.BIN)     │
│                                                  └──► Serial1   │
└──────────────────────────────────────────────────────┬──────────┘
                                                       │ 115200 baud
                                                   RFD900x modem
                                                       │
                                                  RFD900x modem
                                                       │
                                          ┌────────────▼──────────┐
                                          │  Laptop (Python GUI)  │
                                          │  vertisea_plot_v7.py  │
                                          └───────────────────────┘
```

The buoy logs all sensor data to an SD card in a compact binary format at up to 104 Hz.
A subset of data is simultaneously transmitted over a pair of RFD900x 900 MHz radio
modems to a laptop running the Python ground-station display.

After retrieval, the SD card binary file is parsed offline with MATLAB into CSV files
for analysis.

---

## 2. Hardware

| Component | Part | Interface |
|-----------|------|-----------|
| Microcontroller | SparkFun RedBoard Artemis Nano | — |
| Fixed IMU | SparkFun ISM330DHCX | I²C @ 0x6A |
| Stabilized IMU | SparkFun ISM330DHCX | I²C @ 0x6B |
| Magnetometer | SparkFun MMC5983MA | I²C (on stabilized IMU board) |
| Environmental | SparkFun BME280 | I²C |
| GNSS | SparkFun u-blox (ZED-F9P or similar) | I²C |
| RTC | SparkFun RV8803 | I²C |
| Storage | microSD card | SPI (CS = pin 4) |
| Radio | RFD900x × 2 | Serial1 @ 115200 baud |
| Supercap monitor | Resistor divider (30 kΩ / 7.5 kΩ) | ADC pin A14 |

---

## 3. Prerequisites

### Firmware (Arduino IDE)

Install the following libraries via the Arduino Library Manager:

- SparkFun BME280
- SparkFun RV8803 RTC
- SparkFun u-blox GNSS Arduino Library
- SparkFun ISM330DHCX
- SparkFun MMC5983MA Arduino Library
- MadgwickAHRS (by x-io Technologies)
- SD (built-in)
- Wire, SPI (built-in)

Board: **SparkFun RedBoard Artemis Nano** (install the SparkFun Apollo3 boards package via the Arduino Boards Manager: `https://raw.githubusercontent.com/sparkfun/Arduino_Apollo3/main/package_sparkfun_apollo3_index.json`)

### Ground Station (Python)

```
pip install pyserial matplotlib
```

Python 3.8 or later. `tkinter` is included with standard Python distributions.

### MATLAB Parser

MATLAB R2019b or later. No toolboxes required.

---

## 4. Firmware — Flashing the Buoy

1. Open `VertiSea.ino` in the Arduino IDE.
2. Set the deployment flags near the top of the file:

   | Flag | Debug text over USB | GUI over USB | Field (radio) |
   |------|---------------------|--------------|---------------|
   | `USB_DEBUG` | `1` | `0` | `0` |
   | `USB_TELEM` | `0` | `1` | `0` |
   | `TELEM_ENABLE` | `1` | `1` | `1` |
   | `GPS_ENABLE` | `0` (if GPS absent) | `0` (if GPS absent) | `1` |
   | `RPM_ENABLE` | `1` (if Hall sensor wired) | `1` (if wired) | `1` or `0` |
   | `IMU_RAW_ONLY` | `1` or `0` | `1` or `0` | `0` for self-contained logs |
   | `SD_BUFFERED_WRITE` | `1` | `1` | `1` |

   > With `USB_DEBUG 1`, USB is reserved for readable debug text and binary telemetry is
   > routed to `Serial1`, regardless of `USB_TELEM`. The matching `Serial1` initialisation
   > guard is implemented and compiled in the supported feature-matrix builds.

   > **`USB_TELEM`** — set to `1` to send all telemetry packets to the USB Serial port
   > instead of the RFD900 radio. Allows the Python GUI to receive real-time data over
   > USB without any radio hardware. Also increases `TELEMETRY_RATE_HZ` to 10 Hz.

   > **`USB_DEBUG`** — set to `1` for human-readable boot/diagnostic text on USB. In this
   > mode telemetry stays on the radio (`Serial1`) so binary packets cannot corrupt the
   > debug text.

   > **`GPS_ENABLE`** — **must** be `0` when no u-blox module is attached. With `1` and no
   > module, the failed I²C ACK hangs the shared bus and freezes both IMUs.

   **Currently committed values:** `USB_DEBUG 0`, `USB_TELEM 1`, `TELEM_ENABLE 1`,
   `GPS_ENABLE 0`, `RPM_ENABLE 1`, `IMU_RAW_ONLY 1`, `SD_BUFFERED_WRITE 1` — GUI-over-USB,
   no GPS, RPM enabled, raw IMU logging, and buffered synchronous SD writes.

   > **`RPM_ENABLE`** — set to `1` when the Melexis US1881 Hall-effect sensor is wired
   > to `HALL_PIN` (default pin 2). Set to `0` when the sensor is absent. When `0`, all
   > Hall/RPM code is compiled out entirely with zero overhead.

   > **`SD_BUFFERED_WRITE`** — keep at `1` for normal operation. It queues complete records
   > in an eight-sector RAM buffer and drains them through the checked, synchronous Arduino
   > SD backend. Direct Apollo3 SD DMA was tested and rejected on core 1.2.1 because no
   > prototype passed byte verification.

3. Verify the timezone offset:
   ```cpp
   int8_t timezoneOffsetHours = -7;  // PDT; change for your deployment location
   ```
4. Verify the calibration constants (`fixedCal`, `stabCal`, `magCal`) match the current
   hardware. These are hard-coded and do not need to change unless sensors are replaced.
5. Select **Tools → Board → SparkFun Apollo3 → RedBoard Artemis Nano** and the correct COM port.
6. Click **Upload**.

**At boot**, the firmware:
- Initialises all sensors (halts with a serial error message if any sensor fails).
- Attempts GPS time sync for up to 120 s (when `GPS_ENABLE=1`; skipped entirely when `GPS_ENABLE=0`). RTC retains time from previous power cycle if GPS is unavailable.
- Creates a log file named `MMDDHHMM.BIN` on the SD card. If the RTC year is earlier than
  2024 (dead coin cell and no GPS sync), it falls back to `LOGnnnnn.BIN` using the first
  unused counter slot so no existing log is overwritten.
- Writes calibration packets to the log.
- Begins the main loop (LED blinks at 1 Hz when running normally).

**Serial monitor** (115200 baud) shows boot progress and any sensor errors.

---

## 5. Ground Station — Live Telemetry Display

### Via radio (field use)

1. Connect the ground-side RFD900x modem to the laptop via USB.
2. Run:
   ```
   python vertisea_plot_v7.py
   ```
3. Select the COM port for the RFD900x modem from the dropdown.
4. Click **Connect**.

### Via USB (bench use — `USB_TELEM 1`)

1. Flash the firmware with `USB_TELEM 1` (and `USB_DEBUG 0`).
2. Connect the buoy directly to the laptop via USB.
3. Run:
   ```
   python vertisea_plot_v7.py
   ```
4. Select the buoy's USB COM port from the dropdown.
5. Click **Connect**. No RFD900x modems required.

> **Known limitation:** opening the buoy's USB serial port still resets the board on the
> tested RedBoard Artemis Nano/driver path, despite the GUI attempting to hold RTS/DTR low.
> Connecting therefore starts a new logging session. The firmware creates a distinct filename
> instead of appending the rebooted session to an existing log. Use the RFD900x path when a
> connection must not disturb an active deployment, and see `POTENTIAL_UPGRADES.md` for the
> follow-up investigation.

### Displayed Data

| Panel | Data | Update rate |
|-------|------|-------------|
| GPS | Satellites, latitude, longitude | Every 5 s |
| BME280 | Pressure (Pa), humidity (%), temperature (°C) | Every 15 s |
| System Status | SD card health (green/red), supercapacitor voltage, rotor RPM | 1 Hz / 5 Hz |
| IMU plot (top-left) | Pendulum IMU pitch and roll (degrees, ±60° initial range) | 5 Hz |
| IMU/RPM plot (top-right) | Pendulum−buoy IMU tilt difference (°) on left axis; rotor RPM on right axis | 5 Hz |
| IMU plot (bottom-left) | Buoy IMU pitch and roll (degrees, ±60° initial range) | 5 Hz |
| Placeholder (bottom-right) | Reserved for future plot | — |

---

## 6. Post-Deployment Data Processing

### Step 1 — Retrieve the SD card

Remove the microSD card from the buoy and copy the `.BIN` file to your computer.
The filename format is `MMDDHHMM.BIN` (month, day, hour, minute at start of logging).

### Step 2 — Parse the binary log

Run the ground station and click **Load BIN File**, then pick the `.BIN`. CSVs are written
next to it, named `<baseName>_<type>.csv` (e.g. `09031435_imuRaw.csv`).

```bash
python vertisea_plot_v7.py
```

No serial connection is needed for this — the parser is independent of the live link.

> A second MATLAB parser (`parse_vertisea_log_v4.m`) was **retired 2026-09-03**. It is
> recoverable from git history at commit `9f5019f` but should not be revived; the Python
> parser is the only maintained reader.

This creates one CSV file per data type. **The MATLAB parser writes to the current MATLAB
working directory**, so `cd` into the data folder first if you want the CSVs next to the
log file:

```
04030825_imuFixed.csv
04030825_imuStab.csv
04030825_bme280.csv
04030825_gps.csv
04030825_rtcEvt.csv
04030825_mag.csv
04030825_calFixed.csv
04030825_calStab.csv
04030825_supcap.csv
04030825_rpm.csv         (only present when RPM_ENABLE=1)
```

### Step 2b — Alternative: parse without MATLAB

The Python ground station can parse the same `.BIN` file and produce identical CSVs — no
MATLAB licence required:

1. Run `python vertisea_plot_v7.py`.
2. Click **Load BIN File** and select the `.BIN`.
3. CSVs are written **next to the selected `.BIN` file**, and the pendulum/buoy IMU plots
   are populated with the logged attitude data.

A summary dialog reports record counts per type and the files written.

### Step 3 — Analyse

Load the CSVs into MATLAB or Python for analysis. All timestamps are in milliseconds
since boot (`millis()`). Use the `rtcEvt` CSV to convert to wall-clock time.

---

## 7. Magnetometer Calibration

> **Calibration has already been performed** for the current hardware. Only repeat this
> if the magnetometer or its physical mounting is changed.

1. Deploy the buoy (or rotate the sensor through all orientations) to collect a full
   sphere of magnetometer data.
2. Parse the resulting `.BIN` file to get `*_mag.csv`.
3. In MATLAB:
   ```matlab
   [center, scale, Mcal] = calibrateMag('04030825_mag.csv')
   ```
   > **Important:** `calibrateMag` expects **raw** magnetometer counts. Because the
   > firmware applies the existing `magCal` before logging, temporarily set
   > `magCal.offset = {0,0,0}` and `magCal.scale = {1,1,1}` and reflash before collecting
   > calibration data. See [`docs/calibration.md`](docs/calibration.md) §2.6.
4. Inspect the 3D scatter plots — the calibrated data should form a sphere.
5. Copy the `center` and `scale` values into `VertiSea.ino`:
   ```cpp
   } magCal = {
     { center(1), center(2), center(3) },
     { scale(1),  scale(2),  scale(3)  }
   };
   ```
6. Reflash the firmware.

---

## 8. Output Files Reference

### Binary log (`.BIN`)

Raw SD card log. Contains all packet types at their native rates. See
[`docs/binary_protocol.md`](docs/binary_protocol.md) for the full byte-level format.

### CSV files (from parser)

| File suffix | Rate | Key columns |
|-------------|------|-------------|
| `_imuFixed` | 104 Hz | pitch (°), roll (°), heading (°), gx/gy/gz (°/s), ax/ay/az (g) |
| `_imuStab` | 104 Hz | same as imuFixed |
| `_bme280` | 1 Hz | pressure (Pa), humidity (%), temperature (°C) |
| `_gps` | 1 Hz | satellites, latitude (°), longitude (°), altitude (m) |
| `_rtcEvt` | once | year, month, day, hour, minute, second (local time) |
| `_mag` | 104 Hz | mx, my, mz (calibrated, LPF-filtered) |
| `_calFixed` | once | accel bias (mg), accel scale, gyro bias (°/s) |
| `_calStab` | once | same as calFixed |
| ~~`_supcap`~~ | — | **No longer produced.** `0x0A` held supercap voltage, was repurposed to harvested current (`_current`), then retired 2026-09-03. Use `_currentFast` (from `0x0E`). |
| `_rpm` | 5 Hz | rpm (`RPM_ENABLE=1` only) |

All `timestamp_ms` values are milliseconds since boot. `heading = 999.9` means no valid
heading (magnetometer fusion disabled in current configuration).

---

## 9. Things That Are Easy to Forget

| Situation | What to remember |
|-----------|-----------------|
| Firmware upload fails | Check that the SparkFun Apollo3 boards package is installed and **RedBoard Artemis Nano** is selected as the board |
| SD card not detected | CS pin is 4; verify the card is FAT32 formatted |
| GPS time sync skipped | `GPS_SYNC_TIMEOUT_MS = 120 000 ms` (2 min) when `GPS_ENABLE=1`; set `GPS_ENABLE 0` to skip entirely |
| GPS shows no fix during deployment | Expected — the antenna is at water level on a rocking buoy. GPS exists to set the RTC, not for precision positioning; logging is unaffected |
| Running with `GPS_ENABLE 0` | The RTC coin cell becomes the **only** time source. Check it before deployment, and re-sync on the bench with `GPS_ENABLE 1` where reception is good |
| Ground station shows no data | Verify baud rate is 115200; verify the correct COM port is selected (RFD900 modem or buoy USB depending on `USB_TELEM` setting); confirm `USB_DEBUG` and `USB_TELEM` are not **both** `1` |
| Parser CSVs "missing" after MATLAB run | The MATLAB parser writes to the MATLAB working directory, not the `.BIN` folder — `cd` to the data folder first, or use the GUI's **Load BIN File** button instead |
| `heading` is 999.9 in CSV | Normal — magnetometer 9-DOF fusion is currently disabled |
| Parser stops early | Unknown packet type encountered — check that parser version matches firmware version |
| Calibration values look wrong | `magCal.scale` values are large (hundreds to thousands) because they are raw-count scale factors, not normalised |
| `vertDisp` drifts over time | Expected — leaky integrator prevents unbounded drift but does not eliminate it |

---

## 10. Quick Reference

```
# Flash firmware
Arduino IDE → SparkFun Apollo3 → RedBoard Artemis Nano → Upload VertiSea.ino

# Run ground station
python vertisea_plot_v7.py

# Parse an SD log: run the GUI and click "Load BIN File"
# (writes CSVs next to the .BIN file; no serial connection required)

# Magnetometer calibration (MATLAB, only if hardware changed; needs RAW mag counts)
[center, scale, Mcal] = calibrateMag('MMDDHHMM_mag.csv')
```

---

## 11. Appendix — Developer and Maintainer Notes

### Project documentation structure

This project uses the AI-agent documentation strategy described in
[`AI_Agent_Project_Documentation_Guide.md`](AI_Agent_Project_Documentation_Guide.md).
All AI agent project instructions live in a single agent-agnostic file,
[`AGENTS.md`](AGENTS.md), in the repository root. Tool-specific files are thin loaders
that point to it.

| File | Purpose |
|------|---------|
| [`AGENTS.md`](AGENTS.md) | **Single source of truth** for AI agent project instructions |
| [`.roo/rules.md`](.roo/rules.md) | Loader: tells Roo Code to read `AGENTS.md` |
| [`.github/copilot-instructions.md`](.github/copilot-instructions.md) | Loader: tells GitHub Copilot to read `AGENTS.md` |
| [`docs/binary_protocol.md`](docs/binary_protocol.md) | Byte-level packet format for all packet types |
| [`docs/firmware.md`](docs/firmware.md) | Firmware architecture, calibration, filter design, logging flow |
| [`docs/telemetry_ground_station.md`](docs/telemetry_ground_station.md) | Python ground station design and packet parsing |
| [`docs/data_pipeline.md`](docs/data_pipeline.md) | MATLAB parser and magnetometer calibration |
| [`docs/calibration.md`](docs/calibration.md) | Sensor calibration procedure and resulting constants |
| `docs/CHANGELOG_*.md` | Per-source-file history of decisions and dead ends; entries carry `[UNCONFIRMED]` / `[CONFIRMED]` / `[REVERTED]` status markers |

### Adding a new packet type

1. Add the type ID to the `PacketType` enum in `VertiSea.ino`.
2. Add the struct definition (use `__attribute__((packed))`).
3. Add the write call in `loop()` or `setup()`.
4. Add a parse branch to `parse_binary_file()` in `vertisea_plot_v7.py`, an entry in
   `_SD_PAYLOAD_BYTES` (**unless** the packet is variable-length — those must not be in the
   table), a key in the `data` dict initialiser, and a `_schemas` entry for CSV output.
5. If the packet is also transmitted over radio, add a branch to the live serial reader.
6. Update `docs/binary_protocol.md` with the new packet layout.
7. Update the `AGENTS.md` conventions section if needed.

### Changing a packet struct

Any change to field order, type, or size in a packet struct **breaks** the parser and
ground station. Always update both source files (`VertiSea.ino`, `vertisea_plot_v7.py`) and
`docs/binary_protocol.md` in the same commit.

A round-trip test proves the *transport* is right but not that the chosen types can hold real
values — an `int16` gyro field passed such a test and still overflowed on hardware (Issue 35).
Check a real log against physical expectations too.

### Re-enabling 9-DOF magnetometer fusion

In `loop()`, change:
```cpp
lastStabIMU = collectIMUData_ISM(imuStab, filterStab, stabCal, false, lpfStab);
```
to:
```cpp
lastStabIMU = collectIMUData_ISM(imuStab, filterStab, stabCal, true, lpfStab);
```
The `isStabilizedIMU = true` flag enables magnetometer reading, calibration, LPF, and
the 9-DOF Madgwick `update()` call. Heading will then be valid (not 999.9).

### Sample data for parser development

`SampleData/` is **git-ignored** (since 2026-08-18) and will not be present in a fresh
clone. It contains sample logs kept for **developing and testing the parsers against** —
they are not a scientific record, and they are easy to regenerate.

- [`SampleData/04030825/`](SampleData/04030825/) — raw `.BIN` log plus parsed CSVs
- [`SampleData/04021311/`](SampleData/04021311/), [`SampleData/04021543/`](SampleData/04021543/) — two further captures

**To get your own sample log:** flash the firmware, let it run for a few minutes, and pull
the `.BIN` off the SD card. This is usually *better* than reusing an old file, because a
fresh capture contains exactly the packet types the current firmware emits. The committed
samples predate 2026-04-03 and will not contain anything added since.

If you are adding a packet type — for example sampling dynamic current alongside the IMU —
capture a new log as part of that work and use it to exercise the parser via the ground
station's **Load BIN File** path.

The following **are** committed and should not be regenerated or overwritten:

- [`Calibration/calibration.xlsx`](Calibration/calibration.xlsx) — offline calibration workbook
- [`Calibration/accel_calibration_meas.txt`](Calibration/accel_calibration_meas.txt) — raw six-position accel measurements
- [`Madgwick/`](Madgwick/) — vendored AHRS library; takes precedence over any global Arduino install

> **Note on repository size:** ignoring `SampleData/` stops *future* growth, but the blobs
> remain in earlier commits because history was not rewritten, so a full clone still
> transfers ~124 MB. Since this data is regenerable rather than precious, purging it with
> `git filter-repo` is a reasonable option if clone size becomes annoying — it just needs a
> force-push coordinated with anyone who has a clone.
