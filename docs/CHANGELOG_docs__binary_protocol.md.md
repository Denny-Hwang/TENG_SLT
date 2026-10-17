# CHANGELOG — docs/binary_protocol.md

Newest first.

---

## 2026-10-16 - Add versioned session extension records - `[UNCONFIRMED]`

Documented displacement 0x16, SD statistics 0x17, and metadata 0x18 alongside
firmware and the sole parser. No old record layout or telemetry schema changed.
New-record round-trip and simultaneous raw/processed parser tests pass.

---

## 2026-09-08 — Define battery calibration and voltage packets — `[UNCONFIRMED]`

Added the protocol contract for SD-only `TYPE_BATTERY_CAL` (`0x13`) and the distinct SD/radio
forms of 1 Hz `TYPE_BATTERY_VOLTAGE` (`0x14`). This documentation is updated simultaneously
with firmware and the sole Python parser because packet byte layouts cannot be safely staged.
The existing `0x0F` current-statistics packet remains byte-for-byte unchanged to reduce field
deployment risk.

---