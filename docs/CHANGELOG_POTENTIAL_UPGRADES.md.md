# CHANGELOG — POTENTIAL_UPGRADES.md

Newest first.

---

## 2026-09-04 — Reconcile U25 with completed storage experiments — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — user requested the high-level tracker be updated and
cleaned after reviewing the completed experiments.

Replaced U25's obsolete long-form proposal with a concise current summary: Stage 1 queue
confirmed and retained; Phase 2 preallocation evidence positive but integration deferred; direct
SPI/IOM DMA rejected on Apollo3 core 1.2.1 after no architecture passed byte verification. The
tracker links to the component changelogs for detailed measurements and failed approaches.

The superseded planning entries below remain intact as history. Their status text now makes clear
which milestones were confirmed and which recommendations were invalidated by later evidence.

---

## 2026-09-04 — Close U25 direct-DMA investigation after CQ-only failure — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — the updated tracker reflects this hardware result.

The final architecture suggested by Ambiq's `iom_fram` example was tested: after CMD25 startup,
the complete stream used only nonblocking CQ transactions for frame TX, response/busy RX, and
stop/ready handling. Every queued operation generated callbacks, but response synchronization
still failed at sector 1 and no file passed byte verification. This closes the direct-DMA branch
on Apollo3 core 1.2.1. U25's confirmed deliverable is the Stage 1 bounded RAM queue; Phase 2
preallocation evidence remains informative but is not yet a production implementation.

---

## 2026-09-04 — Reject direct SD DMA on Apollo3 core 1.2.1 after hardware failures — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — tracker/reference update completed after user review.

Phase 3 proved 512/515-byte IOM DMA reaches the 4 MHz wire floor (~1.08–1.10 ms), but every tested
CMD25 architecture lost response synchronization and at least one inspected output contained
corrupt sectors. Full IOM teardown/reinitialization between control and DMA phases did not help.
The core's blocking multi-byte SPI path also timed out for 512-, 32-, and 16-byte calls. Therefore
direct HAL DMA is rejected for SparkFun Apollo3 core 1.2.1; no prototype code enters production.
Retain the confirmed Stage 1 RAM queue. Preallocation remains promising from Phase 2 but requires
a separate production design for bounded file sizing, truncation, metadata recovery, and power
loss before integration.

---

## 2026-09-04 — Confirm U25 Phase 2 and justify the DMA backend — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — Phase 2 measurements are confirmed. The proposed DMA
direction was later superseded by the confirmed Phase 3 rejection above.

The isolated 4096-sector benchmark passed byte verification for dynamic, contiguous CMD24, and
contiguous CMD25 paths. Preallocation removed a 111.9 ms dynamic-allocation outlier; CMD25 raised
throughput 46 → 51 KiB/s. Most importantly, contiguous payload submission averaged 9.726 ms while
card busy averaged only 0.909 ms. At 4 MHz the payload wire floor is 1.024 ms; inspection shows
SD 1.3.0 invokes Apollo3's blocking HAL transaction once per byte. The evidence therefore
supports a production backend combining preallocation, multi-block sequencing, and one IOM DMA
transaction per 512-byte payload. Stage 1's queue remains the producer/backpressure boundary.

---

## 2026-09-04 — Promote U25 as the next performance project — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — the staged project was carried out; final results are in
the newer entries above.

Added a fresh-session handoff to U25: instrument first, introduce a three-layer storage
interface, prototype an 8-sector RAM queue on the existing backend, require backpressure and
latency diagnostics, then test preallocation/multi-block writes before attempting SPI DMA.
ADC DMA remains downstream of a proven SD queue so card stalls cannot become DMA-buffer loss.

---

## 2026-09-04 — Complete U12 filename safety in code — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — implementation is present but still needs physical SD-card
verification.

U12 now reflects that SD initialization ordering, invalid-RTC fallback, same-minute collision
handling, and refusal to overwrite on counter exhaustion are implemented in `VertiSea.ino`.

---

## 2026-09-04 — Add buffered SD/SPI DMA storage upgrade — `[CONFIRMED 2026-09-04]`

**Status:** `[CONFIRMED 2026-09-04]` — this planning entry led to the completed staged work;
newer entries record which parts were retained or rejected.

**Why:** The SD card is the third major serial peripheral and, unlike I²C, is already the
confirmed dominant cause of long loop stalls. It therefore deserves a separate upgrade rather
than being hidden as one option inside U19.

**What changed:**

- Added U25 for a layered producer/sector/storage pipeline.
- Recorded that the installed `SPIClass` uses blocking IOM transfers, while Apollo3 supports
  non-blocking SPI/DMA.
- Distinguished 512-byte payload DMA from a truly asynchronous SD writer: command/response,
  data-token validation, card-internal busy time, FAT allocation, and metadata sync remain.
- Ranked three stages: RAM buffering around the current library; preallocated contiguous and
  multi-block writes; then a repository-local asynchronous SD/IOM backend if measurements
  justify it.
- Linked U25 to U23: ADC DMA requires sufficient downstream buffering or SD latency merely
  turns into DMA-buffer overrun.
- Required latency decomposition, queue-overrun diagnostics, byte-exact verification, and
  power-loss/filesystem recovery before acceptance.

---

## 2026-09-04 — Add ADC DMA and I²C/IOM DMA research upgrades — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — feasibility was reviewed against the installed SparkFun Apollo3
core 1.2.1 / AmbiqSuite 2.4.2 and the current VertiSea timing evidence. No firmware was
implemented or hardware-tested.

**Why:** The user wants to investigate DMA for improved stability and loop timing. Keeping ADC
and I²C as separate upgrades prevents an attractive but incorrect assumption that both have
the same payoff or implementation risk.

**What changed:**

- Added U23 for timer-triggered ADC DMA with double buffering. It treats deterministic cadence
  as the primary goal, requires explicit buffer-overrun diagnostics, retains raw `0x0E` data,
  and stages isolated/synthetic-load/full-firmware validation.
- Added U24 for non-blocking Apollo3 IOM/I²C acquisition (DMA where useful). It records that
  the installed `Wire` layer is blocking and owns the IOM handle, so a safe port needs a
  single bus owner/scheduler rather than direct HAL calls alongside `Wire`. A combined
  accel+gyro read is only 12 bytes and fits the 32-byte IOM FIFO, so callback scheduling and
  transaction consolidation may matter more than DMA for this workload.
- Ranked direct contiguous IMU burst reads and IMU FIFO batching as required comparisons. DMA
  does not reduce 400 kHz wire time, and SD remains the dominant measured IMU-rate bottleneck.
- Recorded the local toolchain dependency: installed core 1.2.1 is AmbiqSuite-based, while
  current 2.x SparkFun cores are Mbed-based. Any implementation must pin its tested core and
  keep Apollo3-specific code isolated in the repository.

**Sources checked:** current `VertiSea.ino`; installed `Wire.cpp`, `am_hal_adc.h`, and
`am_hal_iom.h`; SparkFun/Ambiq HAL source; Apollo3 datasheet; existing U17/U19 timing analysis.

---

## 2026-09-04 — Reconcile upgrade tracker and index with implemented work — `[CONFIRMED 2026-09-08]`

**Status:** `[CONFIRMED 2026-09-08]` — documentation-only audit against current source and confirmed
history. User review is still required.

**Why:** The index stopped at U14 while detailed entries extended through U22. It also listed
raw IMU logging as planned, the retired MATLAB parser as active work, supercap display as a
current feature, and the 104 Hz IMU work as wholly pending despite confirmed implementation.

**What changed:**

- Extended the index through U22.
- Clarified U1: the core Python parser/button/CSV flow exists; the richer proposed tab,
  threading, progress, and selection controls do not.
- Marked U4 obsolete after A14's repurpose and `0x0A` retirement.
- Marked U9 implemented using the actual combined `0x12` design and current units/layout.
- Marked U10 obsolete because the MATLAB parser was retired.
- Retargeted U14 from an unimplemented current channel to the remaining voltage,
  bidirectional-current, and linearity gaps.
- Reclassified U6/U12 as partial: write checking is incomplete, and filename collision checks
  currently run before SD initialisation and do not cover valid same-minute names.
- Marked U19 partially implemented: measured dt and raw-only byte reduction are complete;
  SD buffering/latency remains.
- Removed current instructions to update the retired MATLAB parser.

**Deliberately retained:** Historical proposal text where it explains design evolution,
deferred hardware decisions (U16/U18), and unimplemented U11/U21/U22 work.