# Project Instructions — VertiSea

> **Single source of truth for AI agent instructions.** Agent-specific loader files
> (`.roo/rules.md`, `.github/copilot-instructions.md`) point here. Update this file
> only; do not fork project rules into loader files.
>
> Documentation strategy: [`archived/AI_Agent_Project_Documentation_Guide.md`](archived/AI_Agent_Project_Documentation_Guide.md)
> (archived 2026-09-11 — it is a reusable, project-agnostic guide, not VertiSea content).
> `archived/` holds superseded material only; never put live documentation there, and never
> treat anything in it as current design intent.

## What this project is

VertiSea is an embedded data-acquisition and telemetry system for a wave-energy buoy
(Arctic TENG project, PNNL). Arduino firmware (`VertiSea/VertiSea.ino` — the sketch lives in
a folder of the same name) on a **SparkFun RedBoard Artemis Nano** reads two ISM330DHCX IMUs,
an MMC5983MA magnetometer, a BME280 environmental sensor, a u-blox GNSS module, an RV8803
RTC, a harvested-current sensor on A14, a 1S LiFePO4 battery divider on A15, and an optional
Melexis US1881 Hall-effect rotor-RPM sensor. It applies sensor
calibration and Madgwick AHRS filtering, packs data into typed binary packets, logs them
to an SD card over SPI, and streams a subset of packets over a pair of RFD900x 900 MHz
radio modems at 115200 baud. On the receiving end, a Python/Tkinter ground-station script
(`vertisea_plot_v7.py`) displays live GPS, BME280, status, harvested-current statistics,
battery voltage, RPM, and IMU data with rolling plots, and can also parse an SD `.BIN` log to CSV via its "Load BIN File"
button — this is now the **only** SD log parser. A MATLAB function (`calibrateMag.m`)
performs ellipsoid-fit magnetometer calibration.

> **Retired 2026-09-03:** `parse_vertisea_log_v4.m`, a second MATLAB implementation of the
> SD log parser, was deleted. It duplicated the Python parser's packet schema and had to be
> updated in lockstep with every protocol change, but was no longer used and therefore never
> exercised — a maintenance cost plus a correctness risk, since an unrun parser that looks
> maintained invites false confidence. Recoverable from git history at commit `9f5019f`.
> **Do not recreate it**; extend `vertisea_plot_v7.py` instead.

## Read these files before touching any code

| File | What it documents |
|------|-------------------|
| `docs/binary_protocol.md` | Every binary packet type: ID, byte layout, field units — the contract between firmware, parser, and ground station |
| `docs/firmware.md` | Arduino firmware: sensor init, calibration constants, LPF design, Madgwick filter usage, SD logging flow, telemetry flow |
| `docs/telemetry_ground_station.md` | Python ground station: packet parsing, GUI layout, serial connection, rolling plot design |
| `docs/data_pipeline.md` | Magnetometer calibration: file naming, CSV schemas, ellipsoid-fit algorithm. **Its MATLAB SD-parser sections are stale** — that parser was retired 2026-09-03 |
| `docs/calibration.md` | Sensor calibration procedure and where the resulting constants live |
| `docs/current_measurement_testing.md` | Harvested-current channel: measured instrument noise floor, aliasing analysis, and the recommended post-processing pipeline |
| `docs/adc_calibration.md` | Measured per-channel ADC gain for A14 (current) and A15 (battery): setup, raw numbers, fits, the adopted `VREF_A14`/`VREF_A15` constants, and limitations. Re-run if the Artemis Nano is replaced |

These are the single source of truth for design intent. The source code is the authority
for what currently runs. If the two contradict each other, flag the discrepancy rather
than silently following either one.

Two additional working documents are maintained by the human developer:
`IDENTIFIED_ISSUES.md` (known defects) and `POTENTIAL_UPGRADES.md` (proposed work).
Consult them before proposing new features so existing analysis is not duplicated.

## Session start — check for unresolved changelog entries

At the start of every session, search `docs/CHANGELOG_*.md` for entries marked
`[UNCONFIRMED]`. List any you find and ask the user to confirm, revert, or defer each one
before starting new work. This catches changes from a previous session that ended before
the user could verify them. If the user defers an entry, leave it `[UNCONFIRMED]`, note
that it was deferred, and continue. Surface it again at the next session start.

## Changelog files — read before modifying, write during the change

Source files have a companion `CHANGELOG_<name>.md` in `docs/` once they have been
modified under this strategy.

- **Before modifying any file**, check whether a changelog exists for it and read it.
  This prevents accidentally reverting decisions that were already tried and abandoned.
  Pay particular attention to entries marked `[REVERTED]` — these are recorded dead ends.
- **Naming:** use the source file name (e.g., `docs/CHANGELOG_VertiSea.ino.md`,
  `docs/CHANGELOG_vertisea_plot_v7.py.md`). If duplicate source file names exist in
  different folders, include a path-safe relative path using `__` for folder separators
  (e.g., `SampleData/04030825/plot_pitch_roll.py` becomes
  `docs/CHANGELOG_SampleData__04030825__plot_pitch_roll.py.md`).
- **Do not read every changelog upfront.** Only read the ones relevant to files you are
  about to change.
- **Write the changelog entry as part of the change itself**, marked `[UNCONFIRMED]`.
  Create the changelog file if it does not yet exist.
- **For broad mechanical changes** that do not alter behaviour, public interfaces, or
  design intent, add one summary entry to `docs/CHANGELOG_project.md` instead of noisy
  per-file entries.
- **After the user confirms the change works**, flip the marker to
  `[CONFIRMED YYYY-MM-DD]`. Do not rewrite the entry body.
- **If the user reports the change did not work**, mark the entry
  `[REVERTED YYYY-MM-DD]`, leave its body intact as a recorded dead end, and add a brief
  follow-up entry above it explaining what failed.

## Coding conventions

### Arduino / C++ (`VertiSea.ino`)
- Target board: **SparkFun RedBoard Artemis Nano** (Apollo3), **boards package 1.2.1**.
  Not a Teensy — Apollo3-specific behaviour matters (e.g. the SVL bootloader leaves
  residual bytes in the UART TX FIFO at boot).
- **Core 1.2.1 is a hard requirement, not a preference.** Core 2.x is mbed-OS based: it
  compiles cleanly and then panics on the first Hall edge, because mbed's `micros()` takes
  a mutex and `hallISR()` calls it (Issue 59). The sketch has a `#error` guard on
  `ARDUINO_ARCH_MBED`; do not remove or bypass it without fixing the ISR first. Every
  timing figure in `docs/` was measured on 1.2.1 and is not comparable to a 2.x build.
- C++11 or later; use `constexpr`, lambdas, and `struct` with designated initializers freely.
- All packet structs are `__attribute__((packed))`. Do not add padding or change field order
  without updating `docs/binary_protocol.md` AND `vertisea_plot_v7.py` simultaneously.
- Timing: IMU loop uses `micros()` for 104 Hz precision; all other loops use `millis()`.
- GPS uses I²C (u-blox UBX protocol); `Serial1` is telemetry-only at **115200** baud to the
  RFD900x. An Emlid M2 GNSS was originally planned for `Serial1` but was never connected.
- **GPS is for RTC time sync, not reliable positioning.** The antenna sits at water level on
  a rocking buoy, so fixes are expected to be intermittent; every GPS path tolerates having
  no fix. Running `GPS_ENABLE 0` is a legitimate configuration — but then the RTC coin cell
  is the only time source, so do not propose removing the RTC fallback paths. See the
  "GPS Role" section of `docs/firmware.md`.
- Telemetry is written to the `TELEM_SERIAL` macro, never to `Serial`/`Serial1` directly.
- SD logging uses `SD.begin(CS_SD)` (the SD 1.3.0 single-argument overload, which selects
  `SPI_HALF_SPEED` internally); CS pin is 4. Do not pass `SPI_FULL_SPEED` as a second
  argument: that overload is `(clock, csPin)`, not `(csPin, speed)`.
- **Seven** compile-time deployment flags gate major subsystems — read the "Deployment
  Flags" section of `docs/firmware.md` before changing them: `USB_DEBUG`, `USB_TELEM`,
  `TELEM_ENABLE`, `GPS_ENABLE` (**must** be `0` when no GPS is attached, or a failed I²C ACK
  hangs the bus and freezes both IMUs), `RPM_ENABLE`, `IMU_RAW_ONLY`, `SD_BUFFERED_WRITE`.
  Committed state (verified against source 2026-09-11): `USB_DEBUG 0`, `USB_TELEM 0`,
  **`TELEM_ENABLE 0`**, `GPS_ENABLE 0`, `RPM_ENABLE 1`, `IMU_RAW_ONLY 1`,
  `SD_BUFFERED_WRITE 1` — i.e. an **SD-only capture build that transmits nothing**.
  Do not assume field-radio defaults, and do not assume telemetry is on.
- Debug output must use the `DBG_PRINT` / `DBG_PRINTLN` macros, never `Serial.print()`
  directly, so field builds compile it out entirely.
- ADC is 14-bit (`analogReadResolution(14)`); `ADC_MAX = 16383`.
- Calibration constants (`fixedCal`, `stabCal`, `magCal`) are hard-coded in the sketch
  after offline calibration. Do not move them to EEPROM or SD without a design discussion.
- The magnetometer (`MMC5983MA`) is physically on the stabilized IMU board. The
  `isStabilizedIMU` flag in `collectIMUData_ISM()` controls whether mag data is read and
  whether a 9-DOF or 6-DOF Madgwick update is used.
- `heading` is set to `999.9f` for the fixed IMU (no magnetometer) and for the stabilized
  IMU when `isStabilizedIMU = false` (current operating mode). Do not treat `999.9` as a
  valid heading.
- Vertical displacement integration uses a leaky integrator (`vertVel *= 0.995`,
  `vertDisp *= 0.999`) to prevent unbounded drift. The leak constants require empirical
  tuning; do not remove them.

### Python (`vertisea_plot_v7.py`)
- Python 3.x; dependencies: `pyserial`, `matplotlib`, `tkinter` (stdlib).
- Packet parsing is framing-free: the buffer is scanned byte-by-byte for known type bytes.
  This is intentional — the radio link can drop bytes. Do not add a framing/sync byte
  without updating the protocol doc and the Arduino transmit side.
- `struct.unpack` format strings must exactly match the packed Arduino structs. Little-endian
  (`<`) always.
- Rolling buffers use `collections.deque(maxlen=100)`.
- The ground station parses six radio packet types: `0x03` BME, `0x04` GPS, `0x06`
  TELEM_IMU, `0x0B` STATUS, `0x0C` RPM, `0x0F` CURRENT_STATS, and `0x14` BATTERY_VOLTAGE.
  (`0x0A` SUPERCAP/CURRENT was retired 2026-09-03 and its radio handler removed.) SD health,
  window-average current, battery voltage, and rotor RPM are displayed in the System Status
  panel; the harvested-energy panel is driven entirely by `0x0F`.
- **The parser lives in `vertisea_protocol.py`, not in the GUI module** (split
  2026-09-11). That module is stdlib-only — no `tkinter`, no `matplotlib`, no `pyserial` —
  so the parser can be imported, tested and scripted headlessly, and so a packet change has
  exactly ONE place to be reflected on the read side. `vertisea_plot_v7.py` imports from
  it and must not redefine any packet constant or layout.
- `vertisea_protocol.py` also runs as a batch CLI:
  `python3 vertisea_protocol.py LOG00001.BIN [...]` writes the CSVs with no GUI.
- **Run `python3 tests/test_binary_protocol.py` after any packet change.** It builds `.BIN`
  byte streams from `docs/binary_protocol.md` and asserts the parser returns them unchanged.
  It pins the parser against the protocol doc; it does not compile the firmware, so it
  cannot catch a change made to `VertiSea.ino` alone.

### MATLAB
- **`parse_vertisea_log_v4.m` was retired 2026-09-03** — see the note at the top of this
  file. Parse SD logs with `vertisea_plot_v7.py` ("Load BIN File"); output CSVs keep the
  same `<baseName>_<type>.csv` naming (e.g. `09031435_imuRaw.csv`). Do not recreate it.
- `calibrateMag.m` expects a CSV with header `timestamp_ms,mx,my,mz` — the direct output
  of the parser's `mag` type. Run the parser first, then calibrate.
- Magnetometer calibration has already been performed for the current hardware. The
  resulting `magCal` constants are hard-coded in `VertiSea.ino`. Do not re-run calibration
  unless the magnetometer or its mounting is changed.

## Documentation maintenance rules

- **Reference files (`docs/*.md`) and `README.md` are confirmation-gated.** Do not update
  them until the user confirms the change works as expected. They describe current design
  intent and current behaviour, so they must reflect verified code only.
- **Changelogs are written immediately, under an `[UNCONFIRMED]` marker.** They are a
  historical record and must capture dead ends, so they cannot wait for confirmation
  without losing data across session boundaries. Flip the marker on confirmation; mark
  `[REVERTED]` if the change is rolled back.
- Changelog entries must capture *why* decisions were made, not just *what* changed.
- Commit messages should include a short "why" alongside the "what".
- Any change to a packet struct in `VertiSea.ino` requires simultaneous updates to
  `docs/binary_protocol.md` and `vertisea_plot_v7.py`.
- Update this file (`AGENTS.md`) when new component reference files are added or removed,
  or when conventions change.

## README.md — always update for user-facing changes

After a user confirms a feature works, update `README.md` for any change that affects
how someone *operates* the tool: new controls, changed workflows, new output files,
renamed commands, changed baud rates, new packet types.

## Ignored in Git (do not create or assume these exist)

Listed in the root `.gitignore` (re-synchronised 2026-09-11 — it previously listed only
three of these, so several entries documented here were not actually ignored):

- `.venv/`, `__pycache__/`, `*.pyc`, `*.pyo` — Python virtualenv and bytecode
- `*.bak` — Arduino IDE backup files (e.g., `VertiSea.bak`)
- `debug.txt` — ad-hoc debug capture
- `*.pdf` — generated from the `.md` sources
- `Thumbs.db`, `desktop.ini`, `.DS_Store` — OS metadata
- `SampleData/` — deployment logs and parsed CSVs (untracked 2026-08-18; ~124 MB)
- `*.BIN`, `*.bin` — raw SD captures must never be committed

## `SampleData/` — present on disk, no longer version-controlled

`SampleData/` holds sample deployment data (`04021311`, `04021543`, `04030825`) — raw
`*.BIN` SD logs and their parsed `*.csv` outputs. As of 2026-08-18 it is **git-ignored and
untracked**, because ~124 MB of repository weight was sample data rather than build input.

- These logs exist for **developing and testing the parsers against**, not as a scientific
  record. They are **regenerable** — running the firmware for a few minutes produces a new
  `.BIN`. Do not treat them as precious.
- A fresh capture is often *preferable* to these files, because a log recorded with the
  current firmware reflects the current packet set. These samples predate any packet type
  added after 2026-04-03.
- Older commits still contain the blobs (history was not rewritten), so a full clone still
  transfers them.
- New deployment logs go in a dated `SampleData/` subfolder and are ignored automatically.

## Tracked but treated as read-only reference data

These are **committed to the repository**. Do not regenerate, overwrite, or delete them:

- `Calibration/calibration.xlsx` — offline calibration workbook.
- `Calibration/accel_calibration_meas.txt` — raw six-position accel measurements.
- `VertiSea/MadgwickAHRS.{h,cpp}` — vendored AHRS, deliberately **inside the sketch
  folder**. A quoted `#include` searches the includer's own directory first, which is the
  only reason "takes precedence over a global install" is true; it also stops
  arduino-builder pulling in a library copy and producing duplicate symbols. Do not move
  these back out (Issue 58), and note they are a **local fork** — `sampleFreqDef` 512→104
  and `betaDef` 0.1→0.5 differ from upstream 1.2.0.
- `archived/Madgwick-upstream/**` — the upstream packaging metadata, provenance only.
- Image assets in `docs/` (`IMG_1770.jpeg`, `vertisea_system_diagram.png`, screenshots).
