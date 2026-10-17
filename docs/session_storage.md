# Offline Session Storage

## GUI and live recording

The GUI starts a timestamped live HDF5 file under sessions when COM connection
succeeds. The shared vertisea_live recorder also runs without the GUI:
`python vertisea_live.py --port COM7 --output sessions/live.h5 --duration 60`.
Close the GUI first: only one process may own the serial port. Omit duration for
continuous recording until Ctrl-C. Raw receive chunks are preserved and writer
errors are surfaced. Live records do not contain high-rate raw SD streams.

Load BIN File now produces HDF5 rather than automatically scattering CSV files.
Import Session accepts multiple BIN files or a directory. Analyze Cycle asks for
start/end in boot seconds, creates a selected-cycle HDF5, reports coverage/energy
and plots I/P/E; Export Figure saves PNG with analysis provenance. Legacy CSV
conversion remains available through vertisea_protocol.py, not the GUI default.

`python scripts/make_session_example.py` produces a clearly synthetic 20-second
example in sessions/synthetic_example with session.h5 and cycles.csv.

Implementation added 2026-10-16; HDF5 runtime validation requires h5py. This is an
offline SD importer, not a live HDF5 recorder. Firmware and GUI acquisition remain
independent. The existing stdlib protocol parser remains the only BIN decoder.

## APIs

`vertisea_session.import_session(paths, output, cycle_start=None, cycle_end=None)`
accepts a path, directory, or iterable of paths. Explicit files retain supplied
order; directories recursively expand case-insensitive BIN extensions in lexical
path order. Supply chronologically ordered files when filenames are ambiguous.
Duplicate paths are rejected. Empty files, empty directories and empty input lists
produce valid empty sessions. Returns output path, source manifest, warnings,
charging summary and cycle summaries.

Byte-identical files at different paths are SHA-256 detected, warned and skipped
before parsing. Every supplied source keeps its input `source_index` in the
manifest; duplicate entries contain `duplicate_of_source_index` and `bin_dataset`
pointing to the original archived bytes. They add no native rows, analysis, or
second byte copy. Consequently raw source group indices need not be contiguous.
An identical reboot capture is indistinguishable from a copied file and is skipped.
Duplicate paths themselves still raise `ValueError`.

Directory import emits `directory_lexical_order`: it does not scan/parse every BIN
in advance to sort RTC anchors or trust copy-modified mtimes. Use sortable full
date directory names, or an explicit chronological file list across midnight,
month/year changes, and ambiguous legacy names. RTC regressions are diagnosed
during import, not used to reorder sources. Boot IDs depend on supplied ordering.

### Field Directory Workflow

Keep one project directory with a separate run for each deployment:

```text
project/
	run-2026-10-17/
		raw-bin/
			2026-10-17/   (original five-minute BIN files)
			2026-10-18/
		derived/
			session.h5
		export/
			cycles.csv
```

Copy the SD directory structure into `raw-bin` without renaming or editing the
original BIN files. Keep a separate backup. A four-hour run has roughly 48 rotations;
a twelve-hour run roughly 144. Import the run's raw directory into one derived
archive rather than merging BIN bytes or generating per-stream CSVs for every file:

```console
python vertisea_session.py project/run-2026-10-17/raw-bin --output project/run-2026-10-17/derived/session.h5
python vertisea_session.py first.BIN second.BIN --output project/run-2026-10-17/derived/selected.h5 --start 10 --end 32 --cycles-csv project/run-2026-10-17/export/cycles.csv
```

Create `export` before a CSV export; archive parent directories are created
automatically. Import writes only temporary snapshots and derived output, never
the originals. Reimport creates/replaces an archive atomically, not a resume or
append into an existing session. Native datasets keep independent time axes for
the separate explorer/multirate plotting layer; the importer does not resample.

`vertisea_analysis.analyze_charging(current_rows, battery_rows, ...)` is reusable
and stdlib-only. Current rows contain `ts_ms`, `current_mA`, `counts`; battery rows
contain `ts_ms`, `voltage_V`. Optional `boot_id` and `segment_id` isolate streams.
It returns `rows`, `cycles`, `summary`, `parameters`, `algorithm_version` and
`cycle_method`. Missing calibration remains invalid, never guessed.

`detect_cycles(current_rows, method="auto", ...)` returns boundaries and flags.
`method="selected"` requires `cycle_start` and `cycle_end` in native boot seconds.
`analyze_charging` selects that method when boundaries are supplied, or accepts
`cycle_method` explicitly. A selection spanning multiple segments or boots yields
separate summaries rather than merging identically numbered timestamps.

```console
python vertisea_session.py captures --output session.h5
python vertisea_session.py first.BIN second.BIN --output session.h5 --start 10 --end 32 --cycles-csv cycles.csv
python -m unittest discover -s tests -p test_session.py -v
```

Install the numpy/h5py dependencies declared in environment.yml for HDF5 import.
Importing either new module does not load numpy or h5py. Cycle summary export is
also available as `export_cycles_csv(session_path, output)`.

## Schema 1.0

Each native table is a group with `row_count`, a `records_json` dataset and named
column datasets. Integers remain int64; numeric missing values become float NaN;
structured/string fields are JSON strings. `records_json` preserves every parser
field plus source provenance. Its Python JSON encoding permits NaN/Infinity.
Nonempty tables and all source byte datasets use gzip compression.

Columns are chunked, resizable one-dimensional datasets (`maxshape=(None,)`),
written in batches of at most 4096 rows. New columns backfill earlier missing rows;
integer columns promote to float for missing/fractional values, then to JSON if
later records require structured/string values. Promotion copies existing columns
in bounded batches. `records_json` remains the authoritative exact parser record.
These are additive schema 1.0 changes; existing group paths remain unchanged.

| Location | Contents |
| --- | --- |
| `/raw/sources/000000/bin_bytes` | Exact original BIN bytes, including damaged or unparsed bytes |
| `/raw/imu_raw`, `/raw/current_fast`, `/raw/current` | Native raw IMU values and current counts; parser-derived current is also retained |
| `/raw/battery_voltage`, `/raw/hall_edge`, `/raw/mag` | Native battery counts and voltage, accepted Hall edges and magnetometer |
| `/onboard/fixed_imu`, `/onboard/stab_imu` | Exact logged processed values; never offline replacements |
| `/onboard/current_stats`, `/onboard/displacement`, `/onboard/rpm` | Exact records when returned by the parser; empty tables otherwise |
| `/onboard/bme`, `/onboard/gps` | Native environmental and positioning records |
| `/meta/*_cal`, `/meta/session_meta`, `/meta/rtc_event` | Archived calibration, firmware metadata when present, native RTC anchors |
| `/meta/sources` | SHA-256, byte count, path, source index, segment, boot, timestamp range and time provenance |
| `/derived/charging` | Per-current-sample bracketed voltage, current, power, interval charge/energy, measured cumulative sums and validity flags |
| `/derived/cycles` | Selected or automatic boundaries, coverage, charge, peak, clipping and separate gross/baseline energy |
| `/health/sys_health` | Exact parsed health counters |
| `/health/stream_diagnostics` | Per-source native stream sample count, span, observed rate, largest positive gap and nonincreasing intervals |
| `/events/records` | Source boundaries, reboot/ambiguity flags and parser warnings |

Unknown future parser dictionary streams are retained under `/onboard`; new
calibration streams ending in `_cal` go under `/meta`. Original bytes always
remain authoritative. There is no invented firmware hash for legacy sources.

## Time and Calibration

Rows retain `source_index`, `source_row_index` within their parser stream,
`segment_id` and `boot_id`. These are not byte offsets or global packet indices.
Current block timestamps retain the parser's fractional millisecond reconstruction
from measured block span; individual sample timing jitter is unavailable. IMU,
Hall and battery retain their own native timestamps. No unified resampled CSV is
used as acquisition evidence.

A decreasing RTC anchor timestamp relative to the previous nonempty source's
maximum native timestamp starts a new boot. Continued rotations can share a
boot ID. Timestamp overlaps without an RTC regression are flagged, not silently
stitched. Every source is a separate conservative analysis segment, even on a
continuous boot; this intentionally omits boundary intervals and splits cycles at
rotation. An intra-file RTC regression or multiple current/battery calibration
records excludes that file from charging analysis while preserving all records.
Boot IDs are inference, not firmware-certified identifiers; timestamp wraps and
bad RTC anchors need human review.

Overlapping/regressing source times without an RTC reboot anchor also exclude that
source from charging analysis, preserving raw rows and an explicit warning rather
than adding ambiguous duplicate time coverage. Source metadata and boundary events
store `boundary_gap_s` when adjacent nonempty sources share an inferred boot; this
is a native range separation, not a certified acquisition outage. Stream diagnostics
report `(positive intervals)/(last-first span)` only for strictly increasing
timestamps. Largest gaps are measured, not compared to an invented nominal rate;
current block timing remains reconstructed. Diagnostics do not certify lost packets.

RTC calendars remain native local anchors. New session metadata supplies a UTC
offset which is applied when present; legacy logs without an offset have no
claimed UTC mapping. Clock accuracy is unverified. Missing anchors remain missing.
For a valid anchor and offset, UTC mapping is anchor UTC plus native time minus
anchor time. The offset is the recorded deployment setting, not automatic DST.

Current and voltage use only the parser's per-source archived calibration. There
is no global factor-of-two correction, propagation across files, or retroactive
interpretation of resistor changes. Counts remain available for a separately
documented, source-specific recalibration.

## Charging and Coverage

Voltage is interpolated only inside finite, unambiguous brackets separated by at
most 2.5 seconds. Exact finite voltage samples are usable directly. No endpoint
extrapolation, duplicate-time averaging, or interpolation across segments occurs.
Current intervals must be strictly increasing, at most 0.25 seconds, within one
segment, calibrated and unclipped at both ends. `adc_max` can be specified on a
current row; otherwise the public analysis default is 16383. Import uses the
source calibration's ADC ceiling when available.

Power is volts times milliamps in mW. Trapezoidal integrals yield mJ and mC.
Invalid interval energy and cumulative energy entries are NaN. Later valid
cumulative entries resume the measured-only sum; they do not fill missing energy.
`measured_energy_mJ` explicitly totals supported intervals only. An all-invalid
summary has NaN energy, not zero. `coverage_fraction` is valid energy duration
divided by observed within-segment duration, including positive gaps. It does not
measure lost time between files or an excluded source. Inspect source warnings
alongside coverage. Negative/nonmonotonic time intervals are flagged and excluded.

Import computes charging and automatic thresholds one file at a time. Per-sample
cumulative/measured energy and charge reset at each source. Cycle IDs are unique
within the archive, with `source_index` and `source_local_analysis` flags. Automatic
cycles do not seamlessly continue across five-minute rotations. Inspect split or
incomplete cycles before interpreting them as physical events.

Without selection the returned/stored session summary sums measured energies,
charges and valid/observed durations, and computes coverage from summed durations
(not the mean of source coverage fractions). For selected start/end, the summary
includes only fully contained sampled intervals from matching source-local cycles,
not whole-file energy. Its denominator is the requested duration once per matching
boot, even when that boot spans several sources. Empty selections still report the
requested duration and zero coverage with NaN energy. Repeated native clock ranges
on different boots are separate selections, not a UTC-aligned event. Source-local
cycle summaries still use their full requested duration individually; do not average
or sum their coverage fractions to recover the aggregate selection coverage.

Selected summaries include only fully contained sampled intervals, never partial
boundary extrapolation. Coverage uses requested duration, so partially covered
selections remain visibly incomplete. Gross energy is separate from signed
baseline-subtracted energy; `baseline_mA` defaults to zero and must be explicitly
set for background subtraction. Automatic detection's idle estimate does not
silently change the energy baseline.

Automatic onset/stop use lower-half current median plus 6/3 noise sigma, where
sigma is the larger of scaled MAD and RMS deviation of that lower half. Small
absolute threshold floors prevent zero-noise equality triggering. Defaults require
one second minimum duration and one second continuously quiet before closure.
Explicit threshold overrides are available. Gaps and end-of-data mark incomplete
cycles; they are not inferred quiet periods. Thresholds and noise estimates remain
in the cycle records. Inspect automatically detected events, especially when a
capture has little idle data; these defaults are not validated hardware thresholds.

This measures battery-side delivered electrical energy only when current and
voltage describe the same boundary. It is not raw TENG output or net chemical
storage. The 1 Hz battery stream cannot resolve fast voltage transients.

## Atomic Import and Limits

Import snapshots each source into temporary storage and parses that same snapshot,
so hashes and archived bytes match the decoder input. A sibling temporary HDF5
file is closed, fsynced and replaced into the destination only after successful
import. Failure leaves an existing destination untouched and cleans temporary
files. Atomic replacement is not a promise of filesystem power-loss durability.
The optional CSV is a separate, nontransactional export.

Only one writer is supported. One source's bytes, parser dictionaries and derived
rows are held at a time and released before parsing the next source. HDF5 column
encoding/promotion uses 4096-row batches; no day-wide sample/timestamp lists or
stream dictionaries are retained. The protocol parser still materializes a whole
file, so peak sample memory depends on the largest BIN, not total campaign samples.
Unrotated multi-hour files can still exhaust memory; retain five-minute rotations.
Path lists, SHA-256/source metadata, warnings and returned cycle summaries grow
with file/cycle count, not native sample count. Large automatic cycle counts are
therefore still a metadata-memory limit; this is not unlimited-memory streaming.

The importer preserves its public return keys and propagates `FileNotFoundError`,
selection/path `ValueError`, parser exceptions and filesystem/HDF5 errors.
Missing numpy/h5py raises `RuntimeError`. A failure removes temporary files and
keeps an existing output intact; duplicate content is a warning, not an exception.
The destination must not be an input BIN. Disk space must accommodate the source
snapshot plus the new archive alongside any existing destination. No crash resume,
live append, hardware gap recovery, or cross-source interpolation is promised.