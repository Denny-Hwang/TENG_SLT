"""Synthetic telemetry only; no hardware ports are opened."""

import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vertisea_live import LiveRecorder, TelemetryParser, TimestampClock, current_interval_stats
from vertisea_protocol import TYPE_RPM, TYPE_BATTERY_VOLTAGE, TYPE_CURRENT_STATS, TYPE_STATUS


def stats(timestamp, charge, accepted, window=10, samples=100, squared=40):
    return dict(timestamp=timestamp, charge_mC=charge, integ_s=accepted,
                window_s=window, n_samples=samples, i2t_mA2s=squared)


class LiveTests(unittest.TestCase):
    def test_clock_wrap_and_out_of_order(self):
        clock = TimestampClock()
        self.assertAlmostEqual(clock.seconds(65530), 655.30)
        self.assertAlmostEqual(clock.seconds(65529), 655.29)
        self.assertAlmostEqual(clock.seconds(2), 655.38)
        self.assertAlmostEqual(clock.seconds(65535), 655.35)
        self.assertAlmostEqual(clock.seconds(3), 655.39)

    def test_split_packet_provenance(self):
        parser = TelemetryParser()
        packet = struct.pack("<BHH", TYPE_RPM, 100, 2400)
        self.assertEqual(parser.feed(b"\xff" + packet[:2], 123, 0), [])
        records = parser.feed(packet[2:], 456, 1)
        self.assertEqual(records[0]["rpm"], 2400)
        self.assertEqual(records[0]["byte_offset"], 1)
        self.assertEqual(records[0]["first_byte_receive_utc_ns"], 123)
        self.assertEqual(records[0]["host_receive_utc_ns"], 456)
        self.assertEqual(records[0]["completion_chunk_index"], 1)
        self.assertEqual(parser.skipped_bytes, 1)

    def test_interval_current_rms_freshness_reset_gap(self):
        first = stats(1, 4, 1, squared=16)
        second = stats(2, 8, 2, squared=32)
        result = current_interval_stats(first, second, 3.2, 1)
        self.assertEqual(result["current_mA"], 4)
        self.assertEqual(result["rms_mA"], 4)
        self.assertAlmostEqual(result["power_mW"], 12.8)
        self.assertTrue(math.isnan(current_interval_stats(None, first)["current_mA"]))
        self.assertFalse(current_interval_stats(first, second, 3.2, -1)["voltage_fresh"])
        self.assertTrue(math.isnan(current_interval_stats(second, stats(3, 1, 1, samples=1))["current_mA"]))
        self.assertTrue(math.isnan(current_interval_stats(first, stats(5, 8, 2))["current_mA"]))

    def test_archive_exact_chunks_and_derived(self):
        import h5py
        chunks = [b"\xff" + struct.pack("<BHH", TYPE_BATTERY_VOLTAGE, 100, 3200),
                  struct.pack("<BHHHfffII", TYPE_CURRENT_STATS, 100, 10, 4, 4, 16, 1, 100, 0),
                  struct.pack("<BHHHfffII", TYPE_CURRENT_STATS, 200, 11, 4, 8, 32, 2, 200, 0),
                  struct.pack("<BHB", TYPE_STATUS, 200, 1), b"\x06\x00"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.h5"
            with LiveRecorder(path) as recorder:
                for index, chunk in enumerate(chunks):
                    recorder.feed(chunk, 1000 + index)
            recorder.close()
            with h5py.File(path, "r") as archive:
                self.assertEqual(bytes(archive["raw/bytes"][:]), b"".join(chunks))
                self.assertEqual(archive["raw/bytes"].compression, "gzip")
                rows = [json.loads(value) for value in archive["raw/chunks/records_json"].asstr()[:]]
                self.assertEqual([row["host_receive_utc_ns"] for row in rows], list(range(1000, 1005)))
                derived = json.loads(archive["derived/charging/records_json"].asstr()[-1])
                self.assertAlmostEqual(derived["power_mW"], 12.8)
                status = json.loads(archive["health/status/records_json"].asstr()[0])
                self.assertFalse(status["sd_ok"])
                stop = json.loads(archive["events/records/records_json"].asstr()[-1])
                self.assertEqual(stop["trailing_unparsed_bytes"], 2)
                self.assertIn("high-rate", archive["meta"].attrs["limitation"])
            with self.assertRaises(FileExistsError):
                LiveRecorder(path)

    def test_lazy_import(self):
        import subprocess
        completed = subprocess.run([sys.executable, "-c",
            "import sys; import vertisea_live; assert 'h5py' not in sys.modules; "
            "assert 'serial' not in sys.modules; assert 'tkinter' not in sys.modules"],
            cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_all_schemas_one_byte_chunks(self):
        from vertisea_live import RADIO_SCHEMAS
        from vertisea_protocol import TYPE_BME, TYPE_GPS, TYPE_TELEM_IMU
        packets = [struct.pack("<BHfff", TYPE_BME, 100, 100000, 50, 20),
                   struct.pack("<BHBff", TYPE_GPS, 100, 8, 45, -120),
                   struct.pack("<BHhhhhh", TYPE_TELEM_IMU, 100, 1200, -900, 1000, 200, -100),
                   struct.pack("<BHH", TYPE_RPM, 100, 1200),
                   struct.pack("<BHB", TYPE_STATUS, 100, 0),
                   struct.pack("<BHHHfffII", TYPE_CURRENT_STATS, 100, 1, 4, 4, 16, 1, 100, 1),
                   struct.pack("<BHH", TYPE_BATTERY_VOLTAGE, 100, 3200)]
        parser = TelemetryParser()
        records = []
        for index, value in enumerate(b"".join(packets)):
            records.extend(parser.feed(bytes([value]), index, index))
        self.assertEqual(len(records), len(RADIO_SCHEMAS))
        self.assertEqual(records[2]["pitch"], 12)
        self.assertEqual(records[2]["raw_fields"]["fix_pitch_cdeg"], 1200)
        self.assertEqual(records[2]["displacement_m"], 1)
        self.assertEqual(parser.buffer, b"")

    def test_out_of_order_does_not_replace_stats_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            with LiveRecorder(Path(directory) / "live.h5") as recorder:
                for timestamp, charge in [(100, 4), (200, 8), (150, 6), (300, 12)]:
                    recorder.feed(struct.pack("<BHHHfffII", TYPE_CURRENT_STATS, timestamp,
                                              timestamp // 100, 4, charge, charge * 4,
                                              timestamp / 100, timestamp, 0))
                self.assertEqual(recorder.previous_stats["timestamp"], 3)
                row = json.loads(recorder.archive["derived/charging/records_json"].asstr()[-1])
                self.assertEqual(row["current_mA"], 4)

    def test_open_serial_clears_lines_before_open(self):
        from vertisea_live import open_serial
        connection = MagicMock()
        def check_open():
            self.assertFalse(connection.rts)
            self.assertFalse(connection.dtr)
            self.assertEqual(connection.port, "FAKE")
        connection.open.side_effect = check_open
        with patch("serial.Serial", return_value=connection) as factory:
            self.assertIs(open_serial("FAKE"), connection)
        factory.assert_called_once_with(port=None, baudrate=115200, timeout=0.1)

    def test_headless_duration_and_interrupt_close(self):
        from vertisea_live import main
        packet = struct.pack("<BHH", TYPE_RPM, 100, 200)
        for interrupted in (False, True):
            connection = MagicMock()
            connection.in_waiting = len(packet)
            connection.read.side_effect = [packet, KeyboardInterrupt()] if interrupted else [packet]
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "cli.h5"
                ticks = [0, 0, 0] if interrupted else [0, 0, 2]
                with patch("vertisea_live.open_serial", return_value=connection), \
                        patch("vertisea_live.time.monotonic", side_effect=ticks):
                    self.assertEqual(main(["--port", "FAKE", "--output", str(path), "--duration", "1"]), 0)
                connection.close.assert_called_once()
                import h5py
                with h5py.File(path, "r") as archive:
                    self.assertEqual(bytes(archive["raw/bytes"][:]), packet)


class LiveGUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from vertisea_plot_v7 import VertiSeaGUI
        self.directory = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.gui = VertiSeaGUI(self.root)
        self.gui.session_directory = Path(self.directory.name)

    def tearDown(self):
        self.gui.close_window()
        self.directory.cleanup()

    def test_pause_records_exact_bytes_once_before_display(self):
        import h5py
        self.gui.recorder = LiveRecorder(Path(self.directory.name) / "gui.h5")
        packet = struct.pack("<BHH", TYPE_RPM, 100, 1200)
        connection = MagicMock()
        connection.in_waiting = len(packet)
        connection.read.return_value = packet
        self.gui.ser = connection
        self.gui.toggle_pause()
        self.gui._update_once()
        connection.in_waiting = 0
        self.gui._update_once()
        self.assertEqual(self.gui.rpm_data[-1], 1200)
        self.assertEqual(self.gui.rpm_var.get(), "N/A")
        self.gui.disconnect_serial()
        with h5py.File(Path(self.directory.name) / "gui.h5", "r") as archive:
            self.assertEqual(bytes(archive["raw/bytes"][:]), packet)
            self.assertEqual(archive["raw/chunks"].attrs["row_count"], 1)
        self.assertIsNone(self.gui.recorder)
        connection.close.assert_called_once()

    def test_recording_failure_is_visible_but_gui_continues(self):
        writer = MagicMock()
        writer.feed.side_effect = OSError("disk full")
        self.gui.recorder = writer
        connection = MagicMock()
        packet = struct.pack("<BHH", TYPE_RPM, 100, 900)
        connection.in_waiting = len(packet)
        connection.read.return_value = packet
        self.gui.ser = connection
        with patch("vertisea_plot_v7.messagebox.showerror") as dialog:
            self.gui._update_once()
        self.assertIn("RECORDING ERROR", self.gui.conn_status_var.get())
        self.assertEqual(self.gui.rpm_data[-1], 900)
        self.assertIsNone(self.gui.recorder)
        dialog.assert_called_once()
        writer.close.assert_called_once()

    def test_connect_auto_starts_and_link_loss_closes(self):
        self.gui.port_var.set("FAKE")
        connection = MagicMock()
        def check_open():
            self.assertFalse(connection.rts)
            self.assertFalse(connection.dtr)
            self.assertIsNone(self.gui.recorder)
        connection.open.side_effect = check_open
        with patch("vertisea_plot_v7.serial.Serial", return_value=connection), \
                patch.object(self.gui, "_confirm_if_buoy_port", return_value=True), \
                patch("vertisea_plot_v7.messagebox.showinfo"):
            self.gui.connect_serial()
        recorder = self.gui.recorder
        self.assertIsNotNone(recorder)
        self.assertTrue(recorder.path.exists())
        self.gui._on_link_lost(OSError("unplugged"))
        self.assertTrue(recorder.closed)
        self.assertIsNone(self.gui.ser)
        self.assertIn("Disconnected", self.gui.conn_status_var.get())

    def test_import_cycle_plot_and_png_metadata_without_csv(self):
        """Exercise actual atomic import, cycle rendering and image metadata."""
        from PIL import Image
        from test_session import synthetic_bin
        source = Path(self.directory.name) / "input.BIN"
        source.write_bytes(synthetic_bin())
        output = Path(self.directory.name) / "session.h5"
        with patch("vertisea_plot_v7.filedialog.askopenfilename", return_value=str(source)), \
                patch("vertisea_plot_v7.filedialog.asksaveasfilename", return_value=str(output)), \
                patch("vertisea_plot_v7.messagebox.showinfo"):
            self.assertIsNotNone(self.gui.load_bin_file())
        self.assertEqual(list(Path(self.directory.name).glob("*.csv")), [])
        with patch("vertisea_plot_v7.simpledialog.askfloat", side_effect=[0, .2]), \
                patch("vertisea_plot_v7.filedialog.asksaveasfilename", return_value=str(output)), \
                patch("vertisea_plot_v7.messagebox.askyesno", return_value=True), \
                patch("vertisea_plot_v7.messagebox.showinfo"):
            result = self.gui.analyze_cycle_dialog()
        self.assertEqual(result["cycles"][0]["method"], "selected")
        windows = [child for child in self.root.winfo_children() if hasattr(child, "cycle_canvas")]
        self.assertEqual(len(windows), 1)
        figure = windows[0].cycle_canvas.figure
        self.assertEqual(len(figure.axes), 3)
        button = next(child for child in windows[0].winfo_children()
                      if child.winfo_class() == "Button")
        image_path = Path(self.directory.name) / "cycle.png"
        with patch("vertisea_plot_v7.filedialog.asksaveasfilename", return_value=str(image_path)):
            button.invoke()
        with Image.open(image_path) as image:
            metadata = json.loads(image.info["Description"])
            self.assertEqual(len(metadata["battery"]["calibration"]), 1)
            self.assertIn("flags", metadata["rows"][0])
            self.assertEqual(metadata["cycles"][0]["coverage_fraction"], 1)

    def test_overwrite_cancel_preserves_session(self):
        output = Path(self.directory.name) / "existing.h5"
        output.write_bytes(b"original")
        with patch("vertisea_plot_v7.filedialog.asksaveasfilename", return_value=str(output)), \
                patch("vertisea_plot_v7.messagebox.askyesno", return_value=False), \
                patch("vertisea_session.import_session") as importer:
            self.assertIsNone(self.gui._import_sources(["fake.BIN"]))
        importer.assert_not_called()
        self.assertEqual(output.read_bytes(), b"original")

    def test_import_dependency_failure_is_visible(self):
        with patch("vertisea_plot_v7.filedialog.asksaveasfilename",
                   return_value=str(Path(self.directory.name) / "failed.h5")), \
                patch("vertisea_session.import_session", side_effect=OSError("Bad file descriptor")), \
                patch("vertisea_plot_v7.messagebox.showerror") as dialog:
            self.assertIsNone(self.gui._import_sources(["fake.BIN"]))
        self.assertIn("Bad file descriptor", dialog.call_args.args[1])


if __name__ == "__main__":
    unittest.main()