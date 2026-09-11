# VertiSea — Potential Upgrades

This file tracks proposed enhancements and new features. Each entry describes the
motivation, proposed approach, and any known constraints. Update **Status** when work
begins or completes; do not delete completed entries.

**Priority scale:**

| Level | Meaning |
|-------|---------|
| ⭐⭐⭐ High | Directly improves usability or data quality for current deployments |
| ⭐⭐ Medium | Useful improvement; not blocking current work |
| ⭐ Low | Nice-to-have; low urgency |

---

## Upgrade Index

| # | Priority | Component | Short title | Status |
|---|----------|-----------|-------------|--------|
| U1 | ⭐⭐⭐ | Python GUI | Binary SD log parser in ground station | ✅ Core implemented; advanced tab UX deferred |
| U2 | ⭐⭐⭐ | Firmware | Re-enable 9-DOF Madgwick (magnetometer heading) | Planned |
| U3 | ⭐⭐⭐ | Firmware | Extend GPS sync timeout; make it configurable | ✅ Implemented |
| U4 | ⭐⭐ | Python GUI | Add supercapacitor voltage display | ⛔ Obsolete — channel repurposed |
| U5 | ⭐⭐ | Python GUI | Fix `TYPE_TELEM_IMU` plot labels (pitch/roll/disp) | ✅ Resolved (2026-03-30) |
| U6 | ⭐⭐ | Firmware | Add SD write error detection and error LED pattern | ⚠ Partially implemented — see Issue 3 |
| U7 | ⭐⭐ | Firmware | Remove `while (!Serial)` boot block for field use | ✅ Implemented |
| U8 | ⭐⭐ | Python GUI | Wrap-aware telemetry timestamp for rolling plots | ✅ Implemented |
| U9 | ⭐ | Firmware | Log raw (uncalibrated) IMU data as separate packet type | ✅ Implemented as `IMU_RAW_ONLY` / `0x12` |
| U10 | ⭐ | MATLAB | Robust parser — skip unknown packets instead of stopping | ⛔ Obsolete — MATLAB parser retired |
| U11 | ⭐ | Python GUI | CSV export from live telemetry session | Planned |
| U12 | ⭐ | Firmware | RTC validity check before using time for log filename | 🔄 Completed in code; hardware verification pending |
| U13 | ⭐⭐ | Firmware / Hardware | Rotor RPM measurement via Hall-effect sensor | ✅ Implemented |
| U14 | ⭐⭐⭐ | Firmware / Hardware | Dynamic current measurement | ✅ Current capture implemented; voltage/signed-current gaps remain |
| U15 | ⭐⭐ | Firmware / Analysis | RPM validity filter exploiting the spring-driven ramp | Deferred; raw edges support offline filtering |
| U16 | ⭐⭐⭐ | Hardware | Current-channel anti-aliasing / input-range review | ⚠ Proposed; clipping premise needs new-data check |
| U17 | ⭐ | Firmware | Current sample-rate sufficiency note | ✅ Resolved guidance |
| U18 | ⭐⭐⭐ | Hardware | Re-evaluate latching Hall sensor | ⚠ Open concern |
| U19 | ⭐⭐⭐ | Firmware | Reach a true 104 Hz IMU rate | 🔄 Partially implemented; buffering remains |
| U20 | ⭐ | Test practice | Aggressive IMU bench validation | ✅ Adopted practice note |
| U21 | ⭐⭐ | Python GUI | Optional offline orientation from raw IMU logs | Proposed |
| U22 | ⭐⭐⭐ | Firmware | Despike on-board current statistics | Proposed; blocked on linearity check |
| U23 | ⭐⭐⭐ | Firmware / Apollo3 HAL | Timer-triggered ADC DMA with double buffering | Proposed; feasibility confirmed, prototype required |
| U24 | ⭐⭐ | Firmware / Apollo3 HAL | Non-blocking I²C/IOM acquisition (DMA where useful) | Proposed research; high integration cost |
| U25 | ⭐⭐⭐ | Firmware / Storage | Buffered SD pipeline / DMA investigation | ✅ Stage 1 confirmed; direct DMA rejected on core 1.2.1; preallocation deferred |

---

## Detailed Upgrade Descriptions

---

### U1 — ⭐⭐⭐ Python GUI: Binary SD log parser tab

**Status:** ✅ Core implemented; richer tab/progress workflow deferred
**Related issues:** None (new feature)
**Files affected:** [`vertisea_plot_v7.py`](vertisea_plot_v7.py)

#### Motivation

Historically, parsing the SD card binary log required MATLAB. The MATLAB parser was retired
on 2026-09-03; `vertisea_plot_v7.py` is now the sole maintained parser. The implemented
“Load BIN File” flow allows field operators to:
- Insert the SD card into a laptop and immediately view all logged data.
- Generate CSV files without needing a MATLAB licence.
- Overlay logged data on the same plots used for live telemetry.

#### Implemented Scope

`parse_binary_file()`, `write_csvs_from_parsed()`, and the **Load BIN File** button now
provide parse → CSV → plot flow. The parser covers fixed and raw IMU records, environmental
data, calibration records, high-rate current blocks, RPM, and Hall edges.

The originally proposed dedicated tab, background thread, progress bar, output selector,
packet checkboxes, and plot selector were **not** implemented. Those are optional UX
extensions, not missing packet coverage. See Issue 38 for the current raw-only-log UX gap,
Issue 40 for deployment-scale streaming/background conversion, and U21 for optional offline
orientation.

#### Historical Proposed Approach

Add a new **"Parse Log"** tab (or panel) to the existing `VertiSeaGUI` Tkinter window.

**UI elements:**
- File picker button: "Open .BIN file" → `tkinter.filedialog.askopenfilename()`
- Parse button: triggers parsing in a background thread to keep the GUI responsive
- Progress bar or status label
- Output directory selector (default: same folder as `.BIN` file)
- Checkbox list of packet types to export (all checked by default)
- "Export CSVs" button
- Optional: plot selector to display parsed data on the existing rolling plots

**Parser implementation:**

Replicate the MATLAB parser logic in Python. The packet format is fully documented in
[`docs/binary_protocol.md`](docs/binary_protocol.md). Key implementation notes:

```python
import struct, os, csv
from pathlib import Path

PACKET_FORMATS = {
    0x01: ('imuFixed', '<9f',  ['pitch','roll','heading','gx','gy','gz','ax','ay','az']),
    0x02: ('imuStab',  '<9f',  ['pitch','roll','heading','gx','gy','gz','ax','ay','az']),
    0x03: ('bme280',   '<3f',  ['pressure','humidity','temperature']),
    0x04: ('gps',      '<Bfff',['satellites','latitude','longitude','altitude']),
    0x05: ('rtcEvt',   '<6B',  ['year_offset','month','day','hour','minute','second']),
    0x07: ('mag',      '<3f',  ['mx','my','mz']),
    0x08: ('calFixed', '<9f',  ['accel_bias_x','accel_bias_y','accel_bias_z',
                                'accel_scale_x','accel_scale_y','accel_scale_z',
                                'gyro_bias_x','gyro_bias_y','gyro_bias_z']),
    0x09: ('calStab',  '<9f',  ['accel_bias_x','accel_bias_y','accel_bias_z',
                                'accel_scale_x','accel_scale_y','accel_scale_z',
                                'gyro_bias_x','gyro_bias_y','gyro_bias_z']),
    0x0A: ('supcap',   '<H',   ['voltage_mV']),
}
HEADER_FMT = '<BL'   # type (uint8) + timestamp_ms (uint32)
HEADER_SIZE = struct.calcsize(HEADER_FMT)
```

Parse loop:
1. Read 5-byte header (`type`, `timestamp_ms`).
2. Look up `type` in `PACKET_FORMATS`.
3. Read `struct.calcsize(fmt)` bytes and unpack.
4. Append row to the appropriate in-memory list.
5. On unknown type: warn and attempt recovery (scan forward for next known type byte).
6. On EOF: write all lists to CSV files.

**GPS special case:** The SD GPS packet has `uint8 satellites` followed by 3 floats
(lat, lon, alt). The format string is `<Bfff` (1+4+4+4 = 13 bytes payload).

**RTC year:** Add 2000 to `year_offset` when writing CSV (same as MATLAB parser).

**Threading:** Run the parse loop in `threading.Thread` to avoid freezing the GUI.
Use `queue.Queue` to pass progress updates back to the main thread.

#### Constraints and Gotchas

- The Python `struct` module uses little-endian (`<`) to match Artemis Nano byte order.
- GPS packet on SD differs from GPS radio packet — use the SD format (includes altitude,
  uses 5-byte common header).
- `TYPE_TELEM_IMU` (`0x06`) is not written to SD; do not add it to the parser.
- The MATLAB parser uses `global` variables for file handles — the Python version should
  use a `dict` of open `csv.writer` objects instead.
- Large files (multi-hour deployments at 104 Hz) may be 100+ MB. Use streaming reads
  (`file.read(n)`) rather than loading the entire file into memory.

---

### U2 — ⭐⭐⭐ Firmware: Re-enable 9-DOF Madgwick (magnetometer heading)

**Status:** Planned  
**Related issues:** None (deliberate design choice, not a bug)  
**Files affected:** [`VertiSea.ino`](VertiSea.ino)

#### Motivation

The magnetometer and 9-DOF Madgwick code path are fully implemented but currently
disabled. Enabling heading output would allow wave direction analysis relative to
magnetic north, which is valuable for the Arctic TENG application.

#### Proposed Approach

In `loop()`, change:
```cpp
lastStabIMU = collectIMUData_ISM(imuStab, filterStab, stabCal, false, lpfStab);
```
to:
```cpp
lastStabIMU = collectIMUData_ISM(imuStab, filterStab, stabCal, true, lpfStab);
```

Before enabling, verify:
1. The `magCal` constants in the sketch are current (they are, per the calibration log).
2. The magnetometer is not saturated or disturbed by nearby ferromagnetic components.
3. The Madgwick `beta` parameter is appropriate for the expected motion dynamics.

Also update the `TYPE_TELEM_IMU` packet to transmit heading instead of (or in addition
to) vertical displacement, and update the ground station display accordingly.

---

### U3 — ⭐⭐⭐ Firmware: Configurable GPS sync timeout

**Status:** ✅ Implemented
**Related issues:** [Issue 1](IDENTIFIED_ISSUES.md#issue-1) (boot block)
**Files affected:** [`VertiSea.ino`](VertiSea.ino)

#### Motivation

`GPS_SYNC_TIMEOUT_MS = 100 ms` effectively disables GPS time sync. For deployments
where GPS lock is available at startup (clear sky, warm receiver), a longer timeout
(e.g., 120 s) would ensure the RTC is set to accurate UTC before logging begins,
making post-processing time alignment much easier.

#### Proposed Approach

Make the timeout a compile-time constant that is easy to change:
```cpp
// Set to 100UL for fast boot (no GPS sync), or 120000UL for full GPS sync
constexpr unsigned long GPS_SYNC_TIMEOUT_MS = 100UL;
```
Add a comment explaining the trade-off. Consider adding a `#define FAST_BOOT` flag
that sets the timeout to 100 ms, making the intent explicit.

---

### U4 — ⭐⭐ Python GUI: Supercapacitor voltage display

**Status:** ⛔ Obsolete — A14 was repurposed from supercap voltage to harvested current
**Related issues:** [Issue 15](IDENTIFIED_ISSUES.md#issue-15)
**Files affected:** [`vertisea_plot_v7.py`](vertisea_plot_v7.py)

#### Motivation

This was implemented for the former `TYPE_SUPERCAP` packet, but the hardware channel was
later repurposed for harvested current. `0x0A` was renamed and then retired because its
5 Hz point sample was biased. The GUI now shows current statistics from `0x0F`; it does not
and cannot display supercapacitor voltage with the current hardware.

#### Historical Proposed Approach (do not re-implement without a new voltage channel)

Add a `TYPE_SUPERCAP = 0x0A` constant and a handler in `update()`:
```python
TYPE_SUPERCAP = 0x0A
# In update():
elif p == TYPE_SUPERCAP and len(self.buffer) >= 5:
    pkt = self.buffer[:5]; del self.buffer[:5]
    _, ts10, voltage_mV = struct.unpack('<BHH', pkt)
    self.vcap_var.set(f"{voltage_mV / 1000.0:.2f} V")
```

Add a `vcap_var` `StringVar` and a label in the info panel (e.g., alongside the BME280
frame).

---

### U5 — ⭐⭐ Python GUI: Fix `TYPE_TELEM_IMU` plot labels

**Status:** ✅ Resolved (2026-03-30)
**Related issues:** [Issue 8](IDENTIFIED_ISSUES.md#issue-8)
**Files affected:** [`vertisea_plot_v7.py`](vertisea_plot_v7.py)

#### Motivation

The current plot titles and variable names are stale from a prior firmware version.
Correcting them makes the ground station display accurate and reduces operator confusion.

#### Proposed Approach

Completed. The ground station now has a 2×2 plot layout:
- **Top-left:** Pendulum IMU pitch & roll (from `TYPE_TELEM_IMU` `pitch_cdeg` / `roll_cdeg` fields, ÷100)
- **Top-right:** Pendulum−buoy tilt difference & rotor RPM (dual Y-axis)
- **Bottom-left:** Buoy IMU pitch & roll (from `stab_pitch_cdeg` / `stab_roll_cdeg` fields, ÷100)
- **Bottom-right:** Placeholder for future plot

Angle encoding changed from millidegrees (×1000, ±32.767°) to centidegrees (×100, ±327.67°)
to support the full ±70° operating range without `int16_t` overflow.

---

### U6 — ⭐⭐ Firmware: SD write error detection

**Status:** ⚠ Partially implemented — see Issue 3
**Related issues:** [Issue 3](IDENTIFIED_ISSUES.md#issue-3)
**Files affected:** [`VertiSea.ino`](VertiSea.ino)

#### Motivation

Silent SD write failures result in complete data loss with no operator indication.
Adding error detection allows the operator to know the deployment failed.

#### Proposed Approach

- Check `logFile` validity at the start of each write block.
- On write failure, set a global `sdError` flag.
- Change the LED heartbeat pattern when `sdError` is set (e.g., rapid 10 Hz blink
  instead of 1 Hz).
- Optionally attempt to re-open the file or create a new one.

---

### U7 — ⭐⭐ Firmware: Remove `while (!Serial)` boot block

**Status:** ✅ Implemented
**Related issues:** [Issue 1](IDENTIFIED_ISSUES.md#issue-1)
**Files affected:** [`VertiSea.ino`](VertiSea.ino)

#### Motivation

The current `while (!Serial)` call blocks boot indefinitely without a USB host. This
must be fixed before any unattended field deployment.

#### Proposed Approach

See [Issue 1](IDENTIFIED_ISSUES.md#issue-1) for the specific fix. This upgrade tracks
the implementation and testing of the fix.

---

### U8 — ⭐⭐ Python GUI: Wrap-aware telemetry timestamp

**Status:** ✅ Implemented
**Related issues:** [Issue 16](IDENTIFIED_ISSUES.md#issue-16)
**Files affected:** [`vertisea_plot_v7.py`](vertisea_plot_v7.py)

#### Motivation

The `ts10` timestamp wraps every ~11 minutes, causing the rolling plot x-axis to reset.
For long monitoring sessions this is confusing.

#### Proposed Approach

Track the previous timestamp and detect backward jumps:
```python
if t < self._last_t:
    self._t_offset += 655.35  # 2^16 * 0.01 s
self._last_t = t
t_abs = t + self._t_offset
```
Use `t_abs` for the x-axis. Initialise `_last_t = 0` and `_t_offset = 0.0` in
`__init__`.

---

### U9 — ⭐ Firmware: Log raw (uncalibrated) IMU data

**Status:** ✅ Implemented and hardware-verified 2026-09-03
**Related issues:** None  
**Files affected:** [`VertiSea.ino`](VertiSea.ino), [`vertisea_plot_v7.py`](vertisea_plot_v7.py), [`docs/binary_protocol.md`](docs/binary_protocol.md)

#### Motivation

The firmware now supports `IMU_RAW_ONLY 1` and the packed `TYPE_IMU_RAW` (`0x12`) record.
Each record contains both IMUs' accel in int16 milli-g, gyro in int32 mdps, and measured
`interval_us`. The boot calibration records remain present. This replaces the processed
fixed/stabilized/magnetometer records rather than adding a second reduced-rate stream.

#### Implemented Approach

One combined `0x12` record is written each IMU tick. The asymmetric integer widths are
deliberate: int16 is ample for milli-g, while int32 is required for the configured gyro
range. This reduces SD traffic and raises the achieved IMU rate while preserving values
needed for offline processing. The Python parser exports `<base>_imuRaw.csv`.

---

### U10 — ⭐ MATLAB: Robust parser — skip unknown packets

**Status:** ⛔ Obsolete — parser retired 2026-09-03
**Related issues:** [Issue 14](IDENTIFIED_ISSUES.md#issue-14)  
**Files affected:** None (historical file recoverable from git only)

#### Motivation

The MATLAB parser was deleted because it duplicated the Python schema but was no longer
used or tested. Do not recreate it. Robustness work belongs in `parse_binary_file()` in
`vertisea_plot_v7.py`.

#### Proposed Approach

Add a packet-size lookup table:
```matlab
packetSizes = containers.Map(...
    {1, 2, 3, 4, 5, 7, 8, 9, 10}, ...
    {36, 36, 12, 13, 6, 12, 36, 36, 2});  % payload bytes (excluding 5-byte header)
```
In the `otherwise` case, look up the size and `fread` that many bytes to skip the
packet, then `continue` instead of `break`.

---

### U11 — ⭐ Python GUI: CSV export from live telemetry

**Status:** Planned  
**Related issues:** None  
**Files affected:** [`vertisea_plot_v7.py`](vertisea_plot_v7.py)

#### Motivation

The ground station currently displays data but does not save it. Adding a CSV export
option would allow operators to capture a telemetry session for quick field review
without needing the SD card.

#### Proposed Approach

Add a "Start Recording" / "Stop Recording" button. When recording, append each parsed
packet to an in-memory list. On "Stop Recording", write to a CSV file via
`tkinter.filedialog.asksaveasfilename()`. Include columns: `timestamp_s`, `type`,
and the relevant fields for each packet type.

---

### U12 — ⭐ Firmware: RTC validity check for log filename

**Status:** 🔄 Completed in code 2026-09-04; hardware verification pending
**Related issues:** [Issue 2](IDENTIFIED_ISSUES.md#issue-2)
**Files affected:** [`VertiSea.ino`](VertiSea.ino)

#### Motivation

If the RTC battery is dead or the RTC has never been set, the log filename will be
`01010000.BIN` (or similar), potentially overwriting a previous log.

#### Proposed Approach

Check `rtc.getYear()` for a plausible value (e.g., >= 24 for 2024+). If invalid, use
a counter-based filename:
```cpp
// Try to find an unused LOGnnnnn.BIN filename
char fname[13];
for (int i = 0; i < 99999; i++) {
    snprintf(fname, sizeof(fname), "LOG%05d.BIN", i);
    if (!SD.exists(fname)) break;
}
```

**Implemented resolution (2026-09-04):** SD is initialized before collision checks. An unused
date-based name is preferred; an existing same-minute name or invalid RTC uses the first
unused `LOGnnnnn.BIN`. Exhausting all counter names is fatal instead of permitting overwrite.

---

### U13 — ⭐⭐ Firmware / Hardware: Rotor RPM measurement via Hall-effect sensor

**Status:** ✅ Implemented
**Related issues:** None (new feature)
**Files affected:** [`VertiSea.ino`](VertiSea.ino), [`docs/binary_protocol.md`](docs/binary_protocol.md), [`vertisea_plot_v7.py`](vertisea_plot_v7.py)

#### Motivation

The VertiSea buoy houses a rotor (TENG generator). Knowing the rotor RPM in real time
allows correlation of electrical power output with wave conditions and validates the
mechanical design. The original target was 0–400 RPM, but later hardware information put
peak operation near **2000 RPM**; firmware now uses a 3000 RPM noise-rejection ceiling with a single magnet
mounted on the rotor at a **20 mm radius**.

#### Historical Initial Implementation Checklist

> The checklist below records the first implementation, not the final design. Current code
> replaces the bool pulse flag with a monotonic counter, logs raw edges in `0x11`, derives
> the minimum period from `RPM_MAX_EXPECTED=3000`, and uses only the Python parser. The
> MATLAB parser was retired. U18 tracks the still-open suitability of the latching US1881.

1. **Hardware** — Wire US1881 pin 1 → 3.3 V, pin 2 → GND, pin 3 → Artemis GPIO (pin 2 or 3) with 4.7 kΩ pull-up to 3.3 V. Mount sensor on fixed frame; glue magnet to rotor at 20 mm radius, south pole facing sensor, gap ≤ 3 mm.
2. **`VertiSea.ino` — add `RPM_ENABLE` flag** — add `#define RPM_ENABLE 1` and `#define HALL_PIN 2` near the other deployment flags at the top of the file.
3. **`VertiSea.ino` — add `TYPE_RPM` packet type** — add `TYPE_RPM = 0x0C` to the `PacketType` enum.
4. **`VertiSea.ino` — add ISR and shared state** — declare `volatile uint32_t hallPulseUs` and `volatile bool hallNewPulse`; implement `hallISR()` to record `micros()` on each `FALLING` edge.
5. **`VertiSea.ino` — `setup()`** — inside `#if RPM_ENABLE`, call `pinMode(HALL_PIN, INPUT_PULLUP)` and `attachInterrupt(digitalPinToInterrupt(HALL_PIN), hallISR, FALLING)`.
6. **`VertiSea.ino` — `loop()`** — inside `#if RPM_ENABLE`, atomically consume the ISR pulse with `noInterrupts()`/`interrupts()`, compute `currentRPM = 60e6 / periodUs`, zero RPM after 12 s with no pulse, then log `TYPE_RPM` to SD and radio at 5 Hz.
7. **`docs/binary_protocol.md`** — document the `TYPE_RPM (0x0C)` packet: 5-byte header + 2-byte `uint16` RPM field = 7 bytes total.
8. **Historical MATLAB parser** — an `0x0C` case was added, but that parser was retired 2026-09-03.
9. **`vertisea_plot_v7.py`** — add `TYPE_RPM = 0x0C` handler and live numeric RPM display.
10. **Bench test** — with `USB_DEBUG 1`, spin the rotor by hand and confirm RPM prints to Serial at ~1 Hz; verify SD CSV contains plausible values; verify ground station displays RPM.

#### Hardware Required

| Item | Example part | Notes |
|------|-------------|-------|
| Unipolar latching Hall-effect switch | **Melexis US1881** (TO-92) | Open-collector output; latching — pulls LOW on south pole, releases on north pole. 2.5 V–24 V supply; 3.3 V compatible. |
| Pull-up resistor | 4.7 kΩ, 0402 or through-hole | From sensor OUT to 3.3 V (Artemis logic level). |
| Neodymium magnet | 5 mm × 2 mm disc, N35 or stronger | Mounted on rotor at 20 mm radius, pole face toward sensor. |
| Sensor mount | 3D-printed bracket or standoff | Position sensor gap ≤ 3 mm from magnet face at closest approach. |
| Wire / connector | 3-wire (VCC, GND, SIG) | Route away from high-current TENG leads to avoid EMI. |

**Sensor placement:** Mount the A3144 on the fixed (non-rotating) frame so that the
magnet sweeps past it once per revolution. The 20 mm radius gives a magnet tip speed
of `v = 2π × 0.020 m × (400/60) rev/s ≈ 0.84 m/s` — well within the sensor's
response time (switching frequency > 10 kHz).

**Pin selection:** All current Artemis Nano pins are accounted for (SPI on 4/11/12/13,
I²C on SDA/SCL, Serial1 on TX1/RX1, A14 for supercap, LED_BUILTIN). Any remaining
free digital GPIO (e.g. pin **2** or **3**) can be used. Both support
`attachInterrupt()` on the Artemis/Apollo3 platform.

#### Timing Analysis

| Parameter | Value |
|-----------|-------|
| Max RPM | 400 RPM |
| Min period (1 pulse/rev) | 150 ms |
| Min measurable RPM (timeout) | ~5 RPM (12 s timeout before reporting 0) |
| Required timestamp resolution | 1 ms (`millis()` is sufficient) |
| Polling approach viable? | **No** — 104 Hz IMU loop = 9.6 ms tick; a 150 ms pulse would be caught but jitter would be ±9.6 ms (±6.4% at 400 RPM). Use interrupt instead. |

An **interrupt-driven** approach (falling-edge ISR records `micros()` at each pulse)
gives sub-microsecond timestamp resolution, yielding RPM accuracy better than 0.1% at
400 RPM.

#### Software Design

**1. ISR and shared state (add near top of `VertiSea.ino`):**

```cpp
// ---- RPM measurement (Hall-effect sensor on HALL_PIN) ----
#define RPM_ENABLE 1          // set 0 to compile out entirely
#define HALL_PIN   2          // digital pin connected to Hall sensor output

#if RPM_ENABLE
volatile uint32_t hallPulseUs   = 0;   // micros() at last falling edge (written by ISR)
volatile bool     hallNewPulse  = false; // set true by ISR, cleared by loop()

void IRAM_ATTR hallISR() {
  hallPulseUs  = micros();
  hallNewPulse = true;
}
#endif
```

**2. `setup()` additions:**

```cpp
#if RPM_ENABLE
  pinMode(HALL_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(HALL_PIN), hallISR, FALLING);
  DBG_PRINTLN("Hall RPM sensor enabled on pin " TOSTRING(HALL_PIN));
#endif
```

**3. RPM computation in `loop()` (add alongside the 5 Hz telemetry block):**

```cpp
#if RPM_ENABLE
  static uint32_t lastHallUs  = 0;   // micros() of the previous pulse
  static float    currentRPM  = 0.0f;
  static uint32_t lastRpmSend = 0;

  // Consume new pulse atomically
  noInterrupts();
  bool   gotPulse = hallNewPulse;
  uint32_t pulseUs = hallPulseUs;
  if (gotPulse) hallNewPulse = false;
  interrupts();

  if (gotPulse && lastHallUs != 0) {
    uint32_t periodUs = pulseUs - lastHallUs;
    if (periodUs > 0) {
      currentRPM = 60.0e6f / float(periodUs);  // 1 pulse per revolution
    }
  }
  if (gotPulse) lastHallUs = pulseUs;

  // Zero RPM if no pulse for > 2 full revolution periods at min speed (5 RPM → 12 s)
  if (micros() - lastHallUs > 12000000UL) currentRPM = 0.0f;

  // Log and transmit RPM at 5 Hz (co-timed with IMU telemetry)
  if (nowMs - lastRpmSend >= TELEMETRY_INTERVAL_MS) {
    lastRpmSend = nowMs;
    uint16_t rpm_u16 = uint16_t(constrain(currentRPM, 0.0f, 65535.0f));

    // SD log
    if (!sdError) {
      writeHeader(TYPE_RPM, nowMs);
      logFile.write((uint8_t*)&rpm_u16, sizeof(rpm_u16));
    }

    // Radio telemetry
    struct __attribute__((packed)) RPMPacket {
      uint8_t  type;
      uint16_t timestamp_10ms;
      uint16_t rpm;
    } rpmPkt = { TYPE_RPM, uint16_t(nowMs / 10), rpm_u16 };
    sharedSerial.write((uint8_t*)&rpmPkt, sizeof(rpmPkt));
  }
#endif
```

**4. New packet type** — add to the `PacketType` enum:

```cpp
TYPE_RPM = 0x0C,  // rotor RPM — 5 Hz, uint16 (0–65535 RPM)
```

**5. Packet format** (add to [`docs/binary_protocol.md`](docs/binary_protocol.md)):

| Field | Type | Size | Description |
|-------|------|------|-------------|
| `type` | `uint8` | 1 B | `0x0C` |
| `timestamp_ms` | `uint32` | 4 B | `millis()` at log time |
| `rpm` | `uint16` | 2 B | Rotor speed in RPM (0–65535) |

Total packet size: **7 bytes**.

**6. Python ground station** — add `TYPE_RPM = 0x0C` handler in
[`vertisea_plot_v7.py`](vertisea_plot_v7.py) to display a live RPM readout.

#### Constraints and Gotchas

- **One magnet = one pulse per revolution.** If higher resolution is needed (e.g. for
  low-RPM accuracy), add more magnets evenly spaced and divide the computed RPM by the
  magnet count. With a single magnet, the minimum measurable RPM is limited by the
  timeout window (set to 5 RPM / 12 s above).
- **EMI from TENG output.** The TENG generates high-voltage pulses. Route the Hall
  sensor signal wire away from TENG leads and consider a 100 nF decoupling capacitor
  from sensor VCC to GND close to the sensor body.
- **Artemis `IRAM_ATTR`:** The Apollo3/Artemis platform does not require `IRAM_ATTR`
  on ISR functions (it has no IRAM distinction), but the attribute is harmless and
  documents intent. Remove it if the compiler warns.
- **`micros()` overflow:** `uint32_t` overflows after ~71 minutes. The subtraction
  `pulseUs - lastHallUs` handles wrap-around correctly as long as the period is less
  than 71 minutes (guaranteed at any measurable RPM).
- **`RPM_ENABLE` flag:** Mirror the pattern of `GPS_ENABLE` — set to `0` to compile
  out all Hall sensor code when the sensor is not physically connected.

---

### U14 — ⭐⭐⭐ Firmware / Hardware: Dynamic current measurement at IMU rate

**Status:** ✅ Core current capture implemented; follow-on hardware gaps remain
**Related issues:** None (new feature)
**Files affected:** `VertiSea.ino`, `vertisea_plot_v7.py`, `docs/binary_protocol.md`

#### Motivation

The original current-capture objective is complete and was exceeded: firmware requests
1000 Hz, achieves roughly 780–800 Hz in recent raw-IMU runs, logs raw ADC samples in
`TYPE_CURRENT_BLOCK` (`0x0E`) with measured timing, records scale constants in `0x0D`, and
transmits window statistics in `0x0F`. Current can be aligned to IMU data by timestamp.

What remains is **not** “dynamic current measurement”: true energy needs a battery/output
voltage channel, signed/bidirectional sensing needs an offset-aware calibration model, and
absolute current scale still needs the multi-level linearity check documented in
`docs/current_measurement_testing.md`.

**Historical motivation:** the former 5 Hz supercap/current point channel was too slow for a
pulsed TENG output and aliased the transients of interest.

#### Implemented Core and Remaining Follow-ups

1. ✅ **Hardware/current input** — current-sense output is connected directly to A14; ADC is
   configured for 14-bit (`analogReadResolution(14)`, `ADC_MAX = 16383`). Absolute gain still
   needs the documented multi-level linearity test.
2. **Implemented packet set** — `0x0D`, `0x0E`, and `0x0F` are current calibration,
   high-rate sample blocks, and radio/USB statistics. `0x10` is also occupied by LPF
   calibration; use the next free ID documented in `docs/binary_protocol.md` for any new
   packet. Historical note: as of
   2026-09-02: `0x0A` = `TYPE_CURRENT` (5 Hz), `0x0D` = `TYPE_CURRENT_CAL`,
   `0x0E` = `TYPE_CURRENT_BLOCK` (batched 1 kHz samples, SD), `0x0F` =
   `TYPE_CURRENT_STATS` (windowed statistics, radio). **`0x10` was the next free ID at that
   time.**
   Note the substance of this upgrade is now largely IMPLEMENTED: current is sampled at
   1 kHz — nearly 10× the 104 Hz originally proposed here — and logged with per-sample
   timestamps, so it can be correlated with IMU data by interpolation rather than by
   sharing a timestamp. What remains open is (a) true energy, which needs a *voltage*
   channel the hardware does not have, and (b) signed/bidirectional current, since the
   sample type is unsigned `uint16`. Retarget this entry at those two gaps.
3. ✅ **Independent high-rate sampling gate** — implemented at the top of `loop()` rather
   than inside the 104 Hz IMU block. `TYPE_CURRENT_BLOCK.span_ms` stores measured timing, so
   current and IMU can be aligned offline without forcing both channels to the same cadence.
4. ⚠ **Optional compile-time gate** — no `CURRENT_ENABLE` flag exists. Add one only if a
   deployment without the current hardware needs to reclaim the analog-read/SD overhead.
5. **Update both protocol consumers simultaneously** — `docs/binary_protocol.md` and
   `vertisea_plot_v7.py` (both `parse_binary_file()`/`_SD_PAYLOAD_BYTES` and, if
   transmitted, the live `update()` handler).

#### Current Constraints

- **SD write budget.** SD block-write stalls are the dominant remaining limit on IMU rate.
  The current firmware uses `SD.begin(CS_SD)` (the SD 1.3.0 half-speed path), not
  `SPI_FULL_SPEED`. `IMU_RAW_ONLY` reduces IMU traffic, but current blocks still create
  209-byte bursts. See U19; do not assume bandwidth is “fine” without measured timing.
- **Do not add the raw current waveform to radio telemetry.** The link is 115200 baud and
  `TYPE_TELEM_IMU` is deliberately decimated. Live current is already represented by the
  1 Hz `TYPE_CURRENT_STATS` packet.
- **The `TelemetryPacket` struct is full at 13 bytes** for practical purposes; add a new
  packet type rather than extending it, or every existing parser breaks at once.
- **EMI.** Same caution as the Hall sensor (U13): TENG output is high-voltage pulsed.
  Keep sense leads away from the I²C bus — the IMUs share that bus and have already proven
  sensitive to bus disturbance (Issues 25/27).
- **Capture a fresh sample log** as part of this work. The `SampleData/` captures predate
  2026-04-03 and contain no `TYPE_RPM`, let alone a current packet; both parsers should be
  exercised against a log that actually contains the new type.

---

### U15 — ⭐⭐ Firmware: RPM validity filter exploiting the spring-driven ramp

**Status:** Deferred (analysed 2026-09-02, not implemented)
**Files affected:** `VertiSea.ino`
**Related:** `TYPE_HALL_EDGE` (0x11) makes this an *offline* decision, reducing urgency.

#### Motivation

Rotor speed is driven by a spring releasing over ~12 s, so RPM changes smoothly and any fast
discontinuity in the measured period is non-physical. That is a better validity criterion
than the fixed `RPM_MAX_EXPECTED` cap, which is speed-independent and therefore either too
loose at low RPM or too tight at high RPM.

#### Analysis (the useful part — keep this)

For a roughly constant-torque release, ω ramps ~linearly, so pulse *n* arrives at t ∝ √n and
the consecutive-period ratio is **scale-free** (independent of peak RPM and spin-up time):

| Pulse transition | Legitimate period change |
|---|---|
| 1 → 2 | 23.3% |
| 3 → 4 | 11.9% |
| 8 → 9 | 5.4% |

Versus the corruption signatures to reject:
- dropped pulse → period **×2.00** (+100%)
- spurious pulse → period **×0.50** (−50%)

So a "reject if the period changes more than ±50% per pulse" rule separates real dynamics
from glitches at every speed.

#### Why it was NOT implemented

**The band breaks down at low RPM.** With a ~1000 RPM/s rise rate and one magnet:

| At | Period | Legitimate change between pulses |
|---|---|---|
| 200 RPM | 300 ms | **150%** ← a ±50% band would reject valid data |
| 500 RPM | 120 ms | 24% |
| 2000 RPM | 30 ms | 1.5% |

The early rise is exactly where the change is largest, so a naive band corrupts the most
dynamic part of the record. A speed-dependent band would work but needs the very RPM estimate
it is trying to validate.

#### If revisited

1. **Add magnets first.** 4 magnets → ~13 pulses per 200 ms interval and worst-case per-pulse
   change ~38%, which makes the band viable *and* fixes low-RPM resolution. Cheaper and more
   robust than firmware cleverness. Note the latch needs each magnet to present a field
   reversal — bench-check reliability at spacing (see the `PULSES_PER_REV` comment).
2. Prefer filtering **offline** from `TYPE_HALL_EDGE` data, where the full time series is
   available and the algorithm can be changed without reflashing.
3. If done on-board, make the band a function of the current RPM estimate, and widen it below
   ~500 RPM.

---

### U16 — ⭐⭐⭐ Hardware: anti-aliasing and input-range review on the current sense line

**Status:** Proposed (2026-09-02), but the original corner/clipping recommendation needs revision
**Files affected:** hardware only

#### Motivation

Analysis of scope record `scope_466_2.csv` (20 kHz, 13 s, the 12 s discharge) shows the
current signal carries **~3.7 kHz ripple at σ ≈ 0.171 V, about 8.3% of the 2.06 V envelope
peak**, on top of the slow envelope. The firmware samples at ~377 Hz with **no
anti-aliasing filter**, so that content is folded into the measurement.

Empirically this is currently harmless — decimating the 20 kHz truth to 377 Hz changes peak by
−0.60%, ∫I·dt by −0.12% and ∫I²·dt by −0.35% — because the ripple is zero-mean about a slowly
varying envelope and averages out of the integrals. But that is a fortunate property, not a
designed one, and it would not survive a change in the ripple's amplitude or symmetry.

#### Proposed approach

The original proposal said a ~500 Hz corner was “well below” the Nyquist frequency of a
~377 Hz sampler. That is mathematically wrong: Nyquist was ~188.5 Hz then and is roughly
390–400 Hz at the more recent ~780–800 Hz aggregate rate. Select the analog corner from the
**minimum validated achieved rate**, desired envelope bandwidth, and required attenuation;
a single pole near 500 Hz is not an anti-alias filter for either measured rate. More than one
pole may be needed if the 3.7 kHz component must be strongly rejected.

#### Related: ADC clipping (act on this first)

The older scope record peaks at **2.4403 V** against the Apollo3's 2.000 V reference. Newer
instrument testing, however, found a real filtered peak near **125 mA (62% of range)** and
isolated full-scale samples attributable to spikes rather than sustained clipping. Do not fit
a divider solely from the old scope trace. First complete the secure-connection repeat and
linearity/headroom checks in `docs/current_measurement_testing.md`. If representative data
shows consecutive full-scale samples, fit a divider and update `CURRENT_DIV_RATIO`; the
self-describing `TYPE_CURRENT_CAL` record preserves old-log interpretation.

---

### U17 — ⭐ Note: current sample rate is empirically sufficient — do not re-open without cause

**Status:** Resolved (2026-09-02) — recorded to prevent repeated work

The achieved current sample rate is **~377 Hz**, not the 1000 Hz requested by
`CURRENT_RATE_HZ` (the loop is the bottleneck, not the ADC). This was investigated and found
to be **sufficient**, by decimating a 20 kHz scope capture of a real discharge and
recomputing the logged statistics:

| Rate | Peak error | ∫I·dt error | ∫I²·dt error |
|---|---|---|---|
| 1000 Hz | −0.47% | +0.03% | +0.07% |
| **377 Hz (achieved)** | **−0.60%** | **−0.12%** | **−0.35%** |
| 104 Hz | −0.47% | +0.04% | +0.07% |
| 20 Hz | −22.2% | −12.0% | −27.9% |

The discharge is a ~12 s envelope (≈2 s rise, ≈10 s decay), so 377 Hz oversamples it ~25×.
Going to 1 kHz buys ~0.1%.

**Consequences:**
- `TELEM_ENABLE 0` exists and works, but is **not needed** for sample-rate reasons.
- `IMU_RAW_MODE` was designed and then dropped: its only remaining justification was SD
  bandwidth, and there is no bandwidth problem. It was **never** needed for post-processing,
  because the IMU low-pass filter is exactly invertible (see `TYPE_LPF_CAL`, 0x10).
- **Update 2026-09-03 (see U19):** the "no further rate work justified" conclusion below
  was reached at 377 Hz. Raising I²C to 400 kHz for unrelated reasons took current
  sampling to **693 Hz aggregate / 767 Hz within-block** with no ADC changes at all,
  because the sampler consumes spare loop time. The point stands that *dedicated* timer/DMA
  ADC work is unjustified, but the rate is now known to scale with whatever loop time is
  freed elsewhere.
- Do not pursue timer/DMA ADC work merely to improve envelope accuracy at the existing rate.
  **Update 2026-09-04:** deterministic sample cadence and reduced loop coupling are now an
  explicit stability requirement, so U23 records a justified DMA prototype. It must be judged
  on timing isolation and loop behavior, not on a higher headline sample rate.

---

### U18 — ⭐⭐⭐ Hardware: re-evaluate the US1881 *latching* Hall sensor vs a non-latching switch

**Status:** Open concern (raised 2026-09-02, by the user)
**Files affected:** hardware; possibly `PULSES_PER_REV` comment in `VertiSea.ino`

#### The concern

Rotor RPM uses a **Melexis US1881, which is a latch**: its output holds state until it sees a
field **reversal**, not merely field removal. A single magnet works only because a magnet
passing *tangentially* presents a bipolar signature — the trailing return-flux lobe is what
resets the latch.

That reset is a **geometry-dependent** effect. Air gap, magnet size/strength, and how squarely
the magnet sweeps the sensor face all determine whether the trailing lobe crosses `Brp`. If it
does not, the latch never resets and subsequent edges are **silently lost** — RPM reads low or
zero with no error indication anywhere in the data.

The user observed that hand-waving a magnet is **sometimes inconsistent**, which is exactly
what a marginal latch reset would look like.

#### Evidence so far (inconclusive, and that is the point)

| Log | Edges | Period range |
|---|---|---|
| `09021858` | 50 | 124 ms … 13.75 s |
| `09021931` | 8 | 693 ms … 10.36 s |

Analysis found **no contact bounce** (zero intervals < 20 ms) and **no 2:1 alternation** in
consecutive period ratios — the signature you would expect if every other toggle were being
dropped. So there is no positive evidence of failure.

But hand-waving cannot separate "sensor is reliable" from "sensor is marginal": wave speed,
distance and orientation vary every pass, so a missed toggle looks identical to a slow wave.
**Do not treat the clean diagnostics as validation.**

#### Recommendation

A **non-latching unipolar switch** — e.g. Allegro A3144, or A1220 (which behaves switch-like
with hysteresis) — releases on field *removal* rather than reversal. For single-magnet
tachometry that is inherently more robust: no dependence on a trailing reverse lobe, so no
geometry-sensitive failure mode.

Note for the record: the original recommendation of a *latching* part for this application was
probably a mistake. It works on the bench, but it imposes a constraint (bipolar field
signature) that single-magnet rotary sensing does not naturally satisfy, and its failure mode
is silent.

#### Test protocol before accepting either sensor

1. Mount the magnet in its **final** geometry — results from a hand-held test do not transfer.
2. Spin at a **known steady speed**; compare logged edge count against expected revolutions.
   Any shortfall is a dropped toggle.
3. Cross-check derived RPM against an independent measure (strobe, or high-frame-rate video).
4. Repeat at the slowest expected speed *and* near peak — latch reset margin can vary with
   sweep speed because the field slew rate changes.
5. If edges are missing, change the sensor. No firmware change can recover an edge the sensor
   never emitted.

#### Firmware readiness either way

`TYPE_HALL_EDGE` (0x11) logs every raw edge timestamp, so whichever sensor is fitted, the data
needed to *diagnose* dropped edges offline is already being captured. `PULSES_PER_REV` handles
added magnets, and its comment documents the tangential-pass requirement — that comment must be
updated if a non-latching part is adopted, since the reasoning no longer applies.

---

## Completion Log

| # | Date | Summary | Confirmed by |
|---|------|---------|-------------|
| U1 | — | `parse_binary_file()`, `write_csvs_from_parsed()`, and "Load BIN File" button with full parse→CSV→plot flow added to `vertisea_plot_v7.py` | Code audit 2026-04-23 |
| U5 | 2026-03-30 | Fixed `TYPE_TELEM_IMU` plot labels; changed angle encoding to centidegrees (×100) | Code review |
| U3 | — | `GPS_SYNC_TIMEOUT_MS` made a named constant (120 000 ms); `#define FAST_BOOT`-style comment added | Code audit 2026-04-23 |
| U4 | — | Historical supercap display was implemented, then made obsolete when A14 became the harvested-current channel and `0x0A` was retired | Source/history audit 2026-09-04 |
| U6 | — | `sdError` flag, write-size check, 4 Hz LED flash pattern, and `TYPE_STATUS` radio packet implemented | Code audit 2026-04-23 |
| U7 | — | `while (!Serial)` replaced with a 3 s USB-wait gated on `#if USB_DEBUG`; field build boots immediately | Code audit 2026-04-23 |
| U8 | — | `_ts10_last` / `_ts10_offset` wrap-detection added to `VertiSeaGUI.update()` in `vertisea_plot_v7.py` | Code audit 2026-04-23 |
| U12 | — | `localTimeValid` check (year ≥ 2024) + `LOG%05lu.BIN` counter fallback implemented in `setup()` | Code audit 2026-04-23 |
| U13 | 2026-04-23 | `RPM_ENABLE`/`HALL_PIN` flags, `hallISR()`, `setup()` init, loop RPM block added to firmware; `TYPE_RPM (0x0C)` added to MATLAB parser, Python ground station, and binary protocol doc | Implementation |
| U9 | 2026-09-03 | Added `IMU_RAW_ONLY` and combined `TYPE_IMU_RAW (0x12)`; widened gyro to int32 mdps and verified on hardware | Hardware log + parser verification |
| U14 | 2026-09-03 | Added high-rate current blocks, self-describing calibration, and live window statistics; voltage/signed-current follow-ups remain separate | Hardware logs + parser/USB verification |


---

## U19 — Reaching a true 104 Hz IMU rate (and why interrupts are not the answer)

**Status:** 🔄 Partially implemented. Measured-dt correctness and byte-reduction work are
complete; a true 104 Hz rate still needs SD buffering/latency work. Cross-reference:
`IDENTIFIED_ISSUES.md` Issue 34.

### Where the time actually goes

Measured with the `interval_us` field added 2026-09-03, over `09031050` (400 kHz I²C,
5027 IMU samples, 54.19 s):

| Interval band | Share |
|---------------|-------|
| 9500–10000 μs (on time) | **76.22%** |
| 11000–15000 μs | 18.03% |
| 15000–20000 μs | 5.03% |
| 30000–70000 μs | 0.56% |

Median = 9570 μs, which is exactly the gate threshold (`IMU_INTERVAL_US - 50`). So the
sampler already fires on the first eligible loop pass three times out of four. **Excess
time attributable to the long tail is 6.09 s of 54.19 s (11.2%); eliminate it and the rate
is 104.52 Hz.** There is no need to make anything faster — only to stop the interruptions.

### What causes the tail

SD writes, not sensor I/O. Per IMU tick the firmware writes ~108 bytes
(38 + 38 + 17 + 3 headers), so a 512-byte SD block fills every `512/108 = 4.74` ticks.
Observed spacing between long intervals: **5 records (538×), 4 (412×), 3 (219×)** — a
direct match. `TYPE_CURRENT_BLOCK`'s 209-byte burst is a secondary contributor (present in
23.6% of long intervals vs 2.4% of on-time ones) but is too infrequent (~6.9 Hz) to account
for 1193 long intervals on its own.

### Side effect: current sampling nearly doubled

Worth recording because it was not the goal. Raising I²C 100 → 400 kHz moved current
sampling from 373 Hz to **693 Hz aggregate / 767 Hz within-block** (1.86×), against an
IMU gain of only 1.04×. Current sampling is ungated spare-loop-time work, so it absorbs
freed latency directly, whereas the IMU is capped by its 104 Hz gate. This supersedes the
U17 conclusion that "no further rate work is justified" — that held at 377 Hz, and the
sampler has since been shown to scale with available loop time.

The residual ~10% aggregate-vs-within-block gap is ~16 ms of dead time per block, again
the 209-byte SD write — the same bottleneck as the IMU tail, so option 1 below helps both.

### Implemented and Remaining Options

1. ✅ **Reduce bytes per tick** — implemented with retired `0x0A` and `IMU_RAW_ONLY` /
   `TYPE_IMU_RAW` (`0x12`). The final lossless record uses int32 gyro, so it is larger than
   the first 6×int16 estimate, but hardware verification still raised the IMU rate to about
   97.5 Hz.
2. ⚠ **Larger write buffering** — accumulate a full 512-byte block in RAM and write once, so
   the stall lands on a predictable boundary instead of mid-tick.
3. ⚠ **1 MHz Fast-Mode-Plus I²C** — only worth trying after buffering. All bus devices are
   rated ≥400 kHz and the ISM330DHCX supports 1 MHz, but I²C is no longer the limiter:
   going 100 → 400 kHz bought only 88.94 → 92.75 Hz.

### Rejected: doing IMU acquisition and processing inside a timer ISR

Recorded so it is not re-proposed. The loop is **I/O-bound**, not scheduling-bound:

- An ISR cannot usefully do the work. The Apollo3 Wire library is blocking and not
  interrupt-safe; performing two ISM330DHCX reads plus an MMC5983MA read inside an ISR
  would either deadlock or stall interrupts for milliseconds. Running Madgwick there is
  worse still.
- The delay is not caused by *late dispatch*. Three quarters of ticks already fire on the
  first eligible pass; a timer would not improve those, and for the remaining quarter the
  loop is blocked inside an SD write that an interrupt cannot preempt safely.
- It would convert jitter into **data loss**: an ISR firing during an SD block write must
  either drop the sample or queue it, which is exactly the buffering of option 2 without
  its simplicity.

A DMA-backed or double-buffered SPI SD driver would address the real bottleneck, but that
is a driver/filesystem project, not a scheduling change. It is now tracked explicitly as U25.

**Scope clarification (2026-09-04):** U24 does not propose doing I²C or Madgwick inside a
timer ISR. It proposes a main-loop-submitted, callback-driven IOM state machine so the CPU can
do other work while bytes are on the bus. That may improve responsiveness, but it does not
invalidate the conclusion above: it cannot shorten wire time and is not expected to remove
the SD-dominated interval tail by itself.


---

## U20 — Bench-test IMUs aggressively, and record that you did

**Status:** Practice note, not a code change. Recorded because it has already paid off twice.

During the 2026-09-03 `IMU_RAW_ONLY` validation the operator deliberately moved both IMUs
**fast and hard**, explicitly to avoid hiding defects that gentle motion would mask. That
choice is why two bugs were caught in one afternoon:

- The **`int16` gyro overflow** (Issue 35). Slow motion stays under 32.767 dps, so a gentle
  test would have produced a clean-looking log and the corruption would have surfaced only
  in deployment data — where it would have been indistinguishable from real dynamics.
- The **measured-`dt` fix** (Issue 34). The stall/on-time attitude ratio (1.001 → 1.924)
  is only visible when there is enough angular rate for a mistuned dt to matter.

### The corollary: aggressive testing biases the statistics it produces

The same run showed 0.10% of gyro samples pinned at the sensor's ±573 dps rail. That figure
is an **upper bound from deliberate worst-case excitation, not an expected duty cycle** —
hand-shaking a sensor easily exceeds a moored buoy, since 573 dps is ~1.6 rev/s. It would be
a mistake to "fix" it by moving to `ISM_1000dps` and halving resolution on the strength of a
bench number.

**So: shake hard to find bugs, but do not size ranges from shake data.** Range decisions need
a representative motion profile. Both facts should be recorded together, because a future
reader who sees only "0.10% clipping" will draw the wrong conclusion.

### Practical guidance

1. **Always include a hard-motion segment** in IMU bench validation — rotate through all
   three axes near the configured full scale.
2. **Check for rail-pinning explicitly**, not just for plausible ranges: count samples at
   exactly the theoretical maximum. A repeated *identical* extreme value is the signature of
   saturation; noise does not produce the same number 14 times.
3. **Note the excitation level in the log's changelog entry.** "Verified on hardware" means
   little without knowing whether the test could have exposed the failure mode in question.
4. **Do not confuse structural validation with range validation.** A synthetic round-trip
   test confirms transport; only real data at realistic amplitude confirms the chosen type
   can hold the values. The `int16` gyro bug passed a green round-trip test.


---

## U21 — Offline orientation estimation in the GUI parser (VQF and alternatives), opt-in

**Status:** Proposed by the user 2026-09-03. Not implemented.

### Why this is now worth doing

With `IMU_RAW_ONLY 1` the SD log contains **no attitude at all** — just uncalibrated accel
(milli-g), gyro (mdps) and the measured `interval_us` per tick. Attitude *has* to be computed
offline. That is a constraint, but it is also an opportunity: offline there is no 104 Hz
budget, so filters that are impractical on an Apollo3 become free.

Candidates, roughly in order of expected benefit:

1. **VQF** (Laidig & Seel) — designed for exactly this problem: gyro-bias estimation plus
   magnetic-disturbance rejection, and it does not need magnetometer data to produce good
   pitch/roll. Notably robust under sustained linear acceleration, which is the buoy's normal
   condition and the weakest point of Madgwick.
2. **Madgwick with a properly tuned beta** — the cheapest experiment. The firmware runs
   `beta = 0.5` (set for fast bench convergence, never tuned for wave dynamics; 0.041 is the
   author's AHRS recommendation). Re-running offline at several betas would show how much of
   the current attitude error is just mistuning.
3. **Mahony** — useful as a cross-check; different failure modes from Madgwick.
4. **Complementary / band-limited tilt** — a low-order sanity reference. Under mostly
   quasi-static tilt, `atan2` of the filtered accel is a hard-to-beat baseline, and if a fancy
   filter cannot beat it that is diagnostic.

**Use the logged `interval_us` per sample, not a nominal rate.** This is the whole lesson of
Issue 34 — the loop does not achieve 104 Hz, and a fixed-dt offline filter would reintroduce
the exact bug that was just removed from the firmware.

### The user's constraint: it must be optional

Explicitly requested: **conversion must not become slow.** A 6222-record log is trivial, but
`currentFast` already reaches 51000 rows in 64 s, so a multi-hour deployment will be large,
and a Python-loop AHRS over millions of samples is not instant.

Suggested shape:

- A **checkbox / dropdown next to "Load BIN File"**: *Compute orientation* — off by default,
  with the algorithm selectable. Default off means the existing fast path is unchanged and
  nobody is surprised by a slow conversion.
- Write orientation to a **separate CSV** (e.g. `<base>_orientation.csv`) rather than adding
  columns to `_imuRaw.csv`. Keeps the raw file a faithful record of what was logged, lets
  several algorithms coexist as separate files, and avoids re-parsing the `.BIN` to try
  another filter.
- Include the algorithm name and its parameters in that CSV (or a sidecar), so a file is
  self-describing. The `0x10` `TYPE_LPF_CAL` record already sets this precedent.
- **Report timing** after conversion ("orientation: 1.2 M samples in 8.4 s"), so the cost is
  visible rather than mysterious.
- Consider a **progress indicator** or a sample-decimation option for very large files.

### Implementation notes

- `vqf` is on PyPI, but adding a dependency conflicts with the current "stdlib +
  pyserial + matplotlib" footprint, and pyserial is *already* missing in at least one
  environment used for this project. Prefer **graceful degradation**: if the import fails,
  grey out that option with a tooltip rather than crashing the GUI on startup.
- NumPy would make this far faster and is a matplotlib dependency already present — worth
  confirming rather than assuming.
- Apply the `0x08`/`0x09` bias+scale first; optionally reproduce the `0x10` LPF. Whether to
  filter before fusing is itself a question worth testing, since VQF has its own internal
  filtering and double-filtering may hurt.
- **Validation:** run against a log captured with `IMU_RAW_ONLY 0`, where the firmware's own
  Madgwick output is present in the same file. That gives a direct comparison on identical
  data, which is the cleanest possible check and costs nothing extra to collect.

### Open question worth settling first

If offline orientation becomes routine, does the firmware still need Madgwick at all? It
would still be needed for live telemetry (`vertDisp`, attitude on the GUI) — but if the
field configuration is `TELEM_ENABLE 0`, nothing consumes it, and the ~46 μs/tick plus the
complexity could go. **Do not act on that without deciding the telemetry story**, since
removing it would make live attitude impossible to restore cheaply.


---

## U22 — Apply despiking to the on-board current statistics (`TYPE_CURRENT_STATS`, 0x0F)

**Status:** Proposed 2026-09-03, after `current_filter_test.py` quantified how much the
unfiltered statistics are distorted. Not implemented.

### The concrete problem: the reported peak is 59.6% too high

`TYPE_CURRENT_STATS` currently accumulates from **raw** samples. The peak in particular is a
plain running maximum (`VertiSea.ino` ~L1653):

```cpp
if (counts > statPeakCounts) statPeakCounts = counts;
```

A running max over raw data is maximally sensitive to exactly the artefact this channel has.
On `09031702` four isolated single-sample transients hit full scale, so:

| Statistic | Raw | After median-5 | Error |
|-----------|-----|----------------|-------|
| **peak_mA** | **200.00** | **125.35** | **+59.6%** |
| charge_mC | 690.5 | 710.6 | −2.8% |
| i2t_mA2s | 53546 | 55478 | −3.5% |
| RMS mA | 30.23 | 30.77 | −1.8% |

The peak error is the serious one. **`peak_mA` currently reports the ADC's full-scale value,
not the harvester's peak output** — an operator reading the live panel would conclude the
system is clipping when the real peak is 125 mA, 62% of range. See
`docs/current_measurement_testing.md` for why those samples cannot be real (a current cannot
rise 80% of range and return inside one 1.2 ms interval).

Note the integrals err in the *opposite* direction and are **understated**, because dropouts
outnumber positive spikes 221:104. So this is not a single bias that can be corrected with one
scale factor — peak and integrals need different treatment.

### Why do it on-board rather than only in post-processing

The SD path already has a fix available: `current_filter_test.py` filters `_currentFast.csv`
(from `0x0E`), and that work is separately proposed for the GUI converter. But `0x0F` is
**radio/USB-only and never written to SD**, so its numbers cannot be repaired after the fact.
Whatever the firmware computes is all the ground station will ever see. If the live panel is
meant to be trustworthy, the filtering has to happen before accumulation.

### Suggested implementation

A 3- or 5-sample median on the ADC stream, applied **once**, feeding both the statistics and
the `0x0E` block:

1. Keep a tiny ring buffer of the last 3 (or 5) raw counts in the high-rate sampling block.
2. Take the median and use it for `statPeakCounts`, `statCharge_mC`, `statI2t_mA2s`.
3. **Decide deliberately whether `0x0E` stores raw or filtered.** Recommendation: **keep
   `0x0E` raw.** It is the archival record, filtering is not reversible, and the offline tool
   already does a better job with a symmetric window. Filtering only the statistics keeps the
   raw data intact while making the live display honest — but it does mean `0x0F` and `0x0E`
   will no longer agree exactly, which must be documented or it will look like a bug.

**Cost is negligible.** A 3-median is two comparisons; a 5-median is a small sorting network.
Compare with the ~46 μs/tick that Madgwick already costs. This will not affect the sampling
rate, which is SD-write-bound (Issue 34), not CPU-bound.

**A causal filter is unavoidable on-board and is a real limitation.** The offline median is
centred (symmetric), using samples either side. In firmware only past samples exist, so a
running median introduces a lag of (w−1)/2 samples — 1 sample at w=3, 2 at w=5, i.e. 1.2–2.4 ms.
Irrelevant for 1 Hz statistics, but it means the on-board and offline results will differ
slightly even with the same window. **Do not treat a small mismatch as a defect.**

### Alternatives considered

- **Clamp to a plausible maximum instead of filtering.** Simpler, but it needs a magic
  threshold that changes whenever `CURRENT_DIV_RATIO` or the harvester changes, and it cannot
  fix the dropout side at all. Rejected.
- **Report a high percentile (e.g. p99) instead of the max.** Statistically cleaner, but it
  needs the window's samples retained — memory the Apollo3 would rather not spend — and "peak"
  is a more natural field for an operator to read than "p99".
- **Analog RC filter at the sense point.** Fixes it for every consumer at once and is arguably
  the *right* answer, since the transients are a hardware coupling problem. Worth raising with
  the EE. Does not remove the value of the software fix, because existing hardware is fielded.

### Validation plan

1. Extend `current_filter_test.py` to also compute the `0x0F` quantities (peak, charge, i2t,
   integ_s) both raw and filtered, so the firmware's numbers can be checked against an
   independent implementation on the same data.
2. Simulate the **causal** median offline and compare against the centred version, to confirm
   the difference is the predicted 1–2 samples of lag and nothing more.
3. After flashing, compare a live `0x0F` reading against the same window computed offline from
   `0x0E`. They should agree to within the causal/centred difference.

**Do not implement this before the linearity check** (`docs/current_measurement_testing.md`,
capture #2). A gain error would shift every one of these numbers, and it would be unhelpful to
tune the filtering against a mis-scaled baseline.


---

## U23 — Timer-triggered ADC DMA with double buffering

**Status:** Proposed 2026-09-04. Hardware/HAL feasibility confirmed from the Apollo3
datasheet and the AmbiqSuite 2.4.2 HAL bundled with the locally installed SparkFun Apollo3
Arduino core 1.2.1. Not prototyped or compiled.

**Priority:** ⭐⭐⭐ High as a timing-stability experiment; not required for current-channel
accuracy at the presently achieved rate.

### Motivation

The harvested-current ADC is currently polled at the top of every `loop()` pass:

```cpp
uint16_t counts = analogRead(A_PIN);
```

This has two undesirable architectural effects even though the resulting ~780–800 Hz rate is
already sufficient for the measured 12 s discharge envelope:

1. The sample cadence inherits every loop stall, including I²C activity, serial writes, and
   209-byte current-block SD writes.
2. Every loop pass performs an ADC conversion and all sample bookkeeping before other tasks
   can run. The 1000 Hz request is therefore a loop-load request rather than a hardware-timed
   sample rate.

ADC DMA would decouple **when the signal is sampled** from **when the main loop is available to
process or write it**. The primary expected benefit is deterministic sample timing and reduced
loop jitter, not a scientifically necessary increase in sample rate. It also becomes the
appropriate path if a future requirement targets the ~3.7 kHz ripple rather than only the slow
envelope (U16/U17).

### Why it is feasible on this hardware

The Apollo3 has a 14-bit ADC rated up to 1.2 MS/s and a dedicated ADC DMA path. The installed
AmbiqSuite HAL provides:

- `am_hal_adc_initialize()`, `am_hal_adc_configure()`, and
  `am_hal_adc_configure_slot()`;
- `AM_HAL_ADC_REPEATING_SCAN` and hardware trigger selection;
- `am_hal_adc_configure_dma()` with target address and sample count;
- DMA-complete (`AM_HAL_ADC_INT_DCMP`), DMA-error (`AM_HAL_ADC_INT_DERR`), and FIFO-overrun
  interrupts;
- `am_hal_adc_samples_read()` to decode DMA-buffer words; and
- `am_hal_adc_status_get()` for DMA completion/error/in-progress state.

The RedBoard Artemis Nano variant maps Arduino `A14` to physical pad 35, while the Arduino
analog alias is 14. The exact `AM_HAL_ADC_SLOT_CHSEL_*` value must be derived from the core's
analog mapping during the prototype — **do not assume the Arduino number is the HAL channel
enumeration**.

### Proposed architecture

1. Add an opt-in compile-time flag such as `CURRENT_ADC_DMA`, defaulting to `0` until verified.
2. When enabled, do not call `analogRead()` anywhere; Arduino `analogRead()` reconfigures/owns
   the same ADC peripheral and must not be mixed with direct HAL DMA operation.
3. Configure one 14-bit ADC slot for A14 with the existing internal 2.0 V reference and no
   hardware averaging initially, preserving the current conversion semantics.
4. Drive conversions from a hardware timer at a deliberately selected fixed rate. Start with
   **1000 Hz** to isolate the architecture change from signal-processing changes. Confirm the
   exact Apollo3 Timer 3 / ADC trigger route on hardware rather than using a software trigger
   from `loop()`.
5. Use two aligned DMA buffers (for example, 100 or 128 samples each). On DMA-complete:
   - record only completion/error state and immediately arm the alternate buffer;
   - never run statistics, SD writes, floating-point conversion, or telemetry inside the ISR;
   - detect an occupied alternate buffer as a real overrun instead of silently overwriting it.
6. In `loop()`, drain completed buffers, update current statistics, and enqueue raw counts for
   SD. Keep `TYPE_CURRENT_BLOCK` (`0x0E`) raw and archival.
7. Timestamp from the hardware sampling schedule, not from buffer-drain time. A 100-sample
   block at 1000 Hz spans 99 ms from first to last sample. The existing `span_ms` field can
   still represent that, so no packet change is required for the first prototype.
8. Separate diagnostics:
   - requested hardware sample rate;
   - DMA buffers completed;
   - DMA/FIFO errors;
   - buffers lost because the consumer fell behind; and
   - SD queue high-water mark.
   The current `n_dropped` definition measures a polling request/reality gap and will need a
   new meaning or replacement in the DMA build.

### Important constraints

- **DMA does not fix SD blocking.** It prevents SD stalls from moving ADC sample times, but a
  long enough stall can still fill both buffers. A RAM queue or larger ring between DMA and SD
  is required for real isolation.
- **Do not infer integration `dt` from loop time.** With hardware-timed conversion, each sample
  uses the configured period. Buffer completion time is not the sample time.
- **DMA completion is not automatically continuous ping-pong.** The HAL configures a finite
  target/count and halts on DMA completion/error by default. The ISR/state machine must re-arm
  the alternate target promptly and prove there is no gap between buffers.
- Buffers and HAL pointers must meet the required 32-bit alignment and SRAM-access rules.
- Higher sampling rates increase SD traffic and can make the existing SD bottleneck worse.
  Raising the rate above 1 kHz should be a separate, evidence-driven experiment.
- U22's causal despiking should run while draining buffers, not in the DMA ISR. Raw `0x0E`
  samples should remain unchanged.

### Staged validation

**Stage A — isolated ADC sketch:** A14 only, no sensors or SD. Feed a function-generator square
wave and verify exact sample count, interval, buffer-boundary continuity, and no FIFO/DMA errors.

**Stage B — synthetic load:** Run the normal loop workload with SD writes and telemetry while
sampling a stable input. Demonstrate that ADC cadence remains fixed through 30–45 ms loop
stalls and measure queue high-water/overruns.

**Stage C — full firmware A/B test:** Compare polling and DMA builds using identical hardware:

- current effective rate and timestamp jitter;
- IMU `interval_us` distribution and achieved rate;
- telemetry inter-arrival jitter (Issue 37);
- current peak/charge/I²t agreement;
- SD continuity and power-cycle behavior; and
- CPU/loop idle time.

**Acceptance criteria:** zero unexplained missing samples, zero DMA/FIFO errors in a deployment-
length bench run, no regression in current conversion or IMU data, and demonstrably lower ADC
timing jitter. A higher headline sample rate alone is not success.

### Likely implementation boundary

Keep the Apollo3-specific code in a small local module (for example,
`current_adc_dma_apollo3.h/.cpp`) with a narrow `begin / bufferReady / consume / diagnostics`
interface. Do not scatter Ambiq HAL calls throughout `VertiSea.ino`. Pin the tested SparkFun
Apollo3 core version in the implementation notes because HAL behavior and Arduino core
ownership differ substantially between the installed 1.2.1 core and current 2.x Mbed-based
cores.


---

## U24 — Non-blocking I²C/IOM acquisition for IMUs (DMA where useful)

**Status:** Proposed research 2026-09-04. Apollo3 HAL support is confirmed, but replacing the
current `Wire`/SparkFun-library path is a high-risk architectural change and is not yet
justified by a measured prototype.

**Priority:** ⭐⭐ Medium. Investigate after ADC DMA and SD buffering because I²C is no longer
the dominant measured bottleneck at 400 kHz.

### Motivation

Each IMU tick currently performs six blocking library transactions on the shared I²C bus:

```cpp
imu.checkStatus();
imu.getAccel(&accelData);
imu.getGyro(&gyroData);
```

for each of two ISM330DHCX devices. The installed Apollo3 1.2.1 `Wire` implementation calls
`am_hal_iom_blocking_transfer()` in both `requestFrom()` and `endTransmission()`. While a
transaction is on the wire, the CPU waits and the cooperative loop cannot service telemetry,
ADC bookkeeping, or SD queues.

The Apollo3 IOM HAL supports I²C mode, non-blocking transfers, callbacks, DMA-complete/error
interrupts, and a command queue. In principle, IMU register reads can proceed while the CPU
handles other work.

### Why the expected benefit is limited

DMA removes CPU waiting but does **not** shorten the 400 kHz wire time. The two IMUs also
produce new samples at only 104 Hz, so DMA cannot create additional sensor data. Current
measurements show that raising I²C from 100 to 400 kHz improved IMU rate only from 88.94 to
92.75 Hz; the remaining long tail correlates primarily with SD writes. Therefore I²C DMA
should be evaluated for loop responsiveness and jitter, not assumed to solve the 104 Hz rate.

The Apollo3 IOM FIFO is 32 bytes, while one contiguous ISM330DHCX accel+gyro payload is only
12 bytes (plus register/address phases). Such a transfer fits entirely in the FIFO. The HAL's
non-blocking API may therefore gain more from interrupt/callback scheduling than from bulk DMA,
and DMA/command-queue setup overhead may outweigh its transfer savings. The prototype must
measure which hardware path is actually used; do not advertise “I²C DMA” merely because the
submission API can support DMA for larger transfers.

For these small transfers, reducing transaction count may be more valuable than DMA itself.
The first prototype should test one contiguous accel+gyro output-register burst per IMU,
eliminating separate `checkStatus`, accel, and gyro transactions where the device register map
permits it. The ISM330DHCX FIFO is another candidate: let each sensor collect at 104 Hz and
drain several frames per bus transaction. Both approaches reduce starts, addresses, register
writes, and callback overhead.

### Integration problem: `Wire` owns the IOM

This is not a drop-in replacement for `getAccel()`:

- `TwoWire` owns a protected IOM handle and initializes the peripheral internally.
- Its transaction buffer is configured for blocking calls; the public API exposes no
  non-blocking request method.
- The SparkFun IMU, BME280, RTC, magnetometer, and GNSS libraries all expect synchronous
  `Wire` semantics.
- A second independent HAL owner must not use the same IOM concurrently with `Wire`.

Consequently, a safe implementation needs **one owner and one scheduler** for the shared bus.
The realistic options are:

1. Fork/extend the Apollo3 `Wire` layer locally to expose queued non-blocking transactions
   while preserving synchronous compatibility for low-rate libraries; or
2. Build a dedicated Apollo3 I²C bus manager and direct-register driver for the two IMUs,
   with an explicit idle/lock boundary for occasional blocking BME/RTC/GPS/magnetometer calls.

Option 2 has a smaller hot path but still must avoid creating two HAL handles for the same IOM.
Neither option should modify the globally installed Arduino package in place; the dependency
must live in the repository so builds are reproducible.

### Proposed state machine

1. A timer/data-ready event marks an IMU frame due; the ISR only sets a flag or queues a
   request.
2. Submit an asynchronous fixed-IMU burst read through `am_hal_iom_nonblocking_transfer()`.
3. Its completion callback records status and submits the stabilized-IMU burst read.
4. The second callback marks one paired frame ready with a timestamp anchored to acquisition
   start (and optionally completion time for latency diagnostics).
5. `loop()` performs calibration, LPF, Madgwick, vertical integration, telemetry, and SD
   enqueueing on completed paired frames. No floating-point or sensor processing occurs in
   the IOM ISR/callback.
6. Time out and recover any transaction that does not complete. Count NAK, arbitration, DMA,
   FIFO underflow/overflow, timeout, and stale-frame errors separately.
7. Serialize all other shared-bus device access. Low-rate reads may be deferred until the IMU
   pair completes; they must never interleave with an active DMA transaction.

The HAL requires an application-provided non-blocking transaction buffer
(`pNBTxnBuf`/`ui32NBTxnBufLength`), 32-bit data buffers, ISR dispatch through
`am_hal_iom_interrupt_service()`, and callback-safe lifetime for every transaction and buffer.

### Required first benchmark — before a full port

Create a standalone branch or test sketch that reads both IMUs three ways at 400 kHz:

1. current SparkFun library path (six blocking transactions/tick);
2. direct blocking contiguous burst reads (two transactions/tick); and
3. direct non-blocking/DMA burst reads (two transactions/tick).

Measure bus-active time, CPU-blocked time, end-to-end pair latency, loop-service opportunity,
error rate, and IMU sample integrity. Include simultaneous SD write load. If direct blocking
burst reads deliver nearly all the benefit, prefer that much simpler change over DMA.

### Risks and acceptance criteria

- A bus scheduler bug can freeze **all** I²C sensors, recreating the system-wide failure class
  behind Issues 25/27.
- Completion order, callback reentrancy, timeout recovery, `micros()` wrap, and shutdown/reset
  behavior all need explicit handling.
- Direct-register reads must reproduce the SparkFun driver's units exactly: accel milli-g and
  gyro mdps. Validate byte order, signed conversion, full-scale sensitivity, and BDU behavior
  against simultaneous known-motion logs.
- The two IMUs are sampled sequentially on one bus. DMA does not make them simultaneous;
  timestamp or characterize their skew.
- Success means fewer/shorter main-loop blocking intervals and no sensor-regression errors.
  Require a statistically meaningful improvement in IMU interval tail or telemetry jitter;
  otherwise retain the maintained SparkFun library path.

### Relationship to existing upgrades

- **U19:** I²C DMA is not a replacement for SD buffering; SD remains the leading cause of the
  long IMU interval tail.
- **U23:** ADC DMA is independent and should be prototyped first. It gives deterministic
  current sampling without changing every shared-bus sensor driver.
- **U2:** Re-enabling magnetometer reads adds more shared-bus scheduling work and should wait
  until the I²C architecture is stable.


---

## U25 — Buffered SD pipeline with SPI/IOM DMA where useful

**Status:** Stage 1 confirmed 2026-09-04; direct SPI/IOM DMA rejected for SparkFun Apollo3 core
1.2.1; preallocation integration deferred.

### Current production result

`VertiSea.ino` now has an eight-sector RAM queue, atomic record enqueueing, visible backpressure,
and the existing synchronous Arduino SD 1.3.0 backend. A 12.2-minute debug run had zero queue
overruns, parsed exactly to EOF, and improved current-block dead time. This is the retained U25
implementation. See [`docs/CHANGELOG_VertiSea.ino.md`](docs/CHANGELOG_VertiSea.ino.md).

### Experiment conclusions

- **Phase 2 — preallocation/multi-block:** byte verification passed. Contiguous preallocation
  removed a 111.9 ms dynamic-allocation outlier; CMD25 improved throughput 46 → 51 KiB/s and
  made latency more deterministic. It is not integrated because deployment file-size bounds,
  truncation, metadata durability, and power-loss recovery still need a production design. Full
  measurements: [`docs/CHANGELOG_tools__sd_phase2_benchmark__sd_phase2_benchmark.ino.md`](docs/CHANGELOG_tools__sd_phase2_benchmark__sd_phase2_benchmark.ino.md).
- **Phase 3 — direct DMA:** rejected on Apollo3 core 1.2.1. IOM DMA moved 512/515-byte payloads
  near the 4 MHz wire floor (~1.08–1.10 ms), but every tested SD CMD25 architecture lost response
  synchronization and none passed byte verification; inspected output included corrupt sectors.
  Blocking multi-byte SPI also timed out. Full history:
  [`docs/CHANGELOG_tools__sd_phase3_dma_benchmark__sd_phase3_dma_benchmark.ino.md`](docs/CHANGELOG_tools__sd_phase3_dma_benchmark__sd_phase3_dma_benchmark.ino.md) and
  [`docs/CHANGELOG_tools__sd_phase3_bulk_spi_benchmark__sd_phase3_bulk_spi_benchmark.ino.md`](docs/CHANGELOG_tools__sd_phase3_bulk_spi_benchmark__sd_phase3_bulk_spi_benchmark.ino.md).

### Future work

Do not port the experimental DMA path into deployment firmware. Revisit SD DMA only with a
different validated Apollo3 core/library or a proven SD driver that owns the complete IOM and SD
token/response/busy state machine. Preallocation may be revisited independently after defining
maximum deployment size, safe truncation, metadata recovery, and intentional power-loss tests.
