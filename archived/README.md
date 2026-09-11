# `archived/`

Files kept for the record but **not part of the VertiSea system**. Nothing here is read by
the firmware, the ground station, or any build step, and nothing here should be treated as
current design intent. Do not add live documentation to this folder.

| File | Why it is here |
|------|----------------|
| `AI_Agent_Project_Documentation_Guide.md` | A general-purpose methodology document describing the AI-agent documentation strategy this repository follows. It is project-agnostic — it does not mention VertiSea once — and is reusable in any repository. Archived 2026-09-11 so the working tree contains only VertiSea material; `AGENTS.md` remains the live, project-specific instruction file. |
| `CHANGELOG_parse_vertisea_log_v4.m.md` | Changelog for the MATLAB SD-log parser deleted on 2026-09-03. Every entry is permanently `[UNCONFIRMED]` because the changes were written but never executed (no MATLAB in the development environment). Retained as a record of what was attempted; the parser itself must **not** be recreated — extend `vertisea_plot_v7.py` instead. The deleted source is recoverable from git history at `9f5019f`. |
| `Madgwick-upstream/` | Packaging metadata and demo sketches from arduino-libraries/MadgwickAHRS 1.2.0. The two files that actually compile — `MadgwickAHRS.h` and `MadgwickAHRS.cpp` — were moved into `VertiSea/` on 2026-09-11 so the quoted `#include` in the sketch can actually resolve to them; see Issue 58. What remains here (`library.properties`, `keywords.txt`, `README.adoc`, `examples/`, `extras/`) is library-distribution metadata that is meaningless once the sources live in the sketch folder, kept only as provenance for the upstream version. The in-tree copy is a **local fork**: `sampleFreqDef` 512→104 and `betaDef` 0.1→0.5. |
