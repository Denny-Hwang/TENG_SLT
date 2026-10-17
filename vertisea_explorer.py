"""Offline Tk explorer for native and aligned VertiSea HDF5 data."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from vertisea_query import SessionReader, rolling_mean, estimated_power


def open_explorer(parent, path, *, active_path=None):
    if active_path is not None and Path(path).resolve() == Path(active_path).resolve():
        messagebox.showwarning("Recording in progress", "Close the active recorder before opening this HDF5 file.", parent=parent)
        return None
    try:
        return DataExplorer(parent, path)
    except Exception as error:
        messagebox.showerror("Cannot open session", str(error), parent=parent)
        return None


class DataExplorer(tk.Toplevel):
    def __init__(self, parent, path):
        with SessionReader(path) as reader:
            tables = reader.list_tables()
            self.metadata = {table: reader.list_columns(table) for table in tables}
            self.counts = {table: reader.row_count(table) for table in tables}
        super().__init__(parent)
        self.path = Path(path).resolve()
        self.title(f"Data Explorer - {self.path.name}")
        self.geometry("1180x780")
        self.minsize(760, 520)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.busy = False
        self.closed = False
        self.future = None
        self.poll_id = None
        self.table = None
        self.offset = 0
        self.selected_keys = []
        self.aligned = None
        self.page_data = None
        self.start_var = tk.StringVar(value="0")
        self.end_var = tk.StringVar(value="1")
        self.step_var = tk.StringVar(value="1")
        self.boot_var = tk.StringVar(value="All")
        self.source_var = tk.StringVar(value="All")
        self.method_var = tk.StringVar(value="mean")
        self.tolerance_var = tk.StringVar(value="1")
        self.gap_var = tk.StringVar(value="2.5")
        self.page_var = tk.StringVar(value="200")
        self.rolling_var = tk.StringVar(value="1")
        self.voltage_var = tk.StringVar()
        self.current_var = tk.StringVar()
        self.status_var = tk.StringVar(value=str(self.path))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        split = ttk.Panedwindow(self, orient="horizontal")
        split.grid(row=0, column=0, sticky="nsew")
        left = ttk.Frame(split, padding=6)
        right = ttk.Frame(split, padding=6)
        split.add(left, weight=1)
        split.add(right, weight=4)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        left.rowconfigure(3, weight=1)
        ttk.Label(left, text="Native tables").grid(row=0, column=0, sticky="w")
        self.tables = ttk.Treeview(left, columns=("rows",), show="tree headings", selectmode="browse", height=10)
        self.tables.heading("#0", text="Table")
        self.tables.heading("rows", text="Rows")
        self.tables.column("#0", width=190)
        self.tables.column("rows", width=65, anchor="e")
        self.tables.grid(row=1, column=0, sticky="nsew")
        table_scroll = ttk.Scrollbar(left, orient="vertical", command=self.tables.yview)
        table_scroll.grid(row=1, column=1, sticky="ns")
        self.tables.configure(yscrollcommand=table_scroll.set)
        for table in tables:
            self.tables.insert("", "end", iid=table, text=table, values=(self.counts[table],))
        self.tables.bind("<<TreeviewSelect>>", self.select_table)
        ttk.Label(left, text="Columns").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.columns = tk.Listbox(left, selectmode="extended", exportselection=False, height=10)
        self.columns.grid(row=3, column=0, sticky="nsew")
        column_scroll = ttk.Scrollbar(left, orient="vertical", command=self.columns.yview)
        column_scroll.grid(row=3, column=1, sticky="ns")
        column_x = ttk.Scrollbar(left, orient="horizontal", command=self.columns.xview)
        column_x.grid(row=4, column=0, sticky="ew")
        self.columns.configure(yscrollcommand=column_scroll.set, xscrollcommand=column_x.set)
        ttk.Button(left, text="Add To Join", command=self.add_columns).grid(row=5, column=0, sticky="ew", pady=4)
        ttk.Button(left, text="Clear Join", command=self.clear_join).grid(row=6, column=0, sticky="ew")
        self.join_label = ttk.Label(left, text="0 joined columns", wraplength=240)
        self.join_label.grid(row=7, column=0, sticky="w", pady=4)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        control_strip = ttk.Frame(right)
        control_strip.grid(row=0, column=0, sticky="ew")
        control_strip.columnconfigure(0, weight=1)
        control_canvas = tk.Canvas(control_strip, height=170, highlightthickness=0)
        control_canvas.grid(row=0, column=0, sticky="ew")
        controls = ttk.Frame(control_canvas)
        control_window = control_canvas.create_window(0, 0, window=controls, anchor="nw")
        control_scroll = ttk.Scrollbar(control_strip, orient="horizontal", command=control_canvas.xview)
        control_scroll.grid(row=1, column=0, sticky="ew")
        control_canvas.configure(xscrollcommand=control_scroll.set)
        def size_controls(event=None):
            width = max(controls.winfo_reqwidth(), control_canvas.winfo_width())
            control_canvas.itemconfigure(control_window, width=width)
            control_canvas.configure(height=controls.winfo_reqheight(), scrollregion=control_canvas.bbox("all"))
        controls.bind("<Configure>", size_controls)
        control_canvas.bind("<Configure>", size_controls)
        for column in range(6):
            controls.columnconfigure(column, weight=1)
        self._field(controls, "Start (s)", self.start_var, 0, 0)
        self._field(controls, "End (s)", self.end_var, 0, 2)
        self._field(controls, "Step (s)", self.step_var, 0, 4)
        self.boot_menu = self._field(controls, "Boot", self.boot_var, 1, 0, ["All"])
        self.source_menu = self._field(controls, "Source", self.source_var, 1, 2, ["All"])
        self._field(controls, "Method", self.method_var, 1, 4,
                    ["mean", "min", "max", "rms", "count", "nearest", "previous", "linear"])
        self._field(controls, "Tolerance (s)", self.tolerance_var, 2, 0)
        self._field(controls, "Max Gap (s)", self.gap_var, 2, 2)
        self._field(controls, "Rolling Rows", self.rolling_var, 2, 4)
        self._field(controls, "Page Rows", self.page_var, 3, 0, ["200", "500"])
        ttk.Button(controls, text="Native", command=lambda: self.show_native(reset=True)).grid(row=3, column=2, sticky="ew", padx=2)
        ttk.Button(controls, text="Align Join", command=self.show_aligned).grid(row=3, column=3, sticky="ew", padx=2)
        ttk.Button(controls, text="Plot", command=self.plot).grid(row=3, column=4, sticky="ew", padx=2)
        ttk.Button(controls, text="Export CSV", command=self.export_csv).grid(row=3, column=5, sticky="ew", padx=2)
        self.voltage_menu = self._field(controls, "Voltage (V)", self.voltage_var, 4, 0, [])
        self.current_menu = self._field(controls, "Current (mA)", self.current_var, 4, 2, [])
        ttk.Button(controls, text="Plot Estimated Power", command=lambda: self.plot(power=True)).grid(row=4, column=4, columnspan=2, sticky="ew", padx=2)
        self.tabs = ttk.Notebook(right)
        self.tabs.grid(row=1, column=0, sticky="nsew", pady=6)
        self.native_frame, self.native_tree = self._sheet("Native")
        self.aligned_frame, self.aligned_tree = self._sheet("Aligned")
        self.plot_frame = ttk.Frame(self.tabs)
        self.tabs.add(self.plot_frame, text="Plot")
        self.canvas = None
        footer = ttk.Frame(right)
        footer.grid(row=2, column=0, sticky="ew")
        ttk.Button(footer, text="Previous", command=lambda: self.page(-1)).pack(side="left")
        ttk.Button(footer, text="Next", command=lambda: self.page(1)).pack(side="left", padx=4)
        self.page_label = ttk.Label(footer, text="")
        self.page_label.pack(side="left")
        ttk.Label(self, textvariable=self.status_var, anchor="w").grid(row=1, column=0, sticky="ew", padx=6, pady=4)
        if tables:
            self.tables.selection_set(tables[0])

    def _field(self, parent, label, variable, row, column, choices=None):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=2, pady=3)
        widget = ttk.Entry(parent, textvariable=variable, width=10) if choices is None else ttk.Combobox(
            parent, textvariable=variable, values=choices, state="readonly", width=10)
        widget.grid(row=row, column=column + 1, sticky="ew", padx=2, pady=3)
        return widget

    def _sheet(self, label):
        frame = ttk.Frame(self.tabs)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, show="headings", selectmode="extended")
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tabs.add(frame, text=label)
        return frame, tree

    def _run(self, operation, done):
        if self.busy or self.closed:
            return
        self.busy = True
        self.status_var.set("Reading " + self.path.name)
        def work():
            with SessionReader(self.path) as reader:
                return operation(reader)
        self.future = self.executor.submit(work)
        def poll():
            if self.closed:
                return
            if not self.future.done():
                self.poll_id = self.after(40, poll)
                return
            self.busy = False
            try:
                result = self.future.result()
                self.status_var.set(str(self.path))
                done(result)
            except Exception as error:
                self.status_var.set(str(error))
                messagebox.showerror("Explorer", str(error), parent=self)
        self.poll_id = self.after(40, poll)

    def select_table(self, event=None):
        if self.busy:
            return
        selection = self.tables.selection()
        if not selection:
            return
        self.table = selection[0]
        self.column_names = list(self.metadata[self.table])
        self.columns.delete(0, "end")
        for name in self.column_names:
            self.columns.insert("end", name)
        for index, name in enumerate(self.column_names):
            if name != "records_json":
                self.columns.selection_set(index)
        def ready(info):
            self.start_var.set(str(info["start_s"] or 0))
            self.end_var.set(str((info["end_s"] or 0) + 1))
            for menu, variable, values in ((self.boot_menu, self.boot_var, info["boots"]),
                                           (self.source_menu, self.source_var, info["sources"])):
                menu.configure(values=["All"] + [str(value) for value in values])
                variable.set(str(values[0]) if menu is self.boot_menu and values else "All")
            self.show_native(reset=True)
        self._run(lambda reader: reader.table_info(self.table), ready)

    def _native_columns(self):
        return [self.column_names[index] for index in self.columns.curselection()]

    def add_columns(self):
        if not self.table:
            return
        for name in self._native_columns():
            key = (self.table, name)
            if self.metadata[self.table][name]["numeric"] and name not in ("ts_ms", "boot_id", "source_index", "segment_id", "source_row_index"):
                if key not in self.selected_keys:
                    self.selected_keys.append(key)
        self._join_changed()

    def clear_join(self):
        self.selected_keys.clear()
        self._join_changed()

    def _join_changed(self):
        self.aligned = None
        self.join_label.configure(text=f"{len(self.selected_keys)} joined columns\n" + "\n".join(f"{table}/{name}" for table, name in self.selected_keys[:2]))
        labels = [f"{table}/{name}" for table, name in self.selected_keys]
        for menu in (self.voltage_menu, self.current_menu):
            menu.configure(values=labels)
        self.voltage_var.set(next((label for label in labels if "voltage" in label.lower()), ""))
        self.current_var.set(next((label for label in labels if "current_mA" in label), ""))

    def _filters(self):
        return dict(start=float(self.start_var.get()), end=float(self.end_var.get()),
                    boot=None if self.boot_var.get() == "All" else int(self.boot_var.get()),
                    source=None if self.source_var.get() == "All" else int(self.source_var.get()))

    def _fill(self, tree, names, rows):
        tree.delete(*tree.get_children())
        identifiers = [f"column_{index}" for index in range(len(names))]
        tree.configure(columns=identifiers)
        for identifier, name in zip(identifiers, names):
            tree.heading(identifier, text=name)
            tree.column(identifier, width=140, minwidth=80, stretch=False)
        for row in rows:
            tree.insert("", "end", values=[value.decode("utf-8") if isinstance(value, bytes) else
                                           f"{value:.7g}" if isinstance(value, float) else str(value) for value in row])

    def show_native(self, reset=False):
        if self.busy or not self.table:
            return
        try:
            names = self._native_columns()
            filters = self._filters() if any(name in self.metadata[self.table] for name in ("ts_ms", "time_s", "timestamp")) else {}
            limit = int(self.page_var.get())
            if reset:
                self.offset = 0
            table, offset = self.table, self.offset
            def ready(data):
                self.page_data = data
                self._fill(self.native_tree, names, zip(*(data[name] for name in names)))
                self.tabs.select(self.native_frame)
                size = len(data[names[0]])
                self.page_label.configure(text=f"Selected rows {offset + 1 if size else offset} - {offset + size}")
            self._run(lambda reader: reader.read_page(table, names, offset=offset, limit=limit, **filters), ready)
        except Exception as error:
            messagebox.showerror("Native selection", str(error), parent=self)

    def page(self, direction):
        if self.busy:
            return
        if self.tabs.select() == str(self.aligned_frame) and self.aligned is not None:
            self.aligned_offset = max(0, min(max(0, len(self.aligned.time_s) - 1), self.aligned_offset + direction * int(self.page_var.get())))
            self._show_aligned_page()
        else:
            self.offset = max(0, self.offset + direction * int(self.page_var.get()))
            self.show_native()

    def show_aligned(self):
        if self.busy:
            return
        if not self.selected_keys:
            self.add_columns()
        try:
            filters = self._filters()
            start, end = filters.pop("start"), filters.pop("end")
            options = dict(step=float(self.step_var.get()), method=self.method_var.get(),
                           tolerance=float(self.tolerance_var.get()), max_gap=float(self.gap_var.get()), **filters)
            keys = self.selected_keys.copy()
            def ready(result):
                self.aligned = result
                self.aligned_offset = 0
                self._show_aligned_page()
            self._run(lambda reader: reader.align(keys, start, end, **options), ready)
        except Exception as error:
            messagebox.showerror("Aligned selection", str(error), parent=self)

    def _show_aligned_page(self):
        result = self.aligned
        begin = self.aligned_offset
        stop = min(begin + int(self.page_var.get()), len(result.time_s))
        names = ["time_s"] + [f"{table}/{name}:{field}" for table, name in result.columns
                              for field in ("value", "valid", "count", "coverage", "flags")]
        rows = []
        for index in range(begin, stop):
            row = [result.time_s[index]]
            for column in result.columns.values():
                row.extend(getattr(column, field)[index] for field in ("values", "valid", "count", "coverage", "flags"))
            rows.append(row)
        self._fill(self.aligned_tree, names, rows)
        self.tabs.select(self.aligned_frame)
        self.page_label.configure(text=f"Grid rows {begin + 1} - {stop} / {len(result.time_s)}")

    def plot(self, power=False):
        if self.aligned is None:
            messagebox.showwarning("No aligned data", "Run Align Join first.", parent=self)
            return
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
            result = self.aligned
            window = int(self.rolling_var.get())
            series = [(f"{table}/{name}" + (f" (rolling {window})" if window > 1 else ""),
                       rolling_mean(column, window), column.segment) for (table, name), column in result.columns.items()]
            if power:
                mapping = {f"{table}/{name}": column for (table, name), column in result.columns.items()}
                voltage = mapping[self.voltage_var.get()]
                current = mapping[self.current_var.get()]
                series = [("Estimated power (mW; V x mA, not integrated energy)", estimated_power(voltage, current),
                           list(zip(voltage.segment, current.segment)))]
            if len(series) > 12:
                raise ValueError("Select at most 12 plot channels")
            for child in self.plot_frame.winfo_children():
                child.destroy()
            figure = Figure(figsize=(8, max(4, 1.6 * len(series))), dpi=100)
            axes = figure.subplots(len(series), 1, sharex=True, squeeze=False).ravel()
            for axis, (label, values, segments) in zip(axes, series):
                begin = 0
                for index in range(1, len(values) + 1):
                    if index == len(values) or segments[index] != segments[index - 1]:
                        axis.plot(result.time_s[begin:index], values[begin:index], linewidth=.8,
                                  marker="." if index - begin == 1 else None, color="#246d85")
                        begin = index
                axis.set_ylabel(label.rsplit("/", 1)[-1], fontsize=8, wrap=True)
                axis.grid(alpha=.2)
            axes[-1].set_xlabel("Native boot time (s)")
            figure.tight_layout()
            self.canvas = FigureCanvasTkAgg(figure, master=self.plot_frame)
            NavigationToolbar2Tk(self.canvas, self.plot_frame).pack(side="bottom", fill="x")
            self.canvas.get_tk_widget().pack(fill="both", expand=True)
            self.tabs.select(self.plot_frame)
            self.canvas.draw()
        except Exception as error:
            messagebox.showerror("Plot", str(error), parent=self)

    def export_csv(self):
        if self.busy:
            return
        output = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not output:
            return
        try:
            if self.tabs.select() != str(self.native_frame) and self.aligned is not None:
                result = self.aligned
                operation = lambda reader: reader.export_aligned_csv(result, output)
            else:
                table, names = self.table, self._native_columns()
                filters = self._filters() if any(name in self.metadata[table] for name in ("ts_ms", "time_s", "timestamp")) else {}
                operation = lambda reader: reader.export_native_csv(table, names, output, **filters)
            self._run(operation, lambda result: self.status_var.set("Exported " + str(output)))
        except Exception as error:
            messagebox.showerror("CSV export", str(error), parent=self)

    def close(self):
        self.closed = True
        if self.poll_id:
            self.after_cancel(self.poll_id)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    arguments = parser.parse_args(argv)
    root = tk.Tk()
    root.withdraw()
    explorer = open_explorer(root, arguments.session)
    if explorer is None:
        root.destroy()
        return 1
    explorer.bind("<Destroy>", lambda event: root.destroy() if event.widget is explorer else None)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())