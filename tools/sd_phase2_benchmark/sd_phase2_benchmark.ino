// =============================================================================
// VertiSea SD Phase 2 Benchmark
// =============================================================================
//
// PURPOSE
// -------
// Isolate the remaining SD latency before attempting an Apollo3 IOM/DMA driver.
// This sketch compares, on the same card and at the production SPI setting:
//
//   DYNAMIC  - normal FAT growth, 512-byte File/SdFile writes
//   CONTIG   - preallocated contiguous file, nonblocking CMD24 sector writes
//   MULTI    - preallocated contiguous file, raw CMD25 multi-block sequence
//
// CONTIG separately measures command+SPI-payload submission and card-internal
// busy time. If busy time dominates, DMA can free CPU time but cannot remove the
// latency tail. If submission time is material, IOM DMA has a stronger case.
//
// SAFETY
// ------
// The sketch finds an unused P2Dnn/P2Cnn/P2Mnn filename set and never overwrites
// an existing file. It writes 3 * BENCHMARK_SECTORS * 512 bytes. The default is
// 6 MiB total. Do not remove the card or power down while a test is in progress.
// This is a storage benchmark, not buoy firmware; do not deploy it.
//
// SERIAL OUTPUT
// -------------
// Open the Serial Monitor at 115200 baud and save the complete output. RESULT
// lines contain the summaries needed for the Phase 2 decision.

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>  // Arduino SD 1.3.0; exposes its underlying SdFat classes

#include <stdlib.h>
#include <string.h>

constexpr uint8_t  CS_SD = 4;
constexpr uint32_t SECTOR_BYTES = 512;
constexpr uint32_t BENCHMARK_SECTORS = 4096;  // 2 MiB per test, 6 MiB total
constexpr uint32_t CARD_BUSY_TIMEOUT_US = 2000000UL;
constexpr uint32_t SERIAL_WAIT_MS = 10000UL;

// Match VertiSea's SD.begin(CS_SD) production setting. In Arduino SD 1.3.0 the
// single-argument overload selects SPI_HALF_SPEED, which maps to 4 MHz here.
constexpr uint8_t SD_SCK_RATE = SPI_HALF_SPEED;

Sd2Card card;
SdVolume volume;
SdFile root;

alignas(4) uint8_t sectorBuffer[SECTOR_BYTES];
alignas(4) uint8_t verifyBuffer[SECTOR_BYTES];

uint32_t dynamicWriteUs[BENCHMARK_SECTORS];
uint32_t contiguousSubmitUs[BENCHMARK_SECTORS];
uint32_t contiguousBusyUs[BENCHMARK_SECTORS];
uint32_t multiCallUs[BENCHMARK_SECTORS];

char dynamicName[13];
char contiguousName[13];
char multiName[13];

struct TestResult {
  bool created;
  bool wrote;
  bool synced;
  bool verified;
  uint32_t totalUs;
  uint32_t syncUs;
  uint32_t verifyUs;
  uint32_t firstBlock;
  uint32_t lastBlock;
};

int compareUint32(const void* lhs, const void* rhs) {
  uint32_t a = *static_cast<const uint32_t*>(lhs);
  uint32_t b = *static_cast<const uint32_t*>(rhs);
  return (a > b) - (a < b);
}

void fillPattern(uint8_t* destination, uint32_t sectorIndex, uint8_t tag) {
  for (uint32_t i = 0; i < SECTOR_BYTES; ++i) {
    destination[i] = uint8_t(tag * 73U + sectorIndex * 29U +
                             i * 17U + (sectorIndex >> 8));
  }
  // Make the sector index and test identity obvious in a hex dump too.
  destination[0] = uint8_t(sectorIndex);
  destination[1] = uint8_t(sectorIndex >> 8);
  destination[2] = uint8_t(sectorIndex >> 16);
  destination[3] = uint8_t(sectorIndex >> 24);
  destination[4] = tag;
}

bool patternMatches(const uint8_t* actual, uint32_t sectorIndex, uint8_t tag,
                    uint16_t* mismatchOffset) {
  fillPattern(sectorBuffer, sectorIndex, tag);
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

bool chooseUnusedNames() {
  for (uint8_t run = 0; run < 100; ++run) {
    snprintf(dynamicName, sizeof(dynamicName), "P2D%02u.BIN", run);
    snprintf(contiguousName, sizeof(contiguousName), "P2C%02u.BIN", run);
    snprintf(multiName, sizeof(multiName), "P2M%02u.BIN", run);
    if (!fileExists(dynamicName) && !fileExists(contiguousName) &&
        !fileExists(multiName)) {
      return true;
    }
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

void printTestResult(const char* label, const char* name, const TestResult& result) {
  const uint32_t bytes = BENCHMARK_SECTORS * SECTOR_BYTES;
  uint32_t kibPerSec = result.totalUs
      ? uint32_t((uint64_t(bytes) * 1000000ULL) / result.totalUs / 1024ULL)
      : 0;
  Serial.print("RESULT TEST test="); Serial.print(label);
  Serial.print(" file="); Serial.print(name);
  Serial.print(" created="); Serial.print(result.created);
  Serial.print(" wrote="); Serial.print(result.wrote);
  Serial.print(" synced="); Serial.print(result.synced);
  Serial.print(" verified="); Serial.print(result.verified);
  Serial.print(" total_us="); Serial.print(result.totalUs);
  Serial.print(" kib_per_s="); Serial.print(kibPerSec);
  Serial.print(" sync_us="); Serial.print(result.syncUs);
  Serial.print(" verify_us="); Serial.print(result.verifyUs);
  Serial.print(" first_block="); Serial.print(result.firstBlock);
  Serial.print(" last_block="); Serial.println(result.lastBlock);
}

bool verifyFileByFilesystem(const char* name, uint8_t tag, uint32_t* elapsedUs) {
  SdFile file;
  if (!file.open(&root, name, O_READ)) return false;
  uint32_t startUs = micros();
  for (uint32_t sector = 0; sector < BENCHMARK_SECTORS; ++sector) {
    if (file.read(verifyBuffer, SECTOR_BYTES) != int16_t(SECTOR_BYTES)) {
      Serial.print("ERROR verify read failed file="); Serial.print(name);
      Serial.print(" sector="); Serial.println(sector);
      file.close();
      return false;
    }
    uint16_t mismatchOffset = 0;
    if (!patternMatches(verifyBuffer, sector, tag, &mismatchOffset)) {
      Serial.print("ERROR verify mismatch file="); Serial.print(name);
      Serial.print(" sector="); Serial.print(sector);
      Serial.print(" byte="); Serial.println(mismatchOffset);
      file.close();
      return false;
    }
  }
  *elapsedUs = micros() - startUs;
  return file.close();
}

TestResult runDynamicTest() {
  constexpr uint8_t TAG = 0xD1;
  TestResult result = {};
  SdFile file;
  result.created = file.open(&root, dynamicName, O_CREAT | O_EXCL | O_WRITE);
  if (!result.created) return result;

  Serial.println("BEGIN DYNAMIC");
  uint32_t totalStartUs = micros();
  result.wrote = true;
  for (uint32_t sector = 0; sector < BENCHMARK_SECTORS; ++sector) {
    fillPattern(sectorBuffer, sector, TAG);
    uint32_t startUs = micros();
    size_t written = file.write(sectorBuffer, SECTOR_BYTES);
    dynamicWriteUs[sector] = micros() - startUs;
    if (written != SECTOR_BYTES) {
      Serial.print("ERROR dynamic write failed sector="); Serial.println(sector);
      result.wrote = false;
      break;
    }
  }
  result.totalUs = micros() - totalStartUs;
  uint32_t syncStartUs = micros();
  result.synced = file.sync();
  result.syncUs = micros() - syncStartUs;
  if (!file.close()) result.synced = false;
  if (result.wrote && result.synced) {
    result.verified = verifyFileByFilesystem(dynamicName, TAG, &result.verifyUs);
  }
  return result;
}

TestResult runContiguousSingleTest() {
  constexpr uint8_t TAG = 0xC2;
  TestResult result = {};
  SdFile file;
  const uint32_t fileBytes = BENCHMARK_SECTORS * SECTOR_BYTES;
  result.created = file.createContiguous(&root, contiguousName, fileBytes);
  if (!result.created) return result;
  if (!file.contiguousRange(&result.firstBlock, &result.lastBlock) ||
      result.lastBlock - result.firstBlock + 1 != BENCHMARK_SECTORS) {
    Serial.println("ERROR contiguous range invalid");
    file.close();
    return result;
  }
  if (!file.seekSet(0)) {
    file.close();
    return result;
  }

  Serial.println("BEGIN CONTIG");
  uint32_t totalStartUs = micros();
  result.wrote = true;
  for (uint32_t sector = 0; sector < BENCHMARK_SECTORS; ++sector) {
    // availableForWrite() waits for the previous card program operation and
    // switches the next full-sector write to the library's nonblocking path.
    uint32_t waitStartUs = micros();
    while (file.availableForWrite() < int(SECTOR_BYTES)) {
      if (micros() - waitStartUs > CARD_BUSY_TIMEOUT_US) {
        Serial.print("ERROR availableForWrite timeout sector="); Serial.println(sector);
        result.wrote = false;
        break;
      }
    }
    if (!result.wrote) break;

    fillPattern(sectorBuffer, sector, TAG);
    uint32_t submitStartUs = micros();
    size_t written = file.write(sectorBuffer, SECTOR_BYTES);
    contiguousSubmitUs[sector] = micros() - submitStartUs;
    if (written != SECTOR_BYTES) {
      Serial.print("ERROR contiguous write failed sector="); Serial.println(sector);
      result.wrote = false;
      break;
    }

    uint32_t busyStartUs = micros();
    while (card.isBusy()) {
      if (micros() - busyStartUs > CARD_BUSY_TIMEOUT_US) {
        Serial.print("ERROR card busy timeout sector="); Serial.println(sector);
        result.wrote = false;
        break;
      }
    }
    contiguousBusyUs[sector] = micros() - busyStartUs;
    if (!result.wrote) break;
  }
  result.totalUs = micros() - totalStartUs;
  uint32_t syncStartUs = micros();
  result.synced = file.sync();
  result.syncUs = micros() - syncStartUs;
  if (!file.close()) result.synced = false;
  if (result.wrote && result.synced) {
    result.verified = verifyFileByFilesystem(contiguousName, TAG, &result.verifyUs);
  }
  return result;
}

TestResult runMultiBlockTest() {
  constexpr uint8_t TAG = 0xA3;
  TestResult result = {};
  SdFile file;
  const uint32_t fileBytes = BENCHMARK_SECTORS * SECTOR_BYTES;
  result.created = file.createContiguous(&root, multiName, fileBytes);
  if (!result.created) return result;
  if (!file.contiguousRange(&result.firstBlock, &result.lastBlock) ||
      result.lastBlock - result.firstBlock + 1 != BENCHMARK_SECTORS) {
    Serial.println("ERROR multi range invalid");
    file.close();
    return result;
  }
  if (!file.close()) return result;

  Serial.println("BEGIN MULTI");
  uint32_t totalStartUs = micros();
  result.wrote = card.writeStart(result.firstBlock, BENCHMARK_SECTORS);
  if (result.wrote) {
    for (uint32_t sector = 0; sector < BENCHMARK_SECTORS; ++sector) {
      fillPattern(sectorBuffer, sector, TAG);
      uint32_t callStartUs = micros();
      bool ok = card.writeData(sectorBuffer);
      multiCallUs[sector] = micros() - callStartUs;
      if (!ok) {
        Serial.print("ERROR multi write failed sector="); Serial.println(sector);
        result.wrote = false;
        break;
      }
    }
  }
  bool stopped = result.wrote ? card.writeStop() : false;
  if (!stopped) result.wrote = false;
  result.totalUs = micros() - totalStartUs;
  result.synced = stopped;  // directory metadata was synced by createContiguous()
  if (result.wrote && result.synced) {
    // Reopen through FAT rather than verifying only raw LBAs. This checks the
    // preallocated directory entry and cluster mapping as well as payload bytes.
    result.verified = verifyFileByFilesystem(multiName, TAG, &result.verifyUs);
  }
  return result;
}

void haltWithError(const char* message) {
  Serial.print("FATAL "); Serial.println(message);
  while (true) delay(1000);
}

void setup() {
  Serial.begin(115200);
  uint32_t serialStart = millis();
  while (!Serial && millis() - serialStart < SERIAL_WAIT_MS) delay(10);
  delay(100);

  Serial.println();
  Serial.println("VertiSea SD Phase 2 Benchmark");
  Serial.print("sectors_per_test="); Serial.print(BENCHMARK_SECTORS);
  Serial.print(" bytes_per_test="); Serial.println(BENCHMARK_SECTORS * SECTOR_BYTES);
  Serial.println("spi_setting=SPI_HALF_SPEED (production SD 1.3.0 setting)");

  if (!card.init(SD_SCK_RATE, CS_SD)) haltWithError("card.init failed");
  if (!volume.init(&card)) haltWithError("volume.init failed");
  if (!root.openRoot(&volume)) haltWithError("root.openRoot failed");
  if (!chooseUnusedNames()) haltWithError("no unused P2 filename set remains");

  Serial.print("files dynamic="); Serial.print(dynamicName);
  Serial.print(" contiguous="); Serial.print(contiguousName);
  Serial.print(" multi="); Serial.println(multiName);

  TestResult dynamic = runDynamicTest();
  printTestResult("DYNAMIC", dynamicName, dynamic);
  if (dynamic.wrote) {
    printLatencySummary("DYNAMIC_WRITE", dynamicWriteUs, BENCHMARK_SECTORS);
  }

  TestResult contiguous = runContiguousSingleTest();
  printTestResult("CONTIG", contiguousName, contiguous);
  if (contiguous.wrote) {
    printLatencySummary("CONTIG_SUBMIT", contiguousSubmitUs, BENCHMARK_SECTORS);
    printLatencySummary("CONTIG_BUSY", contiguousBusyUs, BENCHMARK_SECTORS);
  }

  TestResult multi = runMultiBlockTest();
  printTestResult("MULTI", multiName, multi);
  if (multi.wrote) {
    printLatencySummary("MULTI_CALL", multiCallUs, BENCHMARK_SECTORS);
  }

  bool allPassed = dynamic.created && dynamic.wrote && dynamic.synced && dynamic.verified &&
                   contiguous.created && contiguous.wrote && contiguous.synced &&
                   contiguous.verified && multi.created && multi.wrote && multi.synced &&
                   multi.verified;
  Serial.print("RESULT COMPLETE all_passed="); Serial.println(allPassed);
  Serial.println("Save this complete serial output before resetting the board.");
}

void loop() {
  delay(1000);
}