# CHANGELOG — IDENTIFIED_ISSUES.md

Newest first.

---

## 2026-09-04 — Close firmware cleanup issues 3, 18, and 19 — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — tracker reconciled to the cleaned firmware; exact build still needs
normal bench/deployment confirmation.

- Issue 3: all packet writes now pass through checked `sdAppendRecord()`/buffered backend writes;
  Arduino `File.flush()` remains void and cannot expose a separate sync result.
- Issue 18: removed the unused `printAligned()` helper.
- Issue 19: retained the 1 Hz debug block because it now actively reports SD queue diagnostics;
  removed obsolete commented calibration output.
- Issue 39: corrected firmware comments; GUI relabeling from “duty” to “coverage” remains open.

---

## 2026-09-04 — Mark Issue 2 filename-safety fix implemented — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — tracker updated with the implemented code path; physical SD-card
verification is still pending.

Issue 2 now records that SD initialization precedes existence checks, same-minute collisions
fall back to a unique counter name, and exhausted counter names halt rather than overwrite.

---

## 2026-09-04 — Reconcile issue tracker with current firmware and GUI — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — documentation audit checked against the current source and
confirmed changelog history; no firmware behaviour changed. User review is still required.

**Why:** The index stopped at Issue 37 while later implementation work had resolved major
parts of Issue 34, retired the component behind Issues 14/15, and reintroduced the conditions
behind Issues 18/19. Several old descriptions also presented historical values as current.

**What changed:**

- Reclassified Issues 2 and 3 as partially resolved: invalid-RTC filename collisions are
  intended to be handled, but the `SD.exists()` scan runs before `SD.begin()` and same-minute
  reboot appends remain; SD failure detection exists, but only one IMU payload write is checked.
- Marked the incorrect Issue 9 RV8803 diagnosis as superseded by the verified Issue 28.
- Marked the retired MATLAB parser issue and retired supercap packet issue obsolete.
- Reopened Issues 18/19 because all debug output is commented and `printAligned()` again has
  no active caller.
- Folded Issue 26 into the broader open radio-verification Issue 36.
- Marked Issue 34's critical fixed-dt defect resolved while preserving residual 104 Hz work
  under U19.
- Updated Issue 33 to the current 3000 RPM threshold/counter/raw-edge implementation.
- Added Issue 38 for the raw-only BIN-loader UX and stale 450 RPM plot scale.
- Added Issue 39 for stale `integ_s`/“duty” semantics after measured-dt integration.
- Added Issue 40 because the parser expands all high-rate samples into in-memory dictionaries
  and performs conversion on the Tk main thread, which does not scale to multi-hour logs.

**Deliberately not changed:** Source code, packet layouts, hardware-dependent open issues,
and reference docs under `docs/` other than this required changelog.