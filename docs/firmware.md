# Firmware — VertiSea.ino

> **Status:** Active development
> **Source file(s):** [`VertiSea.ino`](../VertiSea/VertiSea.ino)
> **Last reviewed:** 2026-08-18

## Purpose

The Arduino firmware running on the SparkFun RedBoard Artemis Nano is the core data-acquisition engine. It initialises all
sensors, applies calibration and filtering, packs data into typed binary packets, logs
them to an SD card, and streams a telemetry subset over Serial1 to the RFD900x modem.
It does **not** perform any post-processing, file management, or user interaction beyond
the LED heartbeat and USB serial debug output.

---

## Dependencies

| Library | Why it is needed |
|---------|-----------------|
| `Wire.h` | I²C bus for BME280, RTC, GNSS, IMUs, magnetometer |
| `SPI.h` | SPI bus for SD card |
| `SD.h` | SD card file I/O |
| `SparkFunBME280` | BME280 pressure/humidity/temperature sensor driver |
| `SparkFun_RV8803` | RV8803 RTC driver |
| `SparkFun_u-blox_GNSS_Arduino_Library` | u-blox GNSS (GPS) driver over I²C (UBX protocol) |
| `SparkFun_ISM330DHCX` | ISM330DHCX 6-DOF IMU driver (used for both fixed and stabilized IMUs) |
| `SparkFun_MMC5983MA_Arduino_Library` | MMC5983MA 3-axis magnetometer driver |
| `MadgwickAHRS.h` | Madgwick AHRS filter (pitch, roll, yaw from IMU + optional mag). **Vendored in the sketch folder**, not a Library Manager install, and a local fork: `sampleFreqDef` 512→104, `betaDef` 0.1→**0.5**. See Issue 58 |

---

## Deployment Flags

Each is an `#ifndef` default near the top of `VertiSea.ino`. Do not edit them there to
configure a session — copy `VertiSea/config_local.h.example` to `VertiSea/config_local.h`
(git-ignored, included first via `__has_include`) and define the ones you need. A missing
override file gives the committed defaults below.

| Flag | Values | Effect |
|------|--------|--------|
| `USB_DEBUG` | `1` (bench) / `0` (field) | `1` → waits up to 3 s for USB host and enables all `DBG_PRINT`/`DBG_PRINTLN` output. **Telemetry is routed to `Serial1` (RFD900), not USB** — `Serial` is reserved exclusively for human-readable debug text so binary packets cannot corrupt it. Takes priority over `USB_TELEM`. `0` → boots immediately, all debug output compiled out entirely. |
| `USB_TELEM` | `1` (USB telem) / `0` (radio) | `1` → all telemetry packets sent to `Serial` (USB CDC) instead of `Serial1`/RFD900, so the Python GUI can receive real-time data over USB without a radio link. Requires `USB_DEBUG=0` (see caution below). `0` → normal field operation, telemetry via `Serial1`. Also changes `TELEMETRY_RATE_HZ` from 5 Hz to 10 Hz. **Has no effect while `TELEM_ENABLE 0`.** |
| `GPS_ENABLE` | `1` (GPS connected) / `0` (GPS absent) | `1` → GPS init, time sync, SD logging, and radio telemetry all active. `0` → ALL GPS-related code compiled out. **Required when GPS module is not physically connected** — `myGNSS.begin()` on an absent device leaves SDA low, hanging the shared I²C bus and freezing both IMUs. See IDENTIFIED_ISSUES #27. |
| `RPM_ENABLE` | `1` (sensor connected) / `0` (absent) | `1` → Hall-effect RPM sensor ISR active on `HALL_PIN`; `TYPE_RPM` packets logged to SD and transmitted over radio at `TELEMETRY_RATE_HZ`. `0` → all Hall/RPM code compiled out entirely (zero overhead). |
| `HALL_PIN` | GPIO number (default `2`) | Digital pin wired to the Melexis US1881 Hall sensor output. Must support `attachInterrupt()`. Wire with 4.7 kΩ pull-up to 3.3 V. |
| `TELEM_ENABLE` | `1` (send) / `0` (silent) | Master gate on the `TELEM_WRITE()` macro. `0` → **no telemetry is transmitted at all** on either transport, freeing loop time for current sampling — but every radio-only packet (`0x06`, `0x0B`, `0x0F`) is then absent and the GUI's live panels stay blank. `1` → telemetry sent, to USB or `Serial1` per `USB_TELEM`. |
| `IMU_RAW_ONLY` | `0` (processed) / `1` (raw) | `0` → log `TYPE_FIXED_IMU` + `TYPE_STAB_IMU` + `TYPE_MAG` (~119 B/tick, ~93 Hz). `1` → log one `TYPE_IMU_RAW` (`0x12`) instead (~61 B/tick, ~97.5 Hz measured). **Trade-off:** a raw log has no on-board attitude and no magnetometer record — recompute attitude offline from `0x08`/`0x09`/`0x10`. Madgwick still runs, so radio telemetry is unaffected. |
| `STAB_IMU_USES_MAG` | `0` (6-DOF) / `1` (9-DOF) | `0` → the stabilized IMU runs 6-DOF: the MMC5983MA is never read, `heading` is the 999.9 sentinel, and **no `TYPE_MAG` (`0x07`) record is written**. `1` → magnetometer read, calibrated, low-pass filtered, and fused by a 9-DOF Madgwick `update()`; `0x07` is logged when `IMU_RAW_ONLY` is also `0`. Added 2026-09-11 to replace a bare `false` literal at the call site — the record used to be written unconditionally from an LPF state nothing updated, logging constant zeros (Issue 46). A `mag.begin()` failure is non-fatal and recorded in `magPresent`. |
| `SD_BUFFERED_WRITE` | `1` (buffered) / `0` (fallback) | `1` → atomically queue complete records in an eight-sector RAM buffer and service the existing synchronous Arduino SD 1.3.0 backend in 512-byte sectors. Checked writes, explicit backpressure, and queue diagnostics remain active. `0` → checked synchronous record writes without the RAM queue. Keep `1` for production. |

**Committed values** (re-read from source 2026-09-11): `USB_DEBUG 0`, `USB_TELEM 0`,
**`TELEM_ENABLE 0`**, `GPS_ENABLE 0`, `RPM_ENABLE 1`, `IMU_RAW_ONLY 1`,
`SD_BUFFERED_WRITE 1`.

That is: **an SD-only capture build — no telemetry on any transport**, no GPS, RPM on, raw
IMU records, buffered synchronous SD pipeline.

> **⚠ This build transmits nothing.** With `TELEM_ENABLE 0` the telemetry UART is never
> initialised and every `TELEM_WRITE()` is compiled out, so the ground station shows a blank
> GUI regardless of which port is selected. That is the intended behaviour of this
> configuration, not a fault — but it means the committed source is **not** the build the
> ground-station sections of the README and `docs/telemetry_ground_station.md` describe.
>
> This doc previously claimed `USB_TELEM 1` / `TELEM_ENABLE 1` ("read from source
> 2026-09-08"); the source disagrees. Re-verify the flags against the sketch rather than
> trusting a doc snapshot.

When `USB_TELEM 1` *is* set, the effective `TELEMETRY_RATE_HZ` is **10 Hz**, not 5 — the
constant is chosen by `#if USB_TELEM`, so any doc quoting a flat "5 Hz" for `0x06`, `0x0C`
or the other telemetry packets is only correct for a radio build.

> **Do not assume field-radio defaults.** A field deployment wants `TELEM_ENABLE 1`,
> `USB_TELEM 0` (radio) and, for a self-contained log, `IMU_RAW_ONLY 0`.
>
> **Transport verification status (2026-09-03):** the **USB telemetry path is confirmed
> working** — packets reach the GUI and its panels populate. The **RFD900 radio path has not
> been exercised recently.** Packet layouts are transport-independent, so what is untested is
> the link itself: 115200 baud framing, byte loss, and range. Budget time to re-verify the
> radio before relying on it in the field.

---

## Pin Configuration

| Pin | Role |
|-----|------|
| `CS_SD = 4` | SPI chip-select for SD card |
| `LED_BUILTIN` | Heartbeat LED (1 Hz blink during normal operation; HIGH during setup; 4 Hz on SD error) |
| `A14` | Analog input for the harvested-current sensor (**was** a supercap voltage divider; repurposed 2026-09-02). `VREF` 2.0 V, `CURRENT_SENS_MA_PER_V` 100.0, `CURRENT_DIV_RATIO` 1.0 |
| `HALL_PIN` (default `2`) | Hall-effect RPM sensor input (`RPM_ENABLE=1` only); 4.7 kΩ pull-up to 3.3 V |

---

## Serial Ports

| Port | Role | Baud |
|------|------|------|
| `Serial` (USB) | Debug output (`USB_DEBUG=1`); telemetry only when `USB_TELEM=1` **and** `USB_DEBUG=0` | 115200 |
| `Serial1` (HardwareSerial) | RFD900x telemetry output (default field mode, and whenever `USB_DEBUG=1`) | 115200 |

The active telemetry port is selected at compile time by the `TELEM_SERIAL` macro:

```cpp
#if USB_DEBUG
  #define TELEM_SERIAL Serial1   // USB_DEBUG takes priority: keep USB text-only
#elif USB_TELEM
  #define TELEM_SERIAL Serial    // USB mirror mode
#else
  #define TELEM_SERIAL Serial1   // normal field / RFD900
#endif
```

When `USB_DEBUG=1`, telemetry deliberately goes to **`Serial1`**, not USB: mixing binary
packets with human-readable debug text on one port corrupts both streams.

`Serial1.begin(115200)` is guarded by
`#if TELEM_ENABLE && (USB_DEBUG || !USB_TELEM)`. This mirrors `TELEM_SERIAL`: the UART is
initialised whenever telemetry is enabled and routed to `Serial1`, including the
`USB_DEBUG=1` + `USB_TELEM=1` combination. With `TELEM_ENABLE=0`, it is intentionally left off.

GPS uses I²C (not Serial1). Serial1 is **output-only** for telemetry in field mode.

---

## Sampling Rates and Intervals

| Task | Rate | Interval constant |
|------|------|-------------------|
| IMU (both) + MAG | nominal 104 Hz; **~93 Hz achieved** (~97.5 Hz with `IMU_RAW_ONLY=1`) | `IMU_INTERVAL_US = 9615 µs` |
| BME280 log | 1 Hz | `BME_INTERVAL_MS = 1000 ms` |
| GPS log | 1 Hz | `GPS_INTERVAL_MS = 1000 ms` |
| IMU telemetry (radio) | 5 Hz (`USB_TELEM=0`) / 10 Hz (`USB_TELEM=1`) | `TELEMETRY_INTERVAL_MS` |
| Supercap telemetry | same as IMU telemetry | same as IMU telemetry |
| RPM log + telemetry (`RPM_ENABLE=1`) | same as IMU telemetry | same as IMU telemetry |
| GPS telemetry (radio) | 0.2 Hz | `GPS_TELEM_INTERVAL_MS = 5000 ms` |
| BME telemetry (radio) | 0.067 Hz | `BME_TELEM_INTERVAL_MS = 15000 ms` |
| SD flush | 0.2 Hz | `FLUSH_INTERVAL_MS = 5000 ms` |
| GPS sync timeout at boot | — | `GPS_SYNC_TIMEOUT_MS = 120000 ms` (2 minutes) |

---

## Sensor Addresses

| Sensor | Interface | Address |
|--------|-----------|---------|
| ISM330DHCX (fixed IMU) | I²C | `0x6A` |
| ISM330DHCX (stabilized IMU) | I²C | `0x6B` |
| MMC5983MA (magnetometer) | I²C | default (auto) |
| BME280 | I²C | default (auto) |
| RV8803 RTC | I²C | default (auto) |
| u-blox GNSS | I²C | default (auto) |

---

## Calibration Constants

### IMU Calibration (`IMUCal` struct)

Applied in `collectIMUData_ISM()` before LPF and Madgwick update.

```
struct IMUCal {
  float accel_bias[3];   // mg — subtracted from raw accel counts
  float accel_scale[3];  // counts per +1 g — divides bias-corrected accel
  float gyro_bias[3];    // MILLIDEGREES/S — subtracted from the driver's mdps value BEFORE the ×0.001 mdps→dps conversion
};
```

Accel correction: `ax_g = -(raw_x - bias_x) / scale_x`  
Note the **negation on X** for the fixed IMU axis convention.

Gyro correction: `gx_dps = (raw_x - bias_x) * 0.001`  
Note the **negation on Y** for both IMUs.

Current values are hard-coded as `fixedCal` and `stabCal` in the sketch. They were
determined by offline calibration and must not be changed without re-running calibration.

### Magnetometer Calibration (`MagCal` struct)

```
struct MagCal {
  float offset[3];  // hard-iron offsets [X, Y, Z] in raw counts
  float scale[3];   // soft-iron scale factors (per-axis)
};
```

Applied as: `mx = (raw_x - offset[0]) * scale[0]`

Current values were obtained via `calibrateMag.m` on a full-sphere sweep. Calibration
is complete and the constants are hard-coded. Do not re-run unless the magnetometer or
its mounting changes.

---

## Low-Pass Filters

A first-order IIR (1-pole) LPF is applied to accel, gyro, and mag before the Madgwick
update. The filter coefficient `alpha` is computed at boot:

```
dt = 1 / IMU_RATE_HZ
rc = 1 / (2π × cutoff_hz)
alpha = dt / (rc + dt)
```

| Signal | Cutoff | Alpha (computed at the **nominal** 104 Hz) |
|--------|--------|--------------------------|
| Accel | 20 Hz | ~0.55 |
| Gyro | 40 Hz | ~0.71 |
| Mag | 2 Hz | ~0.11 |

State is held in `LPFState lpfFixed` and `LPFState lpfStab`. States are initialised to
zero and ramp up on the first loop iterations.

---

## Madgwick AHRS Filter

Two independent `Madgwick` filter instances: `filterFixed` and `filterStab`.

- `filterFixed.begin(IMU_RATE_HZ)` at boot is a **seed only**; `collectIMUData_ISM()` calls
  `filt.begin(1.0f / dtSec)` with the **measured** interval before every update, so the
  filter is tuned to real elapsed time rather than the nominal rate (Issue 34).
  6-DOF only (`updateIMU()`), no magnetometer.
- `filterStab` — currently also 6-DOF (`updateIMU()`) because `isStabilizedIMU = false`
  is passed to `collectIMUData_ISM()`. The 9-DOF path (`update()` with mag) is compiled
  in but not active. To re-enable 9-DOF, change the `false` to `true` in the
  `collectIMUData_ISM(imuStab, ...)` call in `loop()`.

Output: `pitch` (degrees), `roll` (degrees), `heading`/yaw (degrees, or `999.9f` if
invalid/disabled).

---

## `collectIMUData_ISM()` — Key Function

```cpp
IMUData collectIMUData_ISM(
    SparkFun_ISM330DHCX &imu,
    Madgwick &filt,
    const IMUCal &cal,
    bool isStabilizedIMU,
    LPFState &state
)
```

Flow:
1. Read raw accel and gyro from ISM330DHCX.
2. Apply bias/scale calibration → `raw_ax/ay/az` (g), `raw_gx/gy/gz` (°/s).
3. Store raw values in `IMUData.raw_*` fields.
4. Apply 1-pole IIR LPF → update `state.ax/ay/az`, `state.gx/gy/gz`.
5. **Accel magnitude guard** — compute `accelSqMag = state.ax² + state.ay² + state.az²`.
   Set `accelValid = (accelSqMag >= ACCEL_MIN_SQ_MAG)` where `ACCEL_MIN_SQ_MAG = 0.25 g²`
   (minimum magnitude ≈ 0.5 g). If `accelValid` is false, skip the Madgwick update
   entirely; the filter retains its last valid quaternion so pitch/roll hold their last
   good values rather than diverging to NaN. See IDENTIFIED_ISSUES #24.
6. If `isStabilizedIMU`: read MMC5983MA, apply mag calibration and mag LPF (this happens
   regardless of `accelValid`), then run the 9-DOF Madgwick `update()` **only if**
   `accelValid`.
7. Else if `accelValid`: run 6-DOF Madgwick `updateIMU()`.
8. Package filtered values and Madgwick angles into returned `IMUData`.

**Note:** The `IMUData` struct stores both raw and filtered values, but only filtered
values are written to the SD log packets (`TYPE_FIXED_IMU`, `TYPE_STAB_IMU`). Raw values
are available in memory but not persisted.

---

## Vertical Displacement Estimation

Computed in `loop()` on every IMU tick (nominal 104 Hz, ~93 Hz achieved), immediately after
IMU collection:

1. `computeVerticalAccel()` rotates body-frame accel into Earth-frame Z using pitch and
   roll (yaw neglected): `a_ez = ax·sin(p) - ay·sin(r)·cos(p) + az·cos(r)·cos(p)`
2. Subtract 1 g to get inertial vertical acceleration.
3. Euler-integrate to velocity: `vertVel += a_vert × dt`
4. Euler-integrate to displacement: `vertDisp += vertVel × dt`
5. Apply leaky integrator as a **time constant**: `leak = 1 - dtActual/VERT_LEAK_TAU_S`
   with `VERT_LEAK_TAU_S = 19.2f`, then `vertVel *= leak`, `vertDisp *= leak`. The old fixed
   `0.9995f` per-sample factor only gave τ = 19.2 s at exactly 104 Hz; because the loop runs
   slower, τ came out **longer** than intended (21.6 s at the measured 93 Hz)

The leak constants suppress residual long-period drift from accelerometer bias. Do not
remove them. Accuracy depends on IMU calibration quality; re-running the stabilized IMU
accel calibration is the recommended path to improving vertical displacement accuracy.

> **Note:** A 3-phase runtime bias calibration block (warmup + averaging + slow EMA)
> was previously present but removed (see IDENTIFIED_ISSUES #21/#23). It required the
> board to be stationary at startup, which cannot be guaranteed in field deployment, and
> caused NaN pitch/roll output when the board was moving at boot.

`vertDisp` (metres) is transmitted in the `TYPE_TELEM_IMU` radio packet as `int16`
millimetres. It is **not** logged to SD separately (it can be reconstructed offline).

---

## SD Logging Flow

1. At boot: write `TYPE_RTC_EVENT`, `TYPE_FIXED_CAL`, `TYPE_STAB_CAL`, then flush.
2. In `loop()`:
   - 1 Hz: write `TYPE_BME`
   - Per IMU tick: with `IMU_RAW_ONLY 0` write `TYPE_FIXED_IMU`, `TYPE_STAB_IMU`, `TYPE_MAG`
  (~119 B/tick); with `IMU_RAW_ONLY 1` write a single `TYPE_IMU_RAW` (`0x12`) instead
  (~61 B/tick)
   - `TELEMETRY_RATE_HZ`: write `TYPE_RPM` (when `RPM_ENABLE=1`). `TYPE_SUPERCAP` became
  `TYPE_CURRENT` (`0x0A`) and was then **retired 2026-09-03** — current now goes to SD via
  `TYPE_CURRENT_BLOCK` (`0x0E`) and to the radio via `TYPE_CURRENT_STATS` (`0x0F`)
   - 1 Hz: write `TYPE_GPS` (sentinel packet with `gpsSats=0` written when no fix)
3. With `SD_BUFFERED_WRITE=1`, each complete header+payload record is accepted atomically into
   a 512-byte producer sector. Completed bytes feed an eight-sector (4096-byte) RAM ring.
4. `loop()` drains at most one complete sector per pass when there is sufficient IMU timing
   slack. A nearly full queue overrides the slack preference; an overrun or short backend write
   latches `sdError`, stops accepting records, and leaves telemetry active.
5. Every 5 s (`FLUSH_INTERVAL_MS`), the queue and partial producer sector are drained and
   `File.flush()` is called. The backend remains synchronous Arduino SD 1.3.0; buffering does
   not make SPI asynchronous. Direct Apollo3 IOM DMA is rejected on core 1.2.1 after all tested
   CMD25 architectures failed response synchronization or byte verification.

Log filename format: `MMDDHHmm.BIN` (e.g., `04030825.BIN` = April 3, 08:25 **local time**).
Filename is generated from local time (UTC + `timezoneOffsetHours`) at the end of `setup()`.
The `TYPE_RTC_EVENT` boot record also uses local time. The RTC hardware register stores UTC.

If local time is **not** valid (RTC year < 2024, e.g. dead coin cell and no GPS sync), the
firmware falls back to a counter-based name by scanning for the first unused
`LOGnnnnn.BIN` slot (`LOG00001.BIN` … `LOG99999.BIN`) so an existing log is never
silently overwritten.

---

## Telemetry Flow

All telemetry is written to `TELEM_SERIAL` (resolves to `Serial1` in field mode and whenever
`USB_DEBUG=1`, or to `Serial`/USB when `USB_DEBUG=0` and `USB_TELEM=1`):

| Packet | Rate | Struct fields |
|--------|------|--------------|
| `TelemetryPacket` (`0x06`) | `TELEMETRY_RATE_HZ` (5 Hz radio / 10 Hz USB) | pitch_cdeg, roll_cdeg, vertDisp_mm, stab_pitch_cdeg, stab_roll_cdeg |
| ~~`SupercapPacket`~~ (`0x0A`) | — | **Removed 2026-09-03.** Became `CurrentPacket` (current_mA), then retired; current statistics now go out as `CurrentStatsPacket` (`0x0F`) |
| `RPMPacket` (`0x0C`) | same as above (`RPM_ENABLE=1` only) | rpm (uint16) |
| `TelemetryGPSPacket` (`0x04`) | 5 s | sats, lat, lon |
| `TelemetryBMEPacket` (`0x03`) | 15 s | pressure, humidity, temperature |
| `StatusPacket` (`0x0B`) | 1 s | flags (bit 0 = sdError) |

Angle fields in `TelemetryPacket` use centidegree encoding (×100, range ±327.67°).

---

## GPS Role — Time Sync, Not Positioning

**Design intent:** the GNSS module is used primarily to set the RTC to the correct
wall-clock time, **not** as a reliable position source during deployment.

The GPS antenna is mounted at water level on a buoy that is, by definition, rocking.
Reception is expected to be intermittent — the antenna is periodically shadowed by waves
and tilted away from the sky. Position fixes during deployment are therefore treated as
opportunistic, and the firmware is built to keep running without them:

- The boot time-sync loop waits up to `GPS_SYNC_TIMEOUT_MS` (2 min) for a fix and then
  continues regardless, falling back to the RTC's retained time.
- The 1 Hz SD log writes a sentinel packet (`gpsSats=0`, lat/lon/alt = 0) when there is no
  fix, so the CSV has no gaps and no-fix periods are unambiguous (Issue 7's fix).
- Position accuracy is further limited by `float32` storage (~±0.0001°, ~11 m), which is
  adequate for "which buoy is this / roughly where was it" but not for precision tracking.

**Consequences for the operator:**

- Once the RTC holds a good time, GPS is not needed for the log timestamps to be correct.
  Running with `GPS_ENABLE 0` (the current committed state) is a legitimate deployment
  configuration, not a degraded one.
- **The RTC coin cell becomes the critical time source.** With `GPS_ENABLE 0` there is no
  mechanism to correct RTC drift or recover from a dead battery. If the cell fails, the
  firmware falls back to `LOGnnnnn.BIN` counter filenames and the `TYPE_RTC_EVENT` record
  is meaningless — recoverable, but absolute time for that deployment is lost. Check the
  coin cell as part of pre-deployment prep, and periodically re-sync by connecting the GNSS
  module with `GPS_ENABLE 1` on the bench where reception is good.
- If accurate positioning is ever required, the antenna mounting is the thing to change,
  not the firmware.

---

## Known Constraints and Gotchas

- **`GPS_ENABLE` must be `0` when the GPS module is not physically connected.** Leaving
  it `1` with no GPS module causes `myGNSS.begin()` to leave SDA low (I²C bus-hang),
  freezing both IMUs. See IDENTIFIED_ISSUES #27.
- **`GPS_SYNC_TIMEOUT_MS`** controls how long the firmware waits at boot for a GPS fix.
  Set to `120000UL` (2 minutes) for field use; `100UL` effectively skips GPS sync and
  uses the RTC as-is. The active value is in `VertiSea.ino` near the top.
- **RTC 24-hour mode** is forced at init (`rtc.set24Hour()` after `rtc.begin()`). The
  RV8803 defaults to 12-hour mode on first power-up or after coin-cell loss; without
  this, `getHours()` returns a 12-hour value and the log filename/timestamp is off by
  12 hours. See IDENTIFIED_ISSUES #31.
- **RTC year register** must be set by a GPS sync. The RV8803 library's `setYear()`
  expects the full 4-digit year (e.g. `2026`); it subtracts 2000 internally. Passing
  `year - 2000` double-subtracts and corrupts the register. See IDENTIFIED_ISSUES #28.
- The SD filename and `TYPE_RTC_EVENT` boot record use **local time** (UTC +
  `timezoneOffsetHours`). The RTC hardware register stores UTC. Update
  `timezoneOffsetHours` in the firmware before each deployment if the timezone changes.
- The IMU loop uses `micros()` with a `-50 µs` margin to compensate for loop jitter.
  Do not remove this margin.
- Both IMUs share the same I²C bus. Address conflicts are avoided by using `0x6A` and
  `0x6B` (SDO pin strapping).
- `imuReady` flag in `loop()` prevents telemetry from being sent before the first IMU
  sample is collected.
- `heading` is `999.9f` for the fixed IMU always, and for the stabilized IMU in the
  current configuration (6-DOF mode). The parser and ground station do not filter this
  sentinel value — it will appear in CSV and plots as-is.

## Rejected Approaches

- **EEPROM storage for calibration** — considered to allow field updates without
  reflashing. Rejected because calibration is infrequent and hard-coding makes the
  values visible in version control.
- **DMA SPI for SD** — considered for higher throughput. Not needed at current data rates.
- **9-DOF Madgwick on stabilized IMU** — implemented and tested but currently disabled
  (`isStabilizedIMU = false`) because heading accuracy was not required for the current
  deployment. The code path is preserved for future use.
- **Runtime accel bias calibration** — a 3-phase warmup/averaging/EMA block was
  implemented but removed (IDENTIFIED_ISSUES #21/#23). It required a stationary startup
  and caused NaN pitch/roll in field conditions. Vertical displacement accuracy should
  instead be improved by re-running the stabilized IMU accel calibration.

## Open Issues / To-Do

- See [`IDENTIFIED_ISSUES.md`](../IDENTIFIED_ISSUES.md) for the full list and authoritative
  status. The issue index table at the top of that file is the status of record.
- Currently open per the index: Issue 26 (verify the RFD900 modem's own configured baud
  rate matches the firmware's `115200` before the next deployment).
- Also worth fixing: the `USB_DEBUG=1` + `USB_TELEM=1` combination silently disables
  telemetry (see the caution under "Serial Ports" above).
