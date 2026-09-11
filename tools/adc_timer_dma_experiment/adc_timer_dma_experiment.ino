// =============================================================================
// VertiSea Apollo3 ADC Timer + DMA Experiment
// =============================================================================
//
// PURPOSE
// -------
// Isolate timer-triggered ADC DMA on the SparkFun RedBoard Artemis Nano before
// integrating it into VertiSea.ino. This sketch samples A14 (Apollo3 pad 35,
// ADC SE7) into ping-pong DMA buffers while the foreground optionally suffers
// deliberate 10 ms and 45 ms stalls.
//
// This is a bench experiment, not buoy firmware. It does not initialize the
// IMUs, RTC, SD card, telemetry radio, or Hall sensor, and it writes no files.
// Never deploy it in place of VertiSea.ino.
//
// TOOLCHAIN
// ---------
// Written for SparkFun Apollo3 Arduino core 1.2.1 / AmbiqSuite 2.4.2 and board
// SparkFun:apollo3:amap3nano. The current-sensor input must remain in the ADC's
// 0-2.0 V range. Do not call analogRead() while this sketch owns the ADC.
//
// BUILD
// -----
// arduino-cli compile --fqbn SparkFun:apollo3:amap3nano \
//   tools/adc_timer_dma_experiment/adc_timer_dma_experiment.ino
//
// TEST PROCEDURE
// --------------
// 1. Start with A14 driven by a stable 0-2.0 V source. Open Serial at 115200.
// 2. Run the default 500 Hz / 120 s test and save all output.
// 3. Repeat with INJECT_FOREGROUND_STALLS=1 (default). Then repeat with it =0.
// 4. Repeat at SAMPLE_RATE_HZ=400 if lower SD traffic is being evaluated.
// 5. If boundary timing shows short/long intervals, compare
//    SOFTWARE_TRIGGER_AFTER_REARM=0 and =1. The Ambiq example uses =1, but an
//    immediate software trigger at this low rate may disturb buffer boundaries.
// 6. For signal-continuity testing, drive A14 with a slow square wave wholly
//    inside 0-2.0 V and set PRINT_EVERY_SAMPLE=1. Keep the serial stream short.
//
// PASS CONDITIONS
// ---------------
// FINAL must report dma_errors=0, fifo_overruns=0, lost_buffers=0, bad_slots=0,
// and conversions close to 1 + SAMPLE_RATE_HZ * elapsed_s (the initial software
// trigger accounts for the possible extra sample). With TIMING_PROBE_ENABLE=1,
// interval_short and interval_long should both be zero after the re-arm mode is
// chosen. Deliberate foreground stalls must not produce conversion-interval
// tails. A compile or short bench run is not deployment qualification.

#include <Arduino.h>
#include "am_mcu_apollo.h"

// ---- Experiment controls ---------------------------------------------------
constexpr uint32_t SAMPLE_RATE_HZ = 500;       // Also test 400 Hz.
constexpr uint32_t TEST_DURATION_S = 120;
constexpr uint16_t DMA_SAMPLES = 64;           // 128 ms/buffer at 500 Hz.
constexpr bool TIMING_PROBE_ENABLE = true;     // CNVCMP ISR at every sample.
constexpr bool SOFTWARE_TRIGGER_AFTER_REARM = false;
constexpr bool INJECT_FOREGROUND_STALLS = true;
constexpr bool PRINT_EVERY_SAMPLE = false;     // Adds substantial Serial load.

constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t SERIAL_WAIT_MS = 5000;
constexpr uint32_t SUMMARY_INTERVAL_MS = 1000;
constexpr uint32_t TIMER_CLOCK_HZ = 12000000UL;
constexpr uint32_t TIMER_PERIOD_TICKS = TIMER_CLOCK_HZ / SAMPLE_RATE_HZ;
constexpr uint32_t EXPECTED_INTERVAL_US = 1000000UL / SAMPLE_RATE_HZ;
constexpr uint32_t SHORT_INTERVAL_US = EXPECTED_INTERVAL_US * 3UL / 4UL;
constexpr uint32_t LONG_INTERVAL_US = EXPECTED_INTERVAL_US * 5UL / 4UL;

constexpr uint8_t ADC_PAD = 35;                 // RedBoard Artemis Nano A14.
constexpr uint8_t ADC_PIN_FUNCTION = 0;         // Pad 35 function 0 = ADCSE7.
constexpr am_hal_adc_slot_chan_e ADC_CHANNEL = AM_HAL_ADC_SLOT_CHSEL_SE7;

static_assert(SAMPLE_RATE_HZ > 0, "SAMPLE_RATE_HZ must be nonzero");
static_assert(TIMER_CLOCK_HZ % SAMPLE_RATE_HZ == 0,
              "Choose a sample rate that divides the 12 MHz timer clock exactly");
static_assert(DMA_SAMPLES > 1, "DMA buffer must contain at least two samples");

enum BufferState : uint8_t {
  BUFFER_FREE = 0,
  BUFFER_DMA,
  BUFFER_READY,
  BUFFER_PROCESSING
};

alignas(4) uint32_t dmaBuffers[2][DMA_SAMPLES];
volatile BufferState bufferState[2] = {BUFFER_FREE, BUFFER_FREE};
volatile uint8_t activeDmaBuffer = 0;
volatile uint32_t bufferFirstSequence[2] = {0, 0};
volatile uint32_t nextArmSequence = 0;

void *adcHandle = nullptr;
volatile bool fatalSetupError = false;
volatile bool dmaErrorSeen = false;

// ISR diagnostics. The timing probe deliberately enables one interrupt per
// conversion for this experiment only. Production DMA should leave it off.
volatile uint32_t conversionCount = 0;
volatile uint32_t previousConversionUs = 0;
volatile uint32_t intervalCount = 0;
volatile uint32_t intervalSumUs = 0;
volatile uint32_t intervalMinUs = UINT32_MAX;
volatile uint32_t intervalMaxUs = 0;
volatile uint32_t intervalShortCount = 0;
volatile uint32_t intervalLongCount = 0;
volatile uint32_t dmaCompleteCount = 0;
volatile uint32_t previousDmaCompleteUs = 0;
volatile uint32_t dmaCompleteMinUs = UINT32_MAX;
volatile uint32_t dmaCompleteMaxUs = 0;
volatile uint32_t dmaErrorCount = 0;
volatile uint32_t fifoOverrunCount = 0;
volatile uint32_t lostBufferCount = 0;
volatile uint32_t rearmFailureCount = 0;
volatile uint32_t rearmMaxUs = 0;

uint32_t processedBufferCount = 0;
uint32_t processedSampleCount = 0;
uint32_t badSlotCount = 0;
uint32_t processingMaxUs = 0;
uint16_t sampleMin = UINT16_MAX;
uint16_t sampleMax = 0;
uint64_t sampleSum = 0;

uint32_t experimentStartMs = 0;
uint32_t lastSummaryMs = 0;
uint32_t nextShortStallMs = 0;
uint32_t nextLongStallMs = 0;
uint32_t injectedShortStalls = 0;
uint32_t injectedLongStalls = 0;
bool experimentStopped = false;

bool checkHal(uint32_t status, const char *operation) {
  if (status == AM_HAL_STATUS_SUCCESS) return true;
  Serial.print("ERROR,operation=");
  Serial.print(operation);
  Serial.print(",status=");
  Serial.println(status);
  fatalSetupError = true;
  return false;
}

bool armDmaBuffer(uint8_t index) {
  am_hal_adc_dma_config_t config = {};
  config.bDynamicPriority = true;
  config.ePriority = AM_HAL_ADC_PRIOR_SERVICE_IMMED;
  config.bDMAEnable = true;
  config.ui32SampleCount = DMA_SAMPLES;
  config.ui32TargetAddress = reinterpret_cast<uint32_t>(dmaBuffers[index]);

  bufferFirstSequence[index] = nextArmSequence;
  nextArmSequence += DMA_SAMPLES;
  activeDmaBuffer = index;
  bufferState[index] = BUFFER_DMA;
  return am_hal_adc_configure_dma(adcHandle, &config) == AM_HAL_STATUS_SUCCESS;
}

// The Apollo3 startup code dispatches ADC_IRQn to this AmbiqSuite ISR name.
extern "C" void am_adc_isr(void) {
  uint32_t status = 0;
  if (am_hal_adc_interrupt_status(adcHandle, &status, false) !=
      AM_HAL_STATUS_SUCCESS) {
    dmaErrorSeen = true;
    dmaErrorCount++;
    return;
  }
  am_hal_adc_interrupt_clear(adcHandle, status);

  uint32_t nowUs = micros();

  if (status & AM_HAL_ADC_INT_CNVCMP) {
    conversionCount++;
    if (previousConversionUs != 0) {
      uint32_t intervalUs = nowUs - previousConversionUs;
      intervalCount++;
      intervalSumUs += intervalUs;
      if (intervalUs < intervalMinUs) intervalMinUs = intervalUs;
      if (intervalUs > intervalMaxUs) intervalMaxUs = intervalUs;
      if (intervalUs < SHORT_INTERVAL_US) intervalShortCount++;
      if (intervalUs > LONG_INTERVAL_US) intervalLongCount++;
    }
    previousConversionUs = nowUs;
  }

  if (status & (AM_HAL_ADC_INT_FIFOOVR1 | AM_HAL_ADC_INT_FIFOOVR2)) {
    fifoOverrunCount++;
  }

  if (status & AM_HAL_ADC_INT_DERR) {
    dmaErrorSeen = true;
    dmaErrorCount++;
  }

  if (status & AM_HAL_ADC_INT_DCMP) {
    uint32_t rearmStartUs = nowUs;
    uint8_t completed = activeDmaBuffer;
    uint8_t alternate = completed ^ 1U;
    dmaCompleteCount++;

    if (previousDmaCompleteUs != 0) {
      uint32_t completionIntervalUs = nowUs - previousDmaCompleteUs;
      if (completionIntervalUs < dmaCompleteMinUs) {
        dmaCompleteMinUs = completionIntervalUs;
      }
      if (completionIntervalUs > dmaCompleteMaxUs) {
        dmaCompleteMaxUs = completionIntervalUs;
      }
    }
    previousDmaCompleteUs = nowUs;
    bufferState[completed] = BUFFER_READY;

    uint8_t next = alternate;
    if (bufferState[alternate] == BUFFER_READY) {
      // The consumer fell behind. Drop the older ready buffer and preserve the
      // buffer that just completed, which contains the newest complete data.
      lostBufferCount++;
      next = alternate;
    } else if (bufferState[alternate] == BUFFER_PROCESSING) {
      // Never let DMA overwrite memory being read by loop(). Drop the newly
      // completed buffer by immediately reusing it instead.
      lostBufferCount++;
      next = completed;
    }

    if (!armDmaBuffer(next)) {
      rearmFailureCount++;
      dmaErrorSeen = true;
    } else if (SOFTWARE_TRIGGER_AFTER_REARM) {
      if (am_hal_adc_sw_trigger(adcHandle) != AM_HAL_STATUS_SUCCESS) {
        rearmFailureCount++;
        dmaErrorSeen = true;
      }
    }

    uint32_t rearmUs = micros() - rearmStartUs;
    if (rearmUs > rearmMaxUs) rearmMaxUs = rearmUs;
  }
}

bool configureAdc() {
  const am_hal_gpio_pincfg_t adcPinConfig = {
    .uFuncSel = ADC_PIN_FUNCTION
  };
  if (!checkHal(am_hal_gpio_pinconfig(ADC_PAD, adcPinConfig),
                "gpio_pinconfig")) return false;
  if (!checkHal(am_hal_adc_initialize(0, &adcHandle),
                "adc_initialize")) return false;
  if (!checkHal(am_hal_adc_power_control(adcHandle, AM_HAL_SYSCTRL_WAKE, false),
                "adc_power_control")) return false;

  am_hal_adc_config_t adcConfig = {};
  adcConfig.eClock = AM_HAL_ADC_CLKSEL_HFRC;
  adcConfig.ePolarity = AM_HAL_ADC_TRIGPOL_RISING;
  adcConfig.eTrigger = AM_HAL_ADC_TRIGSEL_SOFTWARE;
  adcConfig.eReference = AM_HAL_ADC_REFSEL_INT_2P0;
  adcConfig.eClockMode = AM_HAL_ADC_CLKMODE_LOW_LATENCY;
  adcConfig.ePowerMode = AM_HAL_ADC_LPMODE0;
  adcConfig.eRepeat = AM_HAL_ADC_REPEATING_SCAN;
  if (!checkHal(am_hal_adc_configure(adcHandle, &adcConfig),
                "adc_configure")) return false;

  am_hal_adc_slot_config_t slotConfig = {};
  slotConfig.eMeasToAvg = AM_HAL_ADC_SLOT_AVG_1;
  slotConfig.ePrecisionMode = AM_HAL_ADC_SLOT_14BIT;
  slotConfig.eChannel = ADC_CHANNEL;
  slotConfig.bWindowCompare = false;
  slotConfig.bEnabled = true;
  if (!checkHal(am_hal_adc_configure_slot(adcHandle, 0, &slotConfig),
                "adc_configure_slot")) return false;

  if (!armDmaBuffer(0)) {
    Serial.println("ERROR,operation=initial_dma_arm");
    fatalSetupError = true;
    return false;
  }

  uint32_t interruptMask = AM_HAL_ADC_INT_DERR |
                           AM_HAL_ADC_INT_DCMP |
                           AM_HAL_ADC_INT_FIFOOVR1 |
                           AM_HAL_ADC_INT_FIFOOVR2;
  if (TIMING_PROBE_ENABLE) interruptMask |= AM_HAL_ADC_INT_CNVCMP;
  if (!checkHal(am_hal_adc_interrupt_enable(adcHandle, interruptMask),
                "adc_interrupt_enable")) return false;

  NVIC_ClearPendingIRQ(ADC_IRQn);
  NVIC_EnableIRQ(ADC_IRQn);
  if (!checkHal(am_hal_adc_enable(adcHandle), "adc_enable")) return false;
  return true;
}

void startTimerAndAdc() {
  am_hal_ctimer_stop(3, AM_HAL_CTIMER_TIMERA);
  am_hal_ctimer_config_single(3, AM_HAL_CTIMER_TIMERA,
                              AM_HAL_CTIMER_HFRC_12MHZ |
                              AM_HAL_CTIMER_FN_REPEAT);
  am_hal_ctimer_period_set(3, AM_HAL_CTIMER_TIMERA,
                           TIMER_PERIOD_TICKS,
                           TIMER_PERIOD_TICKS / 2U);
  am_hal_ctimer_adc_trigger_enable();
  am_hal_ctimer_start(3, AM_HAL_CTIMER_TIMERA);

  // Ambiq's repeating-scan example uses one software trigger to seed sampling;
  // subsequent scans are driven by CTIMER A3.
  if (!checkHal(am_hal_adc_sw_trigger(adcHandle), "initial_sw_trigger")) return;
  experimentStartMs = millis();
  lastSummaryMs = experimentStartMs;
  nextShortStallMs = experimentStartMs + 100;
  nextLongStallMs = experimentStartMs + 1000;
}

bool claimReadyBuffer(uint8_t &index, uint32_t &firstSequence) {
  bool found = false;
  NVIC_DisableIRQ(ADC_IRQn);
  for (uint8_t i = 0; i < 2; i++) {
    if (bufferState[i] == BUFFER_READY) {
      bufferState[i] = BUFFER_PROCESSING;
      index = i;
      firstSequence = bufferFirstSequence[i];
      found = true;
      break;
    }
  }
  NVIC_EnableIRQ(ADC_IRQn);
  return found;
}

void releaseProcessedBuffer(uint8_t index) {
  NVIC_DisableIRQ(ADC_IRQn);
  bufferState[index] = BUFFER_FREE;
  NVIC_EnableIRQ(ADC_IRQn);
}

void processReadyBuffers() {
  uint8_t index;
  uint32_t firstSequence;
  while (claimReadyBuffer(index, firstSequence)) {
    uint32_t startUs = micros();
    for (uint16_t i = 0; i < DMA_SAMPLES; i++) {
      uint32_t raw = dmaBuffers[index][i];
      uint8_t slot = AM_HAL_ADC_FIFO_SLOT(raw);
      uint16_t counts = static_cast<uint16_t>(AM_HAL_ADC_FIFO_SAMPLE(raw));
      if (slot != 0) badSlotCount++;
      if (counts < sampleMin) sampleMin = counts;
      if (counts > sampleMax) sampleMax = counts;
      sampleSum += counts;
      processedSampleCount++;

      if (PRINT_EVERY_SAMPLE) {
        Serial.print("S,seq=");
        Serial.print(firstSequence + i);
        Serial.print(",counts=");
        Serial.println(counts);
      }
    }
    processedBufferCount++;
    uint32_t processingUs = micros() - startUs;
    if (processingUs > processingMaxUs) processingMaxUs = processingUs;
    releaseProcessedBuffer(index);
  }
}

void printDiagnostics(const char *prefix) {
  // Use only primitive locals here. Arduino's sketch preprocessor emits
  // function prototypes before sketch-defined types, so returning a custom
  // snapshot struct from a helper is not portable to Apollo3 core 1.2.1.
  uint32_t conversions;
  uint32_t intervals;
  uint32_t intervalSum;
  uint32_t intervalMin;
  uint32_t intervalMax;
  uint32_t intervalShort;
  uint32_t intervalLong;
  uint32_t dmaCompletes;
  uint32_t dmaCompleteMin;
  uint32_t dmaCompleteMax;
  uint32_t dmaErrors;
  uint32_t fifoOverruns;
  uint32_t lostBuffers;
  uint32_t rearmFailures;
  uint32_t rearmMax;

  NVIC_DisableIRQ(ADC_IRQn);
  conversions = conversionCount;
  intervals = intervalCount;
  intervalSum = intervalSumUs;
  intervalMin = intervalMinUs;
  intervalMax = intervalMaxUs;
  intervalShort = intervalShortCount;
  intervalLong = intervalLongCount;
  dmaCompletes = dmaCompleteCount;
  dmaCompleteMin = dmaCompleteMinUs;
  dmaCompleteMax = dmaCompleteMaxUs;
  dmaErrors = dmaErrorCount;
  fifoOverruns = fifoOverrunCount;
  lostBuffers = lostBufferCount;
  rearmFailures = rearmFailureCount;
  rearmMax = rearmMaxUs;
  NVIC_EnableIRQ(ADC_IRQn);

  uint32_t nowMs = millis();
  uint32_t elapsedMs = nowMs - experimentStartMs;
  uint32_t intervalMeanUs = intervals ? intervalSum / intervals : 0;
  uint32_t minInterval = intervalMin == UINT32_MAX ? 0 : intervalMin;
  uint32_t minCompletion = dmaCompleteMin == UINT32_MAX ? 0 : dmaCompleteMin;
  uint32_t sampleMean = processedSampleCount
                      ? static_cast<uint32_t>(sampleSum / processedSampleCount) : 0;

  Serial.print(prefix);
  Serial.print(",elapsed_ms="); Serial.print(elapsedMs);
  Serial.print(",conversions="); Serial.print(conversions);
  Serial.print(",interval_mean_us="); Serial.print(intervalMeanUs);
  Serial.print(",interval_min_us="); Serial.print(minInterval);
  Serial.print(",interval_max_us="); Serial.print(intervalMax);
  Serial.print(",interval_short="); Serial.print(intervalShort);
  Serial.print(",interval_long="); Serial.print(intervalLong);
  Serial.print(",dma_completes="); Serial.print(dmaCompletes);
  Serial.print(",dma_complete_min_us="); Serial.print(minCompletion);
  Serial.print(",dma_complete_max_us="); Serial.print(dmaCompleteMax);
  Serial.print(",dma_errors="); Serial.print(dmaErrors);
  Serial.print(",fifo_overruns="); Serial.print(fifoOverruns);
  Serial.print(",lost_buffers="); Serial.print(lostBuffers);
  Serial.print(",rearm_failures="); Serial.print(rearmFailures);
  Serial.print(",rearm_max_us="); Serial.print(rearmMax);
  Serial.print(",processed_buffers="); Serial.print(processedBufferCount);
  Serial.print(",processed_samples="); Serial.print(processedSampleCount);
  Serial.print(",bad_slots="); Serial.print(badSlotCount);
  Serial.print(",process_max_us="); Serial.print(processingMaxUs);
  Serial.print(",sample_min="); Serial.print(sampleMin == UINT16_MAX ? 0 : sampleMin);
  Serial.print(",sample_mean="); Serial.print(sampleMean);
  Serial.print(",sample_max="); Serial.print(sampleMax);
  Serial.print(",short_stalls="); Serial.print(injectedShortStalls);
  Serial.print(",long_stalls="); Serial.println(injectedLongStalls);
}

void injectForegroundStalls(uint32_t nowMs) {
  if (!INJECT_FOREGROUND_STALLS) return;

  if (static_cast<int32_t>(nowMs - nextShortStallMs) >= 0) {
    nextShortStallMs += 100;
    delay(10);
    injectedShortStalls++;
  }
  if (static_cast<int32_t>(nowMs - nextLongStallMs) >= 0) {
    nextLongStallMs += 1000;
    delay(45);
    injectedLongStalls++;
  }
}

void stopExperiment() {
  am_hal_ctimer_adc_trigger_disable();
  am_hal_ctimer_stop(3, AM_HAL_CTIMER_TIMERA);
  delay(5);  // Allow any conversion already in progress to finish.
  NVIC_DisableIRQ(ADC_IRQn);
  am_hal_adc_interrupt_disable(adcHandle, 0xFFFFFFFF);
  am_hal_adc_disable(adcHandle);
  experimentStopped = true;

  // Only complete DMA buffers are processed. The final partial buffer remains
  // intentionally excluded and is visible as conversions-processed_samples.
  processReadyBuffers();
  printDiagnostics("FINAL");
  Serial.println(dmaErrorSeen ? "RESULT,pass=0,reason=dma_or_rearm_error"
                              : "RESULT,inspect_final_metrics=1");
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  uint32_t waitStartMs = millis();
  while (!Serial && millis() - waitStartMs < SERIAL_WAIT_MS) {}
  delay(100);

  Serial.println("ADC_TIMER_DMA_EXPERIMENT,version=1");
  Serial.print("CONFIG,sample_rate_hz="); Serial.print(SAMPLE_RATE_HZ);
  Serial.print(",duration_s="); Serial.print(TEST_DURATION_S);
  Serial.print(",dma_samples="); Serial.print(DMA_SAMPLES);
  Serial.print(",timing_probe="); Serial.print(TIMING_PROBE_ENABLE ? 1 : 0);
  Serial.print(",sw_trigger_after_rearm=");
  Serial.print(SOFTWARE_TRIGGER_AFTER_REARM ? 1 : 0);
  Serial.print(",foreground_stalls="); Serial.print(INJECT_FOREGROUND_STALLS ? 1 : 0);
  Serial.print(",print_samples="); Serial.println(PRINT_EVERY_SAMPLE ? 1 : 0);

  if (!configureAdc()) {
    Serial.println("RESULT,pass=0,reason=setup_failed");
    return;
  }
  startTimerAndAdc();
  if (!fatalSetupError) Serial.println("START");
}

void loop() {
  if (fatalSetupError || experimentStopped) {
    delay(1000);
    return;
  }

  processReadyBuffers();
  uint32_t nowMs = millis();
  injectForegroundStalls(nowMs);

  if (nowMs - lastSummaryMs >= SUMMARY_INTERVAL_MS) {
    lastSummaryMs += SUMMARY_INTERVAL_MS;
    printDiagnostics("SUMMARY");
  }

  if (nowMs - experimentStartMs >= TEST_DURATION_S * 1000UL) {
    stopExperiment();
  }
}