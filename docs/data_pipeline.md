# Data Pipeline — MATLAB Parser and Magnetometer Calibration

> # ⚠ HALF OF THIS DOCUMENT IS OBSOLETE (2026-09-03)
>
> **The `parse_vertisea_log_v4.m` sections are dead.** That parser was deleted; the only
> maintained SD log reader is `vertisea_plot_v7.py` ("Load BIN File"). Recoverable from git
> at `9f5019f`. Do not follow the MATLAB parsing instructions below, and do not recreate the
> file. Output CSV naming is unchanged (`<baseName>_<type>.csv`).
>
> **The `calibrateMag.m` sections are still correct and in use.** It expects a CSV with
> header `timestamp_ms,mx,my,mz` — exactly what the Python parser's `_mag.csv` provides.
> Note that `_mag.csv` is **absent** from logs built with `IMU_RAW_ONLY 1`, so a calibration
> capture needs `IMU_RAW_ONLY 0`.
>
> This file has not been rewritten because its calibration content is valuable and the
> parser content is merely stale rather than misleading once flagged. Pruning it is a
> separate docs task.

> **Status:** Stable
> **Source file(s):** [`parse_vertisea_log_v4.m`](../parse_vertisea_log_v4.m), [`Calibration/calibrateMag.m`](../Calibration/calibrateMag.m)
> **Last reviewed:** 2026-08-18

## Purpose

Two MATLAB functions form the offline data pipeline:

1. **`parse_vertisea_log_v4.m`** — reads a raw binary SD log file (`.BIN`) and writes
   one CSV file per packet type. This is the primary tool for post-deployment data
   analysis.
2. **`calibrateMag.m`** — performs ellipsoid-fit hard-iron and soft-iron magnetometer
   calibration from a raw magnetometer CSV. This is a one-time setup tool; calibration
   has already been performed for the current hardware.

Neither function modifies the source `.BIN` file.

---

## Dependencies

| Tool | Version requirement |
|------|-------------------|
| MATLAB | R2019b or later (uses `readtable`, `fread`, `svd`) |
| No toolboxes required | All functions use base MATLAB |

---

## `parse_vertisea_log_v4` — Binary Log Parser

### Usage

```matlab
parse_vertisea_log_v4('MMDDHHMM.BIN')
% Example:
parse_vertisea_log_v4('04030825.BIN')
```

### Output Files

CSVs are named `<baseName>_<type>.csv` and are written to the **MATLAB current working
directory**, not to the directory containing the `.BIN` file. `fopen` is called with a
bare filename, so `cd` to the data folder before running the parser if you want the CSVs
to land alongside the log.

> **Difference from the Python parser:** `write_csvs_from_parsed()` in
> `vertisea_plot_v7.py` writes CSVs next to the selected `.BIN` file
> (`os.path.dirname(bin_path)`). The two tools produce identical schemas but choose
> different output directories.

| Output file | Packet type | Contents |
|-------------|-------------|---------|
| `*_imuFixed.csv` | `0x01` | timestamp_ms, pitch, roll, heading, gx, gy, gz, ax, ay, az |
| `*_imuStab.csv` | `0x02` | timestamp_ms, pitch, roll, heading, gx, gy, gz, ax, ay, az |
| `*_bme280.csv` | `0x03` | timestamp_ms, pressure, humidity, temperature |
| `*_gps.csv` | `0x04` | timestamp_ms, satellites, latitude, longitude, altitude |
| `*_rtcEvt.csv` | `0x05` | timestamp_ms, year, month, day, hour, minute, second |
| `*_mag.csv` | `0x07` | timestamp_ms, mx, my, mz |
| `*_calFixed.csv` | `0x08` | timestamp_ms, accel_bias_x/y/z, accel_scale_x/y/z, gyro_bias_x/y/z |
| `*_calStab.csv` | `0x09` | (same columns as calFixed) |
| ~~`*_supcap.csv`~~ | `0x0A` | **No longer produced** — see the banner at the top of this file |
| `*_rpm.csv` | `0x0C` | timestamp_ms, rpm (only present when `RPM_ENABLE=1`) |

### CSV Column Details

**IMU files** (`imuFixed`, `imuStab`):

| Column | Units | Notes |
|--------|-------|-------|
| `timestamp_ms` | ms | `millis()` since boot |
| `pitch` | degrees | Madgwick output |
| `roll` | degrees | Madgwick output |
| `heading` | degrees | 999.9 = invalid (no mag / 6-DOF mode) |
| `gx`, `gy`, `gz` | °/s | LPF-filtered gyro |
| `ax`, `ay`, `az` | g | LPF-filtered accel |

**GPS file**:

| Column | Units | Notes |
|--------|-------|-------|
| `latitude` | degrees | float32 precision (~5 decimal places) |
| `longitude` | degrees | float32 precision |
| `altitude` | metres | from GNSS altitude field |

**RTC event file**: `year` is stored as offset-from-2000 in the binary; the parser adds
2000 before writing to CSV.

**Calibration files**: 9 floats in the order `accel_bias[3]`, `accel_scale[3]`,
`gyro_bias[3]` — matching the `IMUCal` struct layout.

### Parsing Algorithm

The parser reads the binary file sequentially:
1. Read 1 byte: packet type.
2. Read 4 bytes (`uint32`): timestamp in ms.
3. Dispatch on type to read the correct payload bytes.
4. Write a CSV row to the appropriate output file (creating it with a header on first
   encounter).
5. On unknown type: look up the type in `knownPayloadBytes`. If found, skip the payload
   bytes and print a warning. If not found, print a warning and **break** (stop parsing).
6. On EOF: stop.

> **Note:** Known but unhandled packet types (e.g. future additions present in
> `knownPayloadBytes` but not yet in the switch) are skipped safely. Only completely
> unknown types (not in the lookup) cause `break`.

### Internal Implementation Notes

- Uses MATLAB `global` variables (`files`, `headers`, `packetTypes`) for the nested
  helper function `ensureFile`. This is a MATLAB scoping workaround — do not refactor
  to pass these as arguments without testing the nested function scope.
- `fclose('all')` is called at the end to close all open file handles, including any
  that may have been left open by a previous failed run.
- The `mag` packet (`0x07`) writes calibrated, LPF-filtered values (floats), not raw
  counts. Raw counts are not logged to SD.

---

## `calibrateMag` — Magnetometer Calibration

### Usage

```matlab
[center, scale, Mcal] = calibrateMag('04030825_mag.csv')
```

Run the parser first to generate the `_mag.csv` file, then run calibration.

### Algorithm

Ellipsoid fit via SVD on the design matrix:

```
D = [Mx², My², Mz², 2Mx·My, 2Mx·Mz, 2My·Mz, 2Mx, 2My, 2Mz, 1]
```

The last right-singular vector of `D` gives the ellipsoid parameters. Hard-iron offset
(`center`) and soft-iron scale factors (`scale`) are extracted analytically.

Calibrated data: `Mcal = (M - center) ./ scale`

### Outputs

| Output | Type | Description |
|--------|------|-------------|
| `center` | 1×3 double | Hard-iron offsets in raw magnetometer counts |
| `scale` | 1×3 double | Soft-iron per-axis scale factors |
| `Mcal` | N×3 double | Calibrated magnetometer readings |

The function also produces:
- A 3D scatter plot (raw vs. calibrated) to visually verify the sphere fit.
- Histograms of raw and calibrated radii.
- Console output of mean and std of radii before and after calibration.

### Applying Calibration to Firmware

After running `calibrateMag`, copy `center` and `scale` into `VertiSea.ino`:

```cpp
struct MagCal { ... } magCal = {
  { center[0], center[1], center[2] },  // hard-iron offsets
  { scale[0],  scale[1],  scale[2]  }   // soft-iron scales
};
```

> **Current status:** Calibration is complete. The values in `VertiSea.ino` are the
> result of a full-sphere sweep with the current hardware. Do not re-run unless the
> magnetometer or its mounting changes.

### Input Requirements

- CSV must have header: `timestamp_ms,mx,my,mz`
- `mx`, `my`, `mz` must be **raw** MMC5983MA counts (~0–262143), as documented in the
  `calibrateMag.m` header. Because the firmware applies the existing `magCal` before
  logging `TYPE_MAG`, a fresh calibration run requires temporarily setting
  `magCal.offset = {0,0,0}` and `magCal.scale = {1,1,1}` in the firmware so the CSV holds
  unmodified sensor output. See `docs/calibration.md` §2.6.
- Rows where all three axes are zero are discarded as invalid.
- The sweep must cover a full sphere (all orientations) for the ellipsoid fit to be
  well-conditioned. A partial sweep will produce poor calibration.

---

## Known Constraints and Gotchas

- The parser skips known-but-unhandled packet types using the `knownPayloadBytes` lookup.
  Completely unknown types (not in the lookup) still cause `break`. If a new packet type
  is added to the firmware, add it to `knownPayloadBytes` (and ideally add a full handler)
  before parsing `.BIN` files that contain it.
- `fclose('all')` in the parser will close any other MATLAB file handles that happen to
  be open. Run the parser in a clean MATLAB session if this is a concern.
- The `calibrateMag` function reads the entire CSV into memory. For very long deployments
  (many hours at 104 Hz), the mag CSV can be large. MATLAB's `readtable` handles this
  but may be slow.
- GPS latitude/longitude are stored as `float32` in the binary, limiting precision to
  approximately ±0.0001° (~11 m). This is sufficient for buoy tracking but not for
  precision positioning.

## Rejected Approaches

- **Python-based parser** — considered for portability. Rejected because the primary
  analysis workflow is MATLAB-based and the existing MATLAB parser is well-tested.
- **Single combined CSV output** — rejected because different packet types have different
  rates and schemas; per-type CSVs are easier to load into MATLAB/Python for analysis.

## Open Issues / To-Do

- Completely unknown packet types (not in `knownPayloadBytes`) still cause `break`. Full
  resynchronisation (byte-scan for the next valid type) would be more robust for badly
  corrupted files.
- Neither parser handles `TYPE_STATUS` (`0x0B`): it is radio-only and never written to SD,
  so it should never appear in a `.BIN`. It is absent from the MATLAB
  `knownPayloadBytes` map and the Python `_SD_PAYLOAD_BYTES` table, so if it ever did
  appear both parsers would stop at that byte.
- `TYPE_TELEM_IMU` (`0x06`) is not written to SD and has no parser case; this is correct
  and intentional.
