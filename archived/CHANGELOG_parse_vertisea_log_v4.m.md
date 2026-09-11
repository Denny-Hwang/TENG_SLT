# CHANGELOG — parse_vertisea_log_v4.m

Newest first.

---

> # ⚰ FILE RETIRED 2026-09-03
>
> `parse_vertisea_log_v4.m` was **deleted** from the working tree. See
> `docs/CHANGELOG_project.md` for the rationale and
> `AGENTS.md` for the current parser policy. Recoverable from git at **`9f5019f`**
> (final state) / **`ea30553`** (removal). **Do not recreate it** — extend
> `vertisea_plot_v7.py` instead.
>
> **This changelog is kept deliberately.** Every `[UNCONFIRMED]` entry below stays
> `[UNCONFIRMED]` **permanently**: those changes were written but never executed, because no
> MATLAB was available in the environment where they were made. That is exactly the kind of
> fact a changelog exists to preserve — the code was edited blind for several sessions and
> nobody would know from the source alone. Do not "tidy" these into confirmed.

---
## 2026-09-03 — `imuRaw` (0x12): 26 → 38 B payload, gyro now int32 [UNCONFIRMED]

**Status:** `[UNCONFIRMED]` — **not run** (no MATLAB in this environment). Mirrors the
verified Python parser; see `docs/CHANGELOG_VertiSea.ino.md` for the rationale and
`IDENTIFIED_ISSUES.md` Issue 35 for the defect.

- `knownPayloadBytes` entry for `0x12`: 26 → **38**.
- `headers.imuRaw` columns renamed to carry units (`fix_ax_mg`, `fix_gx_mdps`, …).
- The `case` now performs **four separate `fread` calls** rather than one:

```matlab
afix = fread(fid, 3, 'int16=>double');   % fixed accel, milli-g
gfix = fread(fid, 3, 'int32=>double');   % fixed gyro,  mdps
asta = fread(fid, 3, 'int16=>double');   % stab  accel, milli-g
gsta = fread(fid, 3, 'int32=>double');   % stab  gyro,  mdps
iv   = fread(fid, 1, 'uint16=>double');
```

A single mixed-type `fread` is not possible in MATLAB, so the reads must be split and their
order must match the firmware's packed struct exactly. This is the one place where the
asymmetric int16/int32 widths cost readability — accepted because `int32` mdps is the only
encoding that cannot overflow if the gyro full-scale setting is changed.

Variables are named `afix`/`gfix`/`asta`/`gsta` rather than `as`/`gs`; `as` is unwise as an
identifier even though MATLAB permits it.

---

## 2026-09-03 — 0x0A retired (read path kept); parse TYPE_IMU_RAW (0x12) [UNCONFIRMED]

**Status:** `[UNCONFIRMED]` — **not run** (no MATLAB in this environment). Changes are
structural and mirror the verified Python parser; treat as unvalidated until executed.

Mirrors the firmware change of the same date. See `docs/CHANGELOG_VertiSea.ino.md`.

**`current` (0x0A):** the firmware stopped emitting this on 2026-09-03 because a 5 Hz point
sample of a bursty signal is biased (682 vs 325 counts mean against the full-rate 0x0E
stream, 2.1× high). The parse path is **deliberately retained** so pre-existing logs still
convert; newer logs simply produce no `_current.csv`. The `packetTypes.current` entry, the
size-table comment and the `headers.current` block are annotated RETIRED, pointing at
`_currentFast.csv` for analysis.

**`imuRaw` (0x12):** new `packetTypes.imuRaw`, a 26-byte entry in `knownPayloadBytes` (so
even a parser that does not handle it can skip it without desynchronising), a
`headers.imuRaw` 14-column schema, and a `case` reading `fread(fid, 12, 'int16=>double')`
followed by `fread(fid, 1, 'uint16=>double')`.

**`int16` matters:** raw ISM330DHCX counts are signed; reading them as `uint16` would
corrupt every negative sample. The Python side verified −32768 and 32767 round-trip.

**A log contains either the processed records or `imuRaw`, never both** — `IMU_RAW_ONLY 1`
replaces `imuFixed`/`imuStab`/`mag` rather than supplementing them. The header comment says
so, and notes attitude must be recomputed offline from `calFixed`/`calStab`/`lpfCal`.

The new `case` was placed **before** `packetTypes.bme280` inside the existing `switch`, so
the buffered-write ordering relative to `fclose('all')` is untouched.

---

## 2026-09-02 — IMU packets grow to 43 B (new `interval_us` field) — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — **not run** (no MATLAB in this environment).

**What changed:**
- `knownPayloadBytes` for `0x01` / `0x02`: **36 → 38**.
- Both cases now read 9 singles **then** a `uint16`:
  `d = fread(fid,9,'single=>double'); iv = fread(fid,1,'uint16=>double');`
- `headers.imuFixed` gains `interval_us` (inherited by `headers.imuStab`), and the `fprintf`
  format gains a trailing `,%d`.
- Payload-size comment updated to note the trailing uint16.

**No backward compatibility** per the user's instruction — pre-change logs will misparse, since
a 36-byte read against a 38-byte record desynchronises the stream immediately.

**Why it matters:** `interval_us` is the measured microseconds between IMU samples, which makes
the achieved rate directly visible. The nominal 104 Hz was never actually reached (57.2 Hz in
`04030825`, 88.9 Hz in `09021931`) and nothing in the log revealed it.

---
## 2026-09-02 — Parse `TYPE_LPF_CAL` (0x10) and `TYPE_HALL_EDGE` (0x11) — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — **not run** (no MATLAB available). Flip to
`[CONFIRMED YYYY-MM-DD]` or `[REVERTED YYYY-MM-DD]`.

**What changed:**
- `packetTypes.lpfCal = 0x10` (fixed 52 B, added to `knownPayloadBytes`) and
  `packetTypes.hallEdge = 0x11` (variable length, **excluded** from that map).
- `headers.lpfCal` (14 columns) → `<baseName>_lpfCal.csv`, written with `%.9g` so the
  float32 alphas survive the CSV round-trip with enough digits to invert the IIR.
- `headers.hallEdge` → `<baseName>_hallEdge.csv` with `timestamp_ms, edge_us, period_us, rpm`.
- Hall edges are **buffered** (geometric array growth, as with the current samples) and
  written after the read loop, because a period can span two packets. Must stay above
  `fclose('all')`.
- `mod(ed(k)-ed(k-1), 2^32)` handles the `micros()` rollover (~71.6 min).
- First edge is written with empty period/rpm fields — it has no predecessor.

**Assumption:** RPM assumes **one magnet**; `PULSES_PER_REV` is mechanical and not in the
log. A console note reports the edge count and the assumption.

**Comment updated** on the `knownPayloadBytes` exclusion to name both variable-length types
(0x0E and 0x11), since adding either to that map would silently desynchronise the parser.

**Dead ends:** none.

---
## 2026-09-02 — `TYPE_CURRENT_BLOCK` now carries measured `span_ms` — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — **not run** (no MATLAB available). Flip to
`[CONFIRMED YYYY-MM-DD]` or `[REVERTED YYYY-MM-DD]`.

**Why:** a hardware run showed the sampler achieves ~377 Hz against a 1 kHz request, so the
block's former `sample_rate_hz` field was an aspiration rather than a fact and produced
per-sample timestamps ~2.65× too closely spaced.

**What changed:**
- The block's first payload field is read as `spanMs` (measured first-to-last sample time)
  instead of `rateHz`. `dtMs = spanMs / (nBlk - 1)` when `nBlk > 1`, else 0.
- The zero-rate warning is gone — with a measured span there is no divide-by-zero case
  beyond a single-sample block, which the `nBlk > 1` test covers.
- Comment on the `knownPayloadBytes` exclusion updated to name `span_ms`.

Record size is unchanged (still 2 bytes), so `<baseName>_currentFast.csv` keeps its
`timestamp_ms,counts,current_mA` schema — only the timestamps are now correct.

**Note:** logs written by the earlier firmware store a *rate* in that field. A 1 kHz-era log
parsed with this version would interpret 1000 as a span of 1000 ms and spread 100 samples
across a full second. There is no in-band way to distinguish the two, so treat blocks from
before this change as suspect — they were only ever produced by today's unreleased builds.

---
## 2026-09-02 — Parse variable-length `TYPE_CURRENT_BLOCK` (0x0E) — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — **not run** (no MATLAB in this environment). Flip to
`[CONFIRMED YYYY-MM-DD]` after parsing a log from the new firmware, or
`[REVERTED YYYY-MM-DD]`.

**Why:** the firmware now samples harvested current at 1 kHz and batches the samples into
`TYPE_CURRENT_BLOCK` records so the spring-release transient is resolved rather than
aliased.

**What changed:**
- `packetTypes.currentBlk = hex2dec('0E')` and `headers.currentFast`.
- New case reading `uint16 rate`, `uint16 count`, then `count` samples, reconstructing each
  sample's timestamp as `t_ms + (i-1) * 1000/rate`. Handles a truncated block and a
  zero-rate block (falls back to the block timestamp with a warning).
- Samples buffer into `fastTs` / `fastCounts` and are written after the read loop as
  `<baseName>_currentFast.csv`, converted to mA with the same `TYPE_CURRENT_CAL` constants
  as the 5 Hz channel.
- **Arrays grow geometrically** (doubling, minimum +1024) rather than one element per
  sample. This matters a lot here: at 1 kHz a ten-minute log holds 600 000 samples, and
  MATLAB's grow-by-one reallocation would make parsing quadratic and effectively hang.

**`knownPayloadBytes` deliberately excludes 0x0E**, with a comment explaining why: the
record is variable length, so it cannot be skipped from a fixed lookup and must always have
an explicit case. Adding it to that map would silently desynchronise the parser.

**Note on write order:** like the 5 Hz current block, this post-loop write must stay *above*
`fclose('all')`.

**Dead ends:** none.

---
## 2026-09-02 — Parse raw-count `TYPE_CURRENT` and the new `TYPE_CURRENT_CAL` (0x0D) — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — **not run** (no MATLAB in this environment). Flip to
`[CONFIRMED YYYY-MM-DD]` after parsing a log from the new firmware, or
`[REVERTED YYYY-MM-DD]`.

**Why:** the firmware now stores raw 14-bit ADC counts in the SD `TYPE_CURRENT` record to
preserve the ADC's ~0.012 mA resolution, plus a boot-time `TYPE_CURRENT_CAL` record holding
the constants needed to convert to milliamps.

**What changed:**
- `packetTypes.currentCal = hex2dec('0D')`, `knownPayloadBytes` entry of 16 bytes, and
  `headers.currentCal`.
- `headers.current` is now `{timestamp_ms, counts, current_mA}` — output gains a `counts`
  column.
- New `case packetTypes.currentCal` reading 4 singles and writing
  `<baseName>_currentCal.csv`.
- **Current records are now buffered, not streamed.** This is the structural change: every
  other packet type is written to its CSV as it is read, but a current record cannot be
  converted until the cal record has been seen. Records accumulate in `currentTs` /
  `currentCounts` and are written in a block after the read loop, before `fclose('all')`.
  A missing or zero-`adc_max` cal leaves `current_mA` blank and raises a warning pointing
  out that pre-0x0D logs hold milliamps in the counts column; more than one cal record uses
  the first and warns about concatenated logs.

**Note on the write order:** the post-loop block must stay *above* `fclose('all')`. Moving
it below would silently produce an empty `_current.csv`.

**Dead ends:** none.

---
## 2026-09-02 — Renamed the `0x0A` packet from supercap voltage to harvested current — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — **not run** (no MATLAB in this environment). Flip to
`[CONFIRMED YYYY-MM-DD]` after parsing a log recorded with the new firmware, or
`[REVERTED YYYY-MM-DD]`.

**Why:** `A14` on the buoy was repurposed from a supercapacitor voltage divider to a
current sensor monitoring energy harvested into the battery. Per AGENTS.md, a packet-field
change in `VertiSea.ino` must be applied to this parser in the same change.

**What changed:**
- `packetTypes.supcap` → `packetTypes.current` (still `hex2dec('0A')`).
- `headers.supcap = {'timestamp_ms','voltage_mV'}` →
  `headers.current = {'timestamp_ms','current_mA'}`.
- The `switch` case reads into `current_mA` and writes via `files.current`.
- The payload-length comment block now lists `current` instead of `supcap`.

**Output filename change (user-visible):** parsed logs now produce
`<baseName>_current.csv` instead of `<baseName>_supcap.csv`. Downstream scripts or
spreadsheets that look for `*_supcap.csv` will silently find nothing. Matches the Python
parser's new suffix.

**Unchanged on purpose:** `knownPayloadBytes` still maps `0x0A` → 2 bytes, since the
`uint16` payload size did not change — only its meaning did.

**Scale note:** the firmware's `CURRENT_SENS_MA_PER_V` is 100 mA/V (measured), so
`current_mA` spans 0–200 mA in 1 mA steps.

**Dead ends:** none.

---
