#!/usr/bin/env python3
"""current_filter_test.py - standalone test bench for harvested-current post-processing.

PURPOSE
-------
Evaluate the pipeline proposed in docs/current_measurement_testing.md *before* wiring it
into vertisea_plot_v7.py's BIN -> CSV conversion. Integrating an unvalidated filter would
risk silently biasing every future dataset, so this script answers three questions first:

  1. Does the filter remove noise WITHOUT shifting the mean? A filter that moves the
     level is unusable for a quantity we integrate into charge, however clean it looks.
  2. How much does each pipeline step change the reported charge?
  3. How long does it take? That decides whether the GUI option can default to ON.

DELIBERATELY STANDALONE
-----------------------
  * stdlib only; matplotlib optional and only for --plot
  * does not import or modify the ground station
  * pure Python, so the measured runtime is a fair estimate of what the GUI would pay
    if this code were dropped in as-is

USAGE
-----
    py -3 current_filter_test.py <base>_currentFast.csv
    py -3 current_filter_test.py <csv> --plot
    py -3 current_filter_test.py <csv> --write-csv filtered.csv
    py -3 current_filter_test.py <csv> --rtc-csv capture_rtcEvt.csv --write-csv filtered.csv
    py -3 current_filter_test.py <csv> --baseline-window 0,28.5
    py -3 current_filter_test.py --selftest
    py -3 current_filter_test.py --gui

Running without arguments also opens the GUI. It selects a currentFast CSV, automatically
finds the sibling currentCal and rtcEvt files, writes a filtered CSV and PNG, and displays
the plot with zoom/pan controls.

Calibration is read from the sibling <base>_currentCal.csv when present (the log is
self-describing via TYPE_CURRENT_CAL / 0x0D), else documented defaults with a warning.
Wall-clock time is read from the sibling <base>_rtcEvt.csv when present. The RTC event's
timestamp_ms anchors its local date/time to the monotonic timestamps in currentFast.
"""

import argparse
import csv
import datetime
import io
import math
import os
import sys
import time

# Fallbacks, used only when no _currentCal.csv sits beside the input.
DEFAULT_CAL = {"vref": 2.0, "adc_max": 16383.0, "div_ratio": 1.0, "sens_mA_per_V": 100.0}

# rtcEvt stores firmware-local clock fields but no UTC-offset metadata. PNNL is UTC-7
# during PDT, including the September 2026 captures this tool was built for. This value
# labels the local time in ISO 8601 output; it does NOT shift the already-local RTC clock.
DEFAULT_LOCAL_UTC_OFFSET_HOURS = -7.0

# Reject integration intervals longer than this. Inter-block gaps in the SD log reach
# ~45 ms; treating one as a real sample interval would invent charge that never flowed.
MAX_DT_MS = 50.0

# Default boxcar width for the High-Resolution stage. At the achieved ~800 Hz this is a
# -3 dB bandwidth of ~22 Hz and +2.0 effective bits. The discharge envelope is ~12 s long
# (~2 s rise, ~10 s decay), i.e. well under 1 Hz of real signal bandwidth, so 22 Hz leaves
# roughly 20x margin over the fastest structure that physically exists at this node.
# Raise it for a smoother trace; the reported bandwidth tells you what you are giving up.
DEFAULT_BOXCAR = 17

# Hampel despike defaults. 3 sigma against a local MAD estimate: the measured dropouts are
# exact zeros between samples of 1500-3500 counts (10+ sigma) while the genuine 16.7% PMC
# ripple stays well inside 3 sigma and is preserved for the boxcar to average.
DESPIKE_WINDOW = 7
DESPIKE_SIGMA = 3.0

# A rail hit lasting more than this many consecutive samples is genuine ADC saturation,
# not an impulsive glitch, and must NOT be repaired. See reject_full_scale().
MAX_GLITCH_RUN = 2

# Warn when the idle offset eats more than this fraction of the ADC range. The offset is
# pure dead headroom: every count of it is a count the peaks cannot use.
OFFSET_WARN_FRAC = 0.05


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_current_csv(path):
    """Return (timestamps_ms, counts) from a *_currentFast.csv."""
    ts, ct = [], []
    with io.open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts.append(float(row["timestamp_ms"]))
            ct.append(int(row["counts"]))
    if not ts:
        raise SystemExit("no rows in %s" % path)
    return ts, ct


def sibling_path(current_fast_path, suffix):
    """Return the capture-base path with *suffix* appended."""
    base = current_fast_path
    for current_suffix in ("_currentFast.csv", "_currentfast.csv"):
        if base.endswith(current_suffix):
            base = base[: -len(current_suffix)]
            break
    return base + suffix


def load_cal(current_fast_path):
    """Read the sibling _currentCal.csv so conversion matches the logging firmware.

    Returns (cal_dict, source_description).
    """
    cal_path = sibling_path(current_fast_path, "_currentCal.csv")
    if os.path.exists(cal_path):
        with io.open(cal_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if rows:
            r = rows[0]
            return ({"vref": float(r["vref"]),
                     "adc_max": float(r["adc_max"]),
                     "div_ratio": float(r["div_ratio"]),
                     "sens_mA_per_V": float(r["sens_mA_per_V"])},
                    os.path.basename(cal_path))
    return dict(DEFAULT_CAL), "built-in defaults (NO _currentCal.csv found)"


def load_rtc_anchor(current_fast_path, rtc_csv=None):
    """Load the local wall-clock anchor from a parsed *_rtcEvt.csv.

    Returns ((rtc_timestamp_ms, local_datetime), source_description), or
    (None, source_description) when the auto-detected sibling does not exist. An
    explicitly requested missing file is an error. More than one RTC event indicates a
    concatenated/multi-boot log whose separate CSVs cannot be aligned unambiguously, so
    fail rather than attach plausible but potentially wrong wall-clock times.
    """
    explicit = rtc_csv is not None
    rtc_path = rtc_csv or sibling_path(current_fast_path, "_rtcEvt.csv")
    if not os.path.exists(rtc_path):
        if explicit:
            raise SystemExit("RTC CSV not found: %s" % rtc_path)
        return None, "not available (no sibling %s)" % os.path.basename(rtc_path)

    with io.open(rtc_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("no rows in RTC CSV: %s" % rtc_path)
    if len(rows) != 1:
        raise SystemExit(
            "RTC CSV has %d rows; wall-clock mapping is ambiguous for a multi-boot log: %s"
            % (len(rows), rtc_path))

    r = rows[0]
    try:
        local_dt = datetime.datetime(
            int(r["year"]), int(r["month"]), int(r["day"]),
            int(r["hour"]), int(r["minute"]), int(r["second"]))
        rtc_timestamp_ms = float(r["timestamp_ms"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit("invalid RTC CSV %s: %s" % (rtc_path, exc))
    return (rtc_timestamp_ms, local_dt), os.path.basename(rtc_path)


def utc_offset_timezone(offset_hours):
    """Return a fixed-offset tzinfo, validating a user-supplied hours value."""
    offset_hours = float(offset_hours)
    if not -24.0 < offset_hours < 24.0:
        raise ValueError("UTC offset must be greater than -24 and less than +24 hours")
    return datetime.timezone(datetime.timedelta(hours=offset_hours))


def wall_datetime_local(timestamp_ms, rtc_anchor, utc_offset_hours=None):
    """Map a millis()-based timestamp to the local datetime anchored by rtcEvt.

    rtcEvt already contains firmware-local clock fields. utc_offset_hours attaches the
    missing UTC-offset metadata; it deliberately does not shift the clock a second time.
    """
    rtc_timestamp_ms, local_dt = rtc_anchor
    mapped = local_dt + datetime.timedelta(milliseconds=timestamp_ms - rtc_timestamp_ms)
    if utc_offset_hours is not None:
        mapped = mapped.replace(tzinfo=utc_offset_timezone(utc_offset_hours))
    return mapped


def wall_time_local(timestamp_ms, rtc_anchor, utc_offset_hours=None):
    """Map a millis()-based timestamp to ISO 8601 local wall time text."""
    return wall_datetime_local(timestamp_ms, rtc_anchor, utc_offset_hours).isoformat(
        timespec="microseconds")


def counts_to_mA_factor(cal):
    """mA per ADC count."""
    return cal["vref"] * cal["div_ratio"] * cal["sens_mA_per_V"] / cal["adc_max"]


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def reject_full_scale(v, adc_max, max_glitch_run=MAX_GLITCH_RUN):
    """Repair isolated rail hits; KEEP sustained ones and report them as saturation.

    These are two different physical events and the previous version of this function
    treated them as one, which is the single biggest reason a filtered trace could end up
    sitting far below the raw envelope it is supposed to summarise.

      * A SINGLE sample pinned at the rail with neighbours far below cannot be real -
        current cannot rise 80% of range and return inside one ~1.2 ms sample interval.
        That is an impulsive glitch, and replacing it with the bracketing samples is right.

      * A RUN of consecutive samples at the rail is the opposite: it is the ADC honestly
        reporting that the input went past its reference and it has no more range. The
        true value is unknown and is >= full scale. Rewriting those samples invents data,
        and because the samples bracketing a saturated run are themselves on the way up or
        down, the invented value is systematically LOW. Feeding that into a
        mean-preserving boxcar then drags the whole event downward - the filtered line
        lands in the middle of the raw band instead of tracking it.

    So runs up to max_glitch_run are repaired and longer runs are left alone and counted.
    The caller must surface that count: a saturated capture is a RANGE fault, to be fixed
    at the sensor or with a divider, and no amount of post-processing can recover a
    voltage the ADC never saw. Reporting it as "filtered" would be a lie about the data.

    Returns (filtered, n_replaced, sat) where sat = {n_saturated, longest_run, frac}.
    """
    out = [float(x) for x in v]
    n = len(v)
    limit = float(adc_max)
    n_replaced = 0
    n_sat = 0
    longest = 0
    i = 0
    while i < n:
        if v[i] < limit:
            i += 1
            continue
        j = i
        while j < n and v[j] >= limit:
            j += 1
        run = j - i
        if run <= max_glitch_run:
            # Bracket the whole run, not each sample: a 3-point median inside a run of 2
            # sees another rail sample as its neighbour and repairs nothing.
            left = v[i - 1] if i > 0 else None
            right = v[j] if j < n else None
            if left is None and right is None:
                repl = limit
            elif left is None:
                repl = float(right)
            elif right is None:
                repl = float(left)
            else:
                repl = (float(left) + float(right)) / 2.0
            for idx in range(i, j):
                out[idx] = repl
                n_replaced += 1
        else:
            n_sat += run
            longest = max(longest, run)
        i = j
    sat = {"n_saturated": n_sat, "longest_run": longest,
           "frac": (float(n_sat) / n if n else 0.0)}
    return out, n_replaced, sat


def median_filter(v, w):
    """Sliding median, window w (forced odd); edges use a shrinking window.

    Median rather than mean because the noise is asymmetric and impulsive: one dropout
    to zero beside 3500 counts drags a 5-point mean down by 700 while the median ignores
    it. It also preserves the sharp discharge onset that a low-pass would round off.
    """
    if w <= 1:
        return list(v)
    if w % 2 == 0:
        w += 1
    half = w // 2
    n = len(v)
    out = [0] * n
    for i in range(n):
        lo = i - half
        hi = i + half + 1
        if lo < 0:
            lo = 0
        if hi > n:
            hi = n
        window = sorted(v[lo:hi])
        out[i] = window[len(window) // 2]
    return out


def boxcar_filter(v, w):
    """Sliding boxcar (moving average) of width w - the High-Resolution equivalent.

    THIS IS THE MAIN DENOISER. It is what a Keysight scope's High-Resolution acquisition
    mode does: average N consecutive samples taken at the full rate, trading bandwidth for
    vertical resolution. Each 4x increase in w buys one extra effective bit
    (bits = 0.5 * log2(w)), and for white noise the SD falls by exactly sqrt(w).

    It replaced a median-5 as the main stage on 2026-09-11. The median was chosen to
    reject the dropouts in the PMC data, which it does - but it is the wrong tool for this
    job for three reasons:

      1. It is ~20% less efficient than the mean at removing white noise (the sample
         median of w Gaussian values has variance ~pi/2 larger than the mean), so it
         delivers fewer effective bits for the same window. Measured on the real
         9.14-count idle floor: median-5 gives 1.87x, boxcar-5 gives 2.26x (ideal 2.24x).
      2. It is nonlinear, so it has no transfer function. You cannot state the resulting
         bandwidth, cannot match it to a scope setting, and cannot predict what it does to
         a waveform shape - which makes "similar to the scope in HiRes mode" unachievable
         by construction.
      3. Its noise reduction saturates. At w=33 the median reaches 4.71x where the boxcar
         reaches 5.88x.

    Despiking is still needed - a boxcar cannot reject the exact-zero dropouts - but that
    is what hampel_filter() is for, applied first. Separating "remove outliers" from
    "reduce noise" is what makes the second stage predictable.

    Bandwidth: a boxcar of width w at sample rate fs has its first null at fs/w and its
    -3 dB point at about 0.443 * fs/w. See boxcar_bandwidth_hz().
    """
    if w <= 1:
        return [float(x) for x in v]
    if w % 2 == 0:
        w += 1
    half = w // 2
    n = len(v)
    if n == 0:
        return []
    # Running sum rather than a fresh slice per sample: the naive form is O(n*w), which
    # at w=65 over a multi-hour capture is minutes of pure Python. This is O(n).
    out = [0.0] * n
    lo, hi = 0, min(n, half + 1)
    total = float(sum(v[lo:hi]))
    for i in range(n):
        new_lo, new_hi = max(0, i - half), min(n, i + half + 1)
        while hi < new_hi:
            total += v[hi]
            hi += 1
        while lo < new_lo:
            total -= v[lo]
            lo += 1
        out[i] = total / float(hi - lo)
    return out


def boxcar_bandwidth_hz(w, fs_hz):
    """-3 dB bandwidth and effective-bit gain of a width-w boxcar at fs_hz.

    Returns (f_3db_hz, f_null_hz, bits_gained). Reported so the window can be chosen from
    a bandwidth target instead of by eye, and so the result can be compared with a scope
    whose HiRes setting is stated in bandwidth.
    """
    if w <= 1:
        return (fs_hz / 2.0, float('inf'), 0.0)
    return (0.442947 * fs_hz / w, fs_hz / float(w), 0.5 * math.log(w, 2))


def decimate_blocks(ts, v, w):
    """Non-overlapping block average - what a scope ACTUALLY does in High-Resolution.

    boxcar_filter() has the right frequency response but keeps the ORIGINAL sample rate,
    so its output still carries one point per input sample. On a 60 s capture at 800 Hz
    that is 48,000 points drawn across ~1,300 screen pixels: 37 samples share every pixel
    column and matplotlib paints the full vertical extent of all 37. Any residual ripple
    therefore renders as a solid filled band - which is why a correctly filtered trace can
    still look like raw noise, and why widening the window appears not to help.

    A Keysight scope in HiRes does not do that. It averages N samples and emits ONE point,
    so the displayed record is decimated by N and the ripple inside a block is genuinely
    absent from the output rather than hidden under overdraw. This reproduces that, and it
    is the missing half of "make it look like the scope": the averaging was already right,
    the decimation was not being done at all.

    Returns (ts_out, mean, lo, hi) - block centre time, block mean (the HiRes sample), and
    block min/max. The extremes are kept deliberately: a decimated line alone hides how
    much signal is being averaged away, so the honest plot draws the mean as a line and
    the min/max as a band behind it. On a clean capture the band collapses onto the line;
    on a saturated or aliased one it stays wide, and that is information, not clutter.
    """
    if not ts:
        return [], [], [], []
    if w <= 1:
        f = [float(x) for x in v]
        return list(ts), f, list(f), list(f)
    t_out, m_out, lo_out, hi_out = [], [], [], []
    for i in range(0, len(v), w):
        blk = v[i:i + w]
        if not blk:
            break
        tb = ts[i:i + w]
        t_out.append((tb[0] + tb[-1]) / 2.0)
        m_out.append(sum(blk) / float(len(blk)))
        lo_out.append(min(blk))
        hi_out.append(max(blk))
    return t_out, m_out, lo_out, hi_out


def window_for_bandwidth(f3db_hz, fs_hz):
    """Boxcar width whose -3 dB corner lands at f3db_hz, forced odd and at least 1.

    The inverse of boxcar_bandwidth_hz(), so a bandwidth can be specified the way a scope
    states it ("HiRes, 20 Hz") instead of as a sample count that means nothing without
    also knowing the achieved rate.
    """
    if f3db_hz <= 0.0 or fs_hz <= 0.0:
        return 1
    w = int(round(0.442947 * fs_hz / f3db_hz))
    if w < 1:
        w = 1
    if w % 2 == 0:
        w += 1
    return w


def hampel_filter(v, w=7, n_sigma=3.0, sigma_floor=0.0):
    """Despike: replace only points that are outliers against their local neighbourhood.

    A Hampel filter takes the local median and the local median absolute deviation (MAD),
    scales the MAD by 1.4826 to make it a Gaussian-consistent sigma estimate, and replaces
    a sample ONLY if it is more than n_sigma away. Everything else passes through
    untouched.

    That last property is the whole point, and it is what a blanket median filter does not
    give: a median-5 rewrites every sample in the record, so it distorts the waveform
    everywhere in order to fix the 0.7% of samples that are actually bad. This touches
    only the bad ones and leaves the rest bit-exact for the boxcar stage to average.

    The measured data justifies the default n_sigma=3: the PMC-output dropouts are exact
    zeros sitting between samples of 1500-3500 counts, which is 10+ sigma, while the
    genuine 16.7% ripple is well inside 3 sigma and survives.

    `sigma_floor` handles the degenerate case where the local MAD is exactly zero, i.e.
    more than half the window holds the identical value. That happens on a genuinely quiet
    stretch - and notably when a connection drops and the ADC returns a run of exact zeros,
    which the constant-DC characterisation showed is a real failure mode (51.9% exact zeros
    in the first 5 s of that capture). With MAD = 0 there is no scale estimate, so a plain
    Hampel test either divides by zero or, if guarded, silently passes every outlier
    through. Neither is acceptable, so the caller supplies a floor - the instrument's own
    noise floor, measured from the quietest part of the same record. A deviation cannot be
    "explained by local variation" when it exceeds n_sigma times the noise the instrument
    is known to have.

    Returns (filtered, n_replaced).
    """
    if w <= 1 or len(v) < 3:
        return [float(x) for x in v], 0
    if w % 2 == 0:
        w += 1
    half = w // 2
    n = len(v)
    out = [float(x) for x in v]
    replaced = 0
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        seg = sorted(v[lo:hi])
        med = seg[len(seg) // 2]
        devs = sorted(abs(x - med) for x in seg)
        mad = devs[len(devs) // 2]
        sigma = max(1.4826 * mad, sigma_floor)
        if sigma > 0.0 and abs(v[i] - med) > n_sigma * sigma:
            out[i] = float(med)
            replaced += 1
    return out, replaced


def subtract_baseline(v, baseline, clamp=False):
    """Remove the idle offset. Does NOT clamp at zero by default.

    Not cosmetic: the offset is integrated over the whole record, so its contribution
    grows with recording length and will dominate a long log with sparse events.

    WHY CLAMPING WAS REMOVED (2026-09-11). This function used to return
    `x - baseline if x > baseline else 0.0`, which half-wave rectifies the noise and so
    does exactly what this module's own docstring says is unacceptable: it moves the mean
    of a quantity that is about to be integrated into charge.

    On an idle stretch the signal sits AT the baseline, so after subtraction it is
    symmetric noise about zero. Clamping discards the negative half, and for
    zero-mean Gaussian noise of width sigma the surviving mean is

        E[max(X, 0)] = sigma / sqrt(2*pi) ~= 0.399 * sigma

    With the measured idle floor (sigma = 9.14 counts) that is +3.65 counts of current
    that does not exist, present for every idle second of the record. It is invisible on a
    60-second bench capture - about 0.75 mC, under the noise - and ruinous on the 1-2 day
    field deployment this system is for:

        1 hour idle  ->    161 mC fabricated
        1 day  idle  ->   3854 mC
        2 days idle  ->   7708 mC     (the largest REAL event measured was 667.5 mC)

    So on a two-day log the clamp alone invents about eleven discharge events' worth of
    charge, and it scales with idle time - i.e. it is worst exactly when harvesting is
    sparse, which is the case the measurement exists to quantify.

    Plain subtraction leaves the idle stretches centred on zero, so they integrate to zero
    (plus a random walk that grows as sqrt(t), not t). Negative excursions are physically
    meaningful here: they are the other half of the noise, and discarding them is what
    creates the bias.

    `clamp=True` is retained only to reproduce pre-2026-09-11 numbers for comparison.
    """
    if clamp:
        return [x - baseline if x > baseline else 0.0 for x in v]
    return [x - baseline for x in v]


def effective_rate_hz(ts):
    """Achieved samples/second from the measured timestamps, ignoring block gaps."""
    good = [ts[i] - ts[i - 1] for i in range(1, len(ts))
            if 0.0 < ts[i] - ts[i - 1] <= MAX_DT_MS]
    if not good:
        return 0.0
    return 1000.0 / (sum(good) / len(good))


def hires_pipeline(ts, ct, adc_max, baseline, boxcar_w,
                   despike_w=DESPIKE_WINDOW, n_sigma=DESPIKE_SIGMA, clamp=False,
                   sigma_floor=None):
    """The production filter: despike -> boxcar -> baseline. Returns (out, info).

    The order is not interchangeable.

      1. reject_full_scale  - repair isolated rail glitches; leave sustained saturation
                              alone and report it, because inventing values there biases
                              the boxcar that follows.
      2. hampel_filter      - remove the impulsive outliers (dropouts and spikes) that a
                              linear filter cannot reject. Touches only outliers.
      3. boxcar_filter      - the High-Resolution stage. Averaging is what buys effective
                              bits, and it is only legitimate once the impulses are gone:
                              a single exact zero beside 3500 counts drags a 5-point mean
                              down by 700, which is the objection that originally led to
                              using a median for everything.
      4. subtract_baseline  - last, and without clamping, so the idle stretches integrate
                              to zero instead of to a positive bias.

    Doing 2 and 3 as separate stages is the change that makes this predictable: outlier
    rejection is nonlinear and must be, averaging is linear and must be, and a median
    filter doing both at once is the reason the result could not be matched to a scope
    setting.
    """
    v1, n_fs, sat = reject_full_scale(ct, adc_max)
    # Scale floor for the despiker: the instrument's own noise, measured from the quietest
    # second of this same record rather than assumed. Without it, a run of exact zeros
    # from a dropped connection has MAD = 0 and every outlier in it passes through.
    if sigma_floor is None:
        sigma_floor = stats(quietest_window(ts, v1))["sd"]
    v2, n_spike = hampel_filter(v1, despike_w, n_sigma, sigma_floor)
    v3 = boxcar_filter(v2, boxcar_w)
    v4 = subtract_baseline(v3, baseline, clamp=clamp)
    fs = effective_rate_hz(ts)
    f3db, fnull, bits = boxcar_bandwidth_hz(boxcar_w, fs)
    return v4, {"n_full_scale": n_fs, "saturation": sat,
                "n_despiked": n_spike, "fs_hz": fs,
                "sigma_floor": sigma_floor,
                "f3db_hz": f3db, "f_null_hz": fnull, "bits_gained": bits,
                "boxcar_w": boxcar_w, "despike_w": despike_w, "n_sigma": n_sigma}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def integrate_charge(ts, v, k_mA_per_count, max_dt_ms=MAX_DT_MS):
    """Trapezoidal integral -> millicoulombs, using the MEASURED sample interval.

    Never assume 1/CURRENT_RATE_HZ: the requested rate is a deliberate over-request and
    the achieved rate is lower. Using nominal dt is the same class of error as the IMU
    nominal-vs-actual bug (IDENTIFIED_ISSUES.md Issue 34).
    """
    q = 0.0
    skipped = 0
    for i in range(1, len(ts)):
        dt = ts[i] - ts[i - 1]
        if 0.0 < dt <= max_dt_ms:
            q += 0.5 * (v[i] + v[i - 1]) * (dt / 1000.0)
        else:
            skipped += 1
    return q * k_mA_per_count, skipped


def stats(v):
    n = len(v)
    if n == 0:
        return {"n": 0, "mean": 0.0, "sd": 0.0, "min": 0.0, "median": 0.0, "max": 0.0}
    m = sum(v) / float(n)
    sd = (sum((x - m) ** 2 for x in v) / n) ** 0.5
    s = sorted(v)
    return {"n": n, "mean": m, "sd": sd, "min": s[0], "median": s[n // 2], "max": s[-1]}


def _median(v):
    s = sorted(v)
    return s[len(s) // 2]


def bin_medians(ts, v, bin_s=1.0):
    """Group into fixed time bins; return [(bin_index, values)] sorted by bin."""
    t0 = ts[0]
    bins = {}
    for t, c in zip(ts, v):
        b = int((t - t0) / (bin_s * 1000.0))
        bins.setdefault(b, []).append(c)
    return sorted(bins.items())


def estimate_baseline(ts, v):
    """Idle level = the median of the 1-second bin with the lowest median.

    Robust to the record being mostly-on or mostly-off, and to isolated spikes, in a way
    a global percentile is not.

    IMPORTANT LIMITATION, found while testing the constant-DC capture: if any 1-s bin is
    dominated by exact zeros - which happens when the input is switched fully off, or when
    an intermittent connection drops out - this returns 0 and no offset is removed. That is
    the correct answer for a truly-off input (there is no offset to remove) but it is NOT a
    sensor-offset measurement. To characterise the sensor's own offset the input must be
    idle-but-connected, not disconnected. Use --baseline-window to force a known-good span.

    Returns (baseline, bin_index, warning_or_None).
    """
    best, best_b = None, None
    for b, vals in bin_medians(ts, v):
        s = sorted(vals)
        med = s[len(s) // 2]
        if best is None or med < best:
            best, best_b = med, b
    warn = None
    if best is not None and best <= 0:
        n_zero = sum(1 for x in v if x == 0)
        warn = ("baseline auto-detected as 0 (%d exact zeros in the record, %.1f%%). "
                "Either the input was switched fully off, or a connection dropped out. "
                "No offset was removed - to measure sensor offset, capture an "
                "idle-but-CONNECTED span and pass it via --baseline-window."
                % (n_zero, 100.0 * n_zero / len(v)))
    return float(best), best_b, warn


def quietest_window(ts, v, bin_s=1.0):
    """Values from the 1-s bin with the smallest spread - a noise-floor sample."""
    best, vals_out = None, []
    for b, vals in bin_medians(ts, v, bin_s):
        sd = stats(vals)["sd"]
        if best is None or sd < best:
            best, vals_out = sd, vals
    return vals_out


def steadiest_high_plateau(ts, v, bin_s=1.0):
    """Longest run of consecutive 1-s bins that are both high and stable.

    This is the mean-preservation test bed: on a constant input a filter must reduce
    scatter WITHOUT moving the mean. Returns concatenated values, or [] if the record
    has no steady high section (e.g. a pure discharge capture).
    """
    bins = bin_medians(ts, v, bin_s)
    if not bins:
        return []
    overall_max = max(max(vals) for _, vals in bins)
    thresh = 0.5 * overall_max
    runs, cur = [], []
    for b, vals in bins:
        st = stats(vals)
        if st["mean"] > thresh and st["sd"] < 0.05 * max(st["mean"], 1.0):
            cur.append(vals)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if not runs:
        return []
    best = max(runs, key=lambda r: sum(len(x) for x in r))
    flat = []
    for chunk in best:
        flat.extend(chunk)
    return flat


def detect_events(ts, v, baseline, frac=0.02, merge_gap_s=0.5, min_dur_s=0.2):
    """Find discharge events as contiguous excursions above baseline.

    The threshold is a fraction of the peak excursion rather than an absolute current, so
    the same settings work across very different discharge magnitudes.
    """
    peak = max(v) if v else 0.0
    if peak <= baseline:
        return []
    thresh = baseline + frac * (peak - baseline)
    spans, start = [], None
    for i, c in enumerate(v):
        if c > thresh and start is None:
            start = i
        elif c <= thresh and start is not None:
            spans.append((start, i - 1))
            start = None
    if start is not None:
        spans.append((start, len(v) - 1))
    # Merge spans separated by a short gap: switching dropouts split one real event.
    merged = []
    for a, b in spans:
        if merged and (ts[a] - ts[merged[-1][1]]) / 1000.0 <= merge_gap_s:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return [(a, b) for a, b in merged if (ts[b] - ts[a]) / 1000.0 >= min_dur_s]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def hr(title=""):
    return ("=== %s " % title).ljust(78, "=") if title else "=" * 78


def _report_input(lines, path, ts, ct, cal, cal_src, k):
    n = len(ct)
    elapsed = (ts[-1] - ts[0]) / 1000.0
    lines.append(hr("INPUT"))
    lines.append("  file        : %s" % os.path.basename(path))
    lines.append("  calibration : %s" % cal_src)
    lines.append("     vref %.3f V, adc_max %.0f, div_ratio %.3f, sens %.1f mA/V"
                 % (cal["vref"], cal["adc_max"], cal["div_ratio"], cal["sens_mA_per_V"]))
    lines.append("     -> 1 count = %.6f mA, full scale = %.2f mA" % (k, k * cal["adc_max"]))
    lines.append("  samples     : %d over %.2f s (%.1f Hz mean)"
                 % (n, elapsed, (n - 1) / elapsed if elapsed else 0.0))
    dts = sorted(ts[i] - ts[i - 1] for i in range(1, n))
    lines.append("  dt ms       : median %.4f, p99 %.4f, max %.4f"
                 % (dts[n // 2], dts[int(0.99 * n)], dts[-1]))
    nz = sum(1 for x in ct if x == 0)
    lines.append("  at/over full scale: %d   exact zeros: %d (%.2f%%)"
                 % (sum(1 for x in ct if x >= cal["adc_max"]), nz, 100.0 * nz / n))
    # The ABSOLUTE level, before any baseline is removed. Printed because
    # _currentFast.csv stores raw counts and every later table is baseline-relative, so
    # a bench test against a known applied voltage has nothing to compare otherwise.
    st_all = stats(ct)
    lines.append("  absolute level    : mean %.1f counts = %.3f mA  (sd %.1f, "
                 "median %.0f)  <- compare a bench DC input HERE, before baseline removal"
                 % (st_all["mean"], st_all["mean"] * k, st_all["sd"], st_all["median"]))
    lines.append("     a DC input of V volts should read V / %.4f * %.0f counts"
                 % (cal["vref"], cal["adc_max"]))
    if nz > 0.2 * n:
        lines.append("  WARNING: >20%% exact zeros. A large population of exact zeros with")
        lines.append("  excursions to the true level indicates an INTERMITTENT CONNECTION,")
        lines.append("  not electrical noise (noise gives a tight unimodal spread). Check")
        lines.append("  wiring and consider discarding the affected span.")
    return elapsed


def _report_mean_preservation(lines, plateau):
    lines.append("")
    lines.append(hr("MEAN PRESERVATION (the go/no-go test)"))
    if len(plateau) < 200:
        lines.append("  No steady high plateau in this record, so mean preservation cannot be")
        lines.append("  checked here. Run this on a CONSTANT-INPUT capture (function generator)")
        lines.append("  before trusting any filter for charge integration.")
        return
    p0 = stats(plateau)
    lines.append("  plateau: n=%d  mean %.2f counts  sd %.2f (%.3f%% of reading)"
                 % (p0["n"], p0["mean"], p0["sd"], 100.0 * p0["sd"] / p0["mean"]))
    lines.append("")
    lines.append("  %-16s %10s %8s %9s %11s"
                 % ("filter", "mean", "sd", "sd ratio", "mean shift"))
    # Median and boxcar at matched widths, so the efficiency gap is visible rather than
    # asserted. The boxcar column should approach the sqrt(w) ideal; the median falls
    # about 20% short of it, which is the whole reason the main stage changed.
    for label, fn in (("median-5", lambda x: median_filter(x, 5)),
                      ("boxcar-5", lambda x: boxcar_filter(x, 5)),
                      ("median-17", lambda x: median_filter(x, 17)),
                      ("boxcar-17", lambda x: boxcar_filter(x, 17)),
                      ("median-33", lambda x: median_filter(x, 33)),
                      ("boxcar-33", lambda x: boxcar_filter(x, 33))):
        st = stats(fn(plateau))
        lines.append("  %-16s %10.2f %8.2f %9.2fx %+10.4f%%"
                     % (label, st["mean"], st["sd"],
                        p0["sd"] / st["sd"] if st["sd"] else float("inf"),
                        100.0 * (st["mean"] - p0["mean"]) / p0["mean"]))
    lines.append("")
    lines.append("  A usable filter has sd ratio > 1 AND mean shift ~= 0. A large mean shift")
    lines.append("  disqualifies a filter for charge work no matter how clean it looks.")


def _report_events(lines, ts, v3, k):
    lines.append("")
    lines.append(hr("EVENTS (after step 3)"))
    ev = detect_events(ts, v3, 0.0)
    if not ev:
        lines.append("  none detected above the threshold.")
        return
    lines.append("  %-6s %8s %8s %12s %11s %10s %10s"
                 % ("event", "start s", "dur s", "charge mC", "charge mAh",
                    "peak mA", "mean mA"))
    for j, (a, b) in enumerate(ev, 1):
        tt, vv = ts[a:b + 1], v3[a:b + 1]
        q, _ = integrate_charge(tt, vv, k)
        dur = (tt[-1] - tt[0]) / 1000.0
        lines.append("  %-6d %8.2f %8.2f %12.3f %11.5f %10.2f %10.2f"
                     % (j, (tt[0] - ts[0]) / 1000.0, dur, q, q / 3600.0,
                        max(vv) * k, q / dur if dur else 0.0))
    total = (ts[-1] - ts[0]) / 1000.0
    longest = max((ts[b] - ts[a]) / 1000.0 for a, b in ev)
    if longest > 0.5 * total:
        lines.append("")
        lines.append("  CAVEAT: the longest 'event' covers %.0f%% of the record. The detector"
                     % (100.0 * longest / total))
        lines.append("  assumes brief excursions above an idle floor, so on a mostly-ON capture")
        lines.append("  (e.g. a constant-DC test) it merges everything into one span and the")
        lines.append("  per-event numbers are not meaningful. Event splitting is only useful on")
        lines.append("  discharge-style records.")
    lines.append("")
    lines.append("  Charge only. Energy needs integral(V*I dt) and there is no voltage sense")
    lines.append("  on this node, so any mJ figure assumes a constant battery voltage and is")
    lines.append("  an estimate, not a measurement.")


def _report_cost(lines, n, variants):
    lines.append("")
    lines.append(hr("COST (pure Python; informs the GUI default)"))
    for w, _q, dur in variants:
        lines.append("  median-%-2d over %d samples: %.3f s  (%.0f k samples/s)"
                     % (w, n, dur, n / dur / 1000.0 if dur else 0.0))
    w5 = next((d for w, _q, d in variants if w == 5), None)
    if not w5:
        return
    rate = n / w5
    lines.append("")
    lines.append("  Extrapolating median-5 at %.0f k samples/s:" % (rate / 1000.0))
    for mins, label in ((10, "10 min"), (60, "1 hour"), (600, "10 hours")):
        samples = mins * 60 * 800
        lines.append("     %-8s log at 800 Hz (%s samples) -> %.1f s"
                     % (label, "{:,}".format(samples), samples / rate))
    lines.append("  Use this to decide whether the GUI option can default to ON (U21).")


def _report_range(lines, ts, ct, cal, k, baseline):
    """Is the measurement inside the ADC's range at all? Answer this before filtering.

    Two faults show up here and neither is fixable downstream:

      SATURATION - the input went past the reference, so the samples are a floor, not a
      measurement. Averaging a clipped waveform returns a number that is confidently wrong
      and looks perfectly well-behaved, which is worse than a visibly broken one.

      OFFSET - a DC idle level is dead headroom. At 200 mA full scale a 26 mA offset means
      peaks clip at 174 mA of real current, not 200, and the clipping arrives 13% earlier
      than the datasheet range suggests. Subtracting it in software restores the numbers
      but NOT the range that was already lost at the ADC.
    """
    adc_max = cal["adc_max"]
    fs = effective_rate_hz(ts)
    _, n_glitch, sat = reject_full_scale(ct, adc_max)
    lines.append("")
    lines.append(hr("RANGE / SATURATION"))
    lines.append("  full scale        : %.0f counts = %.1f mA" % (adc_max, adc_max * k))
    lines.append("  idle offset       : %.0f counts = %.2f mA = %.1f%% of range"
                 % (baseline, baseline * k, 100.0 * baseline / adc_max if adc_max else 0.0))
    lines.append("  usable headroom   : %.1f mA above the idle level"
                 % ((adc_max - baseline) * k))
    lines.append("  rail glitches     : %d isolated samples repaired (runs <= %d)"
                 % (n_glitch, MAX_GLITCH_RUN))
    sat_ms = (1000.0 * sat["n_saturated"] / fs) if fs else 0.0
    lines.append("  SATURATED samples : %d (%.2f%% of record, %.0f ms total, "
                 "longest run %d samples)"
                 % (sat["n_saturated"], 100.0 * sat["frac"], sat_ms, sat["longest_run"]))

    if sat["frac"] > 0.001:
        lines.append("")
        lines.append("  *** THE CAPTURE IS CLIPPED. %.2f%% of samples sat at the rail for"
                     % (100.0 * sat["frac"]))
        lines.append("  *** more than %d consecutive samples, so the true current there is"
                     % MAX_GLITCH_RUN)
        lines.append("  *** unknown and >= %.1f mA. Every number below - peak, charge, I2t -" % (adc_max * k))
        lines.append("  *** is therefore a LOWER BOUND, not a measurement, and no filter")
        lines.append("  *** setting changes that. Fix it at the hardware:")
        lines.append("  ***   - add a divider ahead of A14, or drop CURRENT_SENS_MA_PER_V,")
        lines.append("  ***     then update TYPE_CURRENT_CAL so the scale follows;")
        lines.append("  ***   - or null the idle offset, which buys back %.1f mA of range."
                     % (baseline * k))
    if adc_max and baseline / adc_max > OFFSET_WARN_FRAC:
        lines.append("")
        lines.append("  WARNING: the idle offset consumes %.1f%% of the ADC range. That is"
                     % (100.0 * baseline / adc_max))
        lines.append("  headroom the peaks cannot use, and it is the difference between")
        lines.append("  clipping at %.0f mA and clipping at %.0f mA. It also means the"
                     % ((adc_max - baseline) * k, adc_max * k))
        lines.append("  post-subtraction trace goes NEGATIVE wherever the input dips below")
        lines.append("  idle - that is real signal, not a filter artefact, and clamping it")
        lines.append("  away would bias the charge (see subtract_baseline).")
    return sat


def report(path, args):
    lines = []
    ts, ct = load_current_csv(path)
    cal, cal_src = load_cal(path)
    rtc_anchor, rtc_src = load_rtc_anchor(path, args.rtc_csv)
    utc_offset_hours = getattr(args, "utc_offset", DEFAULT_LOCAL_UTC_OFFSET_HOURS)
    utc_offset_timezone(utc_offset_hours)  # validate even if the RTC CSV is absent
    k = counts_to_mA_factor(cal)
    n = len(ct)
    elapsed = _report_input(lines, path, ts, ct, cal, cal_src, k)

    # --bandwidth is resolved here, against the ACHIEVED rate read from the timestamps,
    # not the nominal request. A width quoted without its sample rate is meaningless, so
    # let the user state the corner frequency and derive the width from the data.
    if getattr(args, "bandwidth", None):
        args.window = window_for_bandwidth(args.bandwidth, effective_rate_hz(ts))

    lines.append("")
    lines.append(hr("WALL-CLOCK TIME"))
    if rtc_anchor:
        rtc_ts, rtc_dt = rtc_anchor
        lines.append("  RTC anchor  : %s at timestamp_ms %.4f   [%s]"
                     % (rtc_dt.isoformat(timespec="seconds"), rtc_ts, rtc_src))
        lines.append("  first sample: %s"
                     % wall_time_local(ts[0], rtc_anchor, utc_offset_hours))
        lines.append("  last sample : %s"
                     % wall_time_local(ts[-1], rtc_anchor, utc_offset_hours))
        lines.append("  rtcEvt clock fields are already firmware-local; UTC offset %+.2f h"
                     % utc_offset_hours)
        lines.append("  is attached as ISO 8601 metadata and is not added to the clock twice.")
        lines.append("  Sub-second wall time is interpolated from timestamp_ms; the RTC anchor")
        lines.append("  itself is recorded only to whole-second resolution.")
    else:
        lines.append("  %s" % rtc_src)
        lines.append("  --write-csv will leave actual_time_local blank.")

    # ---- baseline -------------------------------------------------------
    if args.baseline_window:
        a, b = [float(x) for x in args.baseline_window.split(",")]
        t0 = ts[0]
        win = [c for t, c in zip(ts, ct) if a <= (t - t0) / 1000.0 < b]
        if not win:
            raise SystemExit("baseline window %s contains no samples" % args.baseline_window)
        bst = stats(win)
        baseline, bnoise = bst["median"], bst["sd"]
        bsrc = "user window %.2f-%.2f s" % (a, b)
    else:
        baseline, bidx, bwarn = estimate_baseline(ts, ct)
        bnoise = stats(quietest_window(ts, ct))["sd"]
        bsrc = "auto (lowest 1-s bin median, bin %d)" % bidx
    if getattr(args, "no_baseline", False):
        # Absolute mode: report what the ADC actually sees. Used for bench calibration
        # against a known input, where the offset IS the measurement.
        baseline, bsrc = 0.0, "disabled by --no-baseline (absolute counts)"
    lines.append("")
    lines.append(hr("BASELINE"))
    lines.append("  estimate : %.2f counts = %.4f mA   [%s]" % (baseline, baseline * k, bsrc))
    lines.append("  noise sd : %.2f counts = %.4f mA (quietest 1-s bin)" % (bnoise, bnoise * k))
    if not args.baseline_window and bwarn:
        lines.append("  WARNING: %s" % bwarn)

    # ---- range health ---------------------------------------------------
    # Printed BEFORE the filter tables on purpose. If the front end clipped or the offset
    # ate the range, nothing below this point can be fixed by choosing a better window,
    # and reading the filter numbers first sends you chasing the wrong thing.
    # A constant-DC bench capture is the one input this tool will silently destroy: the
    # baseline estimator takes the lowest 1-s bin median, which on a flat record IS the
    # signal, so step 4 subtracts the whole thing and every later number reads ~0. That
    # is correct behaviour for a deployment log and exactly wrong for a calibration
    # check, and nothing else in the report says so.
    bins = bin_medians(ts, ct)
    if len(bins) >= 2 and baseline > 0:
        meds = sorted(_median(vals) for _, vals in bins)
        span = meds[-1] - meds[0]
        if span < 0.05 * baseline:
            lines.append("")
            lines.append("  *** CONSTANT-DC CAPTURE DETECTED. The 1-s bin medians span only")
            lines.append("  *** %.1f counts (%.2f%% of the %.0f-count level), i.e. there is no"
                         % (span, 100.0 * span / baseline, baseline))
            lines.append("  *** event in this record - the whole capture IS the baseline.")
            lines.append("  *** Step 4 below will subtract it and leave ~0 mA. For a bench")
            lines.append("  *** check against a known applied voltage, read 'absolute level'")
            lines.append("  *** above, or re-run with --no-baseline to keep the DC level.")

    _report_range(lines, ts, ct, cal, k, baseline)

    _report_mean_preservation(lines, steadiest_high_plateau(ts, ct))

    # ---- pipeline ladder ------------------------------------------------
    lines.append("")
    lines.append(hr("PIPELINE: effect of each step on total charge"))
    q_raw, skipped = integrate_charge(ts, ct, k)
    lines.append("  intervals rejected as block gaps (>%.0f ms): %d" % (MAX_DT_MS, skipped))
    lines.append("")
    lines.append("  %-42s %12s %10s %9s" % ("step", "charge mC", "peak mA", "delta"))
    lines.append("  %-42s %12.3f %10.2f %9s" % ("0. raw", q_raw, max(ct) * k, "-"))

    def pct(q):
        return 100.0 * (q - q_raw) / q_raw if q_raw else 0.0

    v1, n_fs, sat = reject_full_scale(ct, cal["adc_max"])
    q1, _ = integrate_charge(ts, v1, k)
    lines.append("  %-42s %12.3f %10.2f %+8.2f%%"
                 % ("1. repair rail glitches (%d replaced)" % n_fs, q1, max(v1) * k, pct(q1)))

    # Same scale floor the production pipeline uses, so this table's despike count
    # matches the one reported below instead of being several times larger.
    sigma_floor = stats(quietest_window(ts, v1))["sd"]
    vd, n_spike = hampel_filter(v1, args.despike_window, args.despike_sigma, sigma_floor)
    qd, _ = integrate_charge(ts, vd, k)
    lines.append("  %-42s %12.3f %10.2f %+8.2f%%"
                 % ("2. + hampel despike (%d replaced)" % n_spike, qd, max(vd) * k, pct(qd)))

    fs = effective_rate_hz(ts)
    variants = []
    for w in (5, 9, 17, 33, 65):
        t_start = time.perf_counter()
        vv = boxcar_filter(vd, w)
        dur = time.perf_counter() - t_start
        qq, _ = integrate_charge(ts, vv, k)
        variants.append((w, qq, dur))
        f3db, _, bits = boxcar_bandwidth_hz(w, fs)
        lines.append("  %-42s %12.3f %10.2f %+8.2f%%"
                     % ("3. + boxcar-%-2d  (%5.1f Hz, +%.1f bit)" % (w, f3db, bits),
                        qq, max(vv) * k, pct(qq)))

    v3, info = hires_pipeline(ts, ct, cal["adc_max"], baseline, args.window,
                              args.despike_window, args.despike_sigma,
                              clamp=args.clamp_baseline, sigma_floor=sigma_floor)
    v2 = boxcar_filter(vd, args.window)
    q2, _ = integrate_charge(ts, v2, k)
    q3, _ = integrate_charge(ts, v3, k)
    lines.append("  %-42s %12.3f %10.2f %+8.2f%%"
                 % ("4. + subtract baseline (%.2f counts)" % baseline,
                    q3, max(v3) * k, pct(q3)))

    lines.append("")
    lines.append(hr("HIGH-RESOLUTION EQUIVALENCE"))
    lines.append("  This is the Keysight HiRes operation: average N consecutive samples")
    lines.append("  acquired at the full rate, trading bandwidth for vertical resolution.")
    lines.append("  effective sample rate : %.1f Hz (measured, not the 1000 Hz request)"
                 % info["fs_hz"])
    lines.append("  boxcar width          : %d samples" % info["boxcar_w"])
    lines.append("  output rate if decimated: %.1f Hz (%d points, was %d)"
                 % (info["fs_hz"] / max(info["boxcar_w"], 1),
                    (n + info["boxcar_w"] - 1) // max(info["boxcar_w"], 1), n))
    lines.append("  -3 dB bandwidth       : %.2f Hz   (first null %.2f Hz)"
                 % (info["f3db_hz"], info["f_null_hz"]))
    lines.append("  effective bits gained : +%.2f  (14.0 -> %.1f nominal)"
                 % (info["bits_gained"], 14.0 + info["bits_gained"]))
    lines.append("  despiked samples      : %d of %d (%.2f%%), scale floor %.2f counts"
                 % (info["n_despiked"], n,
                    100.0 * info["n_despiked"] / n if n else 0.0, info["sigma_floor"]))
    lines.append("")
    lines.append("  CHARGE IS UNCHANGED by the boxcar at every width in the table above -")
    lines.append("  averaging is mean-preserving by construction, which is the property an")
    lines.append("  integrated quantity requires. The median-5 this replaced moved the")
    lines.append("  measured charge by +2.79% (docs/current_measurement_testing.md).")
    lines.append("")
    lines.append("  PEAK, by contrast, IS bandwidth-dependent and falls as the window")
    lines.append("  widens - that is real, not an artefact: a peak read through a 21 Hz")
    lines.append("  filter is a 21 Hz peak. A scope in HiRes reports the same reduction.")
    lines.append("  Quote the bandwidth whenever quoting a peak, and note that the")
    lines.append("  firmware's TYPE_CURRENT_STATS peak_mA is an UNFILTERED single sample,")
    lines.append("  so it will always read higher than this column.")
    lines.append("")
    lines.append("  DECIMATION is the other half of HiRes and is easy to forget: the scope")
    lines.append("  emits ONE point per averaged block, this tool's CSV keeps one point per")
    lines.append("  input sample. Same frequency response, %dx more points - and %d points"
                 % (info["boxcar_w"], n))
    lines.append("  on a 1300-pixel axis puts %d samples in every pixel column, so residual"
                 % max(1, n // 1300))
    lines.append("  ripple paints a solid band and a correctly filtered trace still looks")
    lines.append("  like noise. The plot decimates for exactly this reason; pass")
    lines.append("  --no-decimate to see the per-sample line instead.")
    lines.append("")
    lines.append("  To match a scope capture, set the scope's HiRes bandwidth to the")
    lines.append("  -3 dB figure above, or pick --window from the bandwidth you want:")
    lines.append("      window = 0.443 * %.0f / f_3dB" % info["fs_hz"])
    lines.append("  ALIASING CAVEAT: the ADC has no analog anti-alias filter, so anything")
    lines.append("  above %.0f Hz folded into the band BEFORE sampling and no digital"
                 % (info["fs_hz"] / 2.0))
    lines.append("  filter can remove it. A scope in HiRes averages at its full rate and")
    lines.append("  does not have this problem. If the two disagree, suspect this first;")
    lines.append("  the fix is an RC low-pass at the sense point, not more filtering.")
    lines.append("")
    lines.append("  Baseline removal alone accounts for %.3f mC over %.1f s (%.1f%% of raw)."
                 % (q2 - q3, elapsed, 100.0 * (q2 - q3) / q_raw if q_raw else 0.0))

    drops = spikes = 0
    for i in range(1, n - 1):
        nb = (v1[i - 1] + v1[i + 1]) / 2.0
        if nb > 500:
            if v1[i] < 0.3 * nb:
                drops += 1
            elif v1[i] > 2.0 * nb:
                spikes += 1
    lines.append("  dropouts (<30%% of neighbours): %d    positive spikes (>2x): %d"
                 % (drops, spikes))
    if drops > spikes:
        lines.append("  Dropouts outnumber spikes, so median filtering RAISES the charge -")
        lines.append("  this inverts the usual 'despiking removes energy' assumption.")

    _report_events(lines, ts, v3, k)
    _report_cost(lines, n, variants)

    if args.write_csv:
        with io.open(args.write_csv, "w", encoding="utf-8", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["timestamp_ms", "actual_time_local", "counts_raw",
                         "counts_filtered", "current_mA"])
            for t, a, b in zip(ts, ct, v3):
                actual_time = (wall_time_local(t, rtc_anchor, utc_offset_hours)
                               if rtc_anchor else "")
                wr.writerow(["%.4f" % t, actual_time, a, "%.2f" % b,
                             "%.6f" % (b * k)])
        lines.append("")
        lines.append("  wrote %s (raw + filtered: despike + boxcar-%d = %.1f Hz, "
                     "baseline removed%s)"
                     % (args.write_csv, args.window, info["f3db_hz"],
                        ", RTC wall time added" if rtc_anchor else ""))

    if args.plot or args.save_plot:
        lines.append("")
        lines.append(_do_plot(ts, ct, v3, k, path, save_to=args.save_plot,
                              block_w=args.window, info=info, cal=cal,
                              decimate=not getattr(args, "no_decimate", False)))

    return "\n".join(lines)


def plot_series(ts, raw, final, k, block_w=1, decimate=True):
    """Everything a raw-vs-filtered plot needs, in mA, with the filtered side decimated.

    Split out of the drawing code because three callers need the same numbers - the CLI
    plot, the GUI's saved PNG and the GUI's on-screen canvas - and they previously each
    rebuilt them slightly differently.

    Returns (raw_mA, idx, fil_mA, lo_mA, hi_mA) where idx indexes into ts for the filtered
    series: the full range when not decimating, one entry per block when decimating. lo/hi
    are None when not decimating, because without blocks there is no spread to show.
    """
    raw_mA = [c * k for c in raw]
    w = block_w if (decimate and block_w and block_w > 1) else 1
    if w <= 1:
        return raw_mA, list(range(len(ts))), [c * k for c in final], None, None
    tb, mb, lob, hib = decimate_blocks(ts, final, w)
    # Block centre times are recomputed as indices so the caller can map them onto either
    # an elapsed-seconds axis or a wall-clock axis without this function knowing which.
    idx = list(range(0, len(ts), w))
    idx = [min(i + w // 2, len(ts) - 1) for i in idx][:len(mb)]
    return (raw_mA, idx, [c * k for c in mb], [c * k for c in lob], [c * k for c in hib])


def _draw_current_axes(ax, x_raw, raw_mA, x_fil, fil_mA, lo_mA, hi_mA,
                       title, xlabel, note=None):
    """Shared rendering: faint raw for context, a decimated filtered line, ripple band.

    Draw order matters. The raw series is the busiest thing on the axes and, at full
    opacity over tens of thousands of points, it swamps the result it is meant to provide
    context for - so it goes underneath at 45% alpha and thin. The filtered line goes on
    top at full strength. The min-max band sits between them so the spread that averaging
    removed stays visible instead of being quietly discarded.

    The zero line is drawn because after baseline subtraction zero is a meaningful level -
    idle should sit ON it, and a trace that does not is telling you the baseline estimate
    picked the wrong span.
    """
    ax.plot(x_raw, raw_mA, lw=0.4, color="#1f77b4", alpha=0.45, zorder=1,
            label="raw (%d pts)" % len(raw_mA))
    if lo_mA is not None and hi_mA is not None:
        ax.fill_between(x_fil, lo_mA, hi_mA, color="#d62728", alpha=0.20, lw=0, zorder=2,
                        label="filtered spread (min-max per block)")
    ax.plot(x_fil, fil_mA, lw=1.2, color="#d62728", zorder=4,
            label="filtered (%d pts)" % len(fil_mA))
    ax.axhline(0.0, color="#555555", lw=0.6, alpha=0.6, zorder=0)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Current (mA)")
    ax.set_title(title)
    ax.legend(loc="upper left", framealpha=0.9, fontsize=8)
    ax.grid(alpha=0.3)
    if note:
        ax.text(0.995, 0.97, note, transform=ax.transAxes, ha="right", va="top",
                fontsize=8, color="#333333", linespacing=1.4,
                bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#bbbbbb",
                          alpha=0.88))


def _plot_note(info, cal, k):
    """Corner annotation: the settings the trace was made with, and any range fault."""
    if not info:
        return None
    bits = ["HiRes: boxcar %d @ %.0f Hz  ->  %.1f Hz -3 dB, +%.1f bit"
            % (info["boxcar_w"], info["fs_hz"], info["f3db_hz"], info["bits_gained"])]
    sat = info.get("saturation") or {}
    if sat.get("frac", 0.0) > 0.001:
        bits.append("CLIPPED: %.1f%% of samples at %.0f mA full scale - values are a floor"
                    % (100.0 * sat["frac"], cal["adc_max"] * k))
    return "\n".join(bits)


def _do_plot(ts, raw, final, k, path, save_to=None, block_w=1, info=None, decimate=True,
             cal=None):
    """Raw context in blue; the HiRes result in red as a decimated line plus ripple band.

    The red trace is decimated rather than drawn per sample because a 48,000-point line on
    a 1,300-pixel axis puts 37 samples in every pixel column, and matplotlib paints the
    full vertical extent of each column - so a correctly filtered trace renders as a solid
    block of colour and widening the window appears to do nothing. Emitting one point per
    averaged block is what the scope displays in HiRes. See decimate_blocks().
    """
    try:
        import matplotlib
        matplotlib.use("Agg" if save_to else "TkAgg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # environment dependent; never fatal
        return "  plot unavailable: %s" % exc
    t0 = ts[0]
    x = [(t - t0) / 1000.0 for t in ts]
    raw_mA, idx, fil_mA, lo_mA, hi_mA = plot_series(ts, raw, final, k, block_w, decimate)
    x_fil = [x[i] for i in idx]

    fig, ax = plt.subplots(figsize=(14, 6))
    _draw_current_axes(ax, x, raw_mA, x_fil, fil_mA, lo_mA, hi_mA,
                       "%s  -  raw vs filtered" % os.path.basename(path),
                       "time (s)", _plot_note(info, cal or DEFAULT_CAL, k))
    fig.tight_layout()
    if save_to:
        fig.savefig(save_to, dpi=140)
        plt.close(fig)
        return "  saved plot: %s" % save_to
    plt.show()
    return "  plot shown (close the window to continue)"


# ---------------------------------------------------------------------------
# Simple desktop GUI
# ---------------------------------------------------------------------------

class CurrentFilterGUI:
    """Tk front end for selecting, filtering, saving, and viewing current data."""

    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.root.title("VertiSea Current Filter")
        self.root.geometry("1100x760")
        self.root.minsize(800, 550)

        self.input_var = tk.StringVar()
        self.rtc_var = tk.StringVar(value="Select a currentFast CSV")
        self.offset_var = tk.StringVar(value="%g" % DEFAULT_LOCAL_UTC_OFFSET_HOURS)
        self.window_var = tk.StringVar(value="5")
        self.status_var = tk.StringVar(value="Ready")
        self.summary_var = tk.StringVar(value="No file processed yet.")

        controls = ttk.Frame(root, padding=8)
        controls.pack(fill=tk.X)
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Current CSV:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(controls, textvariable=self.input_var, state="readonly").grid(
            row=0, column=1, sticky="ew")
        ttk.Button(controls, text="Select File...", command=self.select_file).grid(
            row=0, column=2, padx=(6, 0))

        ttk.Label(controls, text="RTC file:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(controls, textvariable=self.rtc_var).grid(
            row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))

        options = ttk.Frame(controls)
        options.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(options, text="Local UTC offset (hours):").pack(side=tk.LEFT)
        ttk.Entry(options, textvariable=self.offset_var, width=8).pack(
            side=tk.LEFT, padx=(4, 16))
        ttk.Label(options, text="Median window:").pack(side=tk.LEFT)
        ttk.Combobox(options, textvariable=self.window_var, width=5,
                     values=(3, 5, 7, 9, 15, 31), state="readonly").pack(
            side=tk.LEFT, padx=(4, 16))
        self.process_button = ttk.Button(options, text="Filter and Save", command=self.process)
        self.process_button.pack(side=tk.LEFT)

        ttk.Label(controls, textvariable=self.summary_var, foreground="#444444").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        plot_frame = ttk.Frame(root, padding=(8, 0, 8, 4))
        plot_frame.pack(fill=tk.BOTH, expand=True)
        self.figure = Figure(figsize=(10, 6), dpi=100)
        self.axes = self.figure.add_subplot(111)
        self.axes.set_xlabel("Local time")
        self.axes.set_ylabel("Current (mA)")
        self.axes.set_title("Select a currentFast CSV to begin")
        self.axes.grid(alpha=0.3)
        self.figure.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, plot_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(fill=tk.X)

        status = ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w")
        status.pack(fill=tk.X, side=tk.BOTTOM)

    def select_file(self):
        from tkinter import filedialog, messagebox

        path = filedialog.askopenfilename(
            title="Select VertiSea currentFast CSV",
            filetypes=[("Current CSV", "*_currentFast.csv"), ("CSV files", "*.csv"),
                       ("All files", "*.*")])
        if not path:
            return
        if not path.lower().endswith("_currentfast.csv"):
            if not messagebox.askyesno(
                    "Unexpected filename",
                    "This file is not named *_currentFast.csv. Try to process it anyway?"):
                return
        self.input_var.set(path)
        rtc_path = sibling_path(path, "_rtcEvt.csv")
        if os.path.exists(rtc_path):
            self.rtc_var.set(os.path.basename(rtc_path) + " (found automatically)")
            self.status_var.set("Ready to process")
        else:
            self.rtc_var.set("Not found: " + rtc_path)
            self.status_var.set("RTC file missing")

    def process(self):
        from tkinter import messagebox

        path = self.input_var.get()
        if not path:
            messagebox.showwarning("Select a file", "Select a *_currentFast.csv file first.")
            return
        try:
            offset = float(self.offset_var.get())
            utc_offset_timezone(offset)
            window = int(self.window_var.get())
            if window < 1:
                raise ValueError("Boxcar window must be positive")
        except ValueError as exc:
            messagebox.showerror("Invalid option", str(exc))
            return

        out_csv = sibling_path(path, "_currentFast_filtered.csv")
        out_png = sibling_path(path, "_currentFast_filtered.png")
        rtc_path = sibling_path(path, "_rtcEvt.csv")
        if not os.path.exists(rtc_path):
            messagebox.showerror(
                "RTC file not found",
                "Could not automatically find the required RTC file:\n%s" % rtc_path)
            return

        self.process_button.configure(state="disabled")
        self.status_var.set("Filtering and saving...")
        self.root.update_idletasks()
        try:
            result = process_current_file(path, window, offset, rtc_path, out_csv, out_png)
            self.update_plot(result)
        except (Exception, SystemExit) as exc:
            messagebox.showerror("Processing failed", str(exc))
            self.status_var.set("Processing failed")
            return
        finally:
            self.process_button.configure(state="normal")

        self.summary_var.set(
            "%d samples | baseline %.2f counts | filtered charge %.3f mC | UTC%+.2f"
            % (len(result["ts"]), result["baseline"], result["charge_mC"], offset))
        self.status_var.set("Saved %s and %s" % (os.path.basename(out_csv),
                                                  os.path.basename(out_png)))
        messagebox.showinfo(
            "Processing complete",
            "Filtered data and plot saved next to the input file:\n\n%s\n%s"
            % (out_csv, out_png))

    def update_plot(self, result):
        import matplotlib.dates as mdates

        self.axes.clear()
        _draw_current_axes(
            self.axes, result["wall_times"], result["raw_mA"],
            result["blk_times"], result["blk_mA"], result["blk_lo"], result["blk_hi"],
            "%s — raw vs filtered" % os.path.basename(result["path"]),
            "Local time (UTC%+.2f)" % result["utc_offset"], result.get("note"))
        self.axes.xaxis.set_major_formatter(
            mdates.DateFormatter("%H:%M:%S",
                                 tz=utc_offset_timezone(result["utc_offset"])))
        self.figure.autofmt_xdate()
        self.figure.tight_layout()
        self.canvas.draw()


def process_current_file(path, window, utc_offset_hours, rtc_path, out_csv, out_png):
    """Run the production filter once and save matching CSV/PNG outputs for the GUI."""
    ts, ct = load_current_csv(path)
    cal, _ = load_cal(path)
    rtc_anchor, _ = load_rtc_anchor(path, rtc_path)
    tz = utc_offset_timezone(utc_offset_hours)
    k = counts_to_mA_factor(cal)
    baseline, _, _ = estimate_baseline(ts, ct)
    filtered, info = hires_pipeline(ts, ct, cal["adc_max"], baseline, window)
    wall_times = [wall_datetime_local(t, rtc_anchor, utc_offset_hours) for t in ts]
    raw_mA, idx, blk_mA, blk_lo, blk_hi = plot_series(ts, ct, filtered, k, window, True)
    filtered_mA = [v * k for v in filtered]
    blk_times = [wall_times[i] for i in idx]
    charge_mC, _ = integrate_charge(ts, filtered, k)

    with io.open(out_csv, "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["timestamp_ms", "actual_time_local", "counts_raw",
                     "counts_filtered", "current_mA"])
        for t, dt, raw, filt, current in zip(ts, wall_times, ct, filtered, filtered_mA):
            wr.writerow(["%.4f" % t, dt.isoformat(timespec="microseconds"), raw,
                         "%.2f" % filt, "%.6f" % current])

    from matplotlib.figure import Figure
    import matplotlib.dates as mdates
    note = _plot_note(info, cal, k)
    fig = Figure(figsize=(14, 6), dpi=100)
    ax = fig.add_subplot(111)
    _draw_current_axes(ax, wall_times, raw_mA, blk_times, blk_mA, blk_lo, blk_hi,
                       "%s — raw vs filtered" % os.path.basename(path),
                       "Local time (UTC%+.2f)" % utc_offset_hours, note)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=tz))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)

    return {"path": path, "ts": ts, "wall_times": wall_times,
            "raw_mA": raw_mA, "filtered_mA": filtered_mA,
            "blk_times": blk_times, "blk_mA": blk_mA,
            "blk_lo": blk_lo, "blk_hi": blk_hi, "note": note, "info": info,
            "baseline": baseline, "charge_mC": charge_mC,
            "utc_offset": utc_offset_hours, "out_csv": out_csv, "out_png": out_png}


def launch_gui():
    """Launch the current-filter GUI, with a useful dependency error if needed."""
    try:
        import tkinter as tk
        import matplotlib  # noqa: F401 - checked before constructing the Tk canvas
    except ImportError as exc:
        raise SystemExit(
            "The GUI needs tkinter and matplotlib. Run it with the project environment "
            "(.venv\\Scripts\\python.exe current_filter_test.py), or install matplotlib. "
            "Original error: %s" % exc)
    root = tk.Tk()
    CurrentFilterGUI(root)
    root.mainloop()
    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def selftest():
    """Check the primitives against hand-computable cases.

    Deliberately independent of any sample file, so it still runs on a machine without
    SampleData/ (which is git-ignored).
    """
    fails = []

    def check(name, got, want, tol=1e-9):
        ok = abs(got - want) <= tol
        print("  %-52s %s (got %s, want %s)" % (name, "PASS" if ok else "FAIL", got, want))
        if not ok:
            fails.append(name)

    # A median rejects lone outliers; a mean does not. Use a mid-array index so the
    # window is the full width (edge indices use a shrinking window by design).
    check("median-3 removes a lone spike", median_filter([1, 1, 100, 1, 1], 3)[2], 1)
    check("boxcar-5 does NOT remove it (why despiking runs first)",
          round(boxcar_filter([1, 1, 100, 1, 1], 5)[2], 4), 20.8, 1e-4)
    # MAD is exactly 0 on a constant window, so the scale floor is what lets the despiker
    # act at all here. This is the dropped-connection case, not a contrived one.
    hp, nhp = hampel_filter([1, 1, 100, 1, 1, 1, 1], 5, 3.0, sigma_floor=1.0)
    check("hampel removes a spike on a constant run (MAD=0)", hp[2], 1.0)
    check("hampel replaced exactly one sample", nhp, 1)
    check("hampel without a floor cannot act on MAD=0",
          hampel_filter([1, 1, 100, 1, 1, 1, 1], 5, 3.0)[1], 0)
    check("hampel leaves clean data untouched",
          hampel_filter([10, 11, 10, 11, 10, 11, 10], 5, 3.0, sigma_floor=1.0)[1], 0)
    check("hampel keeps a real 16% ripple (the PMC signal)",
          hampel_filter([3000, 3500, 3000, 3500, 3000, 3500, 3000], 5, 3.0,
                        sigma_floor=9.14)[1], 0)
    check("median-3 removes a lone dropout", median_filter([10, 10, 0, 10, 10], 3)[2], 10)

    # Level preservation on constant input - the property that matters for charge.
    check("median-5 preserves a constant", stats(median_filter([4033] * 500, 5))["mean"],
          4033.0)
    check("boxcar-17 preserves a constant",
          round(stats(boxcar_filter([4033] * 500, 17))["mean"], 6), 4033.0)

    # Boxcar bandwidth and bit gain - the numbers that let a window be chosen from a
    # target bandwidth instead of by eye, and compared against a scope's HiRes setting.
    f3, fn_, bits = boxcar_bandwidth_hz(16, 800.0)
    check("boxcar-16 at 800 Hz: -3 dB", round(f3, 2), 22.15, 0.01)
    check("boxcar-16 at 800 Hz: first null", round(fn_, 1), 50.0)
    check("boxcar-16 gains 2 effective bits", round(bits, 4), 2.0)
    check("boxcar noise falls as sqrt(w)",
          round(boxcar_bandwidth_hz(4, 800.0)[2], 4), 1.0)

    # THE BIAS THAT WAS REMOVED. Symmetric noise about the baseline must integrate to
    # zero. Clamping at zero half-wave rectifies it, and the survivor mean is
    # sigma/sqrt(2*pi) - a positive current that does not exist, present for every idle
    # second of the record.
    import random as _rnd
    _rnd.seed(11)
    _sigma = 9.14                      # measured idle floor, docs/current_measurement_testing.md
    idle = [_rnd.gauss(18.36, _sigma) for _ in range(200000)]
    mean_plain = stats(subtract_baseline(idle, 18.36))["mean"]
    mean_clamp = stats(subtract_baseline(idle, 18.36, clamp=True))["mean"]
    check("plain baseline subtraction leaves idle at zero", round(mean_plain, 2), 0.0, 0.05)
    check("clamping biases idle high (the removed bug)", round(mean_clamp, 2),
          round(_sigma / math.sqrt(2 * math.pi), 2), 0.05)
    check("bias is >70x the honest residual",
          mean_clamp > 70 * abs(mean_plain), True)

    out, nrep, sat = reject_full_scale([100, 100, 16383, 100, 100], 16383)
    check("full-scale sample replaced", out[2], 100)
    check("replacement count", nrep, 1)

    # 1 count held for 1 s at 1 mA/count = 1 mC. Built from 1 ms steps because a single
    # 1000 ms step would (correctly) be rejected as a block gap by MAX_DT_MS.
    ts_ms = [i * 1.0 for i in range(1001)]
    q, skipped = integrate_charge(ts_ms, [1] * 1001, 1.0)
    check("trapezoid 1 count x 1 s x 1 mA/count", q, 1.0, 1e-9)
    check("no intervals skipped", skipped, 0)

    q, skipped = integrate_charge([0.0, 1000.0], [1000, 1000], 1.0, max_dt_ms=50.0)
    check("1 s gap rejected as a block boundary", q, 0.0)
    check("gap counted as skipped", skipped, 1)

    ts = [i * 1.0 for i in range(3000)]
    v = [5] * 1000 + [900] * 1000 + [5] * 1000
    base, _, warn = estimate_baseline(ts, v)
    check("baseline finds the idle level", base, 5.0)
    check("no warning for a nonzero baseline", 0 if warn is None else 1, 0)
    sub = subtract_baseline(v, base)
    check("baseline subtraction clamps at zero", min(sub), 0.0)
    check("baseline subtraction shifts the plateau", max(sub), 895.0)
    check("one event detected", len(detect_events(ts, sub, 0.0)), 1)

    # A record whose idle span is exact zeros must WARN rather than silently claim a
    # zero offset - this is the case the constant-DC capture exposed.
    _, _, warn0 = estimate_baseline(ts, [0] * 1000 + [900] * 1000 + [0] * 1000)
    check("zero baseline raises a warning", 1 if warn0 else 0, 1)

    k = counts_to_mA_factor(DEFAULT_CAL)
    check("1 count = 0.012208 mA", round(k, 6), 0.012208, 1e-6)
    check("full scale = 200 mA", round(k * DEFAULT_CAL["adc_max"], 3), 200.0, 1e-3)

    # --- saturation vs glitch ------------------------------------------------
    # An isolated rail sample is a glitch and gets repaired; a sustained run is the ADC
    # telling the truth about being out of range and must survive untouched, because
    # rewriting it biases the mean-preserving boxcar that follows.
    out2, nrep2, sat2 = reject_full_scale([100, 100, 16383, 16383, 16383, 100], 16383)
    check("sustained rail run is NOT repaired", out2[2], 16383.0)
    check("sustained rail run replaces nothing", nrep2, 0)
    check("sustained rail run counted as saturation", sat2["n_saturated"], 3)
    check("longest saturated run reported", sat2["longest_run"], 3)

    out3, nrep3, sat3 = reject_full_scale([100, 16383, 16383, 100], 16383)
    check("a run of 2 is still a glitch", nrep3, 2)
    check("run of 2 repaired from both brackets", out3[1], 100.0)
    check("run of 2 leaves no saturation", sat3["n_saturated"], 0)

    # --- decimation is mean-preserving --------------------------------------
    # The whole point of HiRes is that it buys bits without moving the mean. A decimated
    # block series must therefore carry the same average as the samples it came from.
    tsd = [i * 1.0 for i in range(100)]
    vd_ = [float(i) for i in range(100)]
    td, md, lod, hid = decimate_blocks(tsd, vd_, 10)
    check("decimation emits n/w points", len(md), 10)
    check("decimation preserves the mean",
          round(sum(md) / len(md), 9), round(sum(vd_) / len(vd_), 9), 1e-9)
    check("block min tracks the block", lod[0], 0.0)
    check("block max tracks the block", hid[0], 9.0)
    check("w=1 decimation is a passthrough",
          len(decimate_blocks(tsd, vd_, 1)[1]), 100)

    # --- bandwidth <-> window round trip -------------------------------------
    check("window from bandwidth is odd", window_for_bandwidth(20.0, 800.0) % 2, 1)
    _w = window_for_bandwidth(20.0, 800.0)
    check("window from bandwidth round-trips",
          round(boxcar_bandwidth_hz(_w, 800.0)[0], 0), 20.0, 1.5)

    anchor = (1000.0, datetime.datetime(2026, 9, 8, 14, 45, 45))
    check("RTC mapping preserves anchor second",
          1 if wall_time_local(1000.0, anchor) == "2026-09-08T14:45:45.000000" else 0, 1)
    check("RTC mapping adds fractional millis",
          1 if wall_time_local(1109.25, anchor) == "2026-09-08T14:45:45.109250" else 0, 1)
    check("UTC offset labels without shifting local clock",
          1 if wall_time_local(1109.25, anchor, -7.0)
          == "2026-09-08T14:45:45.109250-07:00" else 0, 1)

    print()
    if fails:
        print("SELFTEST FAILED: %d check(s)" % len(fails))
        return 1
    print("SELFTEST PASSED (all checks)")
    return 0


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Test bench for harvested-current post-processing "
                    "(see docs/current_measurement_testing.md).")
    ap.add_argument("csv", nargs="?", help="path to a *_currentFast.csv")
    ap.add_argument("--window", type=int, default=DEFAULT_BOXCAR, metavar="N",
                    help="boxcar (High-Resolution) width in samples, default %(default)s "
                         "= ~22 Hz and +2.0 effective bits at the achieved ~800 Hz. "
                         "N = 0.443 * fs / f_3dB for a bandwidth target.")
    ap.add_argument("--bandwidth", type=float, default=None, metavar="HZ",
                    help="pick --window from a -3 dB bandwidth target instead, using the "
                         "ACHIEVED sample rate read from the file. This is the setting to "
                         "use when matching a scope: give it the scope's HiRes bandwidth.")
    ap.add_argument("--no-decimate", action="store_true",
                    help="plot the filtered trace at the full sample rate instead of one "
                         "point per averaged block. The frequency response is identical; "
                         "the per-sample line just overdraws itself into a solid band on "
                         "any axis narrower than the record, which is what made a "
                         "correctly filtered trace look unfiltered.")
    ap.add_argument("--despike-window", type=int, default=DESPIKE_WINDOW, metavar="N",
                    help="Hampel despike window, default %(default)s")
    ap.add_argument("--despike-sigma", type=float, default=DESPIKE_SIGMA, metavar="K",
                    help="Hampel threshold in robust sigma, default %(default)s")
    ap.add_argument("--baseline-window", default=None, metavar="A,B",
                    help="seconds A,B of a known-idle span; default is auto-detect")
    ap.add_argument("--rtc-csv", default=None, metavar="RTC",
                    help="RTC-event CSV for wall-clock output; default is sibling *_rtcEvt.csv")
    ap.add_argument("--utc-offset", type=float, default=DEFAULT_LOCAL_UTC_OFFSET_HOURS,
                    metavar="HOURS",
                    help="local UTC offset attached to rtcEvt time (default %(default)s)")
    ap.add_argument("--write-csv", default=None, metavar="OUT",
                    help="write raw+filtered columns, including local wall time, to OUT")
    ap.add_argument("--no-baseline", action="store_true",
                    help="do not remove the idle offset - report the ABSOLUTE level. Use "
                         "this for a bench check against a known applied voltage, where "
                         "the DC level is the measurement and the usual baseline "
                         "subtraction would remove all of it.")
    ap.add_argument("--clamp-baseline", action="store_true",
                    help="re-enable the pre-2026-09-11 clamp-at-zero baseline "
                         "subtraction. For reproducing old numbers ONLY - it biases every "
                         "idle second high by sigma/sqrt(2*pi) and that bias integrates.")
    ap.add_argument("--plot", action="store_true", help="show a raw-vs-filtered plot")
    ap.add_argument("--save-plot", default=None, metavar="PNG",
                    help="save the raw-vs-filtered plot to PNG instead of showing it")
    ap.add_argument("--selftest", action="store_true",
                    help="run built-in checks and exit (needs no data file)")
    ap.add_argument("--gui", action="store_true", help="open the desktop file/plot GUI")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.gui or not args.csv:
        return launch_gui()
    if not os.path.exists(args.csv):
        raise SystemExit("not found: %s" % args.csv)

    t0 = time.perf_counter()
    print(report(args.csv, args))
    print("\ntotal runtime %.2f s" % (time.perf_counter() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
