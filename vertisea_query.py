"""Bounded, read-only queries over native VertiSea HDF5 column tables."""

from dataclasses import dataclass
from pathlib import Path
import csv
import math


@dataclass
class ColumnResult:
    values: object
    valid: object
    count: object
    coverage: object
    flags: object
    segment: object


@dataclass
class AlignedResult:
    time_s: object
    columns: dict
    step_s: float
    boot: object
    method: str


class SessionReader:
    """Context-managed reader; construction does not import h5py or read data.

    Keys are (absolute table path, column name). Native ranges and aligned bins
    are [start, end). All time coordinates are native seconds since boot.
    """

    def __init__(self, path, *, chunk_rows=65536, max_page=500, max_rows=100000,
                 point_budget=1000000):
        for name, value in (("chunk_rows", chunk_rows), ("max_page", max_page),
                            ("max_rows", max_rows), ("point_budget", point_budget)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.path = Path(path).resolve()
        self.chunk_rows = chunk_rows
        self.max_page = max_page
        self.max_rows = max_rows
        self.point_budget = point_budget
        self.archive = None

    def __enter__(self):
        import h5py
        import numpy as np
        self.np = np
        self.archive = h5py.File(self.path, "r")
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.archive is not None:
            self.archive.close()
            self.archive = None

    def _open(self):
        if self.archive is None:
            raise RuntimeError("Use SessionReader inside a with block")
        return self.archive

    def list_tables(self):
        import h5py
        tables = []
        def visit(name, node):
            if isinstance(node, h5py.Group) and ("row_count" in node.attrs or "records_json" in node):
                tables.append("/" + name)
        self._open().visititems(visit)
        return tables

    def list_columns(self, table):
        import h5py
        group = self._open()[table]
        return {name: {"dtype": str(node.dtype), "numeric": node.dtype.kind in "biuf",
                       "unit": str(node.attrs.get("unit", ""))}
                for name, node in group.items()
                if isinstance(node, h5py.Dataset) and node.ndim == 1}

    def row_count(self, table):
        columns = self.list_columns(table)
        lengths = {len(self._open()[table][name]) for name in columns}
        if len(lengths) > 1:
            raise ValueError(f"Unequal column lengths in {table}")
        return next(iter(lengths), int(self._open()[table].attrs.get("row_count", 0)))

    @staticmethod
    def _range(start, end):
        if start is not None and (not math.isfinite(start) or start < 0):
            raise ValueError("start must be finite and nonnegative")
        if end is not None and (not math.isfinite(end) or end < 0):
            raise ValueError("end must be finite and nonnegative")
        if start is not None and end is not None and end <= start:
            raise ValueError("end must be greater than start")

    def _clock(self, table):
        columns = self.list_columns(table)
        for name, scale in (("ts_ms", .001), ("time_s", 1.), ("timestamp", 1.)):
            if name in columns:
                return name, scale
        return None, 1.

    def iter_native(self, table, columns=None, *, start=None, end=None, boot=None, source=None):
        """Yield bounded selected-column chunks, never records_json implicitly."""
        self._range(start, end)
        available = self.list_columns(table)
        names = list(columns) if columns is not None else list(available)
        if not names or any(name not in available for name in names):
            raise ValueError("Select existing columns")
        clock, scale = self._clock(table)
        if clock is None and (start is not None or end is not None):
            raise ValueError(f"{table} has no native time column")
        needed = set(names)
        if clock:
            needed.add(clock)
        for identifier, selected in (("boot_id", boot), ("source_index", source)):
            if selected is not None:
                if identifier not in available:
                    if selected != 0:
                        raise ValueError(f"{table} has no {identifier}; only implicit 0 is available")
                else:
                    needed.add(identifier)
        group = self._open()[table]
        total = self.row_count(table)
        for offset in range(0, total, self.chunk_rows):
            stop = min(offset + self.chunk_rows, total)
            data = {name: group[name][offset:stop] for name in needed}
            mask = self.np.ones(stop - offset, dtype=bool)
            if clock:
                times = data[clock] * scale
                mask &= self.np.isfinite(times)
                if start is not None:
                    mask &= times >= start
                if end is not None:
                    mask &= times < end
            for identifier, selected in (("boot_id", boot), ("source_index", source)):
                if selected is not None and identifier in data:
                    mask &= data[identifier] == selected
            if mask.any():
                yield {name: data[name][mask] for name in names}

    def read_page(self, table, columns=None, *, offset=0, limit=200, **filters):
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.max_page:
            raise ValueError(f"limit must be between 1 and {self.max_page}")
        names = list(columns) if columns is not None else list(self.list_columns(table))
        pieces = {name: [] for name in names}
        skipped = taken = 0
        for chunk in self.iter_native(table, names, **filters):
            size = len(chunk[names[0]])
            begin = max(0, offset - skipped)
            amount = min(size - begin, limit - taken)
            if amount > 0:
                for name in names:
                    pieces[name].append(chunk[name][begin:begin + amount])
                taken += amount
            skipped += size
            if taken == limit:
                break
        return {name: self.np.concatenate(parts) if parts else
                self.np.empty(0, dtype=self._open()[table][name].dtype)
                for name, parts in pieces.items()}

    def table_info(self, table):
        clock, scale = self._clock(table)
        columns = self.list_columns(table)
        names = [name for name in (clock, "boot_id", "source_index") if name in columns]
        minimum, maximum = math.inf, -math.inf
        boots, sources = set(), set()
        if names:
            for chunk in self.iter_native(table, names):
                if clock:
                    times = chunk[clock] * scale
                    minimum = min(minimum, float(times.min()))
                    maximum = max(maximum, float(times.max()))
                boots.update(chunk["boot_id"].tolist() if "boot_id" in chunk else [0])
                sources.update(chunk["source_index"].tolist() if "source_index" in chunk else [0])
        return {"path": table, "columns": columns, "row_count": self.row_count(table),
                "start_s": minimum if math.isfinite(minimum) else None,
                "end_s": maximum if math.isfinite(maximum) else None,
                "boots": sorted(boots), "sources": sorted(sources)}

    def align(self, keys, start, end, *, step=1., method="mean", boot=None,
              source=None, tolerance=None, max_gap=2.5):
        """Aggregate bins or interpolate within strictly increasing source segments.

        Interpolation never extrapolates. Select a boot when clocks overlap.
        count is finite contributing samples; coverage is finite/observed for
        aggregates and 0/1 bracket support for interpolation, not time coverage.
        """
        np = self.np
        self._range(start, end)
        if start is None or end is None or not math.isfinite(step) or step <= 0:
            raise ValueError("Supply finite start/end and positive step")
        if method not in ("mean", "min", "max", "rms", "count", "nearest", "previous", "linear"):
            raise ValueError("Unknown alignment method")
        tolerance = step if tolerance is None else tolerance
        if not math.isfinite(tolerance) or tolerance < 0 or not math.isfinite(max_gap) or max_gap <= 0:
            raise ValueError("tolerance must be nonnegative and max_gap positive, both finite")
        keys = list(dict.fromkeys(("/" + table.strip("/"), column) for table, column in keys))
        if not keys:
            raise ValueError("Select at least one numeric column")
        requested_rows = (end - start) / step
        if not math.isfinite(requested_rows) or requested_rows > self.max_rows:
            raise ValueError("Grid exceeds row/point budget; increase step or shorten range")
        rows_float = math.ceil(requested_rows)
        if rows_float > self.max_rows or rows_float * len(keys) > self.point_budget:
            raise ValueError("Grid exceeds row/point budget; increase step or shorten range")
        grid = start + np.arange(rows_float) * step
        results = {}
        aggregate = method in ("mean", "min", "max", "rms", "count")
        grouped = {}
        for table, column in keys:
            metadata = self.list_columns(table)
            if column not in metadata or not metadata[column]["numeric"]:
                raise ValueError(f"Not a numeric column: {table}/{column}")
            grouped.setdefault(table, []).append(column)
        query_boots = set()
        for table, selected in grouped.items():
            clock, scale = self._clock(table)
            if clock is None:
                raise ValueError(f"{table} has no native time column")
            available = self.list_columns(table)
            identifiers = [name for name in ("boot_id", "source_index", "segment_id") if name in available]
            names = list(dict.fromkeys([clock] + identifiers + selected))
            states = {}
            for column in selected:
                states[column] = {"sum": np.zeros(len(grid)), "count": np.zeros(len(grid), dtype=np.int64),
                                  "observed": np.zeros(len(grid), dtype=np.int64),
                                  "value": np.full(len(grid), np.nan),
                                  "owner": np.full(len(grid), -1, dtype=np.int64),
                                  "ambiguous": np.zeros(len(grid), dtype=bool)}
            tokens, seen_boots = {}, set()
            previous = None
            def assign(column, indices, values, counts, token):
                state = states[column]
                conflict = (state["owner"][indices] != -1) & (state["owner"][indices] != token)
                state["ambiguous"][indices[conflict]] = True
                state["owner"][indices] = token
                state["value"][indices] = values
                state["count"][indices] = counts
            filters = dict(boot=boot, source=source)
            if aggregate:
                filters.update(start=start, end=end)
            else:
                filters.update(start=max(0., start - max_gap), end=end + max_gap)
            for chunk in self.iter_native(table, names, **filters):
                times = chunk[clock] * scale
                boot_values = chunk.get("boot_id", np.zeros(len(times), dtype=int))
                source_values = chunk.get("source_index", np.zeros(len(times), dtype=int))
                segment_values = chunk.get("segment_id", source_values)
                seen_boots.update(boot_values.tolist())
                query_boots.update(seen_boots)
                if boot is None and len(query_boots) > 1:
                    raise ValueError("Multiple boots: select boot explicitly before alignment")
                identities = list(zip(boot_values.tolist(), source_values.tolist(), segment_values.tolist()))
                owners = np.array([tokens.setdefault(identity, len(tokens)) for identity in identities])
                if aggregate:
                    bins = np.floor((times - start) / step).astype(int)
                    for column in selected:
                        state = states[column]
                        values = chunk[column].astype(float)
                        np.add.at(state["observed"], bins, 1)
                        finite = np.isfinite(values)
                        good_bins, good_values = bins[finite], values[finite]
                        np.add.at(state["count"], good_bins, 1)
                        np.add.at(state["sum"], good_bins, good_values ** 2 if method == "rms" else good_values)
                        if method in ("min", "max"):
                            fill = np.inf if method == "min" else -np.inf
                            state["value"][np.isnan(state["value"])] = fill
                            operation = np.minimum.at if method == "min" else np.maximum.at
                            operation(state["value"], good_bins, good_values)
                        for token in np.unique(owners):
                            indices = np.unique(bins[owners == token])
                            conflict = (state["owner"][indices] != -1) & (state["owner"][indices] != token)
                            state["ambiguous"][indices[conflict]] = True
                            state["owner"][indices] = token
                    continue
                for index, right_time in enumerate(times):
                    token = int(owners[index])
                    right_values = {column: float(chunk[column][index]) for column in selected}
                    exact = np.searchsorted(grid, right_time)
                    if exact < len(grid) and grid[exact] == right_time:
                        for column in selected:
                            if math.isfinite(right_values[column]):
                                assign(column, np.array([exact]), right_values[column], 1, token)
                    if previous is not None:
                        left_time, left_token, left_values = previous
                        gap = right_time - left_time
                        if left_token == token and 0 < gap <= max_gap:
                            begin = np.searchsorted(grid, left_time, side="right")
                            stop = np.searchsorted(grid, right_time, side="left")
                            indices = np.arange(begin, stop)
                            distance_left = grid[indices] - left_time
                            distance_right = right_time - grid[indices]
                            for column in selected:
                                left, right = left_values[column], right_values[column]
                                if method == "linear":
                                    supported = (distance_left <= tolerance) & (distance_right <= tolerance)
                                    values = left + (right - left) * distance_left / gap
                                    supported &= math.isfinite(left) and math.isfinite(right)
                                    counts = 2
                                elif method == "previous":
                                    supported = (distance_left <= tolerance) & math.isfinite(left)
                                    values = np.full(len(indices), left)
                                    counts = 1
                                else:
                                    use_left = distance_left <= distance_right
                                    values = np.where(use_left, left, right)
                                    supported = (np.minimum(distance_left, distance_right) <= tolerance) & np.isfinite(values)
                                    counts = 1
                                assign(column, indices[supported], values[supported], counts, token)
                        elif left_token == token and gap <= 0:
                            indices = np.flatnonzero((grid >= right_time) & (grid <= left_time))
                            for column in selected:
                                states[column]["ambiguous"][indices] = True
                    previous = right_time, token, right_values
            for column in selected:
                state = states[column]
                count = state["count"]
                valid = (count > 0) & ~state["ambiguous"]
                values = state["value"]
                if aggregate and method in ("mean", "rms"):
                    values = np.divide(state["sum"], count, out=np.full(len(grid), np.nan), where=count > 0)
                    if method == "rms":
                        values = np.sqrt(values)
                elif method == "count":
                    values = count.astype(float)
                values[~valid] = np.nan
                coverage = np.divide(count, state["observed"], out=np.zeros(len(grid)),
                                     where=state["observed"] > 0) if aggregate else valid.astype(float)
                coverage[~valid] = 0
                flags = np.where(state["ambiguous"], "ambiguous", np.where(valid, "valid", "empty"))
                results[(table, column)] = ColumnResult(values, valid, count, coverage, flags, state["owner"])
        return AlignedResult(grid, results, step, boot, method)

    def _csv_path(self, output):
        if Path(output).resolve() == self.path:
            raise ValueError("CSV output cannot replace the HDF5 archive")
        return output

    def export_native_csv(self, table, columns, output, **filters):
        names = list(columns)
        if not names or any(name not in self.list_columns(table) for name in names):
            raise ValueError("Select existing columns")
        self._range(filters.get("start"), filters.get("end"))
        with open(self._csv_path(output), "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(names)
            for chunk in self.iter_native(table, names, **filters):
                for row in zip(*(chunk[name] for name in names)):
                    writer.writerow([value.decode("utf-8") if isinstance(value, bytes) else value for value in row])

    def export_aligned_csv(self, result, output):
        keys = list(result.columns)
        with open(self._csv_path(output), "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["time_s"] + [f"{table}/{column}:{field}" for table, column in keys
                                          for field in ("value", "valid", "count", "coverage", "flags")])
            for index, time in enumerate(result.time_s):
                row = [time]
                for key in keys:
                    column = result.columns[key]
                    row.extend(getattr(column, field)[index] for field in ("values", "valid", "count", "coverage", "flags"))
                writer.writerow(row)


def rolling_mean(result, window=5):
    """Trailing mean of contiguous finite points in one source segment only."""
    import numpy as np
    if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
        raise ValueError("window must be a positive integer")
    output = np.full(len(result.values), np.nan)
    sums = np.concatenate(([0.], np.cumsum(np.where(result.valid & np.isfinite(result.values), result.values, 0.))))
    begin = 0
    for index, value in enumerate(result.values):
        if not result.valid[index] or not np.isfinite(value):
            begin = index + 1
            continue
        if index and result.segment[index] != result.segment[index - 1]:
            begin = index
        first = max(begin, index - window + 1)
        output[index] = (sums[index + 1] - sums[first]) / (index - first + 1)
    return output


def estimated_power(voltage, current):
    """V times mA yields estimated mW; NOT an energy integral from averages."""
    import numpy as np
    if len(voltage.values) != len(current.values):
        raise ValueError("Power inputs must share an aligned grid")
    valid = voltage.valid & current.valid
    return np.where(valid, voltage.values * current.values, np.nan)