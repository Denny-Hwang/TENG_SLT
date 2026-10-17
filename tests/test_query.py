import csv
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import h5py
import numpy as np
from vertisea_query import SessionReader, rolling_mean, estimated_power


def make_archive(path):
    with h5py.File(path, "w") as archive:
        for name, times, values, boots, sources in (
            ("raw/fast", [0, 250, 500, 750, 1000, 1250, 3000, 0],
             [1, 2, 3, 4, 5, np.nan, 7, 99], [0] * 7 + [1], [0] * 6 + [1, 2]),
            ("raw/slow", [0, 1000, 2000, 3000], [3, 4, 5, 6], [0]*4, [0, 0, 1, 1]),
        ):
            group = archive.create_group(name)
            group.attrs["row_count"] = len(times)
            for column, data in (("ts_ms", times), ("value", values), ("boot_id", boots),
                                 ("source_index", sources)):
                group.create_dataset(column, data=data, chunks=True)
            group.create_dataset("text", data=[b"native"] * len(times))
        archive.create_group("raw/sources/000000").create_dataset("bin_bytes", data=[1, 2])


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "session.h5"
        make_archive(self.path)
        self.reader = SessionReader(self.path, chunk_rows=2).__enter__()

    def tearDown(self):
        self.reader.close()
        self.temp.cleanup()

    def test_tables_ranges_and_pages(self):
        self.assertEqual(self.reader.list_tables(), ["/raw/fast", "/raw/slow"])
        info = self.reader.table_info("raw/fast")
        self.assertEqual((info["row_count"], info["boots"], info["end_s"]), (8, [0, 1], 3))
        first = self.reader.read_page("raw/fast", ["ts_ms"], boot=0, start=.25, end=1.3, limit=2)
        second = self.reader.read_page("raw/fast", ["ts_ms"], boot=0, start=.25, end=1.3, offset=2, limit=2)
        np.testing.assert_equal(first["ts_ms"], [250, 500])
        np.testing.assert_equal(second["ts_ms"], [750, 1000])
        self.assertEqual(len(self.reader.read_page("raw/fast", ["value"], offset=100)["value"]), 0)

    def test_aggregates_and_coverage(self):
        for method, expected in (("mean", 2.5), ("min", 1), ("max", 4),
                                 ("rms", np.sqrt(7.5)), ("count", 4)):
            result = self.reader.align([("raw/fast", "value")], 0, 4, boot=0, method=method)
            column = result.columns[("/raw/fast", "value")]
            self.assertAlmostEqual(column.values[0], expected)
            self.assertEqual(column.coverage[1], .5)
            self.assertTrue(np.isnan(column.values[2]))
            self.assertEqual(column.flags[2], "empty")
            self.assertEqual(column.count[2], 0)

    def test_interpolation_chunk_edges_and_source_boundaries(self):
        keys = [("raw/slow", "value")]
        linear = self.reader.align(keys, 0, 3.5, step=.5, boot=0, method="linear", tolerance=1)
        values = linear.columns[("/raw/slow", "value")].values
        np.testing.assert_allclose(values, [3, 3.5, 4, np.nan, 5, 5.5, 6], equal_nan=True)
        for method, expected in (("nearest", 3), ("previous", 3)):
            result = self.reader.align(keys, 0, 1, step=.5, boot=0, method=method)
            self.assertEqual(result.columns[("/raw/slow", "value")].values[1], expected)
        gap = self.reader.align(keys, 0, 1, step=.5, boot=0, method="linear", max_gap=.2)
        self.assertTrue(np.isnan(gap.columns[("/raw/slow", "value")].values[1]))

    def test_boot_and_ambiguity(self):
        with self.assertRaisesRegex(ValueError, "Multiple boots"):
            self.reader.align([("raw/fast", "value")], 0, 4)
        result = self.reader.align([("raw/slow", "value")], 0, 4, step=4, boot=0)
        column = result.columns[("/raw/slow", "value")]
        self.assertEqual(column.flags[0], "ambiguous")
        self.assertFalse(column.valid[0])
        self.assertTrue(np.isnan(column.values[0]))
        selected = self.reader.align([("raw/fast", "value")], 0, 1, boot=1, source=2)
        self.assertEqual(selected.columns[("/raw/fast", "value")].values[0], 99)

    def test_validation_and_caps(self):
        for kwargs in ({"step": 0}, {"step": -1}, {"step": np.nan}, {"tolerance": -1},
                       {"max_gap": 0}, {"method": "bad"}, {"step": .00001}, {"step": 1e-320}):
            with self.assertRaises(ValueError):
                self.reader.align([("raw/slow", "value")], 0, 4, boot=0, **kwargs)
        for start, end in ((-1, 2), (2, 1), (np.nan, 4), (0, np.inf)):
            with self.assertRaises(ValueError):
                self.reader.align([("raw/slow", "value")], start, end)
        for kwargs in ({"limit": 501}, {"offset": -1}, {"limit": 0}, {"offset": .5}):
            with self.assertRaises(ValueError):
                self.reader.read_page("raw/slow", **kwargs)
        with self.assertRaises(ValueError):
            self.reader.align([("raw/slow", "text")], 0, 4)
        with self.assertRaises(ValueError):
            SessionReader(self.path, chunk_rows=0)

    def test_exports_and_postprocessing_retain_native(self):
        native = self.reader.read_page("raw/slow", ["value"])["value"].copy()
        output = Path(self.temp.name) / "native.csv"
        self.reader.export_native_csv("raw/slow", ["value"], output, source=0)
        with output.open() as handle:
            self.assertEqual(list(csv.reader(handle)), [["value"], ["3"], ["4"]])
        result = self.reader.align([("raw/slow", "value")], 0, 4, boot=0)
        column = result.columns[("/raw/slow", "value")]
        np.testing.assert_allclose(rolling_mean(column, 3), [3, 3.5, 5, 5.5])
        np.testing.assert_allclose(estimated_power(column, column), [9, 16, 25, 36])
        self.reader.export_aligned_csv(result, output)
        with output.open() as handle:
            self.assertIn("/raw/slow/value:coverage", next(csv.reader(handle)))
        np.testing.assert_equal(self.reader.read_page("raw/slow", ["value"])["value"], native)
        with self.assertRaises(ValueError):
            self.reader.export_native_csv("raw/slow", ["value"], self.path)

    def test_chunk_bounded_and_long_grid(self):
        self.assertTrue(all(len(chunk["value"]) <= 2 for chunk in
                            self.reader.iter_native("raw/fast", ["value"])))
        result = self.reader.align([("raw/slow", "value")], 0, 43200, boot=0)
        self.assertEqual(len(result.time_s), 43200)
        self.reader.point_budget = 10
        with self.assertRaisesRegex(ValueError, "budget"):
            self.reader.align([("raw/slow", "value")], 0, 43200, boot=0)

    def test_closed_context(self):
        self.reader.close()
        with self.assertRaises(RuntimeError):
            self.reader.list_tables()

    def test_duplicate_regression_and_missing_rolling(self):
        self.reader.close()
        with h5py.File(self.path, "a") as archive:
            group = archive.create_group("raw/duplicates")
            group.attrs["row_count"] = 5
            group.create_dataset("ts_ms", data=[0, 1000, 1000, 500, 2000])
            group.create_dataset("value", data=[1, 2, 3, 4, 5])
        self.reader.__enter__()
        result = self.reader.align([("raw/duplicates", "value")], 0, 3, step=.5,
                                   method="linear", tolerance=2)
        column = result.columns[("/raw/duplicates", "value")]
        self.assertEqual(column.flags[1], "ambiguous")
        self.assertEqual(column.flags[2], "ambiguous")
        result = self.reader.align([("raw/fast", "value")], 0, 4, boot=0)
        column = result.columns[("/raw/fast", "value")]
        np.testing.assert_allclose(rolling_mean(column, 5), [2.5, 3.75, np.nan, 7], equal_nan=True)
        with self.assertRaises(ValueError):
            rolling_mean(column, 0)

    def test_cross_table_boot_mismatch(self):
        self.reader.close()
        with h5py.File(self.path, "a") as archive:
            group = archive.create_group("raw/other_boot")
            group.attrs["row_count"] = 2
            group.create_dataset("ts_ms", data=[0, 1000])
            group.create_dataset("boot_id", data=[2, 2])
            group.create_dataset("value", data=[1, 2])
        self.reader.__enter__()
        with self.assertRaisesRegex(ValueError, "Multiple boots"):
            self.reader.align([("raw/slow", "value"), ("raw/other_boot", "value")], 0, 4)


if __name__ == "__main__":
    unittest.main()