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

def reject_full_scale(v, adc_max):
    """Replace samples at/above full scale with a 3-point median of neighbours.

    Kept deliberately narrow. A sample pinned at full scale with neighbours far below
    cannot be real - current cannot rise 80% of range and return inside one sample
    interval - but a wider outlier rule would start deleting genuine fast structure.
    Returns (filtered, n_replaced).
    """
    out = list(v)
    n = 0
    limit = int(adc_max)
    for i in range(1, len(v) - 1):
        if v[i] >= limit:
            out[i] = sorted((v[i - 1], v[i], v[i + 1]))[1]
            n += 1
    return out, n


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


def mean_filter(v, w):
    """Sliding mean - included ONLY for contrast, to show why it is the wrong choice."""
    if w <= 1:
        return [float(x) for x in v]
    if w % 2 == 0:
        w += 1
    half = w // 2
    n = len(v)
    out = [0.0] * n
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        seg = v[lo:hi]
        out[i] = sum(seg) / float(len(seg))
    return out


def subtract_baseline(v, baseline):
    """Remove the idle offset, clamping at zero.

    Not cosmetic: the offset is integrated over the whole record, so its contribution
    grows with recording length and will dominate a long log with sparse events.
    """
    return [x - baseline if x > baseline else 0.0 for x in v]


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
    for label, fn in (("median-3", lambda x: median_filter(x, 3)),
                      ("median-5", lambda x: median_filter(x, 5)),
                      ("median-9", lambda x: median_filter(x, 9)),
                      ("median-15", lambda x: median_filter(x, 15)),
                      ("mean-5", lambda x: mean_filter(x, 5))):
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
    lines.append("")
    lines.append(hr("BASELINE"))
    lines.append("  estimate : %.2f counts = %.4f mA   [%s]" % (baseline, baseline * k, bsrc))
    lines.append("  noise sd : %.2f counts = %.4f mA (quietest 1-s bin)" % (bnoise, bnoise * k))
    if not args.baseline_window and bwarn:
        lines.append("  WARNING: %s" % bwarn)

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

    v1, n_fs = reject_full_scale(ct, cal["adc_max"])
    q1, _ = integrate_charge(ts, v1, k)
    lines.append("  %-42s %12.3f %10.2f %+8.2f%%"
                 % ("1. reject >=full-scale (%d replaced)" % n_fs, q1, max(v1) * k, pct(q1)))

    variants = []
    for w in (3, 5, 7, 9, 15, 31):
        t_start = time.perf_counter()
        vv = median_filter(v1, w)
        dur = time.perf_counter() - t_start
        qq, _ = integrate_charge(ts, vv, k)
        variants.append((w, qq, dur))
        lines.append("  %-42s %12.3f %10.2f %+8.2f%%"
                     % ("2. + median-%-2d" % w, qq, max(vv) * k, pct(qq)))

    vm = mean_filter(v1, 5)
    qm, _ = integrate_charge(ts, vm, k)
    lines.append("  %-42s %12.3f %10.2f %+8.2f%%"
                 % ("   (mean-5, contrast only - do not use)", qm, max(vm) * k, pct(qm)))

    v2 = median_filter(v1, args.window)
    v3 = subtract_baseline(v2, baseline)
    q2, _ = integrate_charge(ts, v2, k)
    q3, _ = integrate_charge(ts, v3, k)
    lines.append("  %-42s %12.3f %10.2f %+8.2f%%"
                 % ("3. + subtract baseline (%.2f counts)" % baseline,
                    q3, max(v3) * k, pct(q3)))
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
        lines.append("  wrote %s (raw + filtered, median-%d, baseline removed%s)"
                     % (args.write_csv, args.window,
                        ", RTC wall time added" if rtc_anchor else ""))

    if args.plot or args.save_plot:
        lines.append("")
        lines.append(_do_plot(ts, ct, v3, k, path, save_to=args.save_plot))

    return "\n".join(lines)


def _do_plot(ts, raw, final, k, path, save_to=None):
    """Single overlay: raw in blue, filtered in red drawn last so it sits on top."""
    try:
        import matplotlib
        matplotlib.use("Agg" if save_to else "TkAgg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # environment dependent; never fatal
        return "  plot unavailable: %s" % exc
    t0 = ts[0]
    x = [(t - t0) / 1000.0 for t in ts]

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(x, [c * k for c in raw], lw=0.5, color="#1f77b4", label="raw", zorder=1)
    ax.plot(x, [c * k for c in final], lw=0.9, color="#d62728", label="filtered", zorder=3)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("current (mA)")
    ax.set_title("%s  -  raw vs filtered" % os.path.basename(path))
    ax.legend(loc="upper left", framealpha=0.9)
    ax.grid(alpha=0.3)

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
                raise ValueError("Median window must be positive")
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
        self.axes.plot(result["wall_times"], result["raw_mA"], lw=0.5,
                       color="#1f77b4", label="Raw", zorder=1)
        self.axes.plot(result["wall_times"], result["filtered_mA"], lw=0.9,
                       color="#d62728", label="Filtered", zorder=3)
        self.axes.set_xlabel("Local time (UTC%+.2f)" % result["utc_offset"])
        self.axes.set_ylabel("Current (mA)")
        self.axes.set_title("%s — raw vs filtered" % os.path.basename(result["path"]))
        self.axes.xaxis.set_major_formatter(
            mdates.DateFormatter("%H:%M:%S",
                                 tz=utc_offset_timezone(result["utc_offset"])))
        self.axes.legend(loc="upper left", framealpha=0.9)
        self.axes.grid(alpha=0.3)
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
    full_scale_ok, _ = reject_full_scale(ct, cal["adc_max"])
    filtered = subtract_baseline(median_filter(full_scale_ok, window), baseline)
    wall_times = [wall_datetime_local(t, rtc_anchor, utc_offset_hours) for t in ts]
    raw_mA = [v * k for v in ct]
    filtered_mA = [v * k for v in filtered]
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
    fig = Figure(figsize=(14, 6), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot(wall_times, raw_mA, lw=0.5, color="#1f77b4", label="Raw", zorder=1)
    ax.plot(wall_times, filtered_mA, lw=0.9, color="#d62728", label="Filtered", zorder=3)
    ax.set_xlabel("Local time (UTC%+.2f)" % utc_offset_hours)
    ax.set_ylabel("Current (mA)")
    ax.set_title("%s — raw vs filtered" % os.path.basename(path))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=tz))
    ax.legend(loc="upper left", framealpha=0.9)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)

    return {"path": path, "ts": ts, "wall_times": wall_times,
            "raw_mA": raw_mA, "filtered_mA": filtered_mA,
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
    check("mean-5 does NOT remove it", round(mean_filter([1, 1, 100, 1, 1], 5)[2], 4),
          20.8, 1e-4)
    check("median-3 removes a lone dropout", median_filter([10, 10, 0, 10, 10], 3)[2], 10)

    # Level preservation on constant input - the property that matters for charge.
    check("median-5 preserves a constant", stats(median_filter([4033] * 500, 5))["mean"],
          4033.0)

    out, nrep = reject_full_scale([100, 100, 16383, 100, 100], 16383)
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
    ap.add_argument("--window", type=int, default=5,
                    help="median window for the final pipeline (default 5)")
    ap.add_argument("--baseline-window", default=None, metavar="A,B",
                    help="seconds A,B of a known-idle span; default is auto-detect")
    ap.add_argument("--rtc-csv", default=None, metavar="RTC",
                    help="RTC-event CSV for wall-clock output; default is sibling *_rtcEvt.csv")
    ap.add_argument("--utc-offset", type=float, default=DEFAULT_LOCAL_UTC_OFFSET_HOURS,
                    metavar="HOURS",
                    help="local UTC offset attached to rtcEvt time (default %(default)s)")
    ap.add_argument("--write-csv", default=None, metavar="OUT",
                    help="write raw+filtered columns, including local wall time, to OUT")
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
