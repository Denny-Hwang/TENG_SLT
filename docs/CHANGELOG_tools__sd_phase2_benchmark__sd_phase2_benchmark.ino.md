# CHANGELOG — tools/sd_phase2_benchmark/sd_phase2_benchmark.ino

Newest first.

---

## 2026-09-04 — Add isolated SD preallocation and multi-block benchmark — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — compiles for `SparkFun:apollo3:amap3nano` with Apollo3
core 1.2.1 and Arduino SD 1.3.0 (28,644 bytes flash, 115,276 bytes global RAM). All three paths
ran on the RedBoard Artemis Nano with the deployment SD card, reopened through FAT, and passed
the full 2 MiB byte-pattern verification (`all_passed=1`).

**Why:** Stage 1 proved that an eight-sector queue is byte-correct and does not overrun, but it
did not increase average IMU rate because the queue still drains through synchronous SD 1.3.0.
Before writing an Apollo3 DMA/card driver, Phase 2 needs to distinguish dynamic FAT allocation,
per-sector command/SPI time, card-internal busy time, and the benefit of CMD25 multi-block writes.

**What this benchmark does:**

- Uses the same CS pin and `SPI_HALF_SPEED` setting as production firmware.
- Writes three new 2 MiB files without overwriting existing files:
  - `P2Dnn.BIN`: normal dynamic FAT growth with blocking 512-byte writes.
  - `P2Cnn.BIN`: contiguous preallocation with nonblocking CMD24 writes, timing command/payload
    submission separately from card busy time.
  - `P2Mnn.BIN`: contiguous preallocation with one pre-erased CMD25 multi-block sequence.
- Reports mean, p50, p90, p95, p99, p99.9, and maximum latency plus total throughput and sync
  time over 4096 sectors per path.
- Reopens every output through FAT, reads every sector back, and compares a deterministic
  pattern byte-for-byte. `all_passed=1` is mandatory; speed results from a failed verification
  are invalid.
- Runs outside `VertiSea.ino` so raw block experimentation cannot corrupt scientific packet
  production or silently change deployment behavior.

**Decision rule:** If contiguous preallocation removes the long tail, FAT allocation is the
primary target. If CMD25 materially improves it, integrate preallocation/multi-block writes
behind the Stage 1 backend. If `CONTIG_SUBMIT` remains material while `CONTIG_BUSY` is small,
Apollo3 IOM DMA is justified next. If busy time dominates, DMA alone cannot remove the tail.

**Hardware result — 4096 sectors/path, production 4 MHz setting:**

| Path / component | Mean | p99 | p99.9 | Max | Throughput |
|---|---:|---:|---:|---:|---:|
| Dynamic blocking write | 10.667 ms | 14.617 ms | 16.130 ms | 111.916 ms | 46 KiB/s |
| Contiguous CMD24 submit | 9.726 ms | 9.745 ms | 9.758 ms | 19.840 ms | — |
| Contiguous card busy | 0.909 ms | 4.791 ms | 5.296 ms | 5.373 ms | — |
| CMD25 multi-block call | 9.577 ms | 9.601 ms | 9.610 ms | 9.643 ms | 51 KiB/s |

- Contiguous preallocation removed the **111.9 ms FAT/allocation outlier** and reduced total
  tail to roughly 15 ms (submit + busy), so preallocation is justified for production.
- CMD25 improved throughput only about **10.9%** (46 → 51 KiB/s), but made per-sector latency
  exceptionally deterministic by removing repeated command overhead and allocation work.
- At 4 MHz, a 512-byte payload has a theoretical wire floor of 1024 us. The measured
  9.58–9.73 ms submit time is therefore about 9.4× the wire floor. Source inspection explains
  it: SD 1.3.0 calls `spiSend()` 515 times/sector, and Apollo3 `SPI.transfer(uint8_t)` performs a
  complete blocking HAL IOM transaction per byte. **SPI submission, not card busy, dominates.**
- Card busy averages only 0.91 ms; its p99 is 4.79 ms. DMA cannot remove that physical program
  time, but it can remove most CPU occupation during the dominant payload submission.

**Decision:** Phase 2 is confirmed. Production work should combine contiguous preallocation and
multi-block sequencing behind the Stage 1 queue, then use Apollo3 IOM DMA for each 512-byte
payload. A DMA-only change that keeps SD 1.3.0's byte-at-a-time loop would miss the measured
root cause.

> **Superseded production recommendation:** Later Phase 3 hardware tests rejected direct IOM DMA
> on Apollo3 core 1.2.1 because no SD protocol architecture passed byte verification. The Phase 2
> measurements remain valid; preallocation integration is deferred pending file lifecycle and
> power-loss design. See the Phase 3 benchmark changelog.