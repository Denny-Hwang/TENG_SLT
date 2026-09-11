# CHANGELOG — tools/adc_timer_dma_experiment/adc_timer_dma_experiment.ino

Newest first.

---

## 2026-09-08 — First 500 Hz hardware run with foreground stalls — `[PARTIALLY CONFIRMED 2026-09-08]`

**Capture:** `500Hz_stalls_swtrigger0_120s.txt`, default 500 Hz / 120 s / 64-sample buffers,
`TIMING_PROBE_ENABLE=1`, `SOFTWARE_TRIGGER_AFTER_REARM=0`, foreground stalls enabled.

**What passed:** The timer produced 60,026 conversions in 120.061 s (mean interval exactly
2,000 µs); all 937 completed DMA buffers were processed (59,968 samples), with zero DMA errors,
lost buffers, re-arm failures, or bad slots. DMA completion spacing was 127,992–128,018 µs against
128,000 µs nominal, re-arm took at most 10 µs, and 1,200 injected 10 ms plus 120 injected 45 ms
foreground stalls caused no long conversion interval. The final 58 conversions are the expected
incomplete buffer and are deliberately not processed.

**Important correction to the experiment diagnostic:** `fifo_overruns=5626` does **not** mean
5,626 samples were lost. Apollo3 names are misleading: `FIFOOVR1` is the FIFO **75%-full threshold**,
while only `FIFOOVR2` is the FIFO **100%-full condition**. The sketch combined both into one counter.
The count rose by about six per 64-sample DMA buffer, exactly matching repeated threshold assertions,
while every complete DMA sample arrived. Therefore this counter cannot support the old pass/fail
wording and must be split before another run.

**Still open:** One startup interval was short (1,349 µs), likely the initial software trigger
relative to the first timer edge. This run does not test `SOFTWARE_TRIGGER_AFTER_REARM=1`, 400 Hz,
stalls disabled, a stable known-voltage input, or square-wave continuity. DMA remains deferred from
production firmware until after field qualification, as requested.

---

## 2026-09-08 — Add isolated Apollo3 ADC timer/DMA experiment — `[UNCONFIRMED]`

**Status:** `[UNCONFIRMED]` — the sketch compiles for `SparkFun:apollo3:amap3nano` using SparkFun
Apollo3 core 1.2.1 / AmbiqSuite 2.4.2 (14,716 bytes flash, 34,596 bytes global RAM), but has not
yet run on hardware. Timing and data-integrity claims therefore remain unverified.

**Why:** The production firmware polls A14 at the top of `loop()`, coupling harvested-current
sample times and logging volume to foreground stalls. Analysis indicates that deterministic
400–500 Hz ADC sampling could reduce loop and SD load, but the Apollo3 HAL's finite DMA transfer
halts on completion and Ambiq's example issues a software trigger after every re-arm. At these
low rates that trigger could produce a short buffer-boundary interval, so an isolated hardware
experiment is needed before touching deployment firmware.

**What this experiment does:**

- Configures A14 as Apollo3 pad 35 / ADC SE7, preserving the production 14-bit, internal 2.0 V,
  no-hardware-averaging conversion semantics.
- Uses CTIMER A3 at an exact compile-time-selected 500 Hz by default, with 400 Hz supported.
- Transfers into two aligned 64-sample DMA buffers with explicit `FREE`, `DMA`, `READY`, and
  `PROCESSING` ownership so DMA never overwrites a buffer being consumed.
- Limits the ADC ISR to interrupt/timing diagnostics, state handoff, overrun accounting, and DMA
  re-arm. ADC statistics and optional raw serial output run in `loop()`.
- Makes re-arm software triggering independently selectable so both interpretations of the
  Ambiq example can be measured rather than assumed.
- Provides an experiment-only conversion-complete timing probe to measure per-sample interval
  minima/maxima and short/long boundary events. This 400–500 ISR/s mode is not the proposed
  production architecture and can be disabled for production-like DMA testing.
- Injects recurring 10 ms and 45 ms foreground stalls, reports one-second and final parseable
  diagnostics, and never initializes or writes the SD card.

**Required hardware validation:** Run stable-input and square-wave tests with and without
foreground stalls; compare re-arm trigger modes; then repeat at 400 Hz. Acceptance requires no
DMA/FIFO errors, no lost buffers, no unexpected conversion count loss, no short/long conversion
intervals, correct 0–16383 sample values, and unchanged cadence through injected stalls.

---