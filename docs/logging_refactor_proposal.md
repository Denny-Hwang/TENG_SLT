# Unified logging proposal

Status: implemented 2026-10-16 in firmware/parser, session importer, live recorder
and GUI cycle analysis. See session_storage.md for executable interfaces.
Firmware compile, SD throughput and GUI-independent hardware acquisition still
require board validation. Sections below retain the architecture rationale.

## Current limitations

The board writes interleaved typed binary records to SD independently of the GUI.
Files normally use MMDD/MMDDHHMM.BIN and rotate about every five minutes.
The host parser exports one CSV per record type per BIN; directory processing
also produces a one-second overview. There is no session-level container.

IMU_RAW_ONLY selects raw OR onboard processed IMU recording, not both. Onboard
vertical displacement and running current statistics are live-only. GUI power,
interval current and tilt differences are derived in memory. A raw-only log
cannot reproduce the exact onboard processed values without matching the original
algorithm, state and calibration. GUI screenshots are not a logging substitute.

## Recommended ownership

Keep the embedded SD BIN as the GUI-independent primary acquisition record.
Add versioned records/options for raw plus processed IMU, onboard displacement,
current statistics and event markers. Do not simply turn off IMU_RAW_ONLY:
that switches modes rather than preserving both. Benchmark write throughput,
queue headroom and actual sample rates before deploying both modes together.

Use one headless host import/recording service and one shared calculation module
for both GUI and offline processing. The GUI reads data; it does not own storage.
PC-off operation still depends on SD. A running headless service can record
telemetry without a GUI but cannot obtain high-rate raw records absent from the
telemetry protocol. SD import supplies those records later.

## One session file

Recommend HDF5 for one research session with independently timed datasets:

| Group | Contents |
|---|---|
| /meta | Session/boot IDs, schema, firmware hash, flags, calibration, units, UTC mapping |
| /raw | Original BIN bytes and provenance; IMU, current/battery ADC, accepted Hall edges |
| /onboard | Exact logged processed attitude, displacement, statistics and RPM |
| /derived | Calibrated current, aligned voltage, power, energy, tilt difference; algorithm version |
| /health | SD counters, queue state, acquisition gaps, timing and saturation flags |
| /events | Rotation, reboot, recovery, cycle boundaries and user annotations |

Each dataset retains its native sample timestamps; do not flatten 800 Hz current
and 1 Hz battery into one falsely synchronous CSV. Keep a separate aligned view
for plotting and interval export. Preserve received onboard values separately
from offline recomputed results. One-second overview is a view, not raw data.

Use chunked append, compression, periodic flush and a single writer. Design crash
recovery and validate it; HDF5 is not automatically a transactional store. SQLite
WAL is an alternative when transaction recovery dominates bulk-array analysis.
Five-minute source segments can map into one session container; session IDs and
boot IDs prevent merging unrelated runs. CSV becomes an optional selected export.

## Migration checks

Keep old BIN decoding intact; add schema/versioned new records with round-trip
tests. Validate raw and onboard rates, reset/time-wrap behavior, power units,
calibration provenance, duplicate telemetry/SD records and incomplete files.
Compare GUI-on, headless and SD-only runs to confirm acquisition is independent
of display state. Retain actual time coverage rather than requested rates.