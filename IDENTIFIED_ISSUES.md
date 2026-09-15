# VertiSea — Identified Issues

This file tracks known bugs, logic errors, and risks found by code review. Issues are
ranked by severity. Update the **Status** field and add a **Resolution** note when an
issue is fixed; do not delete resolved entries.

**Severity scale:**

| Level | Meaning |
|-------|---------|
| 🔴 Critical | Data loss, silent data corruption, or system hang in normal operation |
| 🟠 High | Incorrect data values or behaviour that will affect analysis results |
| 🟡 Medium | Latent bug that may surface under specific conditions; code smell with real risk |
| 🟢 Low | Minor inefficiency, cosmetic, or style issue with negligible operational impact |

---

## Issue Index

| # | Severity | File | Short title | Status |
|---|----------|------|-------------|--------|
| 1 | 🔴 Critical | `VertiSea.ino` | `while (!Serial)` blocks boot without USB | ✅ Resolved |
| 2 | 🔴 Critical | `VertiSea.ino` | Log filename collision can append a second boot session to an existing file | 🔄 Fix implemented; hardware verification pending |
| 3 | 🔴 Critical | `VertiSea.ino` | SD write errors are only checked on the IMU payload path | ✅ Resolved in buffered writer; flush API still cannot report status |
| 4 | 🟠 High | `VertiSea.ino` | `vertDisp` / `vertVel` variable shadowing — outer statics never used | ✅ Resolved |
| 5 | 🟠 High | `VertiSea.ino` | `TYPE_MAG` packet uses `millis()` instead of `nowMs` — timestamp inconsistency | ✅ Resolved |
| 6 | 🟠 High | `VertiSea.ino` | `computeVerticalAccel` uses accel in g but integrates as if in m/s² before unit conversion | ✅ Resolved |
| 7 | 🟠 High | `VertiSea.ino` | GPS log skipped entirely when no fix — no GPS packet written, gap in CSV | ✅ Resolved |
| 8 | 🟠 High | `vertisea_plot_v7.py` | `TYPE_TELEM_IMU` field labels wrong — plots show pitch/roll/disp labelled as ax/ay/az | ✅ Resolved |
| 9 | 🟠 High | `VertiSea.ino` | Incorrect early diagnosis of RV8803 year semantics | ↪ Superseded by Issue 28 |
| 10 | 🟡 Medium | `VertiSea.ino` | `imuReady` flag declared `static` inside `loop()` — resets to `false` on every call (C++ static initialisation) | ✅ Resolved |
| 11 | 🟡 Medium | `VertiSea.ino` | `disp_mm` declared but never used | ✅ Resolved |
| 12 | 🟡 Medium | `VertiSea.ino` | `pitch` and `roll` statics in `loop()` declared but never written or read | ✅ Resolved |
| 13 | 🟡 Medium | `VertiSea.ino` | `startSync` and outer `synced` / `lastSatPrint` in `setup()` are shadowed by inner declarations | ✅ Resolved |
| 14 | 🟡 Medium | `parse_vertisea_log_v4.m` | Parser calls `break` on unknown packet type — truncates file on any corruption | ⛔ Obsolete — parser retired |
| 15 | 🟡 Medium | `vertisea_plot_v7.py` | Legacy `TYPE_SUPERCAP` (`0x0A`) bytes dropped one-at-a-time | ⛔ Obsolete — packet retired |
| 16 | 🟡 Medium | `VertiSea.ino` | `uint16_t ts10 = millis()/10` overflows after ~655 s (~11 min) — timestamp wraps silently | ✅ Resolved |
| 17 | 🟡 Medium | `VertiSea.ino` | `TelemetryPacket.vertDisp_mm` computed twice (`vertDisp_mm` local + inline in struct init) | ✅ Resolved |
| 18 | 🟢 Low | `VertiSea.ino` | `printAligned()` defined but has no active call | ✅ Resolved — dead helper removed |
| 19 | 🟢 Low | `VertiSea.ino` | Debug block at 1 Hz contains only commented-out output | ✅ Resolved — SD queue diagnostics active |
| 20 | 🟢 Low | `VertiSea.ino` | `IMUData` comment says accel is m/s² but values are stored in g | ✅ Resolved |
| 21 | 🟠 High | `VertiSea.ino` | Vertical displacement drifts unboundedly — residual `a_vert` bias ~90 mm/s² persists after startup calibration | ✅ Resolved |
| 22 | 🔴 Critical | `VertiSea.ino` | SD filename and `TYPE_RTC_EVENT` timestamp use UTC instead of local time | ✅ Resolved |
| 23 | 🟠 High | `VertiSea.ino` | Runtime accel bias calibration causes NaN pitch/roll — requires stationary startup | ✅ Resolved |
| 24 | 🔴 Critical | `VertiSea.ino` | ISM330DHCX sensor freeze causes near-zero accel → Madgwick diverges to NaN pitch/roll | ✅ Resolved |
| 25 | 🟠 High | `VertiSea.ino` | Both IMUs freeze simultaneously at identical timestamps — shared I²C bus root cause | ✅ Resolved |
| 26 | 🟡 Medium | `VertiSea.ino` | `TELEM_SERIAL.begin(115200)` — verify RFD900 modem baud rate matches before next deployment | ↪ Tracked by Issue 36 |
| 27 | 🔴 Critical | `VertiSea.ino` | GPS module removed from I²C bus — `myGNSS.begin()` hangs or corrupts bus; IMUs freeze without GPS connected | ✅ Resolved |
| 28 | 🟠 High | `VertiSea.ino` | `rtc.getYear() + 2000` double-adds 2000 — year printed as ~4074 instead of ~2026 | ✅ Resolved |
| 29 | 🟢 Low | `VertiSea.ino` | `char buf[32]` too small for RTC fallback debug string | ✅ Resolved |
| 30 | 🟠 High | `VertiSea.ino` | RTC `begin()` intermittently fails — I²C power-on timing / bus-hang from prior session | ✅ Resolved |
| 31 | 🟠 High | `VertiSea.ino` | RTC reads 12-hour time when GPS disabled — `set24Hour()` not called before RTC fallback read | ✅ Resolved |
| 32 | 🟠 High | `vertisea_plot_v7.py` | `relim()`/`autoscale_view()` on mechanical-input plot overrides fixed y-axis limits — RPM spikes rescale axes | ✅ Resolved |
| 33 | 🟠 High | `VertiSea.ino` | Hall-effect ISR fires on noise/magnet bounce — spurious short periods produce unrealistically high RPM values | ✅ Resolved |
| 34 | 🔴 Critical | `VertiSea.ino` | Madgwick + vertDisp assumed nominal 104 Hz despite a slower/jittery loop | ✅ Correctness defect resolved; residual rate work is U19 |
| 35 | 🔴 Critical | `VertiSea.ino` | `TYPE_IMU_RAW` gyro fields overflowed int16 (mdps, not counts) | ✅ Fixed + verified (int32) |
| 36 | 🟡 Medium | `VertiSea.ino` / `vertisea_plot_v7.py` | RFD900 radio transport unverified since the packet-set overhaul (USB path is verified) | ⚠ Open |
| 37 | 🟠 High | `VertiSea.ino` | Telemetry arrives at an irregular real-time rate — polled gate inherits loop-pass jitter from 1000 Hz ADC sampling | ⚠ Open |
| 38 | 🟡 Medium | `vertisea_plot_v7.py` | BIN loader mishandles the expected `IMU_RAW_ONLY=1` user experience | 🔄 Dialogs fixed 2026-09-11; stale 450 RPM plot scale still open |
| 39 | 🟢 Low | `VertiSea.ino` / `vertisea_plot_v7.py` | `integ_s` comments and GUI “duty” interpretation no longer match measured-dt integration | ⚠ Open (documentation/semantics) |
| 40 | 🟡 Medium | `vertisea_plot_v7.py` | SD parser materialises every expanded sample and blocks the Tk main thread | ⚠ Open |
| 41 | 🔴 Critical | `VertiSea.ino` | Accel and gyro are handed to Madgwick in two different body frames (accel X negated, gyro Y negated) | ⚠ Open |
| 42 | 🟠 High | `VertiSea.ino` / docs | `IMUCal.gyro_bias[]` is millidegrees/s but was documented as °/s — the 2026-04-02 recalibration was applied 1000× too small | 🔄 Docs corrected 2026-09-11; constants still need re-deriving |
| 43 | 🟠 High | `vertisea_plot_v7.py` | GUI raises `TypeError` at startup when the machine has no serial ports, blocking the offline "Load BIN File" workflow | ✅ Resolved 2026-09-11 |
| 44 | 🟠 High | `vertisea_plot_v7.py` | An unplugged radio raises inside the Tk `after()` callback, silently stopping all GUI updates permanently | ✅ Resolved 2026-09-11 |
| 45 | 🟡 Medium | `VertiSea.ino` | `TYPE_CURRENT_STATS.n_dropped` is cumulative since boot while `n_samples` resets per window — the pair cannot be compared | ✅ Resolved 2026-09-11 |
| 46 | 🟡 Medium | `VertiSea.ino` | Magnetometer is a fatal boot dependency but is never read; with `IMU_RAW_ONLY 0` it silently logs constant zeros | ✅ Resolved 2026-09-11 |
| 47 | 🟡 Medium | `VertiSea.ino` | Every sensor init failure halts in `while(1)` with no watchdog — a field buoy bricks itself and logs nothing | 🔄 Halts now blink a diagnostic code and the reset spins are bounded; halt-vs-degrade policy still open |
| 48 | 🟡 Medium | `vertisea_plot_v7.py` | Live parser redraws three matplotlib canvases per packet inside the drain loop | ✅ Resolved 2026-09-11 |
| 49 | 🟢 Low | `vertisea_plot_v7.py` | `_ts10_last` is only advanced by `0x06`, so the RPM series can mis-handle a ts10 wrap | ✅ Resolved 2026-09-11 |
| 50 | 🟢 Low | `vertisea_plot_v7.py` | `connect_serial()` never closes a previously opened port | ✅ Resolved 2026-09-11 |
| 51 | 🟢 Low | `vertisea_plot_v7.py` | `load_bin_file()` summary omits `imu_raw`, `rtc_event`, `fixed_cal`, `stab_cal` — the default build reports zero IMU records | ✅ Resolved 2026-09-11 |
| 52 | 🔴 Critical | `current_filter_test.py` | Baseline subtraction clamped at zero, half-wave rectifying the noise and fabricating ~3854 mC of charge per idle day | ✅ Resolved 2026-09-11 |
| 53 | 🔴 Critical | `VertiSea.ino` | `sdError` was a one-way latch — one transient write failure ended logging for the whole deployment | ✅ Resolved 2026-09-11 |
| 54 | 🟠 High | `VertiSea.ino` | Hall ISR accepted every edge, so harvester EMI caused an interrupt storm → loop starvation → SD queue overrun | ✅ Resolved 2026-09-11 |
| 55 | 🟠 High | `VertiSea.ino` | LED heartbeat used `digitalRead()` on an OUTPUT pad, which can latch the LED on | ✅ Resolved 2026-09-11 |
| 56 | 🟠 High | `current_filter_test.py` | Median-5 main stage cannot reproduce a scope's High-Resolution mode and shifted integrated charge by +2.79% | ✅ Resolved 2026-09-11 |
| 57 | 🟠 High | `VertiSea.ino` | No watchdog: an I²C stall hangs the board permanently, losing a multi-day deployment | ⚠ Open |
| 58 | 🔴 Critical | `VertiSea.ino` / `Madgwick/` | Vendored Madgwick sat outside the sketch folder, so Arduino could not see it and silently compiled a global copy with a different `betaDef` | ✅ Resolved 2026-09-11 |
| 59 | 🔴 Critical | `VertiSea.ino` / toolchain | `hallISR()` calls `micros()`, which is not ISR-safe on Apollo3 core 2.x (mbed) — a single Hall edge panics the kernel | ⚠ Open — build on core 1.2.1 |

---

## Detailed Issue Descriptions

---

### Issue 1 — 🔴 Critical: `while (!Serial)` blocks boot without USB

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `setup()`
**Status:** ✅ Resolved

**Description:**
`while (!Serial);` waits indefinitely for a USB serial connection. In field deployment
the buoy will have no USB host connected, so the firmware will never proceed past this
line. The device will appear to be dead.

**Impact:** Complete failure to boot in any unattended or field deployment.

**Resolution:**
Added a `USB_DEBUG` compile-time flag (defined near the top of `VertiSea.ino`).

- **`#define USB_DEBUG 1`** (bench/debugging): waits up to 3 s for a USB host before
  continuing, so boot messages are visible in the Arduino Serial Monitor.
- **`#define USB_DEBUG 0`** (field deployment): the `#if USB_DEBUG` block is compiled
  out entirely; the firmware boots immediately without waiting for USB.

`Serial.print()` calls throughout the firmware are safe in both modes — output is
silently discarded when no USB host is connected.

```cpp
#if USB_DEBUG
  {
    unsigned long t0 = millis();
    while (!Serial && millis() - t0 < 3000);
  }
#endif
```

---

### Issue 2 — 🔴 Critical: Log filename collisions can append sessions

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `setup()`
**Status:** 🔄 Fix implemented 2026-09-04; hardware verification pending

**Description:**
The original title incorrectly blamed `millis()` rollover. The actual risk is filename
collision. If the RTC is invalid, a date-based name such as `01010000.BIN` can collide.
Even with a valid RTC, the `MMDDHHmm.BIN` name has only one-minute resolution. A reset
within the same minute opens the same name with `FILE_WRITE`, which appends a second boot
session to the first log. This was observed when opening the GUI reset the board: duplicate
boot/calibration records and a backward `ts_ms` jump landed in one file.

**Impact before the fix:** A filename collision could produce a concatenated multi-session
log whose timestamps reset mid-file, or reuse the invalid-RTC fallback name.

**Implemented resolution:**

- `SD.begin(CS_SD)` now runs before every `SD.exists()` check.
- With valid local time, `MMDDHHmm.BIN` is used only if it does not already exist.
- A same-minute reset or invalid RTC falls back to the first unused `LOGnnnnn.BIN` slot.
- If all 99,999 counter names are occupied, setup halts rather than appending to or
  overwriting an existing log.

This guarantees that `SD.open(..., FILE_WRITE)` receives a previously unused name, avoiding
the library's append-on-open behavior. Hardware verification should cover unused date names,
same-minute collisions, invalid RTC fallback, and preservation of all pre-existing files.

---

### Issue 3 — 🔴 Critical: SD write errors silently ignored after `setup()`

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`
**Status:** ✅ Resolved 2026-09-04 in the buffered writer. Arduino SD 1.3.0's public
`File.flush()` API returns `void`, so a distinct metadata-sync result is not available.

**Description:**
`logFile.write()` returns the number of bytes written, but the return value is never
checked anywhere in `loop()`. If the SD card fills up, is removed, or encounters a
write error, the firmware continues running silently with no data being saved and no
indication to the operator.

**Impact:** Complete data loss for the remainder of a deployment with no visible
indication. The LED heartbeat continues normally.

**Resolution:**
All packet types now pass through `sdAppendRecord()`, and every backend `logFile.write()` checks
the returned byte count. On the first queue overrun or short write, `setSdError()` latches the
global error state. Once set:

- All subsequent SD records and periodic flushes are skipped.
- **Radio telemetry continues unaffected** — `TELEM_WRITE()` is not gated on `sdError`, so the
  ground station keeps receiving live data when telemetry is enabled.
- The LED heartbeat switches from 1 Hz (normal) to **4 Hz rapid flash** so a field operator can identify the fault without a USB connection.

The `sdError` flag is never cleared; a power-cycle is required to reset.

`File.flush()` is still necessarily unchecked because the installed library exposes it as a
`void` method; failures surfaced by the next checked write still latch `sdError`.

---

### Issue 4 — 🟠 High: `vertDisp` / `vertVel` variable shadowing

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`
**Status:** ✅ Resolved

**Description:**  
`vertVel` and `vertDisp` are declared as `static` locals at the top of `loop()` (lines
601–602). They are then re-declared as `static` locals inside the 104 Hz IMU block
(lines 640–641). The inner declarations shadow the outer ones. The telemetry block at
line 692 references `vertDisp` — which resolves to the **outer** (never-written) static,
not the inner one that is actually integrated. The transmitted `vertDisp_mm` is always 0.

**Impact:** Vertical displacement telemetry is always zero. The SD log does not include
`vertDisp` directly, but the telemetry display is incorrect.

**Suggested fix:**  
Remove the duplicate inner declarations (lines 640–641). The outer statics are
sufficient and will be correctly updated by the inner block.

---

### Issue 5 — 🟠 High: `TYPE_MAG` packet uses `millis()` instead of `nowMs`

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`
**Status:** ✅ Resolved

**Description:**  
```cpp
writeHeader(TYPE_MAG, millis());
```
All other packets in the 104 Hz block use `nowMs` (captured at the top of `loop()`).
`TYPE_MAG` calls `millis()` again, introducing a small but unnecessary timestamp
inconsistency between the IMU and mag packets that are supposed to be co-sampled.

**Impact:** Minor timestamp jitter between IMU and mag packets (microseconds to low
milliseconds). Affects time-alignment in post-processing.

**Suggested fix:** Change to `writeHeader(TYPE_MAG, nowMs);`

---

### Issue 6 — 🟠 High: Vertical accel unit error in integration

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`
**Status:** ✅ Resolved

**Description:**  
`computeVerticalAccel()` returns a value in **g** (gravity units, dimensionless ratio).
The code then multiplies by `G = 9.80665` to get m/s². However, `computeVerticalAccel`
subtracts `1.0f` (one g) from the Earth-frame Z acceleration. This subtraction is
correct only if the input accelerations are in g. The LPF-filtered `lastStabIMU.ax/ay/az`
are indeed in g (the calibration divides by `accel_scale` which is in counts-per-g).
The unit chain is correct, but the `IMUData` struct comment on line 77 says "m/s²" for
the filtered accel fields — this is wrong and could cause confusion if someone uses
those values directly assuming m/s².

**Impact:** The integration itself is correct. The misleading comment could cause
incorrect use of `ax/ay/az` values in future code.

**Suggested fix:** Correct the `IMUData` struct comment: `// **filtered** accel (g)`.

---

### Issue 7 — 🟠 High: GPS packet not written when no fix available

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`
**Status:** ✅ Resolved

**Description:**  
The GPS log block only writes a packet when `myGNSS.getPVT()` returns true. If there
is no GPS fix (common at startup or in poor sky view), no `TYPE_GPS` packet is written
for that second. The CSV will have gaps, and the `rtcEvt` packet cannot be used to
infer GPS availability.

**Impact:** GPS availability is not distinguishable from "GPS had a fix but data was
not logged" in post-processing. Gaps in the GPS CSV are ambiguous.

**Suggested fix:**  
Write a GPS packet even without a fix, using a `gpsSats = 0` sentinel and
`lat = lon = alt = 0.0f`, or add a separate `TYPE_GPS_NO_FIX` packet type. At minimum,
document the gap behaviour in `docs/data_pipeline.md`.

---

### Issue 8 — 🟠 High: `TYPE_TELEM_IMU` field labels wrong in Python ground station

**File:** [`vertisea_plot_v7.py`](vertisea_plot_v7.py)
**Status:** ✅ Resolved

**Description:**
Originally the `TYPE_TELEM_IMU` packet comment said "ax_fix, ay_fix, az_stab" and
variables were named `axm`, `aym`, `azm` — stale names from a prior firmware version
that sent raw accelerations. The firmware was already sending `pitch_mdeg`, `roll_mdeg`,
`vertDisp_mm` but the Python labels were wrong.

Fully resolved in 2026-03-30 session: packet expanded to 13 bytes (5 × `int16`), angle
encoding changed from millidegrees (×1000, ±32.767°) to centidegrees (×100, ±327.67°)
to support ±70° operating range. Ground station now shows a 2×2 plot layout — pendulum IMU
pitch & roll (top-left), buoy IMU pitch & roll (bottom-left), tilt difference & RPM (top-right),
and a placeholder (bottom-right).

**Impact:** Operator sees plots labelled as accelerations when they are actually pitch,
roll, and vertical displacement. The y-axis range `(-10, 10)` is set for m/s² but is
appropriate for degrees too, so the plot is not obviously broken — just mislabelled.

**Suggested fix:** Update variable names, plot titles, y-axis labels, and the comment
on line 11 to reflect the actual packet content.

---

### Issue 9 — 🟠 High: `rtc.getYear()` double-subtraction of 2000

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `setup()`
**Status:** ↪ Superseded by Issue 28

> **Audit correction (2026-09-04):** This entry's library interpretation was wrong.
> SparkFun RV8803 `getYear()` returns the full four-digit year and `setYear()` expects the
> full four-digit year. Issue 28 contains the verified library-source analysis and the final
> correction. The current `yearOffset = localYear - 2000` expression is correct because
> `localYear` is four-digit. Retain this entry only as a record of the discarded diagnosis.

**Description:**  
```cpp
uint8_t yearOffset = (uint8_t)(rtc.getYear() - 2000);
```
The SparkFun RV8803 library's `getYear()` already returns a value offset from 2000
(i.e., it returns `25` for 2025, not `2025`). Subtracting 2000 again produces a large
negative number that wraps to a nonsensical `uint8_t` value (e.g., `25 - 2000` wraps
to `41` as uint8_t due to two's complement truncation — coincidentally close to the
correct value for some years but wrong in general).

**Impact:** The `TYPE_RTC_EVENT` packet year field may be incorrect. The parser adds
2000 back, so the CSV year will be wrong.

**Suggested fix:** Verify the RV8803 library's `getYear()` return value. If it already
returns an offset (0–99), change to:
```cpp
uint8_t yearOffset = (uint8_t)rtc.getYear();
```
If it returns a full 4-digit year, keep the subtraction. Check against the library
source or the `rtcEvt` CSV from a known deployment.

---

### Issue 10 — 🟡 Medium: `imuReady` static initialisation

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`
**Status:** ✅ Resolved

**Description:**
`static bool imuReady = false;` is correct C++ — a `static` local is initialised once
and retains its value. This is not a bug. However, the intent is to prevent telemetry
before the first IMU sample. The flag is set to `true` on the first IMU sample and
never reset. This is correct behaviour but worth noting as intentional.

**Impact:** None — this is working as intended. Documented here to prevent a future
"fix" that removes the `static` keyword, which would break the guard.

---

### Issue 11 — 🟡 Medium: `disp_mm` declared but never used

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`
**Status:** ✅ Resolved

**Description:**
`static int16_t disp_mm = 0;` is declared but never written or read. The telemetry
block uses a separately computed `int16_t vertDisp_mm` local variable.

**Impact:** Dead code; wastes 2 bytes of stack. No functional impact.

**Suggested fix:** Remove the declaration.

---

### Issue 12 — 🟡 Medium: `pitch` and `roll` statics never used

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`
**Status:** ✅ Resolved

**Description:**
`static float pitch = 0, roll = 0;` are declared but never written or read. Pitch and
roll are accessed directly from `lastFixedIMU.pitch` and `lastFixedIMU.roll`.

**Impact:** Dead code. No functional impact.

**Suggested fix:** Remove the declarations.

---

### Issue 13 — 🟡 Medium: Shadowed variables in `setup()` GPS sync block

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `setup()`
**Status:** ✅ Resolved

**Description:**
`bool synced`, `unsigned long startSync`, and `unsigned long lastSatPrint` are declared
at the outer scope of the GPS sync block, then re-declared inside the `else` block. The
outer `startSync` is never used (the inner block uses `start`). The outer `synced` and
`lastSatPrint` are shadowed by the inner declarations.

**Impact:** The outer variables are dead code. No functional impact since the inner
variables are used correctly. However, this is confusing and could mask a real bug if
the outer scope is ever referenced.

**Suggested fix:** Remove the outer declarations of `synced`, `startSync`, and
`lastSatPrint`.

---

### Issue 14 — 🟡 Medium: MATLAB parser stops on unknown packet type

**File:** `parse_vertisea_log_v4.m` (deleted 2026-09-03; recoverable from git history at `9f5019f`)
**Status:** ⛔ Obsolete — `parse_vertisea_log_v4.m` was retired 2026-09-03

**Description:**  
The `otherwise` case calls `break`, terminating the entire parse loop. Any unknown
packet type (e.g., from a future firmware version, or a single corrupted byte) will
silently truncate all output after that point.

**Impact:** If a new packet type is added to the firmware before the parser is updated,
or if a single byte is corrupted in the binary file, all data after that point is lost
with only a `warning()` message.

**Suggested fix:**  
Instead of `break`, attempt to skip the unknown packet by reading ahead to the next
known type byte, or at minimum change `break` to `continue` after the warning (though
this will likely desynchronise the parser). The safest fix is to add a packet-length
lookup table so unknown packets can be skipped by their known size.

---

### Issue 15 — 🟡 Medium: `TYPE_SUPERCAP` bytes dropped inefficiently in Python

**File:** [`vertisea_plot_v7.py`](vertisea_plot_v7.py)
**Status:** ⛔ Obsolete — the supercap/current `0x0A` radio packet was retired 2026-09-03

**Description:**
`TYPE_SUPERCAP` (`0x0A`) is transmitted at 5 Hz (5 bytes per packet). The Python parser
had no handler for it, so the fallback `del buffer[0]` path dropped one byte per
iteration. Each 5-byte supercap packet caused 5 parse loop iterations before it was
consumed. At 5 Hz this was 25 wasted iterations per second.

**Impact:** Minor CPU overhead. More importantly, the `0x0A` byte could coincidentally
match a data byte inside another packet type, causing a false parse attempt. In
practice this is unlikely but possible.

**Historical resolution and retirement:** A `TYPE_SUPERCAP` handler once consumed the full
packet atomically. A14 was later repurposed for harvested current, and `0x0A` was finally
retired because the 5 Hz point sample was biased. The current GUI has no `0x0A` live handler;
it displays current statistics from `TYPE_CURRENT_STATS` (`0x0F`). Legacy SD `0x0A` records
remain readable only for old logs.

---

### Issue 16 — 🟡 Medium: `ts10` timestamp wraps after ~655 seconds

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`; [`vertisea_plot_v7.py`](vertisea_plot_v7.py)
**Status:** ✅ Resolved

**Description:**  
`uint16_t ts10 = uint16_t(lastRFDSend / 10)` overflows when `millis()` exceeds
`65535 * 10 = 655,350 ms` (~10.9 minutes). After that, the timestamp wraps to 0 and
counts up again. The Python ground station uses this timestamp for the x-axis of the
rolling plot, so the plot x-axis will reset every ~11 minutes.

**Impact:** Rolling plot x-axis resets every ~11 minutes. Not a data loss issue (SD
log uses full `uint32_t` timestamps), but the ground station plot becomes confusing
during long deployments.

**Suggested fix:** Use `uint32_t` for the telemetry timestamp, or accept the wrap and
handle it in the Python script by detecting backward jumps and offsetting accordingly.

---

### Issue 17 — 🟡 Medium: `vertDisp_mm` computed twice in telemetry block

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`
**Status:** ✅ Resolved

**Description:**
```cpp
int16_t vertDisp_mm = int16_t(vertDisp * 1000.0f);  // unused local
...
int16_t(vertDisp * 1000.0f)  // used in struct init (recomputed inline)
```
The local `vertDisp_mm` was computed but not used in the struct initialiser, which
recomputed the same expression inline. Due to Issue 4 (variable shadowing), `vertDisp`
referred to the outer static (always 0), so both were 0.

**Impact:** Dead code. No functional impact beyond Issue 4.

**Suggested fix:** After fixing Issue 4, use the local variable in the struct init:
`int16_t(vertDisp_mm)`.

---

### Issue 18 — 🟢 Low: `printAligned()` defined but never called — resolved

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino)
**Status:** ✅ Resolved 2026-09-04 — dead helper removed during pre-commit cleanup.

> **Audit update (2026-09-04):** Active calls were later commented out with the rest of the
> debug output. `printAligned()` again has no active call site. Remove it or restore useful
> debug output.
>
> **Resolution update (2026-09-04):** The dead helper and its commented call sites were removed.

**Description:**
The `printAligned()` helper function is defined but has no call sites. It was likely
used in a previous debug print block that was removed.

**Impact:** Dead code. Wastes a small amount of flash.

**Suggested fix:** Remove the function, or add a call in the debug block (Issue 19).

---

### Issue 19 — 🟢 Low: Debug block is empty — resolved

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`
**Status:** ✅ Resolved 2026-09-04 — the block now prints active SD queue occupancy,
high-water, maximum write latency, and overrun diagnostics when `USB_DEBUG=1`; stale commented
calibration output was removed.

> **Audit update (2026-09-04):** The block still updates `lastDebugTime`, but every print in
> it is inside a block comment. It therefore performs no output even when `USB_DEBUG=1`.
>
> **Resolution update (2026-09-04):** Active SD queue diagnostics now use the block.

**Description:**
The 1 Hz debug print block fires every second but contains no code. It consumes a
`millis()` comparison and a branch with no output.

**Impact:** Negligible CPU overhead. No functional impact.

**Suggested fix:** Either add useful debug output (e.g., pitch, roll, supercap voltage)
or remove the block entirely.

---

### Issue 20 — 🟢 Low: `IMUData` accel comment says m/s² but values are in g

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino)
**Status:** ✅ Resolved

**Description:**  
```cpp
float ax, ay, az;       // **filtered** accel (m/s²)
```
The filtered accel values stored in `IMUData` are in **g** (gravity units), not m/s².
The conversion to m/s² only happens in `computeVerticalAccel()` via multiplication by
`G = 9.80665`. The CSV columns are also in g.

**Impact:** Misleading comment could cause incorrect unit assumptions in future code.

**Suggested fix:** Change comment to `// **filtered** accel (g)`.

---

### Issue 21 — 🟠 High: Vertical displacement drifts unboundedly

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`, integration block
**Status:** ✅ Resolved

**Description:**
The vertical displacement integrator accumulates a persistent DC bias in `a_vert` even
after startup bias calibration, causing `vertDisp` to grow on a stationary bench. The
runtime bias calibration block (3-phase warmup + averaging + slow EMA) also caused NaN
pitch/roll output because it required the board to be stationary at startup — a condition
that cannot be guaranteed in field deployment (see Issue 23).

**Resolution:**
The runtime bias calibration block was removed entirely. The integration now runs
unconditionally with a simple exponential leak (`vertVel *= 0.9995f`, `vertDisp *= 0.9995f`,
τ ≈ 19.2 s) to suppress long-period drift. Vertical displacement accuracy depends on
IMU calibration quality; re-running the accel calibration for the stabilized IMU is the
recommended path to improving accuracy. See also the Madgwick beta TODO in the firmware.

---

### Issue 22 — 🔴 Critical: SD filename and `TYPE_RTC_EVENT` timestamp use UTC instead of local time

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `setup()`
**Status:** ✅ Resolved

**Description:**
After GPS time sync, the RTC is set to UTC (correct — the RTC always stores UTC). However,
the SD filename (`MMDDHHmm.BIN`) and the `TYPE_RTC_EVENT` boot record were both generated
by re-reading from the RTC, which returns UTC values. The USB Serial debug output correctly
showed local time (the timezone offset was applied for printing), but the filename and
binary log timestamp were 7 hours ahead (UTC-7 timezone).

**Impact:** Log filenames do not match the operator's wall-clock time. The `TYPE_RTC_EVENT`
packet written to the binary log contains UTC time, so the parser's absolute time anchor
is offset from local time by `timezoneOffsetHours`.

**Resolution:**
Six `local*` variables (`localYear`, `localMonth`, `localDay`, `localHour`, `localMin`,
`localSec`) are now computed at `setup()` scope by applying `timezoneOffsetHours` to the
GPS UTC fix (or to the RTC's stored UTC if no GPS fix is obtained). Full day/month/year
rollover is handled. Both the SD filename and the `TYPE_RTC_EVENT` packet now use these
local-time variables. The RTC hardware register continues to hold UTC.

---

### Issue 23 — 🟠 High: Runtime accel bias calibration causes NaN pitch/roll

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `loop()`, bias calibration block
**Status:** ✅ Resolved

**Description:**
The 3-phase runtime bias calibration block (added in commit `59d5710`) required the board
to be stationary during the 10 s warmup + calibration window at startup. In field
deployment the board may be moving immediately after power-on (e.g., being carried to the
deployment site or already in the water). When the board is not stationary, `a_vert`
accumulates large values during Phase 2, `biasAccum` becomes large or NaN, and
`aVertBias` is set to a bad value. In Phase 3, `a_vert -= aVertBias` can produce NaN
which then propagates permanently through `vertVel` and `vertDisp`. Although NaN in the
displacement integrator does not feed back into the Madgwick filter directly, the
combination of a moving board and the high Madgwick beta (`0.5`) caused the filter to
produce NaN pitch/roll within ~10–15 seconds of boot on a bench test.

**Resolution:**
The runtime bias calibration block was removed entirely (see Issue 21 resolution). The
integration now runs unconditionally from the first IMU sample.

---

### Issue 24 — 🔴 Critical: ISM330DHCX sensor freeze causes near-zero accel → Madgwick diverges to NaN pitch/roll

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `collectIMUData_ISM()`
**Status:** ✅ Resolved

**Description:**
The ISM330DHCX IMU occasionally freezes mid-session and begins outputting raw zeros from
its hardware registers. After the offline bias/scale calibration is applied, the frozen
raw zeros produce a calibrated accelerometer vector with magnitude ≈ 0.031 g (the residual
comes from the non-zero accel bias values in `stabCal`). The frozen gyroscope similarly
produces small non-zero values equal to the negated gyro bias.

The Madgwick AHRS library's existing guard is:
```cpp
recipNorm = invSqrt(ax * ax + ay * ay + az * az);
if (isinf(recipNorm)) return;   // only catches exactly-zero accel
```
Because the frozen accel magnitude is ~0.031 g (not exactly zero), `invSqrt(0.031²+…) ≈ 32`
— not infinity — so the guard does **not** trigger. The filter continues running with a
near-zero accel vector. The gradient-descent correction step is scaled by `recipNorm`, so
it becomes ~32× larger than normal, causing the quaternion to diverge. Within ~1 second
the quaternion overflows, and `asin(2*(q1*q3 - q0*q2))` receives a value outside [−1, 1],
producing NaN pitch/roll that propagates permanently.

**Evidence from `04011913_imuStab.csv`:**
- t = 57 706 ms: gz jumps to 100.2 °/s (sensor glitch / partial reset)
- t = 59 389 ms: accel magnitude collapses from 0.43 g → 0.019 g over 70 ms
- t = 59 459 ms: accel and gyro values freeze at constants
  - `gx = −0.3845 °/s`, `gy = −0.4385 °/s`, `gz = −0.1133 °/s`
    (= `−stabCal.gyro_bias × 0.001`, confirming raw output = 0)
  - `ax = −0.003793 g`, `ay = 0.017866 g`, `az = −0.025398 g`
    (= residual from accel bias subtraction on raw zero)
  - Accel magnitude ≈ 0.031 g
- t = 60 456 ms: **first NaN** — pitch = nan, roll = nan
- All subsequent rows: pitch/roll remain NaN; sensor values remain frozen

**Impact:** Permanent NaN pitch/roll for the remainder of the session. All telemetry and
SD-logged attitude data is invalid after the sensor freeze event.

**Resolution:**
Added a `ACCEL_MIN_SQ_MAG` constant (`0.25 g²`, corresponding to a minimum magnitude of
0.5 g) and an `accelValid` flag in `collectIMUData_ISM()`. Both the 9-DOF
(`filt.update()`) and 6-DOF (`filt.updateIMU()`) Madgwick calls are now gated on
`accelValid`. When the sensor is frozen and the accel magnitude is below 0.5 g, the
Madgwick update is skipped entirely. The filter retains its last valid quaternion, so
pitch/roll hold their last good values rather than diverging to NaN.

The fix is applied in `VertiSea.ino` only — the vendored `Madgwick/src/MadgwickAHRS.cpp`
library is not modified.

```cpp
static const float ACCEL_MIN_SQ_MAG = 0.25f;  // require ≥ 0.5 g magnitude
// ...
float accelSqMag = state.ax*state.ax + state.ay*state.ay + state.az*state.az;
bool accelValid = (accelSqMag >= ACCEL_MIN_SQ_MAG);
// ...
if (accelValid) {
    filt.updateIMU(state.gx, state.gy, state.gz,
                   state.ax, state.ay, state.az);
}
```

**Note:** The root cause of the sensor freeze itself (I²C bus lockup, sensor power issue,
or ISM330DHCX firmware bug) has not been identified. The fix prevents NaN propagation but
does not recover the sensor. A future improvement could detect the freeze condition
(same raw register values repeated N times) and issue a soft-reset via `imu.deviceReset()`.

---

### Issue 25 — 🟠 High: Both IMUs freeze simultaneously — shared I²C bus root cause

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `collectIMUData_ISM()`, `loop()`
**Status:** ✅ Resolved

> **Resolution:** root-caused to Issue 27 (GPS module absent from the I²C bus) and
> mitigated by `GPS_ENABLE 0` plus the accel-magnitude guard from Issue 24. The analysis
> below is retained because it documents the failure signature and the diagnostic
> reasoning; the "Suggested fixes" list is kept as reference for any recurrence.

> **Update (2026-04-02):** Comparative diff of the initial commit vs. current code
> identified two changes introduced after the initial commit that are the most
> likely triggers for the simultaneous freeze. See **Issue 27** for the confirmed
> root cause (GPS module absent from I²C bus causes `myGNSS.begin()` to corrupt
> or lock the bus). The I²C bus contention mechanism described below remains the
> correct framework.

**Description:**
Comparative analysis of `04011913_imuFixed.csv` (fixed IMU, I²C 0x6A) and
`04011913_imuStab.csv` (stabilized IMU, I²C 0x6B) from the same session reveals that
both sensors exhibit identical failure signatures at identical timestamps. This rules out
individual sensor hardware failure and points to a shared firmware or hardware cause.

**Evidence — simultaneous gz spikes (both IMUs, same loop iteration):**

| Timestamp (ms) | Fixed gz (°/s) | Stab gz (°/s) |
|----------------|----------------|---------------|
| 2 013 | 152.29 | 152.10 |
| 16 236 | 152.22 | 152.00 |
| 20 256 | 152.29 | 152.08 |
| 35 496 | −8.24 → 152.24 (next row) | 151.99 |

During each spike:
- `gz` jumps to ~152 °/s in **both** sensors simultaneously (raw ≈ 152 000 mdps)
- `gy` freezes at its raw-zero equivalent in both sensors:
  - Fixed: `gy = −0.3968 °/s` = `−(0 − (−396.8)) × 0.001`
  - Stab: `gy = −0.4385 °/s` = `−(0 − (−438.5)) × 0.001`
- `gz` then converges toward ~215 °/s over ~1 second before recovering to normal

**Evidence — simultaneous permanent freeze and NaN onset:**

| Event | Fixed IMU | Stab IMU |
|-------|-----------|----------|
| Accel collapses | t ≈ 59 389 ms | t ≈ 59 459 ms |
| Gyro/accel freeze at raw-zero equivalents | t ≈ 59 389 ms | t ≈ 59 459 ms |
| **First NaN pitch/roll** | **t = 60 456 ms** | **t = 60 456 ms** |

The NaN onset is **identical to the millisecond** in both IMUs. Both sensors are read
sequentially in the same `loop()` iteration; the IIR filter time constant (~1 s) explains
the ~1 s gap between freeze and NaN.

**Frozen values confirm raw-zero output:**
- Fixed: `gx = +0.00236 °/s`, `gy = −0.3968 °/s`, `gz = +0.1925 °/s`
  (= `−fixedCal.gyro_bias × 0.001` for each axis)
- Stab: `gx = −0.3845 °/s`, `gy = −0.4385 °/s`, `gz = −0.1133 °/s`
  (= `−stabCal.gyro_bias × 0.001` for each axis)

**Prime firmware suspect — `imu.checkStatus()` on a shared I²C bus:**

```cpp
// collectIMUData_ISM(), line 416 — called unconditionally before every read:
imu.checkStatus();          // reads STATUS_REG over I²C
imu.getAccel(&accelData);
imu.getGyro (&gyroData);
```

Both ISM330DHCX sensors share the same `Wire` I²C bus (only the 7-bit address differs:
0x6A vs 0x6B). `checkStatus()` reads the `STATUS_REG` register. If the I²C bus glitches
(electrical noise, bus contention, or a momentary power droop) during this call, the
SparkFun ISM330DHCX library may not detect the error and subsequent `getAccel()` /
`getGyro()` calls may return stale or zero data from the library's internal buffers.
Because both sensors are read in the same `loop()` iteration, a single I²C glitch can
corrupt both sensors' data simultaneously.

**Impact:**
- Transient gz spikes corrupt attitude estimates for ~1 second per event (4 events observed
  in a ~60 s session).
- The permanent freeze at t ≈ 59 s renders both IMUs invalid for the rest of the session.
- The accel magnitude guard (Issue 24 fix) prevents NaN propagation but does not prevent
  the transient spikes or recover the sensor after a permanent freeze.

**Suggested investigation / mitigations:**

1. **Check `checkStatus()` return value** — the SparkFun library returns `true` if new
   data is available. If it returns `false`, skip `getAccel()` / `getGyro()` for that
   iteration rather than reading stale data:
   ```cpp
   if (!imu.checkStatus()) return lastGoodData;  // no new data — skip
   ```

2. **Add I²C error detection** — after `getAccel()` / `getGyro()`, check
   `Wire.endTransmission()` status or use a "same-value N times" staleness detector:
   ```cpp
   // Detect frozen sensor: if raw values unchanged for N consecutive reads, flag error
   static sfe_ism_data_t prevAccel{}, prevGyro{};
   static uint8_t frozenCount = 0;
   if (accelData.xData == prevAccel.xData && accelData.yData == prevAccel.yData &&
       accelData.zData == prevAccel.zData) {
     if (++frozenCount >= 5) { /* sensor frozen — attempt reset */ }
   } else { frozenCount = 0; }
   prevAccel = accelData;  prevGyro = gyroData;
   ```

3. **Soft-reset on freeze** — the ISM330DHCX supports a software reset via
   `imu.deviceReset()`. If the staleness detector fires, call `deviceReset()` and
   re-initialise the sensor.

4. **Investigate power supply** — a shared 3.3 V rail powering both sensors could droop
   under load (e.g., SD write burst), causing both sensors to reset simultaneously.
   Scope the 3.3 V rail during an SD write to check for voltage droop.

5. **Separate I²C buses** — if the Artemis Nano exposes a second I²C peripheral (`Wire1`),
   placing each IMU on its own bus would prevent a single bus glitch from corrupting both
   sensors.

---

### Issue 26 — 🟡 Medium: `TELEM_SERIAL.begin(115200)` — verify RFD900 modem baud rate matches before next deployment

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `setup()`
**Status:** ↪ Tracked by Issue 36

> **Audit update (2026-09-04):** Keep the baud check in the Issue 36 radio verification
> checklist rather than tracking two overlapping open issues. No evidence was found that
> 115200 baud itself caused the historical IMU freeze; Issue 27 established the absent-GPS
> I²C failure as that root cause.

> **Severity downgraded 🔴 → 🟡** to match the issue index. The IMU-freeze symptom that
> originally motivated this entry was root-caused to Issue 27 (absent GPS module hanging
> the I²C bus), not to the baud-rate change. What remains open is the narrower
> configuration check below: confirming the RFD900's own stored baud rate is 115200.
>
> **Naming note:** the identifier `sharedSerial` used throughout the analysis below has
> since been renamed to the `TELEM_SERIAL` macro in the firmware.

**Description:**
A diff of the initial commit (`764ddb3`) against the current working tree reveals
two changes introduced after the initial commit that are the most likely root cause
of the simultaneous IMU freeze observed in `04011913_imuFixed.csv` /
`04011913_imuStab.csv`. The freeze was **not present** in sessions recorded with
the initial-commit firmware.

**Change 1 — Serial baud rate doubled (primary suspect):**

```diff
-  sharedSerial.begin(57600);   // initial commit
+  sharedSerial.begin(115200);  // current code
```

The RFD900 radio modem on `Serial1` was originally configured at **57,600 baud**.
The current firmware initialises it at **115,200 baud**. If the modem's own serial
baud rate setting (stored in its non-volatile configuration) has not been updated to
match, the UART framing is wrong and the modem's internal processor will be
continuously busy handling framing errors and re-synchronising. More critically:

- At 115,200 baud the firmware pushes **more bytes per second** into the modem's
  TX buffer. The RFD900's RF power amplifier fires in bursts whenever the modem
  transmits over the air. Each RF burst draws a significant current spike (the
  RFD900 datasheet specifies up to **800 mA peak** at 1 W output power).
- The IMU telemetry block fires at **5 Hz** (13-byte `TelemetryPacket` + 5-byte
  `SupercapPacket` = 18 bytes every 200 ms), and the IMU SD-log block fires at
  **104 Hz** (no radio bytes, but the SD SPI bus is active). The 1 Hz status
  packet adds another burst.
- If the 3.3 V rail powering both ISM330DHCX sensors is shared with the RFD900
  modem's logic supply (common on the SparkFun RedBoard Artemis Nano carrier
  boards), each RF burst can droop the 3.3 V rail by tens of millivolts for
  several microseconds. The ISM330DHCX minimum supply voltage is 1.71 V, but
  the I²C bus hold-time and setup-time specifications assume a stable VDD. A
  rail droop during an active I²C transaction can corrupt the byte being
  transferred, leaving the I²C bus in a partially-clocked state. Both IMUs are
  read in the **same `loop()` iteration** from the same `Wire` bus, so a single
  droop event corrupts both simultaneously.

**Change 2 — GPS sync timeout increased from 100 ms to 120 s (contributing factor):**

```diff
-const unsigned long GPS_SYNC_TIMEOUT_MS = 100UL;    // initial commit — effectively skips GPS sync
+const unsigned long GPS_SYNC_TIMEOUT_MS = 120000UL; // current code — waits up to 2 minutes
```

During the GPS sync loop in `setup()`, `myGNSS.getPVT()` is called every 100 ms
for up to 2 minutes. The u-blox GNSS module communicates over the **same `Wire`
I²C bus** as both ISM330DHCX sensors, the RV8803 RTC, the BME280, and the
MMC5983MA magnetometer. The u-blox library uses I²C clock stretching extensively
during PVT parsing. If the GNSS module holds SCL low for longer than the
ISM330DHCX's I²C timeout, the IMU's internal I²C state machine can lock up. This
would not cause a freeze during `loop()` (the IMUs are not read during `setup()`),
but it could leave the IMU I²C interface in a degraded state that makes it
susceptible to the power-rail droop described above.

**Evidence linking the baud-rate change to the freeze timing:**

The freeze events in `04011913_imuFixed.csv` / `04011913_imuStab.csv` occur at:
- t ≈ 2 013 ms, 16 236 ms, 20 256 ms, 35 496 ms (transient gz spikes)
- t ≈ 59 389 ms (permanent freeze)

The 5 Hz telemetry interval is 200 ms. The transient spikes are not evenly spaced
at 200 ms multiples, which is consistent with the RF burst timing being
asynchronous to the IMU sample clock — the droop only corrupts an I²C transaction
when the RF burst happens to overlap with an active `Wire` transfer.

**Impact:**
- Both IMUs freeze simultaneously, rendering all attitude data invalid for the
  remainder of the session.
- The accel magnitude guard (Issue 24 fix) prevents NaN propagation but does not
  prevent the freeze or recover the sensor.

**Suggested fixes (in priority order):**

1. **Revert the baud rate to 57,600** to match the RFD900 modem's configured
   serial baud rate, restoring the initial-commit behaviour:
   ```cpp
   sharedSerial.begin(57600);
   ```
   If 115,200 baud is desired for lower radio latency, **first reconfigure the
   RFD900 modem** (via AT commands or the RFD900 configuration tool) to match,
   then update the firmware. Do not change one without the other.

2. **Scope the 3.3 V rail** during a telemetry burst to confirm the droop
   hypothesis. If droops > 50 mV are observed, add a 100 µF bulk capacitor close
   to the ISM330DHCX VDD pins to absorb the transient.

3. **Add a `Wire.setClock()` call** after `setup()` to ensure the I²C bus is
   running at a known speed (400 kHz fast-mode) and has not been left in a
   degraded state by the GPS sync loop:
   ```cpp
   Wire.setClock(400000);  // after GPS sync loop, before loop() starts
   ```

4. **Issue an I²C bus recovery sequence** at the start of `loop()` if the IMU
   data appears frozen (same raw values N times in a row), using the staleness
   detector described in Issue 25 suggestion 2.

---

### Issue 27 — 🔴 Critical: GPS module absent from I²C bus — `myGNSS.begin()` corrupts bus, freezing both IMUs

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `setup()`, `loop()`
**Status:** ✅ Resolved

> **Resolution:** the `GPS_ENABLE` compile-time flag now gates every GPS code path —
> the `SFE_UBLOX_GNSS` object declaration, `myGNSS.begin()`, the boot time-sync loop, the
> 1 Hz SD-log block, and the 5 s GPS telemetry block are all compiled out when
> `GPS_ENABLE 0`. The flag is currently `0` in the committed firmware. This also resolved
> Issue 25 (simultaneous IMU freeze).
>
> **Operational requirement:** `GPS_ENABLE` must be set back to `1` when a u-blox module
> is reattached, and must remain `0` whenever it is absent.

**Description:**
When the u-blox GNSS module is **physically disconnected** from the I²C bus, the
firmware still calls `myGNSS.begin()` in `setup()` and `myGNSS.getPVT()` in
`loop()`. These calls leave the I²C bus in a corrupted state that causes both
ISM330DHCX IMUs to freeze simultaneously.

**Mechanism — `myGNSS.begin()` in `setup()`:**

The SparkFun u-blox library's `begin()` performs an I²C address scan and attempts
to communicate with the module at its default address (0x42). When no device
responds at that address, the I²C master (Artemis Nano) sends a START condition,
the address byte, and then waits for an ACK that never arrives. The `Wire` library
eventually times out and returns NACK. However, depending on the state of the bus
at the moment of the failed transaction, the SCL/SDA lines may not be cleanly
returned to the idle (high) state. If SDA is left low after a failed transaction
(a known I²C bus-hang condition), all subsequent `Wire` transactions — including
reads from the ISM330DHCX sensors — will fail because the bus appears permanently
busy. The `begin()` call returns `false` (GNSS not detected), but the bus damage
is already done.

**Mechanism — `myGNSS.getPVT()` in `loop()`:**

Even after `begin()` returns `false`, the firmware's 1 Hz GPS block still calls
`myGNSS.getPVT()` unconditionally:

```cpp
// loop() — 1 Hz GPS block (current code):
if (nowMs - lastGPSTime >= GPS_INTERVAL_MS) {
    lastGPSTime = nowMs;
    if (myGNSS.getPVT()) {   // ← called even when begin() returned false
        ...
    }
    ...
}
```

Each `getPVT()` call on an absent device repeats the failed I²C transaction at
1 Hz, continuously re-corrupting the bus. The 104 Hz IMU reads interleaved between
these 1 Hz GPS polls encounter a bus that is intermittently in a bad state,
producing the transient gz spikes and eventually the permanent freeze.

**Why this was not a problem in the initial commit:**

The GPS module was **always physically connected** in the initial-commit test
sessions. The `myGNSS.begin()` call succeeded, and `getPVT()` communicated with a
real device. Removing the GPS module was a new operating mode not tested with the
initial firmware.

**Confirmation:**
- Freeze present when GPS module is unplugged (I²C bus corrupted by failed
  `myGNSS.begin()` + repeated `getPVT()` calls).
- Freeze absent when GPS module is plugged in (all I²C transactions succeed).
- Confirmed by hardware test, 2026-04-02.

**Suggested fix:**
Add a `GPS_ENABLE` compile-time flag (analogous to `USB_DEBUG`). When
`GPS_ENABLE 0`, all GPS-related code — `myGNSS.begin()`, `setI2COutput()`,
`setAutoPVT()`, `getPVT()`, and the GPS SD-log and telemetry blocks — is compiled
out entirely. This eliminates all failed I²C transactions when the GPS module is
not connected, and saves power by not polling a non-existent device.

```cpp
#define GPS_ENABLE 1   // 1 = GPS module connected; 0 = GPS absent (saves power, prevents I²C corruption)
```

---

## Resolution Log

| # | Date | Resolution summary | Confirmed by |
|---|------|--------------------|-------------|
| 1 | 2026-03-27 | Added `USB_DEBUG` flag + 3 s timeout; `#if USB_DEBUG` block compiled out in field mode | Code review |
| 2 | 2026-03-27 | Added RTC validity check (`getYear() >= 24`); falls back to `LOGnnnnn.BIN` counter when RTC is unset | Code review |
| 3 | 2026-03-27 | Added `sdError` flag; write-checked at 104 Hz IMU path; all SD writes gated; LED switches to 4 Hz error flash; telemetry continues | Code review |
| 4 | 2026-03-30 | Removed inner `static float vertVel/vertDisp` declarations inside the 104 Hz IMU block; outer statics now correctly updated and read by telemetry block. Also fixed telemetry struct to use pre-computed `vertDisp_mm` local (fixes #17 double-compute as a side effect) | Code review |
| 5 | 2026-03-30 | Changed `writeHeader(TYPE_MAG, millis())` → `writeHeader(TYPE_MAG, nowMs)` so mag packet timestamp is co-captured with all other 104 Hz packets | Code review |
| 6 | 2026-03-30 | Confirmed unit chain is correct (accel in g → multiply by G → m/s²); `IMUData` struct comment already reads `// filtered accel (g)` — no code change required | Code review |
| 7 | 2026-03-30 | GPS block now always writes a `TYPE_GPS` packet each second; when `getPVT()` returns false, sentinel values (`gpsSats=0`, `lat/lon/alt=0.0f`) are written so the CSV has no gaps | Code review |
| 8 | 2026-03-30 | Already resolved prior to this session — `vertisea_plot_v7.py` correctly uses `pitch_mdeg/roll_mdeg/disp_mm` variable names, degrees/metres axis labels, and correct plot titles | Code review |
| 9 | 2026-03-30 | Confirmed via `SampleData/05300428_rtcEvt.csv` (year=2073 instead of 2025). Removed `- 2000` from `yearOffset` calculation — `rtc.getYear()` already returns offset-from-2000 (e.g. 25 for 2025). MATLAB parser adds 2000 back, so result is now correct. | Sample data + code review |
| 14 | 2026-03-30 | Added `knownPayloadBytes` lookup table (`containers.Map`) in `parse_vertisea_log_v4.m` mapping all 9 known packet types to their payload sizes. `otherwise` block now checks the map: if the type is known (no handler yet), skips its payload bytes and warns; if truly unknown, warns with file offset and breaks. Parser stays synchronised across future packet types. | Code review |
| 10 | 2026-03-30 | Confirmed working as intended — `static bool imuReady` is correct C++; initialised once, persists across `loop()` calls. Added explanatory comment in code to prevent accidental removal of `static` keyword. No code change required. | Code review |
| 11 | 2026-03-30 | Removed dead `static int16_t disp_mm = 0` declaration from `loop()` — never written or read | Code review |
| 12 | 2026-03-30 | Removed dead `static float pitch = 0, roll = 0` declarations from `loop()` — never written or read; values accessed directly from `lastFixedIMU` | Code review |
| 13 | 2026-03-30 | Removed dead outer `bool synced`, `unsigned long startSync`, and `unsigned long lastSatPrint` declarations from `setup()` GPS sync block — all three were shadowed by inner declarations inside the `else` block | Code review |
| 16 | 2026-03-30 | Fixed in Python ground station (`vertisea_plot_v7.py`): added `_ts10_last` / `_ts10_offset` state to `VertiSeaGUI`; each backward jump in `ts10` adds 65536×0.01 s to the offset, making the plot x-axis monotonic across rollovers. Firmware `ts10` field unchanged (SD log uses full `uint32_t` timestamps). | Code review |
| 17 | 2026-03-30 | Already resolved as a side effect of fixing Issue 4 — `vertDisp_mm` local is computed once and used directly in the `TelemetryPacket` struct init; inline recomputation removed | Code review |
| 20 | 2026-03-30 | Changed `IMUData::ax/ay/az` comment from `// filtered accel (g)  ← NOTE: units are g, not m/s²` to `// **filtered** accel (g)` per suggested fix | Code review |
| 18 | 2026-03-30 | Changed `Serial.print(s)` → `DBG_PRINT(s)` in `printAligned()` so output is gated by `USB_DEBUG`; removed "unused" note from comment | Code review |
| 19 | 2026-03-30 | Populated 1 Hz debug block with `printAligned()` calls for pitch, roll, and vertical displacement (mm); block now prints a compact status line once per second when `USB_DEBUG=1` | Code review |
| — | 2026-03-30 | Increased `GPS_SYNC_TIMEOUT_MS` from `100UL` to `120000UL` (2 minutes) so the firmware waits long enough for a GPS cold-start fix to set the RTC. The 100 ms value was effectively skipping GPS sync entirely, leaving the RTC with corrupted/unset values. | Hardware test |
| 21 | 2026-04-01 | Removed runtime bias calibration block (3-phase warmup + averaging + slow EMA). Integration now runs unconditionally with exponential leak (`vertVel *= 0.9995f`, `vertDisp *= 0.9995f`). Vertical displacement accuracy depends on IMU calibration quality. | Code review |
| 22 | 2026-04-01 | Promoted `local*` time variables to `setup()` scope; SD filename and `TYPE_RTC_EVENT` packet now use timezone-adjusted local time. RTC hardware continues to store UTC. No-GPS fallback path also applies timezone offset. | Code review |
| 23 | 2026-04-01 | Removed runtime bias calibration block — root cause of NaN pitch/roll when board is not stationary at startup. See Issue 21 resolution. | Code review |
| 24 | 2026-04-02 | Added `ACCEL_MIN_SQ_MAG = 0.25f` guard in `collectIMUData_ISM()`. Both `filt.update()` and `filt.updateIMU()` are now skipped when filtered accel magnitude < 0.5 g, preventing Madgwick divergence when the ISM330DHCX freezes and outputs near-zero accel. Root cause of sensor freeze not yet identified. | Data analysis (`04011913_imuStab.csv`) + code review |
| 15 | 2026-04-23 | Added `TYPE_SUPERCAP` handler in `vertisea_plot_v7.py` that unpacks all 5 bytes (`struct.unpack('<BHH', pkt)`) and updates `supercap_var`; no more one-byte-at-a-time fallback for supercap packets | Code audit |
| 26 | 2026-04-02 | Identified via initial-commit diff as a risk (baud-rate mismatch between firmware and RFD900 modem). Not the root cause of the IMU freeze. Remains open — verify RFD900 modem baud rate is 115200 before next deployment. | Initial-commit diff analysis |
| 25 | 2026-04-02 | Root cause confirmed as Issue 27. Both IMUs freeze simultaneously because `myGNSS.begin()` + repeated `getPVT()` calls corrupt the shared I²C bus when the GPS module is absent. Fixed by `GPS_ENABLE` flag. | Hardware test (GPS plug/unplug, 2026-04-02) |
| 27 | 2026-04-02 | Added `#define GPS_ENABLE 1` flag in deployment flags section. When `GPS_ENABLE 0`: `SFE_UBLOX_GNSS myGNSS` object, entire GPS sync block in `setup()`, 1 Hz GPS SD-log block, and 5 s GPS telemetry block in `loop()` are all compiled out via `#if GPS_ENABLE` / `#endif`. Eliminates all failed I²C transactions when GPS module is not physically connected, preventing I²C bus-hang that froze both IMUs. | Hardware test (GPS plug/unplug, 2026-04-02) + code review |
| 28 | 2026-04-02 | Two-part fix: (1) `rtc.setYear(gpsYear - 2000)` → `rtc.setYear(gpsYear)` — `setYear()` subtracts 2000 internally, so passing `gpsYear - 2000` double-subtracted and corrupted the RTC register. (2) `rtc.getYear() + 2000` → `rtc.getYear()` — `getYear()` adds 2000 internally, so the `+ 2000` in firmware double-added. Both the write and read paths now pass/receive the full 4-digit year. | Hardware observation + library source inspection |
| 29 | 2026-04-02 | Increased `buf` from `char buf[32]` to `char buf[40]` in the RTC debug print block. The format string `"RTC local time: %04d-%02d-%02d %02d:%02u:%02u"` with a 4-digit year produces up to 36 characters + null terminator = 37 bytes, overflowing the 32-byte buffer and truncating the output. | Hardware observation + code review |
| 30 | 2026-04-02 | Added `delay(250)` after `Wire.begin()` to allow all I²C devices to complete power-on startup before the first bus transaction. Added retry loop (5 attempts, 100 ms apart) around `rtc.begin()` to recover from transient bus-hang states left by prior sessions. | User observation + library source inspection |
| 31 | 2026-04-02 | Added `rtc.set24Hour()` immediately after `rtc.begin()` succeeds. RV8803 defaults to 12-hour mode on first power-up or after coin-cell loss; without this, `getHours()` returns a 12-hour value (1–12) in the GPS-disabled fallback path, causing a 12-hour error in the log filename and `TYPE_RTC_EVENT` timestamp. | Hardware observation + code review |

---

### Issue 28 — 🟠 High: RV8803 `setYear`/`getYear` misuse — year written and read with wrong offset

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino#L762) (write), [`VertiSea.ino`](VertiSea/VertiSea.ino#L803) (read) — `setup()`
**Status:** ✅ Resolved

**Description:**
The SparkFun RV8803 library handles the year-2000 offset **internally** in both
directions:

```cpp
// Library source (SparkFun_RV8803.cpp):
bool RV8803::setYear(uint16_t value) {
    _time[TIME_YEAR] = DECtoBCD(value - 2000);  // subtracts 2000 internally
    ...
}
uint16_t RV8803::getYear() {
    return BCDtoDEC(_time[TIME_YEAR]) + 2000;   // adds 2000 internally
}
```

The firmware had two symmetric bugs:

**Write path (GPS sync):**
```cpp
rtc.setYear(gpsYear - 2000);  // BUG: gpsYear=2026 → passes 26 → library stores 26-2000=-1974 (garbage BCD)
```
`setYear()` expects the full 4-digit year and subtracts 2000 itself. Passing
`gpsYear - 2000` (e.g. `26`) caused the library to compute `26 - 2000 = -1974`, which
wraps to a garbage BCD value. The RTC register ended up storing `74` (year 2074 when
read back), not `26` (year 2026).

**Read path (RTC fallback):**
```cpp
int rtcUtcYear = (int)rtc.getYear() + 2000;  // BUG: getYear() returns 2074 → 2074+2000=4074
```
`getYear()` already returns the full 4-digit year (adds 2000 internally). Adding
another 2000 produced `4074`.

**Why the RTC still showed 2074 after GPS re-sync:**
The GPS sync path wrote the corrupted value (`26` instead of `2026`) to the RTC. The
RTC stored `74` in its year register. `getYear()` then returned `74 + 2000 = 2074`.
Even after re-syncing with GPS, the write bug re-corrupted the register on every sync.

**Impact:**
- Debug console printed `RTC local time: 4074-04-01 ...` (or `2074-...` after partial fix).
- `TYPE_RTC_EVENT` binary packet stored `yearOffset = localYear - 2000 = 2074` instead
  of `26` — corrupted year in the binary log.
- SD filename was unaffected (uses month/day/hour/minute only).

**Resolution:**
Fixed both paths to pass/receive the full 4-digit year, letting the library handle the
offset:

```cpp
// Write (GPS sync):
rtc.setYear(gpsYear);         // pass full 4-digit year; library subtracts 2000 internally

// Read (RTC fallback):
int rtcUtcYear = (int)rtc.getYear();  // getYear() already returns full 4-digit year
```

---

### Issue 29 — 🟢 Low: `char buf[32]` too small for RTC debug string — buffer overflow truncates output

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino#L843) — `setup()`, RTC fallback path
**Status:** ✅ Resolved

**Description:**
The RTC debug print used a 32-byte buffer:

```cpp
char buf[32];
snprintf(buf, sizeof(buf),
        "RTC local time: %04d-%02d-%02d %02d:%02u:%02u",
        localYear, localMonth, localDay,
        localHour, localMin, localSec);
DBG_PRINTLN(buf);
```

The format string `"RTC local time: %04d-%02d-%02d %02d:%02u:%02u"` with a 4-digit
year produces a string of the form `"RTC local time: 2026-04-01 20:13:45"` — 36
characters plus a null terminator = **37 bytes**. This overflows the 32-byte buffer by
5 bytes. `snprintf` safely truncates at 31 characters + null, producing the observed
output `"RTC local time: 4074-04-01 20:1"` (cut off mid-minute field).

**Impact:**
Debug output only — no data corruption. The truncation was cosmetic but confusing.

**Resolution:**
Increased buffer to 40 bytes:

```cpp
char buf[40];
```

---

### Issue 30 — 🟠 High: RTC `begin()` intermittently fails — I²C power-on timing / bus-hang from prior session

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino#L563) — `setup()`, after `Wire.begin()`
**Status:** ✅ Resolved

**Description:**
`rtc.begin()` (RV8803 library) performs a single I²C address probe:

```cpp
bool RV8803::begin(TwoWire& wirePort) {
    _i2cPort->beginTransmission(RV8803_ADDR);  // 0x32
    if (_i2cPort->endTransmission() != 0)
        return false;  // no ACK
    return true;
}
```

This fails intermittently, causing the firmware to halt at `while (1)`. The failure
resolves after random actions (unplugging, re-uploading firmware, etc.).

**Root causes (two independent mechanisms):**

**1. Power-on timing — Artemis boots faster than RTC powers up:**
The RV8803 requires up to ~200 ms after VDD stable before it will respond to I²C.
`Wire.begin()` was called with no subsequent delay, so `rtc.begin()` could fire before
the RTC was ready — especially when powered from a supercap (fast ramp) or USB
hot-plug. Re-uploading firmware takes several seconds, giving the RTC time to power up,
which is why it "fixed itself" after a re-upload.

**2. I²C bus-hang from prior session (pre-GPS_ENABLE-fix):**
Before Issue 27 was fixed, `myGNSS.begin()` on an absent GPS module could leave SDA
low (I²C bus-hang). If the Artemis reset while the RTC and other devices remained
powered from the supercap, the bus stayed hung across the reset. The next `rtc.begin()`
then failed because the bus was stuck. Fully unplugging removed power from all devices,
releasing SDA — which is why "unplugging fixed it."

**Why it was intermittent:**
- Power-on timing: only fails when the Artemis boots faster than the RTC powers up
  (depends on supply ramp rate, which varies with supercap charge state).
- Bus-hang: only occurs when the GPS module was absent in the prior session (now
  eliminated by the GPS_ENABLE fix).

**Impact:**
Firmware halts at `while (1)` — no logging, no telemetry. Requires power cycle or
re-flash to recover. In a field deployment this would be a silent total failure.

**Resolution:**
Two changes in `setup()`:

1. Added `delay(250)` immediately after `Wire.begin()` to guarantee all I²C devices
   have completed their power-on startup before the first bus transaction:

```cpp
Wire.begin();
SPI.begin();
delay(250);  // allow I²C devices to complete power-on startup (RV8803 needs ~200 ms)
```

2. Replaced the single `rtc.begin()` call with a retry loop (5 attempts, 100 ms apart)
   to recover from transient bus states:

```cpp
bool rtcOk = false;
for (uint8_t attempt = 0; attempt < 5; attempt++) {
    if (rtc.begin()) { rtcOk = true; break; }
    delay(100);
}
if (!rtcOk) { while (1); }  // fatal only after all retries exhausted
```

The `delay(250)` addresses the power-on timing root cause. The retry loop provides
an additional safety net for any residual transient failures.

---

### Issue 31 — 🟠 High: RTC reads 12-hour time when GPS disabled — `set24Hour()` not called before RTC fallback read

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino#L603) — `setup()`, after `rtc.begin()`
**Status:** ✅ Resolved

**Description:**
The RV8803 RTC powers up in **12-hour mode** by default (or reverts to 12-hour mode
if the coin cell dies and the chip loses power). The GPS sync path correctly called
`rtc.set24Hour()` before writing the time, but this only affected the write operation.
The RTC fallback path (used when `GPS_ENABLE 0` or GPS sync times out) called
`rtc.updateTime()` and `rtc.getHours()` without first ensuring 24-hour mode was set.

In 12-hour mode, `getHours()` returns values 1–12 (with a separate AM/PM bit) instead
of 0–23. This caused a 12-hour error in:
- The debug console output (`RTC local time: ...`)
- The SD log filename (e.g. `04021408.BIN` instead of `04020208.BIN` for 2:08 AM)
- The `TYPE_RTC_EVENT` binary packet hour field

**Why GPS-enabled path was unaffected:**
The GPS sync path calls `rtc.set24Hour()` before writing the GPS time to the RTC. This
sets 24-hour mode in the RTC register, which persists as long as the RTC has power
(coin cell or main supply). On the next boot, if GPS is still enabled, the RTC is
already in 24-hour mode from the previous sync. But if GPS is disabled (`GPS_ENABLE 0`)
or the coin cell dies between sessions, the RTC reverts to 12-hour mode and the
fallback read path returns the wrong hour.

**Impact:**
- Log filename hour field off by 12 hours (e.g. `04021408.BIN` instead of `04020208.BIN`)
- `TYPE_RTC_EVENT` hour field off by 12 hours — absolute time anchor in binary log is wrong
- Timezone offset calculation may also be wrong (e.g. subtracting 7 from a 12-hour value)

**Resolution:**
Added `rtc.set24Hour()` unconditionally immediately after `rtc.begin()` succeeds, so
the RTC is always in 24-hour mode before any read or write operation:

```cpp
rtc.set24Hour();  // RV8803 defaults to 12-hour mode; force 24-hour for all read paths
```

This is placed after the retry loop in `setup()`, before any other RTC operations.
The GPS sync path retains its own `rtc.set24Hour()` call (before writing GPS time)
as a belt-and-suspenders measure, but the new unconditional call at init makes it
redundant.

---

### Issue 32 — 🟠 High: `relim()`/`autoscale_view()` overrides fixed y-axis limits on mechanical-input plot

**File:** [`vertisea_plot_v7.py`](../vertisea_plot_v7.py) — live packet handler
**Status:** ✅ Resolved

**Description:**
The mechanical-input dual-Y plot (`mech_ax` / `mech_ax2`) had fixed y-axis limits set
at initialisation (`set_ylim(-60, 60)` for tilt difference; `set_ylim(0, 500)` for RPM).
However, the live packet handlers for both `TYPE_TELEM_IMU` and `TYPE_RPM` called
`relim()` followed by `autoscale_view()` (with no `scaley` argument) after every packet.
`autoscale_view()` recomputes the y-axis range from the data, silently overriding the
fixed limits. Any spike in the data (e.g. a noise-induced RPM value) would rescale the
axis, making normal values appear compressed near zero.

**Impact:** Fixed y-axis limits were ineffective; RPM noise spikes caused the right
y-axis to rescale to thousands of RPM, making the plot unreadable.

**Resolution:**
Replaced `relim()` + `autoscale_view()` with `relim()` + `autoscale_view(scaley=False)`
on both axes. This allows the x-axis to scroll with incoming data while the y-axis
remains locked to the values set by `set_ylim()`.

---

### Issue 33 — 🟠 High: Hall-effect ISR fires on noise/bounce — spurious high RPM values

**File:** [`VertiSea.ino`](VertiSea/VertiSea.ino) — `hallISR()` / RPM measurement block
**Status:** ✅ Resolved

**Description:**
The Hall-effect sensor ISR (`hallISR`) triggers on every FALLING edge on `HALL_PIN`.
Magnet bounce, EMI, or cable noise can produce multiple rapid falling edges within a
single physical magnet pass. The RPM calculation `60.0e6 / periodUs` is extremely
sensitive to short periods: a spurious edge 1 ms after a real edge produces 60,000 RPM.
These values were transmitted in `TYPE_RPM` packets and plotted directly.

**Impact:** Occasional large RPM spikes (orders of magnitude above the true value)
appeared in the live plot and in logged data, corrupting RPM statistics.

**Resolution (current implementation):**
Added a minimum-period noise guard derived from `RPM_MAX_EXPECTED` and
`PULSES_PER_REV`. The original 450 RPM ceiling was subsequently proven invalid because
the VertiSea rotor reaches about 2000 RPM. `RPM_MAX_EXPECTED` is now 3000, yielding a
20,000 µs minimum period with one magnet; shorter intervals are rejected while genuine
high-speed pulses are retained. A monotonic pulse counter also prevents two ISR edges
between loop passes from silently producing half-speed RPM, and `TYPE_HALL_EDGE` preserves
raw edges for offline review.

The GUI still fixes its RPM axis at 0–450 RPM; that later contradiction is tracked by
Issue 38 rather than treated as part of the firmware noise-filter fix.


---

### Issue 34 — 🔴 Critical: IMU loop never achieves its nominal 104 Hz, and the filters assume it does

**Status:** ✅ Critical correctness defect resolved 2026-09-03. The firmware now uses
measured `dt` for Madgwick, vertical integration, and the leak time constant. The remaining
shortfall from nominal 104 Hz is a performance/jitter upgrade tracked by U19.

**Where:** `VertiSea.ino`, `collectIMUData_ISM()` and the IMU gate in `loop()`.

**Historical defect:** two coupled problems were originally present.

*1. The loop is slower than 104 Hz.* Measured from the logs:

| Log | I²C clock | Achieved | Mean interval | Stdev | Ticks ≥ 2× nominal |
|-----|-----------|----------|---------------|-------|---------------------|
| `04030825` | 100 kHz (default) | **57.17 Hz** | 17.493 ms | 17.705 ms | 20.17% |
| `09021931` | 100 kHz (default) | **88.94 Hz** | 11.243 ms | 3.834 ms | 1.56% |
| `09031050` | 400 kHz | **92.75 Hz** | 10.781 ms | 3.290 ms | 0.84% |

The original cause was `Wire.begin()` being called without `Wire.setClock()`, leaving the
bus at the 100 kHz default; two ISM330DHCX reads plus the MMC5983MA cost ~4200 μs per tick.
Madgwick + LPF together are only ~46 μs, so **compute was never the bottleneck** and
logging raw-only would not have raised the rate.

*2. The filters were hard-wired to the nominal rate.* `filterFixed.begin(IMU_RATE_HZ)` /
`filterStab.begin(IMU_RATE_HZ)` bake in dt = 1/104 = 9.615 ms, and the vertical integrator
uses the same constant:

```cpp
filterFixed.begin(IMU_RATE_HZ);            // asserts dt = 9.615 ms
vertVel  += vertAccel * (1.0f / IMU_RATE_HZ);   // same assumption
vertDisp += vertVel   * (1.0f / IMU_RATE_HZ);
```

Against the measured intervals above that is a **+12.1% dt error today and +81.9% in the
April log**. Madgwick's gain scales with dt, so the attitude estimate is mistuned, and the
double integration to `vertDisp` compounds the error — this sits directly on the
wave-height critical path, which is the whole point of the instrument.

**Impact on existing data:** treat `pitch`, `roll`, `heading` and `vertDisp` in
**`04030825` as unreliable**, not merely noisy. 56% of that log's elapsed time is inside
44–46 ms gaps — the filter was fed ~4.7× its assumed dt for the majority of the record.
The raw `gx/gy/gz`, `ax/ay/az` and mag columns are unaffected and remain trustworthy.

**Why the rate is still short of 104 Hz.** With 400 kHz the median interval is 9570 μs and
76.2% of ticks now fire on the first eligible loop pass — the sampler *can* hit 104 Hz.
The shortfall is a tail: 18.0% of intervals land in 11–15 ms, 5.0% in 15–20 ms, plus 28
samples at 30–70 ms. Removing just that excess yields **104.52 Hz**.

The tail correlates with SD writes, not with sensor I/O. `TYPE_CURRENT_BLOCK` appears in
23.6% of long intervals versus 2.4% of on-time ones (a 10× enrichment) because it is a
209-byte burst. But it only fires ~6.9×/s and there are 1193 long intervals, so it cannot
explain them all. The structural cause fits better: at ~108 bytes written per IMU tick,
a 512-byte SD block fills every `512/108 = 4.74` ticks — and the observed spacing between
long intervals is 5 records (538×), 4 records (412×), 3 records (219×). **The 512-byte
block flush is the dominant remaining cost.**

**Resolution and remaining work:**

1. ✅ **Use the measured dt** (implemented and hardware-confirmed). The code calls
   `filterX.begin(1.0f / dtActual)` before each `update*()` — `invSampleFreq` is private
   but `begin()` is public — and replace `1.0f / IMU_RATE_HZ` in the integrator with the
   measured `dtActual`. This is the fix that matters for data quality.
2. ✅ **Cut bytes per tick** (implemented and hardware-confirmed): `TYPE_CURRENT` (`0x0A`)
   was retired and `IMU_RAW_ONLY` / `TYPE_IMU_RAW` added. The final lossless layout uses
   int16 milli-g accel plus int32 mdps gyro and achieves about 97.5 Hz, a large improvement
   but still short of 104 Hz.
3. ⚠ **Residual performance work:** larger/predictable SD buffering is the leading option.
   Only if still short afterward, consider 1 MHz Fast-Mode-Plus (all bus devices are rated
   ≥400 kHz; the ISM330DHCX supports 1 MHz).

**Rejected:** interrupt-driven sampling. The loop is I/O-bound on blocking I²C reads and
SD writes, and an ISR cannot usefully perform I²C transactions or run Madgwick. It would
move the jitter, not remove it.


---

### Issue 35 — 🔴 Critical: `TYPE_IMU_RAW` gyro fields overflow `int16` (they are millidegrees/s, not counts)

**Status:** ✅ **FIXED AND VERIFIED ON HARDWARE 2026-09-03** by widening the gyro fields
to `int32` (payload 26 → 38 B, record 31 → 43 B). Confirmed by `09031435.BIN`: gyro now
reaches **573.4 dps**, 17.5× the old 32.767 dps ceiling, with no wrapping. Found while validating the first `IMU_RAW_ONLY 1` log
(`09031405.BIN`); accelerometer columns in that log are valid, gyro columns are not.

> **⚠ Correction to the recommendation below.** Option 2 (`int16` centi-dps) was
> **wrong** and was not used. It assumed a ±250 dps full scale, but the firmware configures
> **`ISM_500dps`** (lines ~1201 and ~1238), so centi-dps clips at 327.67 dps against a
> 500 dps sensor range — a smaller instance of the same bug. Option 3 (true LSB) has the
> same defect in a subtler form: the divisor depends on the FS setting, so raising FS to
> 1000 dps would silently reintroduce overflow.
>
> **Option 1 (`int32` mdps) was implemented**, because it is the only choice that is
> *independent of the full-scale setting*. It costs +12 B/tick, which is real, but it cannot
> break if someone changes the gyro range later. That property is worth more than 12 bytes.
>
> `09031405.BIN` was written with the old 31-byte record and **will no longer parse** — the
> parsers now expect 43 B and desync on it, reporting an unknown packet type rather than
> silently misreading. That is deliberate: the gyro data in it is corrupt anyway.

**Hardware verification (`09031435.BIN`, 63.79 s, 6222 records):**

| Axis | min (mdps) | max (mdps) | at hardware rail |
|------|-----------|-----------|------------------|
| `fix_gx` | −573370 | +519067 | 3 (0.05%) |
| `fix_gy` | −573370 | +573370 | 15 (0.24%) |
| `fix_gz` | −573370 | +486780 | 11 (0.18%) |
| `stab_gx` | −455070 | +410900 | 0 |
| `stab_gy` | −421155 | +556727 | 0 |
| `stab_gz` | −573370 | +462787 | 7 (0.11%) |

The fix is proven: values now span ±573 dps where `int16` capped at ±32.767 dps.

**A separate, pre-existing limit surfaced.** The maximum is *exactly* 573370 mdps on
multiple axes, which is the **ISM330DHCX's own register rail**: at `ISM_500dps` the
sensitivity is 17.5 mdps/LSB, so the sensor's internal `int16` saturates at
32767 × 17.5 = 573422 mdps. The 17/18 mdps quantisation steps observed between adjacent
distinct values confirm that sensitivity. So **0.10% of gyro samples are clipped by the
sensor's configured full scale**, not by our encoding — nothing in the logging path can
recover them. Raising to `ISM_1000dps` would fix it at the cost of halving resolution; the
`int32` field already has the headroom, which is a further argument against any FS-dependent
narrowing.

**Test context matters for interpreting that 0.10%.** The operator deliberately moved the
IMUs **fast and aggressively** during these bench runs, specifically to surface defects that
slow, gentle motion would mask. That was the right call — it is exactly why the `int16` gyro
overflow was caught immediately rather than after a deployment — but it means the 0.10%
figure is an **upper bound from deliberate worst-case excitation, not an expected duty
cycle**. Hand-shaking a sensor easily exceeds what a moored buoy experiences: 573 dps is
about 1.6 revolutions per second.

So **`ISM_500dps` is probably fine and was left unchanged.** The clipping is recorded here
because it is a real property of the configuration, not because it is known to be a problem.
What would settle it is a log from actual wave motion: if clipping stays at 0% there, the
question is closed; if it appears at all in water, revisit `ISM_1000dps`. **Do not use this
bench figure to justify changing the full scale.**

**Where:** `VertiSea.ino` — `IMUData.cnt_gx/cnt_gy/cnt_gz`, populated in
`collectIMUData_ISM()` and written by the `#if IMU_RAW_ONLY` branch as `TYPE_IMU_RAW` (0x12).

**What is wrong:** the fields are named `cnt_*` and documented as "raw ADC counts", but
`sfe_ism_data_t` does **not** contain raw LSB counts — the SparkFun library already scales
in `getGyro()`. The firmware's own conversion proves the units:

```cpp
float gx_dps_raw = (gyroData.xData - cal.gyro_bias[0]) * 0.001f;   // mdps -> dps
```

That `* 0.001f` means `xData` is in **millidegrees per second**. An `int16_t` therefore
saturates at 32767 mdps = **32.767 dps**, but the buoy routinely exceeds that: the
filtered run `09031403` recorded gyro excursions to **±243.6 dps**, which is 7.4× the
representable range.

**Evidence from `09031405`:**

| Axis | min | max | \|x\|>32000 |
|------|-----|-----|-----------|
| `fix_gx` | −32707 | +32725 | 0.8% |
| `fix_gy` | −32740 | +32759 | 0.5% |
| `fix_gz` | −32760 | +32690 | 0.4% |

Every axis presses against both rails, and p01/p99 sit near ±30000. The nominal
"0.4–0.8% clipped" understates the damage: values do not clamp, they **wrap sign**, so a
fast rotation can be recorded as a fast rotation in the opposite direction.

**Why the accelerometer is unaffected:** `accelData.xData` is in **milli-g** (the accel path
divides by ~1000 counts/g), so `int16` spans ±32.7 g — far beyond anything the buoy sees.
Observed range −659…1061 mg, and reconstructing ∣accel∣ from the raw columns with the logged
`calFixed` constants gives a **median of 0.9973 g**, confirming that path is correct.

**Impact:** `09031405.BIN` gyro data is unusable above 32.767 dps. Attitude cannot be
reliably recomputed offline from that log, which defeats the main purpose of
`IMU_RAW_ONLY`. The accel columns, `interval_us`, and the rate measurements from that run
are all still valid.

**Options:**

1. **Store `int32` for gyro** — record mdps without loss. Cost: +12 B/tick (31 → 43 B),
   which gives back roughly a third of the byte saving. Simple and lossless.
2. **Store gyro as `int16` in centi-dps** (`xData / 10`) — range ±327 dps, resolution
   0.01 dps. Keeps 31 B/tick. The ISM330DHCX at ±250 dps FS has ~8.75 mdps/LSB, so this
   discards about one bit of a resolution the sensor barely has; ±327 dps covers the
   configured full scale with margin. **Preferred.**
3. **Read the true hardware registers** instead of the library's scaled output, giving
   genuine LSB counts that fit `int16` by construction. Cleanest conceptually but means
   bypassing the SparkFun API and re-deriving the scale factors.

Whichever is chosen, the `cnt_*` field names and the "raw ADC counts" comments are
misleading and should say **milli-g / mdps**, and `binary_protocol.md` must be corrected —
it currently describes 0x12 as raw counts.

**Lesson for the changelog:** the synthetic round-trip test passed because it checked that
arbitrary `int16` values survive the encode/decode path. It could not catch this, because
the bug is that the *source values do not fit in `int16` in the first place*. Round-trip
tests validate transport, not range — physical-plausibility checks against real data are
what caught it.


---

### Issue 36 — 🟡 Medium: RFD900 radio transport not verified since the packet-set overhaul

**Status:** Open, raised 2026-09-03. **Not a known defect — an untested path.**

**What is verified:** the **USB telemetry transport works** (`USB_TELEM 1`, `TELEM_ENABLE 1`,
the committed configuration). Packets reach `vertisea_plot_v7.py` and its panels populate.

**What is not:** the **RFD900 radio path** (`USB_TELEM 0`) has not been exercised in some
time — across a period in which the telemetry packet set changed substantially: `0x0A`
retired, `0x0F` `TYPE_CURRENT_STATS` added (27 B), `TYPE_TELEM_IMU` unchanged but its rate
now differs by transport (10 Hz on USB vs 5 Hz on radio, selected by `#if USB_TELEM`).

**Why this is probably low risk.** Packet layouts are transport-independent — `TELEM_WRITE()`
writes the same bytes to whichever stream `TELEM_SERIAL` resolves to. So the decode side is
already proven by the USB testing. What is unproven is the **link**: 115200 baud framing,
byte loss over the air, and range.

**Why it is worth tracking anyway.** Two things differ on radio and are not covered by USB
testing:

1. **Byte loss is expected on radio and absent on USB.** The parser's frameless byte-scan
   design exists specifically for this, but it has not been re-verified against a lossy link
   since the packet set grew. A longer packet (`0x0F` at 27 B) has more exposure to a
   mid-packet dropout than the 5-byte packets that dominated before.
2. **Bandwidth.** At 5 Hz radio rate the per-second telemetry load is modest, but this has
   not been measured against the 115200-baud link with the current packet mix. Worth a
   sanity check rather than an assumption.

**How to verify:** flash `USB_TELEM 0`, run the GUI on the receiving RFD900, and confirm all
five radio packet types decode (`0x03`, `0x04`, `0x06`, `0x0B`, `0x0C`, `0x0F`) with the
`errors`/`notes` lists staying clean. Compare against a simultaneous SD log to check nothing
is silently dropped.

**Note on why this was recorded.** Several changelog entries had been annotated with the
claim that `TELEM_ENABLE` was 0 and no telemetry had ever been sent. That was **wrong** — an
agent misread the `#define` values. Correcting it revealed that USB *is* verified while radio
is not, which is a more useful distinction than the blanket "telemetry untested" it replaced.


---

### Issue 37 — 🟠 High: telemetry arrives at an irregular real-time rate (loop-pass jitter)

**Status:** Open, reported 2026-09-03. Root cause identified by inspection and supported by
measured loop timing; **not yet fixed**.

**Operator report:** *"when using USB telemetry there is now very noticeable lag that didn't
exist before... It doesn't seem like dropped packets but seems like the data isn't arriving at
a consistent real-time rate, while before we started making major changes... we were only
measuring the ADC (for supercap) at a much-much lower rate."*

> **An earlier version of this entry blamed the GUI's per-packet `canvas.draw()` calls and a
> doubling of `TELEMETRY_RATE_HZ` from 5 to 10 Hz. That was wrong** and is corrected below.
> The comparison is **USB-to-USB in both cases**, so `TELEMETRY_RATE_HZ` was **10 in both** —
> verified: the pre-work commit `2114478` also has `TELEMETRY_RATE_HZ = 10` under
> `#if USB_TELEM`. No rate change occurred, so no rate-based explanation can hold. The
> mistake was assuming the configuration changed when only the firmware internals did.

### The symptom is jitter, not throughput

The distinction the operator drew matters: **packets are not being lost, they are arriving
unevenly.** That rules out bandwidth and buffer-overflow explanations and points at *when* the
firmware decides to transmit.

### Root cause: the telemetry gate inherits `loop()` pass jitter

Telemetry is emitted from a polled gate inside `loop()` (`VertiSea.ino` ~L1834):

```cpp
if (imuReady && nowMs - lastRFDSend >= TELEMETRY_INTERVAL_MS) {
    lastRFDSend = nowMs;      // snap to now
    ...
}
```

This can only fire **when a `loop()` pass reaches it**. Telemetry timing is therefore exactly
as regular as the loop is — and the loop changed character completely.

**Before** (commit `2114478`): the only ADC work was a **5 Hz** supercap read (1 `analogRead`
per 200 ms). There was no high-rate block. Between IMU ticks the loop **spun freely**, so the
telemetry gate was evaluated *thousands* of times per second and fired within microseconds of
its deadline. Telemetry was effectively hardware-timer-regular.

**Now:** the high-rate current sampler sits **first** in `loop()` and requests **1000 Hz**
(`CURRENT_RATE_HZ`), achieving ~800 Hz. That is **~160× more ADC conversions per second**.
Every pass now carries an `analogRead` plus statistics accumulation, and every ~100th pass
also carries a 209-byte `TYPE_CURRENT_BLOCK` SD write. **The loop no longer spins freely** — it
is saturated, and its pass duration is highly variable.

We have measured that variability directly, via the `interval_us` field (Issue 34):

| Log | Config | Mean pass | ≥11 ms | Tail |
|-----|--------|-----------|--------|------|
| `09031403` | filtered IMU path | 10.795 ms | 23.7% | to 45 ms |
| `09031435` | raw IMU path | 10.234 ms | 12.3% | to 45 ms |

During a 30–45 ms SD block flush the telemetry gate **cannot be evaluated at all**. So a
100 ms nominal interval becomes 100–145 ms depending on where the flush lands — a **±45%
timing error**, which is exactly "not arriving at a consistent real-time rate".

### The error does not self-correct

`lastRFDSend = nowMs` **snaps the deadline to the actual send time** rather than advancing it
by whole intervals. So a late packet pushes the *next* deadline out from the already-late
time, and the delay is inherited rather than absorbed. Over a session the transmit phase
random-walks with respect to real time.

This is the same defect class that was already fixed for the **current sampler**, whose gate
deliberately advances by whole intervals — see the comment at `VertiSea.ino` ~L1608 and the
2026-09-02 changelog entry explaining why snapping to now measured *worse*. **The fix was
applied there but never to the telemetry gate.**

### Why SD write volume is NOT the explanation

Worth recording to prevent a wrong fix. Total SD bytes per second barely moved:

| | Old | New |
|---|-----|-----|
| Est. SD throughput | ~5765 B/s | ~6001 B/s (**1.04×**) |

The problem is not *how much* is written but *how the work is distributed*: the old loop had
long idle stretches in which any gate could fire promptly; the new loop is busy on nearly
every pass with occasional long blocking writes.

### Fix options

1. **Phase-advance the telemetry deadline** instead of snapping:
   `lastRFDSend += TELEMETRY_INTERVAL_MS;` (with catch-up clamping if it falls far behind).
   Removes the random walk so timing errors do not accumulate. **Smallest change, and it
   mirrors what the current sampler already does.** Does not remove per-packet jitter caused by
   a blocking SD write.
2. **Timestamp at sample time, not send time.** `ts10` is derived from `lastRFDSend`, i.e. when
   the packet was *transmitted*. If it instead carried the time the data was *captured*, the
   ground station could plot against true time and jitter would stop mattering for analysis —
   though the display would still update unevenly.
3. **Reduce the blocking-write stall.** Same root cause as Issue 34; anything that shortens the
   512-byte flush (fewer bytes/tick, buffered writes) reduces the worst-case gate delay.
4. **Lower `CURRENT_RATE_HZ`.** Would restore loop idle time, but the 1000 Hz over-request is
   deliberate and measured (U17: 377 Hz validated within 0.6% of scope ground truth; a 400 Hz
   request measured *worse*). **Do not undo it to fix a timing symptom** without re-measuring
   the current channel.
5. **GUI-side smoothing.** Plot against the packet's own timestamp rather than arrival time, so
   uneven arrival does not distort the trace. Complements option 2.

### Still worth checking on the GUI side

Separately from the firmware cause, `update()` calls `canvas.draw()` **inside** the
packet-drain loop (three redraws per `0x06`, one per `0x0C`, at lines 976/982/988/1085) while
rescheduling every 100 ms. This was **not** newly introduced — the pre-work commit had the
same pattern — so it does not explain a *change* in behaviour. But it does mean the GUI has
little headroom to absorb bursty arrival: if a burst of queued packets arrives after a
firmware stall, each one triggers a full redraw. **Contributory, not causal.** Consolidating
the redraws to once per `update()` pass is cheap and would make the GUI tolerant of the
irregular arrival the firmware now produces.

### How to confirm before fixing

1. **Log packet arrival times in the GUI** and histogram the inter-arrival intervals. The
   prediction is a cluster near 100 ms plus a tail to ~145 ms, matching the measured loop tail
   — *not* a uniform shift, which would indicate something else.
2. **Compare `ts10` deltas against arrival deltas.** If `ts10` deltas are also irregular, the
   firmware gate is confirmed as the source; if `ts10` is regular but arrival is not, the
   problem is in transport or the GUI.
3. **Temporarily set `CURRENT_RATE_HZ` to 5** and re-test. If the jitter disappears, the
   loop-saturation explanation is confirmed. Diagnostic only — do not keep this setting.

**Not a data-integrity bug.** The SD log is written independently with its own measured
timestamps and is unaffected. The risk is operational: a live display that lags and stutters
makes it hard to judge the buoy's current state, and `vertDisp`/attitude plotted against
arrival time will look distorted even though the underlying data is sound.


---

### Issue 38 — 🟡 Medium: BIN loader mishandles the normal `IMU_RAW_ONLY=1` workflow

**Status:** Open, found by the 2026-09-04 state audit.

**Where:** `vertisea_plot_v7.py`, `load_bin_file()` and the mechanical-input plot setup.

The committed firmware uses `IMU_RAW_ONLY 1`, so a normal new SD log contains
`TYPE_IMU_RAW` (`0x12`) and deliberately contains no `TYPE_FIXED_IMU`, `TYPE_STAB_IMU`, or
`TYPE_MAG`. The parser correctly reads and exports `_imuRaw.csv`, but the GUI load workflow
still assumes processed records:

- It displays a modal **“No Buoy IMU Data”** message whenever `stab_imu` is empty, even when
  `imu_raw` is present and the file parsed exactly as configured.
- The parse-complete summary omits `imu_raw`, `fixed_cal`, `stab_cal`, and `rtc_event`, so the
  primary high-rate record in current logs is invisible in the record-count summary.
- The existing attitude plots cannot be populated until U21 (optional offline orientation)
  is implemented; that is expected, but the message should explain the raw-only mode rather
  than implying a missing packet/problem.
- The RPM axis is fixed at 0–450 RPM even though firmware now accepts and has observed values
  above 450 RPM (`RPM_MAX_EXPECTED=3000`, target operation around 2000 RPM). Real values will
  be drawn off-scale.

**Impact:** Parsing and CSV output remain correct, but the operator receives a misleading
warning, an incomplete summary, and an RPM plot that cannot show the intended operating range.

**Suggested resolution:** Detect `imu_raw` explicitly, report “raw-only log; attitude was not
stored,” include all non-empty record types in the summary, and raise or dynamically configure
the RPM plot range. U21 remains the separate enhancement for actually reconstructing attitude.


---

### Issue 39 — 🟢 Low: `integ_s` comments and GUI “duty” no longer match measured-dt integration

**Status:** ⚠ Partially resolved 2026-09-04. Firmware comments now describe measured-dt coverage
correctly; the Python GUI still labels the ratio as “duty” and needs a separate confirmed GUI fix.

**Where:** `VertiSea.ino` `CurrentStatsPacket` comments and `vertisea_plot_v7.py` current-stats
panel.

An earlier implementation integrated with the requested interval, so `integ_s` could be much
shorter than wall time when the 1000 Hz request was not met. The current code instead adds the
**measured sample-to-sample `dt`** on every valid interval. In normal continuous sampling,
`integ_s` therefore tracks `window_s` closely regardless of whether the achieved rate is 400
or 800 Hz. The source comments still claim a measured ~377 Hz rate makes `integ_s` about 2.65×
shorter, and the GUI labels `100 * integ_s / window_s` as “duty.” That historical explanation
is no longer true.

**Impact:** The average/RMS calculations remain correct — dividing by `integ_s` is still the
right operation — but the displayed “duty” is now mainly a continuity/gap indicator, not the
achieved/requested sample-rate ratio. It will normally read near 100% even when `n_dropped` is
large by design.

**Suggested resolution:** Correct the comments and relabel the GUI field to “coverage” (or
remove it). Continue showing `n_samples/window_s` as the effective sample rate and keep
`n_dropped` explicitly described as request shortfall, not lost integration time.


---

### Issue 40 — 🟡 Medium: SD parser is not scalable to multi-hour high-rate logs

**Status:** Open, found by the 2026-09-04 state audit.

**Where:** `vertisea_plot_v7.py`, `parse_binary_file()` and `load_bin_file()`.

The file is read incrementally, but the parsed result is not streamed. Every packet becomes
a Python dict retained in a list, and every `TYPE_CURRENT_BLOCK` is expanded into one dict per
ADC sample before any CSV is written. At roughly 800 current samples/s, a multi-hour log can
create tens of millions of dictionaries — far more memory than the raw BIN file itself.
`load_bin_file()` also runs parsing and CSV writing synchronously on Tk's main thread, so the
GUI cannot repaint or respond while conversion runs.

**Impact:** Short bench logs work, but deployment-scale logs can make the GUI appear hung,
consume several GB of RAM, or fail before producing CSV output. This conflicts with U1's
original large-file requirement.

**Suggested resolution:** Add a streaming export path that writes rows as packets are parsed
instead of retaining all records, retaining only downsampled/selected data needed for plots.
Run conversion in a worker thread or process and report progress through the Tk event loop.
Keep the current in-memory API for short logs/tests if useful, but do not make it the only
conversion path.


---

### Issue 41 — 🔴 Critical: accel and gyro reach Madgwick in two different body frames

**Status:** Open, found by the 2026-09-11 code review. **Needs a hardware check before any fix.**

**Where:** `VertiSea/VertiSea.ino`, `collectIMUData_ISM()`.

```cpp
float ax_g_raw  = -(accelData.xData - cal.accel_bias[0]) / cal.accel_scale[0];   // X negated
float ay_g_raw  =  (accelData.yData - cal.accel_bias[1]) / cal.accel_scale[1];
float az_g_raw  =  (accelData.zData - cal.accel_bias[2]) / cal.accel_scale[2];

float gx_dps_raw =  (gyroData.xData - cal.gyro_bias[0]) * 0.001f;
float gy_dps_raw = -(gyroData.yData - cal.gyro_bias[1]) * 0.001f;               // Y negated
float gz_dps_raw =  (gyroData.zData - cal.gyro_bias[2]) * 0.001f;
```

Both comments say the negation exists "to match the buoy body-frame convention", but they
negate **different axes**. The accelerometer is presented as `(−X, +Y, +Z)` and the gyroscope
as `(+X, −Y, +Z)`. Two problems follow:

1. **The two frames differ.** `diag(−1,+1,+1)` and `diag(+1,−1,+1)` are related by
   `diag(−1,−1,+1)` — a 180° rotation about Z. Madgwick fuses both streams assuming they
   share one body frame, so the gyro integrates rotation in a frame whose pitch and roll are
   the *negatives* of what the accelerometer's gravity vector implies. The two inputs fight
   each other continuously.
2. **Each frame is left-handed.** Negating exactly one axis is a reflection, not a rotation.
   Madgwick's quaternion algebra assumes a right-handed frame. A legitimate axis remap needs
   an even number of sign flips (or a real rotation matrix).

`betaDef = 0.5f` in the vendored library is roughly 12× Madgwick's recommended AHRS gain, which
makes the filter behave almost like a smoothed accelerometer tilt sensor. That very likely
**masks** this defect on the bench: the accelerometer dominates, so pitch/roll look plausible
while the gyro contribution is largely overridden. Lowering `beta` for field use — already
flagged as a TODO in `setup()` — would let the gyro assert itself and could make attitude
*worse*, not better, until this is fixed.

**Impact:** Attitude output (`0x01`/`0x02` pitch/roll/heading, the `0x06` telemetry packet,
and everything downstream of it including `vertDisp`) is suspect. `IMU_RAW_ONLY 1` logs are
unaffected — they store the driver output before any of this — which is a good reason to keep
capturing raw logs until this is resolved.

**Suggested resolution:** Recover the intended sensor→body transform from the mechanical
drawing, express it as a single 3×3 rotation, and apply the *same* matrix to accel and gyro.
Validate by rotating the assembled sled through known ±90° attitudes about each axis and
checking that pitch/roll follow with the right sign and that the gyro integral agrees with
the accelerometer-derived tilt. Do not tune `beta` until this is settled.

---

### Issue 42 — 🟠 High: `gyro_bias[]` is in millidegrees/s but was documented as °/s

**Status:** Documentation corrected 2026-09-11. **The stabilized-IMU Y constant still needs re-deriving.**

**Where:** `VertiSea/VertiSea.ino` (`IMUCal`), `docs/calibration.md`, `docs/firmware.md`,
`docs/binary_protocol.md`, `README.md`.

`collectIMUData_ISM()` subtracts `gyro_bias[i]` from the SparkFun driver's value *before* the
`* 0.001f` mdps→dps conversion, so the constant is in **millidegrees per second**. Every
document described it as °/s. That made the committed value −438.56 read as −438.56 °/s, and
`docs/calibration.md` had grown a note asserting that a several-hundred-°/s zero-rate bias was
"normal for this sensor" — it would be a sensor pegged near its ±500 °/s full scale.

The error was not merely cosmetic. The calibration procedure told the operator the CSV columns
and the constant shared units and to "not multiply by 1000". The 2026-04-02 recalibration
followed it: a −0.065 °/s residual (= −65 mdps) was applied as −0.06, changing the constant
from −438.5 to −438.56 instead of to ≈ −503.5. **The stabilized IMU's Y-axis gyro bias is
therefore still uncorrected**, leaving roughly a −0.065 °/s residual rate that the Madgwick
filter has to fight.

**Impact:** A standing gyro bias on one axis biases attitude and, through it, `vertDisp`.
Small compared to Issue 41, but in the same signal path.

**Suggested resolution:** Re-derive both IMUs' gyro biases from a fresh stationary log. The
easiest route is an `IMU_RAW_ONLY 1` capture: the `_imuRaw.csv` `*_g*_mdps` columns are the
uncalibrated driver output in mdps, so their stationary mean *is* the new constant, with no
unit arithmetic at all. Then confirm the residual is < 50 mdps on every axis.

---

### Issue 43 — 🟠 High: ground station crashes at startup on a machine with no serial ports

**Status:** Open, found by the 2026-09-11 code review.

**Where:** `vertisea_plot_v7.py`, `VertiSeaGUI.__init__()`.

```python
ports = [p.device for p in serial.tools.list_ports.comports()]
self.com_menu = tk.OptionMenu(conn_frame, self.port_var, *ports)
```

`tk.OptionMenu.__init__(self, master, variable, value, *values)` takes `value` as a **required**
positional argument. With no ports enumerated, `*ports` expands to nothing and construction
raises `TypeError: OptionMenu.__init__() missing 1 required positional argument: 'value'`
before the window is ever shown.

**Impact:** The documented offline workflow — "run the ground station and click Load BIN File,
no serial connection needed" — is exactly the case where an analyst's laptop may enumerate no
COM ports. The program dies with a traceback and no usable error.

**Suggested resolution:** Pass a placeholder when the list is empty, e.g.
`tk.OptionMenu(conn_frame, self.port_var, *(ports or ["<no ports>"]))`, and have
`connect_serial()` reject the placeholder with a message box. `refresh_ports()` needs the same
guard so the menu can recover once a device is plugged in.


**Resolution (2026-09-11):** the dropdown is now built with
`*(ports or [self.NO_PORTS])`, `refresh_ports()` applies the same guard, and
`connect_serial()` rejects the placeholder with a message box that points the user at
**Load BIN File** for offline work.

---

### Issue 44 — 🟠 High: a serial error inside `update()` silently stops the entire GUI

**Status:** Open, found by the 2026-09-11 code review.

**Where:** `vertisea_plot_v7.py`, `VertiSeaGUI.update()`.

```python
if self.ser and self.ser.in_waiting:
    self.buffer.extend(self.ser.read(self.ser.in_waiting))
```

Neither call is guarded. Unplugging the RFD900x modem (or the buoy's USB cable), a driver
reset, or a USB power glitch raises `serial.SerialException` / `OSError` out of the `after()`
callback. Tk prints the traceback to stderr and simply does not reschedule the callback — so
`root.after(100, self.update)` at the bottom of the method is never reached and **every** panel
and plot freezes permanently. The window stays open and responsive-looking, which is the worst
possible failure mode: an operator watching a frozen plot has no way to tell it from a quiet
sea state.

**Impact:** Silent, unrecoverable loss of live monitoring during a deployment. Nothing on
screen indicates the link is gone.

**Suggested resolution:** Wrap the read in `try/except`, close and `None` the port on failure,
drive the SD/connection indicator to a visible "DISCONNECTED" state, and — critically — put the
`root.after(100, self.update)` reschedule in a `finally` block so the loop can never die.


**Resolution (2026-09-11):** `update()` is now a thin wrapper whose `finally` block always
issues `root.after(100, self.update)`, so the poll loop cannot die. The body moved to
`_update_once()`; `serial.SerialException` and `OSError` are caught and routed to
`_on_link_lost()`, which closes the port, drives the status indicator to "LINK LOST", and
shows the reason in a new connection-state label beside the Connect button.

---

### Issue 45 — 🟡 Medium: `n_dropped` is since-boot while `n_samples` is per-window

**Status:** Open, found by the 2026-09-11 code review.

**Where:** `VertiSea/VertiSea.ino`, `loop()` — the `CURRENT_STATS_WINDOW_MS` close block.

When a window closes, `statCharge_mC`, `statI2t_mA2s`, `statIntegSec`, `statPeakCounts` and
`statSamples` are all reset, but `currentDropped` is not — it is a since-boot counter. The
`CurrentStatsPacket` field is documented as "sample ticks missed vs the requested rate", and
the GUI shows it directly beside the per-window `n_samples`. The two quantities cover different
time spans, so the ratio a reader naturally forms from them is meaningless, and `n_dropped`
grows without bound over a long deployment.

**Impact:** Diagnostic only — the integrals use measured `dt` and are unaffected — but it
makes the one field intended to expose sampling health unusable for that purpose.

**Suggested resolution:** Either reset `currentDropped` with the rest of the window state and
document it as per-window, or keep it cumulative and rename the packet field (and its GUI
label) to say so. Prefer the former: it makes `n_dropped` comparable to `n_samples`.


**Resolution (2026-09-11):** `currentDropped` is reset alongside the rest of the window
state when the window closes, so `n_dropped` and `n_samples` now cover the same interval.
The packet field comment and the `CURRENT_RATE_HZ` note were updated to say
"this window". The GUI needed no change — it only displays the value.

---

### Issue 46 — 🟡 Medium: the magnetometer is a fatal boot dependency but is never read

**Status:** Open, found by the 2026-09-11 code review.

**Where:** `VertiSea/VertiSea.ino`, `setup()` and `loop()`.

`setup()` halts the board forever if `mag.begin()` fails:

```cpp
if (!mag.begin()) { DBG_PRINTLN("Magnetometer failed!"); while (1); }
```

But `loop()` calls `collectIMUData_ISM(..., /*isStabilizedIMU=*/false, ...)` for **both** IMUs,
so the `if (isStabilizedIMU)` branch that actually reads the MMC5983MA never executes. The
magnetometer is initialised, is allowed to brick the deployment, and contributes nothing.

A second consequence: with `IMU_RAW_ONLY 0`, the `TYPE_MAG` (`0x07`) record is still written
every tick from `lastStabIMU.mx/my/mz` — which are copies of an `LPFState` that nothing ever
updates. Those records are **constant zeros**, indistinguishable in the CSV from a real
magnetometer reading near the calibration centre.

**Impact:** An unnecessary single point of failure for the whole mission, plus a silently
fabricated data channel in any `IMU_RAW_ONLY 0` log.

**Suggested resolution:** Make the `mag.begin()` failure non-fatal (log it, set a status flag,
continue) since nothing depends on it; and skip writing `0x07` entirely while 9-DOF is
disabled, rather than writing zeros. If 9-DOF is re-enabled, restore both.


**Resolution (2026-09-11):** two parts.

1. `mag.begin()` no longer halts. Its result is stored in a new global `magPresent`, and a
   failure logs a warning and continues — nothing reads the device while both IMUs run
   6-DOF, so bricking the mission over it bought nothing.
2. The 9-DOF decision moved from a bare `false` literal at the call site to a single
   `#define STAB_IMU_USES_MAG 0`, and the `TYPE_MAG` write is now gated on
   `STAB_IMU_USES_MAG && magPresent`. A 6-DOF build no longer emits `0x07` at all, so a
   parser sees *absent* records instead of fabricated zeros. Re-enabling 9-DOF restores
   both the read and the record from one place.

---

### Issue 47 — 🟡 Medium: every sensor init failure halts the board with no watchdog

**Status:** Open for the four sensor faults. **Decided for SD on 2026-09-12: degrade, never
halt** — see Issue 67. Codes 5–7 are retired.

**Where:** `VertiSea/VertiSea.ino`, `setup()` — RTC, BME280, both IMUs, magnetometer, SD, and
the filename-exhaustion path all end in `while (1);`. `while (!imuStab.getDeviceReset());` and
its fixed-IMU twin are unbounded spins with no timeout either.

On a bench with `USB_DEBUG 1` this is reasonable: the message says which sensor failed. In a
deployed buoy with `USB_DEBUG 0` the failure is completely invisible — the LED is left solid
HIGH from the start of `setup()`, no telemetry is sent, no SD file is created, and the Apollo3
watchdog is not enabled, so nothing ever retries. A transient I²C glitch at power-on costs the
entire deployment.

**Impact:** Total, silent data loss from a recoverable fault. The existing RTC retry loop shows
the pattern is understood; it just is not applied elsewhere.

**Suggested resolution:** For each sensor, retry a bounded number of times, then degrade rather
than halt: record the failure in a boot-status packet, set a distinct LED blink code, and
continue with whatever sensors did initialise. Reserve a true halt for "no SD card", which is
the only failure that makes logging pointless — and even then, prefer enabling the Apollo3
watchdog so the board reboots and retries. Add timeouts to the `getDeviceReset()` spins.


**Partial resolution (2026-09-11):** the two unbounded `while (!imu.getDeviceReset());`
spins are now `waitForDeviceReset()`, which times out after 500 ms and warns. Every fatal
`while (1);` is now `haltWithBlinkCode(n)`, which blinks a per-fault pulse count forever
(1 RTC, 2 BME280, 3 stab IMU, 4 fixed IMU, 5 SD, 6 filenames exhausted, 7 file open) so a
field operator can read the fault off the board with no USB host.

**Still open:** whether these failures should halt at all. Continuing in a degraded mode —
logging what did initialise and recording the failure in a boot-status packet — is a
deployment-policy decision for the project owner, not something to change unilaterally.
Enabling the Apollo3 watchdog so a transient fault self-recovers is the other half.

---

### Issue 48 — 🟡 Medium: live parser redraws three canvases per packet

**Status:** Open, found by the 2026-09-11 code review.

**Where:** `vertisea_plot_v7.py`, `VertiSeaGUI.update()`.

The `while len(self.buffer) >= 1:` drain loop calls `imu_canvas.draw()`,
`stab_canvas.draw()` and `mech_canvas.draw()` **inside** the per-packet `0x06` branch. A
matplotlib `draw()` costs on the order of tens of milliseconds. At 10 Hz (`USB_TELEM 1`) that
is already ~30 full redraws per second; if the 100 ms poll ever finds several buffered packets,
the loop performs that work once per packet before returning to Tk. Redraw time then exceeds
the arrival interval, more packets queue up, and the backlog grows — the classic feedback loop
that turns a responsive GUI into a frozen one.

**Impact:** UI latency and stalls that worsen with link rate. Compounds Issue 44, because a
frozen GUI and a dead GUI look identical.

**Suggested resolution:** Drain the buffer and update only the deques inside the loop, then
issue at most one `draw_idle()` per canvas per `update()` tick, after the loop. `draw_idle()`
also lets Tk coalesce repaints.


**Resolution (2026-09-11):** the drain loop now collects touched canvases into a `dirty`
set and issues one `draw_idle()` per canvas after the buffer is empty, instead of up to
three blocking `draw()` calls per packet.

---

### Issue 49 — 🟢 Low: ts10 wrap handling is not shared with the RPM stream

**Status:** Open, found by the 2026-09-11 code review.

**Where:** `vertisea_plot_v7.py`, `VertiSeaGUI.update()`.

`self._ts10_last` is only updated in the `0x06` branch, but the `0x0C` branch reuses
`self._ts10_offset` to build its own time axis. `0x06` and `0x0C` are emitted from different
places in `loop()` and can straddle a wrap in either order, so around each 655 s boundary the
RPM series can be plotted a full 655.36 s away from the attitude series.

**Impact:** Cosmetic — an RPM trace that jumps off the visible x-range roughly every 11 minutes.

**Suggested resolution:** Factor the wrap tracking into one small helper
(`self._monotonic_seconds(ts10)`) and call it from every branch that carries a `ts10`, so all
streams share one wrap counter.


**Resolution (2026-09-11):** wrap tracking moved into `_monotonic_seconds(ts10)`, which
both the `0x06` and `0x0C` branches call, so every ts10-bearing stream shares one wrap
counter.

---

### Issue 50 — 🟢 Low: `connect_serial()` leaks the previously opened port

**Status:** Open, found by the 2026-09-11 code review.

**Where:** `vertisea_plot_v7.py`, `VertiSeaGUI.connect_serial()`.

The method assigns a new `serial.Serial` to `self.ser` without closing the old one. Clicking
**Connect** a second time leaves the first handle open and owned by a dropped object; on
Windows the port stays locked until the process exits, so reconnecting to the same port fails
with "access denied" and the user has to restart the program.

**Suggested resolution:** `if self.ser and self.ser.is_open: self.ser.close()` before opening,
inside its own `try/except`.


**Resolution (2026-09-11):** `connect_serial()` calls a new `_close_serial()` helper first,
which closes and clears any existing handle inside its own `try/except`.

---

### Issue 51 — 🟢 Low: BIN-load summary omits the packet types the default build produces

**Status:** Open, found by the 2026-09-11 code review. Related to Issue 38.

**Where:** `vertisea_plot_v7.py`, `load_bin_file()`.

The summary dialog iterates a hard-coded key list that includes `fixed_imu` and `stab_imu` but
**not** `imu_raw`, `rtc_event`, `fixed_cal` or `stab_cal`. The committed firmware is
`IMU_RAW_ONLY 1`, so a log from it reports no IMU records at all in the dialog even though
`_imuRaw.csv` was written correctly. The dialog also fires a "No Buoy IMU Data" warning for
the same reason.

**Impact:** The parse summary actively misleads about the most common log type.

**Suggested resolution:** Derive the summary from `data` itself — iterate the keys that have
records, in `_schemas` order — instead of a parallel hard-coded list that has to be kept in
sync by hand. That also fixes step 5 of the README's "adding a new packet type" checklist
permanently.


**Resolution (2026-09-11):** `_CSV_SCHEMAS` moved to module scope in the new
`vertisea_protocol.py` and the summary iterates it directly, so a newly added packet type
appears in the dialog automatically. The "No Buoy IMU Data" warning popup became a note in
the summary that explains the `IMU_RAW_ONLY=1` case and points at the CSVs needed to
recompute attitude offline (also addresses part of Issue 38).

---

### Issue 52 — 🔴 Critical: clamped baseline subtraction fabricates charge on idle records

**Status:** ✅ Resolved 2026-09-11.

**Where:** `current_filter_test.py`, `subtract_baseline()`.

```python
return [x - baseline if x > baseline else 0.0 for x in v]
```

On an idle stretch the signal sits *at* the baseline, so after subtraction it is symmetric
noise about zero. Clamping discards the negative half. For zero-mean Gaussian noise of
width σ the surviving mean is `E[max(X,0)] = σ/√(2π) ≈ 0.399σ` — with the measured idle
floor (σ = 9.14 counts) that is **+3.65 counts of current that does not exist**, present for
every idle second and integrated straight into reported charge.

| Idle duration | Fabricated charge |
|---------------|-------------------|
| 1 hour | 161 mC |
| 1 day | 3 854 mC |
| 2 days | 7 708 mC |

The largest *real* event in `docs/current_measurement_testing.md` is 667.5 mC. On the 1–2
day deployment this system is for, the clamp alone invents about eleven events' worth of
charge — and the error scales with idle time, so it is worst exactly when harvesting is
sparse, which is the case the measurement exists to quantify.

It survived review because on the 58.6 s bench capture it was worth ~0.75 mC, under the
noise. It also directly contradicted the module's own stated design rule: "A filter that
removes noise WITHOUT shifting the mean... a filter that moves the level is unusable for a
quantity we integrate into charge."

**Resolution:** clamping is off by default; `subtract_baseline(..., clamp=True)` and
`--clamp-baseline` reproduce the old numbers for comparison. Idle stretches now integrate to
zero plus a random walk growing as √t rather than t. A 200 000-sample Monte Carlo in the
selftest pins the bias at σ/√(2π) so it cannot silently return.

---

### Issue 53 — 🔴 Critical: `sdError` was a one-way latch

**Status:** ✅ Resolved 2026-09-11.

**Where:** `VertiSea/VertiSea.ino`, `setSdError()` and every `if (!sdError)` guard.

The first SD write failure of a deployment stopped logging permanently; only a power cycle
cleared it. That is acceptable for a ten-minute bench run and unacceptable for the 1–2 day
field logging this system exists for. A single transient — an EMI glitch on the SPI lines
during a TENG discharge, a card pausing for internal garbage collection past the library's
patience, a momentary brown-out — ended the entire run, and the only outward sign was the
heartbeat LED changing from 1 Hz to 4 Hz.

Issue 54 supplies a concrete mechanism that reached this latch by a route nobody intended:
EMI on the Hall line → interrupt storm → 48 kB/s of `TYPE_HALL_EDGE` records into a pipeline
sized for ~6 kB/s → queue overrun → `sdError` → logging dead for the deployment.

**Resolution:** a recoverable state machine. On failure, back off `SD_RECOVERY_INTERVAL_MS`
(5 s), then close the handle, re-run `SD.begin()`, and open a **new** file, re-emitting the
RTC anchor and every calibration record via the new `sdWriteBootRecords()`. A new file is
deliberate: after a card fault the old handle's cached cluster chain is untrustworthy, and
data already written stays intact on disk. The RAM queue is discarded because its bytes are
mid-stream fragments of the failed file. Capped at `SD_MAX_RECOVERY_ATTEMPTS` (20) so a
genuinely dead card does not spend the run re-running `SD.begin()` in the sampling path.
`sd_write_failures` and `sd_recoveries` are reported in the new `TYPE_SYS_HEALTH` record.

---

### Issue 54 — 🟠 High: Hall ISR accepted every edge, so EMI became an interrupt storm

**Status:** ✅ Resolved 2026-09-11.

**Where:** `VertiSea/VertiSea.ino`, `hallISR()`.

`RPM_MIN_PERIOD_US` was applied in `loop()` — *after* the ISR had already taken the
interrupt and buffered the timestamp. The TENG discharge is a high-voltage event beside an
unshielded open-collector sense line, so a burst of induced edges cost three times over:

1. Every edge takes an interrupt. A sustained burst starves `loop()`, which is directly
   visible as the heartbeat LED freezing mid-state — the reported symptom.
2. Every loop pass then emitted a `TYPE_HALL_EDGE` record of up to 31 timestamps (129 B).
   At a ~370 Hz loop that is ~48 kB/s of pure noise into an SD pipeline sized for ~6 kB/s,
   which overran the queue and tripped Issue 53.
3. The RPM reading itself was destroyed, because `loop()` discards any interval spanning
   more than one edge.

**Resolution:** the same `RPM_MIN_PERIOD_US` threshold is applied inside the ISR, which
costs one comparison and breaks all three paths. Nothing physically plausible is lost — the
threshold is 3000 RPM against a rotor that reaches ~2000. Rejected edges are counted in
`hallEdgeRejected` and reported in `TYPE_SYS_HEALTH`, so interference becomes visible
instead of merely destructive; the parser flags a non-zero count as an interference warning.

---

### Issue 55 — 🟠 High: LED heartbeat read back an OUTPUT pad

**Status:** ✅ Resolved 2026-09-11.

**Where:** `VertiSea/VertiSea.ino`, the heartbeat block at the end of `loop()`.

```cpp
digitalWrite(LED_PIN, !digitalRead(LED_PIN));
```

This assumes the pad reads back its driven level. On Apollo3 a pad configured for OUTPUT may
have its input buffer disabled, in which case `digitalRead()` returns 0 regardless of what
is being driven — and `!0` is always HIGH, so the LED latches on and stops blinking **while
the firmware runs perfectly normally**.

That is the "stays fully on, never blinks" half of the reported symptom. It cannot explain
the "stops mid-blink" half, which is a genuine `loop()` stall (Issues 53, 54, 57 and the
`TYPE_SYS_HEALTH` record added to measure it). Both variants were reported, which is
consistent with two distinct causes.

**Resolution:** state tracked in a `ledState` variable.

---

### Issue 56 — 🟠 High: median-5 cannot reproduce a scope's High-Resolution mode

**Status:** ✅ Resolved 2026-09-11.

**Where:** `current_filter_test.py`, `median_filter()` as the main denoising stage.

The goal of the post-processing is for the result to resemble a Keysight scope in
**High-Resolution** acquisition mode. HiRes averages N consecutive samples taken at the full
rate: a boxcar FIR, linear, mean-preserving, with a stated transfer function, buying one
effective bit per 4× increase in N. A median filter cannot produce that:

1. **Less efficient.** The sample median of *w* Gaussian values has ~π/2 more variance than
   the mean. Measured against this project's own 9.14-count idle floor: median-5 gives
   1.87×, boxcar-5 gives 2.25× (ideal 2.24×); at w=33, 4.71× vs 5.81×. About a third of an
   effective bit given away at every width.
2. **Nonlinear, so it has no bandwidth.** No transfer function to quote, so no way to match
   it to a scope setting. "Similar to HiRes" is unachievable by construction.
3. **It moves the mean.** `docs/current_measurement_testing.md` recorded median-5 changing
   total charge by +2.79% and did not act on it. A boxcar changes charge by 0.000%.

The median was chosen for a sound reason — 223 measured dropouts, which a boxcar genuinely
cannot reject. The error was using one filter for two jobs.

**Resolution:** the stages are separated. `hampel_filter()` (local median ± n·MAD, with a
scale floor derived from the quietest second of the record) removes *only* outliers, then
`boxcar_filter()` does the HiRes averaging. `boxcar_bandwidth_hz()` reports the −3 dB point,
first null and bit gain so a window can be chosen from a bandwidth target and matched to a
scope. Default `--window 17` = 20.8 Hz, +2.0 bits at the achieved ~800 Hz.

---

### Issue 57 — 🟠 High: no watchdog, so an I²C stall is unrecoverable

**Status:** ⚠ Open. Related to Issue 47 (which covers the boot-time halts).

**Where:** `VertiSea/VertiSea.ino` — the Apollo3 watchdog is never initialised.

Issues 53–55 removed the firmware-side causes of a frozen `loop()`, but one class remains
and it is the one the firmware cannot fix from inside: an I²C transaction that never
returns. `imu.checkStatus()`, `getAccel()`, `getGyro()`, `bme.read*()` and the RTC calls all
block in `Wire` with no timeout, and a slave that latches SDA low after an EMI event — the
TENG discharge is exactly such an event — hangs the bus and the firmware with it. Nothing
recovers, and a multi-day deployment ends at the first occurrence.

The new `TYPE_SYS_HEALTH` record makes this diagnosable after the fact: an I²C stall shows
as `loop_max_us` spiking with every other counter flat, which is why the parser names it
explicitly when nothing else accounts for a long pass.

**Suggested resolution:** enable the Apollo3 WDT with a timeout of a few seconds and pet it
at the end of `loop()`. A hang then becomes a reboot, and the firmware already opens a fresh
log file on boot, so the cost is seconds rather than the run. Add I²C bus recovery (nine SCL
pulses to free a stuck slave) before re-initialising after such a reset.

**Why it is not in the 2026-09-11 change:** the AmbiqSuite WDT API could not be
compile-checked in the review environment, and shipping an unverified *reset* path into a
deployment is worse than the problem it solves. It needs a compile against the installed
core plus a bench soak confirming it does not fire spuriously.

---

### Issue 58 — 🔴 Critical: the vendored Madgwick library was never actually compiled

**Status:** ✅ Resolved 2026-09-11.

**Where:** `VertiSea/VertiSea.ino` line 152, and the former `Madgwick/` directory.

The layout was:

```
TENG_SLT/                    <- repository root
├── VertiSea/
│   └── VertiSea.ino         <- #include "MadgwickAHRS.h"
└── Madgwick/                <- sibling of the sketch folder
    └── src/MadgwickAHRS.h
```

A quoted `#include` searches the including file's own directory first, then the compiler's
`-I` paths. `VertiSea/` does not contain the header, and arduino-builder's `-I` paths cover
the sketch folder, the core, the variant, and **libraries found in the sketchbook
`libraries/` directory** — not sibling directories of the sketch. So `Madgwick/` was
invisible to the build.

Two consequences, and the second is the damaging one:

1. On a machine with no Madgwick library installed, the sketch does not compile at all
   (`MadgwickAHRS.h: No such file or directory`).
2. On the machine where it *does* compile, a **Library Manager copy is being used instead**
   — which is precisely what `README.md` and `AGENTS.md` told the developer not to install,
   while also asserting the vendored copy "takes precedence over any global Arduino
   install". That assertion was false, and stated confidently enough that nobody checked.

The in-tree copy is a **local fork**, so this is not a harmless substitution:

| Constant | Upstream 1.2.0 | In-tree | Effect if the global copy is compiled instead |
|----------|---------------|---------|-----------------------------------------------|
| `sampleFreqDef` | 512.0f | 104.0f | harmless — a seed value, overwritten from measured `dt` on the first tick |
| `betaDef` | 0.1f | **0.5f** | **5× lower filter gain than every comment in the firmware assumes** |

`setup()` carries a TODO reading "Current value: betaDef = 0.5f (Madgwick/src/
MadgwickAHRS.cpp, line 30)" and proposes reducing it toward 0.05–0.1 for field use. If the
global copy was compiled, beta was **already 0.1** and that TODO described a change that had
effectively been made by accident.

This also weakens the reasoning in **Issue 41**, which argued that beta = 0.5 probably masks
the accel/gyro body-frame mismatch by letting the accelerometer dominate. At beta = 0.1 the
gyro contributes considerably more, so the mismatch would show up in attitude more strongly
than that analysis assumed. **Establish which library actually compiled before interpreting
any existing attitude data.**

**Resolution:** `MadgwickAHRS.h` and `MadgwickAHRS.cpp` moved into `VertiSea/`, beside the
`.ino`. That placement is load-bearing in three ways:

* the quoted `#include` can now only resolve to the copy beside it — precedence is a
  property of the C preprocessor, not of documentation;
* because the header is no longer missing, arduino-builder never searches libraries for it,
  so a globally installed copy cannot be dragged in to produce duplicate symbols either;
* Arduino compiles every `.cpp` in the sketch folder automatically.

The `#include` line itself is unchanged. The upstream packaging metadata
(`library.properties`, `keywords.txt`, `README.adoc`, `examples/`, `extras/`) moved to
`archived/Madgwick-upstream/` as provenance — it is meaningless once the sources live in the
sketch folder, and leaving a second copy of the sources anywhere is the duplication problem
that retired the MATLAB parser.

**Action required on the developer's machine:** delete any `Madgwick` / `MadgwickAHRS`
library from the sketchbook `libraries/` folder. It is now genuinely unnecessary, and
removing it is the only way to be certain which code is running.

---

### Issue 59 — 🔴 Critical: `micros()` in the Hall ISR panics the kernel on Apollo3 core 2.x

**Status:** ⚠ Open. **The firmware must be built on Apollo3 core 1.2.1.** Confirmed on
hardware 2026-09-11.

**Where:** `VertiSea/VertiSea.ino`, `hallISR()` — and, more precisely, the choice of
board-support core.

```
++ MbedOS Error Info ++
Error Status: 0x80010133 Code: 307 Module: 1
Error Message: Mutex: 0x100033BC, Not allowed in ISR context
Current Thread: main ... tgt=SFE_ARTEMIS_NANO
```

Apollo3 core **1.x** is a bare Arduino core: `micros()` is a timer read and is safe from an
interrupt. Core **2.x** is built on mbed OS, where `micros()` goes through an RTOS
primitive that takes a mutex — and taking a mutex in ISR context is an immediate kernel
panic, not a degraded reading.

`hallISR()` calls `micros()` as its first statement. On core 2.x the board therefore dies
on the **first Hall edge after `attachInterrupt()`**, roughly one second into `loop()`.

**Observed consequences, all from this single cause:**

| Symptom | Mechanism |
|---------|-----------|
| **Log filenames lose their zero padding** — `9111614.BIN` instead of `09111614.BIN`, `LOG4.BIN` instead of `LOG00004.BIN`, `2026-9-11` instead of `2026-09-11` | core 2.x links a reduced `printf` that ignores width and zero-pad flags, so every `snprintf("%02d")` / `%05lu` in the filename and timestamp paths silently degrades. This breaks the documented `MMDDHHMM.BIN` 8.3 convention and any script that sorts or parses on it |
| `.BIN` files contain exactly 196 bytes | the boot records were flushed in `setup()`; the panic arrives before the first 5 s `sdFlushBuffered()`, so the 118 B then sitting in the queue never reach the card |
| No telemetry at all, on USB or radio | the board is dead ~1 s into `loop()` |
| Heartbeat LED "blinking at about 1 Hz" | **not** the firmware heartbeat — it is the MbedOS error handler's own blink. This is why the LED looked healthy while nothing worked |
| Binary bytes interleaved into `USB_DEBUG` text | on core 2.x the `Serial` / `Serial1` mapping differs from 1.x, so `Serial1` telemetry surfaces on the USB port |

**This is almost certainly the original field fault.** The reported symptom was "the
heartbeat LED stops blinking or sticks on, and it seems to depend on the measurement
signal." Issue 54 attributed that to harvester EMI on the unshielded Hall line causing an
interrupt storm that starved `loop()`. The EMI mechanism was right; the consequence was
badly understated. On core 2.x a *single* induced edge is fatal, and what the operator
then sees is the mbed error handler's LED pattern replacing the heartbeat — which matches
"stops blinking / changes to something else" far better than loop starvation does.

The ISR-level rejection added for Issue 54 does **not** help here: `micros()` is called
before the threshold test, so the panic happens first. That fix remains correct for its own
purpose (EMI no longer floods the SD pipeline) but it cannot survive a core it was never
written for.

**Resolution: build on Apollo3 core 1.2.1.** Remove any manual 2.x checkout from the
sketchbook `hardware/` folder and install 1.2.1 through the Boards Manager. Core 1.2.1 is
the platform every measurement, timing figure and dead end in `docs/` was recorded against;
2.x differs in `Serial` mapping, `analogRead`, `attachInterrupt` and the RTOS, so its
timing numbers would not be comparable even if it ran.

**If core 2.x ever becomes a requirement**, the ISR must stop calling `micros()`. Options,
in order of preference:

1. Read the Apollo3 STIMER directly (`am_hal_stimer_counter_get()`), which is a register
   read and ISR-safe on both cores. Needs verification against each core's HAL headers.
2. Have the ISR only increment `hallPulseCount` and let `loop()` timestamp. Costs up to one
   loop period (~3 ms) of jitter against a ~30 ms edge period — roughly 10% RPM error — and
   destroys the point of the raw `TYPE_HALL_EDGE` record, so this is a fallback only.
3. `RPM_ENABLE 0`, which compiles the ISR out entirely. This is the correct immediate
   workaround for confirming the diagnosis and for any run that does not need RPM.

**Prevention:** `README.md` §4 stated core 1.2.1 but nothing enforced or checked it, and a
2.x build compiles cleanly — the divergence only appears at run time. A compile-time guard
on `ARDUINO_ARCH_MBED` would have turned a day of hardware debugging into a build error.
That guard is now in place and was confirmed firing on 2026-09-11.

**Confirmed fixed on core 1.2.1 (2026-09-11).** The same board, same wiring, same sketch:
filenames regained their zero padding (`09111631.BIN`, `LOG00005.BIN`), the binary telemetry
stopped leaking into the `USB_DEBUG` text — so `Serial`/`Serial1` are genuinely separate
again — and logging ran with `overruns=0`, a queue high-water of 1005 B against the 4096 B
capacity, and a loop dominated by the SD write rather than by anything unexplained:

```
SDq=533B high=1004 loopUs=23318 maxWriteUs=21520 overruns=0
SDq=772B high=1005 loopUs=49774 maxWriteUs=47971 overruns=0
```

`loopUs ≈ maxWriteUs + 1.8 ms` in nearly every record, which says the longest pass is the
SD write plus ~1.8 ms of actual work — the expected shape, and the direct cause of the
Issue 34 rate shortfall. Note the write itself takes **11–48 ms per 512-byte sector**,
against a more typical 1–5 ms: the card keeps up with the ~6 kB/s inflow but with little
margin, and a faster card is the cheapest available improvement to the achieved IMU rate.

---

### Issue 60 — 🔴 Critical: sustained ADC saturation was silently rewritten as if it were glitch noise

**Found:** 2026-09-11, on the field capture `09111632_currentFast.csv`.

`reject_full_scale()` replaced **every** sample at or above `adc_max` with a 3-point median
of its neighbours. That is the right treatment for one class of event and exactly the wrong
treatment for the other, and the two look identical to a threshold test:

* **An isolated rail sample** with neighbours far below cannot be real — current cannot rise
  80% of range and return inside one ~1.2 ms sample interval. It is an impulsive glitch and
  repairing it is correct.
* **A run of consecutive rail samples** is the ADC honestly reporting that the input went
  past its 2.0 V reference and it has no range left. The true value is unknown and is
  ≥ full scale.

Rewriting the second case invents data, and the invented value is not random — the samples
bracketing a saturated run are themselves on the way up or down, so the replacement is
systematically **low**. That biased value then went into `boxcar_filter()`, which is
mean-preserving by construction and therefore faithfully propagated the bias across the
whole window. The visible result on `09111632` was the filtered line sitting in the middle
of the raw band instead of tracking it, and the reflex reading of that plot — "the filter
isn't working, widen the window" — makes it worse, because a wider window spreads the
fabricated deficit further.

Worse than the number being wrong is that nothing said so. A clipped capture came out of
the tool looking like a well-behaved measurement.

**Fix.** `reject_full_scale()` now walks runs rather than samples. Runs up to
`MAX_GLITCH_RUN` (2) are repaired from the samples bracketing the *whole* run — the old
per-sample 3-point median could not repair even a run of 2, since its neighbour was another
rail sample. Longer runs are left at full scale and counted, and the count is surfaced by a
new `RANGE / SATURATION` report section printed *before* the filter tables, which states
plainly that peak, charge and I²t are lower bounds and that this is a hardware range fault:
add a divider ahead of A14 (and update `TYPE_CURRENT_CAL` so the scale follows), or remove
the idle offset. No filter setting can recover a voltage the ADC never saw.

Return type changed from `(filtered, n_replaced)` to `(filtered, n_replaced, sat)`.

---

### Issue 61 — 🟠 High: a ~26 mA idle offset eats 13% of the ADC range

**Found:** 2026-09-11, same capture.

`09111632` idles at **2159 counts ≈ 26.4 mA**, where the 2026-09-03 capture idled at
approximately zero. Full scale is 200 mA, so peaks now clip at **174 mA of real current**,
not 200 — the clipping in Issue 60 arrives 13% earlier than the nominal range suggests.

Software subtraction restores the *numbers* but cannot restore the *range*: the headroom was
already lost at the ADC, before any sample was stored. The second consequence is cosmetic
but was misread as a bug — after subtraction the trace goes **negative** wherever the input
dips below idle. On this capture it reaches −25 mA at the discharge edges. That is real
signal, not a filter artefact, and clamping it away is precisely the charge-fabricating bug
removed in Issue 52.

The report now prints the offset as a percentage of range and warns above
`OFFSET_WARN_FRAC` (5%). The offset itself still needs finding on the bench — it is either
the sense amplifier's own output offset or a bias that appeared with the current wiring.
Not fixable in post-processing.

---

### Issue 62 — 🟠 High: the HiRes stage averaged but never decimated, so a correct result looked like noise

**Found:** 2026-09-11, from the user report "제대로 필터링도 안되고 있는 것 같아".

The 2026-09-11 rewrite described High-Resolution mode correctly — *"average N consecutive
samples taken at the full rate, **emit one point**"* — and then implemented only the first
half. `boxcar_filter()` is a **sliding** boxcar: correct frequency response, but it returns
one output sample per input sample. The decimation was never done.

That is not a cosmetic difference when the result is plotted. A 40 s capture at 800 Hz is
32,000 points drawn across roughly 1,300 pixels: **24 samples share every pixel column**, and
matplotlib paints the full vertical extent of all 24. Whatever ripple survives the filter is
rendered as a solid filled band, so:

* a correctly filtered trace is indistinguishable from an unfiltered one;
* widening the window appears to do nothing, because the band's *extent* shrinks far more
  slowly than its *density* — and density is invisible at 24× overdraw;
* the natural next step is to widen the window further, which throws away real bandwidth to
  fix a drawing problem.

A scope in HiRes emits one point per averaged block, so the ripple inside a block is
genuinely absent from the output rather than hidden under overdraw. That is why the scope
trace looks clean and this one did not, at the same bandwidth, on the same signal.

**Fix.** New `decimate_blocks()` returns block centre time, block mean (the HiRes sample)
and block min/max. The plot now draws the decimated mean as a line with the min/max as a
translucent band behind it, so the averaged-away ripple stays visible instead of being
quietly discarded — on a clean capture the band collapses onto the line; on a saturated or
aliased one it stays wide, which is information. `--no-decimate` restores the per-sample
line. Verified on a synthetic reproduction of `09111632` (26 mA offset, 3.05% saturation,
137/311 Hz content): identical filter, identical bandwidth, the only change is decimation —
970 points instead of 32,000.

The CSV still carries one row per input sample; decimation is applied to the plot only, so
`--write-csv` output and `integrate_charge()` are unchanged.

Also added `window_for_bandwidth()` and `--bandwidth HZ`, so the window can be specified the
way a scope states it rather than as a sample count that means nothing without also knowing
the achieved rate.

---

### Issue 63 — 🟠 High: the telemetry GUI can reset the buoy, and says nothing about it

**Found:** 2026-09-11 — "이거 실행했는데 … 갑자기 LED 깜박이지 않고 멈춰있어", with the GUI
connected to COM7 and every field reading N/A.

`connect_serial()` already knew the mechanism and documented it: on the RedBoard Artemis
Nano the CH340E **RTS** line is wired to the Artemis reset pin (it is how the SVL bootloader
is triggered), so opening the port can reboot the board. The same failure was recorded on
2026-09-02, where connecting ~14 s after power-up produced a log containing two complete
boot sequences with `ts_ms` resetting 10002 → 591.

The existing mitigation — construct with `port=None`, clear `rts`/`dtr`, *then* open — stops
**pyserial** from asserting the lines. It does not stop the Windows CH340 driver from setting
the line state itself at open, and again at close. A reset pulse can still get through.

What made this hard to read is that the symptom appears on the *other* device. The GUI
reports "Connected" and shows N/A; the only visible sign is on the buoy, where the heartbeat
LED stops. The firmware's LED semantics say which state it is in, and they are worth stating
because they are diagnostic:

| LED | Meaning (VertiSea.ino) |
|-----|------------------------|
| solid ON, indefinitely | inside `setup()` — driven HIGH on entry, LOW only at the end |
| 1 Hz blink | normal `loop()` |
| 4 Hz blink | `sdError` — SD degraded, recovery being attempted |
| N short blinks, repeating | `haltWithBlinkCode(N)`: 1 RTC, 2 BME280, 3 stab IMU, 4 fixed IMU, 5 SD, 6 filenames exhausted, 7 file open |
| frozen in whatever state it was in | `loop()` stalled — check `loop_max_us` in `_sysHealth.csv` |

Compounding it: unless the firmware is built with `USB_TELEM 1` **and** `USB_DEBUG 0`, the
buoy's USB port carries debug **text**, not telemetry packets — telemetry goes out `Serial1`
to the radio. So connecting to the buoy's own port shows N/A no matter how long you wait,
which is exactly what the screenshot showed. And while the GUI holds the port, the Arduino
Serial Monitor cannot open it, so the operator loses their only diagnostic at the moment they
need it.

**Fix.** The GUI now identifies the port by USB vendor ID before opening it. `0x1A86` (WCH,
the CH340E) is the buoy itself; `0x0403` (FTDI) is the RFD900x ground modem this GUI is for.
Selecting a CH340 port raises a confirmation dialog stating both consequences — the reset
risk and the text-not-packets problem — and pointing at "Load BIN File", which reads the SD
log and needs no serial connection at all. It is a confirmation rather than a block: opening
the buoy over USB is legitimate when the firmware is built for it.

**Not fixed:** the reset itself is a hardware path (CH340E RTS → Artemis reset) and cannot be
closed in software on the host side. During a logging run, do not open the buoy's USB port.

---

### Issue 64 — 🟠 High: a backwards `micros()` step was reported as a 71-minute loop stall

**Found:** 2026-09-11, from a real log whose parse warning read *"LOOP STALL: longest loop()
pass was 4294967 ms … most likely an I2C stall."*

4 294 967 ms is 4 294 967 295 µs, which is `UINT32_MAX`. It is not a measurement of anything.

`micros()` on Apollo3 is **not strictly monotonic**: the value is derived from the STIMER
through an integer conversion, and two adjacent calls can return `n` then `n-1` when a read
straddles the clock-domain boundary. The loop timer does

```cpp
uint32_t loopUs = (uint32_t)(nowUs - lastLoopEntryUs);
if (loopUs > loopMaxUs) loopMaxUs = loopUs;
```

which is correct across the genuine ~71.6 min rollover — unsigned subtraction handles that
and yields a *small* delta — but turns a **one-microsecond backward step into 4 294 967 295**.
And because `loopMaxUs` is a max-hold reset only once a second, that single glitch owns the
entire interval.

The consequence was worse than a wrong number. The host parser's health post-pass, added
specifically so that an operator would not have to interpret raw counters, took the value at
face value and produced an authoritative, specific, and completely wrong diagnosis pointing
at the I²C bus. The board was running normally: the same log's sane records show a worst
loop pass of 48 ms. A diagnostic that fabricates a fault is worse than no diagnostic, because
it is acted on.

`sdServiceMaxUs` around `logFile.write()` had the identical exposure and would have reported
a multi-thousand-second SD write.

**Fix, firmware.** `TIMING_MAX_PLAUSIBLE_US` (60 s) is the ceiling above which a µs delta is
treated as a timer fault rather than a measurement. Both timers now discard such a delta and
set a new sticky `timerAnomaly`, reported as `HEALTH_FLAG_TIMER_ANOM` (bit 2 of the existing
`flags` byte — no packet-layout change, so old parsers still read the record) and reset
alongside the maxima it protects. 60 s is unreachable by any real mechanism: the SD path tops
out near 50 ms, and an I²C stall long enough to approach it would have taken the heartbeat LED
with it long before.

Discarding is safe in the direction that matters. A real stall is three orders of magnitude
below the ceiling, so nothing diagnosable is lost; keeping the value reports a 71-minute loop
pass on a board that never missed a beat.

**Fix, parser.** Records at or above `TIMING_IMPLAUSIBLE_US` are excluded from the maxima and
reported separately as `TIMER ANOMALY`, by value as well as by flag so that logs written
before this change are still read correctly rather than left to report a stall. Four
regression tests cover it, including that a genuine 980 ms stall is still reported.

---

### Issue 65 — 🔴 Critical: the Hall line is carrying 36× the mechanically possible edge rate

**Found:** 2026-09-11, same log. **94 691 edges rejected, 1 211.8/s average.**

This is Issue 54's hypothesis confirmed with a number, and it is the direct measurement of
what the user described at the very start of this work: *"측정쪽 신호에 영향을 받는 것 같음"*
— the LED behaviour changing with the measurement signal.

One magnet at 2000 RPM produces **33.3 edges/s**. The ISR rejected 1 211.8/s as arriving
faster than `RPM_MIN_PERIOD_US` (20 000 µs = 3000 RPM, already 1.5× above what the harvester
reaches). That is 36× the maximum rate the mechanism can physically produce, sustained over
the whole record. It is not contact bounce and not a marginal magnet gap; it is electrical
interference coupling into the Hall line from the harvester.

Two consequences, and the second is the one that matters for a 1–2 day deployment:

1. **The RPM channel is unusable.** Every interval spanning a spurious edge is discarded, so
   what survives is not a measurement of rotor speed.
2. **Every rejected edge still costs an interrupt.** The source-level rejection added in
   Issue 54 keeps the storm out of the SD pipeline — which is why this log shows
   `overruns=0` where an earlier build would have overrun and latched `sdError` — but it
   cannot make the interrupt free. At 1 212/s the average load is small; the danger is that
   the average hides bursts, and a burst dense enough to starve `loop()` past the 500 ms
   heartbeat interval is exactly the "LED stops blinking" symptom that started this.

**This is a wiring fault and must be fixed at the wiring.** Shield the Hall line; route it
and its return away from the harvester output; add an RC low-pass at the sensor pin. Setting
`RPM_ENABLE 0` removes the interrupt load and is a legitimate stopgap for a deployment that
does not need RPM — it is what confirmed the Issue 59 diagnosis — but it does not remove the
noise, and the same coupling is present on every other line that shares the routing.

**How to confirm the coupling directly:** run ~10 min with the harvester turning and ~10 min
with it stopped, and compare `hall_rejected` between the two `_sysHealth.csv` files. If the
count tracks the harvester, the path is established.

The parser now states the ratio to the mechanical maximum rather than a bare count, and calls
interference by name above 5×.


---

### Issue 66 — 🟡 Medium: bench test — A14 read zero with 1.2 V "applied"; the ADC path is not the reason

**Found:** 2026-09-12, capture `09111727.BIN`. Two bench supplies: 3.3 V on the battery
divider input, 1.1–1.3 V "on the current measurement pin".

**What the log shows.**

| channel | 0–22 s | 22–48 s |
|---|---|---|
| A14 (current) | mean 35 counts, **65 % exact zeros**, spikes to ~500 (≈ 0–6 mA) | **exactly 0, every sample** |
| A15 (battery) | ≈ 0 (divider input open, pulled down by R_bottom) | **13 600 counts = 3.28 V**, then scatter 8 199–16 383 |

1.2 V on A14 should read `1.2 / 1.972 × 16383 ≈ 9 970` counts. It never did. The first 22 s
is the signature of an **open input** — a floating pad picking up noise, mostly at or below
ground — and after 22 s the pad is **held at or below 0 V**. Neither is "a voltage was
applied and mis-converted".

**Why the firmware is not the suspect.**

* The pad identities are verified against the Apollo3 core 1.2.1 Artemis Nano variant table:
  Arduino pin 14 → pad 35 (ADC SE7), pin 15 → pad 32 (ADC SE4). Both are valid ADC pads and
  both are the silkscreen labels `A14` / `A15`.
* `docs/adc_calibration.md` records this exact code path tracking a DMM on **A14 at 93 mV,
  1 028 mV and 1 864 mV** to within 1.5 %. The channel converts applied voltages correctly.
* The 2026-09-03 capture shows a clean 125 mA discharge on the same pin with the sensor.
* The battery channel in this same run reads **3.28 V for a 3.30 V input** through the
  1.998 divider with the 1.977 V effective reference — 0.7 % error. The ADC, the reference
  and the conversion arithmetic are all working in this very log.

So a hard zero on A14 means the pad was not at 1.2 V. The most common bench causes, in
order: the second supply's negative terminal not returned to board GND (a supply with no
ground path is not a voltage at the pad — it floats, which is the first 22 s); the supply
output disabled; the probe on a neighbouring pad; or the supply reversed, which would hold
the pad below ground — which is what the hard zero looks like, and which the pad's ESD
diode does not enjoy.

**The battery scatter is not the ADC either.** The first six seconds after the 3.3 V supply
was attached read 13 561–13 639 (±0.3 %). The 8 199–16 383 scatter begins at ~31 s, which is
when the second supply was being handled: a moving ground or an open clip on a 49 kΩ source
impedance node will do exactly that. A 0.1 µF across R_bottom would make the node immune to
it, and would also help the Apollo3 ADC's short sample window, but it was not the cause here.

**Fix / what was done.** No firmware bug to fix. The pad numbers are now stated at the pin
definitions, and the 1 Hz `USB_DEBUG` line prints `A14=` and `A15=` raw counts so a bench
test can be read live: touch the probe to the pad and watch the count. The decisive test is a
meter on the pad against board GND while that line runs — if the meter sees 1.2 V and the
count is 0, reopen this issue; otherwise it is the wiring.

**Bonus control result.** This bench run had the harvester stopped and shows
`hall_rejected = 0` over 48 s, against 94 691 with the harvester running (Issue 65). That is
the harvester-off half of the comparison proposed there, and it points at the harvester.
IMU rate in this log: 98.4 Hz (mean interval 10 167 µs) on core 1.2.1 — Issue 34's ~93 Hz
figure confirmed in the right range.

---

### Issue 67 — 🟠 High: a missing SD card halted setup(), which made card-less USB sessions impossible

**Found:** 2026-09-12 — "IMU 실시간으로 보려고 SD 카드없이 시리얼로 바로 연결".

`setup()` ran `SD.begin()` and, on failure, `haltWithBlinkCode(5)`. The board never reached
`loop()`, so `TELEM_SERIAL` never carried a packet, so the GUI showed N/A in every field —
indistinguishable from the wrong-port and wrong-build failures, and at the very moment the
operator wanted to watch the IMU live without a card in the slot.

This was the SD half of the Issue 47 policy question, and the user's workflow decides it:
**an SD fault degrades; it never halts.** Every SD write path already short-circuits on
`sdError` before touching `logFile` (`sdAppendRecord`, `sdFlushBuffered`,
`sdServiceOneSector` all return early), the heartbeat already switches to 4 Hz on `sdError`,
and `TYPE_STATUS` already carries the flag — the degraded mode existed for a mid-run failure
and only the boot path refused to use it.

**Fix.** `setup()` now sets `sdError` and continues on any of the three former halts:

| former code | fault | now |
|---|---|---|
| 5 | `SD.begin()` failed (no card / dead card) | degrade, **retries exhausted** |
| 6 | every `LOGnnnnn.BIN` name taken | degrade, retries exhausted — a remount cannot free a name; refusing to overwrite is the rule, refusing to run is not needed to honour it |
| 7 | card mounted but `SD.open()` failed | degrade, **retries armed** — a remount and a fresh counter name can clear this |

Retries are exhausted deliberately for the no-card case. With nothing on the bus,
`SD.begin()` waits out the SD library's full 2 s init timeout before failing; retrying every
`SD_RECOVERY_INTERVAL_MS` (5 s) would stall `loop()` for 2 s in every 5 — freezing the LED,
dropping IMU samples and gapping telemetry, in precisely the session this mode exists for. A
card inserted later needs a reset, which SPI SD requires in practice anyway.

`sdWriteBootRecords()` is skipped when degraded (it would drop every record harmlessly, but
skipping keeps the debug output honest). Codes 5–7 are retired, not renumbered, so an
operator's notes from an older build still read correctly.

**Confirmed on hardware, same day:** with a card present and `USB_DEBUG 0`, `USB_TELEM 1`,
`TELEM_ENABLE 1`, live telemetry on the buoy's own USB port populated every field — the N/A
seen earlier was `USB_DEBUG 1` routing packets to `Serial1`. The card-less path is the
remaining `[UNCONFIRMED]` piece: it needs one boot with the slot empty and the 4 Hz LED.


---

### Issue 68 — ⚪ WITHDRAWN: the battery divider constants are correct

**Raised and withdrawn 2026-09-15.**

I claimed the divider had been rebuilt without updating `BATTERY_R_TOP_OHM` /
`BATTERY_R_BOTTOM_OHM`, deriving an "implied 1.835:1" from the assumption that the source
was 3.30 V. The resistors were then measured: **98.9 kΩ and 98.8 kΩ**.

| | ratio | vs the firmware's 1.99798 |
|---|---|---|
| R_top 98.9 k, R_bottom 98.8 k | 2.00101 | −0.15 % |
| R_top 98.8 k, R_bottom 98.9 k | 1.99899 | −0.05 % |

Either orientation is within 0.15 % of the compiled value. **There is no divider-constant
error.** The reasoning inverted a known and an unknown: the source voltage was the assumption
and the ratio was the measurement, and I treated it the other way round.

What the counts actually say, with the ratio now confirmed, is that the divider input really
was at **3.60 V** — see Issue 69. The arithmetic was right; the thing it was solved for was
wrong.

`vertisea_protocol.py` now reports the implied divider-input voltage on every log, so this
conversion is never done by hand again:

```
Battery channel: 14946 counts mean (range 14870-15074) = 1.8037 V at the ADC pad
= 3.609 V at the divider input, using the 2.0010:1 ratio the log carries.
On a bench test compare that last number with the supply setting; the pad
saturates once the divider input passes 3.956 V.
```

---

### Issue 69 — RESOLVED: the channel interaction was grounding, not the MCU

**Reported 2026-09-15** — each supply alone reads correctly, both together and neither does,
concluded as "the MCU cannot measure voltage and current at the same time".

**Resolved the same day by correcting the grounding.** The 18:03 capture is the proof, and it
is a clean one: the battery channel sat pinned at 16 383 for five seconds **before** the
current channel was energised at all, and when the current channel came up it read
**9 130 counts = 1.099 V = 109.9 mA** against 1.100 V applied — correct to 0.1 % — and stayed
correct for the rest of the run while the battery channel remained pinned. **Two faults that
no longer move together are two independent channels.** The interaction is gone. What remains
on the battery side is Issue 70 and has nothing to do with the current channel.

**The MCU claim is disproved by this project's own data.** `docs/adc_calibration.md` §3.1–3.2
records three 120 s captures with **both channels driven simultaneously from separate bench
supplies at different voltages**, 60 000 samples per channel per run:

| Run | A14 DMM | A14 measured | A15 DMM | A15 measured |
|---|---|---|---|---|
| 1 | 93 mV | 92.84 mV | 1719 mV | 1738.39 mV |
| 2 | 1028 mV | 1042.05 mV | 1447 mV | 1463.69 mV |
| 3 | 1864 mV | 1890.53 mV | 1217 mV | 1231.92 mV |

Every channel tracked **its own** source to within 1.4 % with the other channel energised at
a different voltage. The Apollo3 ADC is one SAR behind a mux: it converts one channel at a
time and `analogRead()` reconfigures the slot per call, which is time-multiplexing, not a
restriction. So the channels interacting is a property of the wiring in front of them, not
of the MCU.

**Two wrong hypotheses, one habit.** I proposed a ground loop, then — after being told the
grounds were shared — a dual-output supply in SERIES/TRACKING mode, with arithmetic that fit
the observed 4.40 V saturation neatly. Both were attempts to explain the two channels as one
coupled system, and the withdrawn Issue 68 was the same mistake in a different costume. The
evidence never showed more than a shared return. Fitting arithmetic is not evidence when the
model was chosen to fit.

**Worth keeping from the chase:** `vertisea_protocol.py` groups battery samples by the current
level in force at the same instant and reports the shift, so channel interaction is answerable
from any log that carries both channels. It reports rather than diagnoses, because on a
deployment log the same number is the cell sagging under harvested current — real, and the
thing this system exists to measure.

---

### Issue 70 — 🟠 High: the battery divider is not dividing — the pad sees the whole source

**Found:** 2026-09-15, the 18:03 capture, with grounding corrected and the current channel
verified good.

`A15` pins at **16 383** from the instant the source is connected and never moves.

| | pad | divider input |
|---|---|---|
| 3.300 V through the 2.001:1 divider | 1.649 V | 3.300 V → **13 666 counts** |
| **observed** | **≥1.977 V** | **≥3.956 V** → **16 383, pinned** |
| 3.300 V arriving at the pad undivided | 3.300 V | — → **pinned**, matches |

The resistors measure 98.9 kΩ / 98.8 kΩ (Issue 68), so the divider *as a pair of components*
is fine. What is not fine is that the pad sits at very nearly the full source voltage, which
means the bottom leg is doing nothing: **an open R_bottom, or an open ground return on
R_bottom, leaves the pad floating up to the source through R_top.** That is the usual outcome
of reworking grounding, which is exactly what just happened.

The reading is a **floor, not a measurement** — the true voltage is anything at or above
3.956 V — so no post-processing can recover it.

**Check with the supply OFF, meter on resistance:**

| from | to | expect |
|---|---|---|
| ADC pad (A15, Apollo3 pad 32) | board GND | **~98.8 kΩ** — infinite means the bottom leg is open |
| ADC pad | divider input | ~98.9 kΩ |
| divider input | board GND | ~197.7 kΩ |

Then with the supply on, the pad must read **~1.65 V**, not 3.3 V.

`vertisea_protocol.py` prints these expected resistances in the saturation warning, derived
from the `r_top_ohm` / `r_bottom_ohm` the log already carries, so the check needs no external
reference.

---

### Issue 71 — 🟡 Medium: the current channel drifts ~24 % on a fixed bench input

**Found:** 2026-09-15, same capture, noticed while confirming the current channel.

With a fixed 1.100 V applied, `A14` reads 9 040 → 9 463 → 9 923 → 10 490 → **11 200** over
about eight seconds, then settles back to ~9 740–9 814. That is **1.088 V → 1.348 V, +23.9 %**,
well outside the ±0.1 % the same channel showed in its first seconds (9 130 counts = 1.099 V
against 1.100 V applied).

Most likely the supply was being adjusted during the run — the excursion is smooth and
one-directional, which is what a knob looks like and not what noise looks like. Worth one
deliberate check before dismissing it, because a 24 % drift on a fixed input would invalidate
every harvested-current number this system produces: apply 1.100 V, **touch nothing**, and
watch the `A14=` line for 60 s. It should hold 9 137 ± 20.
