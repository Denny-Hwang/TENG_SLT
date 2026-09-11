# Binary Packet Protocol

> **Status:** Stable  
> **Source file(s):** [`VertiSea.ino`](../VertiSea/VertiSea.ino), [`vertisea_plot_v7.py`](../vertisea_plot_v7.py)  
> **Last reviewed:** 2026-08-18

## Purpose

This document is the **single source of truth** for the binary packet format used by
VertiSea. It defines every packet type written to the SD card and/or transmitted over
the RFD900x radio link. Any change to a packet layout **must** be reflected here, in
`VertiSea.ino`, and in `vertisea_plot_v7.py` simultaneously. (A second MATLAB parser was
retired 2026-09-03; `vertisea_plot_v7.py` is now the only reader.)

The protocol is **frameless** — there is no sync byte or framing wrapper. Packets are
identified by their leading type byte. The ground-station Python script handles
framing loss by scanning byte-by-byte for known type bytes.

All multi-byte integers and floats are **little-endian** (native Artemis Nano / x86 byte order).

---

## Common Header

Every packet begins with a 5-byte header:

| Offset | Size | Type | Field | Description |
|--------|------|------|-------|-------------|
| 0 | 1 | `uint8` | `type` | Packet type ID (see table below) |
| 1 | 4 | `uint32` | `timestamp_ms` | `millis()` since boot, in milliseconds |

The firmware writes this header inside `sdAppendRecord(type, t_ms, payload, payloadBytes)`, which is the single entry point for every SD record and the only place the header layout exists. (An older `writeHeader()` helper no longer exists.)

---

## Packet Type IDs

| ID | Name | Logged to SD | Sent over radio | Rate |
|----|------|:---:|:---:|------|
| `0x01` | `TYPE_FIXED_IMU` | ✓ | ✗ | ~93 Hz (nominal 104) |
| `0x02` | `TYPE_STAB_IMU` | ✓ | ✗ | ~93 Hz (nominal 104) |
| `0x03` | `TYPE_BME` | ✓ | ✓ (15 s) | 1 Hz log / 15 s telem |
| `0x04` | `TYPE_GPS` | ✓ | ✓ (5 s) | 1 Hz log / 5 s telem |
| `0x05` | `TYPE_RTC_EVENT` | ✓ | ✗ | Once at boot |
| `0x06` | `TYPE_TELEM_IMU` | ✗ | ✓ (5 Hz) | 5 Hz telem only |
| `0x07` | `TYPE_MAG` | ✓ | ✗ | ~93 Hz; **absent when `IMU_RAW_ONLY=1`** |
| `0x08` | `TYPE_FIXED_CAL` | ✓ | ✗ | Once at boot |
| `0x09` | `TYPE_STAB_CAL` | ✓ | ✗ | Once at boot |
| `0x0A` | ~~`TYPE_CURRENT`~~ | ✗ | ✗ | **RETIRED 2026-09-03** — legacy logs only |
| `0x0B` | `TYPE_STATUS` | ✗ | ✓ (1 Hz) | 1 Hz radio only |
| `0x0C` | `TYPE_RPM` | ✓ | ✓ (5 Hz) | 5 Hz (`RPM_ENABLE=1` only) |
| `0x0D` | `TYPE_CURRENT_CAL` | ✓ | ✗ | Once at boot |
| `0x0E` | `TYPE_CURRENT_BLOCK` | ✓ | ✗ | ~6.9 Hz (100 samples/record) |
| `0x0F` | `TYPE_CURRENT_STATS` | ✗ | ✓ (1 Hz) | 1 Hz radio only |
| `0x10` | `TYPE_LPF_CAL` | ✓ | ✗ | Once at boot |
| `0x11` | `TYPE_HALL_EDGE` | ✓ | ✗ | Per Hall edge, batched |
| `0x12` | `TYPE_IMU_RAW` | ✓ | ✗ | ~97.5 Hz (`IMU_RAW_ONLY=1` only) |
| `0x13` | `TYPE_BATTERY_CAL` | ✓ | ✗ | Once at boot |
| `0x14` | `TYPE_BATTERY_VOLTAGE` | ✓ | ✓ | 1 Hz |

**Next free ID: `0x15`.**

> **⚠ `0x0A` TYPE_CURRENT was removed on 2026-09-03** — the firmware no longer emits it
> and the ground station no longer parses it over the radio. Its SD payload was a single
> point-sample of the current sensor taken at the telemetry tick, which is a *statistically
> biased* estimator: measured mean 682 counts versus 325 counts for the full-rate `0x0E`
> stream (2.1× high), because a ~100 ms point sample aliases a bursty signal. The SD read
> path is retained so pre-2026-09-03 logs still load. **Use `0x0E` for all quantitative
> work.** Do not average `0x0A`, and do not reuse the ID.

---

## Packet Layouts

### `0x01` — TYPE_FIXED_IMU (SD only, ~93 Hz)

Header (5 bytes) + payload:

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 4 | `float` | `pitch` | degrees |
| 9 | 4 | `float` | `roll` | degrees |
| 13 | 4 | `float` | `heading` | degrees (999.9 = invalid, no mag on fixed IMU) |
| 17 | 4 | `float` | `gx` | °/s (LPF-filtered) |
| 21 | 4 | `float` | `gy` | °/s (LPF-filtered) |
| 25 | 4 | `float` | `gz` | °/s (LPF-filtered) |
| 29 | 4 | `float` | `ax` | g (LPF-filtered) |
| 33 | 4 | `float` | `ay` | g (LPF-filtered) |
| 37 | 4 | `float` | `az` | g (LPF-filtered) |

| 41 | 2 | `uint16` | `interval_us` | measured μs since previous IMU sample |

**Total payload:** 38 bytes. **Total packet:** 43 bytes.

`interval_us` was appended 2026-09-03 to expose the **actual** sample interval, because
the loop does not reliably hit `IMU_RATE_HZ`. It is the measured `micros()` delta captured
before `lastImuUs` advances, saturating at 65535 μs. **No back-compatibility was kept** —
logs written before that date are 41-byte records and will not parse with the current
parsers. Distinguish by file date.

> **⚠ The on-board `pitch`/`roll`/`heading`/`vertDisp` assume a fixed 9.615 ms dt that the
> firmware does not actually achieve.** Measured mean interval is 10.78 ms (≤93 Hz), so
> Madgwick and the vertical integrator run with a systematic dt error — currently ~+12%,
> and ~+82% in the April `04030825` log. Prefer re-deriving attitude offline from the raw
> gyro/accel columns using `interval_us`. See `IDENTIFIED_ISSUES.md`.

Parser reads: 9 floats → `[pitch, roll, heading, gx, gy, gz, ax, ay, az]`, then a
`uint16` `interval_us`. MATLAB: `fread(fid, 9, 'single=>double')` then
`fread(fid, 1, 'uint16')`. Python: `struct.unpack('<9fH', payload)`.

---

### `0x02` — TYPE_STAB_IMU (SD only, ~93 Hz)

Identical layout to `TYPE_FIXED_IMU`. Heading is `999.9` when `isStabilizedIMU = false`
(current operating mode — magnetometer 9-DOF fusion is disabled).

---

### `0x03` — TYPE_BME (SD at 1 Hz; radio at 15 s)

**SD version** — header + payload:

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 4 | `float` | `pressure` | Pa |
| 9 | 4 | `float` | `humidity` | % RH |
| 13 | 4 | `float` | `temperature` | °C |

**Total packet (SD):** 17 bytes.

**Radio version** (`TelemetryBMEPacket`, `__attribute__((packed))`):

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 0 | 1 | `uint8` | `type` | = `0x03` |
| 1 | 2 | `uint16` | `timestamp_10ms` | `millis()/10` |
| 3 | 4 | `float` | `pressure` | Pa |
| 7 | 4 | `float` | `humidity` | % RH |
| 11 | 4 | `float` | `temperature` | °C |

**Total radio packet:** 15 bytes. Python unpack: `struct.unpack('<BHfff', pkt)`.

---

### `0x04` — TYPE_GPS (SD at 1 Hz; radio at 5 s)

**SD version** — header + payload:

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 1 | `uint8` | `satellites` | count |
| 6 | 4 | `float` | `latitude` | degrees |
| 10 | 4 | `float` | `longitude` | degrees |
| 14 | 4 | `float` | `altitude` | metres |

**Total packet (SD):** 18 bytes.

**Radio version** (`TelemetryGPSPacket`, `__attribute__((packed))`):

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 0 | 1 | `uint8` | `type` | = `0x04` |
| 1 | 2 | `uint16` | `timestamp_10ms` | `millis()/10` |
| 3 | 1 | `uint8` | `satellites` | count |
| 4 | 4 | `float` | `latitude` | degrees |
| 8 | 4 | `float` | `longitude` | degrees |

**Total radio packet:** 12 bytes. Python unpack: `struct.unpack('<BHBff', pkt)`.

Note: altitude is **not** transmitted over radio (omitted to save bandwidth).

---

### `0x05` — TYPE_RTC_EVENT (SD only, once at boot)

Header + payload:

| Offset | Size | Type | Field | Notes |
|--------|------|------|-------|-------|
| 5 | 1 | `uint8` | `year_offset` | Years since 2000 (e.g., 25 → 2025) |
| 6 | 1 | `uint8` | `month` | 1–12 |
| 7 | 1 | `uint8` | `day` | 1–31 |
| 8 | 1 | `uint8` | `hour` | 0–23 (**local** time = UTC + `timezoneOffsetHours`) |
| 9 | 1 | `uint8` | `minute` | 0–59 |
| 10 | 1 | `uint8` | `second` | 0–59 |

**Total packet:** 11 bytes. Parser adds 2000 to `year_offset` when writing CSV.

> **Timezone:** all six fields are **local** time (UTC + `timezoneOffsetHours`), matching
> the SD log filename so the record agrees with the wall clock the operator sees. The RTC
> hardware register itself stores UTC. See IDENTIFIED_ISSUES #22.

---

### `0x06` — TYPE_TELEM_IMU (radio only, 5 Hz)

`TelemetryPacket` struct (`__attribute__((packed))`):

| Offset | Size | Type | Field | Units / Notes |
|--------|------|------|-------|---------------|
| 0 | 1 | `uint8` | `type` | = `0x06` |
| 1 | 2 | `uint16` | `timestamp_10ms` | `millis()/10` |
| 3 | 2 | `int16` | `pitch_cdeg` | fixed IMU pitch × 100 (centidegrees; ÷100 → degrees) |
| 5 | 2 | `int16` | `roll_cdeg` | fixed IMU roll × 100 (centidegrees; ÷100 → degrees) |
| 7 | 2 | `int16` | `vertDisp_mm` | vertical displacement × 1000 (mm; ÷1000 → metres) |
| 9 | 2 | `int16` | `stab_pitch_cdeg` | stabilized IMU pitch × 100 (centidegrees; ÷100 → degrees) |
| 11 | 2 | `int16` | `stab_roll_cdeg` | stabilized IMU roll × 100 (centidegrees; ÷100 → degrees) |

**Total packet:** 13 bytes. Python unpack: `struct.unpack('<BHhhhhh', pkt)`.

> **Scale rationale:** Angles are encoded at ×100 (centidegrees) rather than ×1000
> (millidegrees) to extend the `int16_t` range from ±32.767° to **±327.67°**, covering
> the full ±70° operating envelope without overflow. Resolution is 0.01°.

---

### `0x07` — TYPE_MAG (SD only, ~93 Hz)

Header + payload:

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 4 | `float` | `mx` | calibrated, LPF-filtered (arbitrary units post-scale) |
| 9 | 4 | `float` | `my` | calibrated, LPF-filtered |
| 13 | 4 | `float` | `mz` | calibrated, LPF-filtered |

**Total packet:** 17 bytes.

---

### `0x08` — TYPE_FIXED_CAL (SD only, once at boot)

Header + payload (mirrors `IMUCal` struct, 9 floats):

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 4 | `float` | `accel_bias_x` | mg |
| 9 | 4 | `float` | `accel_bias_y` | mg |
| 13 | 4 | `float` | `accel_bias_z` | mg |
| 17 | 4 | `float` | `accel_scale_x` | counts per +1 g |
| 21 | 4 | `float` | `accel_scale_y` | counts per +1 g |
| 25 | 4 | `float` | `accel_scale_z` | counts per +1 g |
| 29 | 4 | `float` | `gyro_bias_x` | millidegrees/s |
| 33 | 4 | `float` | `gyro_bias_y` | millidegrees/s |
| 37 | 4 | `float` | `gyro_bias_z` | millidegrees/s |

> **Units.** `accel_bias` is milli-g and `accel_scale` is milli-g per g (≈1000), because
> the SparkFun driver already scales `sfe_ism_data_t`; these are not raw LSB counts.
> `gyro_bias` is **millidegrees per second** — it is subtracted from the driver's mdps
> value *before* the ×0.001 conversion to °/s. Corrected 2026-09-11; these three fields
> were previously documented as °/s, which made a normal −0.44 °/s offset read as −438 °/s.

**Total packet:** 41 bytes. `TYPE_STAB_CAL` (`0x09`) has identical layout.

---

### `0x0B` — TYPE_STATUS (radio only, 1 Hz)

`StatusPacket` struct (`__attribute__((packed))`):

| Offset | Size | Type | Field | Units / Notes |
|--------|------|------|-------|---------------|
| 0 | 1 | `uint8` | `type` | = `0x0B` |
| 1 | 2 | `uint16` | `timestamp_10ms` | `millis()/10` |
| 3 | 1 | `uint8` | `flags` | bit 0 = `sdError` (0=OK, 1=SD failure) |

**Total radio packet:** 4 bytes. Python unpack: `struct.unpack('<BHB', pkt)`.
Not logged to SD.

---

### `0x0A` — ~~TYPE_CURRENT~~ — **RETIRED 2026-09-03** (read-only, legacy logs)

**SD version** — header + payload:

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 2 | `uint16` | `counts` | raw 14-bit ADC counts |

**Total packet (SD):** 7 bytes.

**Radio version** (`CurrentPacket`, packed): 1 B type + 2 B `timestamp_10ms` +
2 B `current_mA` = **5 bytes**. Python unpack: `struct.unpack('<BHH', pkt)`.

Note the SD form carries raw **counts** while the radio form carries **milliamps** —
the buoy converts for the live display because the ground station may connect after
boot and miss the once-only `0x0D` cal record.

> **⚠ RETIRED — the firmware no longer writes or transmits this.** Both the SD write and the
> radio packet were removed on 2026-09-03; `vertisea_plot_v7.py` still *reads* it so logs
> recorded before that date continue to parse. **Do not use it for quantitative analysis.**
> The value is a single point sample
> of `currentCounts` captured at the telemetry tick, so it aliases a bursty signal.
> Measured against the full-rate `0x0E` stream over the same run: mean **682** counts
> vs **325** counts — **2.1× biased high**, because a ~100 ms point sample rarely lands
> on the low-amplitude majority (41% of true samples fall in 50–200 counts, but only
> 13.5% of the point samples do). Peak happened to agree, which is luck not design.
> **Use `0x0E`.** This packet is scheduled for removal.

---

### `0x0D` — TYPE_CURRENT_CAL (SD only, once at boot)

Makes each log self-describing: the constants needed to turn `0x0A`/`0x0E` raw counts
into milliamps, so a log can be interpreted without knowing which firmware build or
sensor produced it.

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 4 | `float` | `vref` | ADC reference (V) |
| 9 | 4 | `float` | `adc_max` | full-scale count |
| 13 | 4 | `float` | `div_ratio` | input divider (1.0 = none) |
| 17 | 4 | `float` | `sens_mA_per_V` | sensor sensitivity |

**Total packet:** 21 bytes.

Conversion: `mA = counts / adc_max * vref * div_ratio * sens_mA_per_V`.

---

### `0x0E` — TYPE_CURRENT_BLOCK (SD only, variable length)

Batched high-rate current samples. **This is the authoritative current record.**

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 2 | `uint16` | `span_ms` | measured first-to-last sample time |
| 7 | 2 | `uint16` | `count` | number of samples following |
| 9 | 2×count | `uint16[]` | `counts` | raw 14-bit ADC counts |

**Total packet:** `9 + 2×count` bytes (209 B at the usual count = 100).

`span_ms` is the **measured** elapsed time, deliberately not a nominal rate: the loop
cannot guarantee `CURRENT_RATE_HZ`. Reconstruct sample *i* at
`t_ms + i × span_ms / (count - 1)`; recover the effective rate as
`(count - 1) / (span_ms / 1000)`.

Measured achieved rate against a 1000 Hz request:

| Log | I²C clock | Aggregate | Within-block (median) |
|-----|-----------|-----------|-----------------------|
| `09021931` | 100 kHz | 373 Hz | — |
| `09031050` | 400 kHz | **693 Hz** | **767 Hz** |

Current sampling runs on spare loop time, so it absorbs almost all of any latency freed
elsewhere: raising I²C to 400 kHz nearly doubled it (1.86×), far more than the IMU gained
(1.04×), because the IMU is gated to a fixed target while this sampler is not.

The aggregate rate sits ~10% below the within-block rate: blocks arrive every ~145 ms but
span only ~129 ms, leaving ~16 ms of dead time per block for the 209-byte SD write.

---

### `0x0F` — TYPE_CURRENT_STATS (radio only, 1 Hz)

Windowed statistics over `CURRENT_STATS_WINDOW_MS` (2 min), so peak and average power
reach the ground station without transmitting the waveform.

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 0 | 1 | `uint8` | `type` | = `0x0F` |
| 1 | 2 | `uint16` | `timestamp_10ms` | `millis()/10` |
| 3 | 2 | `uint16` | `window_s` | wall-clock window length |
| 5 | 2 | `uint16` | `peak_mA` | peak in window |
| 7 | 4 | `float` | `charge_mC` | ∫I dt |
| 11 | 4 | `float` | `i2t_mA2s` | ∫I² dt |
| 15 | 4 | `float` | `integ_s` | **true** integration time Σdt |
| 19 | 4 | `uint32` | `n_samples` | samples contributing |
| 23 | 4 | `uint32` | `n_dropped` | ticks missed vs requested rate |

**Total radio packet:** 27 bytes. Python unpack: `struct.unpack('<BHHHfffII', pkt)`.

**Average current is `charge_mC / integ_s`, RMS is `sqrt(i2t_mA2s / integ_s)` — NOT
divided by `window_s`.** The two differ whenever the sampler misses its requested rate;
using wall-clock time understated both by 2.65× before this field existed.

`n_dropped` counts ticks missed against the **requested** rate. It reads large (~600/s)
because 1000 Hz is a deliberate over-request; that is **not** data loss, and the
integrals are unaffected because they use measured intervals. Judge sampling health from
`n_samples / window_s`, not from `n_dropped`.

`0x0F` remains current-only. Pair it with the latest 1 Hz `0x14` battery voltage for a live
average-power estimate, or interpolate the archived `0x14` voltage samples against the high-rate
`0x0E` current samples for offline ∫V·I dt.

---

### `0x10` — TYPE_LPF_CAL (SD only, once at boot)

13 floats. Makes the IMU low-pass filter invertible offline.

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 5 | 4 | `float` | `alpha_acc` |
| 9 | 4 | `float` | `alpha_gyro` |
| 13 | 4 | `float` | `alpha_mag` |
| 17 | 4 | `float` | `accel_cutoff_hz` |
| 21 | 4 | `float` | `gyro_cutoff_hz` |
| 25 | 4 | `float` | `mag_cutoff_hz` |
| 29 | 4 | `float` | `imu_rate_hz` |
| 33 | 12 | `float[3]` | `mag_offset[]` (hard-iron) |
| 45 | 12 | `float[3]` | `mag_scale[]` (soft-iron) |

**Total packet:** 57 bytes.

The logged IMU values are LPF-**filtered**, but the 1-pole IIR is exactly invertible:

```
x[n] = y[n-1] + (y[n] - y[n-1]) / alpha
```

Recovery is bit-exact after rounding (verified: max error < 0.005 counts across
accel/gyro/mag, holding up under smooth signals and %.6f CSV rounding). Undo the
bias/scale from `0x08`/`0x09` to reach raw counts. Without these constants the inversion
is impossible, since alpha derives from compile-time cutoffs.

---

### `0x11` — TYPE_HALL_EDGE (SD only, batched)

Raw Hall falling-edge timestamps, so RPM can be re-derived offline rather than trusting
a decimated on-board estimate.

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 1 | `uint8` | `count` | edges following |
| 6 | 4×count | `uint32[]` | `edge_us` | raw `micros()` timestamps |

**Total packet:** `6 + 4×count` bytes. ~133 B/s at 2000 RPM with one magnet.

Timestamps are raw `micros()` so inter-edge periods stay exact; the header's `millis()`
anchors them to the rest of the log. `micros()` wraps every ~71.6 min — use modulo-2³²
subtraction. **`PULSES_PER_REV` is a mechanical property and is NOT in the log**; both
parsers assume one magnet and say so.

---

### `0x0C` — TYPE_RPM (SD + radio, 5 Hz, `RPM_ENABLE=1` only)

**SD version** — header + payload:

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 2 | `uint16` | `rpm` | Rotor speed in RPM (0–65535) |

**Total packet (SD):** 7 bytes.

**Radio version** (`RPMPacket`, `__attribute__((packed))`):

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 0 | 1 | `uint8` | `type` | = `0x0C` |
| 1 | 2 | `uint16` | `timestamp_10ms` | `millis()/10` |
| 3 | 2 | `uint16` | `rpm` | Rotor speed in RPM (0–65535) |

**Total radio packet:** 5 bytes. Python unpack: `struct.unpack('<BHH', pkt)`.

> **When `RPM_ENABLE=0`:** This packet type is never emitted. The SD parser and Python
> ground station should handle its absence gracefully (the type simply never appears).

---

### `0x12` — TYPE_IMU_RAW (SD only, `IMU_RAW_ONLY=1` builds)

Written **instead of** `TYPE_FIXED_IMU` + `TYPE_STAB_IMU` + `TYPE_MAG` when the firmware is
built with `IMU_RAW_ONLY 1`. A log contains either the processed records or these, **never
both**. Attitude and magnetometer are absent — recompute attitude offline from these values
using the boot-time `0x08`/`0x09`/`0x10` records.

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 2 | `int16` | `fix_ax` | milli-g |
| 7 | 2 | `int16` | `fix_ay` | milli-g |
| 9 | 2 | `int16` | `fix_az` | milli-g |
| 11 | 4 | `int32` | `fix_gx` | mdps |
| 15 | 4 | `int32` | `fix_gy` | mdps |
| 19 | 4 | `int32` | `fix_gz` | mdps |
| 23 | 2 | `int16` | `stab_ax` | milli-g |
| 25 | 2 | `int16` | `stab_ay` | milli-g |
| 27 | 2 | `int16` | `stab_az` | milli-g |
| 29 | 4 | `int32` | `stab_gx` | mdps |
| 33 | 4 | `int32` | `stab_gy` | mdps |
| 37 | 4 | `int32` | `stab_gz` | mdps |
| 41 | 2 | `uint16` | `interval_us` | measured μs since previous sample |

**Total payload:** 38 bytes. **Total packet:** 43 bytes.
Python unpack: `struct.unpack('<3h3i3h3iH', payload)`.
The firmware guards the layout with `static_assert(sizeof(ImuRawRec) == 38)`.

**These are NOT raw LSB counts.** `sfe_ism_data_t` is already scaled by the SparkFun driver:
accel is **milli-g**, gyro is **millidegrees/second**. They are *uncalibrated* — no bias, no
scale, no LPF — but not unscaled. To recover engineering units apply the `0x08`/`0x09` bias
and scale as the firmware does, then optionally the `0x10` alphas to reproduce the LPF.

**The asymmetric widths are mandatory, not stylistic.** At the configured `ISM_500dps` the
gyro reaches 500000 mdps, **15× the `int16` range**; accel at `ISM_4g` peaks near 4000 mg, so
`int16` (±32767) is ample. An earlier revision stored gyro as `int16` and **wrapped sign on
every fast rotation** — see `IDENTIFIED_ISSUES.md` Issue 35. Do **not** narrow the gyro under
any scaling that depends on the full-scale setting: centi-dps would clip at 327.67 dps, and a
true-LSB divisor would silently overflow again if the FS were raised.

> **⚠ Logs written on 2026-09-03 with a 31-byte `0x12` record predate the fix** and have
> corrupt gyro columns (their accel columns are still valid). They will not parse with the
> current 43-byte reader — it desyncs and reports an unknown packet type, which is deliberate:
> failing loudly beats silently emitting plausible garbage.

**Sensor-level clipping is separate.** The gyro also saturates at the ISM330DHCX's own
register rail, 32767 × 17.5 mdps/LSB = **573422 mdps (573.4 dps)** at `ISM_500dps`. Values
pinned at exactly −573370/+573370 are the sensor clipping, not a logging defect — no logging
change can recover them.

---

### `0x13` — TYPE_BATTERY_CAL (SD only, once at boot)

Archives the ADC and divider constants needed to convert the raw `0x14` SD records.

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 4 | `float` | `vref` | V |
| 9 | 4 | `float` | `adc_max` | counts |
| 13 | 4 | `float` | `r_top_ohm` | Ω, battery-to-ADC resistor |
| 17 | 4 | `float` | `r_bottom_ohm` | Ω, ADC-to-ground resistor |
| 21 | 4 | `float` | `div_ratio` | `(Rtop + Rbottom) / Rbottom` |

**Total packet:** 25 bytes. Python unpack: `struct.unpack('<5f', payload)`.

The initial 30 kΩ / 20 kΩ values are placeholders and must be replaced by measured installed
values before deployment. Their 2.5:1 ratio maps a 4.2 V 1S Li-ion cell to 1.68 V at the ADC.

---

### `0x14` — TYPE_BATTERY_VOLTAGE (SD + radio, 1 Hz)

Battery voltage from A15 (Apollo3 pad 32 / ADC SE4) through the divider documented by `0x13`.

**SD version** — header plus one raw sample:

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 5 | 2 | `uint16` | `counts` | raw 14-bit ADC counts |

**Total SD packet:** 7 bytes. Convert with
`voltage_V = counts / adc_max × vref × div_ratio`.

**Radio version** (`BatteryVoltagePacket`, packed):

| Offset | Size | Type | Field | Units |
|--------|------|------|-------|-------|
| 0 | 1 | `uint8` | `type` | = `0x14` |
| 1 | 2 | `uint16` | `timestamp_10ms` | `millis()/10` |
| 3 | 2 | `uint16` | `battery_mV` | mV |

**Total radio packet:** 5 bytes. Python unpack: `struct.unpack('<BHH', pkt)`.

The ground station retains the latest 1 Hz battery voltage and multiplies it by the running
average current from `0x0F` to display average power in mW. `0x0F` remains unchanged to preserve
its verified packet layout; full offline `V(t)·I(t)` integration can interpolate the slowly
varying 1 Hz voltage against the high-rate current CSV.

---

## Known Constraints and Gotchas

- The SD and radio versions of `TYPE_BME` and `TYPE_GPS` differ in structure (SD uses
  the 5-byte common header; radio uses a packed struct with a 2-byte `uint16` timestamp).
  `vertisea_plot_v7.py` handles **both**: `parse_binary_file()` reads the SD form, and the
  live serial reader handles the radio form.
- `TYPE_RPM` is only present in logs/telemetry when `RPM_ENABLE=1` is compiled in.
- `TYPE_STATUS` (`0x0B`) is radio-only and is never written to SD.
- There is no CRC or checksum. Packet integrity relies on the radio link quality.
- `vertisea_plot_v7.py` skips known-but-unhandled SD packet types using the
  `_SD_PAYLOAD_BYTES` lookup table, so a type it does not decode cannot desynchronise the
  parse. **Variable-length types (`0x0E`, `0x11`) are deliberately absent** from that table
  — their size is not knowable without reading the payload, so they must always have an
  explicit handler.

## Rejected Approaches

- **Framing with sync bytes** — considered to allow re-synchronisation after byte loss.
  Rejected because the radio link is generally reliable and the added overhead (2+ bytes
  per packet) at the nominal 104 Hz IMU rate would increase SD write load — a real concern,
  since SD block flushes were later measured to be the dominant cap on IMU rate (Issue 34). The byte-scan approach
  in the Python script handles occasional loss adequately.
- **ASCII/CSV telemetry** — rejected due to bandwidth constraints at 115200 baud with
  104 Hz IMU data.
