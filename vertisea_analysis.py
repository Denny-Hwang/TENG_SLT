"""Conservative battery-side charging analysis with no optional dependencies."""

import bisect
import math
import statistics


ALGORITHM_VERSION = "charging-1"


def _number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _segment(row):
    return (row.get("boot_id", 0), row.get("segment_id", 0))


def _noise(rows):
    values = sorted(_number(row.get("current_mA")) for row in rows)
    values = [value for value in values if math.isfinite(value)]
    idle = values[:max(1, (len(values) + 1) // 2)]
    if not idle:
        return 0.0, 0.0
    baseline = statistics.median(idle)
    sigma = 1.4826 * statistics.median(abs(value - baseline) for value in idle)
    sigma = max(sigma, math.sqrt(sum((value - baseline) ** 2 for value in idle) / len(idle)))
    return baseline, sigma


def detect_cycles(current_rows, method="auto", cycle_start=None, cycle_end=None,
                  start_threshold_mA=None, stop_threshold_mA=None,
                  min_duration_s=1.0, quiet_end_s=1.0, max_gap_s=0.25):
    """Return cycle boundaries in native milliseconds, independently per segment.

    Selected boundaries are seconds on the native boot clock, not UTC. Automatic
    thresholds use the lower-half median/MAD idle estimate and 6/3 sigma hysteresis.
    Missing data ends an event with a flag, never with an inferred quiet tail.
    """
    if method not in ("auto", "selected"):
        raise ValueError("method must be 'auto' or 'selected'")
    if min_duration_s < 0 or quiet_end_s < 0 or max_gap_s <= 0:
        raise ValueError("durations must be nonnegative and max_gap_s positive")
    if method == "selected":
        if cycle_start is None or cycle_end is None or not (
                math.isfinite(cycle_start) and math.isfinite(cycle_end)
                and cycle_end > cycle_start):
            raise ValueError("selected cycles require finite start < end seconds")
    elif cycle_start is not None or cycle_end is not None:
        raise ValueError("start/end require method='selected'")
    groups = {}
    for index, row in enumerate(current_rows):
        groups.setdefault(_segment(row), []).append((index, row))
    cycles = []
    for (boot_id, segment_id), indexed in groups.items():
        baseline, sigma = _noise([row for _, row in indexed])
        onset = baseline + max(6 * sigma, 0.01) if start_threshold_mA is None else start_threshold_mA
        offset = baseline + max(3 * sigma, 0.005) if stop_threshold_mA is None else stop_threshold_mA
        if not math.isfinite(onset) or not math.isfinite(offset) or onset <= offset:
            raise ValueError("start threshold must exceed stop threshold")

        def emit(start, end, flags):
            cycles.append({"cycle_id": len(cycles), "boot_id": boot_id,
                           "segment_id": segment_id, "start_ms": start,
                           "end_ms": end, "method": method,
                           "baseline_mA": baseline, "noise_sigma_mA": sigma,
                           "start_threshold_mA": onset, "stop_threshold_mA": offset,
                           "flags": flags})

        if method == "selected":
            times = [_number(row.get("ts_ms")) for _, row in indexed]
            times = [value for value in times if math.isfinite(value)]
            start, end = cycle_start * 1000, cycle_end * 1000
            if times and max(times) >= start and min(times) <= end:
                flags = []
                if start < min(times) or end > max(times):
                    flags.append("selection_outside_data")
                emit(start, end, flags)
            continue
        active = None
        quiet = None
        previous = None
        for _, row in indexed:
            timestamp = _number(row.get("ts_ms"))
            current = _number(row.get("current_mA"))
            if not math.isfinite(timestamp):
                continue
            broken = (previous is not None and
                      (timestamp <= previous or timestamp - previous > max_gap_s * 1000))
            if broken or not math.isfinite(current):
                if active is not None:
                    if previous - active >= min_duration_s * 1000:
                        emit(active, previous, ["data_gap", "incomplete_end"])
                    active, quiet = None, None
            if math.isfinite(current):
                if active is None and current >= onset:
                    active, quiet = timestamp, None
                elif active is not None:
                    if current <= offset:
                        if quiet is None:
                            quiet = timestamp
                        if timestamp - quiet >= quiet_end_s * 1000:
                            if timestamp - active >= min_duration_s * 1000:
                                emit(active, timestamp, [])
                            active, quiet = None, None
                    else:
                        quiet = None
            previous = timestamp
        if active is not None and previous - active >= min_duration_s * 1000:
            emit(active, previous, ["incomplete_end"])
    return cycles


def _summarize(rows, duration_s):
    valid_s = sum(row["interval_s"] for row in rows if row["interval_valid"])
    current_s = sum(row["interval_s"] for row in rows if row["current_interval_valid"])
    currents = [row["current_mA"] for row in rows if math.isfinite(row["current_mA"])]
    return {"duration_s": duration_s, "valid_energy_s": valid_s,
            "valid_current_s": current_s,
            "coverage_fraction": valid_s / duration_s if duration_s > 0 else 0.0,
            "gross_energy_mJ": sum(row["energy_increment_mJ"] for row in rows
                                    if row["interval_valid"]) if valid_s else math.nan,
            "baseline_subtracted_energy_mJ": sum(row["baseline_energy_increment_mJ"] for row in rows
                                                  if row["interval_valid"]) if valid_s else math.nan,
            "charge_mC": sum(row["charge_increment_mC"] for row in rows
                              if row["current_interval_valid"]) if current_s else math.nan,
            "peak_current_mA": max(currents) if currents else math.nan,
            "clipped_samples": sum(row["clipped"] for row in rows),
            "invalid_energy_intervals": sum(not row["interval_valid"] for row in rows
                                             if row["interval_s"] > 0)}


def analyze_charging(current_rows, battery_rows, cycle_start=None, cycle_end=None,
                     cycle_method=None, baseline_mA=0.0, max_voltage_gap_s=2.5,
                     max_current_gap_s=0.25, adc_max=16383,
                     min_duration_s=1.0, quiet_end_s=1.0,
                     start_threshold_mA=None, stop_threshold_mA=None):
    """Align voltage and integrate only measured, unclipped short intervals.

    Rows require ts_ms/current_mA/counts or ts_ms/voltage_V. Optional boot_id and
    segment_id isolate sources; source_index/source_row_index are retained.
    Gross and signed idle-subtracted quantities are separate. Cumulative energy
    at an invalid interval is NaN; measured_energy_mJ explicitly sums only valid
    intervals and must be interpreted alongside coverage.
    """
    if max_voltage_gap_s <= 0 or max_current_gap_s <= 0 or not math.isfinite(baseline_mA):
        raise ValueError("gap limits must be positive and baseline finite")
    voltages = {}
    for row in battery_rows:
        timestamp, voltage = _number(row.get("ts_ms")), _number(row.get("voltage_V"))
        if math.isfinite(timestamp):
            voltages.setdefault(_segment(row), []).append((timestamp, voltage))
    for key, values in voltages.items():
        ordered = sorted(values)
        duplicate_times = {ordered[index][0] for index in range(1, len(ordered))
                           if ordered[index][0] == ordered[index - 1][0]}
        voltages[key] = ([value[0] for value in ordered], ordered, duplicate_times)
    result = []
    previous = None
    total = baseline_total = charge_total = 0.0
    for row in current_rows:
        timestamp = _number(row.get("ts_ms"))
        current = _number(row.get("current_mA"))
        voltage = math.nan
        flags = []
        times, pairs, duplicates = voltages.get(_segment(row), ([], [], set()))
        position = bisect.bisect_left(times, timestamp) if math.isfinite(timestamp) else 0
        if position < len(times) and times[position] == timestamp and timestamp not in duplicates:
            voltage = pairs[position][1]
        elif (0 < position < len(times) and times[position] - times[position - 1] <= max_voltage_gap_s * 1000
              and times[position] not in duplicates and times[position - 1] not in duplicates):
            left, right = pairs[position - 1], pairs[position]
            voltage = left[1] + (right[1] - left[1]) * (timestamp - left[0]) / (right[0] - left[0])
        if not math.isfinite(voltage):
            flags.append("voltage_unbracketed_or_gap")
        if not math.isfinite(current):
            flags.append("current_uncalibrated_or_invalid")
        counts = _number(row.get("counts"))
        ceiling = _number(row.get("adc_max", adc_max))
        clipped = math.isfinite(counts) and math.isfinite(ceiling) and counts >= ceiling
        if clipped:
            flags.append("adc_clipped")
        power = voltage * current
        baseline_power = voltage * (current - baseline_mA)
        elapsed = (timestamp - previous["ts_ms"]) / 1000 if previous is not None else 0.0
        same_segment = previous is not None and _segment(row) == _segment(previous)
        short = same_segment and 0 < elapsed <= max_current_gap_s
        current_valid = (short and math.isfinite(current) and math.isfinite(previous["current_mA"])
                         and not clipped and not previous["clipped"])
        valid = current_valid and math.isfinite(power) and math.isfinite(previous["power_mW"])
        if previous is not None and not short:
            flags.append("segment_boundary_or_current_gap")
        increment = (power + previous["power_mW"]) * elapsed / 2 if valid else math.nan
        baseline_increment = (baseline_power + previous["baseline_power_mW"]) * elapsed / 2 if valid else math.nan
        charge = (current + previous["current_mA"]) * elapsed / 2 if current_valid else math.nan
        if valid:
            total += increment
            baseline_total += baseline_increment
        if current_valid:
            charge_total += charge
        aligned = dict(row, ts_ms=timestamp, current_mA=current, voltage_V=voltage,
                       power_mW=power, baseline_power_mW=baseline_power,
                       baseline_mA=baseline_mA, clipped=clipped,
                       interval_s=elapsed if same_segment and elapsed > 0 else 0.0,
                       current_interval_valid=bool(current_valid), interval_valid=bool(valid),
                       energy_increment_mJ=increment, baseline_energy_increment_mJ=baseline_increment,
                       charge_increment_mC=charge,
                       cumulative_energy_mJ=total if valid else math.nan,
                       cumulative_baseline_energy_mJ=baseline_total if valid else math.nan,
                       measured_energy_mJ=total, measured_charge_mC=charge_total, flags=flags)
        result.append(aligned)
        previous = aligned
    method = cycle_method or ("selected" if cycle_start is not None or cycle_end is not None else "auto")
    cycles = detect_cycles(result, method=method, cycle_start=cycle_start, cycle_end=cycle_end,
                           min_duration_s=min_duration_s, quiet_end_s=quiet_end_s,
                           max_gap_s=max_current_gap_s, start_threshold_mA=start_threshold_mA,
                           stop_threshold_mA=stop_threshold_mA)
    for cycle in cycles:
        selected = [row for row in result if _segment(row) == (cycle["boot_id"], cycle["segment_id"])
                    and cycle["start_ms"] <= row["ts_ms"] <= cycle["end_ms"]]
        intervals = [row for index, row in enumerate(selected) if index > 0]
        cycle.update(_summarize(intervals, (cycle["end_ms"] - cycle["start_ms"]) / 1000))
        cycle["sample_count"] = len(selected)
        cycle["clipped_samples"] = sum(row["clipped"] for row in selected)
        cycle["peak_current_mA"] = max((row["current_mA"] for row in selected
                                         if math.isfinite(row["current_mA"])), default=math.nan)
    duration = sum(row["interval_s"] for row in result)
    return {"rows": result, "cycles": cycles, "summary": _summarize(result, duration),
            "algorithm_version": ALGORITHM_VERSION, "cycle_method": method,
            "parameters": {"baseline_mA": baseline_mA, "max_voltage_gap_s": max_voltage_gap_s,
                           "max_current_gap_s": max_current_gap_s, "adc_max": adc_max,
                           "min_duration_s": min_duration_s, "quiet_end_s": quiet_end_s,
                           "start_threshold_mA": start_threshold_mA,
                           "stop_threshold_mA": stop_threshold_mA}}