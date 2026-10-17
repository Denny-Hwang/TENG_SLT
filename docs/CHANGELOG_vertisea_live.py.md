# Changelog: vertisea_live.py

## 2026-10-16 - Shared live telemetry HDF5 recorder - [UNCONFIRMED]

User approved unified storage and cycle analysis. Add a shared headless/GUI
recorder so pausing display never discards received evidence. Firmware, SD
protocol parser, session importer, analysis and environment are unchanged.

- `TelemetryParser.feed(chunk, host_receive_utc_ns=None, chunk_index=0)` scans
  seven known radio schemas framelessly and retains split packet tails. Records
  preserve raw fields, converted engineering values, source markers, byte
  offsets, first-byte and completion receive UTC nanoseconds.
- `TimestampClock.seconds(ts10)` maps ticks to the nearest wrap around a high
  water mark; small out-of-order packets do not fabricate 655.36-second jumps.
- `current_interval_stats(previous, current, battery_voltage, battery_time)`
  shares accepted-time interval current/RMS and fresh-voltage power with GUI.
  First packet, reset, stale voltage and timestamp gap flags remain explicit.
- `LiveRecorder(output, port=None)` uses exclusive-create HDF5 and lazy h5py.
  `feed`, `event`, `close` and context-manager APIs append gzip datasets under
  raw/onboard/derived/meta/health/events, flush per chunk and close idempotently.
  `raw/bytes` preserves every received byte once; `raw/chunks/records_json`
  records exact chunk boundaries and UTC receipt. Parsed tables and derived
  records use incrementally appended `records_json`, like offline session JSON.
- CLI: `python vertisea_live.py --port COM7 --output sessions/live.h5`
  with optional `--duration 60`. Ctrl-C closes writer and serial connection.
  RTS/DTR are false before open; driver rejection does not silently open unsafe.

Limitations: live cannot supply high-rate raw IMU/current or SD calibration;
quantitative cycle analysis requires SD BIN. No device UTC anchors or reboot
detection exist on the link. Gaps >= half-wrap (327.68 s) are ambiguous. The
frameless protocol has no checksum or sequence number; raw bytes enable later
inspection but do not establish complete or error-free telemetry. Fresh-voltage
power is an interval estimate, not instantaneous waveform power. Single owner,
no concurrent threads/writers; flushing does not make HDF5 crash-transactional.

Validation: synthetic/tempfile tests cover schemas, one-byte/split chunks,
rollover/out-of-order, cumulative resets/gaps/freshness/RMS, exact raw bytes,
gzip, exclusive-create, lazy dependencies, mocked CLI duration/Ctrl-C and line
states. GUI tests cover automatic recording, pause, errors, link loss and export.
No physical serial ports or field records were used.