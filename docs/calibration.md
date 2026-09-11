# Sensor Calibration — VertiSea Buoy

> **Status:** Active  
> **Source files:** [`VertiSea.ino`](../VertiSea/VertiSea.ino), [`Calibration/calibrateMag.m`](../Calibration/calibrateMag.m)  
> **Last reviewed:** 2026-08-18

---

## Overview

The VertiSea buoy carries three sensors that require offline calibration before deployment:

| Sensor | Type | Calibration needed | When to redo |
|--------|------|--------------------|--------------|
| ISM330DHCX (fixed IMU, `0x6A`) | 6-DOF accel + gyro | Accel bias/scale, gyro bias | After physical damage or if attitude errors grow |
| ISM330DHCX (stabilized IMU, `0x6B`) | 6-DOF accel + gyro | Accel bias/scale, gyro bias | After physical damage or if attitude errors grow |
| MMC5983MA (magnetometer) | 3-axis mag | Hard-iron offset, soft-iron scale | After any change to the buoy's metal/magnetic environment |

Calibration constants are **hard-coded** in [`VertiSea.ino`](../VertiSea/VertiSea.ino) as the `fixedCal`, `stabCal`, and `magCal` structs. They are also written to the binary log at boot as `TYPE_FIXED_CAL` (0x08) and `TYPE_STAB_CAL` (0x09) packets so the parser can reconstruct physical units without a sidecar file.

---

## 1. IMU Calibration (ISM330DHCX)

### 1.1 What is being calibrated

The `IMUCal` struct in [`VertiSea.ino`](../VertiSea/VertiSea.ino) holds three arrays per IMU:

```cpp
struct IMUCal {
  float accel_bias[3];   // accelerometer zero-g bias (mg)
  float accel_scale[3];  // accelerometer sensitivity (counts per +1 g)
  float gyro_bias[3];    // gyroscope zero-rate bias (MILLIDEGREES/S)
};
```

These are applied in [`collectIMUData_ISM()`](../VertiSea/VertiSea.ino) before the low-pass filter and Madgwick update:

```
ax_g = -(raw_x - accel_bias[0]) / accel_scale[0]   ← X axis negated (body-frame convention)
ay_g =  (raw_y - accel_bias[1]) / accel_scale[1]
az_g =  (raw_z - accel_bias[2]) / accel_scale[2]

gx_dps =  (raw_x - gyro_bias[0]) * 0.001           ← mdps → dps
gy_dps = -(raw_y - gyro_bias[1]) * 0.001            ← Y axis negated (body-frame convention)
gz_dps =  (raw_z - gyro_bias[2]) * 0.001
```

> **Note on axis signs:** The X-accel and Y-gyro negations are body-frame conventions specific to how the IMU boards are physically mounted in the buoy. Do **not** remove them.

---

### 1.2 Equipment needed

- USB cable to the SparkFun RedBoard Artemis Nano
- Arduino IDE or Serial Monitor (115200 baud)
- Flat, level surface
- A precision spirit level (optional but recommended)

---

### 1.3 Accelerometer bias and scale calibration

The ISM330DHCX is configured at **±4 g full-scale** and **104 Hz ODR**. The raw output is in milligravity (mg) units from the SparkFun driver.

#### Procedure

1. **Set `USB_DEBUG 1`** (and `USB_TELEM 0`) in [`VertiSea.ino`](../VertiSea/VertiSea.ino) and flash
   the firmware. Do not set both flags to `1` — see the flag-combination caution in
   [`firmware.md`](firmware.md).

2. **Six-position static test.** Place the buoy (or just the IMU board) in each of the six cardinal orientations — +X up, −X up, +Y up, −Y up, +Z up, −Z up — and record the mean raw accelerometer output for each axis over ≥ 5 seconds. Use the 1 Hz debug print or log the `TYPE_FIXED_CAL` / `TYPE_STAB_CAL` CSV from the parser.

   | Position | Expected output |
   |----------|----------------|
   | +Z up (flat, normal) | ax ≈ 0 mg, ay ≈ 0 mg, az ≈ +1000 mg |
   | −Z up (upside down) | ax ≈ 0 mg, ay ≈ 0 mg, az ≈ −1000 mg |
   | +X up | ax ≈ +1000 mg, ay ≈ 0 mg, az ≈ 0 mg |
   | −X up | ax ≈ −1000 mg, ay ≈ 0 mg, az ≈ 0 mg |
   | +Y up | ax ≈ 0 mg, ay ≈ +1000 mg, az ≈ 0 mg |
   | −Y up | ax ≈ 0 mg, ay ≈ −1000 mg, az ≈ 0 mg |

3. **Compute bias and scale** for each axis i:

   ```
   bias[i]  = (pos_reading[i] + neg_reading[i]) / 2
   scale[i] = (pos_reading[i] - neg_reading[i]) / 2
   ```

   Where `pos_reading` is the mean raw output when +1 g is applied to axis i, and `neg_reading` is the mean when −1 g is applied.

4. **Update the firmware.** Edit the `fixedCal` or `stabCal` struct in [`VertiSea.ino`](../VertiSea/VertiSea.ino):

   ```cpp
   IMUCal fixedCal = {
     {   3.5f,  -25.0f,   10.0f },   // accel bias  [X, Y, Z] (mg)
     {1004.5f, 1007.0f,  999.0f },   // accel scale [X, Y, Z] (counts/g)
     {  -2.36f, -396.8f, -192.5f }   // gyro bias   [X, Y, Z] (mdps)
   };
   ```

   Replace the values with your measured results and reflash. (The block above shows the
   **current committed** values — see §1.5.)

---

### 1.4 Gyroscope bias calibration

Gyroscope bias (zero-rate offset) drifts slowly with temperature. Recalibrate if heading or attitude drifts noticeably at rest.

#### Procedure

1. Place the buoy on a **completely stationary** surface. Vibration from fans, HVAC, or nearby machinery will corrupt the measurement.

2. Log at least **60 seconds** of data with the buoy at rest. Parse the `.BIN` with `vertisea_plot_v7.py` (**Load BIN File**) to extract the `_imuFixed.csv` and `_imuStab.csv` files. This requires an `IMU_RAW_ONLY 0` build; an `IMU_RAW_ONLY 1` log gives you `_imuRaw.csv` instead, whose gyro columns are already the raw **millidegrees/s** this procedure needs.

3. Compute the mean of the gyro columns over the stationary period, then convert to the units `gyro_bias[]` actually uses.

   > **⚠ Unit trap — corrected 2026-09-11.** `IMUCal.gyro_bias[]` is in **millidegrees per second**, not °/s. The firmware subtracts it from the driver's mdps value *before* the ×0.001 conversion:
   >
   > ```
   > gx_dps = (gyroData.xData /* mdps */ - gyro_bias[0] /* mdps */) * 0.001
   > ```
   >
   > The `_imuFixed` / `_imuStab` CSV columns, by contrast, are already in **°/s** and are already bias-corrected, so they carry the *residual*. To update the constant:
   >
   > ```
   > gyro_bias_new[i] = gyro_bias_old[i] + mean(residual_dps[i]) * 1000
   > ```
   >
   > An `_imuRaw` CSV (`IMU_RAW_ONLY 1` build) is easier: its `*_gx_mdps` columns are the uncalibrated driver output in mdps, so the mean *is* the new bias directly, with no arithmetic on the old value.
   >
   > This document previously said the bias was in °/s and instructed "do not multiply by 1000". Following that gives a correction 1000× too small — see the 2026-04-02 entry in the calibration history below.

4. Update `gyro_bias[3]` in the appropriate `IMUCal` struct and reflash.

#### Acceptance criteria

After applying the new bias, the mean gyro output at rest should be < 0.05 °/s (< 50 mdps) on all axes. Standard deviation should be < 0.5 °/s.

---

### 1.5 Current IMU calibration values

These values are hard-coded in [`VertiSea.ino`](../VertiSea/VertiSea.ino):

**Fixed IMU (hull-fixed, I²C `0x6A`)**

| Parameter | X | Y | Z | Units |
|-----------|---|---|---|-------|
| `accel_bias` | 3.5 | −25.0 | 10.0 | mg |
| `accel_scale` | 1004.5 | 1007.0 | 999.0 | counts/g |
| `gyro_bias` | −2.36 | −396.8 | −192.5 | mdps (= −0.002 / −0.397 / −0.193 °/s) |

**Stabilized IMU (gimballed platform, I²C `0x6B`)**

| Parameter | X | Y | Z | Units |
|-----------|---|---|---|-------|
| `accel_bias` | −3.0 | −15.0 | 22.5 | mg |
| `accel_scale` | 1001.0 | 994.0 | 1003.5 | counts/g |
| `gyro_bias` | 384.5 | −438.56 | 113.3 | mdps (= 0.385 / −0.439 / 0.113 °/s) |

> **Note:** These values are in **millidegrees per second**. The stabilized IMU's Y bias of −438.56 mdps is −0.44 °/s — an ordinary zero-rate offset. (This note previously read them as °/s and claimed a −438 °/s bias was "normal for this sensor"; it is not — that would be a sensor pegged near its ±500 °/s full scale.) They must be subtracted before the Madgwick update.

---

## 2. Magnetometer Calibration (MMC5983MA)

### 2.1 What is being calibrated

The MMC5983MA outputs raw 18-bit counts per axis (range 0–262143, midpoint ≈ 131072). Two distortion sources must be corrected:

| Distortion | Cause | Correction |
|------------|-------|------------|
| **Hard-iron** | Permanent magnetic fields from nearby ferrous metal, PCB traces, or permanent magnets | Subtract a fixed offset per axis |
| **Soft-iron** | Magnetically permeable materials that distort the field shape | Multiply by a per-axis scale factor |

The `MagCal` struct in [`VertiSea.ino`](../VertiSea/VertiSea.ino):

```cpp
struct MagCal {
  float offset[3];  // hard-iron offset [X, Y, Z] (raw counts)
  float scale[3];   // soft-iron scale  [X, Y, Z] (normalised)
} magCal = {
  { 129992.4f, 129465.3f, 128479.9f},  // hard-iron offsets
  {    155.97f,   1057.42f,  1777.06f} // soft-iron scales
};
```

Applied in [`collectIMUData_ISM()`](../VertiSea/VertiSea.ino):

```cpp
float mx = (float(mxRaw) - magCal.offset[0]) * magCal.scale[0];
float my = (float(myRaw) - magCal.offset[1]) * magCal.scale[1];
float mz = (float(mzRaw) - magCal.offset[2]) * magCal.scale[2];
```

---

### 2.2 When to recalibrate

Recalibrate the magnetometer whenever:

- The buoy's physical structure changes (new hardware, different mounting)
- The buoy is deployed in a new geographic region with significantly different magnetic inclination
- Heading accuracy degrades noticeably (> 5° error at known headings)
- The magnetometer or its mounting bracket is replaced

Do **not** recalibrate unnecessarily — the current values are stable as long as the hardware is unchanged.

---

### 2.3 Equipment needed

- USB cable to the Artemis Nano
- Arduino IDE or Serial Monitor
- Open area away from large metal objects, vehicles, and power lines (≥ 5 m clearance)
- `vertisea_plot_v7.py` (**Load BIN File**) to extract the mag CSV
- MATLAB with [`Calibration/calibrateMag.m`](../Calibration/calibrateMag.m)

---

### 2.4 Step 1 — Enable the magnetometer in firmware

The magnetometer is currently **disabled** in the main loop. Before collecting calibration data, enable it:

1. Open [`VertiSea.ino`](../VertiSea/VertiSea.ino).

2. Find the two `collectIMUData_ISM` calls in `loop()`:

   ```cpp
   lastFixedIMU = collectIMUData_ISM(imuFixed, filterFixed, fixedCal, false, lpfFixed);
   lastStabIMU  = collectIMUData_ISM(imuStab,  filterStab,  stabCal,  false, lpfStab);
   ```

3. Change the **second** call's fourth argument from `false` to `true`:

   ```cpp
   lastStabIMU  = collectIMUData_ISM(imuStab,  filterStab,  stabCal,  true,  lpfStab);
   ```

4. Set `USB_DEBUG 1` and flash the firmware.

> **Why only the stabilized IMU?** The MMC5983MA is physically mounted on the stabilized (gimballed) platform. The fixed IMU does not have a magnetometer.

---

### 2.5 Step 2 — Collect a full-sphere sweep

The ellipsoid-fit algorithm requires the magnetometer to sample all orientations uniformly. A sparse or planar sweep will produce a degenerate fit.

#### Procedure

1. Power on the buoy and confirm the SD card is logging (LED heartbeats at 1 Hz).

2. **Move to an open area** — at least 5 m from vehicles, metal structures, and power lines. Avoid concrete floors with rebar.

3. **Slowly rotate the buoy through all orientations** over 3–5 minutes:
   - Roll 360° while pitched forward 45°
   - Roll 360° while pitched backward 45°
   - Roll 360° while pitched left 45°
   - Roll 360° while pitched right 45°
   - Yaw 360° while flat
   - Yaw 360° while tilted 30° in each direction

   The goal is to trace a dense, uniform point cloud on the surface of a sphere in (Mx, My, Mz) space.

4. **Minimum sample count:** 500 valid (non-zero) rows in the mag CSV. More is better; 2000+ gives a robust fit.

5. Power off and retrieve the SD card.

---

### 2.6 Step 3 — Extract the magnetometer CSV

Parse the binary log with the Python ground station:

```
python vertisea_plot_v7.py     # then click "Load BIN File"
```

This produces `MMDDHHMM_mag.csv` with columns:

```
timestamp_ms, mx, my, mz
```

Where `mx`, `my`, `mz` are the **calibrated** magnetometer values (the firmware applies the existing `magCal` before logging). 

> **Important:** For a fresh calibration run, you need the **raw** counts, not the pre-calibrated values. To log raw counts, temporarily set `magCal.offset = {0,0,0}` and `magCal.scale = {1,1,1}` in the firmware before collecting data. This ensures the CSV contains unmodified sensor output.

---

### 2.7 Step 4 — Run the MATLAB calibration script

Open MATLAB and run [`Calibration/calibrateMag.m`](../Calibration/calibrateMag.m):

```matlab
[center, scale, Mcal] = calibrateMag('path/to/MMDDHHMM_mag.csv');
```

#### What the script does

1. **Loads** the CSV and discards all-zero rows (invalid samples where the sensor was not ready).
2. **Fits an ellipsoid** to the raw (Mx, My, Mz) point cloud using algebraic least-squares (SVD).
3. **Extracts the ellipsoid centre** → hard-iron offset (`center`).
4. **Computes per-axis scale factors** so the calibrated data lies on a unit sphere (`scale`).
5. **Prints** the results and a firmware-ready C struct.
6. **Plots** before/after 3D scatter and radius histograms.

#### Expected console output

```
Total rows: 3309   Valid (non-zero): 2847   Discarded: 462

--- Calibration Results ---
Hard-iron offsets (center): [129992.4000, 129465.3000, 128479.9000]
Soft-iron scales:           [0.006411, 0.000946, 0.000563]

Raw data:  mean radius = 131072.000,  std = 4821.234
Cal data:  mean radius = 1.0000,  std = 0.0312
           (ideal: mean=1.0000, std→0)

--- Paste into VertiSea.ino (MagCal block) ---
} magCal = {
  { 129992.4000f, 129465.3000f, 128479.9000f},  // hard-iron offsets
  { 0.006411f, 0.000946f, 0.000563f}   // soft-iron scales
};
```

#### Acceptance criteria

| Metric | Acceptable | Good |
|--------|-----------|------|
| Calibrated mean radius | 0.95 – 1.05 | 0.99 – 1.01 |
| Calibrated std of radius | < 0.10 | < 0.03 |
| Valid sample count | ≥ 200 | ≥ 500 |

If the calibrated std is > 0.10, the data coverage was insufficient. Repeat the sweep with more orientations.

---

### 2.8 Step 5 — Update the firmware

1. Copy the C struct block printed by the script.

2. Open [`VertiSea.ino`](../VertiSea/VertiSea.ino) and find the `MagCal` block (around line 265):

   ```cpp
   } magCal = {
     { 129992.4f, 129465.3f, 128479.9f},  // hard-iron offsets
     {    155.97f,   1057.42f,  1777.06f} // soft-iron scales
   };
   ```

3. Replace the numeric values with the new calibration constants from the script output.

4. Reflash the firmware.

5. Verify by logging a short stationary session and checking that the calibrated mag radius is stable near 1.0 in the CSV.

---

### 2.9 Re-enable or disable the magnetometer

After calibration, decide whether to run the stabilized IMU in **6-DOF** (accel + gyro only) or **9-DOF** (accel + gyro + mag) mode:

| Mode | `isStabilizedIMU` arg | Heading output | Use case |
|------|-----------------------|----------------|----------|
| 6-DOF | `false` | `999.9°` (sentinel) | Wave height / pitch / roll only |
| 9-DOF | `true` | Valid 0–360° | Heading-referenced navigation |

Change the argument in `loop()` as described in Step 1 above.

> **Current deployment setting:** `false` (6-DOF). Heading is not required for the current Arctic TENG wave-energy measurement campaign.

---

## 3. Calibration File Reference

### 3.1 Calibration/calibrateMag.m

| Item | Detail |
|------|--------|
| **Input** | CSV with header `timestamp_ms,mx,my,mz` (raw MMC5983MA counts) |
| **Outputs** | `center` (1×3 hard-iron offset), `scale` (1×3 soft-iron scale), `Mcal` (N×3 calibrated data) |
| **Algorithm** | Algebraic ellipsoid fit via SVD; per-axis scale from diagonal of quadric matrix |
| **Zero filtering** | All-zero rows are automatically discarded before fitting |
| **Minimum samples** | 50 valid rows (hard error); 500+ recommended |
| **Degenerate fit detection** | Checks positive-definiteness of A; checks c_val > 0; checks real positive semi-axes |

### 3.2 Calibration/calibration.xlsx

The [`Calibration/calibration.xlsx`](../Calibration/calibration.xlsx) spreadsheet contains the raw six-position IMU calibration measurements used to derive the current `fixedCal` and `stabCal` values. Update this file whenever IMU calibration is redone.

---

## 4. Calibration Log

Keep a record of when calibrations were performed and what changed.

| Date | Sensor | Reason | Performed by | Notes |
|------|--------|--------|--------------|-------|
| 2025-05-30 | MMC5983MA | Initial deployment | PNNL team | Full-sphere sweep, 2847 valid samples |
| 2025-05-30 | ISM330DHCX (both) | Initial deployment | PNNL team | Six-position accel + 60 s gyro bias |
| 2026-04-02 | ISM330DHCX (both) | Pre-deployment recalibration | PNNL team | Six-position accel (both IMUs updated); gyro bias from 19.4 s stationary log (04021311.BIN). Fixed IMU gyro within spec — no change. Stab IMU gy updated −438.5 → −438.56 (residual was −0.065 °/s, just over the 0.05 °/s threshold). **⚠ This correction is wrong by 1000×:** −0.065 °/s is −65 mdps, so the constant should have become ≈ −503.5 mdps, not −438.56. The 2026-04-02 stab-IMU Y bias is therefore effectively unchanged and the residual remains. Re-derive it before the next deployment. |

---

## 5. Troubleshooting

### Magnetometer reads all zeros in the CSV

The firmware logs `(0, 0, 0)` when:
- `isStabilizedIMU = false` (magnetometer disabled — most common cause)
- `mag.getMeasurementXYZ()` returns `false` (I²C error or sensor not ready)

Check that `isStabilizedIMU = true` is passed to `collectIMUData_ISM()` for the stabilized IMU call in `loop()`.

### calibrateMag.m throws "insufficient data" error

The CSV contains fewer than 50 valid (non-zero) rows. Either:
- The magnetometer was disabled during logging (see above)
- The log file is too short — collect more data

### Calibrated radius std is > 0.10

The point cloud does not cover the full sphere. Repeat the sweep, paying attention to:
- Tilting the buoy to ±45° in all directions (not just yaw)
- Moving slowly enough for the 104 Hz magnetometer to sample densely

### Heading drifts after calibration

1. Verify the calibration was collected away from magnetic interference.
2. Check that the `magCal` values in the firmware match the script output exactly.
3. Ensure the Madgwick filter beta parameter is appropriate — a very low beta will cause slow heading convergence.

### Large gyro bias values

The ISM330DHCX gyro bias can be several hundred **millidegrees/s** (a few tenths of a °/s) at room temperature. This is normal. The constants in `IMUCal.gyro_bias[]` are stored in mdps, which is why they look like large numbers. The bias is subtracted in firmware before the Madgwick update. If it changes significantly between sessions, recalibrate the gyro.

---

## 6. Related Documentation

- [`docs/firmware.md`](firmware.md) — full firmware architecture, calibration struct definitions, and `collectIMUData_ISM()` flow
- [`docs/binary_protocol.md`](binary_protocol.md) — `TYPE_FIXED_CAL` (0x08) and `TYPE_STAB_CAL` (0x09) packet formats
- [`docs/data_pipeline.md`](data_pipeline.md) — how calibration constants are used during post-processing
- [`IDENTIFIED_ISSUES.md`](../IDENTIFIED_ISSUES.md) — known firmware bugs that may affect calibration data quality
