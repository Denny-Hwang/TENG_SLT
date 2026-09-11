# CHANGELOG — VertiSea.ino

Newest first.

---

## 2026-09-11 (later) — Reject impossible micros() deltas instead of max-holding them — `[UNCONFIRMED]`

A real log reported `loop_max_us` = 4 294 967 295, i.e. `UINT32_MAX`, which the host parser
turned into "4294967 ms loop stall, most likely an I2C stall". There was no stall — the same
log's sane records peak at 48 ms.

`micros()` on Apollo3 is not strictly monotonic: two adjacent calls can return `n` then `n-1`
when a read straddles the STIMER clock-domain boundary. `nowUs - lastLoopEntryUs` is correct
across the genuine ~71.6 min rollover (unsigned subtraction gives a small delta there) but
turns a one-microsecond backward step into 4 294 967 295 µs — and `loopMaxUs` max-holds it for
the whole second. `sdServiceMaxUs` around `logFile.write()` had the same exposure.

Both now discard a delta above `TIMING_MAX_PLAUSIBLE_US` (60 s) and set `timerAnomaly`,
reported as `HEALTH_FLAG_TIMER_ANOM` — bit 2 of the existing `flags` byte, so the 29-byte
`SysHealth` layout is unchanged and older parsers still read the record. The flag resets with
the maxima it protects, so the host can distinguish "no stall measured" from "the measurement
was rejected".

60 s is unreachable by any real mechanism, so nothing diagnosable is lost: the SD path tops
out near 50 ms, and an I²C stall approaching a minute would have frozen the heartbeat LED long
before. Issue 64.

---

## 2026-09-11 — USB_DEBUG line printed counters the health block had just zeroed — `[UNCONFIRMED]`

Field output showed `maxWriteUs=0` on every 1 Hz debug line, which is exactly the number
someone reads that line to see.

Cause: both the health-record block and the `USB_DEBUG` print fire at 1 Hz, and the health
block runs **earlier in `loop()`**. It resets `sdServiceMaxUs` and `loopMaxUs` after writing
the record, so by the time the debug print reads them they are always 0. Introduced with the
health record earlier today.

The reported values are now stashed in `reportedWriteMaxUs` / `reportedLoopMaxUs` before the
reset, so the console line and the SD record show the same figures instead of the console
showing zeros.

Also added `loopUs=` to the debug line. Nominal is ~2700 us; a much larger value means
`loop()` is not achieving its rate, which starves every gate inside it — the failure mode
seen on core 2.x, where the achieved logging rate was ~300 B/s against an expected
~5700 B/s (about 5.6 IMU samples/s instead of ~93). Without that column the only way to
notice was to reverse-engineer it from the `SDq=` growth rate by hand.

---

## 2026-09-11 — Refuse to build on Apollo3 core 2.x (mbed): `micros()` in the Hall ISR panics the kernel — `[CONFIRMED 2026-09-11]`

**Status:** `[CONFIRMED 2026-09-11]` — reproduced on hardware; the MbedOS panic was
captured over USB and the 196-byte `.BIN` files match the predicted failure exactly.

Apollo3 core 1.x is a bare Arduino core where `micros()` is a timer read. Core 2.x is built
on mbed OS, which forbids RTOS primitives in interrupt context — and its `micros()` takes a
mutex. `hallISR()` calls `micros()` as its first statement, so on 2.x the board panics on
the FIRST Hall edge after `attachInterrupt()`, roughly a second into `loop()`:

```
++ MbedOS Error Info ++
Error Status: 0x80010133 Code: 307 Module: 1
Error Message: Mutex: 0x100033BC, Not allowed in ISR context
```

**What makes this expensive is that it does not look like a crash.** Every observable
pointed somewhere else:

| Symptom | Real cause |
|---------|-----------|
| `.BIN` contains exactly 196 bytes | the boot records were flushed in `setup()`; the panic lands before the first 5 s flush, so the 118 B then queued never reach the card |
| No telemetry on any port | dead ~1 s into `loop()` |
| **Heartbeat LED blinking at ~1 Hz** | the *mbed error handler's* blink, not ours — so the one indicator an operator trusts said "healthy" |
| Binary bytes mixed into the `USB_DEBUG` text | `Serial`/`Serial1` map differently on 2.x, so `Serial1` telemetry surfaces on USB |

Diagnosis took a day of hardware debugging across several wrong hypotheses (telemetry
routing, library versions, SD wiring) because the code compiled cleanly and the LED looked
right.

**This is very likely the original field fault.** The report that started this work was
"the LED stops blinking or sticks on, and it seems to depend on the measurement signal."
Issue 54 attributed it to harvester EMI on the unshielded Hall line starving `loop()` with
an interrupt storm. The EMI mechanism was right and the consequence was badly understated:
on core 2.x a *single* induced edge is fatal, and what the operator sees afterwards is the
mbed error blink replacing the heartbeat — which fits "stops blinking / changes" far better
than loop starvation. The Issue 54 ISR threshold does not help, because `micros()` runs
before the test.

**Change:** a `#error` guard on `ARDUINO_ARCH_MBED`, escapable with `ALLOW_MBED_CORE` for
anyone who deliberately wants to port. `README.md` §4 and `AGENTS.md` now state that 1.2.1
is a hard requirement rather than a preference, with the symptom table so the next person
recognises it in minutes. README also gains a row in "Things That Are Easy to Forget" and
instructions for telling the two cores apart from the build log.

**Why a guard rather than fixing the ISR:** every timing figure in `docs/` — achieved IMU
rate, current sample rate, SD write latency, the 400 Hz-vs-1000 Hz experiment — was
measured on 1.2.1. A 2.x build would not be comparable even if it ran, so making it *run*
would invite silently incomparable data. Issue 59 records the options if 2.x ever becomes a
requirement: read the Apollo3 STIMER directly (ISR-safe on both cores), timestamp in
`loop()` instead (costs ~10% RPM accuracy), or `RPM_ENABLE 0`.

**Verified:** the guard fires under `-DARDUINO_ARCH_MBED`, passes without it, and passes
with `-DALLOW_MBED_CORE`. No other change to the firmware.

---

## 2026-09-11 — Move the vendored Madgwick into the sketch folder so it is actually compiled — `[UNCONFIRMED]`

**No behavioural change to the sketch's own code — but potentially a large change to what
gets built.**

`#include "MadgwickAHRS.h"` sat in `VertiSea/VertiSea.ino` while the header lived in
`Madgwick/src/`, a **sibling of the sketch folder**. A quoted include searches the
including file's directory first and then the compiler's `-I` paths; arduino-builder's
paths cover the sketch folder, core, variant and sketchbook `libraries/` — never a sibling
directory. The vendored copy was therefore invisible to the build, and the only way the
sketch compiled at all was via a Library Manager install, which `README.md` and `AGENTS.md`
both told the developer not to have while simultaneously claiming the vendored copy "takes
precedence over any global Arduino install".

That matters because the in-tree copy is a local fork: `betaDef` is 0.5f against upstream's
0.1f. If the global copy was compiled, the AHRS gain was 5× lower than every comment in the
firmware states — including the `setup()` TODO that proposes reducing it toward 0.05–0.1,
which would then have been describing a change already made by accident. It also weakens
the Issue 41 reasoning, which assumed beta = 0.5 masks the accel/gyro frame mismatch.

`MadgwickAHRS.{h,cpp}` now sit beside the `.ino`. The `#include` line is unchanged; the
placement is what fixes it, and it fixes three things at once: the quoted include can only
resolve to the adjacent copy, arduino-builder never searches libraries for a header it can
already find (so no duplicate symbols from a stray global install), and Arduino compiles
every `.cpp` in the sketch folder automatically.

Upstream packaging metadata moved to `archived/Madgwick-upstream/`. Keeping a second copy
of the sources anywhere was rejected — that is the duplication failure that retired the
MATLAB parser.

**Action on the developer's machine:** delete any `Madgwick`/`MadgwickAHRS` library from
the sketchbook `libraries/` folder, then rebuild. It is now unnecessary, and removing it is
the only way to be certain which code runs. See Issue 58.

---

## 2026-09-11 — Robust long-duration logging: SD recovery, ISR noise rejection, health record — `[UNCONFIRMED]`

**Reported symptom:** on the bench the heartbeat LED blinks at 1 Hz to show SD logging is
alive, but it frequently stops blinking or sticks fully on, apparently influenced by the
measurement signal. Field deployments need 1–2 days of continuous logging.

The LED toggles in the **last** block of `loop()`, so a frozen LED means a pass did not
complete. Four independent defects could produce that, and nothing in the firmware recorded
enough to tell them apart. All four are addressed; the instrumentation is the part that
matters most, because it converts an unreproducible field symptom into a number.

**1. `digitalRead()` on an OUTPUT pad (direct cause of "stuck on").**
`digitalWrite(LED_PIN, !digitalRead(LED_PIN))` assumes the pad reads back its driven level.
On Apollo3 a pad configured for OUTPUT may have its input buffer disabled, in which case
`digitalRead()` returns 0 — and `!0` is always HIGH, so the LED latches on and stops
blinking **while the firmware runs perfectly normally**. State is now held in `ledState`.
This alone explains the "stays on, never blinks" variant; it cannot explain "stops
mid-blink", which is the stall case below.

**2. Hall ISR accepted every edge (the "affected by the measurement signal" path).**
`RPM_MIN_PERIOD_US` was applied in `loop()`, after the ISR had already taken the interrupt
and buffered the timestamp. The TENG discharge is a high-voltage event beside an unshielded
open-collector sense line, so a burst of induced edges cost three times over:

  * every edge takes an interrupt, starving `loop()` — visibly freezing the LED;
  * every pass then emitted a `TYPE_HALL_EDGE` record of up to 31 timestamps (129 B), so a
    ~370 Hz loop produced ~48 kB/s of noise into a pipeline sized for ~6 kB/s — the queue
    overran and latched `sdError`, ending logging for the deployment;
  * RPM itself was destroyed, because `loop()` discards any interval spanning >1 edge.

The same threshold is now applied **inside** the ISR, which costs one comparison and breaks
all three. `hallEdgeRejected` counts what it dropped, so the interference becomes visible
instead of merely destructive.

**3. `sdError` was a one-way latch.** The first write failure of the deployment stopped
logging permanently; only a power cycle cleared it. Acceptable for a ten-minute bench run,
not for 1–2 days — a single EMI glitch on SPI, a card pausing for garbage collection, or a
brown-out ended the run, and the only outward sign was the heartbeat changing to 4 Hz.

It is now a recoverable state machine: on failure, back off `SD_RECOVERY_INTERVAL_MS`, then
close the handle, re-run `SD.begin()`, and open a **new** file. A new file is the point, not
a side effect — after a card fault the old handle's cached cluster chain is untrustworthy,
and data already written stays intact. The RAM queue is discarded on recovery because those
bytes are mid-stream fragments of the failed file; splicing them into a new one would leave
a partial record the parser cannot resynchronise from. Capped at
`SD_MAX_RECOVERY_ATTEMPTS` so a genuinely dead card does not spend the run re-running
`SD.begin()` in the sampling path.

`sdWriteBootRecords()` was factored out of `setup()` for this: a recovered file re-emits the
RTC anchor and every calibration record, so it is as self-describing as the first. Without
that, a recovered file's counts could not be converted to mA (needs `0x0D`), volts (`0x13`),
IMU units (`0x08`/`0x09`), or wall-clock time (`0x05`). `setup()` now computes the LPF
alphas *before* writing boot records rather than after, since `TYPE_LPF_CAL` carries them.

**4. `TYPE_SYS_HEALTH` (`0x15`), 1 Hz to SD.** The firmware measured nothing about its own
execution, so the five candidate causes of a frozen LED were indistinguishable. One record
per second now carries `loop_max_us`, `sd_write_max_us`, SD failure/recovery counts, queue
high-water, overruns, and the Hall rejection/loss counters. `loop_max_us` is measured at the
**top** of `loop()` against the previous entry, so it includes whatever blocked anywhere in
the body — including an I²C stall, which is the one cause no other counter can reveal.
Cost is 34 B/s against ~6 kB/s.

**NOT done — no watchdog.** An I²C stall still hangs the board permanently. The Apollo3 WDT
is the right answer and would turn a hang into a reboot-and-continue (the firmware already
opens a fresh file on boot, so a reboot costs seconds, not the run). It is not included here
because the AmbiqSuite WDT API could not be compile-checked in this environment, and
shipping an unverified reset path into a deployment is worse than the problem. Recommended
as the next change, with a bench soak to confirm it does not reset spuriously.

**Verification:** syntax-checked with `g++ -fsyntax-only -std=c++14 -Wall -Wextra` against
stub headers — no new diagnostics beyond the one pre-existing `%lu` stub artefact. The
`0x15` layout is covered by 8 new round-trip tests. **Not compiled for Apollo3, not run on
hardware.** Bench test before trusting: (a) confirm the LED blinks steadily for an hour;
(b) pull the SD card mid-run and reinsert it, and confirm a new `LOGnnnnn.BIN` appears and
`sd_recoveries` increments; (c) run the harvester and check `hall_rejected` and
`loop_max_us` in `_sysHealth.csv`.

---

## 2026-09-11 — Issues 45–47: per-window `n_dropped`, non-fatal magnetometer, diagnosable halts — `[UNCONFIRMED]`

**Issue 45 — `n_dropped` was incomparable to `n_samples`.** The window-close block reset
`statCharge_mC`, `statI2t_mA2s`, `statIntegSec`, `statPeakCounts` and `statSamples`, but not
`currentDropped`, which stayed cumulative since boot. The two sit side by side in
`TYPE_CURRENT_STATS` and in the GUI, so the ratio a reader naturally forms from them was
meaningless, and the value grew without bound over a deployment. `currentDropped` is now
reset with the rest of the window state. The packet layout is **unchanged** — same field,
same offset, same type — so no parser change was needed; only the meaning narrowed, and the
field comments say so.

**Issue 46 — the magnetometer was a fatal dependency on a device nothing reads.**
`collectIMUData_ISM()` is called with `isStabilizedIMU=false` for *both* IMUs, so the branch
that touches the MMC5983MA never executes. Yet `mag.begin()` failing halted the board
forever, and with `IMU_RAW_ONLY 0` the `TYPE_MAG` record was still written every tick from
an `LPFState` nothing updated — constant `0.0`, indistinguishable in the CSV from a real
reading near the calibration centre.

Two changes. `mag.begin()`'s result goes into a new `magPresent` global and a failure warns
instead of halting. And the 9-DOF decision moved from a bare `false` literal at the call
site to `#define STAB_IMU_USES_MAG 0`, which now gates both the sensor read and the `0x07`
write. A 6-DOF build emits no `0x07` at all: an absent record is unambiguous, a fabricated
zero is not. Re-enabling 9-DOF restores both from one place.

> Logs written before this date by an `IMU_RAW_ONLY 0` build contain a `_mag.csv` of
> constant zeros. Those are not measurements.

**Issue 47 — partial.** `while (!imu.getDeviceReset());` appeared twice as an unbounded spin
on an I²C read; a NAK or a wedged bus hung the firmware there with no timeout. Both are now
`waitForDeviceReset()`, which gives up after 500 ms (the datasheet reset is sub-millisecond)
and warns.

Every fatal `while (1);` is now `haltWithBlinkCode(n)`. Previously a field build
(`USB_DEBUG 0`) compiled out the DBG_PRINTLN above each halt, left the LED solid HIGH from
the top of `setup()`, and initialised no port — so a dead buoy was completely silent about
why, and the fault could not be diagnosed without reflashing a debug build. The codes are
1 RTC, 2 BME280, 3 stabilized IMU, 4 fixed IMU, 5 SD card, 6 filenames exhausted, 7 file
open failed.

**Deliberately NOT changed:** whether these failures should halt at all. Continuing in a
degraded mode and recording the failure in a boot-status packet is a plausible design, and
so is enabling the Apollo3 watchdog, but both change what a deployment produces and that is
the project owner's call. Issue 47 stays open for it. **Issue 41 (accel X and gyro Y negated
into two different body frames) was likewise not touched** — it needs the mechanical drawing
and a rotation test, and guessing at it would be worse than leaving it documented.

**Verification:** syntax-checked with `g++ -fsyntax-only -std=c++14 -Wall -Wextra` against
stub Arduino/SparkFun headers. Same single pre-existing `%lu` format warning as the
unmodified file, no new diagnostics. Not compiled for Apollo3 and not run on hardware.

---
## 2026-09-11 — Correct the `IMUCal` unit comments (mdps, not °/s) — `[UNCONFIRMED]`

**Comment-only change; no behaviour, no packet layout, no constant values changed.**

`collectIMUData_ISM()` computes `gx_dps = (gyroData.xData - cal.gyro_bias[0]) * 0.001f`. The
subtraction happens in the driver's native mdps units, so `gyro_bias[]` is in millidegrees per
second. The struct comment said °/s, which made the committed −438.56 read as a −438 °/s
zero-rate bias — a sensor pegged near its ±500 °/s full scale. The same error had propagated
into four documents and caused a real 1000× mistake in the 2026-04-02 recalibration
(see Issue 42 and `docs/calibration.md`).

Also corrected `accel_scale`'s comment from "counts per +1 g" to "milli-g per +1 g (≈1000)":
`sfe_ism_data_t` is already scaled by the SparkFun library, so nothing in this struct operates
on raw LSB counts. That is the same wrong assumption that produced the Issue 35 int16 gyro
overflow, so it is worth stating once, in the struct.

Added the °/s equivalents to the `fixedCal` / `stabCal` initialiser comments so the numbers are
sanity-checkable at the point of definition.

---
## 2026-09-10 — Enter the installed battery divider (98.7 k / 98.9 k) and correct the cell chemistry to LiFePO4 — `[UNCONFIRMED]`

**Why:** The EE built and measured the A15 battery divider, replacing the 30 k / 20 k
placeholders from 2026-09-08. He also clarified the cell is **1S LiFePO4**, not Li-ion — the
placeholder `static_assert` and comments assumed a 4.2 V Li-ion cell.

**Source (EE, Teams, 2026-09-10):** two 99 kΩ nominal resistors, DMM-measured R1 (BAT+ side)
= 98.7 kΩ, R2 (GND side, A15 tapped across it) = 98.9 kΩ → ratio 1.99798. R1 is wired
**inline in the V+ lead between the PMC and the divider board** as a short-circuit guard, so
only R2 is physically visible on the board. No filter capacitor (C1) fitted. Bench points:
3.000 V → 1.495 V, 3.300 V → 1.645 V at the node. The EE asked that the *measured resistor
values* be used, not the node readings, attributing the small discrepancy to DMM loading.

**Checked the EE's attribution before adopting it:** the resistor-derived node voltages are
1.5015 V and 1.6517 V, i.e. the DMM read 6.5–6.7 mV low in both cases. A 10 MΩ meter across
R2 lowers the effective R2 to 97.93 kΩ and raises the loaded ratio to 2.0078, predicting
1.4941 V and 1.6436 V — within 1 mV of what he read. His explanation is quantitatively
correct, and it also means the divider is *not* a candidate for a two-point fit from those
bench numbers (they measure the divider-plus-meter, not the divider-plus-ADC).

**What changed:**

- `BATTERY_R_TOP_OHM` 30000 → **98700**, `BATTERY_R_BOTTOM_OHM` 20000 → **98900**;
  `BATTERY_DIV_RATIO` 2.5 → **1.99798**; `COUNTS_TO_BATTERY_V` ≈ 0.2411 mV/count
  (with `VREF_A15`).
- New `BATTERY_CELL_MAX_V = 3.65f` (LiFePO4 charge termination) replaces the literal `4.2f` in
  the full-scale `static_assert`. At 3.65 V the node is 1.83 V — 91 % of the 2.0 V ADC full
  scale, so headroom is thin but adequate; the ADC would clip at ~4.0 V cell voltage, which a
  LiFePO4 cell cannot reach. (With the old 4.2 V literal the assert would have *failed* on the
  2:1 divider, which is a useful sign it was doing its job.)
- Header and pin comments updated: LiFePO4, divider values, inline R_TOP location, and that
  the EE will add a current-channel divider only if clipping is observed.
- `0x13` `TYPE_BATTERY_CAL` payload now carries the measured resistors and 1.99798 ratio at
  boot. No layout change, so no protocol/parser edit.

**Flagged, not fixed — source impedance:** R_TOP ‖ R_BOTTOM ≈ **49.4 kΩ**, 4× the placeholder
divider's 12 kΩ. The Apollo3 ADC's sample-and-hold has to charge through this. The existing
loop already discards one A15 conversion after the mux switch, but whether the second
conversion is fully settled at 49 kΩ is unverified. The EE's own sketch includes a
`checkSampleHold()` sweep for exactly this (readings climbing with a longer inter-sample gap
⇒ fit C1 = 100 nF across R2). If the confirmation test below shows the firmware reading
systematically *low* by more than the ~2 mV the gain calibration leaves, that is the first
suspect; the fix is C1, not a software factor.

**Confirmation gate:** with the real divider attached, compare firmware battery voltage
(GUI `Battery:` or parsed `_batteryVoltage.csv`) against a DMM **on the cell terminals** (not
the node — see loading note above) at two or three points across 3.0–3.6 V. Expected
agreement ≈ ±5 mV after the A15 gain calibration. The 2026-09-08 battery-channel entry below
and the ADC-gain entry above share this test.

---
## 2026-09-10 — Apply measured per-channel ADC gain calibration to A14 and A15 — `[UNCONFIRMED]`

**Why:** Known-voltage runs on the isolated DMA experiment sketch (branch
`experiment/dual-adc-dma`, 2026-09-09) showed both ADC channels reading **high by a consistent
gain**: A14 +1.41 %, A15 +1.16 %, with no resolvable offset (gain-only fit residuals < 1.5 mV
at three levels × 60,000 samples). Uncorrected, this is +2.8 mA at 200 mA full scale and
~+48 mV on a 4.2 V cell through the 2.5:1 divider — both large relative to the quantities the
project cares about. Full write-up: `docs/adc_calibration.md`.

**What changed:**

- New constants in HARDWARE CONSTANTS: `ADC_GAIN_A14 = 1.014071f`, `ADC_GAIN_A15 = 1.011584f`,
  and derived `VREF_A14 = VREF / ADC_GAIN_A14` (≈ 1.97225 V), `VREF_A15 = VREF / ADC_GAIN_A15`
  (≈ 1.97710 V). `static_assert`s bound each gain to 0.95–1.05 so a typo cannot silently
  produce a wildly mis-scaled build.
- `COUNTS_TO_MA` now uses `VREF_A14` (≈ 0.012039 mA/count, was 0.012208).
- `COUNTS_TO_BATTERY_V` now uses `VREF_A15`.
- The boot-time `CurrentCal.vref` (0x0D) and `BatteryCal.vref` (0x13) records carry `VREF_A14`
  / `VREF_A15` respectively instead of the nominal 2.0 V.
- `VREF` (2.0 V nominal) is retained for the divider-headroom `static_assert` only.

**Design decision — effective reference rather than a new gain field:** the correction is
expressed as a per-channel effective reference voltage so it flows through the *existing*
`vref` field of the self-describing cal records. Consequences: (1) no change to
`docs/binary_protocol.md` or `vertisea_plot_v7.py` — the parser's `counts × vref / adc_max`
already applies the correction; (2) logs recorded before this change still convert with the
nominal 2.0 V they recorded, i.e. they remain uncorrected but self-consistent; (3) the
semantics of `vref` in 0x0D/0x13 shift from "nominal" to "effective" reference — this is
documented in the sketch and will go into `binary_protocol.md` on confirmation. An offset
term was deliberately not added: both fitted intercepts (−1.5 mV, +3.9 mV) are below the
per-sample noise std and would have required a protocol change.

**Not changed:** ADC configuration, sample rates, the `0x0F` packet layout, the placeholder
battery divider resistors (still need measured values — independent multiplicative term).

**Expected observable effect:** every reported/logged current and battery voltage drops by
1.4 % / 1.2 % relative to the previous build for the same physical input. `_currentCal.csv`
shows `vref` ≈ 1.97225; `_batteryCal.csv` shows `vref` ≈ 1.97710.

**Host validation:** compiled for `SparkFun:apollo3:amap3nano` (see compile note below).
**Hardware validation needed (confirmation gate):** the calibration was measured through the
HAL/DMA path; production uses `analogRead()` on the same ADC configuration and the gain is
expected to transfer 1:1, but this is an inference. Confirm with one spot check: apply a
DMM-measured DC voltage to A15 (≤ 2.0 V, divider bypassed) or a known current on A14, and
compare the parsed `_batteryVoltage.csv` / `_currentFast.csv` value (or the live GUI
reading) against the DMM. Agreement within ~2 mV / ~0.2 mA confirms; a residual ~1.2–1.4 %
error means the two acquisition paths differ and the constants must be re-measured with the
production firmware.

---
## 2026-09-08 — Add 1 Hz A15 battery-voltage logging and telemetry — `[UNCONFIRMED]`

**Why:** The harvester now produces enough charge that battery-side power is scientifically
meaningful. Current alone gives charge but not measured energy; battery voltage changes slowly,
so a 1 Hz channel supplies the missing scalar without duplicating high-rate current traffic.

**What changed:** Added A15 (Apollo3 pad 32 / ADC SE4), a placeholder 30 kΩ / 20 kΩ divider,
boot-time `TYPE_BATTERY_CAL` (`0x13`), and 1 Hz `TYPE_BATTERY_VOLTAGE` (`0x14`). SD stores raw
counts while telemetry sends millivolts. Two A15 reads settle that channel, then a discarded A14
conversion settles the ADC mux back to the high-rate current channel. The verified `0x0F` layout
is unchanged;
the GUI combines its average current with the latest battery voltage to display average power.

**Required validation:** Replace placeholders with measured installed resistors; compare A15 and
telemetry/CSV voltage against a DMM from approximately 3.0–4.2 V; verify no new current outliers,
parser errors, SD overruns, or heartbeat errors. This is not field-qualified until then.

**Host validation:** Compiles for `SparkFun:apollo3:amap3nano` with Apollo3 core 1.2.1 and SD
1.3.0 (50,312 bytes flash, 56,156 bytes global RAM). Core source confirms A15 maps to Apollo3
pad 32 / ADC SE4. Hardware ADC-mux settling and divider accuracy remain unconfirmed.

---
## 2026-09-04 — Pre-commit firmware cleanup after buffered-SD validation — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — user flashed the cleaned build, observed normal operation,
connected the GUI over USB, and supplied both resulting SD logs for parser verification.

**Why:** A final review found stale rate/transport comments and warning-only dead code that would
make future upgrades start from a misleading baseline.

**What changed:**

- Reframed `SD_BUFFERED_WRITE` as the independently confirmed production queue rather than a
  temporary step toward the now-rejected Apollo3 core 1.2.1 DMA backend.
- Corrected stale comments that still described current sampling as 400/~373/~690 Hz and fixed
  the top-level `USB_DEBUG`/`USB_TELEM` routing description.
- Removed the unused `currentCounts` cache and dead `printAligned()` helper/commented calls.
- Compiled GPS-only cached variables only when `GPS_ENABLE=1`.
- Explicitly consumed `setSdError()`'s message argument so field builds do not warn when debug
  output compiles away.
- Corrected the `integ_s` description: measured-dt integration makes it coverage time, not the
  achieved/requested sample-rate ratio.
- Restored the documented normal bench configuration (`USB_TELEM=1`, `TELEM_ENABLE=1`) after the
  temporary SD-only benchmark settings and enlarged local formatting buffers to make their
  8.3/time-string bounds explicit to the compiler.

**No protocol or runtime-path change intended:** packet IDs/layouts, sampling, queue behavior,
SD scheduling, telemetry, and calibration constants are unchanged.

**Hardware/log verification:** `G:\09081325.BIN` (375,199 bytes) and `G:\09081326.BIN`
(648,429 bytes) each scanned exactly to EOF and parsed with zero errors. Each contained exactly
one RTC/fixed-cal/stab-cal/current-cal/LPF-cal boot sequence; the second file is a distinct reboot
session, not an append collision. Combined records included 16,830 raw IMU samples, 136,300
high-rate current samples, 173 BME records, and 1,684 RPM records. No Hall-edge records were
expected because no magnet was available, so the Hall ISR/raw-edge path remains untested in this
confirmation.

---
## 2026-09-04 — Stage 1 buffered SD pipeline for the SPI/DMA upgrade — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — both `SD_BUFFERED_WRITE=1` and the fallback `=0` compile
successfully for `SparkFun:apollo3:amap3nano` with SparkFun Apollo3 core 1.2.1 and SD 1.3.0.
Physical A/B and 12.2-minute debug-enabled runs passed byte-integrity/parser checks; the user
observed zero queue overruns. Buffering did not increase average IMU rate, but consistently
improved current-block dead time and the IMU long tail. This stage deliberately does **not**
claim asynchronous SPI DMA.

**Why:** Measurements tie the IMU interval tail to Arduino SD 1.3.0's synchronous 512-byte
cache flushes. Jumping directly to Apollo3 IOM DMA would mix producer correctness, FAT
allocation, card protocol, and interrupt-driven SPI in one high-risk change. This stage first
creates a stable record/sector/backend boundary and gathers the timing needed to judge DMA.

**What changed:**

- Added compile-time `SD_BUFFERED_WRITE` (enabled) and an eight-sector (4096-byte) RAM ring,
  plus a 512-byte producer sector.
- Replaced fragmented header/payload writes with `sdAppendRecord()`, which accepts each packet
  atomically and preserves the existing binary protocol byte-for-byte.
- Producer paths now copy records into RAM; `loop()` services at most one complete 512-byte
  sector when there is IMU deadline slack, except near queue exhaustion where backpressure
  takes priority over timing.
- The existing Arduino SD/File backend remains synchronous. This means producer calls no
  longer trigger SD writes, but a sector service can still block on SPI/card busy time. A later
  backend can replace this service call with Apollo3 IOM DMA without changing packet producers.
- The 5-second durable flush drains the queue, writes the partial sector, then calls
  `File.flush()`. Boot records use the same path and are forced to disk before acquisition.
- Flush ordering explicitly drains any sub-sector queue tail before the newer producer bytes;
  this avoids reordering records when a packet crosses a producer-sector boundary.
- Centralized complete-write checks for every packet type. Queue overflow or any short backend
  write latches `sdError`, stops logging, preserves telemetry, and triggers the existing status
  bit/error LED behavior.
- Added development diagnostics: queue high-water mark, maximum sector-service latency, service
  count, and overrun count. With `USB_DEBUG=1`, the queue/latency counters print at 1 Hz.

**Protocol impact:** None intended. Packet IDs, field order, sizes, units, timestamps, and CSV
parser behavior are unchanged.

**Required hardware validation:** Compare buffered on/off captures from the same card and
workload. Parse both with `vertisea_plot_v7.py`; verify zero unknown/truncated packets and
expected packet counts. Compare IMU `interval_us`, current-block gaps, queue high-water,
`sdServiceMaxUs`, and overruns. Do not proceed to IOM DMA until this stage is byte-exact and
the queue remains bounded.

**First hardware A/B result — 2026-09-04:** `G:\09041438.BIN` was captured first with
buffering enabled (53.37 s), followed by `G:\09041440.BIN` with buffering disabled (38.36 s).
The current input floated, the IMUs remained still, and no Hall edges were generated; those
conditions are valid for evaluating storage integrity and timing.

- Both files consumed exactly to EOF with the maintained Python parser: zero unknown/truncated
  packets and zero parser errors. The buffered file contained 5228 raw-IMU records, 425 complete
  100-sample current blocks, 54 BME records, and 523 RPM records; the fallback contained
  3767/305/39/379 respectively. This verifies byte-exact packet assembly across sector and
  five-second flush boundaries for the packet types exercised.
- Mean IMU interval was **10189 us buffered (98.14 Hz)** versus **10155 us fallback
  (98.47 Hz)**. Median was 9574 versus 9571 us; >=11 ms share was 11.88% versus 12.27%; p99
  was 19.08 versus 20.03 ms. This short run therefore shows essentially unchanged central
  timing, a slightly better buffered long tail, and no defensible aggregate-rate gain.
- Current-block dead time improved in this sample: mean/median/p99 inter-block gap was
  **4.09/1/22 ms buffered** versus **6.44/3/43.19 ms fallback**. Because the ADC pin floated
  and run lengths differ, this is a scheduler/storage timing comparison only, not signal data.
- Hall/magnetometer absence is expected: no magnet was used, and `IMU_RAW_ONLY=1` deliberately
  emits `0x12` instead of processed IMU/magnetometer records. RPM records still appear with the
  cached zero value, which is normal.
- Queue high-water, maximum sector service time, and overrun counters were not captured because
  the committed deployment flags keep `USB_DEBUG=0`. A longer debug-enabled run is needed to
  prove the eight-sector queue remains bounded and to identify whether residual tails are card
  busy time or producer scheduling.

**Long debug-enabled validation — 2026-09-04:** `G:\09041502.BIN` ran for **733.27 s
(12.22 min)** with buffering enabled. The user observed **zero queue overruns** in the live
debug diagnostics. Independent binary scanning consumed all **4,355,687 bytes** exactly to EOF,
with no unknown/truncated record; the maintained parser's 72,039-row `_imuRaw.csv` matched every
binary `interval_us` value exactly. All 5,837 current blocks held 100 samples.

- IMU: **98.27 Hz** mean; median 9.570 ms; >=11 ms 11.80%; >=20 ms 0.60%; p99 18.624 ms.
- Current-block dead time: mean 4.59 ms, median 1 ms, p99 22 ms, max 55 ms — consistent with the
  short buffered run and materially better than the unbuffered A/B mean/median/p99 of
  6.44/3/43.19 ms.
- The queue is therefore proven adequate for this workload and Stage 1 is confirmed. The next
  step is Stage 2 preallocation/contiguous multi-block testing; direct IOM DMA should still wait
  until that separates FAT/command/card-busy costs from SPI payload-transfer cost.

---
## 2026-09-04 — Make every SD log filename unique before opening — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — logic and host-side filename cases validated; not yet compiled
with the Arduino toolchain or exercised on a physical SD card.

**Why:** `FILE_WRITE` appends when a filename already exists. Two paths could therefore join
independent boot sessions into one log: the invalid-RTC `LOGnnnnn.BIN` scan ran before
`SD.begin()`, and a valid RTC reset within the same minute reused `MMDDHHmm.BIN`. The latter
had already been observed as duplicate boot records plus a backward `ts_ms` jump.

**What changed:**

- Moved `SD.begin(CS_SD)` before every `SD.exists()` call.
- Use the human-readable minute-resolution name only when it is unused.
- On a same-minute collision or invalid RTC, scan for the first unused `LOG00001.BIN` through
  `LOG99999.BIN`.
- Removed the old last-resort overwrite of `LOG99999.BIN`; setup now halts if no safe name
  remains.
- Added comments explaining that these checks are required because `FILE_WRITE` appends.

**No protocol or log-content change:** Only file selection changed. Packet layouts, RTC event
contents, and the Python parser are unaffected.

**Verification required:** Test a blank card, a pre-existing same-minute date file, occupied
counter names, and the invalid-RTC path. Confirm every old file remains byte-identical and each
boot creates a new file.

---
## 2026-09-03 — Fix Issue 35: `TYPE_IMU_RAW` gyro widened to int32; filtered path untouched [CONFIRMED 2026-09-03]

**Why:** `TYPE_IMU_RAW`'s gyro fields were `int16`, on the assumption that
`sfe_ism_data_t` held raw LSB counts. It does not — the SparkFun driver scales it, and gyro
is in **mdps**. `int16` saturates at 32.767 dps while the buoy reaches ±243 dps, so all
three axes wrapped sign. See `IDENTIFIED_ISSUES.md` Issue 35.

**I rejected my own earlier recommendation.** Issue 35 originally proposed `int16` centi-dps
as *preferred*. That was wrong: it assumed ±250 dps full scale, but the firmware configures
**`ISM_500dps`**, so centi-dps clips at 327.67 dps — a smaller version of the same bug.
"True LSB counts" fails similarly: the divisor is tied to the FS setting, so raising FS to
1000 dps would silently reintroduce overflow. **`int32` mdps is the only option independent
of the full-scale setting**, so that is what was implemented. It costs +12 B/tick, and that
robustness is worth more than 12 bytes.

### What changed

**Struct** — renamed to state units, since "cnt_" is what caused the bug:

```cpp
int16_t mg_ax,   mg_ay,   mg_az;    // accelerometer, milli-g
int32_t mdps_gx, mdps_gy, mdps_gz;  // gyroscope, millidegrees per second
```

**Record** — payload 26 → 38 B (record 31 → 43 B), now written as one packed struct with a
`static_assert(sizeof(ImuRawRec) == 38)` so the layout cannot drift from the parsers
unnoticed. Format `'<3h3i3h3iH'`.

**Per-tick cost** — ~49 → ~61 B/tick, predicting a flush every ~8.4 ticks (vs 10.1 measured
at 49 B and 4.2 at 119 B). Expect a rate between the 92.6 Hz filtered and 98.9 Hz broken-raw
results, likely ~97 Hz.

**CSV columns now carry units** (`fix_gx_mdps`, `fix_ax_mg`, …) in both parsers, so a reader
assuming dps cannot be silently wrong by 1000×.

### The filtered path is provably unaffected — verified, not assumed

This was an explicit requirement, so it was checked mechanically rather than by inspection.
All 24 references to the raw fields occur in exactly four places: the struct declaration,
the populate block, the `TYPE_IMU_RAW` write, and the commented-out debug block.
**Zero references anywhere else.**

The reason it is structurally safe: `collectIMUData_ISM()` derives its physical values
*directly* from the driver output, never via the struct fields:

```cpp
float ax_g_raw   = -(accelData.xData - cal.accel_bias[0]) / cal.accel_scale[0];
float gx_dps_raw =  (gyroData.xData  - cal.gyro_bias[0])  * 0.001f;
```

So the `mg_*`/`mdps_*` fields are a pure **side channel** for raw logging. Confirmed that
the LPF (lines 928, 931), Madgwick (966, 976), the vertical integrator (1733) and telemetry
(1857–1861) reference none of them. A comment now records this at the assignment site, so
the invariant is documented where it could be broken.

**Regression tested:** `09031403` and `09031136` both still parse to 5908/5908/5908 and
8711/8711/8711 fixed/stab/mag with **0 errors** and unchanged record keys — identical to
before the change. The filtered SD records and telemetry are byte-for-byte unaffected.

### Verification of the new layout

Round-tripped with values that **specifically defeated the old encoding**:

| Field | Value | Result |
|-------|-------|--------|
| fixed gyro | +500000, −500000, 243600 mdps | exact |
| stab gyro | int32 max, int32 min, 17500 | exact |
| fixed accel | 4000, −4000, 1000 mg | exact |
| stab accel | −32768, 32767, 0 mg | exact |

±500000 mdps is the `ISM_500dps` full scale — the exact case the old `int16` could not
represent. Payload measured 38 B; 0 errors; CSV header and row correct.

**`09031405.BIN` no longer parses** (desyncs at offset 236 with "unknown packet type 0x5B").
This is intentional and better than the alternative: a 31-byte record read as 43 bytes
*must* fail loudly rather than silently produce plausible-looking garbage. That log's gyro
data was corrupt regardless; its accel columns and rate measurements remain valid in the
records already extracted.

**Not compile-checked** (no `arduino-cli`). Brace/paren balance verified; `py_compile`
passes; MATLAB unexecuted. The MATLAB `case` needed four separate `fread` calls because a
single mixed-type read is not possible — that is the one place where the asymmetric widths
cost readability.

### Verified on hardware — `09031435.BIN` (63.79 s, 6222 records)

**Gyro fix proven.** Values now span **±573.4 dps** where the old `int16` capped at
±32.767 dps — a 17.5× increase in representable range, with no sign wrapping. Between 27%
and 34% of samples per axis exceed the old ceiling, so this run would have been almost
entirely corrupt under the previous encoding.

**Rate lands where predicted.** 60.8 B/tick measured against ~61 predicted, giving
**97.54 Hz**:

| Log | Config | B/tick | Predicted flush | Observed | Rate |
|-----|--------|--------|-----------------|----------|------|
| `09031403` | filtered | 119.3 | 4.29 ticks | 4.22 | 92.63 Hz |
| `09031405` | raw, int16 (broken) | 49.0 | 10.45 ticks | 10.05 | 98.91 Hz |
| `09031435` | **raw, int32 (fixed)** | **60.8** | **8.43 ticks** | **8.16** | **97.54 Hz** |

The flush-spacing model has now predicted three independent configurations within 2–4%.
The +12 B/tick cost of `int32` bought back 1.37 Hz — a fair price for gyro data that is
actually usable. ≥11 ms share 12.26%, on-time band 87.74%, stdev 2641 μs. Current sampling
799.5 Hz aggregate / 846.2 Hz within-block.

**Both IMUs confirmed present and independently valid in the single record.** The 43-byte
record carries both, so one `_imuRaw.csv` with 14 columns replaces the previous
`_imuFixed.csv` + `_imuStab.csv` + `_mag.csv`:

- 6 `fix_*` and 6 `stab_*` columns present.
- **Zero of 6222 rows** have identical fixed/stab accel triples — genuinely two sensors,
  not one duplicated.
- Reconstructing ∣accel∣ with each IMU's own cal record: **fixed 0.9981 g, stab 0.9957 g**
  (both should read 1 g at rest) — each is independently physically correct.
- Gyro correlation between the two IMUs is +0.749/+0.811/+0.941 (x/y/z): high, as expected
  for rigidly coupled sensors on one hull, but not 1.0, which is also expected given
  differing orientation and damping.
- 6222 rows, 6222 unique monotonic timestamps — one timestamp per record means the two
  IMUs are **inherently time-aligned**, an improvement on the old scheme where they had to
  be joined on `ts_ms` across two files.

**A separate pre-existing limit surfaced:** the gyro maxima sit at *exactly* 573370 mdps,
which is the sensor's own register rail (32767 × 17.5 mdps/LSB at `ISM_500dps`). The 17/18
mdps steps between adjacent distinct values confirm that sensitivity. **0.10% of gyro
samples are clipped by the configured full scale**, which no logging change can recover.
Recorded in Issue 35; not altered, since 0.10% on a bench shake test may be irrelevant in
water, but worth re-checking against real wave motion.

---

## 2026-09-03 — Retire TYPE_CURRENT (0x0A); add IMU_RAW_ONLY + TYPE_IMU_RAW (0x12) [CONFIRMED 2026-09-03]

Both changes serve one goal: cut bytes written per IMU tick, because the 512-byte SD
block flush is the dominant reason the IMU loop reaches ~93 Hz instead of 104 Hz
(`IDENTIFIED_ISSUES.md` Issue 34, fix 2).

### Part 1 — TYPE_CURRENT (0x0A) retired

**Why:** it was a *biased* estimator, not merely a redundant one. Its payload was a single
point sample of `currentCounts` taken at the 5 Hz telemetry tick, and the harvested-current
signal is bursty, so the sample aliased: measured mean **682 counts vs 325** for the
full-rate `0x0E` stream over the same run (2.1× high). Keeping a channel that silently
reads 2.1× high is worse than having no channel, since `0x0E` already logs every sample.

**Removed from `VertiSea.ino`:** the `TYPE_CURRENT` enum entry, the `CurrentPacket` struct,
the per-tick mA derivation (`v_sense`/`i_mA`), the `current_mA` static, the radio
`TELEM_WRITE(curPkt)`, and the 5 Hz SD write. The enum slot carries a comment recording
why and warning **not to reuse 0x0A** — existing logs still contain it.

**Kept:** `currentCounts` (still used for status/debug), and both parsers' read paths, so
pre-existing logs still convert. Newer logs simply produce no `_current.csv`.

**Ground station:** the System Status "Current:" field lost its data source with the radio
packet gone, so it is now derived from `TYPE_CURRENT_STATS` (0x0F) as `charge_mC / integ_s`
and **labelled "mA avg"**. This is an unbiased window average rather than a point sample;
the label change is deliberate so it is not misread as instantaneous.

### Part 2 — `IMU_RAW_ONLY` flag + `TYPE_IMU_RAW` (0x12)

**Default is `IMU_RAW_ONLY 0`** — existing behaviour is unchanged unless the flag is set.

With the flag at 1 the IMU block writes one 31-byte record (5 B header + 12×`int16` raw
counts + `uint16 interval_us`) instead of 43 + 43 + 17 = 103 bytes of
`TYPE_FIXED_IMU` / `TYPE_STAB_IMU` / `TYPE_MAG`. Per-tick SD traffic drops from ~108 B to
~31 B, moving the 512-byte block flush from every ~4.7 ticks to every ~17.

**Correcting an earlier rationale of mine:** I had originally justified this flag partly on
CPU savings. That was wrong. Madgwick + the LPF together measure only **~46 μs per tick**,
so skipping them saves almost nothing in time. The entire value is **SD bandwidth**. The
code comment and `POTENTIAL_UPGRADES.md` U19 both now say so explicitly, so the flag is not
re-justified on false grounds later.

**Trade-off, stated in the flag comment:** an `IMU_RAW_ONLY` log has **no on-board attitude
and no magnetometer record**. Attitude must be recomputed offline from the raw counts using
the boot-time `TYPE_FIXED_CAL` / `TYPE_STAB_CAL` / `TYPE_LPF_CAL` records, which are still
written. Madgwick still runs every tick, so radio `TYPE_TELEM_IMU` still carries live
attitude and `vertDisp` — only the SD copy is dropped.

**Not** reusing the existing `IMUData.cnt_*` fields would have meant re-reading the sensor;
they were already populated, so the raw path costs nothing extra.

### Verification

Python parser exercised against both a real log and a synthetic one:

- **Regression, `09031136.BIN`:** 8711 `fixed_imu` / 8711 `stab_imu` / 8711 `mag` /
  64900 `current_fast` / 466 `current` / 49 `hall_edge`, **0 errors** — byte-identical
  counts to before the change, and `imu_raw` correctly 0. Retiring 0x0A did not break
  reading of logs that contain it.
- **Synthetic `IMU_RAW_ONLY` log:** record measured 31 B as designed; both records parsed;
  **all 12 int16 values round-tripped exactly**, including the extremes −32768 and 32767
  (confirming signed `<12hH` unpacking, where an unsigned format would have silently
  corrupted negatives); `interval_us` and `ts_ms` correct; 0 errors.
- **CSV writer:** emits `_imuRaw.csv` with the 14-column header and correct rows; the real
  log still emits its usual 13 files and no `_imuRaw.csv`.

A `data['imu_raw']` key was missing from the parser's dict initialiser on the first attempt
— it would have raised `KeyError` on the first 0x12 record. Caught by the synthetic test,
which is precisely why the synthetic log was built rather than waiting for hardware.

**Not compile-checked** (no `arduino-cli`). Brace/paren balance verified; the `#if/#else/#endif`
structure was read back in full to confirm both branches are well-formed. `py_compile`
passes on the ground station. MATLAB changes are unexecuted — no MATLAB in this environment.

**Expected effect:** with `IMU_RAW_ONLY 0` (committed default) the only rate change comes
from dropping 0x0A, which is small. The real test is a run with `IMU_RAW_ONLY 1`, which
should approach the 104.49 Hz ceiling measured earlier.

### Verified on hardware 2026-09-03 — two runs, `09031403` (flag 0) and `09031405` (flag 1)

Both logs parse to completion with **no unknown types and zero errors**. `09031403` contains
imuFixed/imuStab/mag; `09031405` contains imuRaw and **no** imuFixed/imuStab/mag, exactly as
the flag intends. **Neither log contains `_current.csv`**, confirming 0x0A is fully retired
on the write side while both parsers still read older logs that have it.

| Log | Config | B/tick | Rate | Mean interval | ≥11 ms | Current Hz |
|-----|--------|--------|------|---------------|--------|------------|
| `09031136` | 0x0A live | 119.3 | 92.79 Hz | 10777 μs | 23.71% | 691 |
| `09031403` | flag 0, 0x0A retired | 119.3 | 92.63 Hz | 10795 μs | 23.70% | 692 |
| `09031405` | **flag 1** | **49.0** | **98.91 Hz** | **10110 μs** | **9.96%** | **822** |

**Retiring 0x0A alone changed nothing measurable** (92.79 → 92.63 Hz, within run-to-run
noise). That is a useful negative result: at 5 Hz the packet was only ~0.4 B/tick amortised,
far too little to shift a 512-byte boundary. The earlier estimate of "7 B/tick" was wrong —
it was the packet size, not its per-tick cost.

**`IMU_RAW_ONLY 1` delivered the rate gain: 92.6 → 98.91 Hz (+6.8%)**, and the mechanism is
confirmed rather than merely correlated. The ≥11 ms share fell from 23.70% to 9.96%, the
on-time band rose from 76.30% to 90.04%, and stdev dropped from 3330 to 2454 μs. Most
tellingly, the **block-flush spacing prediction held**:

| Log | B/tick | Predicted flush every | Observed mean spacing | Mode |
|-----|--------|----------------------|----------------------|------|
| `09031403` | 119.3 | 4.29 ticks | **4.22 ticks** | 5 (662×), 4 (438×), 3 (269×) |
| `09031405` | 49.0 | 10.45 ticks | **10.05 ticks** | 10 (182×), 11 (128×), 9 (96×) |

Predicted and observed agree within 2–4% across a 2.4× change in bytes per tick. The
512-byte SD block flush is now a **confirmed** cause, not a hypothesis.

Current sampling also rose 692 → 822 Hz aggregate (846 Hz within-block), consistent with the
sampler absorbing freed loop time as established previously.

**Residual gap:** 98.91 Hz against the 104.47 Hz ideal. The remaining ≥11 ms events are
~10% of ticks and still cost 5.3% of elapsed time, so a further byte reduction or write
buffering would be needed to close it. Diminishing returns — the large win is taken.

### ⚠ A defect was found in this change: see `IDENTIFIED_ISSUES.md` Issue 35

Validating the raw data physically (not just structurally) revealed that
**`TYPE_IMU_RAW`'s gyro columns overflow `int16`**. `sfe_ism_data_t` holds *scaled* values,
not LSB counts — gyro is in **mdps**, so `int16` saturates at 32.767 dps while the buoy
reaches ±243 dps. All three gyro axes press against both rails and wrap sign.

The **accelerometer columns are correct** (milli-g, ±32.7 g range): reconstructing ∣accel∣
from the raw columns with the logged `calFixed` gives a median of **0.9973 g**.

So the rate result above stands — it depends only on record *size* — but
`IMU_RAW_ONLY 1` is **not yet fit for deployment**, because recomputing attitude offline is
its whole purpose and the gyro is the input that matters most for that. Keep the committed
default at `IMU_RAW_ONLY 0` until Issue 35 is fixed.

This is also a lesson about the earlier synthetic test: it round-tripped arbitrary `int16`
values successfully, which proved the *transport* was correct but could not reveal that the
*source values do not fit* the chosen type. Range/plausibility checks against real sensor
data caught what a round-trip test structurally could not.

---

## 2026-09-03 — Use the measured sample interval for Madgwick and the vertical integrator [CONFIRMED 2026-09-03]

**Why:** the firmware assumed a fixed dt of 1/104 s = 9.615 ms in three places, but the
loop has never actually achieved 104 Hz. Measured rates: 57.17 Hz (`04030825`),
88.94 Hz (`09021931`), 92.75 Hz (`09031050`, after I²C 400 kHz). That is a **+12% dt error
today and +82% in April**, and it lands on the wave-height critical path: Madgwick's gain
scales with dt, and the accel→velocity→displacement double integration compounds it.
See `IDENTIFIED_ISSUES.md` Issue 34.

**What changed:**

1. `collectIMUData_ISM()` gained a `float dtSec` parameter and now calls
   `filt.begin(1.0f / dtSec)` at the top of each invocation, before the Madgwick update.
2. `loop()` derives `dtActual` from the existing `imuDeltaUs` (the same measured delta
   already logged as `interval_us`), guarded to `0 < delta < 500000` μs with a fallback to
   the nominal period.
3. The `dt` local in `loop()` was renamed `dtNominal` so nothing silently keeps treating
   the nominal value as the integration step.
4. `vertVel`/`vertDisp` integration now uses `dtActual`.
5. The `setup()` `filterX.begin(IMU_RATE_HZ)` calls are retained as seed values and
   commented as such.

**Why calling `begin()` per update is safe (the load-bearing assumption):**
`Madgwick::begin()` is an inline one-liner in `Madgwick/src/MadgwickAHRS.h`:
`void begin(float sampleFrequency) { invSampleFreq = 1.0f / sampleFrequency; }`. It touches
**only** `invSampleFreq`. The quaternion `q0..q3`, `beta` and `anglesComputed` are set
exclusively in the constructor (`MadgwickAHRS.cpp` lines 38–46). So `begin()` retunes dt
without resetting filter state. `invSampleFreq` is private, which is why `begin()` is the
access route rather than assigning the field directly. Verified against the vendored copy,
which per `AGENTS.md` takes precedence over any global Arduino install.

**Bonus fix — the drift leak was also rate-dependent.** The leak was a fixed per-sample
factor `vertVel *= 0.9995f`, documented as τ ≈ 19.2 s — but τ = dt/(1-0.9995), so that
only holds at exactly 104 Hz. Since the loop runs *slower*, dt is *larger* and τ came out
**longer** than intended: **21.6 s at the measured 93 Hz and 35.0 s in the April 57 Hz
logs** (verified against `09031136`: mean dt 10.777 ms → τ = 21.55 s). The practical effect
is the opposite of a passband problem — the high-pass leaked *more slowly* than documented,
so it suppressed long-period drift *less* aggressively than intended, and the corner
drifted with loop load. Now expressed as a time constant: `leak = 1.0f - (dtActual / VERT_LEAK_TAU_S)` with `VERT_LEAK_TAU_S = 19.2f`.
This is the first-order expansion of `exp(-dt/tau)`, accurate to <0.02% for dt/tau << 1,
and avoids a per-sample `expf()`. The leak constants are still empirical and still must
not be removed (see `AGENTS.md`); this change only makes τ mean what it claims.

**Deliberately NOT changed:** the LPF `alpha_acc/gyro/mag` coefficients in `setup()` still
derive from the nominal `IMU_RATE_HZ`. Making them per-sample would (a) cost a division
per axis per tick, and (b) break the offline LPF inversion documented for `TYPE_LPF_CAL`
(`0x10`), which needs one fixed alpha per run to be invertible. The cutoff error is a
second-order effect on a smoothing filter, unlike the dt error in an integrator. Revisit
only if the achieved rate becomes wildly variable.

**Packet layout is unchanged** — `interval_us` was already being logged, so no parser or
`binary_protocol.md` change is needed. Existing logs remain readable.

**Not yet compile-checked** (no `arduino-cli` in this environment) and not yet run on
hardware. Brace/paren balance verified and all five edit anchors matched exactly once.

**Expected on-hardware effect:** attitude should be better damped and `vertDisp` should
drift less, especially during the SD-write stalls where dt spikes to 30–70 ms — those
ticks previously fed the filter a 3–7× understated dt. Rate itself will **not** change;
that is the separate byte-reduction work (Issue 34 fix 2).

### Verified on hardware — `09031136.BIN` (2026-09-03, 93.97 s, 8711 IMU samples)

The log parses cleanly (1041657/1041657 bytes consumed, no unknown types), so the new
signature and the 43-byte packet layout are intact, and there are **zero NaN** pitch/roll.

**Direct evidence the filter now honours dt.** Median per-tick attitude change
`|Δ(pitch,roll)|`, split by whether that tick was on time or a stall:

| | on-time (<10 ms) | stall (≥15 ms) | ratio |
|---|---|---|---|
| `09031050` nominal dt | 0.55344° | 0.55372° | **1.001** |
| `09031136` measured dt | 0.54781° | 1.05380° | **1.924** |

This is the signature of the bug and of the fix. With a hard-coded dt the filter advanced
by the *same* amount whether 9.6 ms or 20 ms of real time had passed — ratio 1.001, the
filter was blind to elapsed time. With measured dt a stall tick now advances ~1.92× as far,
against an interval ratio of ~1.57–2.0. Attitude is now integrated in real time rather
than in "ticks".

Rate is unchanged as predicted: **92.70 Hz** vs 92.75 Hz, mean interval 10777 μs, median
9570 μs, 76.29% of ticks on time — statistically identical to the previous run, confirming
the per-update `begin()` call costs nothing measurable (it is one float division). Current
sampling likewise unchanged at 690.6 Hz aggregate / 767.4 Hz within-block.

**Correction found during verification.** The original entry claimed the old fixed leak
gave τ = 17.2 s at 93 Hz and 11.4 s at 57 Hz. That was the wrong direction:
τ = dt/(1−0.9995), so a *larger* dt yields a *longer* τ. Correct values are **21.55 s at
93 Hz** (verified: mean dt 10.777 ms) and **34.99 s at 57 Hz**. The old leak therefore
suppressed drift *less* aggressively than documented, not more. The fix and its rationale
stand — τ is now 19.2 s by construction — but the description of the old behaviour has been
corrected in both this entry and the code comment.

Offline re-integration of `vertDisp` over this log (bench run, so the absolute value is
drift rather than wave height) gives −15.56 m nominal vs −15.77 m measured-dt, peak 15.57 m
vs 16.22 m — a 4.2% difference in peak, confirming the integrator path changed materially.
A meaningful accuracy check needs real wave motion with an independent reference.

---

## 2026-09-02 — I²C bus to 400 kHz; log the measured IMU interval — [CONFIRMED 2026-09-03]

**Status:** `[CONFIRMED 2026-09-03]` — later hardware logs measured the 400 kHz path and
recorded `interval_us`; the results are documented below and in Issue 34.

**Why:** the IMU has never actually achieved its nominal 104 Hz. Measured effective rates were
**57.2 Hz** in the April deployment (`04030825`) and **88.9 Hz** in the 2026-09-02 bench run
(`09021931`). Analysis of the I²C transaction budget identified the cause.

**Root cause — the bus was running at the Arduino default 100 kHz.** `Wire.begin()` was called
with no `setClock()`. Each IMU tick performs 6 I²C transactions (2× `checkStatus`,
2× `getAccel` 6 B, 2× `getGyro` 6 B):

| Bus speed | Both IMUs | Share of a 9615 µs tick | I²C-bound rate ceiling |
|---|---|---|---|
| 100 kHz (was) | ~4200 µs | 44% | ~238 Hz |
| **400 kHz (now)** | **~1050 µs** | **11%** | **~952 Hz** |

4200 µs of I²C per tick against a measured ~2.7 ms loop period explains the shortfall: the IMU
gate can only fire on a loop boundary, so 9615 µs quantised to 4 passes × 2.7 ms = 10.8 ms
→ ~92 Hz, which matches the observed 88.9 Hz almost exactly.

For scale, the things that were *not* the problem: the SD write is ~396 µs, and Madgwick +
LPF for both IMUs is only **~46 µs**. Madgwick is roughly 1% of the I²C cost — which is why
the previously-considered "raw-only logging to save CPU" would not have helped the rate.

**Change 1: `Wire.setClock(400000)`.** Placed immediately after `Wire.begin()` and
**before** the 250 ms settling delay and every device `.begin()`, so each device is probed at
the final bus speed rather than enumerating at 100 kHz and being switched underneath it.

All bus devices were verified against their datasheets before changing this:

| Device | Max I²C |
|---|---|
| ISM330DHCX ×2 | 400 kHz fast mode **and** 1 MHz fast-mode-plus |
| MMC5983MA | 400 kHz fast mode |
| RV-8803-C7 | 400 kHz |
| BME280 | Standard, Fast and High-Speed |

400 kHz was chosen over 1 MHz deliberately as the safe first step; 1 MHz is available if
400 kHz proves clean and more headroom is wanted later.

**Change 2: log the measured IMU interval.** New `uint16_t interval_us` field in `IMUData`,
captured in `loop()` **before** `lastImuUs` is advanced, and appended to both
`TYPE_FIXED_IMU` and `TYPE_STAB_IMU`.

This exists because the 104 Hz shortfall was invisible: nothing in the log reported the
achieved rate, so it could only be discovered by post-hoc differencing of record timestamps.
Recording the interval makes the rate a first-class observable. Clamped to `uint16` (max
65.535 ms) and reports 0 on the first sample after boot, which has no predecessor.

**⚠ Packet layout change — `TYPE_FIXED_IMU` / `TYPE_STAB_IMU` grow 41 → 43 bytes.** Per the
user's instruction that nothing needs backward compatibility, no legacy branch was added.
Both parsers were updated in the same change:
- `vertisea_plot_v7.py`: `_SD_PAYLOAD_BYTES` 36 → 38, unpack `'<9fH'`, `interval_us` added to
  both `_imu_fields` tuples.
- `parse_vertisea_log_v4.m`: `knownPayloadBytes` 36 → 38, reads 9 singles then a `uint16`,
  `headers.imuFixed` gains `interval_us`.

**Logs written before this change will not parse with the updated parsers**, and vice versa.
That is accepted and intentional.

**Projected effect (a hypothesis to measure, not a prediction).** First-order estimate: loop
period ~2700 → ~1943 µs, gate quantising to 5 passes × 1943 = 9714 µs → **~102.9 Hz**.

I have now been wrong twice on rate predictions this session (1 kHz current sampling, then the
400 Hz request that measured *worse* at 163 Hz), so this figure is stated as an expectation to
be checked rather than a result. The old log's 46 ms outliers prove the loop is not uniform,
which the model does not capture.

**How to verify (do this before confirming):**
1. Flash with `USB_DEBUG 1` for the first run so any I²C init failure is immediately visible.
   A 400 kHz problem would appear as a device `.begin()` failure at boot, or as stale/garbage
   IMU reads.
2. Record ~30 s, then check the `interval_us` column of `<base>_imuFixed.csv`.
3. Success looks like: mean interval moving from 11.24 ms toward **~9.6 ms**, and the fraction
   of intervals ≥ 19 ms falling from 1.56% toward ~0%.
4. If the bus proves marginal, revert to `Wire.setClock(100000)` — the interval logging is
   independent and worth keeping either way.

**Deliberately NOT done in this change:**
- **Interrupt-driven IMU sampling.** The bottleneck is the cooperative loop, not interrupt
  latency. An ISR cannot perform I²C reads plus Madgwick, so work would still defer to the
  loop; interrupts would reduce jitter, not raise the rate.
- **Raising `IMU_RATE_HZ` or the sensor ODR.** Both remain at 104 Hz by the user's decision:
  prove a genuine 104 Hz first, then consider more. Raising the poll rate without also raising
  the ODR would just re-read the same sample.
- **Measured `dt` into Madgwick and the integrators.** Still outstanding and still important —
  see the separate `IDENTIFIED_ISSUES.md` entry. Deferred so this bus change can be measured in
  isolation rather than confounded with a numerical change to the attitude pipeline.
- **Retiring `TYPE_CURRENT` (0x0A)** and the `IMU_RAW_ONLY` flag — both agreed, both pending.

**Verification performed (host-side only):** a synthetic log containing 43-byte IMU records
round-tripped through the Python parser with zero errors; `interval_us` recovered exactly
(9615 → 104.00 Hz), and `TYPE_MAG` / `TYPE_CURRENT_BLOCK` / `TYPE_CURRENT_CAL` continued to
parse, confirming byte accounting is still exact. `<base>_imuFixed.csv` gained the
`interval_us` column. The MATLAB parser was **not** run (no MATLAB available) and the firmware
was **not** compiled.

---
## 2026-09-02 — Revert `CURRENT_RATE_HZ` to 1000 after 400 Hz measured *worse*; phase-advance the sample gate — [CONFIRMED 2026-09-03]

**Status:** `[CONFIRMED 2026-09-03]` — later hardware logs verified the restored 1000 Hz
over-request and phase-advanced gate; achieved rate subsequently rose further after unrelated
loop-time reductions.

**What happened:** `CURRENT_RATE_HZ` was set to 400 to make the dropped-sample counter
meaningful (a 1000 Hz request produced ~31,000 drops purely from request/reality mismatch).
Log `09021858.BIN` shows this **backfired badly**: effective rate fell from **373 Hz to
163 Hz**, and block spans grew from ~265 ms to ~607 ms. Reverted to 1000.

**Why requesting a lower rate produced a lower rate — the counter-intuitive part.** A sample
can only be taken once per `loop()` pass, because `nowUs` is captured once per pass. With a
~2.7 ms loop period:

- **1000 µs interval** (1000 Hz request): every pass exceeds the threshold, so the gate fires
  every pass and the *loop* sets the rate → ~373 Hz.
- **2500 µs interval** (400 Hz request): a pass arriving at 2.6 ms fires and reset the phase
  to `nowUs`; the next pass at ~5.3 ms elapsed frequently fell just short of 2500 µs from the
  new reference and had to wait a third pass. The result is a beat between the loop period and
  the requested interval.

My simulation reproduced the direction of this (2500 µs + jitter → 250–270 Hz) but **could not
reach the observed 163 Hz**, bottoming out near 239 Hz even at ±90% jitter. So the real loop
period is not the near-constant ~2.7 ms I assumed — it is likely bimodal (short passes plus
periodic long ones from SD writes and the 104 Hz IMU block). **This is a gap in my model,
recorded honestly:** the lesson is to trust the measured effective rate over any predicted
one.

**Gate change (kept, as insurance):** `lastCurrentUs` now advances by whole intervals
(`+= n * CURRENT_INTERVAL_US`) rather than snapping to `nowUs`, with a resync if more than
8 intervals behind. At the reverted 1000 µs interval this is a no-op — the gate fires every
pass regardless — but it removes the beat failure mode should the rate ever be raised toward
the loop rate again.

**Related fix — integration now uses a separate sample-to-sample delta.** Because the phase
accumulator no longer tracks real time, `elapsedUs` (phase-relative) would have been the wrong
`dt`. Added a `lastSampleUs` static so ∫I dt / ∫I² dt use the true wall interval between
consecutive samples. Without this, the phase-advance change would have silently corrupted the
integrals — the same class of bug fixed earlier today.

**Consequence accepted:** `n_dropped` will again read large (~600/s) because 1000 Hz is a
deliberate over-request. The comment now states plainly that this represents the
request/reality gap and **not** data loss, and directs the reader to judge sampling health
from the effective rate (`span_ms`, or `n_samples/window_s`) instead. Making the counter
"clean" is not worth a 2.3× loss of real sample rate.

**Also corrected:** the `TELEM_ENABLE` comment now records that the Artemis Nano has only
**one USB connector**, shared between the native USB CDC and the CH340E — so USB telemetry is
a bench/debug convenience and field runs use the RFD900 radio. This matters for the
GUI-reset issue (see `docs/CHANGELOG_vertisea_plot_v7.py.md`).

**Evidence from `09021858.BIN` (2 sessions, 732,879 bytes, all consumed, zero unknown types):**

| | Session 1 | Session 2 |
|---|---|---|
| Duration | 19.0 s | 59.4 s |
| Effective rate | 162.9 Hz | 163.0 Hz |
| span_ms mean | 607.6 | 607.5 |
| Peak counts | 4166 (50.9 mA) | 4498 (54.9 mA) |
| At clip (16383) | 0 | 0 |
| Hall edges | 0 | **50** |

**Confirmed working this run:** `RPM_MAX_EXPECTED 3000` — the hand-waved magnet produced
50 edges and RPM up to **484**, with **0 of 49 periods rejected** by the 20,000 µs threshold.
The old 450 RPM cap would have discarded the 484 reading. `TYPE_HALL_EDGE` and the
single-magnet tangential-pass mechanism both validated on hardware.

**Still open:** no clipping yet (peak 27% of full scale), so `CURRENT_DIV_RATIO` stays at 1.0
pending a real discharge.

---
## 2026-09-02 — `CURRENT_RATE_HZ` 1000 → 400; comments corrected to match — `[REVERTED 2026-09-03]`

**Status:** `[REVERTED 2026-09-03]` — hardware log `09021858.BIN` showed the 400 Hz request
reduced achieved sampling from about 373 Hz to 163 Hz. The later confirmed entry above
restored 1000 Hz and phase-advanced the gate. Entry retained as a recorded dead end.

**What changed:** the user set `CURRENT_RATE_HZ` from 1000 to **400**. I verified the
consequences and corrected the surrounding comments, several of which still asserted 1 kHz as
current fact.

**Why 400 is the right number:**
- `1000000 / 400 = 2500 µs` exactly — no integer-division truncation in
  `CURRENT_INTERVAL_US`.
- Measured throughput was **373–374 Hz** (from the `span_ms` field of a real log), so 400 is
  just above what the loop actually delivers.
- Empirically sufficient: decimating a 20 kHz scope capture of a real discharge to ~377 Hz
  reproduced peak within −0.60%, ∫I·dt within −0.12%, ∫I²·dt within −0.35%.

**The point of the change — making the drop counter meaningful.** At a 1000 Hz request the
counter read ~5,513 (9 s) and ~31,296 (49 s) purely because of the request/reality mismatch,
which buried any real signal. At 400 Hz the normal ~2.68 ms interval sits below the
`2 × CURRENT_INTERVAL_US` = 5000 µs drop threshold, so ordinary ticks no longer count.

**Prediction to check against the next log:** the counter will be **small but not zero**.
Inter-block gaps from SD flushes still exceed the threshold — an 8 ms gap counts 2 ticks, a
17 ms gap 5, and the 44 ms outlier observed earlier would count 16. Expect roughly
**100–300 per minute**, and treat a sudden jump as a genuine anomaly. If it reads exactly 0,
that is also fine — it would mean the flush stalls are shorter than 5 ms.

**Side effects:**
- Block cadence: 100 samples now spans **250 ms** (was ~268 ms at the achieved rate), so
  4.0 blocks/s.
- SD load: current channel 836 B/s, total ~**10.9 kB/s** (down from ~12.1 kB/s).
- Stats accumulator: a 2-minute window is now ~48,000 samples rather than ~120,000. Still far
  beyond float32's ~7 significant digits, so the `double` accumulators remain necessary.

**Comment corrections (these were wrong, not merely stale):**
- The `TYPE_CURRENT_BLOCK` doc block still described the payload as
  `uint16 sample_rate_hz`. It has been `uint16 span_ms` since the measured-dt fix — a reader
  implementing a parser from that comment would have produced wrong timestamps. Now documents
  the measured-span semantics and how to recover the effective rate.
- Header packet list, radio-bandwidth note, `TELEM_ENABLE` rationale, the in-loop sampling
  comment, and the accumulator-precision note all updated from 1 kHz to reflect 400 Hz.
- References to the historical 1000 Hz request are retained *where they explain a past bug*
  (e.g. the 2.65× integral understatement), since removing them would erase the reasoning.
- `vertisea_plot_v7.py` docstring for `current_fast` updated from "typically 1 kHz" and now
  notes timestamps come from the block's measured `span_ms`.

**Not changed:** `CURRENT_BLOCK_LEN` stays at 100. At 400 Hz that is 250 ms per block, which
keeps the record at 209 bytes and the header overhead negligible.

---
## 2026-09-02 — Raise RPM ceiling to 3000, fix pulse-overwrite bug, log raw Hall edges (0x11) and LPF cal (0x10) — `[PARTIALLY CONFIRMED 2026-09-02]`

**Status — deliberately split, because the firmware and the *sensor choice* are different
questions:**

- **`TYPE_LPF_CAL` (0x10): `[CONFIRMED 2026-09-02]`** — present and correct in three hardware
  logs, α values exactly as computed.
- **`TYPE_HALL_EDGE` (0x11) plumbing: `[CONFIRMED 2026-09-02]`** — edges are captured,
  batched, logged, and parsed; `<base>_hallEdge.csv` produced with derived periods and RPM.
- **RPM ceiling / `RPM_MAX_EXPECTED 3000`: `[CONFIRMED 2026-09-02]`** — a hand-waved magnet
  produced RPM up to 484 with **0 of 49 periods rejected**. The old 450 RPM cap would have
  discarded that reading, so the fix demonstrably removed the blocker.
- **Pulse-overwrite fix: `[UNCONFIRMED]`** — cannot be exercised by hand-waving. It only
  matters when two edges arrive inside one `loop()` pass (~2.7 ms), i.e. above ~20,000 RPM with
  one magnet, or during a loop stall. Needs a real spinning rotor.
- **⚠ Sensor SUITABILITY (US1881 latching): `[UNCONFIRMED — SEE CONCERN BELOW]`**

**⚠ Open concern: the latching sensor may be the wrong choice.**

The user reports hand-waving is **sometimes inconsistent**, and is right not to sign this off.
Reviewing the two runs that captured edges:

| Run | Edges | Notes |
|---|---|---|
| `09021858` | 50 | periods 124 ms … 13.75 s |
| `09021931` | 8 | periods 693 ms … 10.36 s |

Diagnostics found **no bounce** (zero intervals < 20 ms) and **no 2:1 alternation** in
consecutive period ratios, so there is no positive evidence of the latch failing to reset.
But hand-waving cannot distinguish "sensor is fine" from "sensor is marginal": the wave speed,
distance, and magnet orientation all vary per pass, so a missed toggle is indistinguishable
from a slow wave. **The absence of evidence here is not evidence of absence.**

**Why this is a genuine design question, not just a test artefact.** The US1881 is a *latch*:
it holds state until it sees a field **reversal**. A single magnet works only because a
tangentially passing magnet presents a bipolar signature — the trailing return-flux lobe
resets the latch (see the `PULSES_PER_REV` comment). That reset depends on the *geometry* of
the installation: air gap, magnet size, and how squarely the magnet sweeps past the face. If
the trailing lobe is too weak at the final mounted geometry, the latch will not reset and
edges will be **silently dropped** — RPM reads low or zero with no error indication.

A **non-latching unipolar switch** (e.g. A3144, or the A1220 which behaves switch-like) releases
on field *removal* rather than reversal, so it is inherently robust to this. That is very
likely the better choice for single-magnet tachometry, and it was probably the wrong call to
recommend a latch originally. Recorded so the decision can be revisited on evidence rather
than assumption.

**How to test properly (do this before confirming):**
1. Mount the magnet in its final geometry and spin the rotor at a **known, steady** speed.
2. Compare the edge count in `<base>_hallEdge.csv` against expected revolutions. Any shortfall
   is a missed toggle — the exact failure mode a latch is prone to.
3. Check the derived RPM against an independent measure (strobe, or video frame count).
4. If edges are missing, swap to a non-latching switch before tuning anything in firmware.
   No firmware change can recover an edge the sensor never emitted.

The rest of the original entry below remains accurate.

---

**Context:** the harvester spins to ~2000 RPM with one magnet at 30 mm radius, and the
spring discharge lasts ~12 s (confirmed from scope capture `scope_465`/`466`, 20 kHz record).

**1. RPM ceiling raised — this was a hard blocker.**
The debounce rejected any period < 133,333 µs, i.e. **450 RPM**. At 2000 RPM the period is
30,000 µs, so **every genuine pulse was discarded** and RPM would have read zero. That
threshold was inherited from a different, slower device. Replaced with
`RPM_MAX_EXPECTED 3000` (user-chosen) and a derived `RPM_MIN_PERIOD_US` (20,000 µs), leaving
1.5× margin below the real signal. The history is recorded in the comment so the value is not
"cleaned up" back to something arbitrary later.

Also added `PULSES_PER_REV` (currently 1) and folded it into both the threshold derivation
and the RPM formula, so adding magnets does not silently halve the effective ceiling.

**2. Pulse-overwrite bug fixed.**
`hallNewPulse` was a `volatile bool` and `hallPulseUs` a single slot. If two edges arrived
between `loop()` iterations, the older was overwritten and lost, the measured period spanned
two revolutions, and RPM reported **exactly half the truth with no error indication**. Now
`hallPulseCount` is a monotonic counter: `loop()` computes a period only when exactly one
edge has arrived, and otherwise re-anchors and waits for a clean interval. Silence beats a
plausible-looking wrong number.

**3. `TYPE_HALL_EDGE = 0x11` — raw edge timestamps (SD only).**
ISR now pushes `micros()` into a 32-slot ring buffer; `loop()` drains it and writes
`uint8 count` + `count × uint32`. Variable length, ~133 B/s at 2000 RPM.

Rationale: with one magnet the whole 12 s discharge is only ~200 edges, and the 5 Hz
`TYPE_RPM` channel decimates that to ~60 samples. Logging raw edges preserves the complete
timing record, so RPM can be re-derived offline, glitches rejected with hindsight, and the
spin-up curve fitted — none of which is possible from a decimated value. Same "log raw,
derive later" pattern as `TYPE_CURRENT_BLOCK`. The existing 5 Hz `TYPE_RPM` packet is
unchanged so the GUI keeps working.

**4. `TYPE_LPF_CAL = 0x10` — IIR + mag calibration (SD only, once at boot).**
13 floats: three alphas, three design cutoffs, `imu_rate_hz`, and `magCal` offsets/scales.

Rationale: the user asked whether the existing log already permits recovering raw IMU data,
and **it does** — the 1-pole IIR is exactly invertible via
`x[n] = y[n-1] + (y[n] - y[n-1]) / alpha`. My earlier claim that raw data was "thrown away"
was wrong. But α is derived from compile-time constants that were **never logged**, so
inverting a log required identifying the firmware build. This packet closes that gap.
`magCal` is included because mag inversion needs it too.

Written after the alpha computation in `setup()`, not with the other boot cal records —
writing it earlier would have logged zeros, since the alphas do not exist yet.

**5. RPM rounding.** `uint16` cast now rounds instead of truncating (was biased down by up
to 1 RPM).

**5a. Ring-buffer hardening (found during self-review).** The drain loop now casts explicitly
when reading `volatile uint32_t` elements into a plain local (interrupts are already disabled,
so dropping volatility is safe, but the cast documents the intent), casts the modulo result
back to `uint8_t`, snapshots `hallEdgeLost` inside the critical section, and emits a
`DBG_PRINT` warning once per new overflow. At ~33 edges/s into a 31-usable-slot buffer drained
every loop pass, overflow should never occur; if it does it means either noise-level edge
rates or a ~1 s loop stall, and both are worth knowing about rather than silently losing data.

**6. Magnet-mounting note.** Documented at `PULSES_PER_REV` that the US1881 is a *latch* and
works with a single magnet only because a **tangentially** passing magnet presents a bipolar
signature — the trailing return-flux lobe resets the latch. A magnet mounted face-on and
withdrawn along the same axis would latch once and never toggle. I initially argued from the
datasheet that two magnets were required; the user's working single-magnet device disproved
that, and the mechanism is recorded so the mistake is not repeated.

**Deliberately NOT changed:**
- **`IMU_RAW_MODE` dropped.** It would have been justified only by post-processing need,
  which the invertibility result eliminates. Purely a bandwidth question now, and there is
  no bandwidth problem.
- **No RPM rate-of-change filter.** The user noted the spring-driven ramp is gradual, which
  is true and exploitable (period changes ~5–23% per pulse on a linear ramp vs ×2 or ×0.5 for
  a dropped/spurious pulse). But at 200 RPM the legitimate per-pulse change reaches **150%**,
  so a naive ±50% band would reject valid early-rise data. Deferred to
  `POTENTIAL_UPGRADES.md`; raw edge logging makes it an offline decision anyway.
- **`CURRENT_RATE_HZ` left at 1000.** Analysis of the 20 kHz scope record showed the achieved
  ~377 Hz is within **0.6%** of ground truth on peak, ∫I·dt and ∫I²·dt. No rate work needed.

**Verification performed (host-side):** synthetic log with a realistic 12 s release profile
(2 s rise to 2000 RPM, 10 s decay) producing 199 edges batched 6 per record. All 199 parsed;
**RPM error vs interval truth = 0.000000**; peak recovered 1995.5 RPM vs 2000 simulated (the
0.2% gap is genuine edge discretisation). `TYPE_LPF_CAL` round-tripped all 13 fields at
float32 precision. Critically, **the logged alpha was used to invert a simulated IIR chain
back to raw counts with max error 0.000219 counts** — bit-exact, confirming the packet
achieves its purpose. First edge correctly emits empty period/RPM columns.
MATLAB parser **not run** (no MATLAB); firmware **not compiled**.

**Still open:**
- **⚠ ADC clipping.** The 20 kHz scope record peaks at **2.4403 V** against the 2.000 V
  reference, with **10.0% of samples above 2.000 V** — concentrated at the peak. A divider is
  needed; user is re-testing before choosing the ratio. `CURRENT_DIV_RATIO` unchanged pending
  that.
- No anti-aliasing filter on the sense line (ripple measured at ~3.7 kHz, sampled at
  ~377 Hz). Harmless for the integrals because the ripple is zero-mean, but not rigorous.
- No voltage channel, so still no true energy.

---
## 2026-09-02 — New `TELEM_ENABLE` flag to disable telemetry entirely, freeing loop time for faster current sampling — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — macro logic verified exhaustively by hand-simulating the
preprocessor, but **not compiled and not run on hardware**. Flip to
`[CONFIRMED YYYY-MM-DD]` or `[REVERTED YYYY-MM-DD]`.

**Why:** the harvested-current sample rate is loop-bound, not ADC-bound — measured ~377 Hz
against a 1000 Hz request. Telemetry is a significant share of that loop time (a 5 Hz IMU
packet, a 5 Hz current packet, 1 Hz status and stats packets, all through blocking serial
writes; a 27-byte packet occupies a 115200-baud UART for ~2.3 ms once the TX buffer fills).
There was previously **no way to switch telemetry off**: `USB_TELEM` only chooses between
USB and radio, so setting it to 0 just moved the traffic back to the RFD900.

**What changed:**

1. **New `TELEM_ENABLE` flag** (default `1`). At `0`, every telemetry transmission is
   compiled out and the telemetry UART is never initialised. SD logging is untouched.
2. **New `TELEM_WRITE(pkt)` macro** — the single entry point for all transmissions,
   replacing seven direct `TELEM_SERIAL.write(...)` calls.
3. **UART init guard** became `#if TELEM_ENABLE && (USB_DEBUG || !USB_TELEM)`, so
   `Serial1.begin()` is skipped when there is nothing to send.
4. A `DBG_PRINTLN` at boot states when telemetry is disabled, so a quiet ground station is
   diagnosable rather than mysterious.

**Why a macro rather than `#if` blocks around the senders:** four of the seven packets are
built inside blocks that *also* write to the SD card (the 5 Hz IMU/current block, the RPM
block, the GPS block). Wrapping those blocks in `#if TELEM_ENABLE` would have disabled SD
logging along with telemetry — the exact opposite of the intent. Routing every send through
one macro makes the on/off switch surgical. It also means any future packet added via
`TELEM_WRITE` inherits the flag automatically; a new direct `TELEM_SERIAL.write()` would
silently escape it, so **use the macro**.

The disabled form is `do { (void)sizeof(pkt); } while (0)` rather than an empty macro: it
keeps the packet struct type-checked and referenced, so `TELEM_ENABLE 0` builds do not
produce a wave of set-but-unused-variable warnings that could mask real ones. The
`do/while(0)` wrapper keeps the macro a single statement, safe inside an unbraced `if`.

**Windowed current statistics are still accumulated when telemetry is off.** They cost only
a few flops per sample and remain meaningful in the SD log's context; only the transmission
is suppressed. Skipping the accumulation would have saved nothing measurable while adding a
second behavioural difference between builds.

**Verification performed:** simulated the preprocessor across all **8** combinations of
`TELEM_ENABLE` × `USB_DEBUG` × `USB_TELEM`, checking in each case that the port
`TELEM_SERIAL` resolves to has actually been initialised wherever a write can occur.
Result: **no write-to-uninitialised-port cases**, and with `TELEM_ENABLE 0` no combination
opens `Serial1`. This is the same class of bug as the 2026-08-18 `Serial1` guard defect, so
it was worth checking exhaustively rather than by inspection. Confirmed all seven call sites
now use `TELEM_WRITE` and the only remaining `TELEM_SERIAL.write` is inside the macro
definition.

**Note:** `Serial.begin(115200)` at the top of `setup()` is left unconditional. USB CDC is
free when idle and `DBG_PRINT` may still need it, so gating it would add risk for no gain.

**Expected effect — and its limit.** This should raise the achieved sample rate, but **by
how much is unmeasured**. Telemetry is one contributor among several; the 104 Hz IMU block
(two I²C sensor reads plus Madgwick) and the ~12 kB/s of SD writes remain. If the rate is
still short of what the spring-release transient needs, the remaining options are unchanged:
timer/DMA-driven ADC, or threshold-triggered burst sampling. **Compare the effective-rate
and duty figures in the GUI before and after** — though note that with telemetry off the GUI
shows nothing, so measure the rate from `<base>_currentFast.csv` timestamps instead, or run
once with `TELEM_ENABLE 1` to get a baseline.

**Dead ends:** none.

---
## 2026-09-02 — Fix integrals to use measured dt; SD blocks record measured span — `[CONFIRMED 2026-09-02]`

**Status:** `[CONFIRMED 2026-09-02]` — validated on hardware across three logs. In
`09021931.BIN` the integration time Σdt came to **28.806 s of 28.806 s wall clock (100.00%)**,
which is the property the fix exists to guarantee. The `span_ms` field also correctly reported
the effective rate in every run (373 Hz, 163 Hz, 394 Hz), which is how the 400 Hz regression
was detected at all.

**How this was found:** the user ran the previous commit with the A14 pin **floating** and
reported the telemetry panel: `Peak 60 mA, Avg 1.966 mA, RMS 3.863 mA, Charge 72.7 mC,
∫I²dt 552.1 mA²s, Window 37s n=13954 DROPS:22423`. Those numbers are internally
inconsistent and exposed two defects. (The floating-pin values themselves are meaningless
noise — a high-impedance input picking up stray charge — but the *timing* they revealed is
real.)

**Defect 1 — the requested sample rate is not achieved.** `n / window = 13954 / 37 ≈
377 Hz` against a 1000 Hz request, i.e. ~2.65 ms per loop iteration. `n + n_dropped =
36377` ≈ the 37 000 ticks expected, so the drop accounting was at least self-consistent.
The cooperative loop simply cannot poll `analogRead()` at 1 kHz alongside the 104 Hz IMU
work, SD writes and telemetry. **The 1 kHz figure in the previous entry was an estimate and
it was wrong** — this is exactly why `n_dropped` was added.

**Defect 2 (the serious one) — the integrals were silently wrong by that same 2.65×.**
The accumulators used a *nominal* `dt = 1/CURRENT_RATE_HZ` per sample taken, so they
integrated only `n × 1 ms = 13.95 s` of the 37 s window, while the ground station divided
by the 37 s wall clock. Every average and RMS was understated by `integ/window = 0.377`.
The true mean of that capture was **5.21 mA, not the displayed 1.966 mA**. The same flaw
compressed SD block timestamps: 37 s of samples were labelled as spanning 14 s.

**Fixes:**

1. **Integrate with the measured interval.** `elapsedUs` (already computed for the drop
   counter) now supplies `dt`, so ∫I dt and ∫I² dt are correct however irregularly the loop
   runs. Guards skip the first sample of a window (no valid predecessor) and any interval
   over 1 s (bogus). This makes the statistics **rate-independent**, which is the property
   that actually matters — a slow loop now loses time resolution but *not* accuracy.
2. **New `integ_s` field in `CurrentStatsPacket`** carrying `Σdt`, the true integration
   time. Average is `charge_mC / integ_s` and RMS is `sqrt(i2t_mA2s / integ_s)` — **never**
   divided by `window_s`. Packet grows 23 → **27 bytes**.
3. **SD blocks record measured `span_ms` instead of a nominal `sample_rate_hz`** (same 2
   bytes, same record size). Parsers interpolate per-sample timestamps across the real span
   as `span_ms / (count - 1)` and can recover the effective rate. Storing an aspirational
   rate that the firmware demonstrably does not achieve was actively misleading.
4. `n_dropped` reinterpreted in comments: it now means "the requested rate is not being
   met", **not** "the data is wrong". With measured dt those are different statements.

**Why not just lower `CURRENT_RATE_HZ` to ~377?** Because the achieved rate varies with SD
activity and loop load, so any fixed nominal value would be wrong some of the time. Measuring
dt is correct at *every* rate and removes the whole class of bug. `CURRENT_RATE_HZ` is now
best read as a *ceiling / request*, not a guarantee — the comment says so.

**GUI additions:** effective rate (`n/window`) and duty (`integ/window`) are displayed, plus
a dedicated "Dropped" row, so a rate shortfall is obvious at a glance instead of requiring
arithmetic on the operator's part.

**Verification performed (host-side):** simulated the measured-dt accumulation at 1000, 377
and 104 Hz over the same 37 s of constant current — charge, average and RMS now agree to
**within 0.02 %** across all three rates (the old code would have scaled charge by
rate/1000, i.e. 377 Hz → 37.7 % of truth). Reproduced the reported screenshot numerically
and confirmed the corrected average is 5.210 mA. Round-tripped the new 27-byte packet
through the GUI on three paths (healthy, degraded-with-drops, `integ_s = 0` → shows `--`),
buffer fully consumed each time. Parsed a block with `span_ms = 265` over 100 samples:
timestamps span exactly 265 ms and the effective rate recovers as 373.6 Hz.

**Still open:**
- **The achieved rate (~377 Hz) may be too slow for the spring-release transient.** If the
  discharge is only a few ms wide it is still under-sampled. Options, in increasing order of
  effort: raise `CURRENT_BLOCK_LEN` and trim other loop work; move the ADC to a
  timer/DMA-driven path (the proper fix, Apollo3-specific); or burst-sample on a trigger
  threshold. **Measure the real pulse width before choosing.**
- Reverse current still unrepresentable (unsigned counts).
- Still no voltage channel, so still no true energy.

---
## 2026-09-02 — 1 kHz current sampling (`TYPE_CURRENT_BLOCK` 0x0E) + windowed telemetry statistics (`TYPE_CURRENT_STATS` 0x0F) — [CONFIRMED 2026-09-03]

> **Partially confirmed — corrected 2026-09-03.** An earlier version of this note claimed
> `TELEM_ENABLE` was 0 and that no telemetry had ever been sent. **That was wrong**: the
> committed values are `TELEM_ENABLE 1` and `USB_TELEM 1`, and the user confirms **USB
> telemetry works**. So the telemetry path, including `TYPE_CURRENT_STATS` (`0x0F`) and the
> GUI panels it drives, *is* exercised over USB.
>
> What remains unverified is the **RFD900 radio transport** (`USB_TELEM 0`), which the user
> reports has not been tested in a while. The packet layouts are transport-independent, so the
> risk there is link-level (baud, framing loss, range), not packet-level. Re-confirm after the
> next radio test.

**Status:** `[CONFIRMED 2026-09-03]` — subsequent hardware logs exercised current blocks,
calibration, and USB current-statistics telemetry. RFD900 link verification remains separate
under `IDENTIFIED_ISSUES.md` Issue 36.

**Why:** the harvester accumulates wave motion as spring potential energy and then releases
it all at once into the TENG disk. The electrically interesting event is a short
high-amplitude transient, so the previous 5 Hz sampling aliased away the very thing worth
measuring. The requirement was the highest practical sample rate on SD, plus telemetry that
conveys peak and average power without shipping the waveform.

**What changed:**

1. **`CURRENT_RATE_HZ = 1000`** — a new sampling block at the *top* of `loop()` (before the
   IMU block, so slower work below perturbs the cadence as little as possible). It replaces
   the `analogRead()` that used to sit in the 104 Hz IMU block; that block now only derives
   the milliamp value for the legacy 5 Hz radio packet.
2. **`TYPE_CURRENT_BLOCK = 0x0E`** — SD only, **variable length**: `uint16 sample_rate_hz`,
   `uint16 count`, then `count × uint16` raw counts, batched `CURRENT_BLOCK_LEN = 100`
   samples per record. Batching matters: one 5-byte header per 1 kHz sample would burn
   5 kB/s on headers alone, whereas 100-sample blocks cost ~9 bytes per 100 samples. The
   header timestamp is the time of the *first* sample; the embedded rate lets a parser
   reconstruct the rest, so no parser has to hard-code 1 kHz.
3. **`TYPE_CURRENT_STATS = 0x0F`** — radio only, 23 bytes, sent at 1 Hz: `window_s`,
   `peak_mA`, `charge_mC` (∫I dt), `i2t_mA2s` (∫I² dt), `n_samples`, `n_dropped`.
   Accumulators reset when the `CURRENT_STATS_WINDOW_MS` (2 min) window closes.
4. **`COUNTS_TO_MA`** — single derived conversion constant, so the SD path and the
   statistics cannot drift apart.

**⚠ "Total energy" was requested but cannot be measured — this is the one requirement I
could not meet as stated.** Energy requires ∫V·I dt, and this build measures *current only*:
there is no voltage sense on the harvester output (A14's divider was removed when the
supercap channel was repurposed earlier today). Fabricating a joule figure from an assumed
voltage would have produced authoritative-looking numbers that are simply wrong. Instead the
packet carries the two quantities that *are* rigorous from current alone:

- `charge_mC` = ∫I dt → average current directly; energy = charge × V_batt **if** the
  battery voltage is known or assumed.
- `i2t_mA2s` = ∫I² dt → energy = R × ∫I²dt **if** the load resistance is known; also gives
  true RMS current as `sqrt(i2t / window_s)`.

Either yields energy once the missing scalar is supplied, and both are exact. **To get true
energy, a second analog channel measuring output voltage is needed** — that is a hardware
change, not a firmware one. Worth deciding before the next deployment.

**Why 1 Hz telemetry of a 2-minute window (rather than one packet per window):**
sending every second means an operator connecting mid-window sees data within a second
instead of waiting up to two minutes, and the ground station can watch the window fill.
Cost is 23 B/s. Streaming raw samples would be 2 kB/s against a ~11.5 kB/s link — it would
starve the IMU and GPS packets.

**Accumulator precision:** `statCharge_mC` / `statI2t_mA2s` are `double`, not `float`. At
1 kHz a 2-minute window is 120 000 samples; a float32 carries ~7 significant digits, so
once the running total grew large, small samples would stop contributing (classic
accumulation error) and ∫I²dt in particular spans a wide dynamic range. The packet fields
are floats — the extra precision is only needed while summing.

**Dropped-sample accounting:** the sampler deliberately does **not** try to catch up after
a delay. Firing several back-to-back reads would violate the fixed `dt` the integrals
assume and silently corrupt them. Instead it takes one sample, resyncs, and counts the
missed ticks in `currentDropped`, which is transmitted so a sampling shortfall is visible
on the ground rather than hidden. **This is the field to watch on first power-up.**

**Rate ceiling — the main risk:** 1 kHz is a *starting estimate*, not a measured result.
`analogRead()` on the Apollo3 takes ~30–50 µs, and the 104 Hz IMU work plus SD writes share
the same cooperative loop. SD load rises from ~10.1 kB/s to ~12.1 kB/s (+21%). If
`n_dropped` climbs, lower `CURRENT_RATE_HZ` or raise `CURRENT_BLOCK_LEN`.

**Alternatives considered:**
- *Per-sample SD records* — rejected, 5 kB/s of pure header overhead.
- *Timer/DMA-driven ADC* — genuinely better for jitter and would allow a much higher rate,
  but it is a substantial Apollo3-specific rework and interacts with the SVL bootloader and
  the existing cooperative loop. The polled approach was chosen to keep this change
  reviewable; DMA is the right follow-up if 1 kHz proves insufficient.
- *Transmitting a decimated waveform* — rejected; decimation aliases the transient just as
  the old 5 Hz sampling did, which is the problem being fixed.
- *Peak-hold only* — insufficient, gives no average power.

**Simultaneous updates:** `vertisea_plot_v7.py` (block parser expanding samples with
reconstructed timestamps, `current_fast` key, `<base>_currentFast.csv`, new
"Harvested (2 min window)" GUI panel showing peak/avg/RMS/charge/∫I²dt/window with a drop
counter) and `parse_vertisea_log_v4.m` (variable-length block case with geometric array
growth, `<baseName>_currentFast.csv`).

`TYPE_CURRENT_BLOCK` is **deliberately absent** from both parsers' fixed payload-size skip
tables, because a variable-length record cannot be skipped from a constant — both files
carry a comment saying so, since a future packet type added without reading this would
otherwise "helpfully" add it and desynchronise the parser.

**Dead ends:** none.

**Verification performed (host-side only):** a synthetic log containing a simulated
spring-release transient (quiescent baseline, 20 ms triangular pulse to full scale) split
across three 100-sample blocks. All 300 samples round-tripped exactly, per-sample
timestamps reconstructed correctly (block 2 starting at 1100.0 ms = 1 ms spacing), peak
located at the pulse apex at 200.000 mA, and independently recomputed statistics matched:
charge 2.016981 mC, ∫I²dt 267.979 mA²s, RMS 29.888 mA, **crest factor 6.69** — confirming
the statistics characterise a pulsed discharge rather than smearing it. The 23-byte packet
round-tripped through the GUI handler on three paths (`window_s=0` shows `--` rather than
dividing by zero; full window computes avg/RMS; `n_dropped` surfaces as `DROPS:n`), with the
buffer fully consumed each time. **The MATLAB parser was not run and the firmware was not
compiled or executed.**

**Still open:**
- No voltage measurement, so no true energy (above).
- Reverse current still unrepresentable — counts are unsigned; a bipolar sensor with a
  mid-rail offset would read a constant half-scale at zero current. Add `offset_counts` to
  `CurrentCal` if so; the cal packet makes that non-breaking.
- The 5 Hz `TYPE_CURRENT` (0x0A) channel is now redundant with 0x0E and could be retired,
  but was left in place to avoid breaking the existing GUI "Current:" display in the same
  change.

---
## 2026-09-02 — SD log stores raw ADC counts; new `TYPE_CURRENT_CAL` (0x0D) makes logs self-describing — `[CONFIRMED 2026-09-02]`

**Status:** `[CONFIRMED 2026-09-02]` — three hardware logs parsed with byte-exact accounting
and zero unknown-type errors; `TYPE_CURRENT_CAL` present and correct in every one, and the
counts→mA conversion reproduces sensible values (e.g. 3626 counts → 44.27 mA).

**Why:** storing milliamps in a `uint16` quantised the reading to 1 mA while the ADC
resolves ~0.012 mA — throwing away ~82× of the available resolution on a 0–200 mA span.
Storing raw counts keeps all of it. But counts are meaningless without the scale factors,
and those live only in the firmware source, so a log would be unreadable without knowing
which build produced it. Hence a companion cal packet.

**What changed:**

1. **`TYPE_CURRENT` (0x0A) SD payload is now raw ADC counts**, not milliamps. Same
   `uint16`, same 7-byte record — **the size did not change, only the meaning**. See the
   compatibility warning below.
2. **New `TYPE_CURRENT_CAL = 0x0D`**, written once at boot to SD alongside the existing
   `TYPE_FIXED_CAL` / `TYPE_STAB_CAL` records, following that established precedent.
   Payload is 4 floats — `vref`, `adc_max`, `div_ratio`, `sens_mA_per_V` — giving a 21-byte
   record. Conversion: `mA = counts / adc_max * vref * div_ratio * sens_mA_per_V`.
3. **`loop()` keeps both forms**: new `currentCounts` static feeds the SD write, existing
   `current_mA` still feeds the radio packet.

**Key design decision — SD and radio units deliberately differ:**
The radio still sends **milliamps**, not counts. The ground station is framing-free and the
operator routinely connects *after* the buoy has booted, so a once-at-boot cal packet would
frequently be missed and the live display would have no way to convert. Converting on the
buoy costs nothing (the float math already runs) and guarantees the GUI always shows real
units. The asymmetry is called out in a block comment in the firmware header, in
`vertisea_plot_v7.py`, and in the `CurrentPacket` struct comment, because it is exactly the
sort of thing that silently confuses a future reader.

**Alternative considered:** send the cal packet over the radio periodically (say every
30 s) and have the GUI convert counts itself. Rejected as needless complexity — it spends
link budget re-sending constants that never change, and the buoy-side conversion is
simpler and always correct. Also considered storing tenths of a mA (`uint16`, 0–6553.5 mA)
as a middle ground; rejected because raw counts are lossless *and* self-documenting via the
cal record, whereas fixed-point still bakes in an assumed scale.

**⚠ Backward incompatibility — the one real hazard here:**
A `TYPE_CURRENT` record is still 7 bytes, so **an old log and a new log are structurally
identical but semantically different**, and nothing in the byte stream distinguishes them.
The presence or absence of a `0x0D` record is the only discriminator. Both parsers now use
exactly that test and warn loudly when no cal record is found, telling the reader to
interpret the counts column as milliamps instead. Logs recorded earlier today with the
mA-payload firmware fall into this category.

**Simultaneous updates:**
- `vertisea_plot_v7.py` — `TYPE_CURRENT_CAL` constant, `_SD_PAYLOAD_BYTES` entry (16), new
  parse branch, `current` records now carry `counts` + derived `current_mA`, new
  `current_cal` key and `<base>_currentCal.csv` output. Conversion runs as a **post-pass**
  after the file scan so cal-record ordering does not matter. Also fixed
  `write_csvs_from_parsed()` to write an empty cell for a present-but-`None` field — it
  used `rec.get(field, '')`, which returns `None` when the key exists, and would have
  written the literal string `None` into the CSV.
- `parse_vertisea_log_v4.m` — `packetTypes.currentCal`, `knownPayloadBytes` entry,
  `headers.current` gains a `counts` column, new cal case, and current records are
  **buffered** and written after the read loop (the parser is otherwise streaming, which
  cannot work when a later record supplies the scale factor).

**Dead ends:** none.

**Verification performed (Python parser only):** four synthetic logs exercised the paths —
cal-before-data, cal-*after*-data, cal-absent, and duplicate cal. Conversion is exact:
8191 counts → 99.9939 mA, 16383 → 200.0000 mA, and 1 count → **0.0122 mA**, which is the
resolution that previously rounded to 0. Cal-absent leaves `current_mA` blank and warns;
duplicate cal uses the first and warns. The MATLAB parser was **not** run (no MATLAB
available) and the firmware was **not** compiled.

**Still open:** reverse current is still unrepresentable — counts are unsigned and a
bidirectional sensor with a mid-rail offset would read a constant ~half-scale at zero
current. If the sensor turns out to be bipolar, add an `offset_counts` field to
`CurrentCal` rather than changing the sample type; the cal packet now makes that a
non-breaking change.

---
## 2026-09-02 — Repurposed the A14 analog input from supercap voltage to harvested-current sensing — `[CONFIRMED 2026-09-02]`

**Status:** `[CONFIRMED 2026-09-02]` — the channel reads plausible harvested current on
hardware (peaks 44–55 mA across runs) and `VREF = 2.0f` is corroborated by the fact that
readings scale sensibly against the scope. Note the divider question remains open separately:
a real discharge reaches 2.44 V, above the 2.0 V reference, so `CURRENT_DIV_RATIO` will need
revisiting — that does not affect the correctness of the repurposing itself.

**What changed:**

1. **Analog front end reinterpreted.** `A14` no longer reads a supercapacitor through a
   30 kΩ / 7.5 kΩ divider; it reads the analog output of a current sensor monitoring the
   energy harvested into the battery.
2. **Divider bypassed.** `R1` and `R2` are kept as documentation of the parts on hand, but
   `SUPERCAP_DIV_RATIO` is **commented out** and replaced by
   `CURRENT_DIV_RATIO = 1.0f`. The sensor's lab maximum output is < 2 V, which the ADC can
   read directly, so no division is needed.
3. **`VREF` corrected from `3.3f` to `2.0f`.** This was a genuine bug, not just a rename:
   the Apollo3 ADC does **not** reference the 3.3 V rail. It uses a selectable internal
   band-gap reference of 2.0 V or 1.5 V, and the Artemis module uses the internal 2.0 V
   one (confirmed against SparkFun's Artemis forum guidance). Inputs are 3.3 V tolerant
   but readings saturate above ~2 V. Every previous supercap voltage figure was therefore
   overstated by 3.3/2.0 = **1.65×**, on top of clipping at 2 V × 5 = 10 V of divider
   input. Historical supercap CSV columns should be treated as suspect.
4. **`CURRENT_SENS_MA_PER_V = 100.0f`** — the measured sensor sensitivity (updated from
   an initial `1.0f` placeholder later the same day). With the 2.0 V reference and no
   divider this gives a 0–200 mA full-scale range and an ADC resolution of ~0.012 mA per
   count. The `uint16` mA payload quantises that to 1 mA steps (0.5 % of full scale),
   which is acceptable; finer detail would require storing raw counts or tenths of a mA.
5. **Naming made consistent with a current measurement.** `TYPE_SUPERCAP` →
   `TYPE_CURRENT`, `SupercapPacket` → `CurrentPacket`, `voltage_mV` → `current_mA`,
   `supercap_mV` → `current_mA`, plus the file-header hardware/packet lists, the pin
   comment, and the `setup()` `pinMode` comment.

**Why the packet ID and layout were left alone:**
`0x0A` and the 2-byte `uint16` payload are unchanged, so SD record sizes, radio packet
sizes, and the `knownPayloadBytes` / `_SD_PAYLOAD_BYTES` skip tables all stay valid. Only
the *meaning* of the field changed. This keeps the change to a rename plus a scale factor
instead of a protocol break. Note the consequence: a `.BIN` from before this change and
one from after are byte-identical in structure but semantically different, and nothing in
the file distinguishes them — date the logs.

**Alternative considered:** allocating a new `TYPE_CURRENT = 0x0D` (as sketched in
`POTENTIAL_UPGRADES.md` U14) and retiring `0x0A`. Rejected for now because the supercap
channel is being *replaced*, not supplemented — there is only one analog input in play, so
carrying two IDs for the same 5 Hz slot would leave a permanently dead type. U14's wider
proposal (104 Hz sampling co-timed with the IMU, signed `int16` for bidirectional current)
remains open and would justify a new ID.

**Also note:** the payload is `uint16`, so **negative current cannot be represented** — the
value is clamped at 0. If the sensor output is bipolar (bidirectional current), this needs
to become `int16`, which *would* be a protocol change across all three consumers.

**Simultaneous updates (required by AGENTS.md for any packet-field change):**
- `vertisea_plot_v7.py` — constant, SD parser branch, CSV schema (`supcap` → `current`),
  and the live GUI handler/label (now "Current:" in mA).
- `parse_vertisea_log_v4.m` — `packetTypes.current`, `headers.current`, and the `switch`
  case; CSV suffix changes from `_supcap.csv` to `_current.csv`.

**Dead ends:** none.

**Verification needed:**
1. Compile the sketch (no `arduino-cli` in this environment — the firmware was **not**
   compile-checked).
2. With the current sensor connected, confirm the GUI's "Current:" field tracks the sensor
   and that a parsed log produces `<base>_current.csv`.
3. Sanity-check the 100 mA/V scale against a known load: a reading of *N* mA should
   correspond to *N*/100 volts at A14. Confirm the expected operating current sits
   comfortably inside the 0–200 mA range and does not clip at the 2 V ADC ceiling.

**Deliberately not updated (confirmation-gated per AGENTS.md):**
`docs/binary_protocol.md`, `docs/firmware.md`, `docs/telemetry_ground_station.md`,
`docs/data_pipeline.md`, `README.md`, and `AGENTS.md` all still describe `0x0A` as
supercapacitor voltage and `A14` as a divider input. They must be updated once this is
confirmed. `POTENTIAL_UPGRADES.md` U14 should also be revisited, since its premise
("supercap voltage at 5 Hz, no current measurement") is now partly satisfied.

---
## 2026-09-02 — Diagnose intermittent SD initialization failure and remove temporary diagnostics — `[CONFIRMED 2026-09-02]`

**Symptom:** SD initialization intermittently failed at the SPI command handshake and the
Apollo3 core repeatedly printed `got an error on _transfer: 4`.

**Cause and resolution:** The failure depended on whether the card was inserted and stopped
when pressure was applied to the card slot. The likely cause was a loose slot or poor card
contact. Reseating the card and pressing the slot restored consistent operation. Card
formatting and the Hall-effect sensor were not responsible.

**Firmware cleanup:** Removed the temporary low-level `Sd2Card` diagnostic and the 1 Hz Hall
sensor troubleshooting output. Normal RPM measurement, SD logging, and RPM telemetry remain
enabled. The SD call remains `SD.begin(CS_SD)`, which correctly uses pin 4 with SD 1.3.0;
the previous two-argument call used that library's `(clock, csPin)` overload rather than the
intended `(csPin, speed)` interpretation.

---
## 2026-08-18 — Fix `Serial1` init guard so telemetry survives `USB_DEBUG=1` + `USB_TELEM=1` — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — **not yet verified on hardware.** Flip to
`[CONFIRMED YYYY-MM-DD]` once bench-tested, or `[REVERTED YYYY-MM-DD]` if it misbehaves.

**What changed:**
In `setup()`, the guard around the telemetry port initialisation changed from
`#if !USB_TELEM` to `#if USB_DEBUG || !USB_TELEM`.

**Why:**
The guard has to mirror the `TELEM_SERIAL` macro, which resolves to `Serial1` in every
case *except* (`USB_TELEM=1` **and** `USB_DEBUG=0`). The old `#if !USB_TELEM` condition
did not account for `USB_DEBUG` winning the priority contest, so the combination
`USB_DEBUG=1` + `USB_TELEM=1` produced:

- `TELEM_SERIAL` → `Serial1` (because `USB_DEBUG` is checked first), but
- `Serial1.begin(115200)` skipped (because `USB_TELEM` is 1),

leaving the port uninitialised. Every `TELEM_SERIAL.write()` then wrote to a dead port and
**all telemetry was silently discarded**. Debug text on USB continued to work normally,
which is exactly what makes this failure mode hard to spot: the operator sees healthy boot
output and concludes the radio link or ground station is at fault.

The new condition initialises `Serial1` whenever `TELEM_SERIAL` points at it, making the
guard and the macro consistent for all four flag combinations:

| `USB_DEBUG` | `USB_TELEM` | `TELEM_SERIAL` | `Serial1.begin()` | Result |
|---|---|---|---|---|
| 0 | 0 | `Serial1` | yes | radio telemetry (field) |
| 1 | 0 | `Serial1` | yes | radio telemetry + USB debug text |
| 0 | 1 | `Serial` | no (not needed) | USB telemetry to GUI |
| 1 | 1 | `Serial1` | **yes (was no)** | radio telemetry + USB debug text — **fixed** |

**Alternative considered:**
Making the flags mutually exclusive with `#error` when both are set. Rejected because the
combination is genuinely useful — debug text on USB while telemetry goes out over the
radio — and it now works as a reader would expect. A hard error would have forced the user
to pick one for no functional reason.

**Dead ends:** none — the fix was a one-line condition change once the interaction was
understood.

**Verification needed:**
Flash with `USB_DEBUG 1` and `USB_TELEM 1`, then confirm the ground station receives
packets over the RFD900 link **and** that boot debug text still appears on USB. The other
three combinations should be unaffected but are worth a quick regression check. Note that
the committed flag state is `USB_DEBUG 0` / `USB_TELEM 1`, which takes the third row above
and is untouched by this change.

**Side effects:**
- No packet layout, timing, or behaviour change in any previously-working configuration.
- The flag-combination warnings added to `docs/firmware.md`,
  `docs/telemetry_ground_station.md`, `docs/calibration.md`, and `README.md` during the
  2026-08-18 documentation audit describe the **old** broken behaviour. They must be
  updated once this fix is confirmed — reference docs are confirmation-gated, so they are
  deliberately left alone for now.

---
