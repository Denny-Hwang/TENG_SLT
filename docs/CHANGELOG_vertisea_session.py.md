# Changelog: vertisea_session.py

## 2026-10-17 - Bounded rotation import and measured summary aggregation - [UNCONFIRMED]

Why: four/twelve-hour runs of five-minute rotations must not retain a campaign's
native dictionaries/current samples or construct day-wide JSON/column arrays.
User explicitly requested changes to the importer, tests and this documentation;
query/explorer/GUI and firmware are owned separately and remain untouched here.

- Parse, analyze and append one source at a time. Use resizable gzip numeric/JSON
  columns and at most 4096-row encoding/promotion batches, preserving schema 1.0
  paths and the public import_session signature/return keys.
- Keep originals unchanged and archive snapshot bytes per unique source. SHA-256
  aliases warn/skip before parsing and retain input indices and byte-dataset links
  in the manifest without adding samples, energy, or duplicate raw bytes.
- Preserve same-boot source segments and per-source calibration. Do not stitch
  automatic cycles, integrate/interpolate across files or promise continuity;
  cumulative sample sums reset per source. Exclude ambiguous unanchored overlaps.
- Aggregate summary durations/energy rather than averaging coverage fractions.
  Selected summaries use only contained intervals and one requested denominator
  per matching boot, not whole-source energy or per-file repeated denominators.
- Retain lexical recursive directory ordering with an explicit cross-day warning;
  do not add a broad RTC parse prepass, another protocol decoder, or mtime ordering.
- Add source boundary range gaps and per-native-stream rate/gap diagnostics;
  these are measured timestamp diagnostics, not asserted packet loss or nominal Hz.
- Document project/run/raw-bin, derived/archive and export workflow, exceptions,
  per-largest-file parser memory, small manifest/warning/cycle growth and no resume.

Initial append-helper validation passed all 17 existing tests. Switching to
deduplication exposed the old reboot fixture's identical bytes; made that capture
distinct and covered alias skipping separately. Expanded tests cover per-file
append/analysis bounds, column promotion, weighted coverage and selected scope.
Hardware and long real field runs still require user confirmation.

Final focused validation: 22 session tests passed in the configured Conda
environment via subprocess with `.venv/Library/bin` on PATH; no tests skipped.
The 15,000-row/three-source lifetime test proves parsed rows are released before
the next parser call, and twelve unique rotations plus a renamed duplicate verify
per-source analysis/appends and single storage of original bytes. Editor error
checks reported no errors in the importer or its tests.

## 2026-10-16 - Offline HDF5 sessions and reusable charging analysis - [UNCONFIRMED]

User approved implementation of the storage refactor and cycle analysis. Ownership
is limited to vertisea_session.py, vertisea_analysis.py, tests/test_session.py,
docs/session_storage.md, environment.yml and this changelog. Firmware/parser and
GUI/live acquisition are maintained independently; no changes were made there.

Why: separate native measurement evidence from synchronized derived quantities,
retain recoverable source bytes and avoid silently integrating energy through
missing voltage/current data or applying today's calibration to historical logs.

- Add lazy HDF5 import, gzip source bytes, SHA-256 manifest, native raw/onboard
  tables, calibration/time provenance, health/events and atomic temp+replace.
- Preserve future parser current_stats/displacement/session_meta streams without
  inventing missing onboard values. No live HDF5 claim is made.
- Infer boot changes from decreasing RTC native timestamps across ordered files;
  keep source segments even within one boot and flag uncertain overlaps. Exclude
  intra-source RTC regressions and multiple calibration records from derived
  charging rather than trusting the parser's first-calibration conversion.
- Add bracket-only voltage synchronization, short-current-interval trapezoids,
  NaN invalid energy, coverage, clipping and separate gross/baseline quantities.
- Add selected-cycle API and noise-based hysteresis/minimum-duration/quiet-end
  automatic detector; thresholds are heuristic and require measured-data review.
- Add recursive directory/file CLI, optional cycle CSV, numpy/h5py environment
  declarations, API/schema/limitation documentation and synthetic tests.

First numerical tests exposed zero-MAD quantized idle triggering. Corrected the
noise estimate to include lower-half RMS deviation and reran the same tests.
Validation at initial handoff: 12 analysis/source tests passed; five HDF5 tests
skipped explicitly because h5py is not installed in the selected environment.
Session syntax and optional-dependency lazy-import checks passed. Hardware and
field-record cycle boundaries are not confirmed by these synthetic tests.