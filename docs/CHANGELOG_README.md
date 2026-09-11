# CHANGELOG — README.md

Newest first.

---

## 2026-09-11 — Re-synchronise the README with the committed source — `[UNCONFIRMED]`

**Why:** a full read of `VertiSea/VertiSea.ino` against the README found the operating
instructions describing a build that is not the one in the repository. The most consequential
divergence: the README stated `TELEM_ENABLE 1` / `USB_TELEM 1`, while the source has both at
`0`. Anyone following §5 and then §5-Ground-Station would flash an SD-only build, connect the
GUI, see nothing, and have no documented reason why.

**What changed:**

- Corrected "Currently committed values" to the real flags (`USB_TELEM 0`, `TELEM_ENABLE 0`)
  and added an explicit warning that the committed build transmits nothing. Documented all
  seven flags; the old table listed the flag set incompletely and omitted `TELEM_ENABLE`'s
  meaning.
- Rewrote the hardware table: A14 is the harvested-current sensor wired directly (100 mA/V,
  0–200 mA full scale), not a 30 k/7.5 k supercapacitor divider; added the A15 1S LiFePO4
  divider, the Hall sensor on pin 2, and the 400 kHz I²C bus.
- Deleted the MATLAB parsing instructions from §6/§9/§11. The parser was retired 2026-09-03,
  but §6 still told the reader the MATLAB parser writes to the MATLAB working directory, and
  §6 "Step 2b — Alternative: parse without MATLAB" presented the only surviving parser as the
  alternative to a deleted one.
- Replaced the CSV table: `_supcap` was the only retired entry marked, while `_imuRaw`,
  `_currentFast`, `_currentCal`, `_batteryCal`, `_batteryVoltage`, `_lpfCal` and `_hallEdge`
  were undocumented despite being what the current build actually produces. Marked which
  suffixes require which build flags.
- Added §2 Repository Layout (the sketch is at `VertiSea/VertiSea.ino`, not the root, which
  every doc link got wrong) and §8 documenting `current_filter_test.py`, a user-facing tool
  with its own `.bat` launcher that the README never mentioned.
- Added the two reference docs missing from the appendix table (`docs/adc_calibration.md`,
  `docs/current_measurement_testing.md`) and links to `IDENTIFIED_ISSUES.md` /
  `POTENTIAL_UPGRADES.md`.
- Removed the dead `SampleData/...` links (the directory is untracked and absent from a fresh
  clone, so they were broken for every reader).
- Added "easy to forget" rows for the failure modes a first-time operator will actually hit:
  blank GUI from `TELEM_ENABLE 0`, board halting in `while(1)` on sensor failure, missing
  `_imuFixed` CSVs from an `IMU_RAW_ONLY` build, and the mdps-vs-°/s gyro unit distinction.
- Noted that no automated test covers `parse_binary_file()`.

**Not changed:** no source behaviour. Every correction was made by reading the committed
source, so the README now matches it rather than an earlier build.

---

## 2026-09-08 — Document the confirmed buffered-SD baseline — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — synchronized after the cleaned firmware was compiled,
hardware-tested, and its two resulting SD logs parsed exactly to EOF.

Updated the deployment-flag table for `TELEM_ENABLE`, `IMU_RAW_ONLY`, and
`SD_BUFFERED_WRITE`; removed the obsolete warning that the combined USB debug/telemetry flags
leave `Serial1` uninitialised; documented that production storage remains buffered but
synchronous after direct Apollo3 DMA was rejected; and warned that opening the GUI over USB
still resets the tested board despite RTS/DTR mitigation.