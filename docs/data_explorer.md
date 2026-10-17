# Data Explorer

Implementation 2026-10-17: [UNCONFIRMED]. Synthetic query and Tk tests exercise
the workflows; deployment interpretation and operator confirmation remain pending.

## Open and Browse

From the ground station, Data Explorer opens an existing `.h5` or `.hdf5` file
without importing BIN or connecting serial. The chooser starts at the last
imported/opened file. Close the active recorder before opening its file. This is
an offline reader, not a concurrent writer/SWMR monitor. Standalone users must
also ensure their archive is not being written by another process.

From the TENG_SLT root in its configured environment:

```console
python vertisea_explorer.py sessions/session.h5
```

Choose a table on the left, select native columns, and use Native to display
200 or 500 filtered rows. Previous/Next page the current sheet. Sheets scroll
horizontally and vertically. Native time is seconds since boot, not UTC.
Start is inclusive, end exclusive. Tables without a clock remain browsable
without time filters. Native export writes the entire filtered subset, not just
the visible page. Numeric and original JSON/string columns remain unchanged.

## Join and Plot

Add To Join retains selected numeric measurement columns across table selections.
Clear Join resets the selection. Set start/end, step (default 1 second), boot,
source, and method, then Align Join. Multiple boots require explicit selection;
identically numbered native times must not be interpreted as one timeline.

Mean/min/max/RMS/count aggregate finite samples within half-open bins. Count
is NaN for an empty bin, not an apparent measured zero. Mixed source/segment
bins are invalid and flagged ambiguous. Nearest/previous/linear use only
strictly increasing, same-source, same-boot brackets, no extrapolation.
Max Gap bounds bracket length; Tolerance bounds distance from the contributing
sample (both samples for linear). Duplicate/regressing brackets are invalid.
Default Max Gap is 2.5 seconds and Tolerance is 1 second in the GUI.

Each selected column has value, valid, count, coverage and flags. Count is the
number of finite contributions, even when a mixed-source bin is rejected.
Aggregate coverage is finite samples / observed samples, **not duration coverage
or evidence of no dropped samples**. Interpolation coverage is 0/1 bracket
support. Empty/ambiguous values are NaN with zero coverage. Native records remain
authoritative; grid values are exploratory, not replacements for acquisition.

Plot uses shared time with separate channel axes and breaks source boundaries.
Rolling Rows adds a trailing mean, resets at missing points or source boundaries,
and does not mutate aligned/native values. Select voltage in V and current in mA
for Estimated Power in mW. The product of averaged channels is an estimate, not
a rigorous energy integral or necessarily the average of instantaneous power.
Export from Aligned/Plot writes the original aligned values and coverage flags,
not smoothed traces or estimated power. Matplotlib's toolbar saves plot images.

## APIs and Limits

Dependencies are existing numpy, h5py and matplotlib; no pandas is required.
Query imports are lazy. HDF5 handles are closed by the context manager. GUI work
uses one worker and a fresh read-only context per job; Tk updates stay on Tk's
thread. Closing a window allows an in-progress worker to finish and close its
handle; jobs are not cancellable mid-chunk.

```python
from vertisea_query import SessionReader, rolling_mean, estimated_power

with SessionReader("sessions/session.h5") as reader:
    tables = reader.list_tables()
    info = reader.table_info("/raw/current_fast")
    page = reader.read_page("/raw/current_fast", ["ts_ms", "current_mA"],
                            boot=0, offset=0, limit=200, start=0, end=14400)
    result = reader.align([("/raw/current_fast", "current_mA"),
                           ("/raw/battery_voltage", "voltage_V")],
                          0, 43200, boot=0, step=1, method="mean")
    reader.export_native_csv("/raw/current_fast", ["ts_ms", "current_mA"],
                             "current.csv", boot=0, start=0, end=14400)
    reader.export_aligned_csv(result, "aligned.csv")
    smooth = rolling_mean(result.columns[("/raw/current_fast", "current_mA")], 5)
```

`iter_native` streams chunks (default 65,536 rows). `read_page` caps output at
500 rows and scans in chunks, including for time filtering and filtered offsets;
deep pages can therefore take longer without a storage index. `table_info`
scans time/identity columns in chunks for counts/ranges/boot/source choices.
Alignment reads only selected columns plus time/identity columns. Interpolation
retains one bracket across chunks and restricts scanning output to the requested
range plus Max Gap. No full native high-rate column is loaded into RAM.

Grid caps default to 100,000 rows and 1,000,000 column points. Exceeding either
raises an error before grid allocation; increase step, shorten range, or select
fewer columns. Twelve hours at one second is 43,200 rows. GUI plots cap channels
at 12. Budgets can be explicitly configured in SessionReader for API use.
CSV is written incrementally; aligned export streams the bounded result rows.
Archives are read-only and CSV cannot overwrite the input HDF5 file.

## Validation

```console
python -m unittest discover -s tests -p test_query.py -v
python -m unittest discover -s tests -p test_explorer.py -v
python -m unittest discover -s tests -p test_charging_plot.py -v
```

Tk tests require a desktop display. This project's `.venv` is Conda: use
`conda run -p .venv --no-capture-output python ...`, or a subprocess environment
with `.venv/Library/bin` prepended to PATH. Tests use synthetic archives and no
hardware. Session importer/storage code is owned separately and is unchanged.