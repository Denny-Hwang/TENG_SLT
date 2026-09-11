# VertiSea

Wave-energy buoy data-acquisition and telemetry system — Arctic TENG project, PNNL.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository Layout](#2-repository-layout)
3. [Hardware](#3-hardware)
4. [Prerequisites](#4-prerequisites)
5. [Firmware — Flashing the Buoy](#5-firmware--flashing-the-buoy)
6. [Ground Station — Live Telemetry Display](#6-ground-station--live-telemetry-display)
7. [Post-Deployment Data Processing](#7-post-deployment-data-processing)
8. [Harvested-Current Post-Processing](#8-harvested-current-post-processing)
9. [Magnetometer Calibration](#9-magnetometer-calibration)
10. [Output Files Reference](#10-output-files-reference)
11. [Things That Are Easy to Forget](#11-things-that-are-easy-to-forget)
12. [Quick Reference](#12-quick-reference)
13. [Appendix — Developer and Maintainer Notes](#13-appendix--developer-and-maintainer-notes)

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                  BUOY (SparkFun RedBoard Artemis Nano)          │
│                                                                 │
│  ISM330DHCX (fixed/hull)  ──┐                                   │
│  ISM330DHCX (stabilized)  ──┤                                   │
│  MMC5983MA (mag)          ──┤                                   │
│  BME280 (env)             ──┼── Madgwick AHRS ──► Binary packets│
│  u-blox GNSS              ──┤                         │         │
│  RV8803 RTC               ──┤                         ├──► SD   │
│  Harvested current  (A14) ──┤                         │  (.BIN) │
│  Battery voltage    (A15) ──┤                         │         │
│  Hall rotor RPM   (pin 2) ──┘                         └──► UART │
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

The buoy logs all sensor data to an SD card in a compact binary format: IMU at a nominal
104 Hz (~93–98 Hz achieved), harvested current at several hundred Hz, and the slow channels
at 1 Hz. A reduced subset can be transmitted over a pair of RFD900x 900 MHz radio modems —
or over USB — to a laptop running the Python ground station.

After retrieval, the SD `.BIN` file is parsed offline into CSV files by the same Python
program (**Load BIN File**). That is the only maintained parser.

---

## 2. Repository Layout

| Path | What it is |
|------|------------|
| `VertiSea/VertiSea.ino` | Buoy firmware (Arduino sketch — **the folder name must match the sketch name**) |
| `VertiSea/MadgwickAHRS.{h,cpp}` | Vendored AHRS, **inside the sketch folder** so the quoted `#include` resolves to it. A local fork of upstream 1.2.0 — see §4 |
| `vertisea_protocol.py` | Packet layouts, SD `.BIN` parser and CSV export. **Stdlib only** — no GUI, no serial. Also a batch CLI |
| `vertisea_plot_v7.py` | Ground station GUI. Imports the parser from `vertisea_protocol.py` |
| `vertisea_plot_v7.bat` | Windows launcher for the GUI |
| `tests/` | Round-trip tests for the binary protocol (stdlib `unittest`) |
| `current_filter_test.py` | Standalone bench for harvested-current post-processing (see §8) |
| `current_filter_test.bat` | Windows launcher for the above |
| `Calibration/` | `calibrateMag.m`, the calibration workbook, and raw accel measurements |
| `tools/` | Throwaway benchmark sketches (SD write paths, ADC timer/DMA). Not part of the deployed system |
| `archived/` | Superseded material kept for the record only — nothing here is read by any build step. See [`archived/README.md`](archived/README.md) |
| `docs/` | Reference documentation and per-file changelogs |

---

## 3. Hardware

| Component | Part | Interface |
|-----------|------|-----------|
| Microcontroller | SparkFun RedBoard Artemis Nano (Apollo3) | — |
| Fixed IMU (hull) | SparkFun ISM330DHCX | I²C @ 0x6A |
| Stabilized IMU (gimbal) | SparkFun ISM330DHCX | I²C @ 0x6B |
| Magnetometer | SparkFun MMC5983MA (on the stabilized IMU board) | I²C |
| Environmental | SparkFun BME280 | I²C |
| GNSS | SparkFun u-blox | I²C |
| RTC | SparkFun RV8803 | I²C |
| Storage | microSD card, FAT32 | SPI (CS = pin 4) |
| Radio | RFD900x × 2 | Serial1 @ 115200 baud |
| Harvested-current sensor | Analog output, 100 mA/V, wired **directly** (no divider) | ADC pin A14 |
| Battery sense | 1S LiFePO4 through a 98.7 kΩ / 98.9 kΩ divider (≈2:1) | ADC pin A15 |
| Rotor tachometer | Melexis US1881 Hall latch, 4.7 kΩ pull-up to 3.3 V | Digital pin 2 |

The I²C bus runs at **400 kHz**. The ADC is configured for 14-bit resolution against the
Apollo3's internal 2.0 V reference; per-channel gain corrections are applied as effective
reference voltages (`VREF_A14`, `VREF_A15` — see [`docs/adc_calibration.md`](docs/adc_calibration.md)).

Current-channel full scale is **0–200 mA** (2.0 V × 100 mA/V), ≈0.012 mA per ADC count.
The battery divider keeps a fully charged 3.65 V LiFePO4 cell at 1.83 V — 91% of full scale.
**Never wire the battery directly to A15.**

Build photo: [`docs/IMG_1770.jpeg`](docs/IMG_1770.jpeg).
RFD900x modem configuration as flashed: [`docs/Ground_RFD900x.png`](docs/Ground_RFD900x.png)
(SiK 3.57, 902–915 MHz, 115200 serial baud, 125 kbps air speed, Net ID 25, Tx power 30).

---

## 4. Prerequisites

### Firmware (Arduino IDE)

Install these libraries via the Arduino Library Manager:

- SparkFun BME280
- SparkFun RV8803 RTC
- SparkFun u-blox GNSS Arduino Library
- SparkFun ISM330DHCX
- SparkFun MMC5983MA Arduino Library
- SD (built-in, 1.3.0)
- Wire, SPI (built-in)

Madgwick AHRS is **vendored inside the sketch folder** as
[`VertiSea/MadgwickAHRS.h`](VertiSea/MadgwickAHRS.h) and
[`VertiSea/MadgwickAHRS.cpp`](VertiSea/MadgwickAHRS.cpp). Do **not** install the Library
Manager copy — if you have one in your sketchbook `libraries/` folder, remove it.

> **This is a local fork, not stock upstream.** Two constants differ from
> arduino-libraries/MadgwickAHRS 1.2.0 and both change filter behaviour:
>
> | Constant | Upstream | Here | Effect |
> |----------|----------|------|--------|
> | `sampleFreqDef` | 512.0f | 104.0f | seed only — the filter is retuned every tick from the measured `dt` |
> | `betaDef` | 0.1f | **0.5f** | ~12× the author's recommended AHRS gain; the filter behaves close to a smoothed accelerometer tilt sensor |
>
> `betaDef` in particular is untuned for wave-frequency dynamics (there is a `TODO` about
> it in `setup()`), and it interacts with Issue 41 — read that before changing it.
>
> Until 2026-09-11 these files lived in a sibling `Madgwick/` folder, where **Arduino could
> not see them** and a globally installed copy was silently compiled instead. See Issue 58.
> The upstream packaging metadata is kept in
> [`archived/Madgwick-upstream/`](archived/Madgwick-upstream/).

Board: **SparkFun RedBoard Artemis Nano**. Install the SparkFun Apollo3 boards package
(core 1.2.1) via the Boards Manager URL
`https://raw.githubusercontent.com/sparkfun/Arduino_Apollo3/main/package_sparkfun_apollo3_index.json`.

### Ground Station (Python)

```
pip install pyserial matplotlib
```

Python 3.8 or later. `tkinter` ships with standard Python distributions.

### MATLAB

Only needed for `Calibration/calibrateMag.m` (R2019b or later, no toolboxes).
**Parsing SD logs does not require MATLAB** — the MATLAB parser was retired 2026-09-03.

---

## 5. Firmware — Flashing the Buoy

1. Open `VertiSea/VertiSea.ino` in the Arduino IDE.
2. Set the compile-time deployment flags near the top of the file. There are **seven**:

   | Flag | Field (radio) | Bench GUI over USB | Bench debug text | SD-only capture |
   |------|---------------|--------------------|------------------|-----------------|
   | `USB_DEBUG` | `0` | `0` | `1` | `0` |
   | `USB_TELEM` | `0` | `1` | ignored | ignored |
   | `TELEM_ENABLE` | `1` | `1` | `1` | `0` |
   | `GPS_ENABLE` | `1` | `0` (if GPS absent) | `0` (if GPS absent) | `0` |
   | `RPM_ENABLE` | `1` if Hall wired | `1` if wired | `1` if wired | `1` if wired |
   | `IMU_RAW_ONLY` | `0` for a self-contained log | `0` or `1` | `0` or `1` | `1` |
   | `SD_BUFFERED_WRITE` | `1` | `1` | `1` | `1` |

   > ### ⚠ Currently committed values
   >
   > `USB_DEBUG 0`, `USB_TELEM 0`, **`TELEM_ENABLE 0`**, `GPS_ENABLE 0`, `RPM_ENABLE 1`,
   > `IMU_RAW_ONLY 1`, `SD_BUFFERED_WRITE 1`.
   >
   > This is an **SD-only capture build**. It transmits nothing: the ground station will
   > show a blank GUI no matter which port you select, and that is not a fault. Set
   > `TELEM_ENABLE 1` (and `USB_TELEM 1` for a USB link) before any run where live
   > monitoring is wanted.

   > **`TELEM_ENABLE`** — master switch for telemetry *transmission*. `0` compiles out every
   > `TELEM_WRITE()` and never initialises the telemetry UART, reclaiming the loop time that
   > blocking serial writes cost so the harvested-current sampler runs faster. SD logging is
   > unaffected. `USB_TELEM` only *routes* telemetry; it cannot switch it off.

   > **`USB_TELEM`** — `1` sends telemetry to the USB Serial port instead of the RFD900x,
   > so the GUI works with no radio hardware. Also raises `TELEMETRY_RATE_HZ` from 5 Hz to
   > 10 Hz. Requires `USB_DEBUG 0`.

   > **`USB_DEBUG`** — `1` gives human-readable boot/diagnostic text on USB and waits up to
   > 3 s for a host. Telemetry is then forced onto `Serial1` so binary packets cannot
   > corrupt the text stream. Takes priority over `USB_TELEM`.

   > **`GPS_ENABLE`** — **must** be `0` when no u-blox module is attached. With `1` and no
   > module, the failed I²C ACK leaves SDA low, hangs the shared bus, and freezes both IMUs.

   > **`RPM_ENABLE`** — `1` when the Melexis US1881 Hall sensor is wired to `HALL_PIN`
   > (default pin 2). When `0`, all Hall/RPM code is compiled out entirely.

   > **`IMU_RAW_ONLY`** — `1` logs one 43 B `TYPE_IMU_RAW` record per tick instead of the
   > processed attitude + magnetometer records (~108 B). That is a ~60% SD-bandwidth
   > reduction and raises the achieved IMU rate, but the log then contains **no on-board
   > attitude and no magnetometer data** — pitch/roll must be recomputed offline from the
   > boot-time calibration records. Use `0` when you want a self-contained log.

   > **`SD_BUFFERED_WRITE`** — keep at `1`. It queues complete records in an eight-sector
   > RAM buffer and drains them through the checked, synchronous Arduino SD backend.
   > Direct Apollo3 SD DMA was tested and rejected on core 1.2.1 (no prototype passed byte
   > verification).

3. Verify the timezone offset:
   ```cpp
   int8_t timezoneOffsetHours = -7;  // PDT; change for your deployment location
   ```
4. Verify the calibration constants (`fixedCal`, `stabCal`, `magCal`) match the installed
   hardware. They are hard-coded and only change when a sensor is replaced.
5. Select **Tools → Board → SparkFun Apollo3 → RedBoard Artemis Nano** and the correct COM port.
6. Click **Upload**.

**At boot**, the firmware:
- Initialises every sensor. A magnetometer failure is tolerated (nothing reads it in the
  6-DOF configuration). Any **other** sensor failure still halts the board permanently,
  now blinking a diagnostic pulse count on the LED: 1 = RTC, 2 = BME280, 3 = stabilized
  IMU, 4 = fixed IMU, 5 = SD card, 6 = log filenames exhausted, 7 = log file open failed.
- Attempts GPS time sync for up to 120 s when `GPS_ENABLE 1`; skipped entirely when `0`.
  The RTC retains time from the previous power cycle if GPS is unavailable.
- Creates a log file `MMDDHHMM.BIN` on the SD card. If that name already exists, or the RTC
  year is earlier than 2024 (dead coin cell and no GPS), it falls back to the first unused
  `LOGnnnnn.BIN` so no existing log is ever appended to or overwritten.
- Writes the boot calibration records (`0x08`, `0x09`, `0x0D`, `0x10`, `0x13`) and the RTC
  event (`0x05`) to the log.
- Enters the main loop. The LED blinks at 1 Hz when healthy, 4 Hz on a latched SD error.

**Serial monitor** (115200 baud) shows boot progress and sensor errors — but only when
`USB_DEBUG 1`. With `USB_DEBUG 0` the board is silent on USB by design.

---

## 6. Ground Station — Live Telemetry Display

Requires a firmware build with **`TELEM_ENABLE 1`**. The committed build has it `0`.

### Via radio (field use — `USB_TELEM 0`)

1. Connect the ground-side RFD900x modem to the laptop via USB.
2. Run `python vertisea_plot_v7.py` (or double-click `vertisea_plot_v7.bat`).
3. Pick the RFD900x COM port, click **Connect**.

### Via USB (bench use — `USB_TELEM 1`, `USB_DEBUG 0`)

1. Connect the buoy directly to the laptop via USB.
2. Run the same program, pick the buoy's COM port, click **Connect**. No radio needed.

> **Known limitation:** opening the buoy's USB serial port still resets the board on the
> tested RedBoard Artemis Nano/driver path, despite the GUI holding RTS/DTR low. Connecting
> therefore starts a new logging session (in a new file). Use the RFD900x path when a
> connection must not disturb an active deployment. See `POTENTIAL_UPGRADES.md`.

### Displayed Data

| Panel | Data | Source packet | Update rate |
|-------|------|---------------|-------------|
| GPS | Satellites, latitude, longitude | `0x04` | Every 5 s |
| BME280 | Pressure (hPa), humidity (%), temperature (°C) | `0x03` | Every 15 s |
| System Status | SD health (green/red), window-average current, battery volts, rotor RPM | `0x0B`, `0x0F`, `0x14`, `0x0C` | 1 Hz / telemetry rate |
| Harvested (2 min window) | Peak / avg / RMS current, avg power, charge, ∫I²dt, window, dropped | `0x0F` | 1 Hz |
| IMU plot (top-left) | Pendulum (fixed) IMU pitch and roll, ±60° initial range | `0x06` | 5 Hz radio / 10 Hz USB |
| IMU/RPM plot (top-right) | Pendulum−buoy tilt difference (°) left axis; rotor RPM right axis | `0x06`, `0x0C` | same |
| IMU plot (bottom-left) | Buoy (stabilized) IMU pitch and roll, ±60° initial range | `0x06` | same |
| Placeholder (bottom-right) | Reserved for a future plot | — | — |

The "Current" reading is the **window average** (`charge_mC / integ_s`), not an instantaneous
sample. The retired 5 Hz point-sample packet read ~2.1× high on this bursty signal.

---

## 7. Post-Deployment Data Processing

### Step 1 — Retrieve the SD card

Copy the `.BIN` file off the microSD card. The name is `MMDDHHMM.BIN` (month, day, hour,
minute at the start of logging) or `LOGnnnnn.BIN` if the RTC was invalid.

### Step 2 — Parse the binary log

Either through the GUI:

```
python vertisea_plot_v7.py
```

Click **Load BIN File** and select the `.BIN`. No serial connection is needed. A summary
dialog reports record counts per type and lists the files written.

Or from the command line, with no GUI and no third-party packages at all:

```
python vertisea_protocol.py 09031435.BIN            # one log
python vertisea_protocol.py /data/*.BIN             # or a whole directory
```

Either way, CSVs are written **next to the `.BIN`**, named `<baseName>_<type>.csv`
(for example `09031435_imuRaw.csv`).

> Only the packet types actually present in the log produce a CSV. A log from an
> `IMU_RAW_ONLY 1` build contains `_imuRaw` and **no** `_imuFixed` / `_imuStab` / `_mag`.
> The GUI's attitude plots stay empty for such a log and the summary says so — expected,
> not an error.

> Large logs are slow. The parser expands every high-rate current sample into a Python
> object and runs on the GUI thread, so a multi-hour capture can consume gigabytes and
> appear hung (Issue 40). Bench-length logs are fine.

### Step 3 — Analyse

Load the CSVs into MATLAB or Python. All `timestamp_ms` values are milliseconds since boot
(`millis()`); use the `_rtcEvt` CSV to convert to local wall-clock time.

For an `IMU_RAW_ONLY` log, recompute attitude offline from `_imuRaw` using the constants in
`_calFixed`, `_calStab`, and `_lpfCal`. The 1-pole IIR is exactly invertible:
`x[n] = y[n-1] + (y[n] − y[n-1]) / alpha`.

---

## 8. Harvested-Current Post-Processing

`current_filter_test.py` is a standalone, stdlib-only bench for the current post-processing
pipeline described in [`docs/current_measurement_testing.md`](docs/current_measurement_testing.md).
It deliberately does **not** import the ground station, so an unvalidated filter cannot
silently bias the production conversion path.

```
py -3 current_filter_test.py --selftest                       # built-in checks, no data needed
py -3 current_filter_test.py <base>_currentFast.csv           # full report
py -3 current_filter_test.py <csv> --window 33                # smoother: 10.7 Hz, +2.5 bits
py -3 current_filter_test.py <csv> --plot                     # requires matplotlib
py -3 current_filter_test.py <csv> --write-csv filtered.csv
py -3 current_filter_test.py --gui                            # or run with no arguments
```

The filter reproduces a **Keysight scope's High-Resolution acquisition mode**: despike with
a Hampel filter, then boxcar-average, then remove the idle baseline. The boxcar is what
buys effective bits — each 4× widening adds one bit and quarters the bandwidth. `--window`
is that width; the report prints the resulting −3 dB bandwidth and bit gain so it can be
matched to a scope setting (`N = 0.443 × fs / f_3dB`).

Two properties worth knowing before comparing results:

- **Charge is unchanged by the window.** Averaging is mean-preserving, which is what an
  integrated quantity requires. The median-5 this replaced moved the measured charge by
  +2.79%.
- **Peak falls as the window widens, and that is correct** — a peak read through a 21 Hz
  filter is a 21 Hz peak. Quote the bandwidth with the peak. The firmware's telemetry
  `peak_mA` is an unfiltered single sample and will always read higher.

The ADC has no analog anti-alias filter, so content above ~400 Hz folded in before
sampling and no digital filter can remove it. If the buoy and the scope still disagree
after matching bandwidths, suspect that first — the fix is an RC at the sense point.

It reads calibration from the sibling `<base>_currentCal.csv` when present and wall-clock
time from `<base>_rtcEvt.csv`; both are produced by the Step 2 parse above.

---

## 9. Magnetometer Calibration

> **Calibration has already been performed** for the current hardware. Repeat only if the
> magnetometer or its physical mounting changes.
>
> Note that 9-DOF fusion is currently **disabled** in firmware — both IMUs run 6-DOF and the
> magnetometer is never read. `magCal` only affects the log if you re-enable it (§13).

1. Rotate the sensor through a full sphere of orientations while logging.
2. Parse the resulting `.BIN` to get `*_mag.csv` (requires an `IMU_RAW_ONLY 0` build with
   9-DOF re-enabled, otherwise no `0x07` records are written).
3. In MATLAB:
   ```matlab
   [center, scale, Mcal] = calibrateMag('04030825_mag.csv')
   ```
   > **Important:** `calibrateMag` expects **raw** magnetometer counts. Because the firmware
   > applies `magCal` before logging, temporarily set `magCal.offset = {0,0,0}` and
   > `magCal.scale = {1,1,1}` and reflash before collecting calibration data.
   > See [`docs/calibration.md`](docs/calibration.md) §2.6.
4. Inspect the 3D scatter plots — calibrated data should form a sphere.
5. Copy `center` and `scale` into `VertiSea/VertiSea.ino`:
   ```cpp
   } magCal = {
     { center(1), center(2), center(3) },
     { scale(1),  scale(2),  scale(3)  }
   };
   ```
6. Reflash.

---

## 10. Output Files Reference

### Binary log (`.BIN`)

Raw SD log containing every packet type at its native rate. See
[`docs/binary_protocol.md`](docs/binary_protocol.md) for the byte-level format.

### CSV files produced by the parser

| File suffix | Packet | Rate | Key columns |
|-------------|--------|------|-------------|
| `_imuRaw` | `0x12` | ~93–98 Hz | Both IMUs, **uncalibrated**: `*_ax_mg`…`*_az_mg` (milli-g, int16), `*_gx_mdps`…`*_gz_mdps` (**millidegrees/s**, int32), `interval_us`. `IMU_RAW_ONLY 1` builds only |
| `_imuFixed` | `0x01` | ~93 Hz | pitch, roll, heading (°), gx/gy/gz (°/s), ax/ay/az (g), interval_us. `IMU_RAW_ONLY 0` only |
| `_imuStab` | `0x02` | ~93 Hz | same as `_imuFixed` |
| `_mag` | `0x07` | ~93 Hz | mx, my, mz (calibrated, LPF-filtered). `IMU_RAW_ONLY 0` **and** 9-DOF enabled |
| `_bme280` | `0x03` | 1 Hz | pressure (Pa), humidity (%), temperature (°C) |
| `_gps` | `0x04` | 1 Hz | satellites, latitude (°), longitude (°), altitude (m) |
| `_rtcEvt` | `0x05` | once | year, month, day, hour, minute, second (**local** time) |
| `_calFixed` | `0x08` | once | accel bias (milli-g), accel scale (milli-g per g), gyro bias (**millidegrees/s**) |
| `_calStab` | `0x09` | once | same as `_calFixed` |
| `_currentCal` | `0x0D` | once | vref (effective), adc_max, div_ratio, sens_mA_per_V |
| `_currentFast` | `0x0E` | ~800 Hz | counts (raw 14-bit ADC), current_mA. **Use this for all quantitative current work** |
| `_lpfCal` | `0x10` | once | IIR alphas, design cutoffs, imu_rate_hz, magCal offsets and scales |
| `_hallEdge` | `0x11` | per edge | edge_us (raw `micros()`), period_us, rpm (assumes one magnet) |
| `_batteryCal` | `0x13` | once | vref (effective), adc_max, r_top_ohm, r_bottom_ohm, div_ratio |
| `_batteryVoltage` | `0x14` | 1 Hz | counts, voltage_V |
| `_rpm` | `0x0C` | telemetry rate | rpm (`RPM_ENABLE 1` only) |
| `_sysHealth` | `0x15` | 1 Hz | loop and SD timing, failure and recovery counts, Hall-noise counters. **Read this first when a deployment misbehaves** |
| ~~`_current`~~ | ~~`0x0A`~~ | — | **Retired 2026-09-03.** The point-sample estimator read ~2.1× high on this bursty signal. Still parsed so legacy logs load; never emitted. Use `_currentFast` |
| ~~`_supcap`~~ | — | — | **No longer produced.** `0x0A` originally held supercapacitor voltage before the channel was repurposed to harvested current and then retired |

All `timestamp_ms` values are milliseconds since boot. `heading = 999.9` means "no valid
heading" — the normal value in the current 6-DOF configuration.

Radio-only packets (`0x06` TELEM_IMU, `0x0B` STATUS, `0x0F` CURRENT_STATS) are never written
to SD and therefore never appear as CSVs.

---

## 11. Things That Are Easy to Forget

| Situation | What to remember |
|-----------|-----------------|
| Ground station shows nothing at all | Check `TELEM_ENABLE` — the committed build is `0` and transmits nothing. Also confirm `USB_DEBUG` and `USB_TELEM` are not both `1` |
| Firmware upload fails | Verify the SparkFun Apollo3 boards package is installed and **RedBoard Artemis Nano** is selected |
| Sketch will not open | The sketch must live in a folder of the same name: `VertiSea/VertiSea.ino` |
| LED stopped blinking / stuck on mid-run | Open `<base>_sysHealth.csv`. `loop_max_us` over 500 000 is a stall long enough to freeze the LED, and the other columns say which subsystem caused it. The parser prints the diagnosis in the Load BIN File summary |
| A deployment produced several `LOGnnnnn.BIN` files | Normal after an SD fault: each recovery opens a new file with a fresh copy of the calibration records. `sd_recoveries` in `_sysHealth.csv` counts them |
| Board appears dead at boot | Count the LED pulses: 1 = RTC, 2 = BME280, 3 = stab IMU, 4 = fixed IMU, 5 = SD, 6 = filenames exhausted, 7 = file open. A steady 1 Hz blink means it is running normally; 4 Hz means a latched SD error. There is still no watchdog — a halted board stays halted (Issue 47) |
| SD card not detected | CS pin is 4; the card must be FAT32 |
| GPS time sync skipped | `GPS_SYNC_TIMEOUT_MS = 120 000 ms` when `GPS_ENABLE 1`; `GPS_ENABLE 0` skips it entirely |
| GPS shows no fix during deployment | Expected — the antenna sits at water level on a rocking buoy. GPS exists to set the RTC, not for positioning; logging is unaffected |
| Running with `GPS_ENABLE 0` | The RTC coin cell is then the **only** time source. Check it before deployment and re-sync on the bench with `GPS_ENABLE 1` where reception is good |
| No `_imuFixed`/`_imuStab` CSV after parsing | The build was `IMU_RAW_ONLY 1`. Use `_imuRaw` and recompute attitude offline |
| `_mag` CSV is missing | 9-DOF fusion is disabled (`STAB_IMU_USES_MAG 0`), so no `0x07` records are written at all. Re-enable it (§13) before expecting magnetometer data. Logs from before 2026-09-11 contain `_mag` columns of constant zeros instead — those are not real readings |
| Gyro columns look 1000× too large | `_imuRaw` gyro is in **millidegrees/s**; `_imuFixed` gyro is in °/s. The `gyro_bias` constants are in millidegrees/s too |
| Parser stops early | An unknown packet type was hit — check that the parser version matches the firmware version |
| Parsing a long log seems to hang | Known limitation (Issue 40): the parser is in-memory and runs on the GUI thread |
| `magCal.scale` values look wrong | They are large (hundreds to thousands) because they are raw-count scale factors, not normalised |
| `vertDisp` drifts over time | Expected — the leaky integrator bounds the drift but does not eliminate it. Treat it as indicative only |
| `n_dropped` is huge in the telemetry panel | By design: `CURRENT_RATE_HZ` is a deliberate over-request. Judge sampling health from the effective rate, not from `n_dropped` |

---

## 12. Quick Reference

```
# Flash firmware
Arduino IDE → SparkFun Apollo3 → RedBoard Artemis Nano → Upload VertiSea/VertiSea.ino
# (check TELEM_ENABLE before any run that needs live telemetry)

# Run ground station / parse an SD log
python vertisea_plot_v7.py          # then "Connect", or "Load BIN File"

# Harvested-current post-processing bench
py -3 current_filter_test.py --selftest
py -3 current_filter_test.py <base>_currentFast.csv

# Magnetometer calibration (MATLAB, only if hardware changed; needs RAW mag counts)
[center, scale, Mcal] = calibrateMag('MMDDHHMM_mag.csv')
```

---

## 13. Appendix — Developer and Maintainer Notes

### Project documentation structure

This project uses the AI-agent documentation strategy described in
[`archived/AI_Agent_Project_Documentation_Guide.md`](archived/AI_Agent_Project_Documentation_Guide.md)
(archived — it is a general-purpose methodology document, not VertiSea-specific).
All AI agent project instructions live in a single agent-agnostic file,
[`AGENTS.md`](AGENTS.md); tool-specific files are thin loaders that point to it.

| File | Purpose |
|------|---------|
| [`AGENTS.md`](AGENTS.md) | **Single source of truth** for AI agent project instructions |
| [`.roo/rules.md`](.roo/rules.md) | Loader: tells Roo Code to read `AGENTS.md` |
| [`.github/copilot-instructions.md`](.github/copilot-instructions.md) | Loader: tells GitHub Copilot to read `AGENTS.md` |
| [`docs/binary_protocol.md`](docs/binary_protocol.md) | Byte-level packet format for all packet types |
| [`docs/firmware.md`](docs/firmware.md) | Firmware architecture, calibration, filter design, logging flow |
| [`docs/telemetry_ground_station.md`](docs/telemetry_ground_station.md) | Python ground station design and packet parsing |
| [`docs/data_pipeline.md`](docs/data_pipeline.md) | CSV schemas and magnetometer calibration |
| [`docs/calibration.md`](docs/calibration.md) | Sensor calibration procedure and resulting constants |
| [`docs/adc_calibration.md`](docs/adc_calibration.md) | Measured per-channel ADC gain for A14/A15 |
| [`docs/current_measurement_testing.md`](docs/current_measurement_testing.md) | Current-channel noise floor, aliasing analysis, post-processing pipeline |
| `docs/CHANGELOG_*.md` | Per-source-file history of decisions and dead ends; entries carry `[UNCONFIRMED]` / `[CONFIRMED]` / `[REVERTED]` markers |
| [`IDENTIFIED_ISSUES.md`](IDENTIFIED_ISSUES.md) | Known defects, ranked by severity |
| [`POTENTIAL_UPGRADES.md`](POTENTIAL_UPGRADES.md) | Proposed work, ranked by value |

### Adding a new packet type

1. Add the type ID to the `PacketType` enum in `VertiSea/VertiSea.ino`.
2. Add the struct definition (use `__attribute__((packed))`).
3. Add the write call in `loop()` or `setup()`.
4. Add a parse branch to `parse_binary_file()` in `vertisea_plot_v7.py`, an entry in
   `_SD_PAYLOAD_BYTES` (**unless** the packet is variable-length — those must not be in the
   table), a key in the `data` dict initialiser, and a `_schemas` entry for CSV output.
5. If the packet is also transmitted over radio, add a branch to the live serial reader in
   `update()`, and add the key to the `load_bin_file()` summary list.
6. Update `docs/binary_protocol.md` with the new packet layout.
7. Update the `AGENTS.md` conventions section if needed.

### Changing a packet struct

Any change to field order, type, or size **breaks** the parser and ground station. Always
update `VertiSea/VertiSea.ino`, `vertisea_plot_v7.py`, and `docs/binary_protocol.md` in the
same commit.

A round-trip test proves the *transport* is right but not that the chosen types can hold real
values — an `int16` gyro field passed such a test and still overflowed on hardware (Issue 35).
Check a real log against physical expectations too.

Run the protocol tests after any packet change:

```
python3 tests/test_binary_protocol.py        # 24 round-trip tests, stdlib only
python3 current_filter_test.py --selftest    # 18 checks on the current-filter bench
```

The protocol tests build `.BIN` byte streams from the layouts in `docs/binary_protocol.md`
and assert the parser returns the values unchanged. They pin the parser against the
protocol document — they do **not** compile the firmware, so a change made to
`VertiSea.ino` alone will not fail them.

### Re-enabling 9-DOF magnetometer fusion

Set the single flag near the top of `VertiSea/VertiSea.ino`:
```cpp
#define STAB_IMU_USES_MAG 1
```
That enables magnetometer reading, calibration, LPF, the 9-DOF Madgwick `update()`, and
the `TYPE_MAG` (`0x07`) SD record — all from one place. `heading` then becomes valid
instead of 999.9. Reaching the log also requires `IMU_RAW_ONLY 0`.

Verify the fix for Issue 41 first: the accelerometer and gyroscope are currently presented
to the filter in two different body frames, and adding a third sensor to that fusion will
not help.

### Sample data

`SampleData/` is **not tracked in git** and will not be present in a fresh clone. It held
sample logs kept for developing and testing the parsers against — not a scientific record,
and easy to regenerate.

**To get your own sample log:** flash the firmware, let it run for a few minutes, and pull the
`.BIN` off the SD card. A fresh capture is usually *better* than an old file, because it
contains exactly the packet types the current firmware emits.

The following **are** committed and should not be regenerated or overwritten:

- [`Calibration/calibration.xlsx`](Calibration/calibration.xlsx) — offline calibration workbook
- [`Calibration/accel_calibration_meas.txt`](Calibration/accel_calibration_meas.txt) — raw six-position accel measurements
- [`VertiSea/MadgwickAHRS.h`](VertiSea/MadgwickAHRS.h) and [`.cpp`](VertiSea/MadgwickAHRS.cpp) — vendored AHRS (a local fork; see §4)
- Image assets in `docs/`

> **Note on repository size:** ignoring `SampleData/` stops *future* growth, but the blobs
> remain in earlier commits because history was not rewritten, so a full clone still transfers
> ~124 MB. Since this data is regenerable rather than precious, purging it with `git
> filter-repo` is a reasonable option — it just needs a force-push coordinated with anyone who
> has a clone.
