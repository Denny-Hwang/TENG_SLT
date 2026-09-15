# CHANGELOG — Project-wide

Summary entries for broad, mechanical, or cross-cutting changes that do not warrant
per-source-file changelogs. Newest first.

---

## 2026-09-15 — Bench calibration reads: absolute mode, and battery range checks

A rebuilt divider and a fresh bench test (3.3 V battery side, 1.1 V current side, both
confirmed on a meter) exposed three places where the tooling could not tell a calibration
check from a deployment log.

`current_filter_test.py` now prints the **absolute level** in mA before baseline removal and
detects a constant-DC capture, which it used to subtract away to ~0 mA in silence;
`--no-baseline` is the explicit absolute mode.

`vertisea_protocol.py` now range-checks the battery channel: a **saturated** channel (the
supply reaching the ADC pad rather than the divider input, which pins the log at a constant
3.95 V that looks like a real number) and an **implausible** voltage for a 1S LiFePO4 cell,
which is what a rebuilt divider produces when the firmware still carries the old resistor
values — `div_ratio` is compiled in, not measured.

Reference numbers for this board: 1.100 V on A14 = 9137 counts = 110.0 mA; 3.300 V at the
divider input = 1.652 V at the pad = 13 686 counts = 3.300 V.

---

## 2026-09-14 — Session flags leave the source tree

Second `git pull` conflict on `VertiSea.ino` in a week, same cause: deployment flags edited
in place. They are now `#ifndef` defaults overridden by a git-ignored
`VertiSea/config_local.h` (template committed). Documented in README §5, AGENTS.md and
`docs/firmware.md`.

---

## 2026-09-12 — Bench test: A14 zero is wiring, battery channel correct, SD no longer halts

Bench supplies on both ADC channels (`09111727.BIN`): the battery channel read **3.28 V for
3.30 V** through the divider (0.7 %); the current channel read a floating input, then a hard
zero — it never saw the 1.2 V. Pad identities verified against the core 1.2.1 variant table
(A14 = pad 35, A15 = pad 32); the channel is documented tracking a DMM to 1.5 % on this exact
path. The decisive next step is a meter on the pad. Issue 66.

Same run, harvester stopped: `hall_rejected = 0` over 48 s, against 94 691 with it running.
That is the control half of Issue 65 and it points at the harvester. IMU rate 98.4 Hz on core
1.2.1.

A missing SD card no longer halts `setup()` — it degrades to the existing 4 Hz / telemetry-
only mode, which is what a card-less live-IMU session needs. Issue 67; Issue 47 decided for SD.

Confirmed on hardware: `USB_DEBUG 0` + `USB_TELEM 1` + `TELEM_ENABLE 1` gives live telemetry
on the buoy's own USB port. The GUI's buoy-port dialog now leads with that recipe.

---

## 2026-09-11 (later) — Health diagnostics told the truth about the wrong thing

Two findings from the first real `_sysHealth.csv`, and a fix to the diagnostic that reported
them.

**The Hall line is carrying 36x the mechanically possible edge rate** — 94 691 edges rejected,
1 211.8/s, against 33.3/s for one magnet at 2000 RPM. Issue 54's hypothesis, now measured.
This is the "LED is affected by the measurement signal" symptom that started this work. It is
a wiring fault: shield the Hall line, route it away from the harvester output and its return,
add an RC at the sensor pin. Issue 65.

**A backwards `micros()` step was being reported as a 71-minute loop stall.** `UINT32_MAX`
microseconds in `loop_max_us` is a timer fault, not a measurement, and the parser's health
post-pass — added so an operator would not have to interpret raw counters — took it at face
value and blamed the I²C bus on a board that was running normally. A diagnostic that
fabricates a fault is worse than none, because it gets acted on. Firmware now rejects
implausible deltas at the source and flags them; the parser excludes them from the maxima and
reports them for what they are, by value as well as by flag so older logs read correctly.
Issue 64.

---

## 2026-09-11 — Add `environment.yml`; teach the `.bat` launchers the conda layout — `[UNCONFIRMED]`

**Why:** the host-side Python setup was three words of prose (`pip install pyserial
matplotlib`) with no pinned interpreter and no record of what the code actually needs.

`environment.yml` (conda-forge, `name: TENG_SLT` — matching the repository, so
`conda env list` lines up with the checkout) pins Python 3.11 and lists the real
dependency set, which is short on purpose: `pyserial`, `matplotlib-base`, `tk`, plus
`pytest`/`pyflakes` as optional conveniences. Two choices worth stating:

- **`matplotlib-base`, not `matplotlib`.** The full package pulls in PyQt (~100 MB) that
  nothing here uses — every plot goes through `matplotlib.backends.backend_tkagg`.
- **`tk` listed explicitly.** `tkinter` ships with CPython, but under conda the Tk runtime
  it binds to is a separate package; without it `import tkinter` fails at run time even
  though the module exists. That is a confusing failure to debug from a bare env file.

The file also records that `vertisea_protocol.py` and the tests are stdlib-only *by design*,
so a `.BIN` converts on a machine with no packages at all. That property is easy to lose
accidentally and worth writing down where someone adding a dependency will see it.

**`.bat` launcher fix.** Both launchers checked only `.venv\Scripts\python.exe`, the
venv/virtualenv layout. Conda puts `python.exe` at the environment *root*, so a conda
environment created in the project folder was silently ignored and the launcher fell
through to whatever Python was on `PATH` — which on a machine with several Pythons is a
quiet way to run the tools against the wrong interpreter. Both layouts are now checked, in
order, before the `PATH` fallback.

README §4 documents both routes and the one non-obvious consequence: a *named* conda
environment works fine from an activated prompt, but only an environment created **at
`.\.venv`** makes double-clicking the `.bat` work.

---

## 2026-09-11 — Repository review: fix broken links, correct the `gyro_bias` unit error, prune a captured log — `[UNCONFIRMED]`

**Why:** a full-repository review. Three classes of problem were mechanical enough to fix
directly; the behavioural findings were filed as Issues 41–51 instead of being changed
blind, because they need hardware to verify.

**Broken links (all docs).** The sketch lives at `VertiSea/VertiSea.ino` (Arduino requires the
folder name to match), but every document linked it as `VertiSea.ino` or `../VertiSea.ino` —
roughly 100 dead links across `README.md`, `AGENTS.md`, `IDENTIFIED_ISSUES.md`,
`POTENTIAL_UPGRADES.md` and `docs/*.md`. Repointed. Also repointed the five surviving links to
`parse_vertisea_log_v4.m`, deleted 2026-09-03, at the Python parser; two of them were inside
live calibration procedures, so a reader following `docs/calibration.md` was being sent to a
file that does not exist.

**`gyro_bias` unit error (Issue 42).** `IMUCal.gyro_bias[]` is subtracted from the SparkFun
driver's mdps value *before* the `* 0.001f` conversion, so it is in millidegrees/s. It was
documented as °/s in the struct comment, `docs/firmware.md`, `docs/binary_protocol.md`,
`docs/calibration.md` and `README.md`. `docs/calibration.md` had additionally grown a note
justifying the resulting impossible number ("several hundred °/s ... is normal for this
sensor"). This was not cosmetic: the calibration procedure told the operator not to multiply
by 1000, and the 2026-04-02 recalibration consequently applied a −0.065 °/s residual as
−0.06 mdps instead of −65 mdps, leaving the stabilized IMU's Y bias uncorrected. Corrected
every occurrence, rewrote the procedure with the right conversion, and flagged the 2026-04-02
history entry as wrong by 1000×. **The constant itself was not changed** — it needs a fresh
stationary log.

**Stale "current state" claims.** `docs/firmware.md` asserted `USB_TELEM 1` / `TELEM_ENABLE 1`
"read from source 2026-09-08"; the source has both `0`. `AGENTS.md` said the same, said "four
compile-time deployment flags" where there are seven, still listed `0x0A SUPERCAP` among the
radio packet types the ground station parses (its handler was removed), and described a
`.gitignore` containing seven entries the actual file did not have. All corrected against the
source, and `.gitignore` rewritten to match what `AGENTS.md` documents — including
`SampleData/`, which was documented as ignored since 2026-08-18 but was not in the file, and
`*.BIN`.

**Deleted:** `tools/adc_timer_dma_experiment/500Hz_stalls_swtrigger0_120s.txt` (54 kB) — a raw
serial capture from the rejected ADC/DMA experiment. Every number in it, and the corrected
`fifo_overruns` interpretation, is already recorded in
`docs/CHANGELOG_tools__adc_timer_dma_experiment__adc_timer_dma_experiment.ino.md`, so the
capture is redundant with its own analysis. Recoverable from git history at `e7827ec`.

**Moved:** `Ground_RFD900x.png` → `docs/Ground_RFD900x.png`. It was an unreferenced file in the
repository root, but it is the only record of the RFD900x configuration as flashed — which
matters while Issue 36 (radio transport unverified) is open. Now referenced from the README
hardware section with the settings transcribed inline.

**Filed, not fixed — Issues 41–51.** Notably Issue 41: `collectIMUData_ISM()` negates accel X
and gyro Y, presenting the two sensors to Madgwick in frames that differ by a 180° yaw
rotation, each of them a left-handed reflection rather than a rotation. That needs the
mechanical drawing and a rotation test to resolve correctly, so no code was touched.

---

## 2026-09-09 — Add Windows launchers for both Python desktop tools — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — launcher dispatch and the current-filter self-test were checked
locally, but double-click operation should still be confirmed by the user on their desktop.

Added `vertisea_plot_v7.bat` and `current_filter_test.bat` beside their corresponding Python
scripts. Both launchers change to their own directory so shortcuts and double-clicks do not
depend on the caller's working directory, prefer the repository's `.venv`, and fall back to
the Windows `py -3` launcher or `python` when the virtual environment is absent or its Python
executable cannot start (for example, a stale `uv` trampoline). When a stale environment still
contains compatible packages, its `site-packages` directory is preserved on the fallback
interpreter's search path; the ground-station launcher also verifies `pyserial`, Matplotlib, and
Tkinter before dispatch. Arguments are forwarded unchanged, allowing uses such as
`current_filter_test.bat --selftest`, and failures remain visible with an exit code instead of
disappearing when a console window closes.

**Why:** The two Tkinter applications previously required opening a terminal and entering the
Python command manually. The BAT files provide direct Windows entry points without changing
either application's behavior or introducing a second dependency configuration.

---

## 2026-09-08 — Exclude local VS Code/Arduino settings — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — the user explicitly requested `.vscode/` remain excluded
from this commit.

Added `.vscode/` to `.gitignore` because its Arduino task files contain a user-specific CLI path
and COM port. The portable benchmark sketches and their changelogs remain tracked.

---

## 2026-09-03 — Retired the MATLAB SD-log parser `parse_vertisea_log_v4.m` [CONFIRMED 2026-09-03]

**What:** deleted `parse_vertisea_log_v4.m` (327 lines, 17 KB). Recoverable from git history
— final state committed at **`9f5019f`**, removal at **`ea30553`**.
`Calibration/calibrateMag.m` is a different tool and is **unaffected**.

**Why:** the user confirmed they had not run it in a long time and do not need it, including
for old logs. It duplicated the Python parser's packet schema, and `AGENTS.md` required both
to be updated in lockstep with every protocol change. That cost was paid for code never
exercised — and an unrun parser that *looks* maintained invites false confidence. Today alone
it absorbed two edits (0x0A retirement, 0x12 int32) and produced two changelog entries that
could never be marked confirmed.

**Two commits, deliberately.** `git rm` initially **refused** because the file had
uncommitted modifications — deleting then would have lost those edits from history entirely
instead of preserving them. So `9f5019f` commits the final state and `ea30553` removes it,
making the retirement reversible.

**`AGENTS.md` updated**, since it is the rule source agents read:

- Python is now described as the **only** SD log parser, with a retirement note and an
  explicit **"do not recreate it"**.
- The packet-change lockstep rule went from three files to two, in both places it appeared.
- The MATLAB section points at `vertisea_plot_v7.py` ("Load BIN File"); CSV naming unchanged.
- `docs/data_pipeline.md` flagged in the reference table as having **stale MATLAB SD-parser
  sections**. Not rewritten — dead documentation to prune in a dedicated docs pass; its
  magnetometer-calibration content is still correct and in use.

**`CHANGELOG_parse_vertisea_log_v4.m.md` is retained** (moved to `archived/` 2026-09-11). Its eight `[UNCONFIRMED]`
entries stay that way permanently and correctly — they describe changes written but never
executed. Deleting the record would erase the fact that the code was modified blind.

**Correction this triggered.** I had claimed the MATLAB parser produced the `09031435` CSVs,
inferring it from the `timestamp_ms` header. Wrong: the Python writer also renames
`ts_ms` → `timestamp_ms` on output, so that header has **no** discriminating power. The real
signature is float formatting — MATLAB uses `%.3f`/`%.6f`, Python writes the full repr, and
the files contain `1325.2929292929293` and `0.5471639633178711`. Python wrote them, as the
user said. Lesson: I tested a hypothesis against the first plausible signal without first
asking whether that signal could distinguish the alternatives.

---

## 2026-08-18 — Reclassified `SampleData/` as regenerable test data — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — current `AGENTS.md` and `.gitignore` consistently
treat these files as regenerable, ignored parser-test data.

**What changed:**
Rewrote the `SampleData/` guidance in `AGENTS.md`, `README.md`, and `.gitignore`. The
earlier entry below described it as "irreplaceable field data" that must "never be deleted"
and needed shared-drive backup. That is wrong, and the guidance now says the opposite:
these are **regenerable** sample logs kept for developing and testing the parsers, and a
fresh capture is often preferable because it reflects the current packet set.

**Why:**
Corrected by the developer. The `.BIN` files were retained to have something to run the
parsers against — not as a scientific record. Regenerating one takes a few minutes of
firmware runtime.

This matters more than a tone change. The previous wording would have discouraged the
incoming developer from doing exactly the right thing: capturing a **new** log. The
committed samples predate 2026-04-03, so they lack any packet type added since. Anyone
extending the protocol — the anticipated next step is sampling dynamic current at the IMU
rate — needs a fresh capture to exercise both parsers, and the docs now say so explicitly
and name that use case.

The README and `AGENTS.md` also now note that purging the blobs from history with
`git filter-repo` is a *reasonable* option if clone size becomes annoying, rather than
framing it as a risky operation guarding precious data.

**Dead end (mine):**
I inferred "irreplaceable" from the fact that the data was committed, sizeable, and
described in the docs as "reference examples", then propagated that inference into three
files and a commit message. The signal was ambiguous — committed bulk data *often* is
precious — but I asserted it rather than asking. The correction cost more edits than the
question would have. Lesson: value judgements about data ("precious", "regenerable",
"authoritative") are project knowledge, not code knowledge, and are not reliably
inferable from the repository alone.

**Side effects:** `AGENTS.md`, `README.md`, `.gitignore`. The `git rm --cached` untracking
itself remains correct and unchanged — only the rationale and the handling guidance moved.
Commit `788e291`'s message retains the older framing; superseded by this entry.

---

## 2026-08-18 — Untracked `SampleData/` and documented GPS-as-time-sync design intent — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — `SampleData/` remains ignored/untracked and the
GPS/RTC design is reflected in current firmware and project instructions.

### Part 1 — `SampleData/` git-ignored and untracked

**What changed:**
Added `SampleData/` to `.gitignore` and ran `git rm -r --cached SampleData` to remove the
25 files from the index. **`--cached` was used deliberately** so every file remains on
local disk; only Git's tracking was removed. Verified afterwards that all files are still
present.

**Why:**
~124 MB of the repository was reference deployment data rather than build input, making
clones slow for anyone picking the project up. Ignoring it stops future growth.

**Important caveat, recorded in `README.md` and `.gitignore`:**
This does **not** shrink existing history. The blobs remain in earlier commits, so a full
clone still transfers them. Eliminating them would need `git filter-repo` plus a
force-push, which requires coordinating with collaborators — deliberately not attempted.

**Risk this introduces, and the mitigation:**
`SampleData/` is irreplaceable field data that was, until now, backed up by virtue of being
in version control. Ignoring it removes that safety net. Both `AGENTS.md` and `README.md`
now state prominently that the directory must never be deleted despite being ignored, and
recommend archiving to a shared drive. This was the main argument *against* the change; it
is mitigated by documentation rather than by keeping 124 MB in Git.

### Part 2 — GPS role documented as time-sync, not positioning

**What changed:**
Added a "GPS Role — Time Sync, Not Positioning" section to `docs/firmware.md`, a summary
bullet in `AGENTS.md`, and two rows in the README's "Things That Are Easy to Forget" table.

**Why:**
Design intent supplied by the developer: the GPS antenna sits at water level on a rocking
buoy, so reception is inherently unreliable. GPS was only ever intended to set the RTC to
the correct wall-clock time, not to provide continuous position. This explains several
things that otherwise look like unfinished work or bugs:

- `GPS_ENABLE 0` in the committed firmware is a legitimate configuration, not a temporary
  debug state.
- The no-fix sentinel packets (Issue 7) and the RTC fallback path are load-bearing
  features, not leftovers.
- `float32` lat/lon storage (~11 m resolution) is an accepted trade-off.

Without this recorded, a new contributor would plausibly "fix" the intermittent GPS by
tightening the sync loop or removing the RTC fallback — both wrong.

**Consequence flagged for the operator:** with `GPS_ENABLE 0` there is no mechanism to
correct RTC drift, so the coin cell becomes the only time source. If it dies, absolute time
for that deployment is lost (logging continues via `LOGnnnnn.BIN` filenames). The docs now
recommend checking the cell pre-deployment and re-syncing on the bench with `GPS_ENABLE 1`.

**Side effects:** `.gitignore`, `AGENTS.md`, `README.md`, `docs/firmware.md`, and the Git
index. No source-code or behavioural change in this entry (the firmware fix is recorded
separately in `docs/CHANGELOG_VertiSea.ino.md`). No commit was made.

---

## 2026-08-18 — Corrected Git ignore/tracked claims in AGENTS.md and README — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — audited against the current ignore/tracked state.

**What changed:**
Rewrote the "Ignored in Git" section of `AGENTS.md` and the "Reference example files"
section of `README.md` to distinguish genuinely-ignored paths from tracked reference data.

**Why:**
Verified against `.gitignore` and `git ls-files` rather than trusting prose. The old
`.roo/rules.md` listed `SampleData/` and `Calibration/calibration.xlsx` under "Ignored in
Git", and my own earlier `AGENTS.md` rewrite repeated that claim while asserting it
"matches `.gitignore`". It does not: `.gitignore` contains only `*.bak`, `debug.txt`,
`*.pdf`, `__pycache__/`, `*.pyc`, `*.pyo`, and OS metadata. `SampleData/**` and
`calibration.xlsx` are **tracked and committed**. `.venv/` is ignored, but by its own
self-generated `.venv/.gitignore`, not the root file.

This matters for handoff: an agent told these paths are ignored could `git rm` ~124 MB of
irreplaceable deployment data believing it to be local scratch.

**Also recorded:** the ~124 MB repository size and its cause, so the next contributor
knows why cloning is slow and thinks twice before committing new `.BIN` logs.

**Dead ends:**
- Trusted the inherited "Ignored in Git" list on the first `AGENTS.md` pass instead of
  checking `.gitignore`. Caught only when a later question prompted running
  `git check-ignore`. The lesson generalises: ignore-status claims are cheap to verify and
  should never be copied forward on faith.

**Side effects:** `AGENTS.md`, `README.md`. No code, no Git operations performed.

---

## 2026-08-18 — Documentation staleness audit against source (pre-handoff) — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — retained corrections remain present; later protocol
evolution has its own newer documentation/changelog entries.

**What changed:**
Audited all reference docs, `README.md`, `AGENTS.md`, `IDENTIFIED_ISSUES.md`, and
`POTENTIAL_UPGRADES.md` against `VertiSea.ino`, `vertisea_plot_v7.py`, and
`parse_vertisea_log_v4.m`, then corrected every divergence found. **No source code was
modified** — only documentation. The three source files were found to be mutually
consistent on the packet protocol; all errors were in the prose.

**Why:**
Preparing the project for handoff. Documentation errors that merely misdescribe working
code are survivable; the ones fixed here would actively mislead a new contributor into
breaking a working system or losing data.

**Corrections, highest-consequence first:**

1. **`USB_DEBUG` telemetry routing was documented backwards** (`firmware.md`,
   `telemetry_ground_station.md`). Docs said `USB_DEBUG=1` routes telemetry to USB; the
   code routes it to `Serial1` precisely so binary packets cannot corrupt debug text.
2. **Discovered a latent firmware trap and documented it** (not fixed in code): with
   `USB_DEBUG=1` *and* `USB_TELEM=1`, `TELEM_SERIAL` resolves to `Serial1` but the
   `#if !USB_TELEM` guard skips `Serial1.begin()`, so **all telemetry is silently
   discarded**. Flagged in `firmware.md`, `telemetry_ground_station.md`, `calibration.md`,
   and as a ⚠️ in the README flag table. Left as a doc warning rather than a code change
   because fixing the guard is a behavioural change needing hardware verification.
3. **MATLAB parser output directory was wrong** (`data_pipeline.md`, `README.md`). Docs
   claimed CSVs land beside the `.BIN`; `fopen` uses a bare filename, so they land in the
   MATLAB working directory. The Python parser *does* write beside the `.BIN` — the two
   tools differ, now documented, plus a README "easy to forget" row.
4. **`calibrateMag` input requirement was contradictory.** `data_pipeline.md` said the
   input is calibrated LPF-filtered values; `calibrateMag.m`'s own header requires raw
   counts, and `calibration.md` §2.6 correctly describes zeroing `magCal` first. Corrected
   to raw counts and cross-referenced.
5. **`AGENTS.md` inherited wrong hardware facts** from the old `.roo/rules.md`: "Teensy
   4.1" (actually SparkFun RedBoard Artemis Nano / Apollo3) and "57600 baud" (actually
   115200). Also added the four deployment flags with their committed values, the
   `TELEM_SERIAL`/`DBG_PRINT` conventions, and corrected the claim that `TYPE_SUPERCAP`
   is not displayed by the ground station — it is, along with STATUS and RPM.
6. **`TELEMETRY_RATE_HZ` under `USB_TELEM=1` documented as 30 Hz; code says 10 Hz.**
   Fixed in three files, including the derived rolling-window durations.
7. **`TYPE_RTC_EVENT` hour documented as UTC** in `binary_protocol.md`; firmware writes
   **local** time (Issue 22's fix). A parser author trusting the doc would have applied a
   timezone offset twice.
8. **`IDENTIFIED_ISSUES.md` index contradicted its own detail sections** for Issues 25,
   26, and 27 — index said Resolved/Medium, details said Open/Critical. Reconciled to the
   index (the status of record), preserving each analysis body and adding resolution notes.
   Issue 27's resolution is load-bearing: it explains why `GPS_ENABLE` must stay `0`.
9. **LPF alpha values were wrong** in `firmware.md` (accel ~0.77, gyro ~0.92); recomputed
   from `alpha = dt/(rc+dt)` at 104 Hz gives ~0.55 and ~0.71.
10. Smaller fixes: `collectIMUData_ISM()` step 6 described mag reads as gated on
    `accelValid` (only the Madgwick update is); the `LOGnnnnn.BIN` counter-based filename
    fallback was undocumented in both `firmware.md` and the README; `POTENTIAL_UPGRADES.md`
    U10 marked Planned though the skip-unknown-packet logic is implemented in both
    parsers; stale `05300428` sample filenames replaced with the real `04030825`
    throughout; stale `VertiSea.ino:NNN` line-number anchors in `calibration.md` removed
    (they pointed into unrelated code); `Last reviewed` dates refreshed.

**Also noted, not changed:** `TYPE_STATUS` (`0x0B`) is absent from both parsers' payload
lookup tables, so a `.BIN` containing one would halt parsing. Harmless today because the
packet is radio-only, but recorded in `data_pipeline.md` as a latent trap.

**Dead ends:**
- Considered "fixing" the `USB_DEBUG`/`USB_TELEM` guard in `VertiSea.ino` directly.
  Rejected for this pass: reference docs are confirmation-gated and a firmware behaviour
  change cannot be verified without the hardware. Documented as a known trap instead.
- Initially assumed the `firmware.md` claim that `USB_DEBUG=1` sends telemetry to USB was
  correct and the code had drifted. Re-reading the `TELEM_SERIAL` block and its comment
  showed the routing is deliberate — the doc was simply wrong.

**Side effects:**
- Files touched: `AGENTS.md`, `README.md`, `docs/binary_protocol.md`, `docs/firmware.md`,
  `docs/telemetry_ground_station.md`, `docs/data_pipeline.md`, `docs/calibration.md`,
  `IDENTIFIED_ISSUES.md`, `POTENTIAL_UPGRADES.md`.
- No source, packet layout, or runtime behaviour changed.
- Two items remain for the maintainer: the `USB_DEBUG`+`USB_TELEM` guard, and Issue 26
  (confirm the RFD900's stored baud rate is 115200).

---

## 2026-08-18 — Migrated documentation strategy to `AGENTS.md` (AI Agent guide) — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — `AGENTS.md` remains the active single source of agent
instructions and the changelog workflow is in active use.

**What changed:**
Replaced the old dual-maintenance instruction scheme (full instructions duplicated in
`.roo/rules.md` and `.github/copilot-instructions.md`) with a single agent-agnostic
[`AGENTS.md`](../AGENTS.md) in the repository root. Both tool-specific files are now
one-line loaders pointing at it. Added the new-strategy sections that the old rules file
lacked: a session-start scan for `[UNCONFIRMED]` changelog entries, changelog status
markers (`[UNCONFIRMED]` / `[CONFIRMED]` / `[REVERTED]`), the write-changelog-during-the-
change rule (as distinct from confirmation-gated reference files and `README.md`),
path-safe `__` changelog naming for duplicate source file names, and this
`docs/CHANGELOG_project.md` escape hatch for broad mechanical changes. Deleted the
superseded `Github_Copilot_Project_Documentation_Guide.md` and updated the README appendix
documentation-structure table.

**Why:**
The old strategy required keeping two byte-identical instruction files in sync by hand,
which drifts — and it had already drifted: the "Ignored in Git" sections of
`.roo/rules.md` and `.github/copilot-instructions.md` listed different files, and both
referenced a `05300428` sample dataset that no longer exists in `SampleData/` (the actual
datasets are `04021311`, `04021543`, `04030825`). Consolidating on a root `AGENTS.md`
removes the sync burden and keeps instructions outside any single tool's config folder,
so adding an agent means adding a one-line loader rather than another full copy.

The changelog status-marker mechanism was the other motivation. Under the old rules,
changelog entries were written only *after* user confirmation, so any session that ended
before verification lost the record of what was tried and why — exactly the dead-end
information the strategy exists to preserve.

**Corrections folded in while migrating** (stale content in the old rules files, fixed
rather than carried forward):
- Dropped the self-contradictory line "Serial1 is shared between GPS (input, I²C
  actually) and RFD900x telemetry (output)"; GPS is on I²C, so `Serial1` is telemetry-only.
- Corrected the sample CSV example from `05300428_imuFixed.csv` to `04030825_imuFixed.csv`.
- Unified the two divergent "Ignored in Git" lists into one that matches `.gitignore`,
  including the previously omitted `.venv/`.
- Added `docs/calibration.md` to the read-first table — it existed but was never listed.
- Added pointers to `IDENTIFIED_ISSUES.md` and `POTENTIAL_UPGRADES.md` so agents consult
  existing analysis before proposing new work.

**Dead ends:**
- Considered symlinking `.roo/rules.md` to `AGENTS.md` for a literal single source of
  truth — rejected because this is a Windows/OneDrive working copy where symlinks do not
  reliably survive checkout or sync.
- Considered mirroring the full `AGENTS.md` contents into
  `.github/copilot-instructions.md` (the guide notes plain Copilot Chat may not follow a
  pointer). Rejected because it reintroduces the exact duplication this migration removes;
  a comment in the loader explains how to attach `AGENTS.md` to chat context instead.

**Side effects:**
- `Github_Copilot_Project_Documentation_Guide.md` deleted; the surviving guide is
  `AI_Agent_Project_Documentation_Guide.md`.
- `README.md` §11 appendix table now lists `AGENTS.md`, `docs/calibration.md`, and the
  `docs/CHANGELOG_*.md` convention; the "Adding a new packet type" step 7 now points at
  `AGENTS.md` instead of `.roo/rules.md`.
- No source code, packet layout, or behaviour changed.
- No `docs/CHANGELOG_*.md` files existed before this one, so there are no legacy entries
  needing retroactive status markers.

---
