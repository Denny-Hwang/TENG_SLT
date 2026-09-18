#!/usr/bin/env python3
"""VertiSea SD binary protocol: packet definitions, log parser, CSV export.

This module is the **read side** of the contract defined in `docs/binary_protocol.md`.
It is deliberately free of GUI and serial dependencies — stdlib only — so that:

  * the parser can be imported, tested and scripted headlessly (see
    `tests/test_binary_protocol.py`), which was impossible while it lived inside the
    Tkinter/matplotlib module;
  * batch conversion of a directory of logs needs no display;
  * there remains exactly ONE place where a packet layout change has to be mirrored on
    the read side. The MATLAB parser was retired 2026-09-03 precisely because a second,
    never-exercised copy of these layouts was a correctness risk.

`vertisea_plot_v7.py` imports from here; it does not redefine anything below.

Any change to a packet struct in `VertiSea/VertiSea.ino` requires a matching change here
AND in `docs/binary_protocol.md`, in the same commit.

Can also be run directly to convert logs without opening the GUI:

    python3 vertisea_protocol.py LOG00001.BIN [more.BIN ...]
"""

import bisect
import io
import csv
import os
import struct
import sys

# ---------------------------------------------------------------------------
# Packet type constants — must match the PacketType enum in VertiSea.ino
# ---------------------------------------------------------------------------
TYPE_FIXED_IMU = 0x01   # 104 Hz  fixed IMU attitude (SD only)
TYPE_STAB_IMU  = 0x02   # 104 Hz  stabilized IMU attitude (SD only)
TYPE_BME       = 0x03   # 1 Hz    environmental (pressure / humidity / temp)
TYPE_GPS       = 0x04   # 1 Hz    GPS fix (lat / lon / alt / sats)
TYPE_RTC_EVENT = 0x05   # once    RTC timestamp at boot
TYPE_TELEM_IMU = 0x06   # 5 Hz    IMU attitude + vertical displacement + stab pitch/roll (radio)
TYPE_MAG       = 0x07   # 104 Hz  magnetometer (SD only)
TYPE_FIXED_CAL = 0x08   # once    fixed IMU calibration (SD only)
TYPE_STAB_CAL  = 0x09   # once    stabilized IMU calibration (SD only)
# 0x0A was TYPE_CURRENT (5 Hz point sample). RETIRED in firmware 2026-09-03:
# it read 2.1x high (mean 682 counts vs 325 for the full-rate 0x0E stream) because
# a ~100 ms point sample aliases a bursty signal. Parsing is retained read-only so
# older logs still load; nothing emits it any more. Do not reuse 0x0A.
TYPE_CURRENT   = 0x0A   # RETIRED — legacy logs only
TYPE_STATUS    = 0x0B   # 1 Hz    system health flags (radio only)
TYPE_RPM       = 0x0C   # 5 Hz    rotor RPM (RPM_ENABLE=1 only)
TYPE_CURRENT_CAL = 0x0D  # once   current-sense scale constants (SD only)
TYPE_CURRENT_BLOCK = 0x0E  # batched high-rate current samples (SD only)
TYPE_CURRENT_STATS = 0x0F  # 1 Hz  windowed current statistics (radio only)
TYPE_LPF_CAL   = 0x10   # once    IIR alpha + magnetometer cal (SD only)
TYPE_HALL_EDGE = 0x11   # raw Hall edge timestamps (SD only, RPM_ENABLE=1)
TYPE_IMU_RAW   = 0x12   # both IMUs: accel int16 mg + gyro int32 mdps (SD only, IMU_RAW_ONLY=1)
TYPE_BATTERY_CAL = 0x13  # once   battery ADC/divider constants (SD only)
TYPE_BATTERY_VOLTAGE = 0x14  # 1 Hz battery voltage (SD + telemetry)
TYPE_SYS_HEALTH = 0x15  # 1 Hz logging-health counters (SD only)

# Packet sizes for SD packets (bytes, including the 5-byte header: 1B type + 4B ts_ms)
# TYPE_FIXED_IMU / TYPE_STAB_IMU : 5B header + 9×float + 1×uint16 = 43 B
#   the trailing uint16 is interval_us: measured microseconds since the previous
#   IMU sample, so the ACHIEVED rate is recorded rather than assumed.
# TYPE_BME       : 5B header + 3×float = 17 B
# TYPE_GPS       : 5B header + 1B sats + 3×float = 18 B
# TYPE_RTC_EVENT : 5B header + 6×uint8 = 11 B
# TYPE_MAG       : 5B header + 3×float = 17 B
# TYPE_FIXED_CAL / TYPE_STAB_CAL : 5B header + 9×float = 41 B
# TYPE_CURRENT   : 5B header + 1×uint16 = 7 B   (RETIRED; legacy logs only)
# TYPE_CURRENT_CAL : 5B header + 4×float = 21 B
# TYPE_CURRENT_BLOCK : 5B header + uint16 span_ms + uint16 count + count×uint16
#   = 9 + 2*count bytes (variable length — the only variable-size SD record)
#   span_ms is the measured first-to-last sample time, NOT a nominal rate.
# TYPE_LPF_CAL   : 5B header + 13×float = 57 B total (52 B payload)
# TYPE_HALL_EDGE : 5B header + uint8 count + count×uint32 = 6 + 4*count bytes
#   (variable length, like TYPE_CURRENT_BLOCK)
# TYPE_BATTERY_CAL : 5B header + 5×float = 25 B
# TYPE_BATTERY_VOLTAGE SD : 5B header + uint16 raw counts = 7 B
# TYPE_IMU_RAW   : 5B header + 38 B payload = 43 B total
#   Payload layout (little-endian, packed), struct format '<3h3i3h3iH':
#     fixed  accel ax,ay,az : 3 x int16, MILLI-G
#     fixed  gyro  gx,gy,gz : 3 x int32, MILLIDEGREES/S
#     stab   accel ax,ay,az : 3 x int16, MILLI-G
#     stab   gyro  gx,gy,gz : 3 x int32, MILLIDEGREES/S
#     interval_us           : 1 x uint16
#   Written INSTEAD of TYPE_FIXED_IMU/TYPE_STAB_IMU/TYPE_MAG when the firmware is
#   built with IMU_RAW_ONLY 1. A log contains either the processed records or these,
#   never both.
#
#   The asymmetric widths are deliberate. These are UNCALIBRATED but already SCALED
#   values (the SparkFun driver scales sfe_ism_data_t), NOT raw LSB counts:
#     accel at ISM_4g peaks near 4000 mg      -> int16 (+/-32767) is ample
#     gyro  at ISM_500dps reaches 500000 mdps -> int32 REQUIRED, 15x the int16 range
#   An earlier revision stored gyro as int16 and wrapped sign on every fast rotation
#   (IDENTIFIED_ISSUES.md Issue 35). Logs from 2026-09-03 with a 31-byte 0x12 record
#   have corrupt gyro columns; the accel columns in those logs are still valid.
#   To convert: g = mg/1000 - apply calFixed/calStab bias+scale; dps = mdps/1000.

# Radio-only packet sizes (different structure — no 4-byte ts_ms, uses 2-byte ts10)
# TYPE_TELEM_IMU : 1B type + 2B ts10 + 5×int16 = 13 B
#   fields: fix_pitch_cdeg, fix_roll_cdeg, vertDisp_mm, stab_pitch_cdeg, stab_roll_cdeg
#   Angle scale: ×100 (centidegrees) → ÷100 to recover degrees.  Range: ±327.67°.
# TYPE_BME radio : 1B type + 2B ts10 + 3×float = 15 B
# TYPE_GPS radio : 1B type + 2B ts10 + 1B sats + 2×float = 12 B
# TYPE_CURRENT radio : RETIRED 2026-09-03 (was 1B type + 2B ts10 + 2B current_mA).
#   The live "Current:" display is now derived from TYPE_CURRENT_STATS (0x0F) as
#   charge_mC / integ_s, which is an unbiased window average rather than a point
#   sample. Radio parsing for 0x0A has been removed; the firmware no longer sends it.
# TYPE_STATUS    : 1B type + 2B ts10 + 1B flags = 4 B
# TYPE_RPM radio : 1B type + 2B ts10 + 2B rpm = 5 B
# TYPE_BATTERY_VOLTAGE radio : 1B type + 2B ts10 + 2B battery_mV = 5 B
# TYPE_CURRENT_STATS radio : 1B type + 2B ts10 + 2B window_s + 2B peak_mA
#   + 4B charge_mC + 4B i2t_mA2s + 4B integ_s + 4B n_samples + 4B n_dropped = 27 B
#   Python unpack: struct.unpack('<BHHHfffII', pkt)
#   Average current = charge_mC / integ_s   (NOT / window_s)
#   RMS current     = sqrt(i2t_mA2s / integ_s)

# STATUS flags (bit definitions — must match StatusPacket in VertiSea.ino)
STATUS_FLAG_SD_ERROR = 0x01   # bit 0: SD write failure

# TYPE_SYS_HEALTH flags byte (must match VertiSea.ino)
HEALTH_FLAG_SD_ERROR = 0x01   # bit 0: SD logging degraded/failed right now
HEALTH_FLAG_NO_MAG   = 0x02   # bit 1: magnetometer did not initialise at boot
HEALTH_FLAG_TIMER_ANOM = 0x04 # bit 2: micros() stepped backwards during this interval

# A loop or SD-write time at or above this is not a measurement, it is the firmware's
# micros() having stepped backwards - unsigned subtraction turns a 1 us backward step into
# 4 294 967 295 us. Firmware from 2026-09-11 onward rejects these at the source and sets
# HEALTH_FLAG_TIMER_ANOM instead; the threshold is kept here so logs written by OLDER
# firmware are still read correctly rather than reported as a 71-minute stall.
TIMING_IMPLAUSIBLE_US = 60_000_000

# ---------------------------------------------------------------------------
# SD binary parser — payload byte counts AFTER the 5-byte header
# ---------------------------------------------------------------------------
_SD_PAYLOAD_BYTES = {
    TYPE_FIXED_IMU: 38,   # 9 floats + uint16 interval_us
    TYPE_STAB_IMU:  38,   # 9 floats + uint16 interval_us
    TYPE_BME:       12,   # 3 floats
    TYPE_GPS:       13,   # 1 uint8 + 3 floats
    TYPE_RTC_EVENT:  6,   # 6 uint8
    TYPE_MAG:       12,   # 3 floats
    TYPE_FIXED_CAL: 36,   # 9 floats
    TYPE_STAB_CAL:  36,   # 9 floats
    TYPE_CURRENT:    2,   # 1 uint16 (raw ADC counts) — RETIRED, legacy logs only
    TYPE_RPM:        2,   # 1 uint16
    TYPE_CURRENT_CAL: 16,  # 4 floats
    TYPE_LPF_CAL:     52,  # 13 floats
    TYPE_IMU_RAW:     38,  # 3h3i3h3iH — accel mg int16, gyro mdps int32, interval
    TYPE_BATTERY_CAL: 20,  # 5 floats: ADC and divider constants
    TYPE_BATTERY_VOLTAGE: 2,  # uint16 raw ADC counts
    TYPE_SYS_HEALTH: 29,  # 6 uint32 + 2 uint16 + 1 uint8
}
# NOTE: TYPE_CURRENT_BLOCK (0x0E) and TYPE_HALL_EDGE (0x11) are deliberately
# absent — both are variable length, so they cannot be skipped from a fixed
# table. They must be handled explicitly by any parser, which the branches in
# parse_binary_file() do. Do not "helpfully" add them here.


def parse_binary_file(bin_path: str) -> dict:
    """Parse a VertiSea SD-card binary log file and return data as a dict of lists.

    The binary format uses a 5-byte common header (1B type + 4B uint32 timestamp_ms)
    followed by a type-specific payload.  See docs/binary_protocol.md for the full
    specification.

    Parameters
    ----------
    bin_path : str
        Path to the .BIN file written by the VertiSea firmware.

    Returns
    -------
    dict with keys:
        'fixed_imu'  : list of dicts {ts_ms, pitch, roll, heading, gx, gy, gz, ax, ay, az}
        'stab_imu'   : list of dicts {ts_ms, pitch, roll, heading, gx, gy, gz, ax, ay, az}
        'bme'        : list of dicts {ts_ms, pressure, humidity, temperature}
        'gps'        : list of dicts {ts_ms, satellites, latitude, longitude, altitude}
        'rtc_event'  : list of dicts {ts_ms, year, month, day, hour, minute, second}
        'mag'        : list of dicts {ts_ms, mx, my, mz}
        'fixed_cal'  : list of dicts {ts_ms, accel_bias_x, ..., gyro_bias_z}
        'stab_cal'   : list of dicts {ts_ms, accel_bias_x, ..., gyro_bias_z}
        'current'    : list of dicts {ts_ms, counts, current_mA}
                       counts is the raw 14-bit ADC reading; current_mA is derived
                       using the TYPE_CURRENT_CAL constants and is None if the log
                       contains no cal record.
        'current_fast': same fields as 'current', expanded from TYPE_CURRENT_BLOCK
                       records (high-rate samples, a few hundred Hz). ts_ms is a
                       float because the sample interval need not be integer ms,
                       and is reconstructed from the block's measured span_ms.
        'current_cal': list of dicts {ts_ms, vref, adc_max, div_ratio, sens_mA_per_V}
        'battery_cal': list of dicts {ts_ms, vref, adc_max, r_top_ohm,
                       r_bottom_ohm, div_ratio}
        'battery_voltage': list of dicts {ts_ms, counts, voltage_V}
        'lpf_cal'    : list of dicts {ts_ms, alpha_acc, alpha_gyro, alpha_mag,
                       accel_cutoff_hz, gyro_cutoff_hz, mag_cutoff_hz,
                       imu_rate_hz, mag_offset_[xyz], mag_scale_[xyz]}
                       Enables offline inversion of the IMU low-pass filter:
                       x[n] = y[n-1] + (y[n] - y[n-1]) / alpha
        'hall_edge'  : list of dicts {ts_ms, edge_us, period_us, rpm}
                       Raw Hall falling edges; period_us and rpm are derived from
                       consecutive edges in a post-pass.
        'notes'      : list of str   (informational; not problems)
        'errors'     : list of str   (warnings / skipped-packet messages)
    """
    data = {
        'fixed_imu': [], 'stab_imu': [], 'bme': [], 'gps': [],
        'rtc_event': [], 'mag': [], 'fixed_cal': [], 'stab_cal': [],
        'current': [], 'current_cal': [], 'current_fast': [],
        'lpf_cal': [], 'hall_edge': [], 'imu_raw': [],
        'rpm': [], 'battery_cal': [], 'battery_voltage': [], 'sys_health': [],
        'errors': [], 'notes': []
    }

    _imu_fields = ('pitch', 'roll', 'heading', 'gx', 'gy', 'gz', 'ax', 'ay', 'az',
                   'interval_us')
    _cal_fields = ('accel_bias_x', 'accel_bias_y', 'accel_bias_z',
                   'accel_scale_x', 'accel_scale_y', 'accel_scale_z',
                   'gyro_bias_x', 'gyro_bias_y', 'gyro_bias_z')

    # The file is read into memory once. A rotated file (U26) is ~11 MB; even an unrotated
    # day is 520 MB, well inside what the per-record dicts below already cost (Issue 40),
    # and resynchronisation needs random access to look past a damaged region.
    with open(bin_path, 'rb') as _f:
        buf = _f.read()
    file_size = len(buf)
    last_good_ts = 0          # timestamp of the last record parsed cleanly
    resync_events = 0

    if True:
        fid = io.BytesIO(buf)
        byte_offset = 0

        while byte_offset < file_size:
            # --- Read 5-byte common header: type (uint8) + timestamp_ms (uint32) ---
            header = fid.read(5)
            if len(header) < 5:
                break  # truncated file — stop cleanly
            pkt_type = header[0]
            ts_ms = struct.unpack_from('<I', header, 1)[0]
            byte_offset += 5

            # ---- TYPE_FIXED_IMU (0x01) or TYPE_STAB_IMU (0x02) — 38 payload bytes ----
            # Payload: 9 × float32 → pitch, roll, heading, gx, gy, gz, ax, ay, az
            #          + uint16 interval_us (measured µs since the previous IMU sample)
            if pkt_type in (TYPE_FIXED_IMU, TYPE_STAB_IMU):
                raw = fid.read(38)
                byte_offset += len(raw)
                if len(raw) < 38:
                    data['errors'].append(
                        f"Truncated IMU packet at offset {byte_offset}")
                    break
                vals = struct.unpack('<9fH', raw)
                rec = {'ts_ms': ts_ms}
                rec.update(zip(_imu_fields, vals))
                key = 'fixed_imu' if pkt_type == TYPE_FIXED_IMU else 'stab_imu'
                data[key].append(rec)

            # ---- TYPE_BME (0x03) — 12 payload bytes --------------------------------
            # Payload: float pressure (Pa), float humidity (%), float temperature (°C)
            elif pkt_type == TYPE_BME:
                raw = fid.read(12)
                byte_offset += len(raw)
                if len(raw) < 12:
                    data['errors'].append(
                        f"Truncated BME packet at offset {byte_offset}")
                    break
                pres, hum, tmp = struct.unpack('<3f', raw)
                data['bme'].append(
                    {'ts_ms': ts_ms, 'pressure': pres,
                     'humidity': hum, 'temperature': tmp})

            # ---- TYPE_GPS (0x04) — 13 payload bytes --------------------------------
            # Payload: uint8 satellites, float lat, float lon, float alt
            elif pkt_type == TYPE_GPS:
                raw = fid.read(13)
                byte_offset += len(raw)
                if len(raw) < 13:
                    data['errors'].append(
                        f"Truncated GPS packet at offset {byte_offset}")
                    break
                sats = raw[0]
                lat, lon, alt = struct.unpack_from('<3f', raw, 1)
                data['gps'].append(
                    {'ts_ms': ts_ms, 'satellites': sats,
                     'latitude': lat, 'longitude': lon, 'altitude': alt})

            # ---- TYPE_RTC_EVENT (0x05) — 6 payload bytes ---------------------------
            # Payload: 6 × uint8 → year_offset (since 2000), month, day, hour, min, sec
            elif pkt_type == TYPE_RTC_EVENT:
                raw = fid.read(6)
                byte_offset += len(raw)
                if len(raw) < 6:
                    data['errors'].append(
                        f"Truncated RTC packet at offset {byte_offset}")
                    break
                yr_off, mon, day, hr, mn, sec = struct.unpack('<6B', raw)
                data['rtc_event'].append(
                    {'ts_ms': ts_ms, 'year': yr_off + 2000, 'month': mon,
                     'day': day, 'hour': hr, 'minute': mn, 'second': sec})

            # ---- TYPE_MAG (0x07) — 12 payload bytes --------------------------------
            # Payload: float mx, float my, float mz
            elif pkt_type == TYPE_MAG:
                raw = fid.read(12)
                byte_offset += len(raw)
                if len(raw) < 12:
                    data['errors'].append(
                        f"Truncated MAG packet at offset {byte_offset}")
                    break
                mx, my, mz = struct.unpack('<3f', raw)
                data['mag'].append({'ts_ms': ts_ms, 'mx': mx, 'my': my, 'mz': mz})

            # ---- TYPE_IMU_RAW (0x12) — 38 payload bytes --------------------------
            # Layout '<3h3i3h3iH': fixed accel (int16 milli-g), fixed gyro (int32
            # mdps), stab accel (int16 milli-g), stab gyro (int32 mdps), interval_us.
            #
            # Emitted only by IMU_RAW_ONLY builds, in place of the processed
            # TYPE_FIXED_IMU / TYPE_STAB_IMU / TYPE_MAG records. Values are
            # UNCALIBRATED but already scaled by the sensor driver — not LSB counts.
            # Apply the TYPE_FIXED_CAL / TYPE_STAB_CAL bias and scale (and optionally
            # the TYPE_LPF_CAL alphas) to recover engineering units. No attitude and no
            # magnetometer are available in such a log.
            #
            # Gyro is int32 because at ISM_500dps the sensor emits up to 500000 mdps,
            # 15x the int16 range (Issue 35). Logs written 2026-09-03 with a 31-byte
            # 0x12 record predate the fix and have corrupt gyro columns.
            elif pkt_type == TYPE_IMU_RAW:
                raw = fid.read(38)
                byte_offset += len(raw)
                if len(raw) < 38:
                    data['errors'].append(
                        f"Truncated IMU_RAW packet at offset {byte_offset}")
                    break
                v = struct.unpack('<3h3i3h3iH', raw)
                data['imu_raw'].append({
                    'ts_ms': ts_ms,
                    'fix_ax_mg': v[0], 'fix_ay_mg': v[1], 'fix_az_mg': v[2],
                    'fix_gx_mdps': v[3], 'fix_gy_mdps': v[4], 'fix_gz_mdps': v[5],
                    'stab_ax_mg': v[6], 'stab_ay_mg': v[7], 'stab_az_mg': v[8],
                    'stab_gx_mdps': v[9], 'stab_gy_mdps': v[10], 'stab_gz_mdps': v[11],
                    'interval_us': v[12]})

            # ---- TYPE_FIXED_CAL (0x08) or TYPE_STAB_CAL (0x09) — 36 payload bytes --
            # Payload: 9 × float32 → accel_bias_xyz, accel_scale_xyz, gyro_bias_xyz
            elif pkt_type in (TYPE_FIXED_CAL, TYPE_STAB_CAL):
                raw = fid.read(36)
                byte_offset += len(raw)
                if len(raw) < 36:
                    data['errors'].append(
                        f"Truncated CAL packet at offset {byte_offset}")
                    break
                vals = struct.unpack('<9f', raw)
                rec = {'ts_ms': ts_ms}
                rec.update(zip(_cal_fields, vals))
                key = 'fixed_cal' if pkt_type == TYPE_FIXED_CAL else 'stab_cal'
                data[key].append(rec)

            # ---- TYPE_CURRENT (0x0A) — 2 payload bytes -----------------------------
            # RETIRED in firmware 2026-09-03; parsed here so pre-existing logs still
            # load. Payload: uint16 raw ADC counts, converted to mA in a post-pass
            # below using the TYPE_CURRENT_CAL constants.
            #
            # WARNING: this is a BIASED estimator — a 5 Hz point sample of a bursty
            # signal. Measured 682 counts mean vs 325 for 0x0E over the same run.
            # Use the currentFast output (0x0E) for anything quantitative.
            elif pkt_type == TYPE_CURRENT:
                raw = fid.read(2)
                byte_offset += len(raw)
                if len(raw) < 2:
                    data['errors'].append(
                        f"Truncated CURRENT packet at offset {byte_offset}")
                    break
                counts, = struct.unpack('<H', raw)
                data['current'].append(
                    {'ts_ms': ts_ms, 'counts': counts, 'current_mA': None})

            # ---- TYPE_CURRENT_BLOCK (0x0E) — variable length -----------------------
            # Payload: uint16 span_ms, uint16 count, count × uint16 counts.
            # span_ms is the MEASURED elapsed time from the first to the last
            # sample in the block, not a nominal rate — the sampler cannot be
            # assumed to hit its requested rate. Per-sample timestamps are
            # therefore interpolated across the real span.
            elif pkt_type == TYPE_CURRENT_BLOCK:
                hdr = fid.read(4)
                byte_offset += len(hdr)
                if len(hdr) < 4:
                    data['errors'].append(
                        f"Truncated CURRENT_BLOCK header at offset {byte_offset}")
                    break
                span_ms, n = struct.unpack('<HH', hdr)
                if n == 0 or n > MAX_CURRENT_BLOCK_SAMPLES:
                    # The firmware writes 1..100 samples per block. Anything else is a
                    # damaged count field, and honouring it would skip real data.
                    data['errors'].append(
                        f"CURRENT_BLOCK at offset {byte_offset - 9} claims {n} samples "
                        f"(firmware max {MAX_CURRENT_BLOCK_SAMPLES}); treating as damage.")
                    pkt_type = None       # fall into the resync path below
                    fid.seek(byte_offset - 9 + 1)
                    byte_offset = byte_offset - 9 + 1
                    raw = b''
                    n = 0
                else:
                    raw = fid.read(2 * n)
                byte_offset += len(raw)
                if len(raw) < 2 * n:
                    data['errors'].append(
                        f"Truncated CURRENT_BLOCK payload at offset {byte_offset} "
                        f"(wanted {2 * n} bytes, got {len(raw)})")
                    break
                samples = struct.unpack(f'<{n}H', raw) if n else ()
                # Spread samples evenly across the measured span. With n samples
                # the span covers n-1 intervals.
                dt_ms = (span_ms / (n - 1)) if n > 1 else 0.0
                for i, counts in enumerate(samples):
                    data['current_fast'].append({
                        'ts_ms': ts_ms + i * dt_ms,
                        'counts': counts,
                        'current_mA': None,
                    })

            # ---- TYPE_LPF_CAL (0x10) — 52 payload bytes ----------------------------
            # Payload: 13 × float32 → alpha_acc, alpha_gyro, alpha_mag,
            #   accel_cutoff_hz, gyro_cutoff_hz, mag_cutoff_hz, imu_rate_hz,
            #   mag_offset[3], mag_scale[3]
            # These make the IMU LPF invertible offline (see docs/binary_protocol.md).
            elif pkt_type == TYPE_LPF_CAL:
                raw = fid.read(52)
                byte_offset += len(raw)
                if len(raw) < 52:
                    data['errors'].append(
                        f"Truncated LPF_CAL packet at offset {byte_offset}")
                    break
                vals = struct.unpack('<13f', raw)
                data['lpf_cal'].append({
                    'ts_ms': ts_ms,
                    'alpha_acc': vals[0], 'alpha_gyro': vals[1], 'alpha_mag': vals[2],
                    'accel_cutoff_hz': vals[3], 'gyro_cutoff_hz': vals[4],
                    'mag_cutoff_hz': vals[5], 'imu_rate_hz': vals[6],
                    'mag_offset_x': vals[7], 'mag_offset_y': vals[8],
                    'mag_offset_z': vals[9],
                    'mag_scale_x': vals[10], 'mag_scale_y': vals[11],
                    'mag_scale_z': vals[12],
                })

            # ---- TYPE_HALL_EDGE (0x11) — variable length ---------------------------
            # Payload: uint8 count, then count × uint32 micros() timestamps.
            # Raw Hall falling-edge times. Expanded into one record per edge, with
            # the inter-edge period and implied RPM computed where available.
            elif pkt_type == TYPE_HALL_EDGE:
                cnt_raw = fid.read(1)
                byte_offset += len(cnt_raw)
                if len(cnt_raw) < 1:
                    data['errors'].append(
                        f"Truncated HALL_EDGE count at offset {byte_offset}")
                    break
                n = cnt_raw[0]
                if n == 0 or n > MAX_HALL_EDGES_PER_RECORD:
                    data['errors'].append(
                        f"HALL_EDGE at offset {byte_offset - 6} claims {n} edges "
                        f"(firmware max {MAX_HALL_EDGES_PER_RECORD}); treating as damage.")
                    pkt_type = None
                    fid.seek(byte_offset - 6 + 1)
                    byte_offset = byte_offset - 6 + 1
                    raw = b''
                    n = 0
                else:
                    raw = fid.read(4 * n)
                byte_offset += len(raw)
                if len(raw) < 4 * n:
                    data['errors'].append(
                        f"Truncated HALL_EDGE payload at offset {byte_offset} "
                        f"(wanted {4 * n} bytes, got {len(raw)})")
                    break
                for edge_us in struct.unpack(f'<{n}I', raw):
                    data['hall_edge'].append({
                        'ts_ms': ts_ms,
                        'edge_us': edge_us,
                        'period_us': None,
                        'rpm': None,
                    })

            # ---- TYPE_CURRENT_CAL (0x0D) — 16 payload bytes ------------------------
            # Payload: 4 × float32 → vref, adc_max, div_ratio, sens_mA_per_V
            elif pkt_type == TYPE_CURRENT_CAL:
                raw = fid.read(16)
                byte_offset += len(raw)
                if len(raw) < 16:
                    data['errors'].append(
                        f"Truncated CURRENT_CAL packet at offset {byte_offset}")
                    break
                vref, adc_max, div_ratio, sens = struct.unpack('<4f', raw)
                data['current_cal'].append({
                    'ts_ms': ts_ms, 'vref': vref, 'adc_max': adc_max,
                    'div_ratio': div_ratio, 'sens_mA_per_V': sens})

            # ---- TYPE_BATTERY_CAL (0x13) — 20 payload bytes -----------------------
            # Payload: vref, adc_max, top/bottom resistor ohms, divider ratio.
            elif pkt_type == TYPE_BATTERY_CAL:
                raw = fid.read(20)
                byte_offset += len(raw)
                if len(raw) < 20:
                    data['errors'].append(
                        f"Truncated BATTERY_CAL packet at offset {byte_offset}")
                    break
                vref, adc_max, r_top, r_bottom, div_ratio = struct.unpack('<5f', raw)
                data['battery_cal'].append({
                    'ts_ms': ts_ms, 'vref': vref, 'adc_max': adc_max,
                    'r_top_ohm': r_top, 'r_bottom_ohm': r_bottom,
                    'div_ratio': div_ratio})

            # ---- TYPE_BATTERY_VOLTAGE (0x14) — 2 payload bytes -------------------
            # SD stores raw counts; conversion is applied after the full scan so
            # calibration-record ordering cannot affect the result.
            elif pkt_type == TYPE_BATTERY_VOLTAGE:
                raw = fid.read(2)
                byte_offset += len(raw)
                if len(raw) < 2:
                    data['errors'].append(
                        f"Truncated BATTERY_VOLTAGE packet at offset {byte_offset}")
                    break
                counts, = struct.unpack('<H', raw)
                data['battery_voltage'].append({
                    'ts_ms': ts_ms, 'counts': counts, 'voltage_V': None})

            # ---- TYPE_SYS_HEALTH (0x15) — 29 payload bytes -------------------------
            # Layout '<6I2HB'. Diagnostic record for the logging path itself, written
            # once a second. Read this CSV FIRST when a deployment misbehaves: a frozen
            # heartbeat LED means loop() did not finish a pass, and loop_max_us is the
            # direct measurement of that. The other columns say which subsystem caused
            # it — an SD stall, the RAM queue backing up, a remount, or an interrupt
            # storm on the Hall line from harvester EMI.
            #
            # loop_max_us and sd_write_max_us are per-second maxima (reset each record);
            # everything else is cumulative since boot, so differences between rows give
            # the per-second rate.
            elif pkt_type == TYPE_SYS_HEALTH:
                raw = fid.read(29)
                byte_offset += len(raw)
                if len(raw) < 29:
                    data['errors'].append(
                        f"Truncated SYS_HEALTH packet at offset {byte_offset}")
                    break
                v = struct.unpack('<6I2HB', raw)
                data['sys_health'].append({
                    'ts_ms': ts_ms,
                    'loop_max_us': v[0], 'sd_write_max_us': v[1],
                    'sd_write_failures': v[2], 'sd_recoveries': v[3],
                    'hall_rejected': v[4], 'hall_lost': v[5],
                    'sd_queue_high_water': v[6], 'sd_overruns': v[7],
                    'flags': v[8],
                    'sd_error': bool(v[8] & HEALTH_FLAG_SD_ERROR),
                    'mag_absent': bool(v[8] & HEALTH_FLAG_NO_MAG),
                    'timer_anomaly': bool(v[8] & HEALTH_FLAG_TIMER_ANOM),
                })

            # ---- TYPE_RPM (0x0C) — 2 payload bytes ---------------------------------
            # Payload: uint16 rpm  (0 when rotor is stopped or RPM_ENABLE=0)
            elif pkt_type == TYPE_RPM:
                raw = fid.read(2)
                byte_offset += len(raw)
                if len(raw) < 2:
                    data['errors'].append(
                        f"Truncated RPM packet at offset {byte_offset}")
                    break
                rpm, = struct.unpack('<H', raw)
                data['rpm'].append({'ts_ms': ts_ms, 'rpm': rpm})

            # ---- Unknown packet type -----------------------------------------------
            # Attempt to skip using the known-payload-size table so the parser stays
            # synchronised (mirrors the MATLAB parser's behaviour).
            else:
                if pkt_type in _SD_PAYLOAD_BYTES:
                    skip = _SD_PAYLOAD_BYTES[pkt_type]
                    fid.read(skip)
                    byte_offset += skip
                    data['errors'].append(
                        f"Skipped known-type packet 0x{pkt_type:02X} "
                        f"(no handler) at offset {byte_offset}")
                else:
                    # A byte that is not a record type. Before 2026-09-18 this stopped
                    # the parse, which on a long log discards everything after one bad
                    # sector. Scan forward for the next pair of agreeing headers instead.
                    damage_at = byte_offset - 5 if pkt_type is not None else byte_offset
                    found = _find_resync(buf, damage_at + 1, last_good_ts)
                    if found is None:
                        data['errors'].append(
                            f"DAMAGE at offset {damage_at}: no further valid record found "
                            f"in the remaining {file_size - damage_at} bytes; stopping.")
                        break
                    skipped = found - damage_at
                    resync_events += 1
                    data['errors'].append(
                        f"DAMAGE at offset {damage_at}"
                        + (f" (type byte 0x{pkt_type:02X})" if pkt_type is not None else "")
                        + f": skipped {skipped} bytes to the next valid record at offset "
                        f"{found}. About {skipped / 6.0:.0f} ms of data lost there.")
                    fid.seek(found)
                    byte_offset = found
                    continue

            last_good_ts = ts_ms if ts_ms >= last_good_ts else last_good_ts

    if resync_events:
        data['notes'].append(
            f"Resynchronised {resync_events} time(s) after damaged bytes. Every record "
            "before and after each damaged region was recovered; only the records "
            "overlapping the damage are lost. The SD format carries no CRC, so a damaged "
            "byte INSIDE a record's payload cannot be detected and reads as a wrong "
            "value - check the affected timestamps against neighbours if it matters.")

    # ---- Derive milliamps from raw counts using the cal record ------------------
    # Done after the main pass so the cal packet's position in the file does not
    # matter. The firmware writes it once at boot, but a log that was truncated or
    # concatenated might not have it first — or at all.
    if data['current'] or data['current_fast']:
        if data['current_cal']:
            cal = data['current_cal'][0]
            adc_max = cal['adc_max']
            if adc_max:
                scale = (cal['vref'] * cal['div_ratio']
                         * cal['sens_mA_per_V'] / adc_max)
                for key in ('current', 'current_fast'):
                    for rec in data[key]:
                        rec['current_mA'] = rec['counts'] * scale
            else:
                data['errors'].append(
                    "CURRENT_CAL has adc_max=0; cannot convert counts to mA.")
            if len(data['current_cal']) > 1:
                data['errors'].append(
                    f"{len(data['current_cal'])} CURRENT_CAL records found; "
                    "used the first. Was this log concatenated from two sessions?")
        else:
            data['errors'].append(
                "No CURRENT_CAL record in log — current is reported as raw ADC "
                "counts only, current_mA left blank. Logs from firmware predating "
                "TYPE_CURRENT_CAL (0x0D) store milliamps directly in TYPE_CURRENT, "
                "so treat their 'counts' column as milliamps instead.")

    # ---- Derive battery volts using the archived divider calibration -----------
    if data['battery_voltage']:
        if data['battery_cal']:
            cal = data['battery_cal'][0]
            adc_max = cal['adc_max']
            if adc_max:
                scale = cal['vref'] * cal['div_ratio'] / adc_max
                for rec in data['battery_voltage']:
                    rec['voltage_V'] = rec['counts'] * scale
            else:
                data['errors'].append(
                    "BATTERY_CAL has adc_max=0; cannot convert counts to volts.")
            if len(data['battery_cal']) > 1:
                data['errors'].append(
                    f"{len(data['battery_cal'])} BATTERY_CAL records found; "
                    "used the first. Was this log concatenated from two sessions?")

            # ---- Is the battery channel inside the ADC's range at all? ----------
            # The divider exists because the ADC reference is ~1.98 V and a 1S cell is
            # up to 3.65 V. If the divider is bypassed, open, or wired to the wrong node,
            # the pad sits above the reference, every conversion pins at full scale, and
            # the log reports a CONSTANT voltage that looks like a plausible number
            # (adc_max x vref x div_ratio = the divider's full-scale, ~3.95 V here).
            # That is the failure a multimeter cannot see: the meter reads the source
            # correctly while the pad is the thing that is out of range.
            # What voltage does the log imply at the DIVIDER INPUT? On a bench test that
            # is the number to compare with the supply's front panel, and it is two
            # conversions away from the raw counts, so nobody does it by hand. A steady
            # level that disagrees with the set voltage says the node is not where it is
            # believed to be - which no other check can see, because the counts are
            # perfectly well-behaved.
            counts_all = [r['counts'] for r in data['battery_voltage']]
            if counts_all:
                lo_c, hi_c = min(counts_all), max(counts_all)
                mean_c = sum(counts_all) / len(counts_all)
                v_pad = mean_c * cal['vref'] / adc_max if adc_max else 0.0
                data['notes'].append(
                    f"Battery channel: {mean_c:.0f} counts mean "
                    f"(range {lo_c}-{hi_c}) = {v_pad:.4f} V at the ADC pad = "
                    f"{mean_c * scale:.3f} V at the divider input, using the "
                    f"{cal['div_ratio']:.4f}:1 ratio the log carries. On a bench test "
                    "compare that last number with the supply setting; the pad saturates "
                    f"once the divider input passes {adc_max * scale:.3f} V.")

            # Can the ADC actually charge its sample capacitor through this divider?
            # The Apollo3 SAR samples onto a switched capacitor: at roughly 1.2 MHz and
            # ~10 pF the input looks like ~83 kohm for the duration of the sample window.
            # A source whose Thevenin impedance approaches that cannot deliver the charge
            # in time, so the conversion lands SHORT of the true voltage - always low,
            # never high, and by a fixed fraction, which is indistinguishable from a
            # wrong divider ratio unless you know the source. Ambiq's guidance is to keep
            # the source well under 10 kohm, or to put a local capacitor at the pin so the
            # sample cap draws its charge from that instead of through the resistors.
            r_th = (cal['r_top_ohm'] * cal['r_bottom_ohm'] /
                    (cal['r_top_ohm'] + cal['r_bottom_ohm'])
                    if (cal['r_top_ohm'] + cal['r_bottom_ohm']) else 0.0)
            if r_th > 10000.0:
                data['notes'].append(
                    f"Battery divider source impedance is {r_th / 1000.0:.1f} kohm "
                    f"(Thevenin of {cal['r_top_ohm'] / 1000.0:.1f} k / "
                    f"{cal['r_bottom_ohm'] / 1000.0:.1f} k), well above the <10 kohm the "
                    "Apollo3 SAR wants. Its switched-cap input looks like ~83 kohm during "
                    "the sample window, so a source this stiff does not settle and the "
                    "channel reads LOW by a fixed fraction - which looks exactly like a "
                    "wrong divider ratio until you meter the pad. MEASURED on this board "
                    "2026-09-15: pad metered at 1.65 V while the ADC reported 1.36 V, a "
                    "17.5 % deficit; adding 0.1 uF from the pad to GND moved the same "
                    "channel from 11 270 to 13 399 counts in one session, recovering "
                    "89 % of it (Issues 72, 74). Fit the capacitor - it droops ~0.01 % "
                    "per conversion and recovers in ~5 ms against a 1 s interval, so it "
                    "costs nothing here; 2.2 uF ceramic is the recommended part - see "
                    "docs/adc_calibration.md for the sizing table. Logs taken without it "
                    "read low by this fraction and should be scaled, not trusted.")

            n_pinned = sum(1 for r in data['battery_voltage']
                           if r['counts'] >= adc_max)
            if n_pinned:
                fs_v = adc_max * scale
                data['errors'].append(
                    f"BATTERY CHANNEL SATURATED: {n_pinned} of "
                    f"{len(data['battery_voltage'])} samples pinned at {adc_max:.0f} "
                    f"counts, which converts to {fs_v:.2f} V and is a FLOOR, not a "
                    "reading - the true voltage is anything at or above it. The pad is "
                    f"above the {cal['vref']:.2f} V ADC reference. With the "
                    f"{cal['div_ratio']:.3f}:1 divider the pad must stay under "
                    f"{cal['vref']:.2f} V, i.e. the battery node under {fs_v:.2f} V. "
                    "A pinned reading that appears the moment the source is connected "
                    "means the divider is not dividing - the pad is seeing very nearly "
                    "the whole source. FIRST check where the source is actually landing: "
                    "probing or injecting one node off puts the full voltage on the pad, "
                    "and it is the cause that has actually occurred here. If the "
                    "injection point is right, measure resistance with the supply OFF: "
                    f"pad to board GND should read ~{cal['r_bottom_ohm'] / 1000.0:.1f} k, "
                    f"pad to the divider input ~{cal['r_top_ohm'] / 1000.0:.1f} k, and "
                    f"input to GND ~{(cal['r_top_ohm'] + cal['r_bottom_ohm']) / 1000.0:.1f} k. "
                    "An open bottom leg - or its ground return - reads infinite pad-to-GND "
                    "and lets the pad float up to the source, which is the most common "
                    "cause after any rework of the grounding.")

            # A 1S LiFePO4 cell lives between ~2.5 V (empty) and 3.65 V (charge
            # termination). A steady reading outside that says the divider ratio in the
            # cal record does not match the resistors actually fitted - which is exactly
            # what a rebuilt divider gets wrong, and it scales the answer rather than
            # breaking it, so nothing else flags it.
            volts = [r['voltage_V'] for r in data['battery_voltage']
                     if r['voltage_V'] is not None]
            if volts and not n_pinned:
                lo, hi = min(volts), max(volts)
                if lo > 3.8 or hi < 2.0:
                    data['errors'].append(
                        f"BATTERY VOLTAGE IMPLAUSIBLE: {lo:.2f}-{hi:.2f} V, outside the "
                        "~2.5-3.65 V a 1S LiFePO4 cell can occupy. The counts are "
                        "believable, so suspect the conversion rather than the ADC: "
                        f"div_ratio in the log is {cal['div_ratio']:.4f} "
                        f"(R_top {cal['r_top_ohm']:.0f}, R_bottom "
                        f"{cal['r_bottom_ohm']:.0f}). If the divider was rebuilt with "
                        "different resistors, BATTERY_R_TOP_OHM / BATTERY_R_BOTTOM_OHM "
                        "in the firmware must be updated to match - the ratio is "
                        "compiled into the log, not measured.")
        else:
            data['errors'].append(
                "No BATTERY_CAL record in log — battery voltage is reported as "
                "raw ADC counts only, voltage_V left blank.")

    # ---- Do the two ADC channels interfere? -------------------------------------
    # Both channels are logged: battery at 1 Hz (0x14) and current at ~800 Hz (0x0E).
    # That is enough to answer "does the battery reading depend on what the current
    # channel is seeing" from any existing log, without a scope and without a special
    # firmware mode - group the battery samples by the current level in force at the
    # same instant and compare.
    #
    # WHY THIS IS REPORTED AND NOT DIAGNOSED: on a deployment log a battery reading that
    # sags when harvested current is high is REAL - it is the cell's internal resistance
    # under load, which is a thing this system exists to measure. The same number on a
    # BENCH capture, where a supply holds the battery node at a fixed voltage, can only
    # be the two inputs interacting through the wiring. The log cannot tell those apart,
    # so this prints the measurement and names both readings.
    if data['battery_voltage'] and data['current_fast'] and len(data['battery_voltage']) >= 4:
        cur = [(r['ts_ms'], r['counts']) for r in data['current_fast']]
        cur.sort()
        cur_ts = [t for t, _ in cur]
        adc_max_c = (data['current_cal'][0]['adc_max']
                     if data['current_cal'] else 16383.0) or 16383.0
        low, high = [], []
        for rec in data['battery_voltage']:
            # Current samples inside the +/-0.5 s the battery sample sits in.
            lo_i = bisect.bisect_left(cur_ts, rec['ts_ms'] - 500.0)
            hi_i = bisect.bisect_right(cur_ts, rec['ts_ms'] + 500.0)
            window = [c for _, c in cur[lo_i:hi_i]]
            if not window:
                continue
            level = sorted(window)[len(window) // 2] / adc_max_c
            (high if level > 0.20 else low if level < 0.05 else []).append(rec['counts'])
        if len(low) >= 3 and len(high) >= 3:
            m_low = sum(low) / len(low)
            m_high = sum(high) / len(high)
            delta = m_high - m_low
            pct = 100.0 * delta / m_low if m_low else 0.0
            data['notes'].append(
                f"ADC channel interaction: battery reads {m_low:.0f} counts while the "
                f"current channel is idle (n={len(low)}) and {m_high:.0f} while it is "
                f"driven (n={len(high)}) - a shift of {delta:+.0f} counts ({pct:+.1f}%). "
                "On a deployment log that is the cell sagging under load and is real. On "
                "a BENCH capture with a supply holding the battery node fixed it can only "
                "be the two inputs interacting through the wiring - check that both "
                "supply returns meet the board at ONE point and that nothing ties the two "
                "sense nodes together. The ADC itself measures both channels "
                "independently: docs/adc_calibration.md logged them simultaneously at "
                "500 Hz with different voltages on each, three times, and each tracked "
                "its own DMM value to within 1.4%.")

    # ---- Derive Hall edge periods and RPM ---------------------------------------
    # Done as a post-pass so it works across packet boundaries: edges are batched
    # into TYPE_HALL_EDGE records, and a period may span two records.
    #
    # PULSES_PER_REV is not stored in the log (it is a mechanical property), so
    # this assumes ONE magnet. If magnets are added, divide the rpm column by the
    # magnet count.
    if len(data['hall_edge']) > 1:
        edges = data['hall_edge']
        for i in range(1, len(edges)):
            # micros() wraps every ~71.6 min; uint32 subtraction handles it.
            p = (edges[i]['edge_us'] - edges[i - 1]['edge_us']) & 0xFFFFFFFF
            edges[i]['period_us'] = p
            if p > 0:
                edges[i]['rpm'] = 60.0e6 / p
        data['notes'].append(
            f"Derived RPM from {len(edges)} Hall edges assuming 1 magnet "
            "(PULSES_PER_REV is not recorded in the log).")

    # ---- Diagnose the logging path from the health records ----------------------
    # The counters are useless if nobody reads them, and the person opening a CSV after a
    # failed deployment is not going to know that 500 000 in loop_max_us means the I2C bus
    # stalled. Turn the raw columns into the conclusion.
    if data['sys_health']:
        h = data['sys_health']
        span_s = (h[-1]['ts_ms'] - h[0]['ts_ms']) / 1000.0 if len(h) > 1 else 0.0
        last = h[-1]

        # Separate timer faults from stalls BEFORE drawing any conclusion from the maxima.
        # A micros() backward step lands in loop_max_us as ~4.29e9 us, and because the
        # firmware max-holds, one glitch dominates the whole interval. Reporting that as a
        # stall sends the reader after an I2C bus that was never stuck, so the implausible
        # records are excluded from the maxima and reported separately for what they are.
        n_timer_anom = sum(1 for r in h
                           if r.get('timer_anomaly')
                           or r['loop_max_us'] >= TIMING_IMPLAUSIBLE_US
                           or r['sd_write_max_us'] >= TIMING_IMPLAUSIBLE_US)
        sane = [r for r in h if r['loop_max_us'] < TIMING_IMPLAUSIBLE_US
                and r['sd_write_max_us'] < TIMING_IMPLAUSIBLE_US]
        worst_loop = max((r['loop_max_us'] for r in sane), default=0)
        worst_write = max((r['sd_write_max_us'] for r in sane), default=0)

        if n_timer_anom:
            data['errors'].append(
                f"TIMER ANOMALY in {n_timer_anom} of {len(h)} health records: micros() "
                "stepped backwards, so the firmware's unsigned subtraction produced "
                "~4 294 967 295 us (about 4 294 967 ms). That is NOT a loop stall and NOT "
                "an I2C problem - it is a known Apollo3 quirk where two adjacent micros() "
                "calls can return n then n-1. Those records are excluded from the maxima "
                "below. Firmware from 2026-09-11 rejects them at the source; if this log "
                "predates that, reflash before reading loop_max_us at all.")

        data['notes'].append(
            f"Health: {len(h)} records over {span_s:.0f} s; worst loop pass "
            f"{worst_loop / 1000.0:.1f} ms, worst SD write {worst_write / 1000.0:.1f} ms, "
            f"queue high-water {max(r['sd_queue_high_water'] for r in h)} B.")

        # A loop pass longer than the 500 ms heartbeat interval is, by construction, a
        # visible LED freeze. This measures the reported symptom instead of guessing.
        if worst_loop >= 500000:
            if worst_write >= 250000:
                culprit = "a long SD write (see sd_write_max_us)"
            elif last['hall_rejected'] and span_s > 0 and \
                    last['hall_rejected'] / span_s > 100.0:
                culprit = ("the Hall interrupt storm below - at that edge rate the ISR "
                           "runs often enough to starve loop()")
            else:
                culprit = ("something OTHER than the SD write path - most likely an I2C "
                           "stall, since no other counter accounts for it")
            data['errors'].append(
                f"LOOP STALL: longest loop() pass was {worst_loop / 1000.0:.0f} ms. The "
                f"heartbeat LED toggles at the end of loop(), so any pass over 500 ms is a "
                f"visible freeze. Attributed to {culprit}.")
        elif worst_loop >= 100000:
            data['errors'].append(
                f"Longest loop() pass was {worst_loop / 1000.0:.0f} ms - not enough to "
                "freeze the LED, but far above the ~3 ms nominal. Worth watching.")

        if last['sd_write_failures']:
            data['errors'].append(
                f"SD WRITE FAILURES: {last['sd_write_failures']} since boot, "
                f"{last['sd_recoveries']} successful remounts. Each recovery starts a new "
                "LOGnnnnn.BIN, so look for sibling files - this log is not the whole run.")

        if last['sd_overruns']:
            data['errors'].append(
                f"SD QUEUE OVERRUNS: {last['sd_overruns']}. The RAM queue filled faster "
                "than the card drained it, so records were dropped.")

        if last['hall_rejected']:
            rate = last['hall_rejected'] / span_s if span_s > 0 else 0.0
            # 33.3 edges/s is one magnet at RPM_MAX_EXPECTED-adjacent 2000 RPM. Quoting the
            # ratio rather than the bare count is what makes the number actionable: a
            # handful of rejects is bounce, two orders of magnitude is a wiring fault.
            ratio = rate / 33.3 if rate else 0.0
            verdict = ("This is interference, not bounce" if ratio >= 5.0
                       else "Low enough to be contact bounce or a marginal magnet gap")
            data['errors'].append(
                f"HALL EDGE NOISE: {last['hall_rejected']} edges rejected by the ISR as "
                f"implausibly fast ({rate:.1f}/s average). A real rotor at 2000 RPM with "
                f"one magnet gives ~33 edges/s, so this is {ratio:.0f}x the maximum "
                f"mechanically possible rate. {verdict}. Every rejected edge still costs "
                "an interrupt, so the RPM channel is unusable AND loop() is paying for it. "
                "Fix at the wiring: shield the Hall line, route it away from the harvester "
                "output and its return, and add an RC at the sensor pin. Setting "
                "RPM_ENABLE 0 removes the load but not the noise.")

        if last['hall_lost']:
            data['errors'].append(
                f"HALL EDGES LOST: {last['hall_lost']} dropped because the ISR ring buffer "
                "was full. Either the edge rate is far above the mechanical maximum "
                "(interference) or loop() stalled for about a second.")

        if last['mag_absent']:
            data['notes'].append(
                "Magnetometer did not initialise at boot. Harmless while the stabilized "
                "IMU runs 6-DOF (nothing reads it), but no 0x07 records exist.")

    return data


_CSV_IMU_FIELDS = ('ts_ms', 'pitch', 'roll', 'heading', 'gx', 'gy', 'gz',
                   'ax', 'ay', 'az', 'interval_us')
_CSV_CAL_FIELDS = ('ts_ms', 'accel_bias_x', 'accel_bias_y', 'accel_bias_z',
                   'accel_scale_x', 'accel_scale_y', 'accel_scale_z',
                   'gyro_bias_x', 'gyro_bias_y', 'gyro_bias_z')

# Module-level so the CSV writer and the GUI's parse summary share ONE ordered source of
# truth. The summary used to iterate a parallel hard-coded key list that omitted
# Upper bounds the firmware can actually produce for the two variable-length records:
# CURRENT_BLOCK_LEN = 100 samples, HALL_EDGE_BUF_LEN = 32 slots (31 usable). A count above
# these did not come from the firmware; it came from a damaged byte, and trusting it would
# skip kilobytes of good data or run off the end of the file.
MAX_CURRENT_BLOCK_SAMPLES = 100
MAX_HALL_EDGES_PER_RECORD = 31

# How far ahead of the last good record a candidate header's timestamp may sit and still
# be believed during resynchronisation. ts_ms is millis() since boot and strictly
# increases within a file, so a header claiming to be more than this far in the future,
# or in the past, is garbage that happened to look like a header.
RESYNC_MAX_GAP_MS = 10 * 60 * 1000

# Records are NOT globally monotonic: a TYPE_CURRENT_BLOCK is stamped with its first
# sample's time but written up to ~125 ms later, after 1 Hz records stamped in between,
# and a recovery pass has held a block for 648 ms. So a valid header may sit a little
# BEFORE the last good timestamp. Allow that much; a candidate further back is garbage.
RESYNC_BACKWARD_MS = 5000


def _payload_len_at(buf, pos):
    """Payload length of the record whose 5-byte header starts at buf[pos], or None.

    None means "this cannot be a record header": unknown type, or a variable-length count
    the firmware could never have written. Reads only what it needs; never raises.
    """
    if pos + 5 > len(buf):
        return None
    t = buf[pos]
    if t == TYPE_CURRENT_BLOCK:
        if pos + 9 > len(buf):
            return None
        n = struct.unpack_from('<H', buf, pos + 7)[0]
        return 4 + 2 * n if 0 < n <= MAX_CURRENT_BLOCK_SAMPLES else None
    if t == TYPE_HALL_EDGE:
        if pos + 6 > len(buf):
            return None
        n = buf[pos + 5]
        return 1 + 4 * n if 0 < n <= MAX_HALL_EDGES_PER_RECORD else None
    return _SD_PAYLOAD_BYTES.get(t)


def _find_resync(buf, start, last_ts):
    """Byte offset of the next believable record header at or after `start`, or None.

    A header is believed only when BOTH it and the header that follows its payload are
    plausible: known type, and a timestamp that is not before the last good record and
    not more than RESYNC_MAX_GAP_MS after it. Two agreeing headers make an accidental
    match in sensor noise vanishingly unlikely (the type byte alone matches 1 in ~12).

    This is what turns a single damaged byte from "the rest of the file is lost" into
    "one record is lost". The SD format has no sync marker and no CRC, so without this
    the parser's only option on a bad type byte was to stop - and on a 520 MB day-long
    log, stopping at byte 1 000 000 discards 99.8 % of the data that is physically there.
    """
    n = len(buf)
    lo = last_ts - RESYNC_BACKWARD_MS if last_ts > RESYNC_BACKWARD_MS else 0
    hi = last_ts + RESYNC_MAX_GAP_MS
    pos = start
    while pos + 5 <= n:
        plen = _payload_len_at(buf, pos)
        if plen is not None:
            ts = struct.unpack_from('<I', buf, pos + 1)[0]
            if lo <= ts <= hi:
                nxt = pos + 5 + plen
                if nxt > n:
                    pos += 1              # would run past EOF: not a record, keep scanning
                    continue
                if nxt == n:
                    return pos            # exactly the last record in the file
                plen2 = _payload_len_at(buf, nxt)
                if plen2 is not None:
                    ts2 = struct.unpack_from('<I', buf, nxt + 1)[0]
                    if ts - RESYNC_BACKWARD_MS <= ts2 <= ts + RESYNC_MAX_GAP_MS:
                        return pos
        pos += 1
    return None


# 'imu_raw', 'rtc_event', 'fixed_cal' and 'stab_cal' — so a log from the committed
# IMU_RAW_ONLY=1 build reported zero IMU records even though _imuRaw.csv was written
# correctly. Adding a packet type must not require remembering a second list. (Issue 51)
_CSV_SCHEMAS = {
    'fixed_imu': ('imuFixed', _CSV_IMU_FIELDS),
    'stab_imu':  ('imuStab',  _CSV_IMU_FIELDS),
    'bme':       ('bme280',   ('ts_ms', 'pressure', 'humidity', 'temperature')),
    'gps':       ('gps',      ('ts_ms', 'satellites', 'latitude', 'longitude', 'altitude')),
    'rtc_event': ('rtcEvt',   ('ts_ms', 'year', 'month', 'day', 'hour', 'minute', 'second')),
    'mag':       ('mag',      ('ts_ms', 'mx', 'my', 'mz')),
    'fixed_cal': ('calFixed', _CSV_CAL_FIELDS),
    'stab_cal':  ('calStab',  _CSV_CAL_FIELDS),
    'current':   ('current',  ('ts_ms', 'counts', 'current_mA')),
    'current_fast': ('currentFast', ('ts_ms', 'counts', 'current_mA')),
    'current_cal': ('currentCal',
                    ('ts_ms', 'vref', 'adc_max', 'div_ratio', 'sens_mA_per_V')),
    'battery_cal': ('batteryCal',
                    ('ts_ms', 'vref', 'adc_max', 'r_top_ohm',
                     'r_bottom_ohm', 'div_ratio')),
    'battery_voltage': ('batteryVoltage', ('ts_ms', 'counts', 'voltage_V')),
    'rpm':       ('rpm',      ('ts_ms', 'rpm')),
    'sys_health': ('sysHealth', ('ts_ms', 'loop_max_us', 'sd_write_max_us',
                                 'sd_write_failures', 'sd_recoveries',
                                 'hall_rejected', 'hall_lost',
                                 'sd_queue_high_water', 'sd_overruns',
                                 'sd_error', 'mag_absent', 'timer_anomaly')),
    'lpf_cal':   ('lpfCal',   ('ts_ms', 'alpha_acc', 'alpha_gyro', 'alpha_mag',
                               'accel_cutoff_hz', 'gyro_cutoff_hz',
                               'mag_cutoff_hz', 'imu_rate_hz',
                               'mag_offset_x', 'mag_offset_y', 'mag_offset_z',
                               'mag_scale_x', 'mag_scale_y', 'mag_scale_z')),
    'hall_edge': ('hallEdge', ('ts_ms', 'edge_us', 'period_us', 'rpm')),
    # Column names carry units on purpose: the gyro is in MILLIdegrees/s, and a
    # reader assuming dps would be off by 1000x. Accel is milli-g.
    'imu_raw':   ('imuRaw',   ('ts_ms',
                               'fix_ax_mg', 'fix_ay_mg', 'fix_az_mg',
                               'fix_gx_mdps', 'fix_gy_mdps', 'fix_gz_mdps',
                               'stab_ax_mg', 'stab_ay_mg', 'stab_az_mg',
                               'stab_gx_mdps', 'stab_gy_mdps', 'stab_gz_mdps',
                               'interval_us')),
}


def write_csvs_from_parsed(data: dict, out_dir: str, base_name: str) -> list:
    """Write one CSV per packet type from the dict returned by parse_binary_file().

    Parameters
    ----------
    data     : dict returned by parse_binary_file()
    out_dir  : directory to write CSV files into
    base_name: filename stem (e.g. '05300428') used as the CSV prefix

    Returns
    -------
    list of str — paths of CSV files written
    """
    written = []
    for key, (suffix, fields) in _CSV_SCHEMAS.items():
        records = data.get(key, [])
        if not records:
            continue
        # Rename ts_ms → timestamp_ms in the CSV header to match existing CSVs
        header = ['timestamp_ms' if f == 'ts_ms' else f for f in fields]
        out_path = os.path.join(out_dir, f"{base_name}_{suffix}.csv")
        with open(out_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for rec in records:
                # A present-but-None field (e.g. current_mA with no cal record)
                # must write an empty cell, not the literal string "None".
                writer.writerow(
                    ['' if rec.get(field) is None else rec.get(field)
                     for field in fields])
        written.append(out_path)
    return written


# ---------------------------------------------------------------------------
# Command-line batch conversion
# ---------------------------------------------------------------------------

def convert(bin_path: str) -> list:
    """Parse one .BIN and write its CSVs next to it. Returns the paths written."""
    data = parse_binary_file(bin_path)
    out_dir = os.path.dirname(os.path.abspath(bin_path))
    base_name = os.path.splitext(os.path.basename(bin_path))[0]
    written = write_csvs_from_parsed(data, out_dir, base_name)
    for note in data.get('notes', []):
        print(f"  note: {note}")
    for err in data.get('errors', []):
        print(f"  WARNING: {err}")
    return written


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__.strip().split('\n\n')[-1])
        return 2
    for bin_path in argv[1:]:
        print(f"{bin_path}:")
        try:
            written = convert(bin_path)
        except OSError as e:
            print(f"  ERROR: {e}")
            return 1
        for p in written:
            print(f"  wrote {os.path.basename(p)}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
