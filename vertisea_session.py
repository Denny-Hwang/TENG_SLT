"""Lossless, atomic SD BIN import to independently timed HDF5 datasets.

HDF5/NumPy are optional and imported only when import_session is called.
"""

import argparse
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import tempfile

from vertisea_analysis import analyze_charging
from vertisea_protocol import parse_binary_file


SCHEMA_VERSION = "1.0"
WRITE_CHUNK_ROWS = 4096
RAW_KEYS = {"imu_raw", "current", "current_fast", "battery_voltage", "hall_edge", "mag"}
ONBOARD_KEYS = {"fixed_imu", "stab_imu", "current_stats", "displacement", "rpm", "bme", "gps"}
META_KEYS = {"rtc_event", "session_meta", "fixed_cal", "stab_cal", "current_cal", "battery_cal", "lpf_cal"}


def _json(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=True)


def _dependencies():
    try:
        import h5py
        import numpy
    except ImportError as error:
        raise RuntimeError("Session import requires h5py and numpy; install environment.yml dependencies") from error
    return h5py, numpy


def _expand_paths(paths):
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    expanded = []
    for supplied in paths:
        path = Path(supplied).resolve()
        if path.is_dir():
            expanded.extend(sorted((item for item in path.rglob("*")
                                    if item.is_file() and item.suffix.lower() == ".bin"),
                                   key=lambda item: str(item).casefold()))
        elif path.is_file():
            expanded.append(path)
        else:
            raise FileNotFoundError(str(path))
    if len(set(expanded)) != len(expanded):
        raise ValueError("Duplicate source paths would double-count measurements")
    return expanded


def _column_kind(values):
    present = [value for value in values if value is not None]
    if present and len(present) == len(values) and all(isinstance(value, (bool, int)) for value in present):
        return "int"
    if present and all(isinstance(value, (int, float)) for value in present):
        return "float"
    return "json"


def _new_column(table, key, kind, size, h5py):
    dtype = h5py.string_dtype(encoding="utf-8") if kind == "json" else "int64" if kind == "int" else "float64"
    fill = "null" if kind == "json" else 0 if kind == "int" else math.nan
    column = table.create_dataset(key, shape=(size,), maxshape=(None,), dtype=dtype,
                                  chunks=(WRITE_CHUNK_ROWS,), compression="gzip", shuffle=True,
                                  fillvalue=fill)
    column.attrs["storage_kind"] = kind
    return column


def _promote_column(table, key, kind, h5py):
    previous = table[key]
    replacement_key = "__promoted_column"
    while replacement_key in table:
        replacement_key += "_"
    replacement = _new_column(table, replacement_key, kind, len(previous), h5py)
    for start in range(0, len(previous), WRITE_CHUNK_ROWS):
        end = min(start + WRITE_CHUNK_ROWS, len(previous))
        values = previous[start:end]
        replacement[start:end] = ([_json(value.item()) for value in values]
                                   if kind == "json" else values)
    del table[key]
    table.move(replacement_key, key)
    return table[key]


def _write_table(parent, name, rows, h5py, numpy):
    table = parent.require_group(name)
    if "records_json" not in table:
        table.attrs["row_count"] = 0
        table.attrs["time_axis"] = "native ts_ms since firmware boot; never a unified resampled clock"
        table.attrs["json_encoding"] = "Python JSON; nonfinite floats use NaN/Infinity"
        _new_column(table, "records_json", "json", 0, h5py)
    iterator = iter(rows)
    while True:
        batch = list(itertools.islice(iterator, WRITE_CHUNK_ROWS))
        if not batch:
            break
        start = int(table.attrs["row_count"])
        end = start + len(batch)
        records = table["records_json"]
        records.resize((end,))
        records[start:end] = [_json(row) for row in batch]
        keys = set(table.keys()) | {key for row in batch for key in row}
        for key in sorted(keys):
            if key == "records_json" or "/" in key:
                continue
            values = [row.get(key) for row in batch]
            kind = _column_kind(values)
            if key not in table:
                if start and kind == "int":
                    kind = "float"
                column = _new_column(table, key, kind, start, h5py)
            else:
                column = table[key]
                previous_kind = column.attrs["storage_kind"]
                if previous_kind == "json":
                    kind = "json"
                elif kind == "json" and not any(value is not None for value in values):
                    kind = "float"
                elif previous_kind == "float" and kind == "int":
                    kind = "float"
                if kind != previous_kind:
                    column = _promote_column(table, key, kind, h5py)
            column.resize((end,))
            column[start:end] = ([_json(value) for value in values] if kind == "json" else
                                 numpy.asarray([math.nan if value is None else value for value in values],
                                               dtype="float64" if kind == "float" else "int64"))
        table.attrs["row_count"] = end
    return table


def _merge_summary(total, summary):
    for key in ("duration_s", "valid_energy_s", "valid_current_s", "clipped_samples", "invalid_energy_intervals"):
        total[key] += summary[key]
    for key in ("gross_energy_mJ", "baseline_subtracted_energy_mJ", "charge_mC"):
        if math.isfinite(summary[key]):
            total[key] = (total[key] if math.isfinite(total[key]) else 0.0) + summary[key]
    peaks = [value for value in (total["peak_current_mA"], summary["peak_current_mA"]) if math.isfinite(value)]
    total["peak_current_mA"] = max(peaks, default=math.nan)
    total["coverage_fraction"] = total["valid_energy_s"] / total["duration_s"] if total["duration_s"] > 0 else 0.0


def _stream_diagnostic(key, rows, source_index, boot_id):
    count = positive = regressions = 0
    first = previous = last = None
    largest = 0.0
    for row in rows:
        timestamp = row.get("ts_ms")
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            continue
        count += 1
        if first is None:
            first = timestamp
        if previous is not None:
            delta = timestamp - previous
            positive += delta > 0
            regressions += delta <= 0
            largest = max(largest, delta)
        previous = last = timestamp
    span_s = (last - first) / 1000 if count > 1 and last > first else 0.0
    return dict(stream=key, source_index=source_index, segment_id=source_index, boot_id=boot_id,
                timestamped_samples=count, observed_span_s=span_s,
                observed_rate_hz=positive / span_s if span_s and not regressions else math.nan,
                max_positive_gap_s=largest / 1000, nonincreasing_intervals=regressions)


def _anchor_utc(anchor, offset_minutes=None):
    if offset_minutes is None:
        return None
    try:
        return datetime(*(int(anchor[key]) for key in ("year", "month", "day", "hour", "minute", "second")),
                        tzinfo=timezone(timedelta(minutes=offset_minutes))).astimezone(timezone.utc).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def _append_source(path, source_index, boot_id, previous_max, seen, scratch, groups,
                   cycle_start, cycle_end, cycle_offset, h5py, numpy):
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest in seen:
        original = seen[digest]
        metadata = dict(original, source_index=source_index, path=str(path),
                        duplicate_of_source_index=original["source_index"],
                        flags=["duplicate_content_skipped"])
        _write_table(groups["meta"], "sources", [metadata], h5py, numpy)
        _write_table(groups["events"], "records", [dict(source_index=source_index,
                     kind="duplicate_content_skipped", duplicate_of_source_index=original["source_index"])],
                     h5py, numpy)
        return metadata, boot_id, previous_max, None, []
    snapshot = Path(scratch) / "source.BIN"
    snapshot.write_bytes(payload)
    parsed = parse_binary_file(str(snapshot))
    minimum = maximum = None
    for records in parsed.values():
        if not isinstance(records, list):
            continue
        for row in records:
            timestamp = row.get("ts_ms") if isinstance(row, dict) else None
            if isinstance(timestamp, (int, float)) and math.isfinite(timestamp):
                minimum = timestamp if minimum is None else min(minimum, timestamp)
                maximum = timestamp if maximum is None else max(maximum, timestamp)
    anchors = parsed.get("rtc_event", [])
    anchor = anchors[0] if anchors else None
    session_metadata = parsed.get("session_meta", [])
    offset_minutes = session_metadata[0].get("utc_offset_minutes") if session_metadata else None
    flags = []
    overlap = False
    boundary_gap = None
    if anchor is not None and previous_max is not None and anchor["ts_ms"] < previous_max:
        boot_id += 1
        flags.append("rtc_timestamp_regression_reboot")
    elif minimum is not None and previous_max is not None:
        boundary_gap = (minimum - previous_max) / 1000
        if minimum < previous_max:
            overlap = True
            flags.extend(["overlapping_or_regressing_time_without_reboot_anchor",
                          "overlapping_source_analysis_excluded"])
    if not anchor:
        flags.append("utc_anchor_missing")
    ambiguous = any(right["ts_ms"] < left["ts_ms"] for left, right in zip(anchors, anchors[1:]))
    if ambiguous:
        flags.append("intra_source_reboot_ambiguous_analysis_excluded")
    calibration_ambiguous = any(len(parsed.get(key, [])) > 1 for key in ("current_cal", "battery_cal"))
    if calibration_ambiguous:
        flags.append("multiple_calibrations_analysis_excluded")
    metadata = {"source_index": source_index, "segment_id": source_index, "boot_id": boot_id,
                "path": str(path), "byte_count": len(payload), "sha256": digest, "flags": flags,
                "min_ts_ms": minimum, "max_ts_ms": maximum, "rtc_anchor": anchor,
                "rtc_anchor_utc": _anchor_utc(anchor, offset_minutes) if anchor else None,
                "utc_offset_minutes": offset_minutes, "boundary_gap_s": boundary_gap,
                "duplicate_of_source_index": None,
                "bin_dataset": f"/raw/sources/{source_index:06d}/bin_bytes",
                "utc_assumption": "Recorded offset applied; clock accuracy unverified"
                if offset_minutes is not None else "Legacy RTC timezone unknown; no UTC mapping"}
    source = groups["raw"]["sources"].create_group(f"{source_index:06d}")
    source.attrs["provenance_json"] = _json(metadata)
    source.create_dataset("bin_bytes", data=numpy.frombuffer(payload, dtype="uint8"),
                          compression="gzip", shuffle=True)
    del payload
    source.attrs["parser_notes_json"] = _json(parsed.get("notes", []))
    source.attrs["parser_errors_json"] = _json(parsed.get("errors", []))
    event = dict(source_index=source_index, segment_id=source_index, boot_id=boot_id,
                 kind="source_start" if not seen else "source_boundary", ts_ms=minimum,
                 flags=flags, boundary_gap_s=boundary_gap)
    _write_table(groups["events"], "records", [event], h5py, numpy)
    for message in parsed.get("errors", []):
        _write_table(groups["events"], "records", [dict(event, kind="parser_warning", message=message)], h5py, numpy)
    for key, records in parsed.items():
        if key in ("errors", "notes") or not isinstance(records, list):
            continue
        for index, row in enumerate(records):
            if isinstance(row, dict):
                row.update(source_index=source_index, source_row_index=index,
                           segment_id=source_index, boot_id=boot_id)
        category = ("raw" if key in RAW_KEYS else "onboard" if key in ONBOARD_KEYS else
                    "meta" if key in META_KEYS or key.endswith("_cal") else
                    "health" if key in ("sys_health", "status") else "onboard")
        _write_table(groups[category], key, (row for row in records if isinstance(row, dict)), h5py, numpy)
        _write_table(groups["health"], "stream_diagnostics",
                     [_stream_diagnostic(key, (row for row in records if isinstance(row, dict)), source_index, boot_id)],
                     h5py, numpy)
    currents = parsed.get("current_fast") or parsed.get("current", [])
    calibration = parsed.get("current_cal", [])
    for row in currents:
        row["adc_max"] = calibration[0]["adc_max"] if calibration else 16383
    eligible = not (ambiguous or calibration_ambiguous or overlap)
    analysis = analyze_charging(currents if eligible else [],
                                parsed.get("battery_voltage", []) if eligible else [],
                                cycle_start=cycle_start, cycle_end=cycle_end)
    for cycle in analysis["cycles"]:
        cycle["cycle_id"] += cycle_offset
        cycle["source_index"] = source_index
        cycle["flags"].append("source_local_analysis")
    _write_table(groups["derived"], "charging", analysis["rows"], h5py, numpy)
    _write_table(groups["derived"], "cycles", analysis["cycles"], h5py, numpy)
    stabilized = {row["ts_ms"]: row for row in parsed.get("stab_imu", [])}

    def differences():
        for fixed in parsed.get("fixed_imu", []):
            stable = stabilized.get(fixed["ts_ms"])
            if stable is not None:
                yield dict(ts_ms=fixed["ts_ms"], source_index=source_index, boot_id=boot_id,
                           segment_id=source_index, diff_pitch_deg=fixed["pitch"] - stable["pitch"],
                           diff_roll_deg=fixed["roll"] - stable["roll"])

    _write_table(groups["derived"], "tilt_difference", differences(), h5py, numpy)
    _write_table(groups["meta"], "sources", [metadata], h5py, numpy)
    warnings = [f"source {source_index}: {flag}" for flag in flags]
    warnings.extend(f"source {source_index}: {message}" for message in parsed.get("errors", []))
    del analysis["rows"]
    return metadata, boot_id, maximum if maximum is not None else previous_max, analysis, warnings


def import_session(paths, output, cycle_start=None, cycle_end=None):
    """Atomically append one parsed source at a time; never retain campaign rows.

    Explicit paths retain supplied order; directory expansion is lexical with a
    warning. Identical content is represented by an alias manifest entry only.
    Sources remain separate analysis segments, including within the same boot.
    Returns small metadata, aggregate summary, cycles and warnings, not samples.
    """
    if (cycle_start is None) != (cycle_end is None):
        raise ValueError("cycle_start and cycle_end must be supplied together")
    if cycle_start is not None and not (math.isfinite(cycle_start) and math.isfinite(cycle_end)
                                        and cycle_end > cycle_start):
        raise ValueError("cycle_start must be finite and smaller than cycle_end")
    h5py, numpy = _dependencies()
    supplied = [paths] if isinstance(paths, (str, os.PathLike)) else list(paths)
    sources = _expand_paths(supplied)
    destination = Path(output).resolve()
    if destination in sources:
        raise ValueError("Output cannot replace an input source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    warnings = []
    if any(Path(path).is_dir() for path in supplied):
        warnings.append("directory_lexical_order: verify date folders across midnight/month/year; "
                        "supply explicit chronological files when names are ambiguous; RTC is not a sorting prepass")
    manifest, cycles, seen, selected_boots = [], [], {}, set()
    boot_id, previous_max = 0, None
    template = analyze_charging([], [], cycle_start=cycle_start, cycle_end=cycle_end)
    summary = dict(template["summary"])
    with tempfile.TemporaryDirectory(prefix=".vertisea-", dir=str(destination.parent)) as scratch:
        temporary_output = Path(scratch) / "session.h5"
        with h5py.File(temporary_output, "w") as archive:
            archive.attrs["schema_version"] = SCHEMA_VERSION
            groups = {name: archive.create_group(name) for name in
                      ("raw", "onboard", "derived", "meta", "health", "events")}
            groups["raw"].create_group("sources")
            for source_index, path in enumerate(sources):
                metadata, boot_id, previous_max, analysis, messages = _append_source(
                    path, source_index, boot_id, previous_max, seen, scratch, groups,
                    cycle_start, cycle_end, len(cycles), h5py, numpy)
                manifest.append(metadata)
                warnings.extend(messages)
                if analysis is None:
                    warnings.append(f"source {source_index}: duplicate_content_skipped "
                                    f"(source {metadata['duplicate_of_source_index']})")
                    continue
                seen[metadata["sha256"]] = metadata
                if cycle_start is None:
                    _merge_summary(summary, analysis["summary"])
                else:
                    for cycle in analysis["cycles"]:
                        _merge_summary(summary, cycle)
                        selected_boots.add(cycle["boot_id"])
                cycles.extend(analysis["cycles"])
            if cycle_start is not None:
                summary["duration_s"] = (cycle_end - cycle_start) * max(1, len(selected_boots))
                summary["coverage_fraction"] = summary["valid_energy_s"] / summary["duration_s"]
            for category, keys in (("raw", RAW_KEYS), ("onboard", ONBOARD_KEYS), ("meta", META_KEYS),
                                   ("health", {"sys_health", "stream_diagnostics"}),
                                   ("derived", {"charging", "cycles", "tilt_difference"}),
                                   ("meta", {"sources"}), ("events", {"records"})):
                for key in keys:
                    _write_table(groups[category], key, [], h5py, numpy)
            groups["derived"].attrs["algorithm_version"] = template["algorithm_version"]
            groups["derived"].attrs["parameters_json"] = _json(template["parameters"])
            groups["derived"].attrs["summary_json"] = _json(summary)
            groups["derived"].attrs["cycle_method"] = template["cycle_method"]
            groups["derived"].attrs["analysis_boundary_policy"] = "source-local; no boundary interpolation, integration or cycle stitching; cumulative sums reset per source"
            groups["derived"].attrs["summary_scope"] = "selected fully contained intervals per boot" if cycle_start is not None else "sum of observed within-source intervals; inter-source gaps excluded"
            groups["derived"].attrs["units_json"] = _json({"ts_ms": "ms since boot", "current_mA": "mA",
                                                          "voltage_V": "V", "power_mW": "mW",
                                                          "energy": "mJ", "charge": "mC"})
            groups["meta"].attrs["created_utc"] = datetime.now(timezone.utc).isoformat()
            groups["meta"].attrs["schema_version"] = SCHEMA_VERSION
            groups["meta"].attrs["time_provenance"] = "Native parser timestamps; current block times reconstructed from measured span"
            groups["meta"].attrs["calibration_policy"] = "Parser per-source archived calibration only; no historical rescaling or cross-source propagation"
            groups["meta"].attrs["capture_mode"] = "offline SD BIN import; not live HDF5 recording"
            groups["meta"].attrs["import_strategy"] = "one source snapshot/parser/analysis at a time; resizable columns; 4096-row write batches"
            groups["health"].attrs["warnings_json"] = _json(warnings)
            archive.flush()
        with temporary_output.open("r+b") as completed:
            os.fsync(completed.fileno())
        os.replace(str(temporary_output), str(destination))
    return {"output": str(destination), "sources": manifest, "warnings": warnings,
            "summary": summary, "cycles": cycles}


def export_cycles_csv(session_path, output):
    """Export cycle summaries only; native high-rate streams remain in HDF5."""
    h5py, _ = _dependencies()
    if Path(output).resolve() == Path(session_path).resolve():
        raise ValueError("CSV output cannot replace the session archive")
    with h5py.File(session_path, "r") as archive:
        cycles = [json.loads(value) for value in archive["derived/cycles/records_json"].asstr()[:]]
    fields = sorted(set().union(*(row.keys() for row in cycles))) if cycles else ["cycle_id", "start_ms", "end_ms", "method"]
    with open(output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in cycles:
            writer.writerow({key: _json(value) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})
    return str(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Ordered BIN files or recursively searched directories")
    parser.add_argument("--output", required=True, help="Destination HDF5 session")
    parser.add_argument("--start", type=float, help="Selected cycle start in native boot seconds")
    parser.add_argument("--end", type=float, help="Selected cycle end in native boot seconds")
    parser.add_argument("--cycles-csv", help="Optional cycle summary CSV destination")
    arguments = parser.parse_args(argv)
    if arguments.cycles_csv and Path(arguments.cycles_csv).resolve() in (
            _expand_paths(arguments.paths) + [Path(arguments.output).resolve()]):
        parser.error("CSV output cannot replace an input BIN or HDF5 output")
    result = import_session(arguments.paths, arguments.output, arguments.start, arguments.end)
    if arguments.cycles_csv:
        export_cycles_csv(result["output"], arguments.cycles_csv)
    print(_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())