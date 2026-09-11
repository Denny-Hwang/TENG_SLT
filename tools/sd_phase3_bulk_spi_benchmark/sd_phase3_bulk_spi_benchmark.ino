// =============================================================================
// VertiSea SD Phase 3B — Bulk SPI Payload Benchmark
// =============================================================================
//
// PURPOSE
// -------
// Test the lowest-risk fix exposed by Phase 2/3 measurements: keep Arduino SPI
// ownership and the proven SD CMD25 sequence, but send each 512-byte payload in
// thirty-two TX-FIFO-sized SPI.transferOut() calls instead of 512 byte calls.
//
// This is intentionally blocking. Both 512-byte and 32-byte transferOut() calls
// timed out in Apollo3 core 1.2.1's blocking HAL refill loop. The IOM has 32
// bytes total FIFO storage, split into 16-byte TX/RX halves in this SPI setup.
// Limiting each TX transaction to 16 bytes avoids the refill path while still
// cutting HAL calls 16x.
//
// SAFETY
// ------
// Creates a new P3Bnn.BIN file, never overwrites, and writes 2 MiB. This is an
// isolated benchmark, not deployment firmware. Do not remove card/power after
// BEGIN BULK. RESULT COMPLETE all_passed=1 is mandatory.

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>

#include <stdlib.h>

constexpr uint8_t CS_SD = 4;
constexpr uint32_t SPI_CLOCK_HZ = 4000000UL;
constexpr uint32_t SECTOR_BYTES = 512;
constexpr uint32_t BULK_CHUNK_BYTES = AM_HAL_IOM_FIFO_SIZE_MAX / 2;  // 16-byte TX half
constexpr uint32_t BENCHMARK_SECTORS = 4096;
constexpr uint32_t CARD_TIMEOUT_US = 2000000UL;
constexpr uint32_t SERIAL_WAIT_MS = 10000UL;

Sd2Card card;
SdVolume volume;
SdFile root;

alignas(4) uint8_t sectorBuffer[SECTOR_BYTES];
alignas(4) uint8_t verifyBuffer[SECTOR_BYTES];
alignas(4) uint8_t commandBuffer[8];

uint32_t payloadUs[BENCHMARK_SECTORS];
uint32_t busyUs[BENCHMARK_SECTORS];
uint32_t responseUs[BENCHMARK_SECTORS];
char outputName[13];

int compareUint32(const void* lhs, const void* rhs) {
  uint32_t a = *static_cast<const uint32_t*>(lhs);
  uint32_t b = *static_cast<const uint32_t*>(rhs);
  return (a > b) - (a < b);
}

void fillPattern(uint8_t* destination, uint32_t sectorIndex) {
  constexpr uint8_t TAG = 0xB3;
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
    snprintf(outputName, sizeof(outputName), "P3B%02u.BIN", run);
    if (!fileExists(outputName)) return true;
  }
  return false;
}

uint32_t percentileFromSorted(const uint32_t* sorted, uint32_t count,
                              uint32_t numerator, uint32_t denominator) {
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

uint8_t spiReceive() {
  return SPI.transfer(0xFF);
}

bool waitReady(uint32_t timeoutUs) {
  uint32_t startUs = micros();
  do {
    if (spiReceive() == 0xFF) return true;
  } while (micros() - startUs < timeoutUs);
  return false;
}

bool sendCommand(uint8_t command, uint32_t argument, uint8_t* response) {
  if (!waitReady(300000UL)) return false;
  commandBuffer[0] = command | 0x40;
  commandBuffer[1] = uint8_t(argument >> 24);
  commandBuffer[2] = uint8_t(argument >> 16);
  commandBuffer[3] = uint8_t(argument >> 8);
  commandBuffer[4] = uint8_t(argument);
  commandBuffer[5] = 0xFF;
  SPI.transferOut(commandBuffer, 6);
  for (uint8_t attempt = 0; attempt < 10; ++attempt) {
    *response = spiReceive();
    if ((*response & 0x80) == 0) return true;
  }
  return false;
}

bool startMultiBlock(uint32_t firstBlock, uint32_t blockCount, bool sdhc) {
  uint8_t response = 0xFF;
  digitalWrite(CS_SD, LOW);
  if (!sendCommand(CMD55, 0, &response) || response > 1) return false;
  if (!sendCommand(ACMD23, blockCount, &response) || response != 0) return false;
  uint32_t address = sdhc ? firstBlock : firstBlock << 9;
  return sendCommand(CMD25, address, &response) && response == 0;
}

bool writeSector(uint32_t sectorIndex, uint8_t* response) {
  uint32_t busyStart = micros();
  if (!waitReady(CARD_TIMEOUT_US)) return false;
  busyUs[sectorIndex] = micros() - busyStart;

  SPI.transfer(WRITE_MULTIPLE_TOKEN);
  fillPattern(sectorBuffer, sectorIndex);
  uint32_t payloadStart = micros();
  for (uint32_t offset = 0; offset < SECTOR_BYTES;
       offset += BULK_CHUNK_BYTES) {
    SPI.transferOut(sectorBuffer + offset, BULK_CHUNK_BYTES);
  }
  payloadUs[sectorIndex] = micros() - payloadStart;

  uint32_t responseStart = micros();
  SPI.transfer(0xFF);
  SPI.transfer(0xFF);
  *response = spiReceive();
  responseUs[sectorIndex] = micros() - responseStart;
  return (*response & DATA_RES_MASK) == DATA_RES_ACCEPTED;
}

bool stopMultiBlock() {
  if (!waitReady(CARD_TIMEOUT_US)) return false;
  SPI.transfer(STOP_TRAN_TOKEN);
  if (!waitReady(CARD_TIMEOUT_US)) return false;
  digitalWrite(CS_SD, HIGH);
  SPI.endTransaction();
  return true;
}

void abortMultiBlockWithoutMoreSpi() {
  // A HAL timeout leaves IOM0 unable to complete further blocking calls. Do
  // not attempt STOP_TRAN_TOKEN or busy polling in that state: each call would
  // wait for another timeout and flood Serial. Deassert CS and end ownership;
  // the benchmark is already failed and the card is power-cycled before reuse.
  digitalWrite(CS_SD, HIGH);
  SPI.endTransaction();
}

bool verifyFile(uint32_t* verifyUs) {
  if (!card.init(SPI_HALF_SPEED, CS_SD)) return false;
  if (!volume.init(&card)) return false;
  if (!root.openRoot(&volume)) return false;
  SdFile file;
  if (!file.open(&root, outputName, O_READ)) return false;
  uint32_t startUs = micros();
  for (uint32_t sector = 0; sector < BENCHMARK_SECTORS; ++sector) {
    if (file.read(verifyBuffer, SECTOR_BYTES) != int16_t(SECTOR_BYTES)) return false;
    uint16_t mismatch = 0;
    if (!patternMatches(verifyBuffer, sector, &mismatch)) {
      Serial.print("ERROR verify sector="); Serial.print(sector);
      Serial.print(" byte="); Serial.println(mismatch);
      return false;
    }
  }
  *verifyUs = micros() - startUs;
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
  Serial.println("VertiSea SD Phase 3B Bulk SPI Benchmark");
  Serial.print("sectors="); Serial.print(BENCHMARK_SECTORS);
  Serial.print(" bytes="); Serial.println(BENCHMARK_SECTORS * SECTOR_BYTES);
  Serial.print("spi_hz=4000000 payload_chunks=");
  Serial.print(SECTOR_BYTES / BULK_CHUNK_BYTES);
  Serial.print(" chunk_bytes="); Serial.println(BULK_CHUNK_BYTES);

  if (!card.init(SPI_HALF_SPEED, CS_SD)) haltWithError("card.init failed");
  bool sdhc = card.type() == SD_CARD_TYPE_SDHC;
  if (!volume.init(&card)) haltWithError("volume.init failed");
  if (!root.openRoot(&volume)) haltWithError("root.openRoot failed");
  if (!chooseUnusedName()) haltWithError("no unused filename");

  SdFile file;
  if (!file.createContiguous(&root, outputName,
                             BENCHMARK_SECTORS * SECTOR_BYTES)) {
    haltWithError("createContiguous failed");
  }
  uint32_t firstBlock = 0;
  uint32_t lastBlock = 0;
  if (!file.contiguousRange(&firstBlock, &lastBlock) ||
      lastBlock - firstBlock + 1 != BENCHMARK_SECTORS) {
    haltWithError("contiguousRange invalid");
  }
  if (!file.close() || !root.close()) haltWithError("close failed");

  SPI.beginTransaction(SPISettings(SPI_CLOCK_HZ, MSBFIRST, SPI_MODE0));
  if (!startMultiBlock(firstBlock, BENCHMARK_SECTORS, sdhc)) {
    haltWithError("CMD25 start failed");
  }

  Serial.print("file="); Serial.print(outputName);
  Serial.print(" first_block="); Serial.print(firstBlock);
  Serial.print(" last_block="); Serial.println(lastBlock);
  Serial.println("BEGIN BULK");

  bool wrote = true;
  uint32_t completed = 0;
  uint32_t totalStartUs = micros();
  for (uint32_t sector = 0; sector < BENCHMARK_SECTORS; ++sector) {
    uint8_t response = 0xFF;
    if (!writeSector(sector, &response)) {
      Serial.print("ERROR write sector="); Serial.print(sector);
      Serial.print(" response=0x"); Serial.println(response, HEX);
      wrote = false;
      break;
    }
    completed++;
  }
  bool stopped = false;
  if (wrote) {
    stopped = stopMultiBlock();
  } else {
    abortMultiBlockWithoutMoreSpi();
  }
  uint32_t totalUs = micros() - totalStartUs;

  uint32_t verifyUs = 0;
  bool verified = wrote && stopped && verifyFile(&verifyUs);
  uint32_t kibPerSec = totalUs
      ? uint32_t((uint64_t(completed) * SECTOR_BYTES * 1000000ULL) /
                 totalUs / 1024ULL)
      : 0;

  Serial.print("RESULT TEST test=BULK wrote="); Serial.print(wrote);
  Serial.print(" stopped="); Serial.print(stopped);
  Serial.print(" verified="); Serial.print(verified);
  Serial.print(" completed_sectors="); Serial.print(completed);
  Serial.print(" total_us="); Serial.print(totalUs);
  Serial.print(" kib_per_s="); Serial.print(kibPerSec);
  Serial.print(" verify_us="); Serial.println(verifyUs);
  if (completed) {
    printLatencySummary("BULK_PAYLOAD", payloadUs, completed);
    printLatencySummary("CARD_BUSY", busyUs, completed);
    printLatencySummary("DATA_RESPONSE", responseUs, completed);
  }
  Serial.print("RESULT COMPLETE all_passed=");
  Serial.println(wrote && stopped && verified);
}

void loop() {
  delay(1000);
}