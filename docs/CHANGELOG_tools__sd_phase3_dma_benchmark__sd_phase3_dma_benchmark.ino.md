# CHANGELOG — tools/sd_phase3_dma_benchmark/sd_phase3_dma_benchmark.ino

Newest first.

---

## 2026-09-04 — CQ-only CMD25 experiment fails at sector 1; close Phase 3 — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — hardware result is conclusive for the tested architecture.

The final 64-sector experiment kept one IOM/CQ handle for the complete active CMD25 stream and
used only `am_hal_iom_nonblocking_transfer()` after CMD25 began: 515-byte frame TX, 64-byte
response/busy RX windows, stop-token TX, and final ready RX. It therefore tested the meaningful
architectural distinction found in Ambiq's `iom_fram` reference without mixing blocking and
nonblocking IOM APIs.

Hardware still failed at sector 1:

- sector 0 completed with 1.084 ms frame DMA and 221 us response/busy service;
- sector 1's first response-window byte was `0x00`, not an accepted response token;
- all submitted CQ operations completed (`RESULT CALLBACKS count=9`), so this was not a missing
  ISR or callback;
- `all_passed=0` and no byte-verified output was produced.

**Conclusion:** The SparkFun/Ambiq references validate the DMA mechanics but do not solve SD's
token/response/busy protocol. The FRAM-style CQ-only pattern was the last materially different
architecture and it failed at the same boundary. Phase 3 is closed: do not integrate direct HAL
SD DMA into `VertiSea.ino` on SparkFun Apollo3 core 1.2.1. Retain the confirmed Stage 1 queue and
synchronous SD 1.3.0 backend. Revisit only with a different validated core/library or a proven SD
driver that already owns the complete Apollo3 IOM protocol state machine.

---

## 2026-09-04 — Final CQ-only CMD25 experiment based on Ambiq FRAM pattern — `[REVERTED 2026-09-04]`

**Status:** `[REVERTED 2026-09-04]` — all CQ callbacks completed, but the SD response stream was
invalid at sector 1 and byte verification could not proceed.

**Why retry after the stop decision:** The SparkFun-linked AmbiqSuite 2.4.2 `iom_fram` example is
not an SD example and largely matches our initialization/ISR/callback setup. Its relevant extra
pattern is that related SPI phases stay in the nonblocking command queue using `bContinue`, with
the callback only on the final transaction; it does not alternate nonblocking DMA and blocking
IOM calls. That exact architecture was not previously tested for SD.

**Experiment:** Start CMD25 while still in blocking setup, then forbid blocking IOM calls for the
active stream. Submit each 515-byte token+payload+CRC frame as nonblocking TX; read response and
busy bytes through repeated 64-byte nonblocking RX windows; send STOP_TRAN_TOKEN as nonblocking
TX and poll ready via nonblocking RX. Keep one IOM/CQ handle for the entire stream. Limit the first
test to 64 sectors (32 KiB) and require FAT reopen plus byte-for-byte verification.

**Decision remains strict:** This is the final architecture test. Any missing response, timeout,
or verification mismatch leaves direct DMA rejected for Apollo3 core 1.2.1.

---

## 2026-09-04 — Stop direct HAL DMA work on Apollo3 core 1.2.1 — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — the final isolation test failed at sector 1 exactly as the
prior atomic-frame test did. Per the predeclared decision rule, direct HAL ownership is rejected
for this core/card combination and will not be integrated into production.

The isolated control/DMA IOM reinitialization did not restore a valid CMD25 stream:

- 515-byte DMA remained fast and deterministic (1.100 ms; submit 30 us).
- The first sector appeared accepted, but sector 1 returned `0x00` instead of a response token.
- `all_passed=0`; no byte-verification pass was achieved by any DMA revision.

**Conclusion:** The physical DMA engine is fast, but Apollo3 core 1.2.1's HAL/CQ and control-byte
semantics cannot be made into a trustworthy SD writer with the tested architecture. Repeated
experiments also proved the core's blocking multi-byte SPI path times out. Production remains on
the confirmed Stage 1 queue and SD 1.3.0 backend. Future DMA work requires either a different,
validated Apollo3 core/library backend or a complete coherent SD state machine with independent
hardware verification; do not continue patching this prototype into deployment firmware.

---

## 2026-09-04 — Isolate DMA/CQ and blocking control modes with IOM reinitialization — `[REVERTED 2026-09-04]`

**Status:** `[REVERTED 2026-09-04]` — hardware still lost the response at sector 1; IOM
reinitialization did not fix the stream.

**What failed:** Atomic 515-byte token+payload+CRC DMA still lost the response at sector 1. Direct
inspection of `P3D11.BIN` did not show the expected pattern even in sector 0. The common factor
across every failed DMA revision is alternating HAL nonblocking/CQ and blocking transfer APIs on
the same IOM handle while CS remains asserted.

**Diagnostic correction:** Keep CS and pin mux stable, but fully disable/uninitialize IOM0 after
each control or DMA phase. Reinitialize without a nonblocking buffer for command/response/busy
operations, and with the CQ buffer only for the 515-byte frame DMA. This is too expensive for the
eventual production backend, but it directly tests whether persistent HAL CQ state — rather than
SD framing — causes the corruption. If this verifies, production needs one coherent CQ-only state
machine; if it fails, direct HAL ownership is rejected for this core/card combination.

---

## 2026-09-04 — DMA the complete 515-byte SD data frame atomically — `[REVERTED 2026-09-04]`

**Status:** `[REVERTED 2026-09-04]` — both the original and IOM-isolated hardware runs lost the
response at sector 1; no verified file was produced.

**Why:** The 512-byte DMA itself repeatedly completed near the wire limit, but the CMD25 stream
corrupted when blocking IOM calls were interleaved for the token and CRC while CS remained low.
The separate blocking bulk fallback also timed out for 512-, 32-, and 16-byte calls, proving that
Apollo3 core 1.2.1's blocking multi-byte TX path is not a viable bridge.

**Correction:** Build one aligned 515-byte frame containing `WRITE_MULTIPLE_TOKEN`, all 512 data
bytes, and both CRC placeholders, then submit that entire frame as one nonblocking IOM DMA. This
keeps the card's token-through-CRC phase inside one coherent HAL transaction and leaves only the
post-frame response/busy reads outside DMA. Expected wire time at 4 MHz is 1.030 ms.

---

## 2026-09-04 — Reject missing response tokens; disk inspection proves stream corruption — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — disk inspection confirmed corrupt sectors and the final
fail-fast conclusion remains valid.

After the provisional-busy run stopped on `response=0x01` at sector 6, the SD card was mounted
and `P3D06.BIN` inspected directly. Sectors 0–4 matched the deterministic pattern exactly;
sector 5 was already corrupt, sector 6 was corrupt, and later sectors contained unrelated
pre-existing card data because the file was preallocated but never written. This proves that
`0x00` was **not** safe evidence of acceptance and invalidates that fallback. It is removed.

The useful result remains: five 512-byte DMA transfers completed at 1.081 ms mean, proving the
bulk IOM DMA mechanism and speed. The unresolved defect is maintaining a valid SD CMD25 stream
when alternating custom DMA and blocking control transactions. Do not integrate this raw
protocol path into `VertiSea.ino`; either encapsulate all token/payload/CRC/response phases in one
coherent IOM state machine/command queue, or use a storage library/backend designed for Apollo3
multi-byte SPI transfers.

---

## 2026-09-04 — Revert full-duplex helper; provisionally accept busy only with final verification — `[REVERTED 2026-09-04]`

**Status:** `[REVERTED 2026-09-04]` — treating busy as provisional acceptance produced corrupt
sectors; the fallback was removed.

**What failed:** Replacing RX-only control reads with the HAL blocking full-duplex helper caused
the first DMA transaction never to complete (`complete=0` after 100 ms). The earlier RX-only
version had completed five DMA payloads correctly at 1.082 ms mean, so the full-duplex change
regressed DMA/CQ state handling and is reverted.

**New diagnostic path:** Keep the required two CRC placeholder bytes. On this card the RX-only
control primitive occasionally returns `0x00` (busy) without exposing the preceding data-response
token. Treat that case as provisional acceptance, count it as `busy_without_response`, continue
the stream, and require full byte-for-byte FAT verification before `all_passed=1`. This does not
weaken the acceptance criterion: any rejected, omitted, or shifted sector fails final verification.

---

## 2026-09-04 — Use full-duplex clocks for SD response/busy reads — `[REVERTED 2026-09-04]`

**Status:** `[REVERTED 2026-09-04]` — hardware run timed out on the first DMA completion. The
full-duplex blocking helper disturbed the nonblocking DMA/CQ state and was removed.

**What failed:** The delayed-response correction still stopped at sector 5 with `response=0x00`.
The useful result is that five DMA payloads completed in **1.082 ms mean**, very close to the
1.024 ms 4 MHz wire floor, while submit returned in 30 us mean. DMA itself is therefore working
and delivers the expected speed. The failure is isolated to reading SD control bytes afterward.

**Root-cause correction:** The custom helper used an Apollo3 RX-only IOM command for `spiRec()`.
SPI has no receive-only operation; an SD card response requires the master to transmit `0xFF`
while sampling MISO. Replace control-byte reads with `am_hal_iom_spi_blocking_fullduplex()` using
separate aligned TX=`0xFF` and RX buffers. Add a 16-byte response trace on failure so another
card-protocol error is directly observable rather than inferred from one byte.

---

## 2026-09-04 — Poll for delayed SD data response and always terminate CMD25 — `[REVERTED 2026-09-04]`

**Status:** `[REVERTED 2026-09-04]` — hardware still lost response synchronization; later disk
inspection confirmed corruption.

**What failed:** The first DMA run accepted five sectors, then read `0x00` where the data-response
token was expected at sector 5. The benchmark treated the first post-CRC byte as the token and,
after the error, skipped `STOP_TRAN_TOKEN`; verification therefore could not run. This does not
yet prove payload corruption or a DMA defect — `0x00` is also the SD busy value and the response
token may be delayed by fill bytes.

**Correction:** Poll up to 10 ms for the first non-`0xFF` data-response byte before applying the
`0x1F == 0x05` acceptance mask. Always attempt the CMD25 stop sequence after entering the stream,
even after a sector error. Report `completed_sectors` and summarize only initialized samples so
failed runs remain diagnostically valid instead of producing impossible projected throughput.

---

## 2026-09-04 — Add isolated Apollo3 IOM DMA SD payload benchmark — `[REVERTED 2026-09-04]`

**Status:** `[REVERTED 2026-09-04]` — the prototype proved DMA speed but no revision passed SD
byte verification; direct DMA was rejected for core 1.2.1.

**Why:** Phase 2 proved that contiguous preallocation removes FAT outliers and that CMD25 is
deterministic, but measured 9.58 ms per 512-byte payload at 4 MHz versus a 1.024 ms wire floor.
Arduino SD 1.3.0 sends each sector through 515 separate one-byte blocking HAL transactions.
Card busy averaged only 0.91 ms, so payload submission is the measured bottleneck.

**What this benchmark does:**

- Uses normal SD/FAT code to create a new contiguous 2 MiB `P3Dnn.BIN` without overwriting an
  existing file, then closes the filesystem before raw access.
- Releases Arduino `SPI`, takes explicit ownership of Apollo3 IOM0 at the production 4 MHz,
  configures HAL nonblocking transaction storage and the IOM0 ISR, and starts a raw CMD25 stream.
- Sends the token/CRC/response protocol explicitly, but submits each aligned 512-byte payload as
  one `am_hal_iom_nonblocking_transfer()` so the HAL uses DMA rather than 512 byte calls.
- Times DMA submission, callback completion, card busy, response handling, total throughput,
  and CPU spin-loop progress while DMA owns the bus.
- Releases the custom IOM, reinitializes normal SD/FAT, reopens the file, and verifies every byte
  of every sector. `RESULT COMPLETE all_passed=1` is mandatory.

**Containment:** This remains an isolated benchmark. It does not alter production packet code,
the confirmed Stage 1 queue, or the Arduino SD installation. Hardware validation comes before a
repository-local production backend.