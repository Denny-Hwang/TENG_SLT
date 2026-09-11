# `archived/`

Files kept for the record but **not part of the VertiSea system**. Nothing here is read by
the firmware, the ground station, or any build step, and nothing here should be treated as
current design intent. Do not add live documentation to this folder.

| File | Why it is here |
|------|----------------|
| `AI_Agent_Project_Documentation_Guide.md` | A general-purpose methodology document describing the AI-agent documentation strategy this repository follows. It is project-agnostic — it does not mention VertiSea once — and is reusable in any repository. Archived 2026-09-11 so the working tree contains only VertiSea material; `AGENTS.md` remains the live, project-specific instruction file. |
| `CHANGELOG_parse_vertisea_log_v4.m.md` | Changelog for the MATLAB SD-log parser deleted on 2026-09-03. Every entry is permanently `[UNCONFIRMED]` because the changes were written but never executed (no MATLAB in the development environment). Retained as a record of what was attempted; the parser itself must **not** be recreated — extend `vertisea_plot_v7.py` instead. The deleted source is recoverable from git history at `9f5019f`. |
