# CHANGELOG — docs/firmware.md

Newest first.

---

## 2026-09-08 — Synchronize storage and telemetry flow with confirmed firmware — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — reflects the compiled and hardware-verified production
firmware baseline.

Added `SD_BUFFERED_WRITE` to the deployment flags, documented atomic record assembly, the
eight-sector queue, checked synchronous draining, backpressure, five-second durable flush, and
the rejected Apollo3 DMA result. Corrected the `Serial1` initialisation guard and
`TELEM_SERIAL` routing descriptions so they match the implemented feature combinations.