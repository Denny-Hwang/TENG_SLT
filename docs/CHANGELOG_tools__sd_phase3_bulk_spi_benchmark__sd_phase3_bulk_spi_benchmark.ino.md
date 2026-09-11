# CHANGELOG — tools/sd_phase3_bulk_spi_benchmark/sd_phase3_bulk_spi_benchmark.ino

Newest first.

---

## 2026-09-04 — Use the 16-byte TX half-FIFO and make timeout cleanup silent — `[REVERTED 2026-09-04]`

**Status:** `[REVERTED 2026-09-04]` — 16-byte calls also timed out on sector 0. The blocking
multi-byte SPI path is abandoned; the later complete-frame DMA test also failed verification, so
neither experimental backend is suitable for production on core 1.2.1.

**What failed:** Sixteen 32-byte calls also returned HAL status 4 on sector 0. The Apollo3 IOM
has 32 bytes of total FIFO storage, but this SPI configuration exposes it as 16-byte TX and RX
halves; a 32-byte TX therefore still enters the defective blocking refill path. Once the first
timeout poisoned IOM0, the benchmark attempted CMD25 cleanup through the same failed peripheral,
causing the long cascade of identical timeout messages.

**Correction:** Use thirty-two 16-byte `transferOut()` calls per sector, which fit entirely in
the TX half-FIFO before the command starts and still reduce HAL calls 16× versus SD 1.3.0. If a
write fails, deassert CS and end the transaction without issuing more SPI commands, preventing
misleading timeout floods from an already-failed peripheral.

---

## 2026-09-04 — Use 32-byte IOM-FIFO chunks after 512-byte blocking timeout — `[REVERTED 2026-09-04]`

**Status:** `[REVERTED 2026-09-04]` — hardware showed that 32 bytes exceeds the usable TX half of
the split FIFO and still invokes the broken refill path.

**What failed:** The first `SPI.transferOut(..., 512)` returned HAL status 4
(`AM_HAL_STATUS_TIMEOUT`). The failed long blocking transfer left IOM0 unable to service cleanup
bytes, producing repeated status-4 messages and `completed_sectors=0`. This is a core/HAL limit,
not an SD card rejection: failure occurred inside payload submission before a valid response.

**Correction:** Split each 512-byte payload into sixteen 32-byte `SPI.transferOut()` calls. The
Apollo3 IOM FIFO is exactly 32 bytes, so each call is fully preloaded before its command starts
and avoids the blocking HAL's FIFO-refill loop. This still reduces payload HAL transactions from
512 to 16 (32× fewer), retains one coherent Arduino-SPI CMD25 stream, and keeps final byte-for-byte
verification mandatory.

---

## 2026-09-04 — Add coherent bulk-SPI fallback benchmark — `[REVERTED 2026-09-04]`

**Status:** `[REVERTED 2026-09-04]` — the single 512-byte blocking HAL transfer timed out on the
first sector. Retained as the rationale for the FIFO-sized correction above.

**Why:** Direct IOM DMA proved that a 512-byte payload can transfer in about 1.08 ms, but mixing
HAL DMA/CQ and separate blocking control transactions corrupted the CMD25 stream after five
sectors. Disk inspection confirmed the corruption. Before implementing a full asynchronous SD
state machine, test the simpler root-cause fix: one existing `SPI.transferOut()` call per payload.

**Design:** Preserve Arduino SPI ownership and a coherent CMD25 transaction. Preallocate a new
contiguous 2 MiB file, send token/control bytes with normal `SPI.transfer()`, send each aligned
512-byte payload through one bulk blocking `SPI.transferOut()`, terminate CMD25, then reopen via
FAT and verify every byte. This does not overlap CPU work, but should remove the measured 512×
HAL-call overhead and may be sufficient to reach the acquisition-rate goal with much lower risk.