# CHANGELOG — current_filter_test.py

Newest entries first. This changelog records why changes were made as well as what changed.

---

## 2026-09-11 (later) — Decimate like the scope; stop rewriting saturation as noise — `[UNCONFIRMED]`

Driven by a real field capture, `09111632_currentFast.csv`, whose filtered trace was a red
band sitting in the middle of the raw band — visually indistinguishable from no filtering at
all. Three separate defects, only one of which was a filter problem.

**1. Sustained saturation was repaired as if it were glitch noise (Issue 60).**
`reject_full_scale()` rewrote every sample at the rail. An isolated rail sample is a glitch
and repairing it is right; a *run* of them is the ADC truthfully reporting it is out of
range, and the replacement drawn from the bracketing samples is systematically low. That
bias then went into a mean-preserving boxcar, which propagated it faithfully across the
window — the filtered line landing below the raw envelope. It now walks runs: ≤ 2 samples
repaired from the brackets of the whole run (the old per-sample 3-point median could not
even repair a run of 2 — its neighbour was another rail sample), longer runs kept and
counted. Returns `(filtered, n_replaced, sat)`.

**2. The HiRes stage averaged but never decimated (Issue 62).**
The previous entry below states HiRes correctly — *"average N consecutive samples taken at
the full rate, emit one point"* — and implemented only the averaging. 32,000 points on a
1,300-pixel axis is 24 samples per pixel column, all painted to full vertical extent, so
surviving ripple renders as a solid band and widening the window appears to do nothing.
`decimate_blocks()` now emits one point per block for the plot, with the block min/max drawn
as a band so the removed ripple stays visible rather than being quietly discarded. The CSV
and `integrate_charge()` are untouched — decimation is a display operation, and making it a
data operation would change the charge integral's sample spacing for no benefit.

Verified on a synthetic reproduction of the real capture (26 mA offset, 3.05% saturation,
137 Hz + 311 Hz content, 800 Hz, 40 s): same filter, same bandwidth, same data — 970 plotted
points instead of 32,000, and the envelope becomes readable.

**3. A 26 mA idle offset eats 13% of the range (Issue 61).**
Reported, not fixed: it is a hardware offset. New `RANGE / SATURATION` report section, placed
*before* the filter tables on purpose — if the front end clipped or the offset ate the range,
nothing below that point can be fixed by choosing a better window, and reading the filter
numbers first sends you chasing the wrong thing.

**Also:** `window_for_bandwidth()` and `--bandwidth HZ` — specify the corner frequency the
way a scope states it, resolved against the *achieved* rate read from the timestamps, rather
than a sample count that means nothing without also knowing that rate. `--no-decimate`
restores the per-sample line. Plot rendering is now shared by the CLI, the GUI's saved PNG
and the GUI's on-screen canvas, which previously each rebuilt it slightly differently.

Nine new selftest checks: glitch-vs-saturation classification, run-of-2 repair, decimation
mean preservation, and the bandwidth↔window round trip.

---

## 2026-09-11 — Replace median-5 with the actual High-Resolution operation; remove a charge-fabricating bias — `[UNCONFIRMED]`

**Stated goal:** the processed current should resemble a **Keysight scope in
High-Resolution acquisition mode** rather than Normal mode. The existing pipeline could not
produce that, and one of its steps was actively fabricating charge.

**What HiRes is.** Average N consecutive samples taken at the full rate, emit one point. A
boxcar FIR: linear, mean-preserving, with a stated transfer function. Each 4x increase in N
buys one effective bit; `f_-3dB = 0.443*fs/N`.

**Why median-5 could not deliver it.**

1. *Less efficient.* The sample median of w Gaussian values has ~pi/2 more variance than the
   mean. On this project's own measured 9.14-count idle floor: median-5 gives 1.87x,
   boxcar-5 gives 2.25x (ideal 2.24x); at w=33, 4.71x vs 5.81x. About a third of a bit
   given away at every width.
2. *Nonlinear, so it has no bandwidth.* Nothing to quote, nothing to match a scope to.
   "Similar to HiRes" is unachievable by construction.
3. *It moves the mean.* `docs/current_measurement_testing.md` already recorded median-5
   changing total charge by **+2.79%** — and this module's own docstring says a filter that
   moves the level is unusable for a quantity that gets integrated. The finding was measured
   and then not acted on. A boxcar changes charge by 0.000% at every width.

The median was chosen for a sound reason — the 223 measured dropouts, which a boxcar cannot
reject. The error was using one filter for two jobs. Despiking must be nonlinear and noise
reduction must be linear; combining them forfeits the properties of both. Now separate:
`hampel_filter()` then `boxcar_filter()`.

**The clamp-at-zero baseline bug.** `subtract_baseline()` returned
`x - baseline if x > baseline else 0.0`. On idle stretches the signal sits *at* the
baseline, so after subtraction it is symmetric noise about zero — and clamping keeps only
the positive half. For zero-mean Gaussian noise, `E[max(X,0)] = sigma/sqrt(2*pi) ~= 0.399
sigma`, i.e. **+3.65 counts of current that does not exist**, integrated for every idle
second:

| Idle | Fabricated charge |
|------|-------------------|
| 1 hour | 161 mC |
| 1 day | 3 854 mC |
| 2 days | 7 708 mC |

The largest *real* event in the reference data is 667.5 mC. On a two-day deployment the
clamp alone invents ~11 events' worth of charge, and it scales with idle time — worst
exactly when harvesting is sparse, which is the case being measured. On the 58.6 s bench
capture it was worth ~0.75 mC and hid under the noise, which is why it survived review.
Clamping is now off by default; `--clamp-baseline` reproduces old numbers.

**Also in this change:**

- `hampel_filter(v, w, n_sigma, sigma_floor)` — local median +/- n*MAD, replacing *only*
  outliers. The MAD degenerates to zero when over half a window is identical, which is
  exactly the dropped-connection signature (51.9% exact zeros in the first 5 s of the
  constant-DC capture). A scale floor taken from the quietest second of the same record
  gives it something to test against; without it every outlier in a flat run passes through.
- `boxcar_filter()` uses a running sum — O(n) instead of O(n*w). At w=65 the naive form was
  minutes of pure Python on a multi-hour capture.
- `boxcar_bandwidth_hz()` and a HIGH-RESOLUTION EQUIVALENCE report block: effective rate,
  -3 dB, first null, bits gained, despike count and scale floor — so the window can be
  chosen from a bandwidth target and matched to a scope setting.
- `hires_pipeline()` is now the single definition of the filter, shared by the report, the
  GUI and the CSV writer, which previously each assembled their own stage order.
- New `--window` default 17 (20.8 Hz, +2.0 bits), plus `--despike-window`,
  `--despike-sigma`, `--clamp-baseline`.
- Selftest extended: boxcar bandwidth/bit-gain arithmetic, constant preservation, Hampel
  behaviour including the MAD=0 case and the "keeps a real 16% ripple" case, and a
  200 000-sample Monte Carlo pinning the clamp bias at sigma/sqrt(2*pi).

**Stated plainly in the report and the doc:** peak current falls as the window widens and
that is correct — a peak through a 21 Hz filter is a 21 Hz peak, and the scope in HiRes
shows the same. The firmware's `TYPE_CURRENT_STATS.peak_mA` is an unfiltered single sample
and will always read higher; they are different quantities.

**The limit post-processing cannot cross:** the ADC has no analog anti-alias filter, so
content above ~400 Hz folded in before sampling and no digital filter can undo it. If buoy
and scope still disagree after matching bandwidths, suspect aliasing first; the fix is an RC
at the sense point. The existing "we are not aliasing" analysis still holds but is an
inference, not a measurement — the decisive test is a simultaneous scope/buoy capture of
the same discharge with matched bandwidths.

**Verification:** selftest passes; end-to-end run on 96 000 synthetic samples modelled on
the reference capture confirms charge identical to 3 decimal places across boxcar widths
5-65, despike rate 0.73% against the 0.72% outlier population measured in the real data, and
noise reduction within 1% of sqrt(w) at every width. **Not yet run against the real
`09031702` capture** — `SampleData/` is not in the repository.

---

## 2026-09-09 — Add file-processing and plot GUI — `[UNCONFIRMED]`

**Why:** Selecting and comparing high-rate current data in Excel is cumbersome. The normal
workflow should require selecting only `_currentFast.csv`; the matching calibration and RTC
files are deterministic siblings and should not need repetitive manual selection.

**What changed:** Running `current_filter_test.py` without arguments (or with `--gui`) now opens
a Tkinter GUI. It automatically locates `_currentCal.csv` and `_rtcEvt.csv`, applies the existing
full-scale rejection → centered median → baseline-subtraction pipeline, saves
`_currentFast_filtered.csv` and `_currentFast_filtered.png` next to the input, and embeds the
raw/filtered plot with Matplotlib zoom, pan, and save controls. The median window is selectable.

Added a local UTC-offset field defaulting to `-7` for the September PNNL/PDT captures. Because
the RTC event's clock fields are already firmware-local, the offset is attached as ISO-8601
metadata (for example `14:45:45.109000-07:00`) rather than added to the clock a second time.
The CLI has the equivalent `--utc-offset` option.

**Validation:** Python compilation, all primitive self-tests, a headless GUI construction test,
and end-to-end CSV/PNG generation against the `09081445` test capture are required before this
entry is presented for confirmation.

---

## 2026-09-08 — Add RTC-derived wall-clock timestamps — `[UNCONFIRMED]`

**Why:** Oscilloscope traces use wall-clock time, while `_currentFast.csv` contains only
`millis()`-relative timestamps. Comparing the two required a manual conversion even though the
same capture's `_rtcEvt.csv` already provides the intended local-time anchor.

**What changed:** `current_filter_test.py` now auto-loads the sibling `_rtcEvt.csv` (or accepts
`--rtc-csv RTC`), anchors its date/time to the RTC packet's `timestamp_ms`, and writes an
`actual_time_local` ISO-8601 column in `--write-csv` output. The report shows the mapped first
and last times and explicitly notes that RTC values are local time without a UTC offset and
that the anchor has whole-second resolution. Missing auto-detected RTC data leaves the column
blank; an explicitly missing or malformed RTC file fails loudly. Multiple RTC rows also fail
loudly because separate parsed CSVs cannot unambiguously associate samples with boot sessions.

**Validation:** Added wall-time arithmetic checks to the existing self-test. The target
`09081445_currentFast.csv` / `09081445_rtcEvt.csv` pair is used for an end-to-end generated-file
check before this entry is presented for confirmation.