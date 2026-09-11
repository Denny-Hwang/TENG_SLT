// =============================================================================
//  VertiSea Buoy Firmware
//  Pacific Northwest National Laboratory (PNNL) — Arctic TENG Project
// =============================================================================
//
//  PURPOSE
//  -------
//  Firmware for the VertiSea wave-energy buoy. Collects high-rate IMU data
//  (104 Hz), low-rate environmental data (BME280 at 1 Hz, GPS at 1 Hz), and
//  high-rate harvested current. All data are logged to a binary file on an
//  SD card and a subset is broadcast over a serial radio link (RFD900) for
//  real-time ground-station monitoring.
//
//  HARDWARE
//  --------
//  Microcontroller : SparkFun RedBoard Artemis Nano
//  Fixed IMU       : SparkFun ISM330DHCX (I²C addr 0x6A) — hull-fixed frame
//  Stabilized IMU  : SparkFun ISM330DHCX (I²C addr 0x6B) — gimballed frame
//  Magnetometer    : SparkFun MMC5983MA (I²C) — on stabilized platform
//  Barometer       : SparkFun BME280 (I²C)
//  GNSS            : u-blox module (I²C)
//  RTC             : SparkFun RV8803 (I²C)
//  SD card         : SPI, CS on pin 4
//  Current sense   : Current-sensor analog output on A14, wired directly
//                    (no resistor divider — sensor output stays below the
//                    Apollo3 ADC's 2.0 V internal reference; EE will add one
//                    only if clipping is observed)
//  Battery sense   : 1S LiFePO4 through a 98.7 kΩ / 98.9 kΩ divider (≈2:1)
//                    on A15; R_TOP is inline in the V+ lead, not on the board
//  Radio           : RFD900 on Serial1 (115200 baud)
//  NOTE: An Emlid M2 external GNSS was originally planned for Serial1 but was
//        never connected. Serial1 is used exclusively by the RFD900 modem.
//        The u-blox GNSS module (I²C) is the only GNSS source in use.
//
//  BINARY LOG FORMAT
//  -----------------
//  Every record starts with a 5-byte header:
//    [1 B type] [4 B uint32 timestamp_ms]
//  Followed by a type-specific payload. See docs/binary_protocol.md for the
//  full packet layout and field definitions.
//
//  Packet types (PacketType enum):
//    0x01  TYPE_FIXED_IMU   — nominal 104 Hz (~93 achieved), hull-fixed IMU
//    0x02  TYPE_STAB_IMU    — 104 Hz, stabilized IMU
//    0x03  TYPE_BME         — 1 Hz, pressure / humidity / temperature
//    0x04  TYPE_GPS         — 1 Hz, GNSS fix (lat/lon/alt/sats)
//    0x05  TYPE_RTC_EVENT   — once at boot, RTC timestamp
//    0x06  TYPE_TELEM_IMU   — 5 Hz radio packet (pitch/roll/vertDisp)
//    0x07  TYPE_MAG         — 104 Hz, calibrated magnetometer XYZ
//    0x08  TYPE_FIXED_CAL   — once at boot, fixed-IMU calibration constants
//    0x09  TYPE_STAB_CAL    — once at boot, stabilized-IMU calibration constants
//    0x0A  (RETIRED)        — was TYPE_CURRENT (5 Hz point sample). Removed
//                             2026-09-03: biased 2.1x high vs 0x0E. Do not reuse.
//    0x0B  TYPE_STATUS       — 1 Hz radio only, system status
//    0x0C  TYPE_RPM         — TELEMETRY_RATE_HZ, rotor RPM (0 when RPM_ENABLE=0)
//    0x0D  TYPE_CURRENT_CAL — once at boot, current-sense scale constants
//    0x0E  TYPE_CURRENT_BLOCK — batched high-rate current samples (SD only)
//    0x0F  TYPE_CURRENT_STATS — 1 Hz windowed current statistics (radio only)
//    0x10  TYPE_LPF_CAL     — once at boot, IIR alpha + mag cal (SD only)
//    0x11  TYPE_HALL_EDGE   — raw Hall edge timestamps (SD only, RPM_ENABLE=1)
//    0x12  TYPE_IMU_RAW     — both IMUs, uncalibrated accel/gyro (SD only)
//    0x13  TYPE_BATTERY_CAL — once at boot, battery-divider constants (SD only)
//    0x14  TYPE_BATTERY_VOLTAGE — 1 Hz battery voltage (SD + telemetry)
//    0x15  TYPE_SYS_HEALTH  — 1 Hz logging-health counters (SD only)
//
//  ENERGY HARVESTING & THE CURRENT CHANNEL
//  ---------------------------------------
//  The harvester accumulates wave motion as potential energy in a spring, then
//  periodically releases all of it into a TENG disk. The electrically
//  interesting event is therefore a short, high-amplitude current transient, not
//  a slowly-varying level. This drives the whole design of the current channel:
//
//    - SD: requested at CURRENT_RATE_HZ (1000 Hz), achieved at roughly 800 Hz
//      with the current 400 kHz I²C configuration, and written in batches as
//      TYPE_CURRENT_BLOCK so the release transient is resolved rather than
//      aliased. Raw ADC counts, so no resolution is lost.
//    - Radio: the raw sample stream is too wide for a 115200-baud link, so each
//      CURRENT_STATS_WINDOW_MS (2 min) window is reduced on the buoy to a peak
//      plus accumulated ∫I dt and ∫I² dt, sent once per second as
//      TYPE_CURRENT_STATS. That gives peak power and average power per window
//      without transmitting the waveform.
//
//  Conversion (see TYPE_CURRENT_CAL): mA = counts / adc_max * vref * div_ratio
//                                          * sens_mA_per_V
//  where vref is the per-channel EFFECTIVE reference (nominal 2.0 V corrected
//  by the measured ADC gain — docs/adc_calibration.md).
//
//  All logged current data is raw ADC counts (TYPE_CURRENT_BLOCK, 0x0E); the
//  radio carries derived statistics only (TYPE_CURRENT_STATS, 0x0F). The old
//  0x0A packet, which stored counts on SD but milliamps over the radio, was
//  retired 2026-09-03 — that asymmetry is gone.
//
//  DEPLOYMENT FLAGS  (edit before flashing)
//  -----------------------------------------
//  USB_DEBUG  — set to 1 during bench/USB debugging to enable the Serial
//               console and wait up to 3 s for a USB host to connect.
//               Set to 0 for field deployment: the firmware boots immediately
//               without waiting for USB. All DBG_PRINT / DBG_PRINTLN calls
//               are compiled out entirely — zero overhead in field builds.
//               When USB_DEBUG=1, Serial (USB) carries human-readable debug
//               text only; binary telemetry packets are routed to Serial1
//               (RFD900) so the two streams never share the same port.
//
//  USB_TELEM  — set to 1 to mirror all telemetry packets to the USB Serial
//               port (Serial) instead of Serial1/RFD900. Allows the Python
//               ground-station GUI to receive real-time data over USB without
//               a radio link. USB_DEBUG takes priority: if USB_DEBUG=1, USB is
//               reserved for text and binary telemetry is routed to Serial1.
//               Set to 0 for normal radio telemetry via Serial1/RFD900.
//               NOTE: this flag only *routes* telemetry — it never disables it.
//               Use TELEM_ENABLE 0 to switch transmission off entirely.
//
//  TELEM_ENABLE — set to 0 to compile out ALL telemetry transmission, leaving
//               SD logging fully intact. The point is to reclaim the loop time
//               and blocking serial writes that telemetry costs, so the
//               harvested-current sampler can run faster (its achieved rate is
//               loop-bound, not ADC-bound). Use for SD-only current-capture
//               runs where no live monitoring is needed. When 0:
//                 • No packets are written to Serial or Serial1.
//                 • The telemetry UART is not even initialised.
//                 • Windowed current statistics are still accumulated (they are
//                   cheap), but are not sent or logged as TYPE_CURRENT_STATS.
//               Set to 1 for any run where the ground station is in use.
//
//  GPS_ENABLE — set to 1 when the u-blox GNSS module is physically connected
//               to the I²C bus. Set to 0 when the GPS module is absent (e.g.
//               power-saving bench tests or deployments without GPS).
//               When 0, ALL GPS-related code is compiled out entirely.
//               REQUIRED when GPS is not connected: myGNSS.begin() leaves SDA
//               low on a failed ACK, hanging the shared I²C bus and freezing
//               both IMUs. See IDENTIFIED_ISSUES.md #27 for details.
//
//  RPM_ENABLE — set to 1 when the Melexis US1881 Hall-effect sensor is wired
//               to HALL_PIN. Set to 0 when the sensor is absent (bench tests
//               or deployments without the RPM sensor). When 0, ALL Hall/RPM
//               code is compiled out entirely — zero overhead.
//
//  KNOWN ISSUES
//  ------------
//  See IDENTIFIED_ISSUES.md for the full list of open bugs and their severity.
//
// =============================================================================

#include <Wire.h>
#include <SPI.h>
#include <SD.h>
#include <SparkFunBME280.h>
#include <SparkFun_RV8803.h>
#include <SparkFun_u-blox_GNSS_Arduino_Library.h>
#include <SparkFun_ISM330DHCX.h>
#include <SparkFun_MMC5983MA_Arduino_Library.h>
// Vendored AHRS. The two source files sit in THIS folder (VertiSea/MadgwickAHRS.{h,cpp}),
// not in a sibling directory, and that placement is load-bearing:
//
//   * A quoted #include searches the including file's own directory FIRST, so this line
//     can only resolve to the copy beside it. That is what makes "takes precedence over a
//     global install" true rather than merely intended.
//   * Because the header is found in the sketch folder, arduino-builder never reports it
//     missing and therefore never pulls a Madgwick library into the build — so there is no
//     duplicate-symbol clash with a globally installed copy either.
//   * Arduino compiles every .cpp in the sketch folder automatically, so MadgwickAHRS.cpp
//     is built with the sketch.
//
// This copy is a LOCAL FORK of arduino-libraries/MadgwickAHRS 1.2.0, modified in two
// places that materially change the filter's behaviour:
//     sampleFreqDef  512.0f -> 104.0f   (seed only; retuned per-sample from measured dt)
//     betaDef          0.1f ->   0.5f   (~12x the author's recommended AHRS gain)
// Do NOT replace it with the Library Manager version, and do not install that version
// alongside. See the beta TODO in setup() and IDENTIFIED_ISSUES.md Issue 41.
#include "MadgwickAHRS.h"

// =============================================================================
//  BOARD-SUPPORT CORE GUARD
// =============================================================================
// This firmware targets SparkFun Apollo3 core 1.2.1 — the bare Arduino core. Core 2.x is
// built on mbed OS and is NOT a drop-in: it compiles cleanly and then fails at run time,
// which cost a full day of hardware debugging before this guard existed (Issue 59).
//
// The fatal difference is that mbed OS forbids RTOS primitives in interrupt context, and
// its `micros()` takes a mutex:
//
//     ++ MbedOS Error Info ++
//     Error Message: Mutex: 0x100033BC, Not allowed in ISR context
//
// hallISR() calls micros() as its first statement, so on core 2.x the board panics on the
// FIRST Hall edge — about a second into loop(). The observable result is not an obvious
// crash: the SD file contains only the 196 bytes of boot records, no telemetry is ever
// sent, and the LED keeps blinking because the mbed error handler blinks it. Everything
// looks nearly healthy while nothing works.
//
// Other 2.x divergences found alongside it: `Serial` / `Serial1` map differently (Serial1
// telemetry surfaces on the USB port), and analogRead/attachInterrupt semantics differ —
// so even a 2.x build that ran would not produce timing numbers comparable to anything in
// docs/.
//
// To build on 2.x anyway, define ALLOW_MBED_CORE and fix hallISR() first: read the Apollo3
// STIMER directly instead of calling micros(), or set RPM_ENABLE 0 to compile the ISR out.
#if defined(ARDUINO_ARCH_MBED) && !defined(ALLOW_MBED_CORE)
  #error "Apollo3 core 2.x (mbed) detected. This firmware requires core 1.2.1 - on 2.x, micros() in hallISR() panics the kernel on the first Hall edge (IDENTIFIED_ISSUES.md Issue 59). Remove any manual core checkout from the sketchbook hardware/ folder and install SparkFun Apollo3 1.2.1 via the Boards Manager. To override deliberately, define ALLOW_MBED_CORE."
#endif

// =============================================================================
//  DEPLOYMENT FLAGS — edit these before flashing
// =============================================================================

// USB_DEBUG: set to 1 for bench/USB debugging, 0 for field deployment.
//   1 → Serial console is active; firmware waits up to 3 s for a USB host,
//       and all DBG_PRINT / DBG_PRINTLN calls produce output.
//       USB is reserved for text; binary telemetry is routed to Serial1 so the
//       streams never share a port. USB_DEBUG takes priority over USB_TELEM.
//   0 → Firmware boots immediately; all DBG_PRINT / DBG_PRINTLN calls are
//       compiled out entirely (zero code size, zero clock cycles).
//       Binary telemetry packets are sent normally (Serial1/RFD900 or USB
//       if USB_TELEM=1).
#define USB_DEBUG 0

// USB_TELEM: set to 1 to mirror all telemetry packets to the USB Serial port
// (Serial) instead of Serial1/RFD900. Useful for real-time GUI monitoring over
// USB without a radio link. USB_DEBUG takes priority: if USB_DEBUG=1, Serial is
// text-only and telemetry stays on Serial1 regardless of this flag.
//   1 → All TELEM_WRITE() telemetry goes to Serial (USB) when USB_DEBUG=0.
//   0 → All telemetry goes to Serial1 (RFD900 radio modem) — normal field use.
#define USB_TELEM 0

// TELEM_ENABLE: master on/off switch for telemetry TRANSMISSION.
//   1 → Telemetry packets are sent (to Serial or Serial1 per the flags above).
//   0 → ALL telemetry writes are compiled out and the telemetry UART is never
//       initialised. SD logging is completely unaffected.
//
// Why this exists: the harvested-current sample rate is limited by how long each
// loop() iteration takes, not by the ADC. Telemetry costs real time — a 5 Hz
// TelemetryPacket, a current packet, plus 1 Hz status and stats packets, all via
// blocking Serial writes (a 27-byte packet at 115200 baud occupies the UART for
// ~2.3 ms if the TX buffer is full). The flag remains available for SD-only
// captures and controlled timing comparisons.
//
// NOTE: on the RedBoard Artemis Nano there is only ONE USB connector, shared by
// the native USB CDC and the CH340E. USB telemetry is therefore a bench/debug
// convenience only; field deployments use the RFD900 radio (USB_TELEM 0).
//
// Set to 0 for SD-only high-rate current capture; 1 whenever live monitoring is
// wanted. Note USB_TELEM only *routes* telemetry and cannot switch it off.
#define TELEM_ENABLE 0

// GPS_ENABLE: set to 1 when the u-blox GNSS module is physically connected to
// the I²C bus, 0 when it is absent (e.g. power-saving bench tests).
//   1 → GPS init, time sync, SD logging, and radio telemetry are all active.
//   0 → ALL GPS-related code is compiled out entirely. This is REQUIRED when
//       the GPS module is not connected: myGNSS.begin() leaves SDA low on a
//       failed ACK, hanging the shared I²C bus and freezing both IMUs.
//       See IDENTIFIED_ISSUES.md #27 for the full failure analysis.
#define GPS_ENABLE 0

// RPM_ENABLE: set to 1 when the Melexis US1881 Hall-effect sensor is physically
// connected to HALL_PIN. Set to 0 when the sensor is absent.
//   1 → Interrupt-driven pulse timing; rotor RPM logged to SD and transmitted
//       over radio at TELEMETRY_RATE_HZ. Zero RPM reported after 12 s silence.
//   0 → All Hall/RPM code compiled out entirely (zero code size, zero overhead).
#define RPM_ENABLE 1

// IMU_RAW_ONLY: choose what the IMU logs to SD each tick.
//   0 - Default. Log the processed 43 B TYPE_FIXED_IMU / TYPE_STAB_IMU records
//       (pitch/roll/heading + calibrated, LPF-filtered gyro/accel) plus a 17 B
//       TYPE_MAG record. ~108 B per tick including headers.
//   1 - Log one 43 B TYPE_IMU_RAW record instead: uncalibrated sensor output from
//       both IMUs (accel int16 milli-g, gyro int32 mdps) + interval_us, skipping
//       the float conversion entirely. ~43 B per tick, a 60% reduction.
//
// WHY THIS EXISTS: the win is SD BANDWIDTH, not CPU. Madgwick + the LPF together
// measure only ~46 us per tick, so skipping them saves almost nothing in time.
// But at ~108 B/tick a 512-byte SD block fills every 4.7 ticks, and the resulting
// block-write stall is the dominant reason the IMU loop achieves ~93 Hz instead
// of its nominal 104 Hz (see IDENTIFIED_ISSUES.md Issue 34). Measured: 119 B/tick
// flushes every 4.2 ticks and gives 92.6 Hz; 49 B/tick flushes every 10.1 ticks and
// gives 98.9 Hz. This path now costs ~61 B/tick, predicting a flush every ~8.4 ticks.
//
// TRADE-OFF: with IMU_RAW_ONLY 1 the log contains NO on-board attitude and NO
// magnetometer record. pitch/roll/heading must be recomputed offline from the raw
// counts using the TYPE_FIXED_CAL / TYPE_STAB_CAL / TYPE_LPF_CAL constants, which
// are still written at boot. The radio telemetry path is unaffected: Madgwick still
// runs every tick, so TYPE_TELEM_IMU still carries live attitude and vertDisp.
// Use 0 when you want a self-contained log; use 1 when you want maximum rate.
//
// HISTORY: the first version of this path stored gyro as int16, assuming
// sfe_ism_data_t held raw LSB counts. It does not — the SparkFun library scales it, and
// gyro is in mdps, so int16 saturated at 32.767 dps while the buoy reached +/-243 dps
// and all three axes wrapped sign (Issue 35, fixed 2026-09-03 by widening to int32).
#define IMU_RAW_ONLY 1

// SD_BUFFERED_WRITE: queue complete binary records in RAM and service the
// existing Arduino SD 1.3.0 backend in 512-byte sectors. This independently
// validated queue decouples packet producers from storage service and makes
// backpressure visible. The backend is still synchronous: File.write() can
// block loop() on SPI/card latency. Direct IOM DMA was investigated separately
// and rejected for Apollo3 core 1.2.1 after no prototype passed byte verification.
#define SD_BUFFERED_WRITE 1

// STAB_IMU_USES_MAG: run the stabilized IMU's Madgwick filter in 9-DOF (accel + gyro +
// magnetometer) instead of 6-DOF. Currently 0 — heading is reported as the 999.9 sentinel
// and no TYPE_MAG (0x07) records are written.
//
// This exists so the 9-DOF decision lives in ONE place. It was previously a bare `false`
// literal passed to collectIMUData_ISM() at the call site, with the magnetometer's SD
// record gated by nothing at all, which is how 0x07 came to log constant zeros while the
// sensor went unread (Issue 46).
//
// Setting this to 1 enables magnetometer reading, calibration, the LPF, and the 9-DOF
// Madgwick update()... but note that a log only contains 0x07 when IMU_RAW_ONLY is also 0.
#define STAB_IMU_USES_MAG 0

// HALL_PIN: digital GPIO connected to the US1881 output (open-collector, active-LOW).
// The pin must support attachInterrupt() on the Artemis Nano (any free digital GPIO).
// Wire: sensor pin 3 → HALL_PIN with 4.7 kΩ pull-up to 3.3 V.
// Default: pin 2.  Change to any free pin that doesn't conflict with SPI/I²C/Serial1.
#define HALL_PIN 2

// RPM_MAX_EXPECTED: upper bound on plausible rotor speed, used ONLY as a
// noise-rejection threshold — it is not a measurement limit and does not scale
// the result. Any inter-pulse period implying a faster speed than this is
// treated as electrical noise or contact bounce and discarded.
//
// History: this was previously hard-coded as 133,333 µs (= 450 RPM), a value
// carried over from a different, slower device. The VertiSea harvester spins to
// ~2000 RPM (period 30,000 µs), so the old threshold rejected EVERY genuine
// pulse and RPM read zero. Raised to 3000 RPM (20,000 µs), leaving 1.5x margin
// below the real signal while still rejecting implausible glitches.
//
// Sensor headroom is not the constraint: the US1881's 10 kHz max switching
// frequency is ~300x the 33 Hz pulse rate at 2000 RPM.
#define RPM_MAX_EXPECTED 3000

// PULSES_PER_REV: number of Hall falling edges per rotor revolution — i.e. the
// number of magnets on the disk. Currently 1.
//
// NOTE ON MAGNET MOUNTING: the US1881 is a *latch*, so it holds its output state
// until it sees a field reversal. A single magnet still works because a magnet
// passing TANGENTIALLY past the sensor presents a bipolar signature: the
// return-flux lobes on approach and departure are of opposite polarity to the
// pole face, and the trailing lobe is what resets the latch. A magnet mounted
// face-on and withdrawn along the same axis would latch once and never toggle.
// Keep the magnet passing across the sensor face, not toward it.
//
// ⚠ UNVERIFIED AT FINAL GEOMETRY — see POTENTIAL_UPGRADES.md U18.
// Because the latch reset depends on that trailing reverse lobe, it is
// GEOMETRY-SENSITIVE: too large an air gap, too small a magnet, or an off-square
// sweep can leave the lobe below Brp, in which case the latch never resets and
// edges are SILENTLY DROPPED (RPM reads low or zero, with no error anywhere).
// Bench hand-waving has been inconsistent, which is consistent with a marginal
// reset. A non-latching unipolar switch (e.g. A3144) releases on field REMOVAL
// and has no such failure mode; it may be the better part for single-magnet
// tachometry. Validate edge count against known revolutions at the final
// mounted geometry before relying on RPM data.
//
// If magnets are added, set this to the count and prefer alternating polarities;
// the derived RPM formula divides by this value.
#define PULSES_PER_REV 1

// Convenience macros — use these instead of Serial.print() / Serial.println()
// everywhere in the firmware so that debug output is automatically suppressed
// in field builds without touching any other code.
#if USB_DEBUG
  #define DBG_PRINT(x)    Serial.print(x)
  #define DBG_PRINTLN(x)  Serial.println(x)
#else
  #define DBG_PRINT(x)    ((void)0)
  #define DBG_PRINTLN(x)  ((void)0)
#endif

// =============================================================================
//  USER CONFIGURATION
// =============================================================================

// Local timezone offset from UTC (hours). Applied when printing the synced
// time to the console; the RTC is always stored in UTC.
int8_t timezoneOffsetHours = -7;  // PDT = UTC-7; change to -8 for PST

// =============================================================================
//  HARDWARE CONSTANTS
// =============================================================================

// Current-sense front end on A14.
//
// The analog input formerly measured supercapacitor voltage through a resistor
// divider. It now reads the analog output of a current sensor that monitors the
// energy harvested into the battery. The sensor's full-scale output measured in
// the lab is < 2 V, which is within the Apollo3 ADC's 2.0 V reference, so the
// divider is bypassed and the sensor output is wired straight to A14.
//
// R1 / R2 are retained for reference in case a divider is reinstated; the ratio
// applied to the reading is 1.0 (direct connection).
constexpr float R1 = 30000.0f;   // high-side resistor (Ω) — divider not currently fitted
constexpr float R2 =  7500.0f;   // low-side resistor  (Ω) — divider not currently fitted
// constexpr float CURRENT_DIV_RATIO = (R1 + R2) / R2;  // = 5.0 (divider bypassed)
constexpr float CURRENT_DIV_RATIO = 1.0f;   // no divider: ADC sees the sensor output directly

// Current sensor scale factor: milliamps per volt of sensor output.
// Measured value: 100 mA/V. With the ADC's 2.0 V reference and no divider, this
// gives a full-scale range of 0–200 mA and an ADC resolution of
// (2.0 / 16383) * 100 ≈ 0.012 mA per count.
constexpr float CURRENT_SENS_MA_PER_V = 100.0f;   // mA per volt (measured)

// Artemis Nano ADC configured for 14-bit resolution (0–16383 counts).
// The Apollo3 ADC references its internal 2.0 V band-gap reference (the other
// selectable option is 1.5 V; the Artemis module uses the internal 2.0 V one).
// Inputs are 3.3 V tolerant but the reading saturates above ~2.0 V.
constexpr float ADC_MAX = 16383.0f;
constexpr float VREF    =   2.0f;   // NOMINAL reference (V) — datasheet value; range checks only

// Per-channel ADC gain calibration — see docs/adc_calibration.md.
//
// Measured 2026-09-09 on this board against a DMM at three DC levels per
// channel (60,000 samples each): both channels read HIGH by a consistent gain
// factor with no resolvable offset (residuals < 1.5 mV after a gain-only fit).
// The error is within the band-gap reference tolerance and is a property of
// this specific Artemis Nano, so RE-MEASURE if the board is replaced.
//
// The correction is applied as an *effective* reference voltage per channel,
// which folds into the existing `vref` field of TYPE_CURRENT_CAL (0x0D) and
// TYPE_BATTERY_CAL (0x13). The parser therefore converts calibrated logs
// correctly with no protocol change, and pre-calibration logs still convert
// with the nominal 2.0 V they recorded. `vref` in those records means
// "effective reference", not "nominal reference".
constexpr float ADC_GAIN_A14 = 1.014071f;   // measured / true, current channel
constexpr float ADC_GAIN_A15 = 1.011584f;   // measured / true, battery channel
constexpr float VREF_A14 = VREF / ADC_GAIN_A14;   // ≈ 1.97225 V effective
constexpr float VREF_A15 = VREF / ADC_GAIN_A15;   // ≈ 1.97710 V effective
static_assert(ADC_GAIN_A14 > 0.95f && ADC_GAIN_A14 < 1.05f,
              "ADC_GAIN_A14 outside plausible band-gap tolerance — check calibration");
static_assert(ADC_GAIN_A15 > 0.95f && ADC_GAIN_A15 < 1.05f,
              "ADC_GAIN_A15 outside plausible band-gap tolerance — check calibration");

// Single conversion factor from raw ADC counts to milliamps, derived from the
// constants above. Used by both the SD path and the telemetry statistics.
constexpr float COUNTS_TO_MA =
    VREF_A14 * CURRENT_DIV_RATIO * CURRENT_SENS_MA_PER_V / ADC_MAX;   // ≈ 0.012039 mA/count

// Battery-voltage divider on A15 (Apollo3 pad 32 / ADC SE4).
//
// Installed divider (EE, 2026-09-10), both resistors DMM-measured:
//   R_TOP    = 98.7 kΩ  (BAT+ side; the EE's "R1") — physically wired INLINE in the
//              V+ lead between the PMC and the divider board as a short-circuit
//              guard, so it is NOT visible on the board itself.
//   R_BOTTOM = 98.9 kΩ  (GND side; the EE's "R2") — the only resistor on the board;
//              A15 is tapped across it.
//   Ratio    = 1.99798 (nominal 2:1). No filter cap (C1) fitted yet.
// Bench check by the EE: 3.000 V → 1.495 V, 3.300 V → 1.645 V at the node. These
// read ~6.5 mV below the resistor-derived value; that is exactly the loading of a
// 10 MΩ DMM across R_BOTTOM (loaded ratio 2.0078 → 1.4941 / 1.6436 V), so the
// resistor values, not the loaded node readings, are what the firmware uses.
//
// Cell chemistry is 1S LiFePO4 (charge cutoff 3.65 V, nominal 3.2 V, cutoff
// ~2.5 V) — NOT Li-ion. 3.65 V presents 1.83 V to the ADC (91% of the 2.0 V
// full scale); the ADC clips at a cell voltage of 2.0 × 1.998 ≈ 4.0 V. Never
// connect the battery directly to A15.
//
// Source impedance seen by the ADC is R_TOP ‖ R_BOTTOM ≈ 49.4 kΩ, four times the
// 12 kΩ of the earlier 30k/20k placeholder. The Apollo3 sample-and-hold must
// charge from this; the loop discards one A15 conversion after the mux switch
// before taking the archived one. If the reading is found to depend on
// settling time, fit C1 (100 nF across R_BOTTOM) rather than a software fudge.
// The ADC gain above and the divider ratio are independent multiplicative
// terms; entering the measured resistors does not invalidate the gain
// calibration. Values and derived ratio are archived in TYPE_BATTERY_CAL at boot.
constexpr float BATTERY_R_TOP_OHM    = 98700.0f;   // measured (EE's R1)
constexpr float BATTERY_R_BOTTOM_OHM = 98900.0f;   // measured (EE's R2)
constexpr float BATTERY_DIV_RATIO =
    (BATTERY_R_TOP_OHM + BATTERY_R_BOTTOM_OHM) / BATTERY_R_BOTTOM_OHM;   // ≈ 1.99798
constexpr float COUNTS_TO_BATTERY_V = VREF_A15 * BATTERY_DIV_RATIO / ADC_MAX;  // ≈ 0.2411 mV/count
constexpr float BATTERY_CELL_MAX_V   = 3.65f;      // 1S LiFePO4 charge-termination voltage
static_assert(BATTERY_R_BOTTOM_OHM > 0.0f,
              "Battery divider bottom resistor must be nonzero");
static_assert(BATTERY_CELL_MAX_V / BATTERY_DIV_RATIO < VREF,
              "Battery divider must keep a fully charged cell below ADC full scale");

// =============================================================================
//  PIN ASSIGNMENTS
// =============================================================================
const int     CS_SD   = 4;           // SD card SPI chip-select
const int     LED_PIN = LED_BUILTIN; // status / heartbeat LED
const uint8_t A_PIN   = A14;         // current sensor analog output (analog input)
const uint8_t BATTERY_PIN = A15;     // 1S LiFePO4 divider output (Apollo3 pad 32 / ADC SE4)

// =============================================================================
//  SERIAL PORT ALIASES
// =============================================================================
// TELEM_SERIAL selects the binary telemetry output port at compile time:
//   USB_DEBUG=1  → Serial1 (RFD900) — Serial (USB) is reserved exclusively
//                  for human-readable DBG_PRINT text; mixing binary packets
//                  with text on the same USB port corrupts both streams.
//                  Serial1 is initialised unconditionally when USB_DEBUG=1.
//   USB_TELEM=1  → Serial  (USB CDC) — mirror packets to USB for GUI use
//                  without a radio link (USB_DEBUG must be 0).
//   otherwise    → Serial1 (RFD900 radio modem at 115200 baud) — normal field.
#if USB_DEBUG
  #define TELEM_SERIAL Serial1
#elif USB_TELEM
  #define TELEM_SERIAL Serial
#else
  #define TELEM_SERIAL Serial1
#endif

// TELEM_WRITE(pkt) — the single entry point for every telemetry transmission.
// Use this instead of TELEM_SERIAL.write() directly so that TELEM_ENABLE 0
// removes the transmission without disturbing any surrounding SD-logging code.
// Several packets are built inside blocks that also write to the SD card, so a
// blanket #if around those blocks would wrongly disable logging too.
//
// The do/while(0) wrapper keeps the macro safe as a single statement inside an
// unbraced if/else. When disabled it still references the argument in a
// discarded sizeof, so an unused-variable warning is not introduced and the
// packet struct is still type-checked by the compiler.
#if TELEM_ENABLE
  #define TELEM_WRITE(pkt) \
      do { TELEM_SERIAL.write((uint8_t*)&(pkt), sizeof(pkt)); } while (0)
#else
  #define TELEM_WRITE(pkt) do { (void)sizeof(pkt); } while (0)
#endif

// =============================================================================
//  SAMPLING RATES & TIMING INTERVALS
// =============================================================================
const int IMU_RATE_HZ       = 104;  // ISM330DHCX ODR (must match setAccelDataRate)
const int BME_RATE_HZ       =   1;  // BME280 environmental sensor
const int BATTERY_RATE_HZ   =   1;  // slowly varying 1S battery voltage
#if USB_TELEM
const int TELEMETRY_RATE_HZ =  10;  // IMU telemetry packets over USB (higher rate)
#else
const int TELEMETRY_RATE_HZ =   5;  // IMU telemetry packets over radio
#endif
const int GPS_RATE_HZ       =   1;  // GPS SD-log rate
const int DEBUG_RATE_HZ     =   1;  // USB debug print rate (when USB_DEBUG=1)

// Current sampling rate. The harvester stores wave motion in a spring and then
// releases it all at once into the TENG disk, so the useful signal is a short
// high-amplitude transient. Sampling must be fast enough to resolve that pulse
// rather than alias it.
//
// 1000 Hz is a deliberate over-request, not a guaranteed target. The achieved
// rate is loop-dependent: it was ~377 Hz on the earlier 100 kHz-I²C build and
// rose to roughly 780–800 Hz after moving the shared I²C bus to 400 kHz. The
// lower measured rate was already sufficient for this signal (see below).
// Two hardware measurements drove this choice:
//
//  1. Accuracy: a 20 kHz scope capture of a real discharge (scope_465/466) was
//     decimated and the logged statistics recomputed. At ~377 Hz the peak came
//     within -0.60%, integral(I dt) within -0.12% and integral(I^2 dt) within
//     -0.35% of the 20 kHz truth. The discharge is a ~12 s envelope (~2 s rise,
//     ~10 s decay), so a few hundred Hz already oversamples it ~25x.
//  2. Requesting a rate CLOSE TO the loop period backfires. Setting this to 400
//     (2500 us) alongside a ~2.7 ms loop produced only 163 Hz measured — far
//     worse than the 373 Hz obtained at 1000 Hz. When the requested interval is
//     comparable to the loop period, the gate frequently misses by a hair and
//     waits a whole extra pass; when the interval is well below the loop period
//     the gate simply fires every pass and the loop sets the rate. The 400 Hz
//     experiment is recorded in docs/CHANGELOG_VertiSea.ino.md.
//
// Consequence to be aware of: because this is an over-request, the dropped-sample
// counter reports a large number (~600/s of window) representing the request/reality
// gap, NOT data loss. The integrals are unaffected — they use measured intervals. Judge
// sampling health from the effective rate (span_ms in TYPE_CURRENT_BLOCK, or
// n_samples/window_s in TYPE_CURRENT_STATS) rather than from n_dropped.
//
// If a future requirement needs the ~3.7 kHz ripple riding on the envelope rather
// than the envelope itself, polling cannot get there at all — that needs a
// timer/DMA-driven ADC. See POTENTIAL_UPGRADES.md U16/U17.
const int CURRENT_RATE_HZ   = 1000; // harvested-current sample rate (over-request)

// Samples per batched SD block (TYPE_CURRENT_BLOCK). Writing a 5-byte header per
// sample would cost ~4 kB/s in headers alone at the current ~800 Hz aggregate
// rate; batching amortises it to ~9 bytes per 100 samples. The 209-byte record
// stays comfortably inside the SD sector size.
constexpr uint16_t CURRENT_BLOCK_LEN = 100;

// RAM queue for the staged SD pipeline. Eight sectors cost 4096 bytes and cover
// roughly 0.3 s at the current ~12 kB/s aggregate log rate. Keep one additional
// producer sector so records can be assembled without exposing partial records
// to the storage backend.
constexpr uint16_t SD_SECTOR_BYTES = 512;
constexpr uint8_t  SD_QUEUE_SECTORS = 8;
constexpr uint16_t SD_QUEUE_BYTES = SD_SECTOR_BYTES * SD_QUEUE_SECTORS;
constexpr uint32_t SD_SERVICE_SLACK_US = 1500UL;

// Telemetry window for the current statistics. Rather than streaming raw samples
// over a 115200-baud link, the buoy reduces each window to peak and accumulated
// totals and sends those. See CurrentStatsPacket.
const unsigned long CURRENT_STATS_WINDOW_MS = 120000UL;  // 2 minutes

// Derived intervals (computed once at compile time)
const unsigned long IMU_INTERVAL_US       = 1000000UL / IMU_RATE_HZ;   // µs between IMU samples
const unsigned long BME_INTERVAL_MS       = 1000UL    / BME_RATE_HZ;   // ms between BME reads
const unsigned long BATTERY_INTERVAL_MS   = 1000UL    / BATTERY_RATE_HZ;
const unsigned long TELEMETRY_INTERVAL_MS = 1000UL    / TELEMETRY_RATE_HZ; // ms between radio IMU packets
const unsigned long BME_TELEM_INTERVAL_MS = 15000UL;  // ms between BME radio packets (15 s)
const unsigned long GPS_TELEM_INTERVAL_MS =  5000UL;  // ms between GPS radio packets  (5 s)
const unsigned long FLUSH_INTERVAL_MS     =  5000UL;  // ms between SD flush() calls   (5 s)
const unsigned long GPS_INTERVAL_MS       = 1000UL    / GPS_RATE_HZ;   // ms between GPS SD-log writes
const unsigned long DEBUG_INTERVAL_MS     = 1000UL    / DEBUG_RATE_HZ; // ms between debug prints
const unsigned long CURRENT_INTERVAL_US   = 1000000UL / CURRENT_RATE_HZ; // µs between current samples

// Minimum plausible inter-pulse period, derived from RPM_MAX_EXPECTED.
// Periods shorter than this are rejected as noise. Accounts for PULSES_PER_REV
// so adding magnets does not silently lower the effective RPM ceiling.
const unsigned long RPM_MIN_PERIOD_US =
    (unsigned long)(60000000.0 / ((double)RPM_MAX_EXPECTED * PULSES_PER_REV));

// How long to wait for a GPS time fix during setup before giving up and using
// the RTC as-is. Set to 120000UL (2 min) for field use; 100UL skips the wait.
//const unsigned long GPS_SYNC_TIMEOUT_MS   = 100UL;
const unsigned long GPS_SYNC_TIMEOUT_MS   = 120000UL;

// =============================================================================
//  PACKET TYPE IDs  (1-byte type field at the start of every log record)
// =============================================================================
enum PacketType : uint8_t {
  TYPE_FIXED_IMU  = 0x01,  // hull-fixed IMU  — nominal 104 Hz, ~93 Hz achieved
  TYPE_STAB_IMU   = 0x02,  // stabilized IMU  — nominal 104 Hz, ~93 Hz achieved
  TYPE_BME        = 0x03,  // BME280 env data — 1 Hz
  TYPE_GPS        = 0x04,  // GNSS PVT fix    — 1 Hz
  TYPE_RTC_EVENT  = 0x05,  // RTC timestamp   — once at boot
  TYPE_TELEM_IMU  = 0x06,  // IMU telem — TELEMETRY_RATE_HZ (5 radio / 10 USB)
  TYPE_MAG        = 0x07,  // magnetometer    — nominal 104 Hz (absent if IMU_RAW_ONLY)
  TYPE_FIXED_CAL  = 0x08,  // fixed-IMU cal   — once at boot
  TYPE_STAB_CAL   = 0x09,  // stab-IMU cal    — once at boot
  // 0x0A was TYPE_CURRENT (5 Hz point sample). RETIRED 2026-09-03: it was a
  // biased estimator (mean 682 counts vs 325 for the full-rate 0x0E stream over the
  // same run, 2.1x high) because a ~100 ms point sample aliases a bursty signal.
  // Use TYPE_CURRENT_BLOCK (0x0E) for data, TYPE_CURRENT_STATS (0x0F) for display.
  // Do NOT reuse 0x0A for a new type: existing logs still contain it.
  TYPE_STATUS     = 0x0B,  // system status   — 1 Hz radio only
  TYPE_RPM        = 0x0C,  // rotor RPM — TELEMETRY_RATE_HZ (RPM_ENABLE=1 only)
  TYPE_CURRENT_CAL = 0x0D, // current-sense cal — once at boot (SD only)
  TYPE_CURRENT_BLOCK = 0x0E, // block of high-rate current samples (SD only)
  TYPE_CURRENT_STATS = 0x0F, // windowed current statistics — 1 Hz radio
  TYPE_LPF_CAL       = 0x10, // IIR/mag cal constants — once at boot (SD only)
  TYPE_HALL_EDGE     = 0x11, // raw Hall edge timestamps (SD only, RPM_ENABLE=1)
  TYPE_IMU_RAW       = 0x12, // both IMUs, uncalibrated accel(int16 mg)+gyro(int32 mdps)
  TYPE_BATTERY_CAL   = 0x13, // battery ADC/divider constants — once at boot (SD only)
  TYPE_BATTERY_VOLTAGE = 0x14, // 1 Hz battery voltage — SD + telemetry
  TYPE_SYS_HEALTH      = 0x15  // 1 Hz logging-health counters (SD only)
};

// =============================================================================
//  DEVICE HANDLES & GLOBAL STATE
// =============================================================================
SparkFun_ISM330DHCX imuFixed;   // hull-fixed IMU  (I²C 0x6A)
SparkFun_ISM330DHCX imuStab;    // stabilized IMU  (I²C 0x6B)
SFE_MMC5983MA       mag;        // magnetometer on stabilized platform
BME280              bme;        // barometric pressure / humidity / temperature
RV8803              rtc;        // real-time clock (battery-backed)
#if GPS_ENABLE
SFE_UBLOX_GNSS      myGNSS;    // u-blox GNSS module (I²C 0x42)
#endif
File                logFile;    // open SD log file handle
Madgwick            filterFixed; // Madgwick AHRS for fixed IMU
Madgwick            filterStab;  // Madgwick AHRS for stabilized IMU

// =============================================================================
//  DATA STRUCTURES
// =============================================================================

// Calibration constants for one ISM330DHCX IMU.
// Biases are subtracted, then the accel is divided by its scale, yielding g and °/s.
//
// UNITS: these are subtracted from / divide the values the SparkFun driver returns,
// which are already SCALED (accel in milli-g, gyro in mdps) and are NOT raw LSB counts.
//   accel_bias  — milli-g                (subtracted from accelData.*Data)
//   accel_scale — milli-g per 1 g, ~1000 (divides the bias-corrected accel)
//   gyro_bias   — MILLIDEGREES/S, not °/s (subtracted from gyroData.*Data, which is
//                 in mdps; the ×0.001 to °/s happens AFTER the subtraction). A value
//                 of -438.56 is -0.44 °/s, a normal zero-rate offset. Reading it as
//                 °/s implies a sensor pegged near full scale, which is what the docs
//                 said before 2026-09-11.
struct IMUCal {
  float accel_bias[3];   // accelerometer zero-g bias (milli-g)
  float accel_scale[3];  // accelerometer sensitivity (milli-g per +1 g, ≈1000)
  float gyro_bias[3];    // gyroscope zero-rate bias (MILLIDEGREES/S — see note above)
};

// Processed output from one ISM330DHCX + Madgwick filter cycle.
// All filtered values have passed through a 1-pole IIR low-pass filter
// before being fed into the Madgwick AHRS.
struct IMUData {
  float pitch, roll, heading; // Euler angles from Madgwick filter (degrees)
  float gx, gy, gz;           // filtered gyro (°/s)
  float ax, ay, az;           // **filtered** accel (g)
  float mx, my, mz;           // filtered, calibrated magnetometer (arbitrary units)

  float raw_gx, raw_gy, raw_gz; // bias-corrected raw gyro (°/s)
  float raw_ax, raw_ay, raw_az; // bias/scale-corrected raw accel (g)
  float raw_mx, raw_my, raw_mz; // raw magnetometer counts

  // UNCALIBRATED sensor output, straight from the SparkFun driver. These are NOT
  // raw LSB counts — sfe_ism_data_t is already scaled by the library. Named for their
  // real units, because assuming "counts" caused an int16 overflow (Issue 35).
  //   accel: milli-g   — int16 spans +/-32.7 g, far beyond the ISM_4g full scale.
  //   gyro : mdps      — int32 REQUIRED. At the configured ISM_500dps full scale the
  //                      sensor emits up to 500000 mdps, which is 15x the int16 range.
  //                      Do not narrow this to int16 under any scaling that depends on
  //                      the full-scale setting; changing FS would silently break it.
  int16_t mg_ax,   mg_ay,   mg_az;    // accelerometer, milli-g
  int32_t mdps_gx, mdps_gy, mdps_gz;  // gyroscope, millidegrees per second

  // Measured microseconds since the previous IMU sample. Logged so the ACHIEVED
  // rate is directly observable rather than inferred from record timestamps after
  // the fact - which is how an 88.9 Hz shortfall against the nominal 104 Hz went
  // unnoticed. 0 on the first sample after boot.
  uint16_t interval_us;
};

// Most-recent processed IMU frames (updated at 104 Hz in loop())
IMUData lastFixedIMU;
IMUData lastStabIMU;

// =============================================================================
//  LOOP TIMING STATE  (last-fired timestamps, all in ms unless noted)
// =============================================================================
unsigned long lastImuUs     = 0;  // last IMU sample time (µs, from micros())
unsigned long lastBMETime   = 0;  // last BME280 read
unsigned long lastBatteryTime = 0; // last 1 Hz battery-voltage sample
unsigned long lastRFDSend   = 0;  // last IMU telemetry radio send
unsigned long lastGPSTime   = 0;  // last GPS SD-log write
unsigned long lastFlush     = 0;  // last SD flush()
unsigned long lastHeartbeat  = 0;  // last LED toggle
unsigned long lastBME_Telem  = 0;  // last BME telemetry radio send
unsigned long lastDebugTime  = 0;  // last debug print
unsigned long lastStatusSend = 0;  // last TYPE_STATUS radio send
unsigned long lastCurrentUs  = 0;  // last high-rate current sample (µs)
unsigned long lastCurrentStatsSend = 0;  // last TYPE_CURRENT_STATS radio send

// =============================================================================
//  HIGH-RATE CURRENT SAMPLING STATE
// =============================================================================
// Buffer of raw ADC counts awaiting a batched SD write as TYPE_CURRENT_BLOCK.
uint16_t currentBlock[CURRENT_BLOCK_LEN];
uint16_t currentBlockCount = 0;   // samples currently buffered
uint32_t currentBlockStartMs = 0; // millis() of currentBlock[0]

// Rolling statistics for the telemetry window. Accumulated in mA and mA² using
// doubles: at roughly 800 Hz a 2-minute window is ~96 000 samples, and a
// float32 has only ~7 significant digits, so a float accumulator would lose
// low-amplitude samples once the running total grew large (classic accumulation
// error). The packet fields are floats — the precision only matters while summing.
double   statCharge_mC  = 0.0;   // Σ (I_mA × dt_s)  → millicoulombs
double   statI2t_mA2s   = 0.0;   // Σ (I_mA² × dt_s) → mA²·s
double   statIntegSec   = 0.0;   // Σ dt_s — true integration time for this window
uint16_t statPeakCounts = 0;     // peak raw count seen in this window
uint32_t statSamples    = 0;     // samples accumulated in this window
uint32_t statWindowStartMs = 0;  // millis() when this window began
uint32_t currentDropped = 0;     // sample ticks missed in THIS window (diagnostic)

// =============================================================================
//  BUFFERED SD PIPELINE STATE
// =============================================================================
#if SD_BUFFERED_WRITE
uint8_t sdQueue[SD_QUEUE_BYTES];             // complete queued log bytes
uint8_t sdProducer[SD_SECTOR_BYTES];         // record assembly / partial sector
uint8_t sdWriteScratch[SD_SECTOR_BYTES];     // contiguous backend write buffer
uint16_t sdQueueHead = 0;
uint16_t sdQueueTail = 0;
uint16_t sdQueueUsed = 0;
uint16_t sdProducerUsed = 0;
uint16_t sdQueueHighWater = 0;
uint32_t sdQueueOverruns = 0;
uint32_t sdServiceMaxUs = 0;
#endif

// =============================================================================
//  SD ERROR STATE AND RECOVERY
// =============================================================================
// sdError used to be a ONE-WAY LATCH: the first write failure of the deployment
// stopped logging permanently and only a power cycle could clear it. That is
// acceptable for a ten-minute bench run and unacceptable for the 1-2 day field
// logging this system is for. A single transient — an EMI glitch on the SPI lines
// during a TENG discharge, a card pausing for internal garbage collection past the
// library's patience, a momentary brown-out — ended the entire run, and the only
// outward sign was the heartbeat changing to 4 Hz.
//
// It is now a RECOVERABLE state machine:
//
//   healthy  --write fails-->  degraded  --remount succeeds-->  healthy (new file)
//                                  |
//                                  +--SD_MAX_RECOVERY_ATTEMPTS exhausted--> failed
//
// While degraded, records are dropped (there is nowhere to put them) but sampling,
// telemetry and the health record continue, and a remount is retried on a backoff so
// a transient does not cost more than a few seconds of data. Recovery deliberately
// opens a NEW file rather than reusing the old handle: after a card-level fault the
// previous handle's cached cluster chain cannot be trusted, and a fresh file keeps the
// pre-fault data intact on disk.
//
// `sdError` remains the single flag the rest of the firmware tests, so every existing
// `if (!sdError)` guard keeps its original meaning: "is it safe to append right now?"
//
// When sdError is true:
//   • SD appends are skipped (no point hammering a card that just refused)
//   • The LED heartbeat switches to a rapid 4 Hz flash
//   • Radio telemetry continues unaffected (sensor data is still valid)
//   • A remount is attempted every SD_RECOVERY_INTERVAL_MS
bool sdError = false;

constexpr uint8_t  SD_MAX_RECOVERY_ATTEMPTS = 20;    // then stop trying and stay degraded
constexpr uint32_t SD_RECOVERY_INTERVAL_MS  = 5000UL; // backoff between remount attempts

uint32_t sdWriteFailures   = 0;   // cumulative failed writes since boot (health record)
uint32_t sdRecoveries      = 0;   // successful remounts since boot (health record)
uint8_t  sdRecoveryAttempts = 0;  // consecutive failed remounts; reset on success
uint32_t lastSdRecoveryMs  = 0;   // millis() of the last remount attempt
char     sdLogName[20]     = {0}; // current log filename, for the recovery path

// RTC boot timestamp payload (TYPE_RTC_EVENT), captured in setup() and re-emitted into
// any replacement file opened by the recovery path.
uint8_t  rtcBootPayload[6] = {0};

// LED heartbeat state. Tracked explicitly because digitalRead() on an OUTPUT pad is
// not a reliable read-back on Apollo3 — see the heartbeat block at the end of loop().
bool ledState = false;

// Magnetometer presence. Set in setup(); false means mag.begin() failed. Nothing in the
// 6-DOF configuration reads the device, so a failure is reported and tolerated rather
// than fatal — see Issue 46 and the init block in setup().
bool magPresent = false;

// =============================================================================
//  IMU CALIBRATION VALUES  (measured offline; update after each recalibration)
// =============================================================================
// Fixed IMU (hull-fixed, I²C 0x6A)
IMUCal fixedCal = {
  {   3.5f,  -25.0f,   10.0f },   // accel bias  [X, Y, Z] (mg)
  {1004.5f, 1007.0f,  999.0f },   // accel scale [X, Y, Z] (counts/g)
  {  -2.36f, -396.8f, -192.5f }   // gyro bias   [X, Y, Z] (mdps ≈ -0.002/-0.397/-0.193 °/s)
};

// Stabilized IMU (gimballed platform, I²C 0x6B)
IMUCal stabCal = {
  {  -3.0f,  -15.0f,   22.5f },   // accel bias  [X, Y, Z] (mg)
  {1001.0f,  994.0f, 1003.5f },   // accel scale [X, Y, Z] (counts/g)
  { 384.5f, -438.56f,  113.3f }   // gyro bias   [X, Y, Z] (mdps ≈ 0.385/-0.439/0.113 °/s) — Y updated 2026-04-02 from 19.4 s stationary log
};

// =============================================================================
//  MAGNETOMETER CALIBRATION  (obtained via offline ellipsoid fit)
// =============================================================================
// Hard-iron offsets and soft-iron scale factors for the MMC5983MA.
// Collect a full-sphere sweep, then run Calibration/calibrateMag.m to update.
struct MagCal {
  float offset[3];  // hard-iron offset [X, Y, Z] (raw counts)
  float scale[3];   // soft-iron scale  [X, Y, Z] (normalised)
} magCal = {
  { 129992.4f, 129465.3f, 128479.9f},  // hard-iron offsets
  { 155.97f, 1057.42f, 1777.06f}     // soft-iron scales
};

// =============================================================================
//  LOW-PASS FILTER STATE & COEFFICIENTS
// =============================================================================
// Each IMU channel is pre-filtered with a 1-pole IIR (exponential moving
// average) before being passed to the Madgwick AHRS. This reduces high-
// frequency noise without introducing significant phase lag at wave frequencies.
//
// Discrete-time coefficient:  alpha = dt / (rc + dt)
//   where rc = 1 / (2π·f_cutoff) and dt = 1 / IMU_RATE_HZ
// alpha_acc/gyro/mag are computed in setup() once IMU_RATE_HZ is known.

struct LPFState {
  float ax=0, ay=0, az=0;  // filtered accel (g)
  float gx=0, gy=0, gz=0;  // filtered gyro  (°/s)
  float mx=0, my=0, mz=0;  // filtered mag   (calibrated counts)
};
LPFState lpfFixed, lpfStab;  // one state per IMU

// Cutoff frequencies — tune to buoy dynamics.
// Higher cutoff → less smoothing, more noise; lower → more lag.
const float ACCEL_CUTOFF_HZ = 20.0f;  // accel LPF cutoff (Hz)
const float GYRO_CUTOFF_HZ  = 40.0f;  // gyro  LPF cutoff (Hz)
const float MAG_CUTOFF_HZ   =  2.0f;  // mag   LPF cutoff (Hz) — slow sensor

// IIR coefficients (computed in setup(); declared here for global scope)
float alpha_acc, alpha_gyro, alpha_mag;

// =============================================================================
//  RADIO TELEMETRY PACKET STRUCTURES
// =============================================================================
// All packets are packed (no padding) and sent over Serial1 to the RFD900.
// The Python ground station (vertisea_plot_v7.py) parses these structs.
// NOTE: timestamp_10ms wraps after ~655 s (~11 min) — see IDENTIFIED_ISSUES #16.

// Stop accepting records after a storage failure. Telemetry remains active and
// the existing status/LED paths expose the latched failure.
void setSdError(const char* message) {
  (void)message;  // DBG_PRINTLN compiles out in field builds
  if (!sdError) {
    sdError = true;
    sdWriteFailures++;
    lastSdRecoveryMs = millis();   // start the backoff; do not retry instantly
    DBG_PRINTLN(message);
  }
}

#if SD_BUFFERED_WRITE
bool sdQueuePush(const uint8_t* data, uint16_t length) {
  if (length > SD_QUEUE_BYTES - sdQueueUsed) return false;

  while (length > 0) {
    uint16_t chunk = min(length, uint16_t(SD_QUEUE_BYTES - sdQueueHead));
    memcpy(sdQueue + sdQueueHead, data, chunk);
    sdQueueHead = (sdQueueHead + chunk) % SD_QUEUE_BYTES;
    sdQueueUsed += chunk;
    data += chunk;
    length -= chunk;
  }
  if (sdQueueUsed > sdQueueHighWater) sdQueueHighWater = sdQueueUsed;
  return true;
}

bool sdPromoteProducerSector() {
  if (sdProducerUsed < SD_SECTOR_BYTES) return true;
  if (!sdQueuePush(sdProducer, SD_SECTOR_BYTES)) return false;
  sdProducerUsed = 0;
  return true;
}

// Queue one complete binary record atomically. A record is either accepted in
// full or rejected; the queue never contains a partial packet.
bool sdAppendRecord(uint8_t type, uint32_t t_ms,
                    const void* payload, uint16_t payloadBytes) {
  if (sdError) return false;

  const uint16_t recordBytes = 5 + payloadBytes;
  if (recordBytes > SD_SECTOR_BYTES) {
    setSdError("ERROR: SD record exceeds producer sector — logging stopped.");
    return false;
  }

  if (recordBytes > SD_SECTOR_BYTES - sdProducerUsed) {
    if (sdProducerUsed > SD_QUEUE_BYTES - sdQueueUsed ||
        !sdQueuePush(sdProducer, sdProducerUsed)) {
      sdQueueOverruns++;
      setSdError("ERROR: SD queue overrun — logging stopped. Telemetry continues.");
      return false;
    }
    sdProducerUsed = 0;
  }

  sdProducer[sdProducerUsed++] = type;
  memcpy(sdProducer + sdProducerUsed, &t_ms, sizeof(t_ms));
  sdProducerUsed += sizeof(t_ms);
  if (payloadBytes > 0) {
    memcpy(sdProducer + sdProducerUsed, payload, payloadBytes);
    sdProducerUsed += payloadBytes;
  }

  if (!sdPromoteProducerSector()) {
    sdQueueOverruns++;
    setSdError("ERROR: SD queue overrun — logging stopped. Telemetry continues.");
    return false;
  }
  return true;
}

bool sdServiceOneSector() {
  if (sdError || sdQueueUsed < SD_SECTOR_BYTES) return false;

  uint16_t first = min(uint16_t(SD_SECTOR_BYTES),
                       uint16_t(SD_QUEUE_BYTES - sdQueueTail));
  memcpy(sdWriteScratch, sdQueue + sdQueueTail, first);
  if (first < SD_SECTOR_BYTES) {
    memcpy(sdWriteScratch + first, sdQueue, SD_SECTOR_BYTES - first);
  }

  uint32_t startUs = micros();
  size_t written = logFile.write(sdWriteScratch, SD_SECTOR_BYTES);
  uint32_t elapsedUs = micros() - startUs;
  // Same non-monotonic micros() exposure as the loop timer above. A backwards step here
  // would report a multi-thousand-second SD write and send the reader after the card.
  if (elapsedUs > TIMING_MAX_PLAUSIBLE_US) {
    timerAnomaly = true;
  } else if (elapsedUs > sdServiceMaxUs) {
    sdServiceMaxUs = elapsedUs;
  }

  if (written != SD_SECTOR_BYTES) {
    setSdError("ERROR: SD sector write failed — logging stopped. Telemetry continues.");
    return false;
  }

  sdQueueTail = (sdQueueTail + SD_SECTOR_BYTES) % SD_QUEUE_BYTES;
  sdQueueUsed -= SD_SECTOR_BYTES;
  return true;
}

bool sdFlushBuffered() {
  if (sdError) return false;

  while (sdQueueUsed >= SD_SECTOR_BYTES) {
    if (!sdServiceOneSector()) return false;
  }

  // The queue can contain a sub-sector tail when a complete record did not fit
  // in the producer sector. It is older than the current producer bytes and
  // must be written first to preserve exact record order across a flush.
  if (sdQueueUsed > 0) {
    uint16_t queuedTailBytes = sdQueueUsed;
    uint16_t first = min(queuedTailBytes,
                         uint16_t(SD_QUEUE_BYTES - sdQueueTail));
    memcpy(sdWriteScratch, sdQueue + sdQueueTail, first);
    if (first < queuedTailBytes) {
      memcpy(sdWriteScratch + first, sdQueue, queuedTailBytes - first);
    }
    if (logFile.write(sdWriteScratch, queuedTailBytes) != queuedTailBytes) {
      setSdError("ERROR: SD queued-tail write failed — logging stopped.");
      return false;
    }
    sdQueueTail = (sdQueueTail + queuedTailBytes) % SD_QUEUE_BYTES;
    sdQueueUsed = 0;
  }

  if (sdProducerUsed > 0) {
    size_t written = logFile.write(sdProducer, sdProducerUsed);
    if (written != sdProducerUsed) {
      setSdError("ERROR: SD partial-sector write failed — logging stopped.");
      return false;
    }
    sdProducerUsed = 0;
  }

  logFile.flush();
  return true;
}
#else
bool sdAppendRecord(uint8_t type, uint32_t t_ms,
                    const void* payload, uint16_t payloadBytes) {
  if (sdError) return false;
  uint8_t header[5];
  header[0] = type;
  memcpy(header + 1, &t_ms, sizeof(t_ms));
  if (logFile.write(header, sizeof(header)) != sizeof(header) ||
      (payloadBytes > 0 && logFile.write((const uint8_t*)payload, payloadBytes) != payloadBytes)) {
    setSdError("ERROR: SD write failed — logging stopped. Telemetry continues.");
    return false;
  }
  return true;
}

bool sdFlushBuffered() {
  if (sdError) return false;
  logFile.flush();
  return true;
}
#endif

template <typename T>
bool sdAppendRecord(uint8_t type, uint32_t t_ms, const T& payload) {
  return sdAppendRecord(type, t_ms, &payload, sizeof(payload));
}

// Attempt to bring SD logging back after a write failure.
//
// Called from loop() on a backoff while sdError is set. Returns true if logging
// resumed. The sequence is deliberately heavy-handed — close the handle, re-run
// SD.begin() to re-initialise the card, then open a NEW file — because a card that has
// just refused a write may have an inconsistent internal state, and the library's
// cached cluster chain for the old handle is no longer trustworthy.
//
// A new file per recovery is the point, not a side effect: data written before the
// fault is already on disk and closed, so a later failure cannot corrupt it. The cost
// is that a 2-day deployment with N recoveries produces N+1 files, which the parser
// already handles (each is independently self-describing — the boot calibration records
// are rewritten into every new file below).
//
// The in-RAM queue is discarded on recovery. Those bytes belong to the failed file's
// byte stream and appending them to a new file would splice a partial record across the
// boundary, which the parser cannot resynchronise from.

// Forward declaration: defined below, after the calibration structs it serialises.
// Needed here because sdTryRecover() re-emits the boot records into the new file.
bool sdWriteBootRecords();

bool sdTryRecover() {
  if (sdRecoveryAttempts >= SD_MAX_RECOVERY_ATTEMPTS) return false;
  sdRecoveryAttempts++;

  DBG_PRINT("SD recovery attempt "); DBG_PRINTLN(sdRecoveryAttempts);

  if (logFile) logFile.close();

#if SD_BUFFERED_WRITE
  // Discard queued bytes: they are mid-stream fragments of the file that just failed.
  sdQueueHead = sdQueueTail = sdQueueUsed = sdProducerUsed = 0;
#endif

  if (!SD.begin(CS_SD)) {
    DBG_PRINTLN("SD recovery: SD.begin() failed.");
    return false;
  }

  // Derive a fresh name. The date-based name is already taken by the failed file, so go
  // straight to the counter namespace and take the first free slot — the same
  // no-overwrite rule setup() uses.
  char fname[20] = {0};
  bool found = false;
  for (uint32_t n = 1; n <= 99999UL; n++) {
    snprintf(fname, sizeof(fname), "LOG%05lu.BIN", n);
    if (!SD.exists(fname)) { found = true; break; }
  }
  if (!found) {
    DBG_PRINTLN("SD recovery: no unused filename remains.");
    return false;
  }

  logFile = SD.open(fname, FILE_WRITE);
  if (!logFile) {
    DBG_PRINTLN("SD recovery: could not open replacement log file.");
    return false;
  }

  snprintf(sdLogName, sizeof(sdLogName), "%s", fname);
  sdError = false;              // clear BEFORE writing: sdAppendRecord() checks it
  sdRecoveryAttempts = 0;
  sdRecoveries++;

  // Re-emit the boot records so the new file is as self-describing as the first one.
  // Without this, a recovered file would have no calibration and its counts could not
  // be converted to mA or volts.
  if (!sdWriteBootRecords()) {
    DBG_PRINTLN("SD recovery: opened the file but could not write boot records.");
    return false;             // sdError was re-set by the failing append
  }

  DBG_PRINT("SD recovery OK, now logging to "); DBG_PRINTLN(fname);
  return true;
}

// TYPE_TELEM_IMU (0x06) — 5 Hz IMU attitude + vertical displacement
// Total: 1B type + 2B ts10 + 5×int16 = 13 bytes
// Angle encoding: centidegrees (×100).  int16_t range → ±327.67°.  Resolution: 0.01°.
struct __attribute__((packed)) TelemetryPacket {
  uint8_t  type;                // = TYPE_TELEM_IMU (0x06)
  uint16_t timestamp_10ms;      // millis()/10 — wraps after ~655 s
  int16_t  pitch_cdeg;          // fixed IMU pitch  in centi-degrees (÷100 → degrees)
  int16_t  roll_cdeg;           // fixed IMU roll   in centi-degrees (÷100 → degrees)
  int16_t  vertDisp_mm;         // vertical displacement             (÷1000 → metres)
  int16_t  stab_pitch_cdeg;     // stabilized IMU pitch in centi-degrees (÷100 → degrees)
  int16_t  stab_roll_cdeg;      // stabilized IMU roll  in centi-degrees (÷100 → degrees)
};

// TYPE_GPS (0x04) — 5 s GPS telemetry (most-recent cached fix)
struct __attribute__((packed)) TelemetryGPSPacket {
  uint8_t  type;            // = TYPE_GPS (0x04)
  uint16_t timestamp_10ms;  // millis()/10
  uint8_t  sats;            // number of satellites in view
  float    lat;             // latitude  (decimal degrees, WGS-84)
  float    lon;             // longitude (decimal degrees, WGS-84)
};

// TYPE_BME (0x03) — 15 s environmental telemetry
struct __attribute__((packed)) TelemetryBMEPacket {
  uint8_t  type;            // = TYPE_BME (0x03)
  uint16_t timestamp_10ms;  // millis()/10
  float    pressure;        // barometric pressure (Pa)
  float    humidity;        // relative humidity   (%)
  float    temperature;     // air temperature     (°C)
};

// TYPE_CURRENT_CAL (0x0D) — written once at boot to the SD log (never over the
// radio). Records everything needed to turn the raw counts in the SD
// TYPE_CURRENT_BLOCK (0x0E) records into milliamps:
//
//   V_sense = counts / adc_max * vref * div_ratio
//   I_mA    = V_sense * sens_mA_per_V
//
// Storing these makes each log self-describing: if the sensor, the divider, or
// the ADC reference changes, old logs still convert correctly with no need to
// remember the firmware build that produced them.
struct __attribute__((packed)) CurrentCal {
  float vref;            // ADC reference voltage (V)
  float adc_max;         // full-scale ADC count
  float div_ratio;       // input divider ratio (1.0 = no divider)
  float sens_mA_per_V;   // current sensor sensitivity (mA per volt)
};

// TYPE_BATTERY_CAL (0x13) — written once at boot to make every battery
// voltage record self-describing. Resistor values are included, not only the
// derived ratio, so the installed divider can be audited from the SD log.
struct __attribute__((packed)) BatteryCal {
  float vref;            // ADC reference voltage (V)
  float adc_max;         // full-scale ADC count
  float r_top_ohm;       // battery-to-ADC resistor (ohms)
  float r_bottom_ohm;    // ADC-to-ground resistor (ohms)
  float div_ratio;       // (r_top + r_bottom) / r_bottom
};
static_assert(sizeof(BatteryCal) == 20, "BatteryCal payload must remain 20 bytes");

// TYPE_BATTERY_VOLTAGE (0x14) telemetry form. The SD form stores one uint16
// raw ADC count after the normal 5-byte SD header; the parser applies 0x13.
struct __attribute__((packed)) BatteryVoltagePacket {
  uint8_t  type;
  uint16_t timestamp_10ms;
  uint16_t battery_mV;
};
static_assert(sizeof(BatteryVoltagePacket) == 5,
              "BatteryVoltagePacket must remain 5 bytes");

// TYPE_LPF_CAL (0x10) — written once at boot to the SD log (never over radio).
//
// The IMU records store LPF-*filtered* values, but the 1-pole IIR is exactly
// invertible, so raw sensor counts can be reconstructed offline:
//
//   x[n] = y[n-1] + (y[n] - y[n-1]) / alpha
//
// then undo the calibration (see TYPE_FIXED_CAL / TYPE_STAB_CAL) to get counts.
// Verified numerically: recovery is bit-exact after rounding (max error < 0.005
// counts across accel/gyro/mag, holding up under smooth signals and %.6f CSV
// rounding).
//
// Without these constants that inversion is impossible, because alpha depends on
// ACCEL_CUTOFF_HZ / GYRO_CUTOFF_HZ / MAG_CUTOFF_HZ and IMU_RATE_HZ, all of which
// are compile-time values in the sketch. Logging them makes every log
// self-describing instead of requiring the reader to identify the firmware build.
// magCal is included for the same reason — mag inversion needs it too.
//
// The LPF state initialises to exactly 0.0, so even the first sample inverts.
struct __attribute__((packed)) LpfCal {
  float alpha_acc;        // IIR coefficient, accelerometer
  float alpha_gyro;       // IIR coefficient, gyroscope
  float alpha_mag;        // IIR coefficient, magnetometer
  float accel_cutoff_hz;  // design cutoff used to derive alpha_acc
  float gyro_cutoff_hz;   // design cutoff used to derive alpha_gyro
  float mag_cutoff_hz;    // design cutoff used to derive alpha_mag
  float imu_rate_hz;      // sample rate the coefficients assume
  float mag_offset[3];    // magCal hard-iron offsets (raw counts)
  float mag_scale[3];     // magCal soft-iron scales
};

// TYPE_CURRENT_BLOCK (0x0E) — a block of consecutive high-rate current samples,
// SD only. Writing one 5-byte header per sample would spend 2 kB/s on headers
// alone at the historical 400 Hz rate; batching amortises that to one header per CURRENT_BLOCK_LEN
// samples. The header timestamp is the time of the FIRST sample in the block.
//
// Payload: uint16 span_ms, uint16 count, then `count` × uint16 raw counts.
//
// span_ms is the MEASURED elapsed time from the first to the last sample in the
// block — deliberately not a nominal rate. The loop cannot guarantee the
// requested CURRENT_RATE_HZ, so storing an assumed rate produced per-sample
// timestamps that were wrong by the request/reality ratio. A parser reconstructs
// sample i at t_ms + i * span_ms / (count - 1), and can recover the effective
// rate as (count - 1) / (span_ms / 1000).
//
// (CURRENT_BLOCK_LEN is declared with the sampling-rate constants above, because
// the sample buffer that uses it is sized before this point in the file.)

// TYPE_CURRENT_STATS (0x0F) — windowed statistics, radio only.
//
// The raw sample stream cannot be transmitted: at roughly 800 samples/s it is
// about 1.6 kB/s before framing on a ~11 kB/s link, and it would compete with the IMU and GPS
// packets for no analytical benefit. Instead each CURRENT_STATS_WINDOW_MS window
// is reduced to a peak and two accumulated integrals, which is what
// characterising the spring-release event actually needs:
//
//   peak_mA      — largest single sample in the window → peak power
//   charge_mC    — ∫I dt over the window (millicoulombs) → energy as
//                  charge × battery voltage if that voltage is known
//   i2t_mA2s     — ∫I² dt over the window (mA²·s) → energy directly as R × ∫I²dt
//                  if the load resistance is known
//   integ_s      — the TRUE integration time Σdt actually covered by the two
//                  integrals above. Average current is charge_mC / integ_s and
//                  RMS is sqrt(i2t_mA2s / integ_s) — NOT divided by window_s.
//                  Because integration uses measured sample-to-sample dt,
//                  integ_s normally tracks window_s even when the achieved
//                  sample rate is below the request. A gap makes it a coverage
//                  measure; dividing by integ_s excludes unmeasured time.
//   n_samples    — how many samples actually contributed, so the ground station
//                  can tell a full window from a partial or degraded one
//   n_dropped    — sample ticks missed against the requested rate IN THIS WINDOW.
//                  Non-zero just means the requested rate is not being achieved; it
//                  does NOT mean the integrals are wrong, because dt is measured.
//                  Reset with the rest of the window state so it stays comparable to
//                  n_samples. It was previously cumulative since boot while n_samples
//                  was per-window, so the ratio a reader naturally forms from the pair
//                  was meaningless and the value grew without bound over a deployment
//                  (Issue 45).
//
// NOTE ON "ENERGY": this packet intentionally remains current-only. The new 1 Hz
// A15 battery channel supplies voltage separately as TYPE_BATTERY_VOLTAGE (0x14),
// allowing the ground station to estimate average battery-side power as V*Iavg
// without breaking this verified packet layout. Offline processing can interpolate
// the slowly varying voltage against high-rate 0x0E current for ∫V·I dt.
struct __attribute__((packed)) CurrentStatsPacket {
  uint8_t  type;             // = TYPE_CURRENT_STATS (0x0F)
  uint16_t timestamp_10ms;   // millis()/10 at the time of sending
  uint16_t window_s;         // wall-clock length of the window so far (s)
  uint16_t peak_mA;          // peak current in the window (mA)
  float    charge_mC;        // ∫I dt over the window (millicoulombs)
  float    i2t_mA2s;         // ∫I² dt over the window (mA²·s)
  float    integ_s;          // true integration time Σdt covered (s)
  uint32_t n_samples;        // samples that contributed to this window
  uint32_t n_dropped;        // sample ticks missed vs the requested rate, THIS window
};

// TYPE_SYS_HEALTH (0x15) — 1 Hz logging-health counters, SD only.
//
// WHY THIS EXISTS. The reported field symptom was "the heartbeat LED stops blinking or
// sticks on, seemingly when the harvester fires" — and there was no way to tell which of
// several very different causes it was, because the firmware recorded nothing about its
// own execution. A frozen LED means loop() did not reach its final block, which can be:
//
//   * a long SD write (card garbage collection)      -> sd_write_max_us spikes
//   * the RAM queue backing up                       -> sd_queue_high_water near 4096
//   * an SD failure and recovery                     -> sd_write_failures / sd_recoveries
//   * an interrupt storm on the Hall line from EMI   -> hall_rejected climbs fast
//   * an I2C stall (the one cause NOT visible here)  -> loop_max_us spikes with every
//                                                       other counter flat
//
// Those five hypotheses are indistinguishable from the outside and are told apart
// instantly by one row of this CSV. It costs 27 bytes/s against a ~6 kB/s log.
//
// All counters except loop_max_us and sd_write_max_us are cumulative since boot; those
// two are per-interval maxima, reset after each record, so a single bad second cannot be
// hidden by averaging.
struct __attribute__((packed)) SysHealth {
  uint32_t loop_max_us;          // longest loop() pass in this interval
  uint32_t sd_write_max_us;      // longest single SD write in this interval
  uint32_t sd_write_failures;    // cumulative failed writes since boot
  uint32_t sd_recoveries;        // cumulative successful remounts since boot
  uint32_t hall_rejected;        // cumulative ISR-rejected (too fast) Hall edges
  uint32_t hall_lost;            // cumulative Hall edges dropped, ring buffer full
  uint16_t sd_queue_high_water;  // peak bytes held in the RAM queue since boot
  uint16_t sd_overruns;          // cumulative queue overruns since boot
  uint8_t  flags;                // bit0 sdError, bit1 magnetometer absent
};
static_assert(sizeof(SysHealth) == 29, "SysHealth payload must remain 29 bytes");

constexpr uint8_t HEALTH_FLAG_SD_ERROR   = 0x01;
constexpr uint8_t HEALTH_FLAG_NO_MAG     = 0x02;
constexpr uint8_t HEALTH_FLAG_TIMER_ANOM = 0x04;  // micros() stepped backwards

// Longest value micros() arithmetic may produce before it is treated as a timer fault
// rather than a measurement.
//
// micros() on Apollo3 is NOT strictly monotonic. Two adjacent calls can return n then
// n-1: the value is derived from the STIMER through an integer conversion, and a read
// that straddles the clock-domain boundary can round down. Unsigned subtraction then
// turns a ONE MICROSECOND backward step into 4 294 967 295 us, and because loopMaxUs is
// a max-hold, that single glitch poisons the whole 1-second interval.
//
// Observed 2026-09-11: a real log reported loop_max_us = 4 294 967 xxx, which the host
// parser dutifully reported as a "4 294 967 ms loop stall, most likely an I2C stall".
// There was no stall. The board was running normally.
//
// 60 s is chosen because it is unreachable by any real mechanism: the SD write path tops
// out near 50 ms, an I2C stall with no timeout blocks for as long as the bus is held but
// would take the heartbeat LED with it, and the genuine micros() rollover at ~71.6 min is
// handled correctly by unsigned arithmetic and produces a SMALL delta, not a large one.
// So anything above this can only be a backwards step.
constexpr uint32_t TIMING_MAX_PLAUSIBLE_US = 60000000UL;

// Per-interval maxima for the health record. loopMaxUs is sampled at the TOP of loop()
// against the previous pass's entry time, so it measures the full round trip including
// whatever blocked — which is exactly the quantity a frozen LED is reporting.
uint32_t loopMaxUs      = 0;
// Set when a micros() delta exceeded TIMING_MAX_PLAUSIBLE_US, i.e. the timer went
// backwards. Reported as HEALTH_FLAG_TIMER_ANOM and reset with the maxima it protects,
// so the host can tell "no stall measured" from "the measurement itself was rejected".
bool     timerAnomaly   = false;
uint32_t lastLoopEntryUs = 0;
unsigned long lastHealthMs = 0;

// Snapshot of what the last health record actually reported. The health block resets the
// per-interval maxima, and it runs BEFORE the 1 Hz USB_DEBUG print later in loop() — so
// the debug line read values that had just been zeroed and always printed maxWriteUs=0,
// which is precisely the number someone reads that line to see. Stashing the reported
// values keeps the console line and the SD record showing the same thing.
uint32_t reportedLoopMaxUs  = 0;
uint32_t reportedWriteMaxUs = 0;

// TYPE_STATUS (0x0B) — 1 Hz system health packet (radio only, not logged to SD)
// flags byte bit definitions:
//   bit 0 : sdError  — 0 = SD logging OK, 1 = SD write failure detected
//   bits 1-7 : reserved for future status flags
struct __attribute__((packed)) StatusPacket {
  uint8_t  type;            // = TYPE_STATUS (0x0B)
  uint16_t timestamp_10ms;  // millis()/10
  uint8_t  flags;           // status bit-field (see above)
};

// Write the self-describing boot records: RTC anchor plus every calibration constant a
// reader needs to turn raw counts into engineering units.
//
// Factored out of setup() so the SD recovery path can re-emit them into a replacement
// file. A recovered file without these would contain counts that cannot be converted:
// no mA (needs 0x0D), no volts (needs 0x13), no IMU units (needs 0x08/0x09), no LPF
// inversion (needs 0x10), and no wall-clock anchor (needs 0x05).
//
// Returns false if any append failed, which means sdError was re-set underneath us.
bool sdWriteBootRecords() {
  uint32_t t = millis();

  sdAppendRecord(TYPE_RTC_EVENT, t, rtcBootPayload, sizeof(rtcBootPayload));
  sdAppendRecord(TYPE_FIXED_CAL, t, fixedCal);
  sdAppendRecord(TYPE_STAB_CAL,  t, stabCal);

  // vref is the per-channel EFFECTIVE reference (docs/adc_calibration.md), so the
  // parser's counts * vref / adc_max already includes the ADC gain correction.
  CurrentCal currentCal = {
    VREF_A14, ADC_MAX, CURRENT_DIV_RATIO, CURRENT_SENS_MA_PER_V
  };
  sdAppendRecord(TYPE_CURRENT_CAL, t, currentCal);

  BatteryCal batteryCal = {
    VREF_A15, ADC_MAX, BATTERY_R_TOP_OHM, BATTERY_R_BOTTOM_OHM, BATTERY_DIV_RATIO
  };
  sdAppendRecord(TYPE_BATTERY_CAL, t, batteryCal);

  LpfCal lpfCal = {
    alpha_acc, alpha_gyro, alpha_mag,
    ACCEL_CUTOFF_HZ, GYRO_CUTOFF_HZ, MAG_CUTOFF_HZ,
    float(IMU_RATE_HZ),
    { magCal.offset[0], magCal.offset[1], magCal.offset[2] },
    { magCal.scale[0],  magCal.scale[1],  magCal.scale[2]  }
  };
  sdAppendRecord(TYPE_LPF_CAL, t, lpfCal);

  return sdFlushBuffered();   // get them on disk before anything else happens
}

// =============================================================================
//  computeVerticalAccel()
// =============================================================================
// Rotates the body-frame accelerometer readings (in g) into the Earth-frame
// vertical axis using the Madgwick-estimated pitch and roll, then subtracts
// 1 g of gravity to yield the net inertial vertical acceleration.
//
// Returns: net vertical acceleration in g (multiply by 9.80665 for m/s²).
//
// The rotation matrix (neglecting yaw) is:
//   a_ez = ax·sin(p) - ay·sin(r)·cos(p) + az·cos(r)·cos(p)
// where p = pitch, r = roll (both in radians).
float computeVerticalAccel(
  float ax_g, float ay_g, float az_g,
  float pitch_deg, float roll_deg
) {
  float p = pitch_deg * DEG_TO_RAD;
  float r = roll_deg  * DEG_TO_RAD;

  // Rotate body-frame accel into Earth-frame vertical component
  float a_ez =  ax_g *  sin(p)
              + ay_g * -sin(r)*cos(p)
              + az_g *  cos(r)*cos(p);

  // Remove the 1 g static gravity component to get dynamic (inertial) accel
  return a_ez - 1.0f;
}

// =============================================================================
//  collectIMUData_ISM()
// =============================================================================
// Reads one sample from an ISM330DHCX, applies bias/scale calibration,
// runs the 1-pole IIR low-pass filter, updates the Madgwick AHRS, and
// returns a fully populated IMUData struct.
//
// If isStabilizedIMU is true, also reads the MMC5983MA magnetometer and
// performs a 9-DOF Madgwick update; otherwise uses the 6-DOF (IMU-only) path.
// Minimum squared accel magnitude (g²) required to run a Madgwick update.
// A healthy gravity vector should always be ≥ ~0.5 g in magnitude; the
// ISM330DHCX outputs raw zeros when it freezes, which after bias subtraction
// yields ≈ 0.031 g — well below this threshold.  Skipping the update when
// the accel is near-zero prevents the Madgwick gradient-descent step from
// diverging and producing NaN pitch/roll.
// Threshold: 0.25 g²  →  minimum magnitude ≈ 0.5 g
static const float ACCEL_MIN_SQ_MAG = 0.25f;

IMUData collectIMUData_ISM(SparkFun_ISM330DHCX &imu, Madgwick &filt, const IMUCal &cal, bool isStabilizedIMU, LPFState &state, float dtSec) {
  // Retune the Madgwick filter to the MEASURED sample period before updating.
  // begin() only assigns invSampleFreq (it is an inline one-liner in
  // MadgwickAHRS.h); the quaternion q0..q3 is initialised solely in the
  // constructor, so calling begin() every update retunes dt WITHOUT resetting
  // filter state. Verified against the vendored library in Madgwick/src/.
  //
  // Previously the filter was pinned to IMU_RATE_HZ (9.615 ms) in setup() while
  // the loop actually delivered ~10.78 ms, a +12% dt error that mistuned the
  // gain (and +82% in the April logs). See IDENTIFIED_ISSUES.md Issue 34.
  if (dtSec > 0.0f) {
    filt.begin(1.0f / dtSec);
  }

  imu.checkStatus();
  sfe_ism_data_t accelData, gyroData;
  imu.getAccel(&accelData);
  imu.getGyro (&gyroData);

  IMUData d{};

  // Store the uncalibrated sensor output for the raw-logging path (TYPE_IMU_RAW).
  // These fields are a SIDE CHANNEL: every calculation below reads accelData/gyroData
  // directly, so nothing here feeds the LPF, Madgwick, the vertical integrator, or
  // telemetry. Changing their type or scaling cannot affect the filtered path.
  d.mg_ax   = (int16_t)accelData.xData;   // milli-g
  d.mg_ay   = (int16_t)accelData.yData;
  d.mg_az   = (int16_t)accelData.zData;
  d.mdps_gx = (int32_t)gyroData.xData;    // mdps — int32, see the struct comment
  d.mdps_gy = (int32_t)gyroData.yData;
  d.mdps_gz = (int32_t)gyroData.zData;

  // --- Accelerometer: subtract bias (mg), divide by scale (counts/g) → g ---
  // X axis is negated to match the buoy body-frame convention.
  float ax_g_raw  = -(accelData.xData - cal.accel_bias[0]) / cal.accel_scale[0];
  float ay_g_raw  =  (accelData.yData - cal.accel_bias[1]) / cal.accel_scale[1];
  float az_g_raw  =  (accelData.zData - cal.accel_bias[2]) / cal.accel_scale[2];

  // --- Gyroscope: subtract bias (mdps), scale to dps (×0.001) → °/s ---
  // Y axis is negated to match the buoy body-frame convention.
  float gx_dps_raw =  (gyroData.xData - cal.gyro_bias[0]) * 0.001f;
  float gy_dps_raw = -(gyroData.yData - cal.gyro_bias[1]) * 0.001f;
  float gz_dps_raw =  (gyroData.zData - cal.gyro_bias[2]) * 0.001f;

  // Store calibrated-but-unfiltered values for the raw log fields
  d.raw_ax = ax_g_raw;
  d.raw_ay = ay_g_raw;
  d.raw_az = az_g_raw;
  d.raw_gx = gx_dps_raw;
  d.raw_gy = gy_dps_raw;
  d.raw_gz = gz_dps_raw;

  // --- 1-pole IIR low-pass filter (exponential moving average) ---
  state.ax += alpha_acc  * (ax_g_raw  - state.ax);
  state.ay += alpha_acc  * (ay_g_raw  - state.ay);
  state.az += alpha_acc  * (az_g_raw  - state.az);
  state.gx += alpha_gyro * (gx_dps_raw - state.gx);
  state.gy += alpha_gyro * (gy_dps_raw - state.gy);
  state.gz += alpha_gyro * (gz_dps_raw - state.gz);

  // --- Accel magnitude guard: skip Madgwick update if sensor is frozen/invalid ---
  // When the ISM330DHCX freezes it outputs raw zeros; after bias subtraction the
  // calibrated accel magnitude drops to ~0.03 g.  Feeding near-zero accel into
  // the Madgwick filter causes the gradient-descent normalisation to overflow and
  // eventually produce NaN pitch/roll.  We skip the filter update entirely when
  // the filtered accel magnitude is below ACCEL_MIN_SQ_MAG (0.5 g minimum).
  // The filter retains its last valid quaternion, so pitch/roll hold their last
  // good values rather than going NaN.
  float accelSqMag = state.ax*state.ax + state.ay*state.ay + state.az*state.az;
  bool accelValid = (accelSqMag >= ACCEL_MIN_SQ_MAG);

  // --- Magnetometer (stabilized IMU only) ---
  if (isStabilizedIMU) {
    uint32_t mxRaw, myRaw, mzRaw;
    if (mag.getMeasurementXYZ(&mxRaw, &myRaw, &mzRaw)) {
      d.raw_mx = mxRaw;
      d.raw_my = myRaw;
      d.raw_mz = mzRaw;

      // Apply hard-iron offset and soft-iron scale, then LPF
      float mx = (float(mxRaw) - magCal.offset[0]) * magCal.scale[0];
      float my = (float(myRaw) - magCal.offset[1]) * magCal.scale[1];
      float mz = (float(mzRaw) - magCal.offset[2]) * magCal.scale[2];

      state.mx += alpha_mag * (mx - state.mx);
      state.my += alpha_mag * (my - state.my);
      state.mz += alpha_mag * (mz - state.mz);
    }

    // 9-DOF Madgwick update (accel + gyro + mag) — only when accel is valid
    if (accelValid) {
      filt.update(
        state.gx, state.gy, state.gz,
        state.ax, state.ay, state.az,
        state.mx, state.my, state.mz
      );
    }
  } else {
    // 6-DOF Madgwick update (accel + gyro only; heading will be 999.9°)
    // Only run when accel is valid to prevent NaN from frozen sensor output.
    if (accelValid) {
      filt.updateIMU(
        state.gx, state.gy, state.gz,
        state.ax, state.ay, state.az
      );
    }
  }

  // --- Package filtered outputs into the return struct ---
  d.gx    = state.gx;
  d.gy    = state.gy;
  d.gz    = state.gz;
  d.ax    = state.ax;
  d.ay    = state.ay;
  d.az    = state.az;
  d.mx    = state.mx;
  d.my    = state.my;
  d.mz    = state.mz;
  d.pitch = filt.getPitch();
  d.roll  = filt.getRoll();
  // Heading is only valid for the 9-DOF (stabilized) IMU; sentinel = 999.9°
  d.heading = isStabilizedIMU
            ? (isnan(filt.getYaw()) ? 999.9f : filt.getYaw())
            : 999.9f;

  return d;
}

// ---- Hall-effect RPM sensor ISR and shared state ----------------------------
// Compiled out entirely when RPM_ENABLE=0 so there is no overhead for builds
// without the sensor.
// NOTE: defined here (after all struct/global declarations) to prevent the
// Arduino IDE's auto-forward-declaration pre-scan from injecting a prototype
// before the #include directives, which would break type visibility for IMUData
// and other structs defined earlier in the file.
#if RPM_ENABLE
// Hall edge state shared with the ISR.
//
// hallPulseCount is the authoritative "new data" signal, NOT a bool flag. The
// previous design used `volatile bool hallNewPulse`, which lost information: if
// two edges arrived between loop() iterations, hallPulseUs was overwritten and
// the older edge vanished silently. loop() then measured a period spanning two
// revolutions and reported exactly HALF the true RPM with no indication of
// error. A monotonic counter lets loop() detect that it missed edges and discard
// the ambiguous period instead of trusting it.
volatile uint32_t hallPulseUs    = 0;  // micros() at the most recent falling edge
volatile uint32_t hallPulseCount = 0;  // total falling edges since boot

// Ring buffer of raw edge timestamps for TYPE_HALL_EDGE logging. Written by the
// ISR, drained by loop(). Sized generously: at 2000 RPM with one magnet the edge
// rate is only ~33 Hz, so 32 slots is over a second of buffering.
constexpr uint8_t HALL_EDGE_BUF_LEN = 32;
volatile uint32_t hallEdgeBuf[HALL_EDGE_BUF_LEN];
volatile uint8_t  hallEdgeHead = 0;   // ISR writes here
volatile uint8_t  hallEdgeTail = 0;   // loop() reads here
volatile uint32_t hallEdgeLost = 0;   // edges dropped because the buffer was full
volatile uint32_t hallEdgeRejected = 0;  // edges rejected by the ISR as too-fast (noise)

// ---- ISR-level noise rejection ---------------------------------------------
// The plausibility check used to live only in loop(): the ISR accepted EVERY edge,
// buffered it, and loop() decided afterwards whether the derived period was sane.
// That is fine for contact bounce, but it fails badly under electromagnetic
// interference, which is what the TENG harvester produces at exactly the moment the
// data matters. The discharge is a high-voltage event next to an unshielded
// open-collector sense line, and a burst of induced edges then costs three times over:
//
//   1. Every edge takes an interrupt. A sustained burst starves loop(), which is
//      directly visible as the heartbeat LED freezing mid-state.
//   2. Every loop pass then emits a TYPE_HALL_EDGE record of up to 31 timestamps
//      (129 B). At a ~370 Hz loop that is ~48 kB/s of pure noise into an SD pipeline
//      sized for ~6 kB/s — the queue overruns and, before the recovery path added
//      alongside this, latched sdError and ended logging for the whole deployment.
//   3. The RPM reading itself is destroyed, because loop() discards every interval
//      that spans more than one edge.
//
// Rejecting at the source costs one comparison and breaks all three. RPM_MIN_PERIOD_US
// is the same threshold loop() already applied (20 000 us = 3000 RPM, 1.5x above the
// ~2000 RPM the harvester actually reaches), so nothing physically plausible is lost.
//
// hallEdgeRejected is reported in the 1 Hz health record: a non-zero value is the
// signature of electrical noise on the Hall line, which is otherwise invisible.
void hallISR() {
  uint32_t now = micros();

  // Wrap-safe: unsigned subtraction is correct across the ~71.6 min micros() rollover.
  if (hallPulseCount != 0 && (now - hallPulseUs) < RPM_MIN_PERIOD_US) {
    hallEdgeRejected++;
    return;   // implausibly fast — interference or bounce, not a revolution
  }

  hallPulseUs = now;
  hallPulseCount++;

  uint8_t next = (hallEdgeHead + 1) % HALL_EDGE_BUF_LEN;
  if (next != hallEdgeTail) {
    hallEdgeBuf[hallEdgeHead] = now;
    hallEdgeHead = next;
  } else {
    hallEdgeLost++;   // buffer full — loop() is not draining fast enough
  }
}
#endif  // RPM_ENABLE

// Halt permanently, blinking a diagnostic code on the LED.
//
// Every fatal path in setup() used to be a bare `while (1);`. In a field build
// (USB_DEBUG 0) the DBG_PRINTLN above it compiles to nothing, the LED is still solid HIGH
// from the start of setup(), and no port is initialised — so a dead buoy is completely
// silent about WHY it is dead, and the fault cannot be diagnosed without reflashing a
// debug build (Issue 47). Blinking `code` short pulses, then a long pause, costs nothing
// and lets an operator read the failure off the board:
//
//   1 = RTC        2 = BME280      3 = stabilized IMU   4 = fixed IMU
//   5 = SD card    6 = log filenames exhausted          7 = log file open failed
//
// This still HALTS. Whether a missing BME280 should really end the mission, or whether
// the firmware should log what it can and set a status flag, is a deployment-policy
// decision that has not been made — see Issue 47. This only makes the current policy
// observable.
static void haltWithBlinkCode(uint8_t code) {
  pinMode(LED_PIN, OUTPUT);
  for (;;) {
    for (uint8_t i = 0; i < code; i++) {
      digitalWrite(LED_PIN, HIGH); delay(200);
      digitalWrite(LED_PIN, LOW);  delay(200);
    }
    delay(1200);   // long gap so the pulse count is unambiguous
  }
}

// Wait for an ISM330DHCX soft reset to complete, with a timeout.
//
// `while (!imu.getDeviceReset());` is an unbounded spin on an I2C read: if the device
// NAKs or the bus is wedged, the firmware hangs here forever with the LED solid on and
// nothing on any port to say why (Issue 47). The datasheet reset completes in well under
// a millisecond, so 500 ms is generous. Returns false on timeout; the caller decides.
static bool waitForDeviceReset(SparkFun_ISM330DHCX &imu, const char* name) {
  const unsigned long t0 = millis();
  while (!imu.getDeviceReset()) {
    if (millis() - t0 > 500UL) {
      DBG_PRINT("WARNING: ");
      DBG_PRINT(name);
      DBG_PRINTLN(" reset did not complete within 500 ms; continuing anyway.");
      return false;
    }
  }
  return true;
}

// =============================================================================
//  setup()
// =============================================================================
void setup() {
  Serial.begin(115200);

#if USB_DEBUG
  // Wait up to 3 s for a USB serial host (Arduino IDE Serial Monitor, etc.).
  // This prevents the firmware from racing past boot messages during debugging.
  // In field deployment (USB_DEBUG=0) this block is compiled out entirely and
  // the firmware boots immediately — Serial.print() calls are safe either way.
  {
    unsigned long t0 = millis();
    while (!Serial && millis() - t0 < 3000);
  }
  // The Artemis SVL bootloader leaves residual bytes in the UART TX FIFO that
  // drain out interleaved with the first Serial.print() output, appearing as
  // garbage characters. Serial.flush() blocks until the TX buffer is empty,
  // and the delay gives the hardware time to fully drain before we print.
  Serial.flush();
  delay(200);
#endif

  DBG_PRINTLN("VertiSea booting...");

  Wire.begin();

  // I2C bus speed. The Arduino default is 100 kHz (Standard mode), which was the
  // dominant cost in the main loop and the reason 104 Hz was never achieved.
  //
  // Per IMU tick the firmware performs 6 I2C transactions (2x checkStatus,
  // 2x getAccel(6 B), 2x getGyro(6 B)). Cost for both IMUs:
  //     100 kHz -> ~4200 us  (44% of a 9615 us tick; caps IMU at ~238 Hz)
  //     400 kHz -> ~1050 us  (11%;                   caps IMU at ~952 Hz)
  // Logged behaviour at 100 kHz was an effective IMU rate of only 88.9 Hz, the
  // gate quantising to 4 loop passes of ~2.7 ms = 10.8 ms.
  //
  // All devices on this bus support at least Fast mode, per their datasheets:
  //   ISM330DHCX x2 : 400 kHz fast mode AND 1 MHz fast-mode-plus
  //   MMC5983MA     : 400 kHz fast mode
  //   RV-8803-C7    : 400 kHz
  //   BME280        : Standard, Fast and High-Speed modes
  // The u-blox GNSS also supports 400 kHz (GPS_ENABLE is currently 0).
  //
  // Set BEFORE the settling delay and any device .begin(), so each device is
  // probed at the final speed rather than enumerating at 100 kHz.
  //
  // If 400 kHz proves marginal (weak pull-ups / bus capacitance show up as
  // .begin() failures at boot or stale IMU reads), drop back to 100000. 1 MHz is
  // available but should not be tried until 400 kHz is proven clean.
  Wire.setClock(400000);

  SPI.begin();

  // Allow all I²C devices time to complete their power-on startup sequence
  // before the first bus transaction. The RV8803 RTC requires up to ~200 ms
  // after VDD stable before it will ACK. Without this delay, rtc.begin()
  // intermittently fails when the Artemis boots faster than the RTC powers up
  // (e.g. from a supercap or USB hot-plug). See IDENTIFIED_ISSUES.md #30.
  delay(250);

  pinMode(A_PIN, INPUT);        // analog input for current sensor output
  pinMode(BATTERY_PIN, INPUT);  // divided 1S battery voltage; never wire battery directly
  analogReadResolution(14);     // 14-bit ADC → 0–16383 counts
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // LED on solid during setup; goes low when done

  // Serial1: RFD900 radio modem at 115200 baud (telemetry output only).
  // NOTE: An Emlid M2 external GNSS was originally planned for this port
  // but was never connected. The u-blox GNSS is on I²C.
  //
  // TELEM_SERIAL resolves to Serial1 in every case EXCEPT (USB_TELEM=1 and
  // USB_DEBUG=0), where it resolves to Serial (already begun above). The guard
  // below must therefore mirror the TELEM_SERIAL macro exactly.
  //
  // The condition was previously `#if !USB_TELEM`, which was wrong for the
  // USB_DEBUG=1 + USB_TELEM=1 combination: TELEM_SERIAL resolved to Serial1
  // (USB_DEBUG wins) but the guard suppressed Serial1.begin(), so the port was
  // never initialised and ALL telemetry was silently discarded. Debug text on
  // USB still worked, which made the fault easy to miss.
  //
  // TELEM_ENABLE is checked first: with telemetry off there is nothing to send,
  // so the UART is left uninitialised. That is the point of the flag — an idle
  // Serial1 still costs power and pin configuration for no benefit.
#if TELEM_ENABLE && (USB_DEBUG || !USB_TELEM)
  TELEM_SERIAL.begin(115200);  // Serial1 @ 115200 — RFD900 radio modem
#endif
#if !TELEM_ENABLE
  DBG_PRINTLN("Telemetry DISABLED (TELEM_ENABLE 0) — SD logging only.");
#endif

  // ---- RTC ----------------------------------------------------------------
  // Retry up to 5 times with 100 ms between attempts. The RV8803 occasionally
  // needs extra time after power-on before it will ACK on I²C, especially
  // when the Artemis resets while the RTC remains powered from the supercap
  // (the I²C bus may be in a partially-hung state from the previous session).
  DBG_PRINTLN("*Initializing RTC...");
  {
    bool rtcOk = false;
    for (uint8_t attempt = 0; attempt < 5; attempt++) {
      if (rtc.begin()) { rtcOk = true; break; }
      DBG_PRINT("RTC not ready, retrying (attempt ");
      DBG_PRINT(attempt + 1);
      DBG_PRINTLN("/5)...");
      delay(100);
    }
    if (!rtcOk) {
      DBG_PRINTLN("RTC failed after 5 attempts!");
      haltWithBlinkCode(1);  // fatal — RTC is required for log filenames
    }
  }
  // Force 24-hour mode immediately after init. The RV8803 defaults to 12-hour
  // mode on first power-up (or after coin-cell loss). Without this, getHours()
  // returns a 12-hour value (1–12) when the GPS fallback path reads the RTC,
  // causing a 12-hour error in the log filename and TYPE_RTC_EVENT timestamp.
  // The GPS sync path also calls set24Hour() before writing, but doing it here
  // guarantees 24-hour mode for ALL read paths regardless of GPS availability.
  // See IDENTIFIED_ISSUES.md #31.
  rtc.set24Hour();
  DBG_PRINTLN("RTC OK");

  // ---- BME280 -------------------------------------------------------------
  DBG_PRINTLN("*Initializing BME280...");
  if (!bme.beginI2C()) {
    DBG_PRINTLN("BME280 failed!");
    haltWithBlinkCode(2);  // fatal — environmental sensor required
  }
  DBG_PRINTLN("BME280 OK");

  // ---- Stabilized IMU (I²C 0x6B) -----------------------------------------
  DBG_PRINTLN("*Initializing stabilized IMU...");
  if (!imuStab.begin(0x6B)) {
    DBG_PRINTLN("Stabilized IMU failed!");
    haltWithBlinkCode(3);
  }
  // TODO: Review Madgwick beta gain before next deployment.
  //   Current value: betaDef = 0.5f  (Madgwick/src/MadgwickAHRS.cpp, line 30)
  //   beta controls the trade-off between gyro integration and accelerometer/mag correction:
  //     Higher beta → faster convergence, more susceptible to linear-accel disturbance
  //     Lower  beta → slower convergence, smoother attitude, less noise sensitivity
  //   Madgwick's original recommendation for AHRS: beta ≈ 0.041 (gyro noise ≈ 0.3 °/s RMS)
  //   The current 0.5f was set for fast bench convergence and has NOT been tuned for
  //   wave-frequency buoy dynamics. Consider reducing to 0.05–0.1 for field deployment.
  // Seed the filter with the nominal rate. This is only a starting value: from the
  // first IMU tick onward collectIMUData_ISM() re-calls begin() with the MEASURED
  // period, since the loop does not reliably achieve IMU_RATE_HZ (Issue 34).
  filterStab.begin(IMU_RATE_HZ);
  DBG_PRINTLN("Stabilized IMU OK");

  // Soft-reset the ISM330DHCX and wait for it to complete before configuring
  imuStab.deviceReset();
  waitForDeviceReset(imuStab, "stabilized IMU");
  delay(100);

  imuStab.setDeviceConfig();       // load default register map
  imuStab.setBlockDataUpdate();    // BDU: prevent reading stale half-updated data

  // Accelerometer: 104 Hz ODR, ±4 g full-scale
  imuStab.setAccelDataRate(ISM_XL_ODR_104Hz);
  imuStab.setAccelFullScale(ISM_4g);

  // Gyroscope: 104 Hz ODR, ±500 °/s full-scale
  imuStab.setGyroDataRate(ISM_GY_ODR_104Hz);
  imuStab.setGyroFullScale(ISM_500dps);

  // On-chip LP2 anti-aliasing filter on accel; LP1 bandwidth filter on gyro
  imuStab.setAccelFilterLP2();
  imuStab.setAccelSlopeFilter(ISM_LP_ODR_DIV_100);
  imuStab.setGyroFilterLP1();
  imuStab.setGyroLP1Bandwidth(ISM_MEDIUM);

  // ---- Magnetometer (on stabilized platform) ------------------------------
  // NOT fatal. Nothing in the current configuration reads the magnetometer:
  // collectIMUData_ISM() is called with isStabilizedIMU=false for BOTH IMUs, so the
  // branch that touches the MMC5983MA never executes. Halting the whole mission over a
  // device whose output is unused cost a deployment for no benefit (Issue 46).
  //
  // magPresent gates the 0x07 record so a re-enabled 9-DOF build cannot silently log a
  // dead sensor. If 9-DOF is re-enabled AND the magnetometer is required, check
  // magPresent here and decide deliberately — do not restore a bare while(1).
  DBG_PRINTLN("*Initializing stabilized magnetometer...");
  magPresent = mag.begin();
  if (!magPresent) {
    DBG_PRINTLN("WARNING: magnetometer init failed — continuing without it.");
    DBG_PRINTLN("         (Nothing reads it while both IMUs run 6-DOF.)");
  } else {
    DBG_PRINTLN("Stabilized magnetometer OK");
  }

  // ---- Fixed IMU (I²C 0x6A) -----------------------------------------------
  DBG_PRINTLN("*Initializing fixed IMU...");
  if (!imuFixed.begin(0x6A)) {
    DBG_PRINTLN("Fixed IMU failed!");
    haltWithBlinkCode(4);
  }
  DBG_PRINTLN("Fixed IMU OK");

  imuFixed.deviceReset();
  waitForDeviceReset(imuFixed, "fixed IMU");
  delay(100);

  imuFixed.setDeviceConfig();
  imuFixed.setBlockDataUpdate();

  // Accelerometer: 104 Hz ODR, ±4 g full-scale
  imuFixed.setAccelDataRate(ISM_XL_ODR_104Hz);
  imuFixed.setAccelFullScale(ISM_4g);

  // Gyroscope: 104 Hz ODR, ±500 °/s full-scale
  imuFixed.setGyroDataRate(ISM_GY_ODR_104Hz);
  imuFixed.setGyroFullScale(ISM_500dps);

  // On-chip LP2 anti-aliasing filter on accel; LP1 bandwidth filter on gyro
  imuFixed.setAccelFilterLP2();
  imuFixed.setAccelSlopeFilter(ISM_LP_ODR_DIV_100);
  imuFixed.setGyroFilterLP1();
  imuFixed.setGyroLP1Bandwidth(ISM_MEDIUM);

  filterFixed.begin(IMU_RATE_HZ);  // seed only; retuned per-sample from measured dt
  DBG_PRINTLN("Fixed IMU configured");

  // ---- GPS time sync -------------------------------------------------------
  // Attempt to get a valid GPS fix and sync the RTC. If GPS_SYNC_TIMEOUT_MS
  // elapses without a fix, the RTC is used as-is (it may be stale if the
  // battery died). Increase GPS_SYNC_TIMEOUT_MS to 120000UL for field use.
  //
  // localTime* variables hold the timezone-adjusted time used for the SD
  // filename and the TYPE_RTC_EVENT boot record. The RTC itself is always
  // stored in UTC so that absolute time can be recovered during parsing.
  //
  // IMPORTANT: when GPS_ENABLE 0, the entire GPS block below is compiled out.
  // Do NOT call myGNSS.begin() when the module is absent — a failed I²C ACK
  // can leave SDA low, hanging the shared Wire bus and freezing both IMUs.
  // See IDENTIFIED_ISSUES.md #27.
  int     localYear  = 0;
  int     localMonth = 0;
  int     localDay   = 0;
  int     localHour  = 0;
  uint8_t localMin   = 0;
  uint8_t localSec   = 0;
  bool    localTimeValid = false;  // set true once we have a good local time

#if GPS_ENABLE
  DBG_PRINTLN("Waiting on GPS time sync");

  // GNSS init over I2C
  DBG_PRINTLN("*Initializing u-blox GNSS...");
  if (!myGNSS.begin()) {
    DBG_PRINTLN("GNSS not detected. Continuing without GPS sync.");
  } else {
    DBG_PRINTLN("GNSS OK. Waiting for valid time...");

    myGNSS.setI2COutput(COM_TYPE_UBX); // Use UBX protocol only
    myGNSS.setAutoPVT(true);           // Enable automatic PVT messages

    unsigned long start = millis();
    unsigned long lastSatPrint = 0;
    bool synced = false;
    while (millis() - start < GPS_SYNC_TIMEOUT_MS && !synced) {
      // Try to get a PVT fix
      if (myGNSS.getPVT()) {
        if (myGNSS.getYear() >= 2022) {
          // Read raw GPS UTC time
          int     gpsYear  = myGNSS.getYear();
          uint8_t gpsMonth = myGNSS.getMonth();
          uint8_t gpsDay   = myGNSS.getDay();
          int     gpsHour  = myGNSS.getHour();
          uint8_t gpsMin   = myGNSS.getMinute();
          uint8_t gpsSec   = myGNSS.getSecond();

          // Apply timezone offset to get local time
          localHour  = gpsHour + timezoneOffsetHours;
          localDay   = gpsDay;
          localMonth = gpsMonth;
          localYear  = gpsYear;
          localMin   = gpsMin;
          localSec   = gpsSec;

          if (localHour < 0) {
            localHour += 24;
            localDay  -= 1;
            if (localDay < 1) {
              static const uint8_t mdays[] = {31,28,31,30,31,30,31,31,30,31,30,31};
              localMonth -= 1;
              if (localMonth < 1) {
                localMonth = 12;
                localYear -= 1;
              }
              uint8_t maxDay = (localMonth==2 && (localYear%4==0 && (localYear%100!=0||localYear%400==0)))
                              ? 29 : mdays[localMonth-1];
              localDay = maxDay;
            }
          } else if (localHour >= 24) {
            localHour -= 24;
            localDay  += 1;
            static const uint8_t mdays[] = {31,28,31,30,31,30,31,31,30,31,30,31};
            uint8_t maxDay = (localMonth==2 && (localYear%4==0 && (localYear%100!=0||localYear%400==0)))
                            ? 29 : mdays[localMonth-1];
            if (localDay > maxDay) {
              localDay = 1;
              localMonth += 1;
              if (localMonth > 12) {
                localMonth = 1;
                localYear += 1;
              }
            }
          }
          localTimeValid = true;

          // Sync the RTC with raw GPS UTC.
          // The RV8803 defaults to 12-hour mode; explicitly set 24-hour mode
          // before writing the hour so that hours 12-23 are stored correctly.
          // Without this, rtc.setHours(17) stores 5 (PM) and getHours() returns
          // 5 instead of 17, causing a 12-hour error in the log filename and CSV.
          rtc.set24Hour();
          rtc.setSeconds(gpsSec);
          rtc.setMinutes(gpsMin);
          rtc.setHours (gpsHour);   // UTC hour (0-23)
          rtc.setDate  (gpsDay);
          rtc.setMonth (gpsMonth);
          rtc.setYear  (gpsYear);        // setYear() expects the full 4-digit year; it subtracts 2000 internally

          // Print the *localized* time
          char buf[32];
          snprintf(buf, sizeof(buf),
            "Local time: %04d-%02d-%02d %02d:%02u:%02u",
            localYear, localMonth, localDay,
            localHour, localMin, localSec
          );
          DBG_PRINTLN(buf);

          synced = true;
          break;
        }
      }

      // Every 5 s, print how many satellites we see
      if (millis() - lastSatPrint >= 5000) {
        lastSatPrint = millis();
        uint8_t sats = myGNSS.getSIV();
        char buf[36];
        snprintf(buf, sizeof(buf),
                "Waiting for time sync: %u satellites", sats);
        DBG_PRINTLN(buf);
      }

      delay(100);  // avoid hammering I²C
    }

    if (!synced) {
      DBG_PRINTLN("Unable to sync RTC. Using RTC as-is.");
    }
  }
#else
  DBG_PRINTLN("GPS_ENABLE=0 — skipping GPS init and time sync.");
#endif  // GPS_ENABLE

  // If we did not get a GPS fix, derive local time from the RTC (which holds
  // UTC from a previous sync, or an unknown time if the battery died).
  if (!localTimeValid) {
    rtc.updateTime();
    int     rtcUtcYear  = (int)rtc.getYear();          // getYear() returns the full 4-digit year
    uint8_t rtcUtcMonth = rtc.getMonth();
    uint8_t rtcUtcDay   = rtc.getDate();
    int     rtcUtcHour  = (int)rtc.getHours();
    uint8_t rtcUtcMin   = rtc.getMinutes();
    uint8_t rtcUtcSec   = rtc.getSeconds();

    // Apply timezone offset
    localHour  = rtcUtcHour + timezoneOffsetHours;
    localDay   = rtcUtcDay;
    localMonth = rtcUtcMonth;
    localYear  = rtcUtcYear;
    localMin   = rtcUtcMin;
    localSec   = rtcUtcSec;

    if (localHour < 0) {
      localHour += 24;
      localDay  -= 1;
      if (localDay < 1) {
        static const uint8_t mdays[] = {31,28,31,30,31,30,31,31,30,31,30,31};
        localMonth -= 1;
        if (localMonth < 1) { localMonth = 12; localYear -= 1; }
        uint8_t maxDay = (localMonth==2 && (localYear%4==0 && (localYear%100!=0||localYear%400==0)))
                        ? 29 : mdays[localMonth-1];
        localDay = maxDay;
      }
    } else if (localHour >= 24) {
      localHour -= 24;
      localDay  += 1;
      static const uint8_t mdays[] = {31,28,31,30,31,30,31,31,30,31,30,31};
      uint8_t maxDay = (localMonth==2 && (localYear%4==0 && (localYear%100!=0||localYear%400==0)))
                      ? 29 : mdays[localMonth-1];
      if (localDay > maxDay) {
        localDay = 1;
        localMonth += 1;
        if (localMonth > 12) { localMonth = 1; localYear += 1; }
      }
    }
    localTimeValid = (localYear >= 2024);  // treat as valid only if year is plausible

    char buf[48];
    snprintf(buf, sizeof(buf),
            "RTC local time: %04d-%02d-%02d %02d:%02u:%02u",
            localYear, localMonth, localDay,
            localHour, localMin, localSec);
    DBG_PRINTLN(buf);
  }

  // ---- SD card & log file -------------------------------------------------
  // Initialise the card BEFORE calling SD.exists(). The counter fallback used
  // to scan an uninitialised SD object, which could report LOG00001.BIN as free
  // on every boot and then append a new session to that existing file.
  DBG_PRINTLN("*Initializing SD card...");
  // SD 1.3.0's single-argument overload takes the chip-select pin. Its
  // two-argument overload is (clock, csPin), not (csPin, speed).
  if (!SD.begin(CS_SD)) {
    DBG_PRINTLN("SD card failed!");
    haltWithBlinkCode(5);
  }
  DBG_PRINTLN("SD card OK");

  // Filename strategy (fixes IDENTIFIED_ISSUES #2):
  //   1. With valid local time, prefer MMDDHHmm.BIN when that name is unused.
  //   2. If that minute-resolution name already exists (e.g. a reset in the
  //      same minute), or if the RTC is invalid, find the first unused
  //      LOG00001.BIN … LOG99999.BIN name.
  //   3. If every counter name is occupied, halt rather than append to or
  //      overwrite an existing deployment log.
  //
  // FILE_WRITE appends to an existing file, so the SD.exists() checks below
  // are load-bearing data-safety checks, not merely naming preferences.
  // Extra capacity avoids false-positive format-truncation warnings while retaining
  // the required 8.3 names (12 visible characters plus NUL).
  char fname[20] = {0};
  bool filenameFound = false;

  if (localTimeValid) {
    snprintf(fname, sizeof(fname), "%02d%02d%02d%02d.BIN",
             localMonth,
             localDay,
             localHour,
             (int)localMin);

    if (!SD.exists(fname)) {
      filenameFound = true;
      DBG_PRINTLN("Local time valid — using unused date-based log filename.");
    } else {
      DBG_PRINT("Date-based log already exists: ");
      DBG_PRINTLN(fname);
      DBG_PRINTLN("Using a unique counter-based filename instead.");
    }
  } else {
    DBG_PRINTLN("Local time not valid (year < 2024) — using counter-based log filename.");
  }

  if (!filenameFound) {
    for (uint32_t n = 1; n <= 99999UL; n++) {
      snprintf(fname, sizeof(fname), "LOG%05lu.BIN", n);
      if (!SD.exists(fname)) {
        filenameFound = true;
        break;
      }
    }
  }

  if (!filenameFound) {
    DBG_PRINTLN("FATAL: no unused SD log filename remains; refusing to overwrite data.");
    haltWithBlinkCode(6);
  }

  logFile = SD.open(fname, FILE_WRITE);
  if (!logFile) {
    DBG_PRINTLN("Failed to open log file!");
    haltWithBlinkCode(7);
  }
  snprintf(sdLogName, sizeof(sdLogName), "%s", fname);
  DBG_PRINT("Logging to "); DBG_PRINTLN(fname);

  // ---- IIR filter coefficients --------------------------------------------
  // alpha = dt / (rc + dt),  rc = 1 / (2π·f_cutoff)
  // Computed here so they are available globally in loop() and collectIMUData_ISM(),
  // and BEFORE the boot records are written — TYPE_LPF_CAL carries these values, and
  // writing that record before they exist would silently log zeros.
  float dt = 1.0f / float(IMU_RATE_HZ);
  auto alpha = [&](float f) {
    float rc = 1.0f / (2.0f * PI * f);
    return dt / (rc + dt);
  };
  alpha_acc  = alpha(ACCEL_CUTOFF_HZ);
  alpha_gyro = alpha(GYRO_CUTOFF_HZ);
  alpha_mag  = alpha(MAG_CUTOFF_HZ);

  // ---- Boot-time log records ----------------------------------------------
  // Capture the RTC boot timestamp into a global so sdWriteBootRecords() can re-emit it
  // verbatim into a replacement file after an SD recovery. It anchors the whole log to
  // wall-clock time, so a recovered file without it would be untethered.
  //
  // Uses local time (timezone-adjusted) so the timestamp in the binary log matches the
  // wall-clock time visible to the operator, consistent with the SD filename. The RTC
  // itself continues to hold UTC internally. yearOffset is years since 2000 (e.g. 26 for
  // 2026), matching the RV8803 getYear() convention the parser expects.
  rtcBootPayload[0] = (uint8_t)(localYear - 2000);
  rtcBootPayload[1] = (uint8_t)localMonth;
  rtcBootPayload[2] = (uint8_t)localDay;
  rtcBootPayload[3] = (uint8_t)localHour;
  rtcBootPayload[4] = localMin;
  rtcBootPayload[5] = localSec;

  sdWriteBootRecords();

  // ---- Hall-effect RPM sensor -----------------------------------------------
#if RPM_ENABLE
  pinMode(HALL_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(HALL_PIN), hallISR, FALLING);
  DBG_PRINTLN("Hall RPM sensor enabled on HALL_PIN");
#endif  // RPM_ENABLE

  digitalWrite(LED_PIN, LOW);  // LED off → setup complete
  DBG_PRINTLN("Setup complete, entering loop...");
}

// =============================================================================
//  loop()
// =============================================================================
void loop() {
  // imuReady gates telemetry: don't send radio packets until the first IMU
  // sample has been collected (prevents transmitting zeroed-out data at boot).
  // Declared static so it persists across calls and is only initialised once.
  static bool imuReady = false;

  uint32_t      nowMs = millis();   // ms timestamp captured once per loop tick
  unsigned long nowUs = micros();   // µs timestamp for the 104 Hz IMU gate

  // Longest loop() round trip since the last health record. Measured at the TOP of the
  // pass against the previous entry, so it includes everything that blocked anywhere in
  // the body — an I2C stall, an SD write, an interrupt storm. This is the number that
  // explains a frozen heartbeat LED: the LED toggles in the last block, so any pass
  // longer than the 500 ms heartbeat interval is directly visible as a stall.
  if (lastLoopEntryUs != 0) {
    uint32_t loopUs = (uint32_t)(nowUs - lastLoopEntryUs);
    // Reject the impossible rather than max-holding it — see TIMING_MAX_PLAUSIBLE_US.
    // Discarding is safe in the direction that matters: a real stall is orders of
    // magnitude below the ceiling, so nothing diagnosable is lost, while keeping the
    // value would report a 71-minute loop pass on a board that never missed a beat.
    if (loopUs > TIMING_MAX_PLAUSIBLE_US) {
      timerAnomaly = true;
    } else if (loopUs > loopMaxUs) {
      loopMaxUs = loopUs;
    }
  }
  lastLoopEntryUs = nowUs;

  // Persistent sensor readings — updated by their respective rate-limited blocks
  static float pressure = 0, humidity = 0, tempC = 0;  // BME280 (1 Hz)
#if GPS_ENABLE
  static float gpsLat = 0, gpsLon = 0, gpsAlt = 0;     // GNSS fix (1 Hz)
  static uint8_t gpsSats = 0;                           // satellite count
  static unsigned long lastGPSTelem = 0;                // last GPS radio send
#endif

  // Vertical motion integrator state (updated at 104 Hz inside the IMU block).
  static float vertVel  = 0.0f;   // integrated vertical velocity (m/s)
  static float vertDisp = 0.0f;   // integrated vertical displacement (m)

  // Nominal IMU sample period (s). Used ONLY as a fallback when the measured
  // interval is unavailable or implausible -- the loop does not reliably achieve
  // IMU_RATE_HZ (measured ~93 Hz). Do not use this as the integration step.
  const float dtNominal = 1.0f / float(IMU_RATE_HZ);

  // ---- High-rate harvested-current sampling -------------------------------
  // Placed first in loop() so the sample cadence is affected as little as
  // possible by the slower blocks below.
  //
  // Sample as often as the loop allows, capped by CURRENT_RATE_HZ.
  //
  // The gate advances lastCurrentUs by WHOLE INTERVALS rather than snapping it to
  // nowUs. At the current 1000 us interval this makes no difference (the gate
  // fires on every loop pass regardless), but it matters if CURRENT_RATE_HZ is
  // ever raised toward the loop rate: snapping to now caused a pass arriving at
  // 2.6 ms to reset the phase, so the next pass at 5.3 ms elapsed often missed the
  // threshold by a hair and had to wait a third pass. That is how a 400 Hz request
  // measured only 163 Hz on hardware — worse than the 1000 Hz over-request.
  // Carrying the residual forward avoids that failure mode.
  if (nowUs - lastCurrentUs >= CURRENT_INTERVAL_US) {
    uint32_t elapsedUs = nowUs - lastCurrentUs;
    if (elapsedUs >= 2 * CURRENT_INTERVAL_US) {
      // Count whole intervals that went by unsampled. This is a rate-shortfall
      // diagnostic only; it does not affect the integrals' correctness.
      currentDropped += (elapsedUs / CURRENT_INTERVAL_US) - 1;
    }
    // Advance the phase by whole intervals rather than snapping to nowUs, so
    // residual time is carried forward instead of discarded. Clamp the catch-up
    // to avoid a long stall producing a rapid burst of samples.
    if (elapsedUs > 8 * CURRENT_INTERVAL_US) {
      lastCurrentUs = nowUs;                 // too far behind: resync
    } else {
      lastCurrentUs += (elapsedUs / CURRENT_INTERVAL_US) * CURRENT_INTERVAL_US;
    }

    uint16_t counts = analogRead(A_PIN);

    // ---- Window statistics ----
    // dt is the MEASURED wall interval since the previous SAMPLE (tracked
    // separately from the phase accumulator above, which advances in whole
    // intervals and so does not represent real elapsed time). This keeps ∫I dt
    // and ∫I² dt correct however irregularly the loop runs. The first sample
    // after boot has no predecessor, so it is skipped for integration.
    static uint32_t lastSampleUs = 0;
    float i_mA_inst = float(counts) * COUNTS_TO_MA;
    if (statSamples > 0 && lastSampleUs != 0) {
      uint32_t sampleDeltaUs = nowUs - lastSampleUs;   // wrap-safe
      if (sampleDeltaUs < 1000000UL) {                 // sane dt: under 1 s
        double dtMeas = double(sampleDeltaUs) * 1e-6;  // s
        statCharge_mC += double(i_mA_inst) * dtMeas;
        statI2t_mA2s  += double(i_mA_inst) * double(i_mA_inst) * dtMeas;
        statIntegSec  += dtMeas;   // true integration time, for avg/RMS on the ground
      }
    }
    lastSampleUs = nowUs;
    if (counts > statPeakCounts) statPeakCounts = counts;
    statSamples++;
    if (statWindowStartMs == 0) statWindowStartMs = nowMs;

    // ---- Batched SD write ----
    if (currentBlockCount == 0) currentBlockStartMs = nowMs;
    currentBlock[currentBlockCount++] = counts;
    if (currentBlockCount >= CURRENT_BLOCK_LEN) {
      if (!sdError) {
        // Record the block's ACTUAL span in ms rather than a nominal rate, so
        // per-sample timestamps reconstruct to real time. A parser recovers the
        // effective rate as (count - 1) / (span_ms / 1000).
        uint16_t spanMs = uint16_t(constrain(
            long(nowMs) - long(currentBlockStartMs), 0L, 65535L));
        struct __attribute__((packed)) CurrentBlockRecord {
          uint16_t span_ms;
          uint16_t count;
          uint16_t samples[CURRENT_BLOCK_LEN];
        } currentRecord;
        currentRecord.span_ms = spanMs;
        currentRecord.count = currentBlockCount;
        memcpy(currentRecord.samples, currentBlock,
               currentBlockCount * sizeof(currentBlock[0]));
        sdAppendRecord(TYPE_CURRENT_BLOCK, currentBlockStartMs,
                       &currentRecord,
                       sizeof(currentRecord.span_ms) + sizeof(currentRecord.count) +
                       currentBlockCount * sizeof(currentRecord.samples[0]));
      }
      currentBlockCount = 0;
    }
  }

  // ---- 1 Hz battery voltage log + telemetry -------------------------------
  // A battery changes slowly, so 1 Hz is sufficient and adds negligible SD and
  // radio load. The first A15 conversion is discarded after switching from the
  // high-rate A14 channel. A final discarded A14 conversion restores/settles the
  // ADC mux so the next archived current sample is not the first conversion after
  // a channel change.
  if (nowMs - lastBatteryTime >= BATTERY_INTERVAL_MS) {
    lastBatteryTime = nowMs;
    (void)analogRead(BATTERY_PIN);
    uint16_t batteryCounts = analogRead(BATTERY_PIN);
    (void)analogRead(A_PIN);

    if (!sdError) {
      sdAppendRecord(TYPE_BATTERY_VOLTAGE, nowMs, batteryCounts);
    }

    uint16_t battery_mV = uint16_t(constrain(
        float(batteryCounts) * COUNTS_TO_BATTERY_V * 1000.0f,
        0.0f, 65535.0f) + 0.5f);
    BatteryVoltagePacket batteryPkt = {
      TYPE_BATTERY_VOLTAGE,
      uint16_t(nowMs / 10),
      battery_mV
    };
    TELEM_WRITE(batteryPkt);
  }

  // ---- 1 Hz BME280 environmental log --------------------------------------
  if (nowMs - lastBMETime >= BME_INTERVAL_MS) {
    lastBMETime = nowMs;
    pressure = bme.readFloatPressure();  // Pa
    humidity = bme.readFloatHumidity();  // %
    tempC    = bme.readTempC();          // °C
    if (!sdError) {
      struct __attribute__((packed)) BmeRecord {
        float pressure;
        float humidity;
        float temperature;
      } bmeRecord = { pressure, humidity, tempC };
      sdAppendRecord(TYPE_BME, nowMs, bmeRecord);
    }
  }

  // ---- 104 Hz IMU sample + SD log -----------------------------------------
  // The -50 µs margin absorbs scheduling jitter so we don't miss a tick.
  if (nowUs - lastImuUs >= IMU_INTERVAL_US - 50) {
    // Measured interval since the previous IMU sample, captured BEFORE lastImuUs
    // is advanced. Clamped to uint16 (max 65.535 ms); reports 0 on the first
    // sample after boot, when there is no previous sample to difference against.
    uint32_t imuDeltaUs = (lastImuUs == 0) ? 0UL : (uint32_t)(nowUs - lastImuUs);
    uint16_t imuInterval_us =
        (uint16_t)((imuDeltaUs > 65535UL) ? 65535UL : imuDeltaUs);
    lastImuUs = nowUs;

    // Measured sample period in seconds, for Madgwick and the vertical integrator.
    // Falls back to the nominal period on the first sample after boot (no previous
    // sample to difference) and whenever the measured gap is implausible, so a
    // scheduling hiccup or a micros() wrap cannot inject a wild dt into the
    // integrator. Upper bound 0.5 s is ~46x the nominal tick.
    float dtActual = (imuDeltaUs > 0UL && imuDeltaUs < 500000UL)
                       ? (float(imuDeltaUs) * 1e-6f)
                       : dtNominal;

    // Collect calibrated, filtered, AHRS-processed data from both IMUs.
    // The fixed IMU has no magnetometer, so it is always 6-DOF. The stabilized IMU
    // follows STAB_IMU_USES_MAG (currently 0 — see the flag's definition).
    lastFixedIMU = collectIMUData_ISM(imuFixed, filterFixed, fixedCal, false, lpfFixed, dtActual);
    lastStabIMU  = collectIMUData_ISM(imuStab,  filterStab,  stabCal,
                                      STAB_IMU_USES_MAG && magPresent, lpfStab, dtActual);
    lastFixedIMU.interval_us = imuInterval_us;
    lastStabIMU.interval_us  = imuInterval_us;
    imuReady = true;

    // Compute net vertical (Earth-frame) acceleration from the stabilized IMU.
    // computeVerticalAccel() returns a value in g; multiply by G for m/s².
    float a_vert_g = computeVerticalAccel(
      lastStabIMU.ax, lastStabIMU.ay, lastStabIMU.az,
      lastStabIMU.pitch, lastStabIMU.roll
    );
    const float G = 9.80665f;
    float a_vert = a_vert_g * G;  // m/s²

    // Euler integration: accel → velocity → displacement.
    // NOTE: vertical displacement accuracy depends on IMU calibration quality.
    // The bias calibration block was removed because it required the board to
    // be stationary at startup, which cannot be guaranteed in field deployment.
    vertVel  += a_vert * dtActual;
    vertDisp += vertVel * dtActual;

    // Exponential leak (high-pass) to suppress residual long-period drift.
    // Expressed as a TIME CONSTANT rather than a fixed per-sample factor. The old
    // 0.9995f gave tau = dt/(1-0.9995), which equals the documented 19.2 s ONLY at
    // exactly 104 Hz. Because the loop runs slower, dt is larger and tau came out
    // LONGER than intended: 21.6 s at the measured 93 Hz and 35.0 s in the April
    // 57 Hz logs -- i.e. the high-pass leaked more slowly than documented and
    // suppressed drift less aggressively, and the corner drifted with loop load.
    // First-order form of exp(-dt/tau); accurate to <0.02% for dt/tau << 1 and
    // avoids a per-sample expf().
    const float VERT_LEAK_TAU_S = 19.2f;
    float leak = 1.0f - (dtActual / VERT_LEAK_TAU_S);
    vertVel  *= leak;
    vertDisp *= leak;

    // Log fixed IMU: pitch, roll, heading, gyro XYZ (°/s), accel XYZ (g)
    // SD write error detection (fixes IDENTIFIED_ISSUES #3):
    // Write the first field and check the return value. A return of 0 means
    // the SD card has failed (full, removed, or hardware error). On failure,
    // set sdError=true — subsequent SD writes are skipped, but telemetry
    // (TELEM_SERIAL) continues so the ground station keeps receiving data.
    if (!sdError) {
#if IMU_RAW_ONLY
      // Compact path: one 38 B payload instead of 38+38+12 = 88 B, i.e. a 43 B
      // record instead of 103 B including headers.
      //
      // Accel is int16 milli-g; gyro is int32 mdps. The widths are NOT symmetric on
      // purpose: at the configured ISM_500dps full scale the gyro reaches 500000 mdps,
      // 15x the int16 range, and an earlier int16 version wrapped sign on every fast
      // rotation (Issue 35). Accel at ISM_4g peaks near 4000 mg, so int16 is ample.
      //
      // Packed into one struct and written in a single call so the layout is explicit
      // and the byte order cannot drift from what the parsers expect.
      struct __attribute__((packed)) ImuRawRec {
        int16_t  mg_ax_f,   mg_ay_f,   mg_az_f;
        int32_t  mdps_gx_f, mdps_gy_f, mdps_gz_f;
        int16_t  mg_ax_s,   mg_ay_s,   mg_az_s;
        int32_t  mdps_gx_s, mdps_gy_s, mdps_gz_s;
        uint16_t interval_us;
      };
      static_assert(sizeof(ImuRawRec) == 38, "TYPE_IMU_RAW payload must be 38 bytes");

      ImuRawRec rawRec = {
        lastFixedIMU.mg_ax,   lastFixedIMU.mg_ay,   lastFixedIMU.mg_az,
        lastFixedIMU.mdps_gx, lastFixedIMU.mdps_gy, lastFixedIMU.mdps_gz,
        lastStabIMU.mg_ax,    lastStabIMU.mg_ay,    lastStabIMU.mg_az,
        lastStabIMU.mdps_gx,  lastStabIMU.mdps_gy,  lastStabIMU.mdps_gz,
        lastFixedIMU.interval_us
      };

      // Attitude is NOT logged here; recompute it offline from these values using the
      // boot-time TYPE_FIXED_CAL / TYPE_STAB_CAL / TYPE_LPF_CAL records.
      sdAppendRecord(TYPE_IMU_RAW, nowMs, rawRec);
#else
      struct __attribute__((packed)) ProcessedImuRecord {
        float pitch, roll, heading;
        float gx, gy, gz;
        float ax, ay, az;
        uint16_t interval_us;
      };
      static_assert(sizeof(ProcessedImuRecord) == 38,
                    "Processed IMU payload must be 38 bytes");

      ProcessedImuRecord fixedRecord = {
        lastFixedIMU.pitch, lastFixedIMU.roll, lastFixedIMU.heading,
        lastFixedIMU.gx, lastFixedIMU.gy, lastFixedIMU.gz,
        lastFixedIMU.ax, lastFixedIMU.ay, lastFixedIMU.az,
        lastFixedIMU.interval_us
      };
      sdAppendRecord(TYPE_FIXED_IMU, nowMs, fixedRecord);

      ProcessedImuRecord stabRecord = {
        lastStabIMU.pitch, lastStabIMU.roll, lastStabIMU.heading,
        lastStabIMU.gx, lastStabIMU.gy, lastStabIMU.gz,
        lastStabIMU.ax, lastStabIMU.ay, lastStabIMU.az,
        lastStabIMU.interval_us
      };
      sdAppendRecord(TYPE_STAB_IMU, nowMs, stabRecord);

      // Only write 0x07 when the magnetometer was actually read this tick. The mx/my/mz
      // fields are copies of an LPFState that collectIMUData_ISM() updates ONLY on the
      // isStabilizedIMU=true path. With both IMUs running 6-DOF that state is never
      // touched, so this record used to log constant 0.0 every tick — indistinguishable
      // in the CSV from a real reading near the calibration centre, and a parser has no
      // way to tell the difference. Absent records are unambiguous; fabricated ones are
      // not (Issue 46). Re-enabling 9-DOF restores the record automatically.
      if (STAB_IMU_USES_MAG && magPresent) {
        struct __attribute__((packed)) MagRecord {
          float mx, my, mz;
        } magRecord = { lastStabIMU.mx, lastStabIMU.my, lastStabIMU.mz };
        sdAppendRecord(TYPE_MAG, nowMs, magRecord);
      }
#endif  // IMU_RAW_ONLY
    }
  }

  // ---- 5 Hz IMU + current telemetry (radio) -------------------------------
  if (imuReady && nowMs - lastRFDSend >= TELEMETRY_INTERVAL_MS) {
    lastRFDSend = nowMs;
    // ts10 wraps after ~655 s (~11 min) — see IDENTIFIED_ISSUES #16.
    uint16_t ts10 = uint16_t(lastRFDSend / 10);

    // Compute vertDisp_mm once and reuse in the struct init (fixes IDENTIFIED_ISSUES #17).
    // vertDisp is the outer static updated at 104 Hz (fixes IDENTIFIED_ISSUES #4).
    //
    // Angle encoding: centidegrees (×100 scale factor).
    //   int16_t range: −32768 … 32767  →  ±327.67° at ×100 scale.
    //   Resolution: 0.01° — sufficient for wave-buoy attitude.
    //   This was changed from ×1000 (millidegrees, ±32.767° range) to ×100
    //   to support the full ±70° operating range without int16_t overflow.
    //
    // toCdeg() — convert float degrees to centidegrees, clamped to int16_t range.
    auto toCdeg = [](float deg) -> int16_t {
      return int16_t(constrain(deg * 100.0f, -32767.0f, 32767.0f));
    };
    int16_t vertDisp_mm = int16_t(constrain(vertDisp * 1000.0f, -32767.0f, 32767.0f));

    TelemetryPacket imuPkt = {
      TYPE_TELEM_IMU,
      ts10,
      toCdeg(lastFixedIMU.pitch),   // fixed IMU pitch  in centi-degrees (÷100 → degrees)
      toCdeg(lastFixedIMU.roll),    // fixed IMU roll   in centi-degrees (÷100 → degrees)
      vertDisp_mm,                  // vert disp in mm  (÷1000 → metres)
      toCdeg(lastStabIMU.pitch),    // stabilized IMU pitch in centi-degrees (÷100 → degrees)
      toCdeg(lastStabIMU.roll)      // stabilized IMU roll  in centi-degrees (÷100 → degrees)
    };
    TELEM_WRITE(imuPkt);

    // No 5 Hz current packet here any more (TYPE_CURRENT 0x0A retired):
    //   - SD gets every sample via TYPE_CURRENT_BLOCK (0x0E) at the achieved rate.
    //   - the ground station gets TYPE_CURRENT_STATS (0x0F) once per second.
    // Dropping it also removes 7 B/tick of SD traffic, which reduces how often a
    // 512-byte block flush stalls the IMU loop (Issue 34 fix 2).
  }

  // ---- 1 Hz GPS SD log ----------------------------------------------------
  // Compiled out entirely when GPS_ENABLE 0 — myGNSS.getPVT() on an absent
  // module leaves SDA low and hangs the I²C bus (IDENTIFIED_ISSUES #27).
#if GPS_ENABLE
  // Always writes a packet each second (fixes IDENTIFIED_ISSUES #7).
  // When getPVT() returns a valid fix, real coordinates are logged.
  // When there is no fix, a sentinel packet with gpsSats=0 and lat/lon/alt=0
  // is written so the CSV has no gaps and no-fix periods are unambiguous.
  if (nowMs - lastGPSTime >= GPS_INTERVAL_MS) {
    lastGPSTime = nowMs;
    if (myGNSS.getPVT()) {
      gpsSats = myGNSS.getSIV();
      gpsLat  = (float)(myGNSS.getLatitude()  * 1e-7);   // degrees (WGS-84)
      gpsLon  = (float)(myGNSS.getLongitude() * 1e-7);   // degrees (WGS-84)
      gpsAlt  = (float)(myGNSS.getAltitude()  * 1e-3);   // mm → m (MSL)
    } else {
      // No fix — write sentinel values so the log has no gaps.
      gpsSats = 0;
      gpsLat  = 0.0f;
      gpsLon  = 0.0f;
      gpsAlt  = 0.0f;
    }
    if (!sdError) {
      struct __attribute__((packed)) GpsRecord {
        uint8_t satellites;
        float latitude;
        float longitude;
        float altitude;
      } gpsRecord = { gpsSats, gpsLat, gpsLon, gpsAlt };
      sdAppendRecord(TYPE_GPS, nowMs, gpsRecord);
    }
  }

  // ---- 5 s GPS telemetry (radio) ------------------------------------------
  // Sends the most-recently cached fix; does not poll the GNSS module.
  if (nowMs - lastGPSTelem >= GPS_TELEM_INTERVAL_MS) {
    lastGPSTelem = nowMs;
    uint16_t ts10 = uint16_t(lastGPSTelem / 10);
    TelemetryGPSPacket gpsPkt = {
      TYPE_GPS,
      ts10,
      gpsSats,
      gpsLat,
      gpsLon
    };
    TELEM_WRITE(gpsPkt);
  }
#endif  // GPS_ENABLE

  // ---- 15 s BME telemetry (radio) -----------------------------------------
  // Sends the most-recently cached BME280 readings (updated at 1 Hz above).
  if (nowMs - lastBME_Telem >= BME_TELEM_INTERVAL_MS) {
    lastBME_Telem = nowMs;
    uint16_t ts10 = uint16_t(lastBME_Telem / 10);
    TelemetryBMEPacket bmePkt = {
      TYPE_BME,
      ts10,
      pressure,
      humidity,
      tempC
    };
    TELEM_WRITE(bmePkt);
  }

  // ---- RPM measurement and telemetry (RPM_ENABLE only) --------------------
  // Co-timed with TELEMETRY_RATE_HZ (5 Hz radio / 30 Hz USB).
  // Interrupt-driven: ISR records micros() on each FALLING edge from the Hall
  // sensor. loop() atomically consumes the pulse, computes RPM, and sends the
  // packet. Zero RPM is reported after 12 s with no pulse (stalled/stopped rotor).
#if RPM_ENABLE
  {
    static uint32_t lastHallUs  = 0;     // micros() of the previous consumed pulse
    static float    currentRPM  = 0.0f;
    static uint32_t lastRpmSendMs = 0;
    static uint32_t lastPulseCount = 0;   // hallPulseCount at the previous read

    // ---- Drain the ISR edge ring buffer and log raw timestamps -------------
    // Logging raw edges (rather than only the derived RPM) preserves the full
    // timing record: with one magnet the discharge yields ~200 edges over 12 s,
    // and offline analysis can fit the expected spin-up curve, reject glitches
    // with hindsight, or re-derive RPM a different way — none of which is
    // possible from a 5 Hz decimated RPM value. Costs ~133 B/s at 2000 RPM.
    {
      // HALL_EDGE_BUF_LEN - 1 is the true capacity of the ring buffer: one slot
      // is always left empty to distinguish "full" from "empty".
      uint32_t edges[HALL_EDGE_BUF_LEN];
      uint8_t  nEdges = 0;
      noInterrupts();
      while (hallEdgeTail != hallEdgeHead && nEdges < HALL_EDGE_BUF_LEN) {
        // Explicit const-cast: reading a volatile array element into a plain
        // local is well-defined, but the cast documents that the volatility is
        // deliberately dropped here because interrupts are already disabled.
        edges[nEdges++] = (uint32_t)hallEdgeBuf[hallEdgeTail];
        hallEdgeTail = (uint8_t)((hallEdgeTail + 1) % HALL_EDGE_BUF_LEN);
      }
      uint32_t lostSnapshot = hallEdgeLost;
      interrupts();

      if (nEdges > 0 && !sdError) {
        // Payload: uint8 count, then count × uint32 micros() timestamps.
        // Timestamps are raw micros() so inter-edge periods stay exact; the
        // 5-byte header's millis() value anchors them to the rest of the log.
        struct __attribute__((packed)) HallEdgeRecord {
          uint8_t count;
          uint32_t timestamps[HALL_EDGE_BUF_LEN - 1];
        } edgeRecord;
        edgeRecord.count = nEdges;
        memcpy(edgeRecord.timestamps, edges, nEdges * sizeof(edges[0]));
        sdAppendRecord(TYPE_HALL_EDGE, nowMs, &edgeRecord,
                       sizeof(edgeRecord.count) + nEdges * sizeof(edgeRecord.timestamps[0]));
      }

      // Report a full-buffer overflow once per occurrence. At ~33 edges/s into a
      // 31-slot buffer drained every loop pass this should never fire; if it
      // does, either the edge rate is far higher than expected (noise) or loop()
      // stalled for ~1 s.
      static uint32_t lastLostReported = 0;
      if (lostSnapshot != lastLostReported) {
        lastLostReported = lostSnapshot;
        DBG_PRINT("WARN: Hall edge buffer overflow, total lost=");
        DBG_PRINTLN(lostSnapshot);
      }
    }

    // ---- Derive RPM from the most recent edge ------------------------------
    // Uses the monotonic pulse counter rather than a bool flag so that missed
    // edges are detectable. If more than one edge arrived since the last check,
    // the interval spans multiple revolutions and cannot be attributed to a
    // single one, so it is discarded rather than reported as a halved RPM.
    noInterrupts();
    uint32_t pulseCount = hallPulseCount;
    uint32_t pulseUs    = hallPulseUs;
    interrupts();

    uint32_t newPulses = pulseCount - lastPulseCount;   // wrap-safe
    if (newPulses > 0) {
      if (lastHallUs != 0 && newPulses == 1) {
        uint32_t periodUs = pulseUs - lastHallUs;  // handles uint32 wrap correctly
        // Reject implausibly short periods as noise / contact bounce. The ISR now
        // applies the same RPM_MIN_PERIOD_US threshold at the source, so this is a
        // second line of defence rather than the only one — it still catches a short
        // period formed across a buffer wrap. Both must use the same constant.
        if (periodUs >= RPM_MIN_PERIOD_US) {
          // 60e6 µs per minute, divided by pulses per revolution.
          currentRPM = 60.0e6f / (float(periodUs) * float(PULSES_PER_REV));
        }
        // If period too short, keep previous RPM (ignore the glitch pulse)
      }
      // newPulses > 1: edges were missed between iterations. Re-anchor on the
      // latest edge and wait for a clean single-edge interval; do NOT compute a
      // period from an ambiguous multi-revolution span.
      lastHallUs = pulseUs;
      lastPulseCount = pulseCount;
    }

    // Zero RPM if no pulse for > 12 s (below ~5 RPM) — rotor considered stopped
    if (lastHallUs != 0 && (micros() - lastHallUs) > 12000000UL) {
      currentRPM = 0.0f;
    }

    // Log and transmit at TELEMETRY_RATE_HZ
    if (nowMs - lastRpmSendMs >= TELEMETRY_INTERVAL_MS) {
      lastRpmSendMs = nowMs;
      // Round rather than truncate: truncation biased every reading downward by
      // up to 1 RPM.
      uint16_t rpm_u16 = uint16_t(constrain(currentRPM, 0.0f, 65535.0f) + 0.5f);

      // SD log: 5-byte header + 2-byte uint16
      if (!sdError) {
        sdAppendRecord(TYPE_RPM, nowMs, rpm_u16);
      }

      // Radio / USB telemetry packet
      struct __attribute__((packed)) RPMPacket {
        uint8_t  type;
        uint16_t timestamp_10ms;
        uint16_t rpm;
      } rpmPkt = { TYPE_RPM, uint16_t(nowMs / 10), rpm_u16 };
      TELEM_WRITE(rpmPkt);
    }
  }
#endif  // RPM_ENABLE

  // ---- 1 Hz windowed current statistics (radio) ---------------------------
  // Sends the running peak / ∫I dt / ∫I² dt once per second. The accumulators
  // are reset only when the CURRENT_STATS_WINDOW_MS window closes, so each
  // second the ground station sees the window filling up and then a fresh start.
  // Sending every second (rather than once per window) means an operator who
  // connects mid-window still sees data within a second instead of waiting up to
  // two minutes.
  if (nowMs - lastCurrentStatsSend >= 1000UL) {
    lastCurrentStatsSend = nowMs;

    uint32_t windowMs = (statWindowStartMs == 0) ? 0 : (nowMs - statWindowStartMs);

    CurrentStatsPacket statsPkt = {
      TYPE_CURRENT_STATS,
      uint16_t(nowMs / 10),
      uint16_t(windowMs / 1000UL),                    // seconds covered so far
      uint16_t(constrain(float(statPeakCounts) * COUNTS_TO_MA, 0.0f, 65535.0f) + 0.5f),
      float(statCharge_mC),
      float(statI2t_mA2s),
      float(statIntegSec),
      statSamples,
      currentDropped
    };
    TELEM_WRITE(statsPkt);

    // Close the window once it has run its full length. currentDropped is reset with
    // the rest of the window state: leaving it cumulative made it incomparable to the
    // per-window n_samples sitting next to it in the packet (Issue 45).
    if (windowMs >= CURRENT_STATS_WINDOW_MS) {
      statCharge_mC     = 0.0;
      statI2t_mA2s      = 0.0;
      statIntegSec      = 0.0;
      statPeakCounts    = 0;
      statSamples       = 0;
      currentDropped    = 0;
      statWindowStartMs = nowMs;
    }
  }

  // ---- Buffered SD service + periodic durable flush ----------------------
#if SD_BUFFERED_WRITE
  // Drain at most one full sector per loop pass, and avoid starting a normal
  // service write immediately before the next IMU deadline. If the queue is
  // nearly full, backpressure wins over timing slack so data is not discarded.
  if (!sdError && sdQueueUsed >= SD_SECTOR_BYTES &&
      nowMs - lastFlush < FLUSH_INTERVAL_MS) {
    uint32_t serviceNowUs = micros();
    uint32_t untilImuUs = IMU_INTERVAL_US - min(uint32_t(serviceNowUs - lastImuUs),
                                                uint32_t(IMU_INTERVAL_US));
    bool queueUrgent = sdQueueUsed >= SD_QUEUE_BYTES - SD_SECTOR_BYTES;
    if (queueUrgent || untilImuUs >= SD_SERVICE_SLACK_US) {
      sdServiceOneSector();
    }
  }
#endif

  // ---- SD recovery attempt (backoff) --------------------------------------
  // While degraded, retry a remount every SD_RECOVERY_INTERVAL_MS. A transient fault
  // then costs a few seconds of data instead of the entire deployment, which is what
  // the old permanent latch cost. Attempts are capped so a genuinely dead card does not
  // spend the rest of the run re-running SD.begin() in the sampling path.
  if (sdError && sdRecoveryAttempts < SD_MAX_RECOVERY_ATTEMPTS &&
      nowMs - lastSdRecoveryMs >= SD_RECOVERY_INTERVAL_MS) {
    lastSdRecoveryMs = nowMs;
    sdTryRecover();
  }

  // ---- 1 Hz logging-health record (SD only) -------------------------------
  // Written before the flush block so a stall recorded in this interval reaches the card
  // in the same flush. Deliberately not gated on anything but sdError: this record is
  // most valuable precisely when other things are going wrong.
  if (nowMs - lastHealthMs >= 1000UL) {
    lastHealthMs = nowMs;
    if (!sdError) {
      uint8_t healthFlags = 0;
      if (sdError)    healthFlags |= HEALTH_FLAG_SD_ERROR;
      if (!magPresent) healthFlags |= HEALTH_FLAG_NO_MAG;
      if (timerAnomaly) healthFlags |= HEALTH_FLAG_TIMER_ANOM;

      SysHealth health = {
        loopMaxUs,
#if SD_BUFFERED_WRITE
        sdServiceMaxUs,
#else
        0UL,
#endif
        sdWriteFailures,
        sdRecoveries,
#if RPM_ENABLE
        hallEdgeRejected,
        hallEdgeLost,
#else
        0UL, 0UL,
#endif
#if SD_BUFFERED_WRITE
        sdQueueHighWater,
        (uint16_t)min(sdQueueOverruns, uint32_t(65535)),
#else
        0, 0,
#endif
        healthFlags
      };
      sdAppendRecord(TYPE_SYS_HEALTH, nowMs, health);
    }
    // Per-interval maxima reset every second so one bad pass cannot be averaged away.
    // Stash them first: the USB_DEBUG line below runs later in the same pass and would
    // otherwise print the freshly zeroed values.
    reportedLoopMaxUs  = loopMaxUs;
    loopMaxUs = 0;
    timerAnomaly = false;
#if SD_BUFFERED_WRITE
    reportedWriteMaxUs = sdServiceMaxUs;
    sdServiceMaxUs = 0;
#endif
  }

  // flush() forces buffered data to the SD card. Calling it every 5 s limits
  // data loss to at most 5 s of records if power is cut unexpectedly.
  // Skipped when sdError is set — no point flushing a failed card.
  if (!sdError && nowMs - lastFlush >= FLUSH_INTERVAL_MS) {
    sdFlushBuffered();
    lastFlush = nowMs;
  }

  // ---- 1 Hz debug print (USB_DEBUG mode only) -----------------------------
  // Prints buffered-SD diagnostics to USB serial once per second.
  // When USB_DEBUG=0 the DBG_PRINT macros expand to nothing.
  if (nowMs - lastDebugTime >= DEBUG_INTERVAL_MS) {
    lastDebugTime = nowMs;
#if SD_BUFFERED_WRITE
    // loopUs is the headline number when logging looks slow: nominal is ~2700 us, and
    // anything far above that means loop() is not achieving its rate, which starves every
    // gate inside it. maxWriteUs and loopUs are the values the last health record carried,
    // not live counters — see reportedLoopMaxUs.
    DBG_PRINT("SDq="); DBG_PRINT(sdQueueUsed + sdProducerUsed);
    DBG_PRINT("B high="); DBG_PRINT(sdQueueHighWater);
    DBG_PRINT(" loopUs="); DBG_PRINT(reportedLoopMaxUs);
    DBG_PRINT(" maxWriteUs="); DBG_PRINT(reportedWriteMaxUs);
    DBG_PRINT(" overruns="); DBG_PRINTLN(sdQueueOverruns);
#endif
  }

  // ---- 1 Hz system status telemetry (radio) --------------------------------
  // Sends a TYPE_STATUS packet every second so the ground station can display
  // the SD health indicator. Not logged to SD (no point logging an SD error
  // to the SD card that just failed).
  if (nowMs - lastStatusSend >= 1000UL) {
    lastStatusSend = nowMs;
    uint8_t flags = 0;
    if (sdError) flags |= 0x01;  // bit 0 = SD error
    StatusPacket statusPkt = {
      TYPE_STATUS,
      uint16_t(lastStatusSend / 10),
      flags
    };
    TELEM_WRITE(statusPkt);
  }

  // ---- LED heartbeat -------------------------------------------------------
  // Normal operation  : slow 1 Hz toggle (500 ms on / 500 ms off).
  // SD degraded/failed: rapid 4 Hz flash (125 ms on / 125 ms off) so a field
  // operator can see the fault without a USB connection.
  //
  // The state is tracked in a variable rather than read back with
  // digitalRead(LED_PIN). On Apollo3 a pad configured for OUTPUT may have its
  // input buffer disabled, in which case digitalRead() does NOT return the
  // driven level — it returns 0. `!0` is always HIGH, so the LED would latch ON
  // and stop blinking while the firmware ran perfectly normally. That is one of
  // the two ways the reported "LED stops blinking / stays solid on" symptom can
  // happen; the other is loop() stalling, which the health record now measures.
  {
    unsigned long heartbeatInterval = sdError ? 125UL : 500UL;
    if (nowMs - lastHeartbeat >= heartbeatInterval) {
      lastHeartbeat = nowMs;
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState ? HIGH : LOW);
    }
  }
}
