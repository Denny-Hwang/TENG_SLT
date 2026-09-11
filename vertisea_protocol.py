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
        'rpm': [], 'battery_cal': [], 'battery_voltage': [],
        'errors': [], 'notes': []
    }

    _imu_fields = ('pitch', 'roll', 'heading', 'gx', 'gy', 'gz', 'ax', 'ay', 'az',
                   'interval_us')
    _cal_fields = ('accel_bias_x', 'accel_bias_y', 'accel_bias_z',
                   'accel_scale_x', 'accel_scale_y', 'accel_scale_z',
                   'gyro_bias_x', 'gyro_bias_y', 'gyro_bias_z')

    with open(bin_path, 'rb') as fid:
        file_size = os.path.getsize(bin_path)
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
                raw = fid.read(2 * n)
                byte_offset += len(raw)
                if len(raw) < 2 * n:
                    data['errors'].append(
                        f"Truncated CURRENT_BLOCK payload at offset {byte_offset} "
                        f"(wanted {2 * n} bytes, got {len(raw)})")
                    break
                samples = struct.unpack(f'<{n}H', raw)
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
                    data['errors'].append(
                        f"Unknown packet type 0x{pkt_type:02X} at byte offset "
                        f"{byte_offset} — cannot determine payload size; stopping.")
                    break

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
        else:
            data['errors'].append(
                "No BATTERY_CAL record in log — battery voltage is reported as "
                "raw ADC counts only, voltage_V left blank.")

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

    return data


_CSV_IMU_FIELDS = ('ts_ms', 'pitch', 'roll', 'heading', 'gx', 'gy', 'gz',
                   'ax', 'ay', 'az', 'interval_us')
_CSV_CAL_FIELDS = ('ts_ms', 'accel_bias_x', 'accel_bias_y', 'accel_bias_z',
                   'accel_scale_x', 'accel_scale_y', 'accel_scale_z',
                   'gyro_bias_x', 'gyro_bias_y', 'gyro_bias_z')

# Module-level so the CSV writer and the GUI's parse summary share ONE ordered source of
# truth. The summary used to iterate a parallel hard-coded key list that omitted
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
