# Current Measurement Testing — Results and Post-Processing

> **Source data:** `SampleData/constant_DC_voltage/09031640_currentFast.csv` (instrument
> characterisation) and `SampleData/Discharge_PMC_Current/09031702_currentFast.csv`
> (TENG → PMC → battery discharge). Both recorded 2026-09-03.
>
> **Companion docs:** [`binary_protocol.md`](binary_protocol.md) for the `0x0D`/`0x0E`/`0x0F`
> packet layouts, [`firmware.md`](firmware.md) for the sampling implementation.

## Why this file exists

The harvested-current channel had never been characterised against a known input. Without a
reference measurement there was no way to answer the question that matters: **when the signal
looks noisy, is that the circuit or the instrument?** Two runs settle it.

---

## Measurement chain

| Item | Value |
|------|-------|
| ADC input | `A14`, 14-bit (`analogReadResolution(14)`), `ADC_MAX = 16383` |
| Reference | `VREF = 2.0 V` |
| Divider | `CURRENT_DIV_RATIO = 1.0` (none fitted) |
| Sensor | `CURRENT_SENS_MA_PER_V = 100.0` |
| Conversion | `mA = counts / 16383 × 2.0 × 1.0 × 100.0` → **1 count = 0.01221 mA** |
| Full scale | 16383 counts = 2.000 V = **200.0 mA** |
| Achieved rate | ~846 Hz within a block, ~780–800 Hz aggregate |

These constants are written to every log as `TYPE_CURRENT_CAL` (`0x0D`), so a file is
self-describing and does not depend on knowing which firmware build produced it.

---

## Test 1 — Constant DC from a function generator (instrument noise floor)

**Setup:** function generator into the ADC directly. No PMC. Signal stepped
off → steady on → off → on. 27000 samples over 33.6 s at 804 Hz.

### The steady plateaus are the useful part

| Plateau | n | Mean | SD | SD as % of reading | Peak-to-peak |
|---------|---|------|----|--------------------|--------------|
| 5.2–20.5 s | 12290 | 4032.65 counts | **9.07** | **0.225%** | 168 counts |
| 24.2–29.8 s | 4510 | 4033.75 counts | 11.59 | 0.287% | 114 counts |

In engineering units: **49.23 mA ± 0.11 mA** (1σ).

The two plateaus agree to **1.1 counts (0.03%)** across an intervening off period, which is a
good repeatability result — it means the reading is reproducible after the input is removed
and reapplied.

### The noise is white, and that is what makes averaging legitimate

Autocorrelation of the detrended plateau is **below 0.024 at every lag tested** (1–100
samples, i.e. 1.2–118 ms). Block-averaging follows the 1/√N law almost exactly:

| Block size | Measured SD | White-noise prediction | Ratio |
|-----------|-------------|------------------------|-------|
| 1 | 9.07 | — | — |
| 4 | 4.60 | 4.53 | 1.01 |
| 16 | 2.36 | 2.27 | 1.04 |
| 64 | 1.36 | 1.13 | 1.20 |

The mild excess at large N (ratio 1.20 at 64) indicates a small correlated/low-frequency
component, consistent with the measured drift below. **There is no mains pickup**: no
autocorrelation peak at lag 14 (60.4 Hz) or lag 17 (49.8 Hz).

### Drift is negligible over a discharge timescale

Slope over the 15 s plateau: **+0.154 counts/s** (+0.23% of reading per minute). Over 15 s
that is +2.3 counts against a 9.07-count noise floor — immaterial for events lasting seconds.
It would matter for a multi-minute integration, so long baselines should be re-zeroed rather
than assumed constant.

### Effective resolution

An SD of 9.07 counts on a 14-bit converter is roughly **10.8 effective bits**. The missing
~3 bits are the analog front end and the Apollo3 SAR, not the logging path. That is normal
for an unshielded breadboard measurement and is far better than needed here.

### The messy first 5 s were a connection artefact, not noise — confirmed

The operator suspected the disturbed opening period came from making connections. **The data
supports that, and the distribution shape is the evidence:**

| First 5 s | Value |
|-----------|-------|
| Exact zeros | **2088 of 4020 (51.9%)** |
| Samples > 2000 counts | 232 (5.8%) |
| Most common value | `0`, 2088 occurrences |

The signal is **bimodal** — it sits at exactly 0 about half the time and otherwise jumps to
near the true plateau value (4033 appears 10 times in this window). Electrical noise produces
a *tight, unimodal* distribution about a mean; an intermittent contact **switches between zero
and the correct reading**. That is what this is.

**Consequence for analysis: discard the first ~5 s of this run.** It characterises a loose
wire, not the instrument. The same signature — a large population of exact zeros — is a useful
general check for connection problems in future captures.

---

## Test 2 — TENG → PMC → battery discharge, sensor between PMC and battery

**Setup:** energy accumulator discharging spring to TENG; TENG AC into the power management
circuit; PMC output to battery; **current sensor between PMC and battery**. 45700 samples over
58.6 s. Reported by the EE: switching frequency **3.735 kHz**, duty cycle **3.6%**.

### Acquisition quality

| Metric | Value |
|--------|-------|
| Samples | 45700 over 58.61 s (780 Hz aggregate, 846 Hz in-block) |
| Idle baseline | 18.36 ± 9.14 counts = **0.224 ± 0.112 mA** |
| Peak | **16383 counts = 2.000 V = 100% of full scale** (4 samples) |
| Zeros | 1142 (2.5%) |

Note the idle baseline noise (9.14 counts) matches the constant-DC noise floor (9.07 counts)
almost exactly. **The instrument behaves identically in both tests**, which is the
cross-check that makes the comparison below valid.

### The 4 full-scale samples are transients, not signal

Despite the run staying under the 2 V limit overall, four samples pin at exactly 16383. Each
is a **single-sample impulse** surrounded by normal values:

```
t=31.49 s  [9087, 9814, 9459, 16383, 9047, 9866, 9650]
t=31.57 s  [9253, 9472, 9900, 16383, 8569, 9356, 9854]
t=33.47 s  [7382, 7872, 7520, 16383, 7815, 7874, 5892]
t=39.12 s  [1217, 1292,  411, 16383, 1330,    0,  772]
```

A real current cannot rise ~80% of full scale and return within one 1.2 ms sample interval.
These are switching transients coupled into the sense line. **Removing them changes total
charge by −0.09%**, confirming they carry no real charge.

---

## The central finding: we are NOT aliasing the switching waveform

This was the first thing to check and the answer is reassuring, but it is **not** what the
switching numbers alone would suggest.

At 846 Hz against a 3.735 kHz switching frequency we are **8.8× under-Nyquist**. If the sensor
saw the raw switch node at 3.6% duty, then during a discharge ~96% of samples would sit at
the off-state floor and ~4% would be high. **The data shows the opposite:**

| During peak discharge (30–32 s) | Value |
|--------------------------------|-------|
| Samples > 5000 counts | **95.7%** |
| Samples < 200 counts | **1.1%** |
| Median | 8613 counts |

Supporting evidence: **autocorrelation 0.96–0.98 at every lag out to 24 ms**, and a smooth
multi-second decay envelope.

**Why:** the sensor sits between the PMC and the battery, i.e. **after the PMC output filter**.
The battery-side current is the smoothed average, not the switch-node waveform. The 3.735 kHz
and 3.6% figures describe the **switch**, not the node being measured.

> **This distinction matters for planning.** If we *were* aliasing a 3.735 kHz signal at
> 846 Hz, no amount of post-processing could recover it and the only fix would be hardware
> (a faster ADC path or an analog integrator). Because we are measuring a filtered node, the
> envelope is real and post-processing is a legitimate cleanup rather than a cover-up.

---

## Instrument noise vs circuit noise — quantified

This is what the constant-DC run was for.

| Source | Level | SD | SD as % of reading |
|--------|-------|----|--------------------|
| Constant DC (instrument) | 4033 counts | 9.07 | 0.225% |
| PMC output, detrended | 3633 counts | 606.9 | 16.7% |

**Ratio: 66.9×.** Quadrature subtraction gives
√(606.9² − 9.07²) = 606.8 counts — i.e. **100% of the observed PMC "noise" is real circuit
behaviour**, and the ADC contributes nothing measurable to it.

**Interpretation.** The EE is right that filtering is needed, but the target is *not* the
instrument. What we are seeing is genuine ~15% ripple on the PMC output plus impulsive
switching transients. Improving the ADC, shielding, or the sample rate would not reduce it.
The options are: filter in post-processing (below), add analog filtering at the sense point,
or reduce the ripple at source in the PMC.

### The noise is asymmetric, and the direction is counter-intuitive

| Feature | Count |
|---------|-------|
| Dropouts (< 30% of neighbour mean, neighbours > 500) | **223** |
| Positive spikes (> 2× neighbour mean) | 106 |

Dropouts outnumber spikes roughly 2:1, and many are exact zeros sitting between samples of
1500–3500 counts. **Consequence: median filtering *increases* total charge by ~2.8%.** Anyone
assuming "despiking removes energy" would get the sign of the correction backwards.

---

## Signal content

Two discharge events, both smooth decays. Values below are after the full pipeline.

| Event | Duration | Charge | Peak | Mean |
|-------|----------|--------|------|------|
| 1 (28.5–42 s) | 13.50 s | **667.5 mC** (0.1854 mAh) | 125.1 mA | 49.5 mA |
| 2 (52–58.7 s) | 6.61 s | 30.2 mC (0.0084 mAh) | 42.1 mA | 4.6 mA |

The decay is **not** a clean exponential (R² = 0.83 against an RC fit, τ ≈ 4.0 s). That is
expected — a regulating PMC does not passively discharge, so a good RC fit would have been the
surprising result.

**Event 2 delivers 22× less charge than event 1.** Worth understanding before optimising:
smaller mechanical input, or the accumulator not fully recharged between discharges.

---

## Recommended post-processing pipeline

> **⚠ REVISED 2026-09-11.** The pipeline below described a median-5 main stage and a
> clamp-at-zero baseline subtraction. Both have been replaced. The *measurements* in this
> document are unchanged and still stand — the reinterpretation is in
> [Revision 2026-09-11](#revision-2026-09-11--matching-the-scopes-high-resolution-mode)
> at the end. Read that section instead of the four steps below, which are kept for
> provenance.

Apply in this order. Measured effect on total charge for `09031702`:

| Step | Operation | Charge | Δ |
|------|-----------|--------|---|
| 0 | raw | 691.276 mC | — |
| 1 | replace samples ≥ 16383 with a 3-point median | 690.646 mC | −0.09% |
| 2 | median-5 filter | 710.596 mC | +2.79% |
| 3 | subtract the 18.36-count idle baseline | 698.212 mC | +1.00% net |

### 1. Reject impossible samples first

Only touch samples at or above full scale (16383). Replace with a 3-point median of
neighbours. Keep this narrow — aggressive outlier rejection on a signal with real fast
structure will remove signal.

### 2. Median-5, not a mean or low-pass

**Median is the right choice here and the constant-DC run proves it is safe:**

- On constant DC it reduces SD **9.07 → 4.50 counts (2.02×**, close to the √5 = 2.24 ideal).
- It changes the mean by **−0.000%** — no bias introduced, which is what matters for a
  quantity that will be integrated.
- It rejects both the dropouts and the positive impulses, which a mean cannot: a single zero
  next to 3500 counts drags a 5-point mean down by 700, while the median ignores it entirely.
- It preserves the sharp discharge onset. A Gaussian or Butterworth low-pass would round the
  leading edge and be pulled by the outliers.

Widen the window only if the ripple is still objectionable, and re-check the charge each time
— the table above shows charge stabilising by w=5, so wider windows buy little.

### 3. Subtract the idle baseline — not optional

The 18.36-count (0.224 mA) idle offset contributes **12.4 mC over 58.6 s, which is 1.8% of the
total**. It scales with recording length, so on a long deployment with sparse harvesting events
it would eventually dominate the reported charge.

Measure the baseline from a genuinely idle window in the same file rather than assuming a
constant — it may drift with temperature. Whether it is sensor offset or true leakage is worth
resolving with a dedicated capture (harvester disconnected, sensor powered).

### 4. Integrate with the measured `dt`

Use the per-sample timestamps, which the parser reconstructs from the logged `span_ms`. Do not
assume `1/CURRENT_RATE_HZ` — the requested 1000 Hz is a deliberate over-request and the
achieved rate is ~800 Hz. This is the same class of error as the IMU nominal-vs-actual dt bug
(`IDENTIFIED_ISSUES.md` Issue 34).

Trapezoidal integration is sufficient given the sample density; guard against the
inter-block gaps by rejecting any interval above ~50 ms.

---

## Limitations to state plainly

**Energy is not measured, only charge.** There is no voltage sense on the battery node, so
∫V·I dt is unavailable. Charge × nominal battery voltage is an estimate that assumes a
constant voltage: at 3.7 V, event 1 ≈ 2470 mJ, but the true figure depends on the battery's
actual terminal voltage during charging. **A second analog channel on the battery would make
this a real energy measurement** and is the single highest-value addition to this setup.

**Headroom is tighter than the "we stayed under 2 V" summary implies.** The filtered peak
reached 125 mA (62% of the 200 mA full scale) and the transients already touch the rail. If
optimisation roughly doubles the output, genuine multi-sample clipping begins. `CURRENT_DIV_RATIO`
exists for this: a 2:1 divider restores margin for one bit of resolution, and because the
ratio is logged in `0x0D`, existing files stay correctly interpretable.

**Single run, unoptimised hardware.** Both files are one capture each. The instrument
characterisation is solid (12290 samples on a stable plateau), but the discharge numbers
describe one unoptimised configuration and should not be treated as representative performance.

**Sub-millisecond structure is invisible.** At ~846 Hz anything faster than ~400 Hz is not
resolved. This is fine for the filtered battery-side current but means the pipeline cannot
report instantaneous switching behaviour — for that, a scope at the switch node is the right
instrument.

---

## Test bench: `current_filter_test.py`

The pipeline above is implemented as a standalone script at the repository root, kept
separate from `vertisea_plot_v7.py` on purpose: integrating an unvalidated filter into the
BIN→CSV conversion would silently bias every future dataset.

```bash
py -3 current_filter_test.py --selftest                      # 18 checks, no data needed
py -3 current_filter_test.py <base>_currentFast.csv          # full report
py -3 current_filter_test.py <csv> --baseline-window 21.5,23  # force an idle span
py -3 current_filter_test.py <csv> --window 9 --plot
py -3 current_filter_test.py <csv> --write-csv out.csv       # raw + filtered columns
```

It reads calibration from the sibling `_currentCal.csv` (`0x0D`), so conversion always
matches the firmware that produced the log, and falls back to documented defaults with a
warning if that file is absent.

### What running it on both captures established

**Mean preservation, measured on the constant-DC plateau (n = 12873):**

| Filter | Mean | SD | SD ratio | Mean shift |
|--------|------|----|----------|-----------|
| none | 4032.65 | 9.10 | — | — |
| median-3 | 4032.65 | 5.70 | 1.60× | +0.0001% |
| **median-5** | **4032.65** | **4.52** | **2.01×** | **+0.0000%** |
| median-9 | 4032.63 | 3.51 | 2.59× | −0.0004% |
| median-15 | 4032.63 | 2.83 | 3.21× | −0.0005% |
| mean-5 | 4032.64 | 4.15 | 2.19× | −0.0000% |

This is the go/no-go criterion: **a filter must reduce scatter without moving the level**,
because the level is what gets integrated into charge. Median-5 achieves a 2.01× reduction
at a mean shift of 0.0000%. Wider windows keep helping the SD, so if the ripple is
objectionable, median-9 or median-15 are defensible — but re-check the charge each time.

Note that on *constant DC* the mean filter also looks fine (−0.0000%). It is on the
**PMC** data that they diverge: median-5 gives +2.79% charge while mean-5 gives −0.05%.
The mean is pulled down by the dropouts it fails to reject, so it under-reports charge
exactly where the signal is real. That contrast is the argument for the median.

### Runtime: fast enough to default ON

| Window | 45700 samples | Throughput |
|--------|---------------|-----------|
| median-3 | 0.008 s | 5.7 M samples/s |
| median-5 | 0.010 s | 4.7 M samples/s |
| median-31 | 0.039 s | 1.2 M samples/s |

Extrapolating median-5: a **1-hour** log at 800 Hz (2.88 M samples) filters in **~0.6 s**;
a **10-hour** log in **~6 s**. This is pure Python with no NumPy. **The cost is not a
reason to make the option opt-out** — the U21 concern about slow conversion applies to
orientation estimation, not to this filter.

### Two limitations the script exposed

Both were found by running it rather than by reading it, and both are now reported by the
tool itself rather than left as silent traps.

**1. Auto baseline detection returns 0 on the constant-DC file.** Its off-periods are exact
zeros, so the lowest 1-second bin median is 0 and no offset is removed. That is arithmetically
correct — a disconnected input has no offset to subtract — but it is **not** a sensor-offset
measurement, and quietly reporting "baseline 0.00" would invite the wrong conclusion. The
script now prints a warning naming the likely causes and pointing at `--baseline-window`.

> **Consequence for test design:** to characterise the sensor's own offset the input must be
> **idle but still connected**, not switched off. This is why capture #1 below matters.

**2. The event detector is meaningless on a mostly-ON record.** On the DC file it merges the
whole capture into one 31.9 s "event", because it is built for brief excursions above an idle
floor. The script now warns when the longest event exceeds 50% of the record. Event splitting
is only meaningful for discharge-style captures.

---

## Suggested next captures

Ordered so that each one unblocks something. Every capture should be **≥30 s** with the
harvester quiet for at least a few seconds at both ends, so the baseline and noise floor can
be measured from the same file rather than assumed.

### 1. Sensor offset — idle but CONNECTED  *(highest value, cheapest)*

Sensor powered, wired into the circuit, harvester quiet. Run 60 s.

**Answers:** is the 0.224 mA idle reading the sensor's own offset or real leakage? The
constant-DC file cannot tell us, because its off-periods are exact zeros (disconnected).
Until this is known, the baseline subtraction is a correction of unknown provenance.

**Check:** `--baseline-window` over the whole file; the reported offset and its SD.
Repeat after the board has warmed up to see whether it drifts.

### 2. Multi-level DC — linearity and gain  *(unblocks quantitative claims)*

Function generator at ~10%, 25%, 50%, 75%, 90% of the 2 V range, ~20 s dwell each, in one
capture. Record the generator's set voltage for each step.

**Answers:** is the counts→mA conversion linear, and is `CURRENT_SENS_MA_PER_V = 100.0`
actually right? The single-level run establishes noise and repeatability but **cannot
detect a gain error or curvature** — a 10% scale error would be invisible.

**Check:** plateau means against set voltage; fit and inspect the residuals. A gain error
shows as a slope ≠ 1; an offset shows as a nonzero intercept, which should match capture #1.

> Do this **before** trusting any absolute mC or mAh figure. Everything reported so far is
> internally consistent but has never been checked against a reference.

### 3. Secure-connection discharge repeat  *(explains the outstanding anomaly)*

Same setup as `09031702` with all connections mechanically secured, several discharges,
allowing full accumulator recharge between them.

**Answers:** why did event 2 deliver **22× less charge** than event 1 (30 mC vs 668 mC)?
Candidate explanations — smaller mechanical input, incomplete recharge, or a connection
fault — are not separable from one capture.

**Check:** consistency of charge across repeats. Also confirm the exact-zero count stays low;
a high count means the wiring is still intermittent.

### 4. Simultaneous scope at the sense point  *(independent verification)*

Scope across the sense resistor during a discharge, ideally triggered so the traces can be
aligned with the log.

**Answers:** is the ~15% ripple figure real, and is anything faster being missed? Every
ripple number in this document comes from the same 846 Hz sampler that might be aliasing it.
An independent instrument is the only way to close that loop.

**Check:** scope RMS ripple vs the detrended residual SD; scope peak vs logged peak.

### 5. Post-optimisation headroom check  *(before it becomes a problem)*

After PMC optimisation, one discharge with the existing `CURRENT_DIV_RATIO = 1.0`.

**Answers:** does the output now clip? Present peak is 125 mA = 62% of the 200 mA range, so
roughly a 1.6× increase starts genuine clipping.

**Check:** count samples at/near 16383. **More than a handful of consecutive** full-scale
samples means real clipping, as distinct from the isolated single-sample transients seen so
far. If so, fit a 2:1 divider and set `CURRENT_DIV_RATIO = 2.0` — the constant is logged in
`0x0D`, so old files remain correctly interpretable.

### 6. Battery voltage channel  *(turns charge into energy)*

Not a capture but a hardware change: a second analog input on the battery node.

**Answers:** actual energy, ∫V·I dt. Today every energy figure assumes a constant battery
voltage and is an estimate.

**Consider first:** a second high-rate channel roughly doubles the current SD load, and SD
write bandwidth is already the limiting factor on IMU rate (Issue 34). Battery voltage moves
slowly, so a low-rate channel — say 10 Hz — would capture it at negligible cost. Do not
sample it at 800 Hz simply because the existing channel is.

### What would make these captures easier to interpret

- **Log a note file alongside each capture** recording the setup, the generator settings and
  what was being tested. `09031640` and `09031702` had to be reverse-engineered from the data.
- **Keep the sampler configuration fixed** across a comparison set. Changing rate or divider
  mid-series makes runs hard to compare.
- **Always capture idle periods at both ends** — they are the only in-file source of both the
  baseline and the noise floor.

---

## Revision 2026-09-11 — matching the scope's High-Resolution mode

The stated requirement changed, and with it the answer. The goal is for the processed data
to resemble a **Keysight scope in High-Resolution acquisition mode** rather than Normal
mode. That is a specific, well-defined operation, and the pipeline above was not it.

### What High-Resolution mode actually is

HiRes averages **N consecutive samples acquired at the full sample rate** and emits one
point. It is a boxcar (moving-average) FIR filter: linear, mean-preserving, with a known
transfer function. It trades bandwidth for vertical resolution at a fixed exchange rate —
each 4× increase in N buys one effective bit, because white noise falls as √N:

```
bits gained = 0.5 * log2(N)
f_-3dB      = 0.443 * fs / N          first null at fs / N
```

Normal mode, by contrast, decimates by *dropping* samples: full bandwidth, full noise.
The visual difference the operator sees between the two modes is entirely this averaging.

### Why the median-5 could not produce that result

Three reasons, in increasing order of importance.

1. **It is less efficient.** The sample median of *w* Gaussian values has variance about
   π/2 larger than the mean. Measured against this document's own 9.14-count idle floor:

   | w | median SD ratio | boxcar SD ratio | ideal √w |
   |---|-----------------|-----------------|----------|
   | 5 | 1.87× | 2.25× | 2.24× |
   | 17 | 3.40× | 4.15× | 4.12× |
   | 33 | 4.71× | 5.81× | 5.74× |

   The boxcar tracks the ideal to within 1%. The median gives up ~20% of the available
   noise reduction — i.e. roughly a third of an effective bit at every width.

2. **It is nonlinear, so it has no bandwidth.** There is no transfer function to quote, no
   way to state what was kept and what was removed, and therefore no way to set a scope to
   the same thing. "Similar to HiRes" is unachievable by construction with a median.

3. **It moves the mean — which this document already measured and did not act on.** The
   table above records median-5 changing total charge by **+2.79%**. This module's own
   design note says a filter that moves the level is unusable for a quantity that gets
   integrated. A boxcar changes it by **0.000%** at every width, because averaging is
   mean-preserving by construction. That is not a tuning detail; it is the requirement.

The median was chosen for a real and correct reason — the dropouts. Section
[The noise is asymmetric](#the-noise-is-asymmetric-and-the-direction-is-counter-intuitive)
shows 223 dropouts against 106 positive spikes, and a boxcar genuinely cannot reject them:
one exact zero beside 3500 counts drags a 5-point mean down by 700. The error was using
one filter for two jobs. **Despiking and noise reduction are separate stages** — the first
must be nonlinear, the second must be linear, and combining them forfeits the properties of
both.

### The clamp-at-zero baseline subtraction was fabricating charge

`subtract_baseline()` returned `x - baseline if x > baseline else 0.0`. On an idle
stretch the signal sits *at* the baseline, so after subtraction it is symmetric noise about
zero — and clamping discards the negative half. For zero-mean Gaussian noise of width σ the
surviving mean is

```
E[max(X,0)] = σ / √(2π) ≈ 0.399 σ
```

With the σ = 9.14 counts measured here, that is **+3.65 counts of current that does not
exist**, present for every idle second of the record and integrated straight into the
reported charge:

| Idle duration | Fabricated charge |
|---------------|-------------------|
| 1 hour | 161 mC |
| 1 day | 3 854 mC |
| **2 days** | **7 708 mC** |

The largest *real* event measured in this document is **667.5 mC**. On the 1–2 day
deployment this system is for, the clamp alone invents about eleven discharge events' worth
of charge — and it scales with idle time, so it is worst exactly when harvesting is sparse,
which is the case the measurement exists to quantify. On the 58.6 s bench capture it was
worth only ~0.75 mC and hid under the noise, which is why it survived review.

Plain subtraction leaves idle stretches centred on zero, so they integrate to zero plus a
random walk growing as √t rather than t.

### The pipeline now

```
1. reject_full_scale()   repair isolated rail GLITCHES; keep sustained SATURATION and
                         report it — the two are different events (Issue 60)
2. hampel_filter()       remove impulsive outliers ONLY; everything else passes untouched
3. boxcar_filter()       the HiRes stage — this is what buys effective bits
4. subtract_baseline()   last, and without clamping
5. decimate_blocks()     one point per averaged block — the other half of HiRes, applied
                         to the PLOT only, never to the CSV or the charge integral
```

Step 5 was missing until 2026-09-11 and its absence was the single most misleading thing
about this tool (Issue 62). A sliding boxcar has the right frequency response but returns
one output sample per input sample, so a 40 s capture at 800 Hz still plots 32,000 points
across ~1,300 pixels — 24 samples per pixel column, every column painted to its full
vertical extent. Residual ripple then renders as a solid band and a correctly filtered
trace is indistinguishable from an unfiltered one. A scope in HiRes emits one point per
block, which is why its trace looks clean at the same bandwidth on the same signal.

The decimated plot draws the block mean as a line and the block min/max as a band behind
it. The band is not decoration: it is the ripple that averaging removed. On a clean capture
it collapses onto the line; if it stays wide, the record is saturated or aliased and the
line is hiding it.

Step 2 is a Hampel filter: local median ± n·MAD (scaled by 1.4826), replacing a sample only
if it exceeds the threshold. Unlike a blanket median it rewrites *only* the bad samples —
on the synthetic reproduction of this data it touches 0.73%, which matches the 0.72%
outlier population measured here (223 + 106 of 45 700) closely enough to be reassuring.

The MAD degenerates to zero when more than half a window holds the same value — which is
exactly the dropped-connection signature this document identified in the first 5 s of the
constant-DC run (51.9% exact zeros). The despiker therefore takes a **scale floor** derived
from the quietest second of the same record, so it still has something to test against.

### Choosing the window

Default is `--window 17`: **20.8 Hz** and **+2.0 effective bits** at the achieved ~800 Hz,
taking the idle floor from 9.14 counts (0.110 mA) to 2.20 counts (0.027 mA).

The discharge envelope is ~12 s long (~2 s rise, ~10 s decay) — under 1 Hz of real signal
bandwidth — so 20.8 Hz leaves roughly 20× margin over the fastest structure that physically
exists at this node. Widen it freely if the trace is still busier than the scope's:

| `--window` | −3 dB | Bits gained | Idle SD |
|-----------|-------|-------------|---------|
| 5 | 70.9 Hz | +1.16 | 4.05 counts |
| 9 | 39.4 Hz | +1.58 | 3.02 |
| **17** | **20.8 Hz** | **+2.04** | **2.20** |
| 33 | 10.7 Hz | +2.52 | 1.57 |
| 65 | 5.5 Hz | +3.01 | 1.12 |

To match a specific scope capture, set both to the same bandwidth: `N = 0.443 × fs / f_3dB`.

### Two things to expect, so they are not mistaken for faults

**Peak falls as the window widens, and that is correct.** A peak read through a 21 Hz
filter *is* a 21 Hz peak; the scope in HiRes reports the same reduction. Always quote the
bandwidth alongside a peak. Note also that the firmware's `TYPE_CURRENT_STATS.peak_mA` is
an **unfiltered single sample** and will always read higher than the processed column —
they are different quantities, not a disagreement.

**Charge does not change at all.** That is the point, not a bug.

### The limit that post-processing cannot cross

The ADC has **no analog anti-alias filter**. Everything above ~400 Hz folded into the band
*before* the sample was taken, and no digital filter can undo that. A scope in HiRes
averages at its full acquisition rate and never has this problem, so **if the two still
disagree after matching bandwidths, aliasing is the first thing to suspect** — and the fix
is an RC low-pass at the sense point, not more filtering.

The [central finding](#the-central-finding-we-are-not-aliasing-the-switching-waveform)
above argues we are not aliasing the 3.735 kHz switching, because the sensor sits after the
PMC output filter and the autocorrelation stays at 0.96–0.98 out to 24 ms. That argument
still holds, with one caveat now worth stating: the alias frequency moves with the achieved
sample rate, which jitters with loop load, so aliased content would smear rather than
appear at a fixed frequency. The decisive test is a direct one — capture the same discharge
on the scope in HiRes and on the buoy simultaneously, match the bandwidths, and overlay.
Until that is done, "we are not aliasing" is a well-supported inference, not a measurement.
