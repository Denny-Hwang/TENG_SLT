# CHANGELOG — vertisea_plot_v7.py

Newest first.

---

## 2026-09-08 — Parse and display battery voltage and average power — `[UNCONFIRMED]`

Added `0x13` battery calibration and `0x14` battery voltage to the sole SD parser, producing
`<base>_batteryCal.csv` and `<base>_batteryVoltage.csv`. The live GUI displays the 1 Hz voltage
and calculates average mW from latest battery volts times the verified `0x0F` running average
current. Keeping voltage separate avoids a backward-incompatible change to `0x0F`.

**Host validation:** `py_compile` passes. A synthetic log with voltage before calibration,
followed by `0x13`, a second voltage record, and legacy RPM parsed with zero errors; voltage
conversion and both new CSV schemas round-tripped exactly. The 3,042,128-byte pre-change
`SampleData/SD_test/09081703.BIN` still parses to its exact 50,198 IMU / 410,000 current /
2,546 RPM record counts with zero errors. Hardware/DMM, GUI, and radio validation remain required.

---

## 2026-09-04 — Correct `TYPE_IMU_RAW` constant comment units — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — documentation-only source comment correction; parser bytes and
behaviour are unchanged.

The constant comment said “raw int16 counts,” contradicting the implemented and verified
layout. It now states the actual fields: int16 milli-g accelerometer and int32 mdps gyro.
The unit/type confusion is the same class that caused Issue 35, so it is corrected at the
first declaration as well as in the detailed parser comments below.

---
## 2026-09-03 — `TYPE_IMU_RAW` 0x12: 26 → 38 B payload, gyro now int32 [CONFIRMED 2026-09-03]

Mirrors the firmware fix for `IDENTIFIED_ISSUES.md` Issue 35. See
`docs/CHANGELOG_VertiSea.ino.md` for the full rationale.

- `_SD_PAYLOAD_BYTES[TYPE_IMU_RAW]` 26 → **38**.
- Unpack format `'<12hH'` → **`'<3h3i3h3iH'`** — accel `int16` milli-g, gyro `int32` mdps.
- Dict keys and CSV columns renamed to **carry units**: `fix_ax_mg`, `fix_gx_mdps`, etc.
  A reader that assumed dps would be wrong by 1000×, and the original unit confusion is
  exactly what caused the bug, so the units are now impossible to miss in the header row.

**Verified:** round-trip with ±500000 mdps (the `ISM_500dps` full scale that the old `int16`
could not hold), int32 min/max, and int16 accel extremes — all exact, 0 errors, payload
measured 38 B, CSV header and row correct.

**Regression:** `09031403` and `09031136` parse to 5908 and 8711 fixed/stab/mag records with
**0 errors** and unchanged keys, confirming the filtered-record path is untouched.

**`09031405.BIN` (written with the old 31-byte record) now fails to parse**, desyncing at
offset 236 with "unknown packet type 0x5B". This is the correct behaviour: reading a 31-byte
record as 43 bytes must fail loudly rather than emit plausible garbage. Its gyro data was
corrupt in any case.

---

## 2026-09-03 — 0x0A retired; parse TYPE_IMU_RAW (0x12); "Current:" now from 0x0F [CONFIRMED 2026-09-03]

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

Mirrors the firmware change of the same date. See `docs/CHANGELOG_VertiSea.ino.md`.

**`TYPE_CURRENT` (0x0A):**
- The **radio** parse branch is **deleted** — the firmware no longer transmits it.
- The **SD** parse branch is **kept**, so pre-existing logs still load, but now carries a
  warning that the value is a biased point sample (682 vs 325 counts mean against the 0x0E
  stream, 2.1× high) and that `currentFast` is the quantitative source.
- `TYPE_CURRENT = 0x0A` is retained as a constant purely for that read path, annotated
  RETIRED so nobody reuses the ID.

**GUI:** the System Status "Current:" field lost its feed when the radio branch went, so it
is now set from `TYPE_CURRENT_STATS` (0x0F) as `charge_mC / integ_s` and displayed as
`"N.NN mA avg"`. The "avg" suffix is deliberate — it is a window average, not an
instantaneous reading, and mislabelling it would repeat the error that made 0x0A misleading.
Set to `"--"` when `integ_s` is 0.

**`TYPE_IMU_RAW` (0x12):** new constant, a 26-byte payload entry in `_SD_PAYLOAD_BYTES`, a
parse branch unpacking `'<12hH'`, an `imu_raw` key in the `data` initialiser, and an
`imuRaw` CSV schema with 14 columns. Note the format is `12h` (**signed**) — raw
ISM330DHCX counts are signed and an unsigned format would silently corrupt every negative
reading.

**Verified:**
- Regression on `09031136.BIN`: 8711/8711/8711 IMU+mag, 64900 currentFast, 466 current,
  49 hallEdge, **0 errors** — identical to pre-change counts; `imu_raw` 0 as expected.
- Synthetic 0x12 log: 31 B records, all 12 values round-trip exactly **including −32768 and
  32767**, `interval_us`/`ts_ms` correct, 0 errors.
- CSV writer emits `_imuRaw.csv` with correct header/rows; real log still emits its usual 13
  files and no `_imuRaw.csv`.

**Bug caught during verification:** the first attempt omitted `'imu_raw': []` from the
`data` dict initialiser, which would have raised `KeyError` on the first 0x12 record. Found
by the synthetic test before any hardware run.

`py_compile` passes. Testing required stubbing `serial` (pyserial is not installed in this
environment); the SD parser does not use it.

---

## 2026-09-02 — IMU packets grow to 43 B (new `interval_us` field) — [CONFIRMED 2026-09-03]

**Status:** `[CONFIRMED 2026-09-03]` — later real logs parsed with the added interval field.

**Why:** the firmware now records the measured microseconds since the previous IMU sample, so
the ACHIEVED sample rate is in the log rather than having to be inferred. See
`docs/CHANGELOG_VertiSea.ino.md`.

**What changed:**
- `_SD_PAYLOAD_BYTES` for `TYPE_FIXED_IMU` / `TYPE_STAB_IMU`: **36 → 38**.
- Parse branch reads 38 bytes and unpacks `'<9fH'` instead of `'<9f'`.
- `interval_us` appended to both `_imu_fields` tuples, so it flows into
  `<base>_imuFixed.csv` / `<base>_imuStab.csv`.
- Size comment updated: 5 B header + 9×float + 1×uint16 = 43 B total.

**No backward compatibility**, by the user's instruction: logs written before this change will
not parse with this version. There is no legacy 36-byte branch and no version sniffing.

**Verification:** synthetic log with 43-byte IMU records parsed with zero errors;
`interval_us` recovered exactly (9615 → 104.00 Hz); `TYPE_MAG`, `TYPE_CURRENT_BLOCK` and
`TYPE_CURRENT_CAL` still parsed afterwards, confirming byte accounting stayed exact (a wrong
size here would have desynchronised everything downstream). CSV header now ends
`...,ax,ay,az,interval_us`.

**Analysis tip:** `1e6 / interval_us` gives the instantaneous IMU rate. Watch its distribution
rather than its mean — the pre-change data was bimodal (79.7% at 9–10 ms, 19.4% at 44–46 ms),
and a mean alone hides that.

---
## 2026-09-02 — Separate informational notes from warnings; RTS/DTR fix did not take effect — `[PARTIALLY CONFIRMED 2026-09-02]`

**Status:**
- **Notes/warnings separation: `[CONFIRMED 2026-09-02]`** — log `09021931.BIN` parsed with
  **no warning popup at all**, which is the correct behaviour for a clean single-session log.
- **RTS/DTR reset fix: `[REVERTED 2026-09-08]`**

**Cause of the reset is now established by controlled comparison.** Three runs:

| Log | GUI connected? | Sessions | Duplicate cal records |
|---|---|---|---|
| `09021837` | yes | 2 | yes |
| `09021858` | yes | 2 | yes |
| **`09021931`** | **no** | **1** | **no** |

Two-for-two with the GUI, clean without it. The CH340E's RTS line resetting the Artemis on port
open is confirmed as the mechanism; the buoy does **not** reset spontaneously.

The pyserial-side fix remains unverified — most likely it was never exercised, because the GUI
was probably launched from the broken project `.venv` rather than the edited file. Confirm by
running the GUI from a working interpreter and repeating the connect-during-logging test.

**Priority note:** the user confirmed USB telemetry is bench/debug only and field deployments
use the RFD900 radio, where the GUI never touches the buoy's USB. So this is a convenience
issue, not a data-integrity risk in deployment. The zero-cost workaround is to connect the GUI
*before* starting a run that matters.

**1. Fixed my own mislabelling.** The "Derived RPM from N Hall edges assuming 1 magnet" message
was appended to `data['errors']`, so it appeared in the **Parse Warnings** popup alongside a
genuine problem. It is purely informational. Added a `data['notes']` list, moved the message
there, and the notes are now folded into the "Parse Complete" summary dialog instead. A warning
popup should always mean something needs attention — diluting it trains the operator to dismiss
it.

**2. The RTS/DTR reset fix did NOT work.** Log `09021858.BIN` still shows two sessions:
session 1 runs 19.0 s (RTC 18:58:28) and session 2 boots at 18:58:49 — a ~2 s reset-and-reinit
gap, not a power cycle. Telling detail: **session 1 has zero Hall edges and session 2 has all
50**, so the sequence was: power up → GUI connect (reset) → wave magnet.

**Why it did not work — new information from the user.** The RedBoard Artemis Nano has only
**one USB connector**. There is no separate CH340 port to avoid: the single connector *is* the
CH340E, whose RTS line is wired to the Artemis reset pin. So the GUI necessarily opens the
reset-capable port.

The code change itself is mechanically correct — verified against pyserial
`serialwin32.py`, where `_reconfigure_port()` (called inside `open()`) sets
`comDCB.fRtsControl = RTS_CONTROL_ENABLE if self._rts_state else RTS_CONTROL_DISABLE`
(line 180) and the same for DTR (line 211). Pre-setting the flags to `False` therefore *does*
produce `*_CONTROL_DISABLE` in the DCB.

**Most likely reason it had no effect: the GUI was run from the broken project `.venv`, or an
already-running instance, so the edited file was not the one executing.** That needs
confirming before any further code change — otherwise we risk "fixing" something that is
already correct.

**Remaining possibilities if a confirmed-fresh run still resets:**
- Windows/CH340 driver asserts RTS during `CreateFile` before the DCB is applied, so the pulse
  precedes any software setting. If so, no pyserial-side fix exists and the options are
  hardware (cut/​jumper the RTS-reset path, or add a capacitor on reset) or procedural (connect
  the GUI *before* starting a logging run).
- Some CH340 driver versions ignore `RTS_CONTROL_DISABLE`.

**Practical mitigation available today:** this only affects bench/USB debugging. Field runs use
`USB_TELEM 0` with the RFD900 radio, where the GUI never touches the buoy's USB. And connecting
the GUI *before* the run matters begins is a zero-cost workaround.

**Also worth fixing separately (firmware):** because the RTC minute had not rolled over,
the `MMDDHHMM` filename collided and the second session appended to the same file. A counter
suffix would make each boot a distinct file regardless.

---
## 2026-09-02 — Stop the GUI resetting the buoy on connect (RTS/DTR) — `[REVERTED 2026-09-08]`

**Status:** `[REVERTED 2026-09-08]` — connecting the GUI over USB still reset the buoy. The
firmware's unique-filename fix prevented concatenation: pre-connect and post-reset sessions were
written as distinct logs, each with exactly one boot-record set. RTS/DTR suppression therefore
did not solve this board/driver reset path and needs a separate follow-up.

> **Update 2026-09-03.** The user confirms **USB telemetry works**, which means the GUI has
> been connected to a running board since this fix landed — i.e. the code path *has* executed
> without breaking the connection. That is weaker evidence than it sounds, though: the fix
> prevents a **reset on connect**, and a reset would be invisible to someone watching live
> telemetry (the board reboots in well under a second and telemetry resumes). Proving it
> requires checking a log for the double-boot signature — duplicated `RTC_EVENT`/`*_CAL`
> records and a backward `ts_ms` jump — in a run where the GUI was attached mid-session.
>
> Left `[UNCONFIRMED]` deliberately rather than upgraded on circumstantial evidence. The
> check is cheap: connect the GUI ~15 s into a run, then look for two boot-record sets.

**Symptom:** log `09021837.BIN` contained **two complete boot sequences** — duplicate
`RTC_EVENT`/`FIXED_CAL`/`STAB_CAL`/`CURRENT_CAL`/`LPF_CAL` records, with `ts_ms` resetting
from 10002 back to 591 about 14 s in. The SD-log parser correctly flagged it
("2 CURRENT_CAL records found; used the first. Was this log concatenated from two
sessions?"), which is how it was noticed.

The user confirmed they did not power-cycle, but **did connect the GUI over USB shortly after
power-up** — which matches the reboot timing exactly.

**Cause:** `serial.Serial(port, 115200, timeout=0.1)` asserts **both RTS and DTR** on open
(pyserial `serialutil.py` lines 210–211 set `_rts_state = True` / `_dtr_state = True` by
default). On the RedBoard Artemis Nano, **RTS is wired to the Artemis reset pin** — it is the
mechanism the SVL bootloader uses. SparkFun's own hookup guide states: *"For the Nano we
needed to use the much smaller CH340E that has only RTS. The CH340E and RTS work fine to
reset the Artemis module and activate the SparkFun variable bootloader."*

So **opening the GUI's serial port rebooted the buoy**, losing the in-progress log and
restarting `millis()`. Because the RTC minute had not rolled over (18:37 both times), the
`MMDDHHMM` filename was identical and the firmware reopened and appended to the same file,
producing one file containing two sessions.

This is a data-integrity bug, not a cosmetic one: any field run where the operator attaches
the GUI would silently lose everything logged up to that point.

**Fix:** construct `Serial` **without** a port (which defers opening — `serialutil.py` line
237 `if port is not None:`), clear `rts` and `dtr` while closed, then assign the port and
call `open()`. Setting the lines while closed is safe and is applied at open time: the
setters store `_rts_state` and only call `_update_rts_state()` `if self.is_open`
(lines 454–457).

Ordering matters — clearing the lines *after* `open()` would be too late, as the reset pulse
has already been emitted. That is why the one-line constructor form cannot be kept.

**Robustness:** the rts/dtr assignment is wrapped in a `try` that swallows
`OSError`/`AttributeError`/`ValueError`, since some drivers reject setting control lines on a
closed handle. In that case the code proceeds to open anyway — a possible reset is better
than refusing to connect at all. `self.ser` is now also reset to `None` on failure, so a
failed connect cannot leave a half-constructed unopened port that `update()` would poll.

**Verification:** confirmed against pyserial's `serialutil.py` that (a) both control lines
default to asserted, (b) they are assignable while closed and applied on open, and (c) a
port-less constructor defers opening. Could not exercise it locally because the project
`.venv` is broken (`uv trampoline failed to spawn Python child process`) and the system
interpreter has no `pyserial`.

**How to confirm on hardware:** power the buoy, wait ~15 s, connect the GUI, then convert the
log. A single set of boot records and a monotonic `ts_ms` means fixed. The duplicate-cal
warning firing again means the reset still happens.

**Note:** the firmware-side filename collision is a separate latent issue — two sessions
starting within the same RTC minute will still share a file. Worth addressing separately
(e.g. a counter suffix), but with this fix the second session should no longer occur
spontaneously.

---
## 2026-09-02 — Parse `TYPE_LPF_CAL` (0x10) and `TYPE_HALL_EDGE` (0x11) — `[CONFIRMED 2026-09-02]`

**Status:** `[CONFIRMED 2026-09-02]` — both types parsed from three hardware logs with
byte-exact accounting and zero unknown-type errors. `<base>_lpfCal.csv` and
`<base>_hallEdge.csv` produced correctly, with derived periods and RPM.

**Caveat that is NOT a parser issue:** whether the *sensor* reliably emits an edge per
revolution is unresolved — the US1881 is a latch and its reset is geometry-sensitive. See
`POTENTIAL_UPGRADES.md` U18. The parser faithfully reports whatever edges were captured, which
is exactly what is needed to diagnose that question offline.

**What changed:**
- Added `TYPE_LPF_CAL = 0x10` (52-byte payload, 13 floats) and
  `TYPE_HALL_EDGE = 0x11` (variable length: `uint8 count` + `count × uint32`).
- `lpf_cal` records carry the IIR alphas, design cutoffs, `imu_rate_hz` and `magCal`
  offsets/scales → `<base>_lpfCal.csv`. These make the IMU low-pass filter invertible
  offline (`x[n] = y[n-1] + (y[n]-y[n-1])/alpha`), which was previously impossible because
  alpha lived only in the firmware source.
- `hall_edge` records carry raw `micros()` falling-edge times → `<base>_hallEdge.csv` with
  derived `period_us` and `rpm`. Derivation is a **post-pass** because edges are batched and
  a period can span two packets. `uint32` wrap (every ~71.6 min) is handled with a masked
  subtraction.
- `_SD_PAYLOAD_BYTES` gains 0x10 (52) but **deliberately not** 0x11, which is variable
  length. Comment updated to name both variable-length types and warn against adding them.
- Load-BIN summary lists the two new keys.

**Assumption recorded in the output:** RPM derivation assumes **one magnet**.
`PULSES_PER_REV` is a mechanical property and is not stored in the log, so the parser emits
a note saying so rather than silently guessing. If magnets are added, divide the `rpm` column
by the count.

**Verification performed:** synthetic log with a realistic 12 s spring-release profile (2 s
rise to 2000 RPM, 10 s decay) → 199 edges batched 6 per record. All parsed with **0.000000
RPM error** against interval truth; peak recovered 1995.5 vs 2000 simulated. `lpf_cal`
round-tripped all 13 fields, and the parsed alpha was then used to invert a simulated IIR
chain back to raw counts with max error **0.000219 counts** (bit-exact) — confirming the
packet is fit for its purpose. First edge correctly writes empty `period_us`/`rpm` cells
rather than the string `None`.

**Dead ends:** none.

---
## 2026-09-02 — Divide by true integration time, not wall clock; parse measured `span_ms` — `[CONFIRMED 2026-09-02]`

**Status:** `[CONFIRMED 2026-09-02]` — verified against hardware logs. Reconstructing the
integrals from `09021931.BIN` gives Σdt = 28.806 s against 28.806 s of wall clock (100.00%),
and the `span_ms`-derived effective rate correctly tracked three different configurations
(373 Hz, 163 Hz, 394 Hz) — which is how the 400 Hz sample-rate regression was caught.

**Why:** a hardware run revealed the buoy achieves ~377 Hz, not the requested 1 kHz, and
that the firmware's integrals used a nominal dt. This file was complicit: it divided charge
and ∫I²dt by `window_s` (wall clock), which understated average and RMS by the
integration-time-to-wall-clock ratio — a factor of 2.65 in the reported capture.

**What changed:**
- `TYPE_CURRENT_STATS` is now **27 bytes** (`<BHHHfffII`), with a new `integ_s` field.
  **Average = `charge_mC / integ_s`, RMS = `sqrt(i2t_mA2s / integ_s)`** — the wall-clock
  `window_s` must never be used as the divisor.
- `TYPE_CURRENT_BLOCK`'s first payload field is now measured `span_ms`, not
  `sample_rate_hz`. Per-sample timestamps interpolate as `span_ms / (count - 1)`, so they
  land on real time even when the sampler runs slow or irregularly. The zero-rate guard
  became an `n > 1` guard.
- GUI shows **effective rate** (`n/window`) and **duty** (`integ/window`) on the Window row,
  and gained a dedicated **Dropped** row, so a rate shortfall is legible without the
  operator doing arithmetic.

**Verified:** charge/avg/RMS agree within 0.02 % across simulated 1000/377/104 Hz captures
of the same signal, confirming the displayed figures no longer depend on the achieved rate.
Three GUI paths exercised (healthy, degraded with 22 423 drops, `integ_s = 0` → `--` with no
ZeroDivisionError), buffer fully consumed each time. A block with `span_ms = 265` across 100
samples yields timestamps spanning exactly 265 ms and a recovered rate of 373.6 Hz.

**Note:** the 27-byte packet is **not** backward compatible with the 23-byte version from
earlier today. Since the type byte and length both changed, an old firmware talking to this
GUI would desynchronise rather than mis-display — flash both sides together.

---
## 2026-09-02 — Parse `TYPE_CURRENT_BLOCK` (0x0E) and display `TYPE_CURRENT_STATS` (0x0F) — [CONFIRMED 2026-09-03]

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

**Status:** `[CONFIRMED 2026-09-03]` — exercised with real `.BIN` logs and USB telemetry.
RFD900 transport remains separately unverified (Issue 36).

**Why:** the firmware now samples harvested current at 1 kHz to resolve the spring-release
transient, batching samples into `TYPE_CURRENT_BLOCK` records on SD, and reduces each
2-minute window to peak/∫I dt/∫I² dt for transmission as `TYPE_CURRENT_STATS`.

**What changed:**
- Added `TYPE_CURRENT_BLOCK = 0x0E` and `TYPE_CURRENT_STATS = 0x0F`.
- **New variable-length parse branch** for 0x0E — reads `uint16 rate`, `uint16 count`, then
  `count` samples, and expands them into one `current_fast` record each with the timestamp
  reconstructed as `block_ts + i * 1000/rate`. `ts_ms` is a float here because the sample
  interval need not be a whole millisecond. Guards against a truncated header, a truncated
  payload, and a zero rate (which would divide by zero).
- `current_fast` records feed the same cal-based mA conversion post-pass as the 5 Hz
  channel, and are written to `<base>_currentFast.csv`.
- **New "Harvested (2 min window)" GUI panel** showing peak current, average current
  (charge/window), RMS current (√(i2t/window)), raw charge, raw ∫I²dt, and a window/sample
  line that appends `DROPS:n` when the firmware reports missed sample ticks.
- `_SD_PAYLOAD_BYTES` **intentionally does not** include 0x0E, with a comment explaining
  that a variable-length record cannot be skipped from a fixed table.

**Why average power is not displayed as watts:** the buoy measures current only — there is
no voltage sense on the harvester output — so a watt figure would require inventing a
voltage. The panel shows the rigorous integrals instead, from which power follows once the
battery voltage or load resistance is known. Deliberate choice, not an oversight.

**Verification performed:** synthetic log with a simulated spring-release transient
(quiescent baseline plus a 20 ms triangular pulse to full scale) across three 100-sample
blocks. All 300 samples round-tripped, timestamps reconstructed at 1 ms spacing across
block boundaries, peak row `1110.0,16383,200.0` at the pulse apex, and zero parse errors.
The stats handler was driven directly with a synthesised 23-byte packet on three paths:
`window_s=0` (shows `--`, no ZeroDivisionError), a full window (avg 0.017 mA, RMS 1.494 mA),
and a drops case (`DROPS:37`) — buffer fully consumed each time, confirming correct framing.
Ran on the system interpreter with `serial`/`matplotlib` stubbed and Tk bypassed, since the
project `.venv` remains broken (`uv trampoline failed to spawn Python child process`).

**Dead ends:** none.

---
## 2026-09-02 — Parse raw-count `TYPE_CURRENT` and the new `TYPE_CURRENT_CAL` (0x0D) — [CONFIRMED 2026-09-03]

**Status:** `[CONFIRMED 2026-09-03]` — exercised with hardware logs. The old live `0x0A`
path was later retired; current live display now comes from `0x0F`.

**Why:** the firmware now stores raw 14-bit ADC counts in the SD `TYPE_CURRENT` record
(instead of pre-rounded milliamps) to keep the ADC's full ~0.012 mA resolution, and emits a
`TYPE_CURRENT_CAL` record at boot carrying the constants needed to convert.

**What changed:**
- Added `TYPE_CURRENT_CAL = 0x0D` and a `_SD_PAYLOAD_BYTES` entry of 16 (4 floats).
- New parse branch producing a `current_cal` list of
  `{ts_ms, vref, adc_max, div_ratio, sens_mA_per_V}`.
- `current` records now carry `counts` **and** a derived `current_mA`.
- **Conversion is a post-pass** run after the whole file is scanned, not inline, so the cal
  record's position does not matter. Verified with a log where the cal record comes *after*
  the data. If several cal records appear (a concatenated log) the first is used and a
  warning is recorded; if none appears, `current_mA` is left `None` and the warning explains
  that pre-0x0D logs store milliamps directly in the counts column.
- New CSV `<base>_currentCal.csv`; `<base>_current.csv` gains a `counts` column, so its
  schema is now `timestamp_ms,counts,current_mA`.
- **Bug fixed in passing:** `write_csvs_from_parsed()` used `rec.get(field, '')`, whose
  default never fires for a key that exists with value `None` — an unconverted
  `current_mA` would have been written as the literal string `None`. Now emits an empty
  cell.

**Unchanged on purpose:** the live radio handler still expects **milliamps**, because the
firmware deliberately converts on the buoy. A framing-free GUI that connects mid-session
would otherwise never see the once-at-boot cal record and could not convert counts. This
SD/radio asymmetry is documented in the packet-size comment block.

**Verification performed:** four synthetic logs — cal-first, cal-last, no-cal, double-cal.
Conversion exact (8191→99.9939 mA, 16383→200.0000 mA, 1→0.0122 mA); CSV for the no-cal case
correctly wrote `100,8191,` with an empty final field. Ran on the system interpreter with
`serial`/`matplotlib` stubbed, since the project `.venv` is broken
(`uv trampoline failed to spawn Python child process`); the GUI class was not instantiated.

**Dead ends:** none.

---
## 2026-09-02 — Renamed the `0x0A` packet from supercap voltage to harvested current — `[SUPERSEDED 2026-09-03]`

**Status:** `[SUPERSEDED 2026-09-03]` — hardware use confirmed the A14 current-channel
repurpose, but `0x0A` was then retired because its 5 Hz point sample was biased. The current
GUI now uses `TYPE_CURRENT_STATS` (`0x0F`); this entry remains as historical evolution.

**Why:** `A14` on the buoy was repurposed from a supercapacitor voltage divider to a
current sensor monitoring energy harvested into the battery. Per AGENTS.md, a change to a
packet field in `VertiSea.ino` must be applied to this file in the same change.

**What changed:**
- `TYPE_SUPERCAP` → `TYPE_CURRENT` (still `0x0A`), and the byte-layout comments now read
  `current_mA` instead of `voltage_mV`.
- `parse_binary_file()`: the `supercap` result key became `current`, holding
  `{ts_ms, current_mA}`; the truncation message now says "CURRENT".
- `write_csvs_from_parsed()`: CSV suffix `supcap` → `current`, so output is
  `<base>_current.csv` with header `timestamp_ms,current_mA`. Matches the MATLAB parser's
  new schema.
- Load-BIN summary key list updated so record counts still appear.
- GUI: `supercap_var` → `current_var`, label "Supercap:" → "Current:", and the live
  handler now displays `f"{current_mA} mA"` instead of dividing by 1000 for volts.

**Unchanged on purpose:** the packet ID, the 2-byte `uint16` payload, `_SD_PAYLOAD_BYTES`,
and the framing-free byte-scanning parse strategy. Only the field's meaning changed, so
every size table stays correct.

**Scale note:** the firmware's `CURRENT_SENS_MA_PER_V` is 100 mA/V (measured), giving a
0–200 mA full-scale range. The GUI displays whole milliamps, which is 0.5 % of full scale.

**Verification performed:** a synthetic SD-format log containing one `0x0A` record
(`current_mA = 1234`) and one `0x0C` RPM record was parsed with a throwaway harness;
`parse_binary_file()` returned the expected `current` and `rpm` records with no errors, and
`write_csvs_from_parsed()` produced `T_current.csv` containing
`timestamp_ms,current_mA` / `1000,1234`. The harness was deleted afterwards. Note the
project `.venv` is currently broken (`uv trampoline failed to spawn Python child process`),
so this ran on the system interpreter with `serial`/`matplotlib` stubbed — the GUI class
itself was therefore not instantiated.

**Dead ends:** none.

---
