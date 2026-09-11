# CHANGELOG — current_filter_test.py

Newest entries first. This changelog records why changes were made as well as what changed.

---

## 2026-09-09 — Add file-processing and plot GUI — `[UNCONFIRMED]`

**Why:** Selecting and comparing high-rate current data in Excel is cumbersome. The normal
workflow should require selecting only `_currentFast.csv`; the matching calibration and RTC
files are deterministic siblings and should not need repetitive manual selection.

**What changed:** Running `current_filter_test.py` without arguments (or with `--gui`) now opens
a Tkinter GUI. It automatically locates `_currentCal.csv` and `_rtcEvt.csv`, applies the existing
full-scale rejection → centered median → baseline-subtraction pipeline, saves
`_currentFast_filtered.csv` and `_currentFast_filtered.png` next to the input, and embeds the
raw/filtered plot with Matplotlib zoom, pan, and save controls. The median window is selectable.

Added a local UTC-offset field defaulting to `-7` for the September PNNL/PDT captures. Because
the RTC event's clock fields are already firmware-local, the offset is attached as ISO-8601
metadata (for example `14:45:45.109000-07:00`) rather than added to the clock a second time.
The CLI has the equivalent `--utc-offset` option.

**Validation:** Python compilation, all primitive self-tests, a headless GUI construction test,
and end-to-end CSV/PNG generation against the `09081445` test capture are required before this
entry is presented for confirmation.

---

## 2026-09-08 — Add RTC-derived wall-clock timestamps — `[UNCONFIRMED]`

**Why:** Oscilloscope traces use wall-clock time, while `_currentFast.csv` contains only
`millis()`-relative timestamps. Comparing the two required a manual conversion even though the
same capture's `_rtcEvt.csv` already provides the intended local-time anchor.

**What changed:** `current_filter_test.py` now auto-loads the sibling `_rtcEvt.csv` (or accepts
`--rtc-csv RTC`), anchors its date/time to the RTC packet's `timestamp_ms`, and writes an
`actual_time_local` ISO-8601 column in `--write-csv` output. The report shows the mapped first
and last times and explicitly notes that RTC values are local time without a UTC offset and
that the anchor has whole-second resolution. Missing auto-detected RTC data leaves the column
blank; an explicitly missing or malformed RTC file fails loudly. Multiple RTC rows also fail
loudly because separate parsed CSVs cannot unambiguously associate samples with boot sessions.

**Validation:** Added wall-time arithmetic checks to the existing self-test. The target
`09081445_currentFast.csv` / `09081445_rtcEvt.csv` pair is used for an end-to-end generated-file
check before this entry is presented for confirmation.