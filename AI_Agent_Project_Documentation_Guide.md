# AI Agent Project Documentation Guide

This guide describes a documentation strategy for software projects that use AI coding
agents (Roo Code, GitHub Copilot, Cursor, Claude Code, Windsurf, etc.). The goal is to
give the agent enough context to act correctly on the first attempt — avoiding reversions
of deliberate design decisions, re-introduction of fixed bugs, and silent deviation from
project conventions.

Drop this file, and the files it describes, into any repository. Use `AGENTS.md` as
the root project-instructions file; for agents that do not read it natively, point
their instruction loader to it at the start of every session.

---

## Contents

1. [Core Idea](#1-core-idea)
2. [File Structure](#2-file-structure)
3. [AI Instructions File — `AGENTS.md`](#3-ai-instructions-file--agentsmd)
4. [Component Reference Files](#4-component-reference-files)
5. [Changelog Files](#5-changelog-files)
6. [User Guide](#6-user-guide)
7. [Workflow Rules — What the AI Must Follow](#7-workflow-rules--what-the-ai-must-follow)
8. [Template: `AGENTS.md`](#8-template-agentsmd)
9. [Template: Component Reference File](#9-template-component-reference-file)
10. [Template: Changelog Entry](#10-template-changelog-entry)
11. [Maintenance Checklist](#11-maintenance-checklist)
12. [Agent Compatibility — Wiring Your Agent to `AGENTS.md`](#12-agent-compatibility--wiring-your-agent-to-agentsmd)

---

## 1. Core Idea

Git commit history records *what* changed. It does not record *why*, and it does not
capture dead ends, rationale, or constraints that are invisible in the final code.

An AI agent starting a new session has access to the current source files but not to
the reasoning behind them. Without that reasoning, it will:

- Silently revert a deliberate workaround that you already tried and rejected.
- Re-implement a utility function that already exists under a different name.
- Violate a naming or architectural convention that exists for a good reason.
- Undo a bug fix whose root cause is not obvious from the surrounding code alone.

This strategy closes that gap by maintaining three layers of prose documentation
alongside the code:

| Layer | Granularity | What it captures | When the AI reads it |
|-------|------------|-----------------|----------------------|
| **Project instructions** (`AGENTS.md`) | Whole project | Scope, conventions, file map, toolchain constraints | Every session, automatically |
| **Component reference files** (`docs/component_name.md`) | One major system or subsystem (may span many source files) | Full design intent, API, data model, rejected approaches | Before touching that system |
| **Changelog files** (`docs/CHANGELOG_sourcefile.md`) | One individual source file | Chronological record of decisions and dead ends for that file | Before modifying the corresponding source file |

Together, these let an AI reconstruct enough project context to act correctly without
reading every source file from scratch.

---

## 2. File Structure

```
your-project/
├── AGENTS.md                         ← single source of truth for project instructions (agent-agnostic, lives in root)
├── .roo/
│   └── rules.md                     ← agent loader: reads AGENTS.md (Roo Code auto-loads this)
├── docs/                            ← optional; all human-authored markdown
│   ├── component_a.md               ← reference for a major system or subsystem
│   ├── component_b.md               ← one .md per system/subsystem, not per source file
│   ├── CHANGELOG_source_file_1.md   ← one changelog per individual source file
│   ├── CHANGELOG_source_file_2.md   ← created the first time that source file is modified
│   └── CHANGELOG_source_file_3.md
├── README.md                        ← end-user documentation and project homepage
├── src/
│   └── ...                          ← your code
└── AI_Agent_Project_Documentation_Guide.md   ← this file
```

The single source of truth for project instructions is **`AGENTS.md`** in the project root.
Placing it in the root keeps it agent-agnostic — it does not live inside any tool's
configuration folder, so switching or adding AI agents requires no reorganisation.
Agent-specific loader files (like `.roo/rules.md` for Roo Code, or
`.github/copilot-instructions.md` for GitHub Copilot) simply point to it. This means
you only maintain one instructions file regardless of which agents your team uses.

---

## 3. AI Instructions File — `AGENTS.md`

**Location:** `AGENTS.md` (project root)

This is the single most important file. It lives in the project root and is the
authoritative project instructions file for **all** agents. Each agent's own loader
file (see [§12](#12-agent-compatibility--wiring-your-agent-to-agentsmd)) points here.

**It must contain:**

1. **What the project is** — one paragraph. What problem does it solve? Who uses it?
2. **Read-first file table** — a table of your component reference files with a
   one-line description of what each covers. The AI reads only what is relevant to the
   current task; this table tells it which file that is. Changelog files are handled in
   a separate section and are discovered on demand, not enumerated here.
3. **Coding conventions** — language version, toolchain, architectural patterns, naming
   rules, things you explicitly do *not* do. Be brief but specific.
4. **Documentation maintenance rules** — when to update the reference files and
   changelogs, and what triggers an update.
5. **Files / folders to ignore** — generated output directories, cache folders, backup
   files. The AI should not create, assume, or reference these.

**Keep it short.** Two to four pages. If it grows beyond that, move detail into the
component reference files and link to them here.

See [§8](#8-template-agentsmd) for a fill-in-the-blanks template.

---

## 4. Component Reference Files

One markdown file per major system or subsystem — not one per individual source file.
A component reference file typically covers an entire coherent feature area that may
span several source files (e.g., the whole GUI, the data processing pipeline, the
authentication system). This is the authoritative source of truth for design intent
for that system.

**A component reference file covers:**

- **Purpose and scope** — what this component does and what it deliberately does *not* do.
- **Public interface** / API — function signatures, input/output types, events emitted,
  side effects.
- **Internal design** — key data structures, state variables, the flow through major
  operations. Enough detail that the AI can make a targeted edit without having to read
  every line of source.
- **Dependencies** — which other modules, libraries, or external services it relies on.
- **Known constraints and gotchas** — things that look wrong but are intentional, platform
  quirks, performance considerations, and past bugs worth remembering.
- **Out-of-scope / rejected approaches** — brief notes on approaches that were considered
  and rejected, so they are not re-proposed.

**Naming:** `<system_name>.md` (e.g., `auth_service.md`, `data_pipeline.md`,
`main_window.md`). Use broad, descriptive names that reflect a feature area, not
one-to-one mappings to source file names.

**Who updates it:** The human developer (or the AI, with human confirmation). See §7.

See [§9](#9-template-component-reference-file) for a template.

---

## 5. Changelog Files

One `CHANGELOG_<source_file_name>.md` per **individual source code file** — named
directly after the file it tracks when the file name is unique (e.g.,
`CHANGELOG_auth_controller.md` for `auth_controller.py`). If the project contains
duplicate source file names in different folders, include a path-safe relative path in
the changelog name, using `__` for folder separators (e.g.,
`src/api/config.py` becomes `docs/CHANGELOG_src__api__config.py.md`).

Do not create changelogs in advance for every file in the project; for existing
codebases, create a changelog the **first time you modify that file**, and populate it
with the change being made. New projects can adopt the same approach: the changelog
comes into existence when the file first changes, not before.

For broad mechanical changes that touch many files without changing behaviour, public
interfaces, or design intent, use one summary entry in `docs/CHANGELOG_project.md`
instead of creating noisy per-file entries. The summary should list the affected file
patterns and explain why the mechanical change was made.

Entries are added in reverse chronological order, newest first.

**What a changelog entry captures:**

- **Status marker** — one of `[UNCONFIRMED]`, `[CONFIRMED YYYY-MM-DD]`, or
  `[REVERTED YYYY-MM-DD]`. See "Status markers" below.
- **Date and version/commit** (optional but useful).
- **What changed** — a brief description of the modification.
- **Why** — the reasoning behind the decision. This is the most valuable part. If there
  were alternatives, briefly note why they were not chosen.
- **Dead ends** — if you tried something that didn't work before landing on this
  solution, record it. This prevents the AI (or another contributor) from trying the
  same failed approach.
- **Side effects** — anything else in the codebase that was affected.

### Status markers — how changelogs handle confirmation

Changelogs are a *historical record*, not a description of current state. They must
capture dead ends and reverted attempts (§5 above), so they cannot wait for confirmation
before being written — a session that ends before confirmation would lose the record
entirely. Instead, every entry carries a status marker:

- **`[UNCONFIRMED]`** — written at the time of the change, before the user has tested
  it. This is the default state of a new entry.
- **`[CONFIRMED YYYY-MM-DD]`** — the user has verified the change works. The AI flips
  the marker on confirmation; the entry body is otherwise unchanged.
- **`[REVERTED YYYY-MM-DD]`** — the change did not work and was rolled back. The
  original entry stays in place (now serving as a recorded dead end) and a brief
  follow-up entry above it explains what failed and why.

**The AI reads the relevant changelog *before* modifying a file, writes a new
`[UNCONFIRMED]` entry *as part of* the change, and updates the marker only after the
user reports the result.** This keeps the historical record complete across session
boundaries while still distinguishing verified decisions from speculative ones.

Reference files and `README.md` follow a different rule — they describe current design
intent and current behaviour, so they are only updated after confirmation. See §7.

See [§10](#10-template-changelog-entry) for a template entry.

---

## 6. User Guide

If your project has an end-user-facing interface (GUI, CLI, API, web app), maintain a
`README.md` that describes what the tool does and how to use it — written for
someone who has never seen the code. Placing user-facing content in `README.md` means
it renders automatically as the project homepage on GitHub or GitLab.

The AI must keep this in sync with verified behaviour: any confirmed user-visible
behaviour change (new button, renamed command, changed output file, new workflow)
triggers a `README.md` update after the user confirms the change works.

Keep developer and maintainer notes (architecture details, AI assistant instructions,
how to run headlessly, etc.) in an **Appendix** section at the bottom of `README.md`
so end users see clean documentation first and contributors can still find the internals.

**Useful sections to include:**

- Getting started / prerequisites
- Core concepts and terminology
- Step-by-step workflows for the most common tasks
- Reference tables for controls, commands, or settings
- Output files: what is created, where, and what it contains
- A "Things That Are Easy to Forget" table for common gotchas
- A quick-reference section for users who already know the tool

---

## 7. Workflow Rules — What the AI Must Follow

These rules are what make the documentation strategy effective. Include them verbatim
(or adapted) in your `AGENTS.md`.

### At the start of every session

1. **Scan for unresolved `[UNCONFIRMED]` changelog entries.** Search `docs/CHANGELOG_*.md`
   for the marker `[UNCONFIRMED]`. If any are found, list them and ask the user to
   confirm, revert, or defer each one before starting new work. This closes the gap
   created when a previous session ended before the user could verify a change.
   Deferring means the entry stays `[UNCONFIRMED]`, the agent notes that the user chose
   to defer it for now, and new work may proceed. Deferred entries should still be
   surfaced at future session starts until they are confirmed or reverted.

### Before modifying any file

2. **Check whether a `CHANGELOG_<name>.md` exists** for that file and read it if so.
   Do not read every changelog upfront — only the one(s) for files you are about to
   change. Pay particular attention to entries marked `[REVERTED]` — these are
   recorded dead ends that should not be re-attempted.
3. **Check whether a component reference file exists** for the system or subsystem and
   read the relevant sections.
4. If documentation contradicts the current source, flag the discrepancy rather than
   silently following one or the other. Treat source code as the authority for what
   currently runs, and reference files as the authority for intended design.

### During the change

5. **Implement, do not suggest.** Make changes using tools rather than producing
   code blocks for the human to copy.
6. **Reuse what exists.** Prefer extending existing utilities over re-implementing them.
   Check the reference file for what already exists before writing new code.
7. **Write the changelog entry as part of the change**, marked `[UNCONFIRMED]`. Create
   the changelog file if it does not yet exist. The entry captures *why*, not just
   *what*, and includes any dead ends already encountered while making the change.
   For broad mechanical changes that do not alter behaviour, public interfaces, or
   design intent (formatting, import sorting, generated lockfile updates), one summary
   entry in `docs/CHANGELOG_project.md` may cover the affected files instead of
   creating noisy per-file entries.

### After the user confirms the change works

8. **Flip the changelog marker** from `[UNCONFIRMED]` to `[CONFIRMED YYYY-MM-DD]`. Do
   not rewrite the entry body — confirmation is a status change, not a re-edit.
9. **Update the component reference file** — remove any "planned / design only" sections
   that are now implemented; fold new behaviour into the appropriate reference sections.
10. **Update `README.md`** for any user-visible behaviour change.

### If the user reports the change did not work

11. **Mark the existing changelog entry `[REVERTED YYYY-MM-DD]`** and leave its body
    intact — it is now a recorded dead end. Add a brief follow-up entry above it
    explaining what failed and why, so the next attempt has the full context.
12. **Do not update reference files or `README.md`** for a reverted change. Those
    files describe current behaviour and should not have reflected the unconfirmed
    change in the first place (see rule below).

### Reference files and `README.md` are confirmation-gated

13. Do **not** update reference files or `README.md` until the user explicitly confirms
    the change works. These describe *current design intent* and *current behaviour*,
    so they must stay in sync with verified, working code rather than speculative
    changes. Changelogs are different — they are a historical record and are written
    immediately under an `[UNCONFIRMED]` marker (see §5 and rule 7 above).

---

## 8. Template: `AGENTS.md`

Copy this into `AGENTS.md` (project root) and fill in the bracketed sections.

```markdown
# Project Instructions

## What this project is

[One paragraph: what problem does this project solve, who uses it, what are its main
subsystems or components?]

## Read these files before touching any code

| File | What it documents |
|------|-------------------|
| `docs/component_a.md` | [One sentence describing what this covers] |
| `docs/component_b.md` | [One sentence] |

These are the single source of truth for design intent. The source code is the
authority for what currently runs. If the two contradict each other, flag the
discrepancy rather than silently following either one.

## Session start — check for unresolved changelog entries

At the start of every session, search `docs/CHANGELOG_*.md` for entries marked
`[UNCONFIRMED]`. List any you find and ask the user to confirm, revert, or defer each
one before starting new work. This catches changes from a previous session that ended
before the user could verify them. If the user defers an entry, leave it
`[UNCONFIRMED]`, note that it was deferred, and continue. Surface it again at the next
session start.

## Changelog files — read before modifying, write during the change

Many source files have a companion `CHANGELOG_<name>.md` in `docs/`.

- **Before modifying any file**, check whether a changelog exists for it and read it.
  This prevents accidentally reverting decisions that were already tried and abandoned.
  Pay particular attention to entries marked `[REVERTED]` — these are recorded dead
  ends.
- **If duplicate source file names exist**, include a path-safe relative path in the
  changelog name, using `__` for folder separators (for example,
  `src/api/config.py` becomes `docs/CHANGELOG_src__api__config.py.md`).
- **Do not read every changelog upfront.** Only read the ones relevant to files you are
  about to change.
- **Write the changelog entry as part of the change itself**, marked `[UNCONFIRMED]`.
  Create the changelog file if it does not yet exist.
- **For broad mechanical changes**, one summary entry in
  `docs/CHANGELOG_project.md` may cover the affected files if the change does not
  alter behaviour, public interfaces, or design intent.
- **After the user confirms the change works**, flip the marker to
  `[CONFIRMED YYYY-MM-DD]`. Do not rewrite the entry body.
- **If the user reports the change did not work**, mark the entry
  `[REVERTED YYYY-MM-DD]` and leave its body intact as a recorded dead end. Add a
  brief follow-up entry above it explaining what failed.

## Coding conventions

- [Language version and compiler/interpreter requirements]
- [Architectural pattern: e.g., "all state lives in a single top-level class"]
- [Naming conventions: e.g., "utility functions are prefixed with `util_`"]
- [Toolchain / dependency constraints: e.g., "only use stdlib; no third-party packages"]
- [Things you explicitly do NOT do: e.g., "no global variables", "no dynamic SQL"]

## Documentation maintenance rules

- **Reference files and `README.md` are confirmation-gated.** Do not update them
  until the user confirms the feature works as expected. They describe current design
  intent and current behaviour, so they must reflect verified code only.
- **Changelogs are written immediately, under an `[UNCONFIRMED]` marker.** They are a
  historical record and must capture dead ends, so they cannot wait for confirmation
  without losing data across session boundaries. Flip the marker on confirmation;
  mark `[REVERTED]` if the change is rolled back.
- Changelog entries should capture *why* decisions were made, not just *what* changed.
- Commit messages should include a short "why" alongside the "what".

## README.md — always update for user-facing changes

After a user confirms a feature works, update `README.md` for any change that
affects how someone *operates* the tool. This includes new controls, changed workflows,
new output files, and renamed commands.

## Ignored in Git (do not create or assume these exist)

- `[output directory]` — generated files
- `[cache directory]` — cached data
- `*.[bak/tmp/auto-save extension]` — backup and temporary files
```

---

## 9. Template: Component Reference File

```markdown
# [Component Name]

> **Status:** [Active development / Stable / Deprecated]  
> **Source file(s):** [`src/component_name.ext`](../src/component_name.ext)  
> **Last reviewed:** [YYYY-MM-DD]

## Purpose

[One paragraph: what does this component do? What is its responsibility boundary?
What does it explicitly *not* do?]

## Dependencies

| Dependency | Why it is needed |
|------------|-----------------|
| [Library or module name] | [One-line reason] |

## Public Interface

### `functionOrMethodName(param1, param2)`

**Purpose:** [What it does]  
**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `param1` | `type` | [Description] |
| `param2` | `type` | [Description] |

**Returns:** `type` — [Description]  
**Side effects:** [File I/O, state mutation, events emitted, etc., or "none"]

[Repeat for each public function / method / endpoint.]

## Internal Design

### Data Structures

| Variable / Property | Type | Description |
|--------------------|------|-------------|
| `internalVar` | `type` | [What it holds and why] |

### Key Flows

**[Flow name — e.g., "Initialisation", "Processing a request", "Saving to disk"]**

1. [Step 1]
2. [Step 2]
3. [Step 3]

[Repeat for each significant flow.]

## Known Constraints and Gotchas

- [Anything that looks wrong but is intentional, or non-obvious behaviour to preserve]
- [Platform quirks, performance constraints, or known edge cases]

## Rejected Approaches

- **[Approach name]** — tried [date or version]; abandoned because [reason]. Do not
  re-introduce.

## Open Issues / To-Do

- [Known limitations that are accepted for now]
```

---

## 10. Template: Changelog Entry

Add new entries at the **top** of the file (newest first).

```markdown
# CHANGELOG — [Source File Name]

---

## [YYYY-MM-DD] — [Short title of the change] — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — written at the time of the change. Flip to
`[CONFIRMED YYYY-MM-DD]` once the user verifies, or `[REVERTED YYYY-MM-DD]` if
rolled back.

**What changed:**
[1–3 sentences describing the modification.]

**Why:**
[The reasoning. Why was this approach chosen? What problem did it solve?
If there were alternatives, briefly note why they were not chosen.]

**Dead ends (if any):**
- Tried [approach X] first — did not work because [reason].
- Considered [approach Y] — rejected because [reason].

**Side effects:**
[Other files or behaviours affected, or "none".]

---

## [YYYY-MM-DD] — [Previous entry title] — `[CONFIRMED YYYY-MM-DD]`

...
```

**Example status transitions:**

- New entry: `## 2026-05-21 — Switched auth to JWT — [UNCONFIRMED]`
- After user confirms: `## 2026-05-21 — Switched auth to JWT — [CONFIRMED 2026-05-22]`
- After user reports it broke production: `## 2026-05-21 — Switched auth to JWT — [REVERTED 2026-05-23]` (body left intact; a new follow-up entry is added above)

---

## 11. Maintenance Checklist

### At session start

- [ ] Searched `docs/CHANGELOG_*.md` for `[UNCONFIRMED]` entries and resolved each
      with the user (confirm, revert, or defer); deferred entries remain
      `[UNCONFIRMED]` and should be surfaced again next session

### As part of every code change (before user confirmation)

- [ ] `[UNCONFIRMED]` changelog entry added to `CHANGELOG_<modified_file>.md`
      (create if absent), capturing *why* and any dead ends already encountered
      or, for broad mechanical changes, one summary entry added to
      `docs/CHANGELOG_project.md`

### After the user confirms the change works

- [ ] Changelog marker flipped from `[UNCONFIRMED]` to `[CONFIRMED YYYY-MM-DD]`
- [ ] Component reference file updated for any new/changed interface, data structure,
      or design decision
- [ ] `README.md` updated if any user-visible behaviour changed
- [ ] `AGENTS.md` updated if new files were added that the AI should read, or if
      conventions changed

### If the user reports the change did not work

- [ ] Existing changelog entry marked `[REVERTED YYYY-MM-DD]` with body intact
- [ ] Brief follow-up entry added above it explaining what failed
- [ ] Reference files and `README.md` left unchanged (they were never updated for
      the unconfirmed change)

### Periodically (e.g., each milestone or release)

- [ ] Reference files reviewed for accuracy — code may have drifted from prose
- [ ] "Open Issues / To-Do" sections reviewed and pruned or promoted to issues
- [ ] `AGENTS.md` still accurately describes the project scope and conventions
- [ ] `AGENTS.md` read-first file table updated if component reference files are
      added, renamed, or removed
- [ ] Stale `[UNCONFIRMED]` entries (older than the current work cycle) flagged
      to the user — they likely point to changes the writer forgot to verify

---

## 12. Agent Compatibility — Wiring Your Agent to `AGENTS.md`

The project instructions live in one file: **`AGENTS.md`** in the project root. Each AI
agent tool uses a different mechanism to load project instructions automatically. The
table below shows how to wire the most common agents to `AGENTS.md` so you only ever
maintain one file.

| Agent | Auto-load file | How to wire it to `AGENTS.md` |
|-------|---------------|------------------------------|
| **Codex** | `AGENTS.md` | No loader needed; Codex reads `AGENTS.md` from the repository root automatically. |
| **Roo Code** | `.roo/rules.md` | Put `Read AGENTS.md and follow all instructions in it.` as the sole content of `.roo/rules.md` |
| **GitHub Copilot** | `.github/copilot-instructions.md` | See note below: pointer instructions may work in Agent/Edits mode; paste or mirror full contents for Chat |
| **Cursor** | `.cursor/rules` or `.cursorrules` | Create `.cursorrules` with: `Read AGENTS.md and follow all instructions in it.` |
| **Windsurf** | `.windsurfrules` | Create `.windsurfrules` with: `Read AGENTS.md and follow all instructions in it.` |
| **Claude Code** | `CLAUDE.md` | Create `CLAUDE.md` with: `Read AGENTS.md and follow all instructions in it.` |

> **Compatibility caution:** This strategy is most reliable with agents that can read
> project files and use tools. For inline-completion tools or chat assistants without
> repository file access, treat `AGENTS.md` as source material to paste or mirror into
> that tool's supported instruction surface.

### GitHub Copilot — pointer vs. paste

`.github/copilot-instructions.md` is injected as project instruction text for Copilot
Chat and Copilot coding sessions, but whether a pointer like `Read AGENTS.md and follow
all instructions in it.` actually causes Copilot to read the file depends on the mode:

- **Copilot Agent / Edits mode:** The agent has workspace file access as a tool and may
  follow the instruction to read `AGENTS.md` proactively. A short pointer is usually
  enough.
- **Copilot Chat / inline chat:** The instruction is available as text, but Copilot may
  not read the referenced file unless the user explicitly adds it to context. The safer
  approach is to paste or mirror the full contents of `AGENTS.md` into
  `.github/copilot-instructions.md`, or begin the session by attaching `AGENTS.md` to
  the chat context.

**Recommended `.github/copilot-instructions.md`:**
```markdown
<!-- Source of truth: AGENTS.md. Keep this file in sync when AGENTS.md changes. -->
<!-- In Copilot Agent/Edits mode, the pointer below may be sufficient.          -->
<!-- In Copilot Chat, paste the full contents of AGENTS.md below instead.       -->

Read `AGENTS.md` at the repository root and follow all instructions in it.
```

### Example loader files

**`.roo/rules.md` (Roo Code):**
```markdown
Read `AGENTS.md` and follow all instructions in it.
```

**`.cursorrules` (Cursor):**
```markdown
Read `AGENTS.md` and follow all instructions in it.
```

### Keeping loader files in sync

If you must duplicate content (e.g., for GitHub Copilot), add a comment at the top of
the loader file:

```markdown
<!-- This file mirrors AGENTS.md. Update AGENTS.md first, then sync here. -->
```

---

## Why This Works

The strategy is effective because it separates three kinds of knowledge, and applies a
different update rule to each:

| Kind | Where it lives | When it is written | How it ages |
|------|---------------|--------------------|-------------|
| Current code state | Source files | At edit time | Always current |
| Current design intent | Reference `.md` files | Only after user confirmation | Updated on confirmation |
| Historical decisions and dead ends | `CHANGELOG_*.md` files | At edit time, marked `[UNCONFIRMED]`; status flipped to `[CONFIRMED]` or `[REVERTED]` later | Append-only, never deleted |

The split matters: reference files describe *current state* and must stay in sync with
verified code, so they are confirmation-gated. Changelogs are a *historical record* and
must capture dead ends — including reverted attempts — so they are written immediately
under a status marker that survives session boundaries. A session that ends before
confirmation does not lose the record; the next session begins by resolving any
`[UNCONFIRMED]` entries it finds.

An AI working within this system can answer "what should this function do?", "what has
already been tried?", and "what are the conventions?" without reading the full codebase.
It knows when to act and when to flag a discrepancy.

The overall cost of maintenance is low: a changelog entry takes two to five minutes to
write. The payoff — not spending thirty minutes walking a new AI session back from a
confidently wrong change — outweighs that cost quickly.
