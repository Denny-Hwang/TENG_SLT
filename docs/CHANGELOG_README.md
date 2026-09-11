# CHANGELOG — README.md

Newest first.

---

## 2026-09-08 — Document the confirmed buffered-SD baseline — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — synchronized after the cleaned firmware was compiled,
hardware-tested, and its two resulting SD logs parsed exactly to EOF.

Updated the deployment-flag table for `TELEM_ENABLE`, `IMU_RAW_ONLY`, and
`SD_BUFFERED_WRITE`; removed the obsolete warning that the combined USB debug/telemetry flags
leave `Serial1` uninitialised; documented that production storage remains buffered but
synchronous after direct Apollo3 DMA was rejected; and warned that opening the GUI over USB
still resets the tested board despite RTS/DTR mitigation.