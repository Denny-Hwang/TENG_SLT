"""Synthetic charging and lossless session-storage checks."""

import math
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import weakref
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vertisea_analysis import analyze_charging, detect_cycles
from vertisea_session import _expand_paths, _write_table, import_session, main


def current_rows(times, values=None, **extra):
    values = values if values is not None else [10.0] * len(times)
    return [dict(ts_ms=timestamp, current_mA=value, counts=100, **extra)
            for timestamp, value in zip(times, values)]


class ChargingTests(unittest.TestCase):
    def test_trapezoids_units_and_baseline(self):
        result = analyze_charging(current_rows([0, 100, 200]),
                                  [{"ts_ms": 0, "voltage_V": 3}, {"ts_ms": 200, "voltage_V": 4}],
                                  baseline_mA=2, cycle_start=0, cycle_end=0.2)
        self.assertAlmostEqual(result["summary"]["gross_energy_mJ"], 7)
        self.assertAlmostEqual(result["summary"]["baseline_subtracted_energy_mJ"], 5.6)
        self.assertAlmostEqual(result["summary"]["charge_mC"], 2)
        self.assertEqual(result["cycles"][0]["method"], "selected")
        self.assertEqual(result["cycles"][0]["coverage_fraction"], 1)

    def test_no_extrapolation_or_long_voltage_gap(self):
        result = analyze_charging(current_rows([-100, 0, 100, 2900, 3000, 3100]),
                                  [{"ts_ms": 0, "voltage_V": 3}, {"ts_ms": 3000, "voltage_V": 4}])
        for index in (0, 2, 3, 5):
            self.assertTrue(math.isnan(result["rows"][index]["voltage_V"]))
        self.assertTrue(math.isnan(result["summary"]["gross_energy_mJ"]))

    def test_current_gap_clipping_and_segment_isolation(self):
        rows = current_rows([0, 100, 1000, 1100, 1200])
        rows[3]["counts"] = 16383
        rows[-1]["segment_id"] = 1
        result = analyze_charging(rows, [{"ts_ms": 0, "voltage_V": 3},
                                         {"ts_ms": 2000, "voltage_V": 3}])
        self.assertAlmostEqual(result["summary"]["gross_energy_mJ"], 3)
        self.assertEqual(result["summary"]["clipped_samples"], 1)
        for row in result["rows"][2:]:
            self.assertFalse(row["interval_valid"])
            self.assertTrue(math.isnan(row["cumulative_energy_mJ"]))

    def test_noise_hysteresis_quiet_end(self):
        rows = current_rows(list(range(0, 2200, 100)), [0, .01, 0, .01, 0] + [2] * 10 + [0] * 7)
        cycles = detect_cycles(rows, min_duration_s=.5, quiet_end_s=.4)
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0]["start_ms"], 500)
        self.assertEqual(cycles[0]["end_ms"], 1900)
        self.assertGreater(cycles[0]["start_threshold_mA"], cycles[0]["stop_threshold_mA"])

    def test_empty_missing_calibration_and_selection_validation(self):
        self.assertEqual(analyze_charging([], [])["rows"], [])
        result = analyze_charging(current_rows([0, 100], [None, None]), [])
        self.assertTrue(math.isnan(result["summary"]["gross_energy_mJ"]))
        with self.assertRaises(ValueError):
            detect_cycles([], method="selected", cycle_start=2, cycle_end=1)

    def test_selected_does_not_include_interval_before_start(self):
        result = analyze_charging(current_rows([0, 100, 200]),
                                  [{"ts_ms": 0, "voltage_V": 3}, {"ts_ms": 200, "voltage_V": 3}],
                                  cycle_start=.05, cycle_end=.2)
        self.assertAlmostEqual(result["cycles"][0]["gross_energy_mJ"], 3)
        self.assertAlmostEqual(result["cycles"][0]["coverage_fraction"], 2 / 3)

    def test_reboot_and_invalid_voltage_are_not_bridged(self):
        rows = current_rows([0, 100]) + current_rows([0, 100], boot_id=1)
        battery = [{"ts_ms": 0, "voltage_V": 3}, {"ts_ms": 100, "voltage_V": None},
                   {"ts_ms": 0, "voltage_V": 4, "boot_id": 1},
                   {"ts_ms": 100, "voltage_V": 4, "boot_id": 1}]
        result = analyze_charging(rows, battery)
        self.assertFalse(result["rows"][1]["interval_valid"])
        self.assertFalse(result["rows"][2]["interval_valid"])
        self.assertAlmostEqual(result["summary"]["gross_energy_mJ"], 4)

    def test_duplicate_battery_timestamps_are_ambiguous(self):
        result = analyze_charging(current_rows([0, 100]),
                                  [{"ts_ms": 0, "voltage_V": 3}, {"ts_ms": 0, "voltage_V": 4},
                                   {"ts_ms": 100, "voltage_V": 3}])
        self.assertTrue(math.isnan(result["rows"][0]["voltage_V"]))
        self.assertFalse(result["rows"][1]["interval_valid"])

    def test_gap_ends_cycle_with_flag(self):
        rows = current_rows(list(range(0, 1100, 100)) + [2000], [2] * 11 + [0])
        cycles = detect_cycles(rows, start_threshold_mA=1, stop_threshold_mA=.5)
        self.assertEqual(cycles[0]["end_ms"], 1000)
        self.assertIn("data_gap", cycles[0]["flags"])


def packet(kind, timestamp, format_string, *values):
    return struct.pack("<BI", kind, timestamp) + struct.pack("<" + format_string, *values)


def synthetic_bin(start=0, sensitivity=100):
    return (packet(5, start, "6B", 26, 10, 16, 12, 0, 0)
            + packet(13, start, "4f", 2, 16383, 1, sensitivity)
            + packet(19, start, "5f", 2, 16383, 10000, 10000, 2)
            + packet(20, start, "H", 14000)
            + packet(14, start, "HH3H", 200, 3, 100, 200, 300)
            + packet(18, start, "3h3i3h3iH", 0, 0, 1000, 100, 200, 300,
                     0, 0, 1000, 400, 500, 600, 9615)
            + packet(1, start, "9fH", 1, 2, 999.9, 4, 5, 6, 7, 8, 9, 9615)
            + packet(20, start + 200, "H", 14000))


class SourceTests(unittest.TestCase):
    def test_directory_recursion_case_insensitivity_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            (root / "b.BIN").write_bytes(b"")
            (root / "nested" / "a.bin").write_bytes(b"")
            (root / "ignored.txt").write_bytes(b"")
            self.assertEqual([path.name for path in _expand_paths(root)], ["b.BIN", "a.bin"])
            with self.assertRaises(ValueError):
                _expand_paths([root / "b.BIN", root / "b.BIN"])

    def test_synthetic_bin_parser_preserves_archived_scale(self):
        from vertisea_protocol import parse_binary_file
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.BIN"
            path.write_bytes(synthetic_bin(sensitivity=100))
            parsed = parse_binary_file(str(path))
            self.assertAlmostEqual(parsed["current_fast"][0]["current_mA"], 100 * 2 * 100 / 16383)
            self.assertEqual(parsed["current_fast"][-1]["ts_ms"], 200)
            self.assertEqual(parsed["imu_raw"][0]["ts_ms"], 0)

    def test_new_modules_do_not_import_optional_dependencies(self):
        import subprocess
        result = subprocess.run([sys.executable, "-c",
                                 "import sys, vertisea_session, vertisea_analysis; "
                                 "assert 'h5py' not in sys.modules; assert 'numpy' not in sys.modules"],
                                cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(importlib.util.find_spec("h5py"), "h5py not installed: HDF5 integration tests unavailable")
class SessionTests(unittest.TestCase):
    def test_lossless_native_streams_calibration_rotation_and_reboot(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payloads = [synthetic_bin(0, 100), synthetic_bin(1000, 200), synthetic_bin(0, 101), b""]
            paths = []
            for index, payload in enumerate(payloads):
                path = root / f"{index}.BIN"
                path.write_bytes(payload)
                paths.append(path)
            output = root / "session.h5"
            result = import_session(paths, output, cycle_start=0, cycle_end=.2)
            self.assertEqual([source["boot_id"] for source in result["sources"]], [0, 0, 1, 1])
            with h5py.File(output, "r") as archive:
                for index, payload in enumerate(payloads):
                    restored = archive[f"raw/sources/{index:06d}/bin_bytes"][:].tobytes()
                    self.assertEqual(restored, payload)
                    self.assertEqual(result["sources"][index]["sha256"], hashlib.sha256(payload).hexdigest())
                    self.assertEqual(archive[f"raw/sources/{index:06d}/bin_bytes"].compression, "gzip")
                self.assertEqual(list(archive["raw/current_fast/ts_ms"][:]), [0, 100, 200, 1000, 1100, 1200, 0, 100, 200])
                self.assertEqual(archive["raw/imu_raw"].attrs["row_count"], 3)
                self.assertEqual(archive["onboard/fixed_imu"].attrs["row_count"], 3)
                self.assertEqual(archive["onboard/current_stats"].attrs["row_count"], 0)
                currents = archive["derived/charging/current_mA"][:]
                self.assertAlmostEqual(currents[3], 2 * currents[0])
                self.assertFalse(archive["derived/charging/interval_valid"][3])
                self.assertFalse(archive["derived/charging/interval_valid"][6])

    def test_empty_session_and_empty_source(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "empty.BIN"
            source.write_bytes(b"")
            for paths in ([], [source]):
                result = import_session(paths, root / "empty.h5")
                self.assertTrue(math.isnan(result["summary"]["gross_energy_mJ"]))
                with h5py.File(result["output"], "r") as archive:
                    self.assertEqual(archive["derived/charging"].attrs["row_count"], 0)

    def test_many_sources_append_per_file_and_skip_duplicate_bytes(self):
        import h5py
        import vertisea_session
        from vertisea_protocol import parse_binary_file
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for index in range(12):
                path = root / f"{index:02d}.BIN"
                path.write_bytes(synthetic_bin(index * 1000))
                paths.append(path)
            duplicate = root / "renamed.BIN"
            duplicate.write_bytes(paths[0].read_bytes())
            paths.insert(5, duplicate)
            append_sizes = []
            analysis_sizes = []
            original_writer = vertisea_session._write_table
            original_analysis = vertisea_session.analyze_charging

            def write(parent, name, rows, h5py_module, numpy_module):
                if name == "current_fast":
                    materialized = list(rows)
                    append_sizes.append(len(materialized))
                    return original_writer(parent, name, iter(materialized), h5py_module, numpy_module)
                return original_writer(parent, name, rows, h5py_module, numpy_module)

            def analyze(currents, batteries, **kwargs):
                analysis_sizes.append(len(currents))
                return original_analysis(currents, batteries, **kwargs)

            with mock.patch("vertisea_session.WRITE_CHUNK_ROWS", 2), \
                    mock.patch("vertisea_session._write_table", side_effect=write), \
                    mock.patch("vertisea_session.analyze_charging", side_effect=analyze), \
                    mock.patch("vertisea_session.parse_binary_file", wraps=parse_binary_file) as parser:
                result = import_session(paths, root / "session.h5", cycle_start=0, cycle_end=11.2)
            self.assertEqual(parser.call_count, 12)
            self.assertEqual(append_sizes, [3] * 12 + [0])
            self.assertEqual(max(analysis_sizes), 3)
            self.assertEqual(result["sources"][5]["duplicate_of_source_index"], 0)
            self.assertTrue(any("duplicate_content_skipped" in warning for warning in result["warnings"]))
            self.assertEqual([source["boot_id"] for source in result["sources"]], [0] * 13)
            self.assertAlmostEqual(result["summary"]["valid_energy_s"], 2.4)
            self.assertAlmostEqual(result["summary"]["duration_s"], 11.2)
            self.assertAlmostEqual(result["summary"]["coverage_fraction"], 2.4 / 11.2)
            self.assertEqual([cycle["cycle_id"] for cycle in result["cycles"]], list(range(12)))
            with h5py.File(result["output"], "r") as archive:
                table = archive["raw/current_fast"]
                self.assertEqual(table.attrs["row_count"], 36)
                self.assertEqual(table["ts_ms"].maxshape, (None,))
                self.assertEqual(table["records_json"].chunks, (2,))
                self.assertEqual(len(archive["raw/sources"]), 12)
                self.assertNotIn("000005", archive["raw/sources"])
                self.assertEqual(list(table["source_index"][:]),
                                 [index for index in range(13) if index != 5 for _ in range(3)])
                for source in result["sources"]:
                    self.assertEqual(archive[source["bin_dataset"]][:].tobytes(), Path(source["path"]).read_bytes())
                charging = archive["derived/charging"]
                self.assertFalse(any(charging["interval_valid"][::3]))
                self.assertTrue(all(charging["measured_energy_mJ"][::3] == 0))
                diagnostics = [json.loads(row) for row in archive["health/stream_diagnostics/records_json"].asstr()[:]]
                currents = [row for row in diagnostics if row["stream"] == "current_fast"]
                self.assertEqual(len(currents), 12)
                self.assertEqual(currents[0]["observed_rate_hz"], 10)
                self.assertEqual(currents[0]["max_positive_gap_s"], .1)

    def test_chunked_column_promotion_missing_and_future_fields(self):
        import h5py
        import numpy
        with tempfile.TemporaryDirectory() as directory:
            with h5py.File(Path(directory) / "columns.h5", "w") as archive:
                with mock.patch("vertisea_session.WRITE_CHUNK_ROWS", 2):
                    _write_table(archive, "stream", iter([{"ts_ms": 0, "value": 1},
                                                         {"ts_ms": 1, "value": 2}]), h5py, numpy)
                    _write_table(archive, "stream", iter([{"ts_ms": 2, "value": 2.5, "new": 8},
                                                         {"ts_ms": 3}]), h5py, numpy)
                    self.assertEqual(archive["stream/value"].dtype.kind, "f")
                    self.assertTrue(math.isnan(archive["stream/value"][3]))
                    self.assertTrue(math.isnan(archive["stream/new"][0]))
                    _write_table(archive, "stream", iter([{"ts_ms": 4, "value": {"nested": 1}}]), h5py, numpy)
                table = archive["stream"]
                values = [json.loads(value) for value in table["value"].asstr()[:]]
                self.assertEqual(values[:3], [1, 2, 2.5])
                self.assertTrue(math.isnan(values[3]))
                self.assertEqual(values[4], {"nested": 1})
                self.assertEqual(table["ts_ms"].dtype.kind, "i")
                self.assertEqual(table.attrs["row_count"], 5)
                self.assertEqual({len(column) for column in table.values()}, {5})

    def test_parsed_rows_released_before_next_source(self):
        import h5py

        class TrackedRow(dict):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            references = []
            parsed_count = 0
            for index in range(3):
                path = root / f"{index}.BIN"
                path.write_bytes(bytes([index]))
                paths.append(path)

            def parse(path):
                nonlocal parsed_count
                self.assertTrue(all(reference() is None for reference in references))
                start = parsed_count * 1000
                parsed_count += 1
                rows = [TrackedRow(ts_ms=start + index / 10, current_mA=10, counts=100)
                        for index in range(5000)]
                references[:] = [weakref.ref(row) for row in rows]
                return {"current": rows, "battery_voltage": [
                    {"ts_ms": start, "voltage_V": 3}, {"ts_ms": start + 500, "voltage_V": 3}]}

            with mock.patch("vertisea_session.parse_binary_file", side_effect=parse):
                result = import_session(paths, root / "session.h5")
            self.assertTrue(all(reference() is None for reference in references))
            with h5py.File(result["output"], "r") as archive:
                self.assertEqual(archive["raw/current"].attrs["row_count"], 15000)
                self.assertEqual(archive["derived/charging"].attrs["row_count"], 15000)

    def test_weighted_coverage_and_selected_summary_scope(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "first.BIN", root / "second.BIN"]
            for index, path in enumerate(paths):
                path.write_bytes(bytes([index]))
            parsed = [
                {"current": current_rows([0, 100, 200]),
                 "battery_voltage": [{"ts_ms": 0, "voltage_V": 3}, {"ts_ms": 200, "voltage_V": 3}]},
                {"current": current_rows([1000, 1100, 2000]),
                 "battery_voltage": [{"ts_ms": 1000, "voltage_V": 3}, {"ts_ms": 2000, "voltage_V": 3}]}]
            with mock.patch("vertisea_session.parse_binary_file", side_effect=parsed):
                result = import_session(paths, root / "weighted.h5")
            self.assertAlmostEqual(result["summary"]["coverage_fraction"], .3 / 1.2)
            self.assertAlmostEqual(result["summary"]["gross_energy_mJ"], 9)
            self.assertEqual(result["sources"][1]["boundary_gap_s"], .8)
            with mock.patch("vertisea_session.parse_binary_file", side_effect=parsed):
                selected = import_session(paths, root / "selected.h5", cycle_start=.05, cycle_end=.2)
            self.assertAlmostEqual(selected["summary"]["duration_s"], .15)
            self.assertAlmostEqual(selected["summary"]["valid_energy_s"], .1)
            self.assertAlmostEqual(selected["summary"]["gross_energy_mJ"], 3)
            self.assertAlmostEqual(selected["summary"]["coverage_fraction"], 2 / 3)
            with h5py.File(selected["output"], "r") as archive:
                self.assertEqual(json.loads(archive["derived"].attrs["summary_json"]), selected["summary"])

    def test_directory_order_warning_and_ambiguous_overlap_exclusion(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "first.BIN").write_bytes(b"first")
            (root / "second.BIN").write_bytes(b"second")
            parsed = {"current": current_rows([0, 100]),
                      "battery_voltage": [{"ts_ms": 0, "voltage_V": 3}, {"ts_ms": 100, "voltage_V": 3}]}
            with mock.patch("vertisea_session.parse_binary_file", side_effect=[parsed, parsed]):
                result = import_session(root, root / "session.h5")
            self.assertTrue(any("directory_lexical_order" in warning for warning in result["warnings"]))
            self.assertIn("overlapping_source_analysis_excluded", result["sources"][1]["flags"])
            with h5py.File(result["output"], "r") as archive:
                self.assertEqual(archive["raw/current"].attrs["row_count"], 4)
                self.assertEqual(archive["derived/charging"].attrs["row_count"], 2)

    def test_failure_keeps_existing_output_and_removes_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.BIN"
            source.write_bytes(synthetic_bin())
            output = root / "session.h5"
            output.write_bytes(b"previous archive")
            with mock.patch("vertisea_session.parse_binary_file", side_effect=ValueError("bad parser")):
                with self.assertRaises(ValueError):
                    import_session([source], output)
            self.assertEqual(output.read_bytes(), b"previous archive")
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["input.BIN", "session.h5"])

    def test_new_parser_keys_are_preserved_exactly(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "new.BIN"
            source.write_bytes(b"opaque original bytes")
            processed = {"ts_ms": 123, "charge_mC": 2.5, "n_samples": 17}
            parsed = {"current_stats": [processed], "displacement": [{"ts_ms": 123, "displacement_mm": 42}],
                      "session_meta": [{"ts_ms": 123, "firmware_hash": "abcd"}], "errors": [], "notes": []}
            with mock.patch("vertisea_session.parse_binary_file", return_value=parsed):
                import_session([source], root / "new.h5")
            with h5py.File(root / "new.h5", "r") as archive:
                stored = json.loads(archive["onboard/current_stats/records_json"].asstr()[0])
                for key, value in processed.items():
                    self.assertEqual(stored[key], value)
                self.assertEqual(archive["meta/session_meta"].attrs["row_count"], 1)
                self.assertEqual(archive["onboard/displacement"].attrs["row_count"], 1)

    def test_cli_import_and_cycles_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.BIN"
            source.write_bytes(synthetic_bin())
            self.assertEqual(main([str(source), "--output", str(root / "session.h5"),
                                   "--start", "0", "--end", ".2", "--cycles-csv", str(root / "cycles.csv")]), 0)
            self.assertIn("selected", (root / "cycles.csv").read_text())


if __name__ == "__main__":
    unittest.main()