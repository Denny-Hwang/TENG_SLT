from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_query import make_archive
from vertisea_explorer import DataExplorer, open_explorer


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "session.h5"
        make_archive(self.path)
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.dialog = patch("vertisea_explorer.messagebox.showerror", side_effect=lambda *args, **kwargs: self.errors.append(args))
        self.dialog.start()
        self.window = DataExplorer(self.root, self.path)
        self.wait()

    def wait(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.root.update()
            if not self.window.busy:
                self.root.update()
                if not self.window.busy:
                    return
            time.sleep(.01)
        self.fail("Explorer worker did not finish")

    def tearDown(self):
        self.window.close()
        self.root.destroy()
        self.dialog.stop()
        self.temp.cleanup()

    def select(self, table, columns):
        self.window.tables.selection_set(table)
        self.root.update()
        self.wait()
        self.window.columns.selection_clear(0, "end")
        for name in columns:
            self.window.columns.selection_set(self.window.column_names.index(name))

    def test_native_join_plot_resize(self):
        self.select("/raw/fast", ["value"])
        self.window.show_native(reset=True)
        self.wait()
        self.assertEqual(len(self.window.native_tree.get_children()), 7)
        self.window.add_columns()
        self.select("/raw/slow", ["value"])
        self.window.add_columns()
        self.window.show_aligned()
        self.wait()
        self.assertEqual(len(self.window.aligned.columns), 2)
        self.window.plot()
        self.root.update()
        self.assertEqual(len(self.window.canvas.figure.axes), 2)
        self.window.geometry("800x560")
        self.root.update()
        self.assertTrue(self.window.native_tree.cget("xscrollcommand"))
        self.assertEqual(self.errors, [])

    def test_export_and_invalid_selection(self):
        self.select("/raw/slow", ["value"])
        self.window.add_columns()
        self.window.show_aligned()
        self.wait()
        output = Path(self.temp.name) / "aligned.csv"
        with patch("vertisea_explorer.filedialog.asksaveasfilename", return_value=str(output)):
            self.window.export_csv()
            self.wait()
        self.assertIn("coverage", output.read_text())
        self.window.step_var.set("0")
        self.window.show_aligned()
        self.wait()
        self.assertTrue(self.errors)

    def test_active_writer_guard(self):
        with patch("vertisea_explorer.messagebox.showwarning") as warning:
            self.assertIsNone(open_explorer(self.root, self.path, active_path=self.path))
            warning.assert_called_once()

    def test_ground_station_open_without_import_and_last_file(self):
        from types import SimpleNamespace
        from vertisea_plot_v7 import VertiSeaGUI
        gui = SimpleNamespace(root=self.root, _last_session_path=str(self.path),
                              session_directory=self.path.parent, recorder=None)
        with patch("vertisea_plot_v7.filedialog.askopenfilename", return_value=str(self.path)) as choose:
            with patch("vertisea_explorer.open_explorer", return_value=self.window) as opened:
                self.assertIs(VertiSeaGUI.data_explorer_dialog(gui), self.window)
                self.assertEqual(choose.call_args.kwargs["initialfile"], "session.h5")
                opened.assert_called_once_with(self.root, str(self.path), active_path=None)


if __name__ == "__main__":
    unittest.main()