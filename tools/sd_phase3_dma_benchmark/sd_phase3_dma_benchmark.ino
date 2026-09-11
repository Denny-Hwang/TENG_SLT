// =============================================================================
// VertiSea SD Phase 3 — Apollo3 IOM DMA Benchmark
// =============================================================================
//
// PURPOSE
// -------
// Validate the high-risk part of the proposed production SD backend in isolation:
// one coherent Apollo3 IOM command-queue state machine for the complete CMD25
// stream. After CMD25 starts, every data frame, response/busy read, and stop
// token uses am_hal_iom_nonblocking_transfer(); blocking IOM calls are forbidden.
//
// Phase 2 measured ~9.58 ms per sector because Arduino SD 1.3.0 performs 515
// separate SPI.transfer(uint8_t) HAL transactions. At 4 MHz, the 512-byte wire
// floor is only 1.024 ms. This benchmark keeps FAT preallocation and SD command
// handling explicit, but replaces the payload loop with one nonblocking IOM DMA.
//
// SAFETY
// ------
// - This is NOT deployment firmware.
// - It creates a new P3Dnn.BIN file and never overwrites an existing file.
// - This first CQ-only validation writes 64 sectors (32 KiB).
// - Do not remove power/card while BEGIN DMA is active.
// - RESULT COMPLETE all_passed=1 is mandatory before production integration.

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <am_mcu_apollo.h>

#include <stdlib.h>
#include <string.h>

constexpr uint8_t  CS_SD = 4;
constexpr uint8_t  SPI_IOM_MODULE = AP3_SPI_IOM;  // IOM0 on RedBoard Artemis Nano
constexpr uint32_t SPI_CLOCK_HZ = 4000000UL;
constexpr uint32_t SECTOR_BYTES = 512;
constexpr uint32_t DMA_FRAME_BYTES = 1 + SECTOR_BYTES + 2;
constexpr uint32_t RESPONSE_WINDOW_BYTES = 64;
constexpr uint32_t BENCHMARK_SECTORS = 64;        // bounded correctness test first
constexpr uint32_t DMA_TIMEOUT_US = 100000UL;
constexpr uint32_t CARD_BUSY_TIMEOUT_US = 2000000UL;
constexpr uint32_t SERIAL_WAIT_MS = 10000UL;

// SD SPI commands/tokens used by the minimal raw writer.
constexpr uint8_t DATA_RESPONSE_MASK = 0x1F;
constexpr uint8_t DATA_RESPONSE_ACCEPTED = 0x05;

Sd2Card card;
SdVolume volume;
SdFile root;

alignas(4) uint8_t sectorBuffer[SECTOR_BYTES];
alignas(4) uint8_t verifyBuffer[SECTOR_BYTES];
alignas(4) uint8_t dmaFrameBuffer[DMA_FRAME_BYTES + 1];  // rounded storage for aligned DMA
alignas(4) uint8_t responseWindow[RESPONSE_WINDOW_BYTES];
alignas(4) uint8_t stopTokenBuffer[4];
alignas(4) uint8_t commandBuffer[8];
alignas(4) uint8_t ioByteBuffer[4];

// HAL nonblocking/CQ storage. Length is specified in 32-bit words. 64 words
// provides room for two CQ transactions; only one is outstanding here.
alignas(4) uint32_t nonblockingTransactionBuffer[64];

uint32_t dmaSubmitUs[BENCHMARK_SECTORS];
uint32_t dmaElapsedUs[BENCHMARK_SECTORS];
uint32_t cardBusyUs[BENCHMARK_SECTORS];
uint32_t responseUs[BENCHMARK_SECTORS];
uint32_t cpuSpinCounts[BENCHMARK_SECTORS];

constexpr uint8_t RESPONSE_TRACE_BYTES = 16;
uint8_t responseTrace[RESPONSE_TRACE_BYTES];
uint8_t responseTraceCount = 0;

char dmaFileName[13];
void* iomHandle = nullptr;

volatile bool dmaComplete = false;
volatile uint32_t dmaCompletionStatus = AM_HAL_STATUS_FAIL;
volatile uint32_t dmaCallbackCount = 0;

int compareUint32(const void* lhs, const void* rhs) {
  uint32_t a = *static_cast<const uint32_t*>(lhs);
  uint32_t b = *static_cast<const uint32_t*>(rhs);
  return (a > b) - (a < b);
}

void fillPattern(uint8_t* destination, uint32_t sectorIndex) {
  constexpr uint8_t TAG = 0xD3;
  for (uint32_t i = 0; i < SECTOR_BYTES; ++i) {
    destination[i] = uint8_t(TAG * 73U + sectorIndex * 29U +
                             i * 17U + (sectorIndex >> 8));
  }
  destination[0] = uint8_t(sectorIndex);
  destination[1] = uint8_t(sectorIndex >> 8);
  destination[2] = uint8_t(sectorIndex >> 16);
  destination[3] = uint8_t(sectorIndex >> 24);
  destination[4] = TAG;
}

bool patternMatches(const uint8_t* actual, uint32_t sectorIndex,
                    uint16_t* mismatchOffset) {
  fillPattern(sectorBuffer, sectorIndex);
  for (uint16_t i = 0; i < SECTOR_BYTES; ++i) {
    if (actual[i] != sectorBuffer[i]) {
      *mismatchOffset = i;
      return false;
    }
  }
  return true;
}

bool fileExists(const char* name) {
  SdFile candidate;
  if (!candidate.open(&root, name, O_READ)) return false;
  candidate.close();
  return true;
}

bool chooseUnusedName() {
  for (uint8_t run = 0; run < 100; ++run) {
    snprintf(dmaFileName, sizeof(dmaFileName), "P3D%02u.BIN", run);
    if (!fileExists(dmaFileName)) return true;
  }
  return false;
}

uint32_t percentileFromSorted(const uint32_t* sorted, uint32_t count,
                              uint32_t numerator, uint32_t denominator) {
  if (count == 0) return 0;
  uint64_t scaled = uint64_t(count - 1) * numerator;
  uint32_t index = uint32_t((scaled + denominator - 1) / denominator);
  return sorted[index];
}

void printLatencySummary(const char* label, uint32_t* samples, uint32_t count) {
  qsort(samples, count, sizeof(samples[0]), compareUint32);
  uint64_t sum = 0;
  for (uint32_t i = 0; i < count; ++i) sum += samples[i];

  Serial.print("RESULT LATENCY_US test="); Serial.print(label);
  Serial.print(" n="); Serial.print(count);
  Serial.print(" mean="); Serial.print(uint32_t(sum / count));
  Serial.print(" min="); Serial.print(samples[0]);
  Serial.print(" p50="); Serial.print(percentileFromSorted(samples, count, 50, 100));
  Serial.print(" p90="); Serial.print(percentileFromSorted(samples, count, 90, 100));
  Serial.print(" p95="); Serial.print(percentileFromSorted(samples, count, 95, 100));
  Serial.print(" p99="); Serial.print(percentileFromSorted(samples, count, 99, 100));
  Serial.print(" p999="); Serial.print(percentileFromSorted(samples, count, 999, 1000));
  Serial.print(" max="); Serial.println(samples[count - 1]);
}

void dmaCallback(void*, uint32_t transactionStatus) {
  dmaCompletionStatus = transactionStatus;
  dmaCallbackCount++;
  dmaComplete = true;
}

extern "C" void am_iomaster0_isr(void) {
  if (iomHandle == nullptr) return;
  uint32_t status = 0;
  am_hal_iom_interrupt_status_get(iomHandle, true, &status);
  am_hal_iom_interrupt_clear(iomHandle, status);
  am_hal_iom_interrupt_service(iomHandle, status);
}

bool iomTransferBlocking(am_hal_iom_dir_e direction, uint8_t* data,
                         uint32_t length) {
  am_hal_iom_transfer_t transaction = {};
  transaction.uPeerInfo.ui32SpiChipSelect = 0;
  transaction.ui32NumBytes = length;
  transaction.eDirection = direction;
  transaction.pui32TxBuffer = direction == AM_HAL_IOM_TX
      ? reinterpret_cast<uint32_t*>(data) : nullptr;
  transaction.pui32RxBuffer = direction == AM_HAL_IOM_RX
      ? reinterpret_cast<uint32_t*>(data) : nullptr;
  transaction.ui8Priority = 1;
  return am_hal_iom_blocking_transfer(iomHandle, &transaction) == AM_HAL_STATUS_SUCCESS;
}

bool spiSendByte(uint8_t value) {
  ioByteBuffer[0] = value;
  return iomTransferBlocking(AM_HAL_IOM_TX, ioByteBuffer, 1);
}

bool spiReceiveByte(uint8_t* value) {
  // On Apollo3 the HAL's SPI RX command generates master clocks while filling
  // the RX FIFO. Do not call the full-duplex helper here: it waits for queued
  // nonblocking transactions while the IOM CQ may still hold completed state,
  // which deadlocked the very first DMA submission in the previous revision.
  ioByteBuffer[0] = 0xFF;
  if (!iomTransferBlocking(AM_HAL_IOM_RX, ioByteBuffer, 1)) return false;
  *value = ioByteBuffer[0];
  return true;
}

// A write data-response token is 0bXXX00101, but cards are allowed to hold MISO
// high for one or more fill bytes before presenting it. Poll for the first
// non-0xFF byte instead of assuming the response follows immediately.
bool readDataResponse(uint8_t* response, uint32_t timeoutUs) {
  uint32_t startUs = micros();
  responseTraceCount = 0;
  do {
    if (!spiReceiveByte(response)) return false;
    if (responseTraceCount < RESPONSE_TRACE_BYTES) {
      responseTrace[responseTraceCount++] = *response;
    }
    if (*response != 0xFF) return true;
  } while (micros() - startUs < timeoutUs);
  return false;
}

bool waitCardReady(uint32_t timeoutUs) {
  uint32_t startUs = micros();
  uint8_t response = 0;
  do {
    if (!spiReceiveByte(&response)) return false;
    if (response == 0xFF) return true;
  } while (micros() - startUs < timeoutUs);
  return false;
}

bool sendCardCommand(uint8_t command, uint32_t argument, uint8_t* response) {
  if (!waitCardReady(300000UL)) return false;

  commandBuffer[0] = command | 0x40;
  commandBuffer[1] = uint8_t(argument >> 24);
  commandBuffer[2] = uint8_t(argument >> 16);
  commandBuffer[3] = uint8_t(argument >> 8);
  commandBuffer[4] = uint8_t(argument);
  commandBuffer[5] = 0xFF;  // CRC disabled after card initialization
  if (!iomTransferBlocking(AM_HAL_IOM_TX, commandBuffer, 6)) return false;

  for (uint8_t attempt = 0; attempt < 10; ++attempt) {
    if (!spiReceiveByte(response)) return false;
    if ((*response & 0x80) == 0) return true;
  }
  return false;
}

bool startMultiBlockWrite(uint32_t firstBlock, uint32_t blockCount,
                          bool highCapacityCard) {
  uint8_t response = 0xFF;
  digitalWrite(CS_SD, LOW);

  if (!sendCardCommand(CMD55, 0, &response) || response > 1) return false;
  if (!sendCardCommand(ACMD23, blockCount, &response) || response != 0) return false;

  uint32_t address = highCapacityCard ? firstBlock : firstBlock << 9;
  return sendCardCommand(CMD25, address, &response) && response == 0;
}

bool submitQueuedTransfer(am_hal_iom_dir_e direction, uint8_t* buffer,
                          uint32_t length, uint32_t* submitUs,
                          uint32_t* elapsedUs) {
  am_hal_iom_transfer_t transaction = {};
  transaction.uPeerInfo.ui32SpiChipSelect = 0;
  transaction.ui32NumBytes = length;
  transaction.eDirection = direction;
  transaction.pui32TxBuffer = direction == AM_HAL_IOM_TX
      ? reinterpret_cast<uint32_t*>(buffer) : nullptr;
  transaction.pui32RxBuffer = direction == AM_HAL_IOM_RX
      ? reinterpret_cast<uint32_t*>(buffer) : nullptr;
  transaction.bContinue = false;
  transaction.ui8Priority = 1;

  dmaComplete = false;
  dmaCompletionStatus = AM_HAL_STATUS_FAIL;
  uint32_t startUs = micros();
  uint32_t submitStartUs = micros();
  uint32_t status = am_hal_iom_nonblocking_transfer(
      iomHandle, &transaction, dmaCallback, nullptr);
  if (submitUs) *submitUs = micros() - submitStartUs;
  if (status != AM_HAL_STATUS_SUCCESS) return false;

  while (!dmaComplete && micros() - startUs < DMA_TIMEOUT_US) {
    // Deliberately leave the CPU free to make progress while IOM DMA runs.
  }
  if (elapsedUs) *elapsedUs = micros() - startUs;
  return dmaComplete && dmaCompletionStatus == AM_HAL_STATUS_SUCCESS;
}

bool queuedReadResponseAndReady(uint32_t timeoutUs, uint32_t* elapsedUs) {
  uint32_t startUs = micros();
  bool responseAccepted = false;
  responseTraceCount = 0;

  while (micros() - startUs < timeoutUs) {
    memset(responseWindow, 0xFF, sizeof(responseWindow));
    if (!submitQueuedTransfer(AM_HAL_IOM_RX, responseWindow,
                              RESPONSE_WINDOW_BYTES, nullptr, nullptr)) {
      return false;
    }

    for (uint32_t i = 0; i < RESPONSE_WINDOW_BYTES; ++i) {
      uint8_t value = responseWindow[i];
      if (responseTraceCount < RESPONSE_TRACE_BYTES) {
        responseTrace[responseTraceCount++] = value;
      }

      if (!responseAccepted) {
        if (value == 0xFF) continue;  // fill byte before data response
        if ((value & DATA_RESPONSE_MASK) != DATA_RESPONSE_ACCEPTED) {
          return false;
        }
        responseAccepted = true;
      } else if (value == 0xFF) {
        if (elapsedUs) *elapsedUs = micros() - startUs;
        return true;                 // card has finished programming
      }
    }
  }
  return false;
}

bool queuedStopMultiBlockWrite() {
  stopTokenBuffer[0] = STOP_TRAN_TOKEN;
  if (!submitQueuedTransfer(AM_HAL_IOM_TX, stopTokenBuffer, 1,
                            nullptr, nullptr)) {
    return false;
  }

  // STOP_TRAN_TOKEN has no data-response token; poll only for ready. RX windows
  // are still nonblocking CQ transactions, so no blocking API enters the stream.
  uint32_t startUs = micros();
  while (micros() - startUs < CARD_BUSY_TIMEOUT_US) {
    memset(responseWindow, 0xFF, sizeof(responseWindow));
    if (!submitQueuedTransfer(AM_HAL_IOM_RX, responseWindow,
                              RESPONSE_WINDOW_BYTES, nullptr, nullptr)) {
      return false;
    }
    for (uint32_t i = 0; i < RESPONSE_WINDOW_BYTES; ++i) {
      if (responseWindow[i] == 0xFF) {
        digitalWrite(CS_SD, HIGH);
        return true;
      }
    }
  }
  return false;
}

bool configureDmaIom() {
  // Sd2Card initialized the normal SPI pins. SPI.end() releases IOM0 but leaves
  // those pin mux settings in place, so this benchmark can take ownership of
  // the same hardware without reaching into SPIClass's protected handle.
  am_hal_iom_config_t config = {};
  config.eInterfaceMode = AM_HAL_IOM_SPI_MODE;
  config.ui32ClockFreq = SPI_CLOCK_HZ;
  config.eSpiMode = AM_HAL_IOM_SPI_MODE_0;
  config.pNBTxnBuf = nonblockingTransactionBuffer;
  config.ui32NBTxnBufLength =
      sizeof(nonblockingTransactionBuffer) / sizeof(uint32_t);

  if (am_hal_iom_initialize(SPI_IOM_MODULE, &iomHandle) != AM_HAL_STATUS_SUCCESS) return false;
  if (am_hal_iom_power_ctrl(iomHandle, AM_HAL_SYSCTRL_WAKE, false) != AM_HAL_STATUS_SUCCESS) return false;
  if (am_hal_iom_configure(iomHandle, &config) != AM_HAL_STATUS_SUCCESS) return false;
  if (am_hal_iom_enable(iomHandle) != AM_HAL_STATUS_SUCCESS) return false;

  NVIC_ClearPendingIRQ(IOMSTR0_IRQn);
  NVIC_EnableIRQ(IOMSTR0_IRQn);
  return true;
}

void releaseIom() {
  NVIC_DisableIRQ(IOMSTR0_IRQn);
  if (iomHandle != nullptr) {
    am_hal_iom_disable(iomHandle);
    am_hal_iom_power_ctrl(iomHandle, AM_HAL_SYSCTRL_DEEPSLEEP, false);
    am_hal_iom_uninitialize(iomHandle);
    iomHandle = nullptr;
  }
}

bool initializeDmaIom() {
  // Sd2Card initialized the normal SPI pins. SPI.end() releases IOM0 but leaves
  // those pin mux settings in place.
  SPI.end();
  return configureDmaIom();
}

void shutdownDmaIom() {
  releaseIom();
  digitalWrite(CS_SD, HIGH);
}

bool verifyFile(uint32_t* elapsedUs) {
  if (!card.init(SPI_HALF_SPEED, CS_SD)) return false;
  if (!volume.init(&card)) return false;
  if (!root.openRoot(&volume)) return false;

  SdFile file;
  if (!file.open(&root, dmaFileName, O_READ)) return false;
  uint32_t startUs = micros();
  for (uint32_t sector = 0; sector < BENCHMARK_SECTORS; ++sector) {
    if (file.read(verifyBuffer, SECTOR_BYTES) != int16_t(SECTOR_BYTES)) {
      Serial.print("ERROR verify read sector="); Serial.println(sector);
      file.close();
      return false;
    }
    uint16_t mismatchOffset = 0;
    if (!patternMatches(verifyBuffer, sector, &mismatchOffset)) {
      Serial.print("ERROR verify mismatch sector="); Serial.print(sector);
      Serial.print(" byte="); Serial.println(mismatchOffset);
      file.close();
      return false;
    }
  }
  *elapsedUs = micros() - startUs;
  return file.close();
}

void haltWithError(const char* message) {
  digitalWrite(CS_SD, HIGH);
  Serial.print("FATAL "); Serial.println(message);
  while (true) delay(1000);
}

void setup() {
  Serial.begin(115200);
  uint32_t serialStart = millis();
  while (!Serial && millis() - serialStart < SERIAL_WAIT_MS) delay(10);
  delay(100);

  Serial.println();
  Serial.println("VertiSea SD Phase 3 IOM DMA Benchmark");
  Serial.print("sectors="); Serial.print(BENCHMARK_SECTORS);
  Serial.print(" bytes="); Serial.println(BENCHMARK_SECTORS * SECTOR_BYTES);
  Serial.print("iom=0 spi_hz=4000000 mode=0 frame_dma_bytes=515 cq_only_after_cmd25=1 response_window=");
  Serial.println(RESPONSE_WINDOW_BYTES);

  pinMode(CS_SD, OUTPUT);
  digitalWrite(CS_SD, HIGH);
  if (!card.init(SPI_HALF_SPEED, CS_SD)) haltWithError("card.init failed");
  bool highCapacityCard = card.type() == SD_CARD_TYPE_SDHC;
  if (!volume.init(&card)) haltWithError("volume.init failed");
  if (!root.openRoot(&volume)) haltWithError("root.openRoot failed");
  if (!chooseUnusedName()) haltWithError("no unused P3 filename remains");

  SdFile file;
  const uint32_t fileBytes = BENCHMARK_SECTORS * SECTOR_BYTES;
  if (!file.createContiguous(&root, dmaFileName, fileBytes)) {
    haltWithError("createContiguous failed");
  }
  uint32_t firstBlock = 0;
  uint32_t lastBlock = 0;
  if (!file.contiguousRange(&firstBlock, &lastBlock) ||
      lastBlock - firstBlock + 1 != BENCHMARK_SECTORS) {
    haltWithError("contiguousRange invalid");
  }
  if (!file.close() || !root.close()) haltWithError("preallocation close failed");

  Serial.print("file="); Serial.print(dmaFileName);
  Serial.print(" first_block="); Serial.print(firstBlock);
  Serial.print(" last_block="); Serial.print(lastBlock);
  Serial.print(" sdhc="); Serial.println(highCapacityCard);

  if (!initializeDmaIom()) haltWithError("DMA IOM initialization failed");
  if (!startMultiBlockWrite(firstBlock, BENCHMARK_SECTORS, highCapacityCard)) {
    haltWithError("CMD25 start failed");
  }

  Serial.println("BEGIN DMA");
  uint32_t totalStartUs = micros();
  bool wrote = true;
  uint32_t completedSectors = 0;
  for (uint32_t sector = 0; sector < BENCHMARK_SECTORS; ++sector) {
    // Keep the complete SD data frame in one IOM transaction. Earlier versions
    // alternated blocking token/CRC calls with a 512-byte DMA payload; that
    // crossed HAL blocking/nonblocking state boundaries while CS was asserted
    // and corrupted sector 5. One DMA now owns token through CRC continuously.
    dmaFrameBuffer[0] = WRITE_MULTIPLE_TOKEN;
    fillPattern(dmaFrameBuffer + 1, sector);
    dmaFrameBuffer[1 + SECTOR_BYTES] = 0xFF;
    dmaFrameBuffer[1 + SECTOR_BYTES + 1] = 0xFF;

    if (!submitQueuedTransfer(AM_HAL_IOM_TX, dmaFrameBuffer, DMA_FRAME_BYTES,
                              &dmaSubmitUs[sector], &dmaElapsedUs[sector])) {
      Serial.print("ERROR DMA submit sector="); Serial.println(sector);
      wrote = false;
      break;
    }
    cpuSpinCounts[sector] = 0;  // legacy output slot; CQ callbacks prove completion

    uint32_t responseStartUs = micros();
    if (!queuedReadResponseAndReady(CARD_BUSY_TIMEOUT_US,
                                    &cardBusyUs[sector])) {
      Serial.print("ERROR CQ response/busy sector="); Serial.println(sector);
      Serial.print("response_trace=");
      for (uint8_t i = 0; i < responseTraceCount; ++i) {
        if (i) Serial.print(',');
        if (responseTrace[i] < 0x10) Serial.print('0');
        Serial.print(responseTrace[i], HEX);
      }
      Serial.println();
      wrote = false;
      break;
    }
    responseUs[sector] = micros() - responseStartUs;
    completedSectors++;
  }

  // Always terminate a stream that reached CMD25, even after a sector error.
  // Leaving CS low without STOP_TRAN_TOKEN can keep the card in receive state
  // and make the subsequent FAT reinitialization fail.
  bool stopped = queuedStopMultiBlockWrite();
  uint32_t totalUs = micros() - totalStartUs;
  shutdownDmaIom();

  uint32_t verifyUs = 0;
  bool verified = wrote && stopped && verifyFile(&verifyUs);
  const uint32_t bytes = completedSectors * SECTOR_BYTES;
  uint32_t kibPerSec = totalUs
      ? uint32_t((uint64_t(bytes) * 1000000ULL) / totalUs / 1024ULL)
      : 0;

  Serial.print("RESULT TEST test=DMA file="); Serial.print(dmaFileName);
  Serial.print(" wrote="); Serial.print(wrote);
  Serial.print(" stopped="); Serial.print(stopped);
  Serial.print(" verified="); Serial.print(verified);
  Serial.print(" completed_sectors="); Serial.print(completedSectors);
  Serial.print(" total_us="); Serial.print(totalUs);
  Serial.print(" kib_per_s="); Serial.print(kibPerSec);
  Serial.print(" verify_us="); Serial.println(verifyUs);
  Serial.print("RESULT CALLBACKS count="); Serial.println(dmaCallbackCount);

  if (completedSectors > 0) {
    printLatencySummary("DMA_SUBMIT", dmaSubmitUs, completedSectors);
    printLatencySummary("DMA_ELAPSED", dmaElapsedUs, completedSectors);
    printLatencySummary("CARD_BUSY", cardBusyUs, completedSectors);
    printLatencySummary("DATA_RESPONSE", responseUs, completedSectors);
    printLatencySummary("CPU_SPINS", cpuSpinCounts, completedSectors);
  }

  bool allPassed = wrote && stopped && verified;
  Serial.print("RESULT COMPLETE all_passed="); Serial.println(allPassed);
  Serial.println("Save this complete output before resetting the board.");
}

void loop() {
  delay(1000);
}