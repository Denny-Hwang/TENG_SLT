import tkinter as tk
from tkinter import filedialog, messagebox
from collections import deque
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import serial
import serial.tools.list_ports
import struct
import os
import csv

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
    _imu_fields  = ('ts_ms', 'pitch', 'roll', 'heading', 'gx', 'gy', 'gz',
                    'ax', 'ay', 'az', 'interval_us')
    _cal_fields  = ('ts_ms', 'accel_bias_x', 'accel_bias_y', 'accel_bias_z',
                    'accel_scale_x', 'accel_scale_y', 'accel_scale_z',
                    'gyro_bias_x', 'gyro_bias_y', 'gyro_bias_z')
    _schemas = {
        'fixed_imu': ('imuFixed', _imu_fields),
        'stab_imu':  ('imuStab',  _imu_fields),
        'bme':       ('bme280',   ('ts_ms', 'pressure', 'humidity', 'temperature')),
        'gps':       ('gps',      ('ts_ms', 'satellites', 'latitude', 'longitude', 'altitude')),
        'rtc_event': ('rtcEvt',   ('ts_ms', 'year', 'month', 'day', 'hour', 'minute', 'second')),
        'mag':       ('mag',      ('ts_ms', 'mx', 'my', 'mz')),
        'fixed_cal': ('calFixed', _cal_fields),
        'stab_cal':  ('calStab',  _cal_fields),
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

    written = []
    for key, (suffix, fields) in _schemas.items():
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


class VertiSeaGUI:
    def __init__(self, root):
        self.root = root
        root.title("VertiSea Telemetry Monitor")
        self.ser = None
        self.buffer = bytearray()

        # ---- Connection controls -------------------------------------------
        conn_frame = tk.Frame(root)
        conn_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        tk.Label(conn_frame, text="COM Port:").pack(side=tk.LEFT)
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_var = tk.StringVar(value=ports[0] if ports else "")
        self.com_menu = tk.OptionMenu(conn_frame, self.port_var, *ports)
        self.com_menu.pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(conn_frame, text="Refresh", command=self.refresh_ports).pack(side=tk.LEFT)
        tk.Button(conn_frame, text="Connect", command=self.connect_serial).pack(side=tk.LEFT)

        # "Load BIN File" button — opens a file dialog and parses the SD binary log
        tk.Button(
            conn_frame, text="Load BIN File",
            command=self.load_bin_file,
            bg="#2060a0", fg="white", font=("TkDefaultFont", 9, "bold")
        ).pack(side=tk.LEFT, padx=(10, 0))

        # ---- Telemetry text fields -----------------------------------------
        info_frame = tk.Frame(root)
        info_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        # GPS fields
        gps_frame = tk.LabelFrame(info_frame, text="GPS")
        gps_frame.pack(side=tk.LEFT, padx=5)
        self.sats_var = tk.StringVar(value="N/A")
        self.lat_var  = tk.StringVar(value="N/A")
        self.lon_var  = tk.StringVar(value="N/A")
        for i, (lbl, var) in enumerate([("Sats:", self.sats_var),
                                         ("Lat:",  self.lat_var),
                                         ("Lon:",  self.lon_var)]):
            tk.Label(gps_frame, text=lbl).grid(row=i, column=0, sticky="e")
            tk.Label(gps_frame, textvariable=var).grid(row=i, column=1)

        # BME280 fields
        bme_frame = tk.LabelFrame(info_frame, text="BME280")
        bme_frame.pack(side=tk.LEFT, padx=5)
        self.press_var = tk.StringVar(value="N/A")
        self.hum_var   = tk.StringVar(value="N/A")
        self.temp_var  = tk.StringVar(value="N/A")
        for i, (lbl, var) in enumerate([("Pressure:", self.press_var),
                                         ("Humidity:", self.hum_var),
                                         ("Temp:",     self.temp_var)]):
            tk.Label(bme_frame, text=lbl).grid(row=i, column=0, sticky="e")
            tk.Label(bme_frame, textvariable=var).grid(row=i, column=1)

        # ---- System status panel -------------------------------------------
        status_frame = tk.LabelFrame(info_frame, text="System Status")
        status_frame.pack(side=tk.LEFT, padx=5)

        # SD card status indicator — green = OK, red = ERROR
        tk.Label(status_frame, text="SD Card:").grid(row=0, column=0, sticky="e", padx=(4, 2))
        self.sd_status_label = tk.Label(
            status_frame,
            text="  SD: OK  ",
            bg="green",
            fg="white",
            font=("TkDefaultFont", 10, "bold"),
            relief="raised",
            padx=4, pady=2
        )
        self.sd_status_label.grid(row=0, column=1, padx=(0, 4), pady=4)
        self._sd_ok = True  # track current state to avoid redundant redraws

        # Harvested current display
        tk.Label(status_frame, text="Current:").grid(row=1, column=0, sticky="e", padx=(4, 2))
        self.current_var = tk.StringVar(value="N/A")
        tk.Label(status_frame, textvariable=self.current_var).grid(row=1, column=1, sticky="w")

        # Battery voltage from the dedicated 1 Hz TYPE_BATTERY_VOLTAGE packet.
        tk.Label(status_frame, text="Battery:").grid(row=2, column=0, sticky="e", padx=(4, 2))
        self.battery_var = tk.StringVar(value="N/A")
        tk.Label(status_frame, textvariable=self.battery_var).grid(row=2, column=1, sticky="w")

        # Rotor RPM display (only populated when RPM_ENABLE=1 in firmware)
        tk.Label(status_frame, text="RPM:").grid(row=3, column=0, sticky="e", padx=(4, 2))
        self.rpm_var = tk.StringVar(value="N/A")
        tk.Label(status_frame, textvariable=self.rpm_var).grid(row=3, column=1, sticky="w")

        # ---- Harvested-energy panel (TYPE_CURRENT_STATS, 1 Hz) -------------
        # Peak current and the two accumulated integrals for the current 2-minute
        # window. The separate 1 Hz battery packet supplies voltage without
        # changing the verified TYPE_CURRENT_STATS layout; latest V × running
        # average I is displayed as average battery-side power.
        energy_frame = tk.LabelFrame(info_frame, text="Harvested (2 min window)")
        energy_frame.pack(side=tk.LEFT, padx=5)

        self.peak_var    = tk.StringVar(value="N/A")
        self.charge_var  = tk.StringVar(value="N/A")
        self.i2t_var     = tk.StringVar(value="N/A")
        self.iavg_var    = tk.StringVar(value="N/A")
        self.irms_var    = tk.StringVar(value="N/A")
        self.power_var   = tk.StringVar(value="N/A")
        self.window_var  = tk.StringVar(value="N/A")
        self.drops_var   = tk.StringVar(value="N/A")
        for i, (label, var) in enumerate((
            ("Peak I:",   self.peak_var),
            ("Avg I:",    self.iavg_var),
            ("RMS I:",    self.irms_var),
            ("Avg P:",    self.power_var),
            ("Charge:",   self.charge_var),
            ("\u222bI\u00b2dt:", self.i2t_var),
            ("Window:",   self.window_var),
            ("Dropped:",  self.drops_var),
        )):
            tk.Label(energy_frame, text=label).grid(row=i, column=0, sticky="e", padx=(4, 2))
            tk.Label(energy_frame, textvariable=var).grid(row=i, column=1, sticky="w")

        # ---- Rolling plot data (live telemetry via radio) ------------------
        self.time_data       = deque(maxlen=100)
        self.pitch_data      = deque(maxlen=100)   # fixed IMU pitch
        self.roll_data       = deque(maxlen=100)   # fixed IMU roll
        self.disp_data       = deque(maxlen=100)   # vertical displacement
        self.stab_pitch_data = deque(maxlen=100)   # stabilized IMU pitch
        self.stab_roll_data  = deque(maxlen=100)   # stabilized IMU roll
        # IMU tilt-difference (fixed minus stabilized) — mechanical input proxy
        self.diff_pitch_data = deque(maxlen=100)   # fix_pitch − stab_pitch (°)
        self.diff_roll_data  = deque(maxlen=100)   # fix_roll  − stab_roll  (°)
        # RPM (arrives as separate TYPE_RPM packets — own time axis)
        self.rpm_time_data   = deque(maxlen=100)
        self.rpm_data        = deque(maxlen=100)   # rotor RPM
        self._latest_battery_v = None
        self._latest_i_avg_mA = None

        # ts10 rollover compensation (fixes IDENTIFIED_ISSUES #16).
        # ts10 is uint16 (0–65535), representing millis()/10 (~655 s range).
        # When a backward jump is detected, add 65536 × 0.01 s to the offset.
        self._ts10_last   = 0
        self._ts10_offset = 0.0   # cumulative seconds added for each wrap

        # ---- Plot frames — 2×2 grid ----------------------------------------
        # Row 0: Fixed IMU (left) | Stabilized IMU (right)
        # Row 1: Mechanical input / RPM (left) | Placeholder (right)
        plot_frame = tk.Frame(root)
        plot_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.columnconfigure(1, weight=1)
        plot_frame.rowconfigure(0, weight=1)
        plot_frame.rowconfigure(1, weight=1)

        # Top-left — Fixed IMU Pitch & Roll (live radio telemetry)
        imu_fig = Figure(figsize=(5, 2.5))
        self.imu_ax = imu_fig.add_subplot(111)
        self.imu_ax.set_title("Attitude: Pitch & Roll (pendulum IMU — live radio)")
        self.imu_ax.set_ylabel("degrees")
        self.imu_ax.set_ylim(-60, 60)
        self.imu_line1, = self.imu_ax.plot([], [], label="pitch", color="tab:blue")
        self.imu_line2, = self.imu_ax.plot([], [], label="roll",  color="tab:orange")
        self.imu_ax.legend(loc="upper right")
        imu_fig.tight_layout()
        imu_canvas = FigureCanvasTkAgg(imu_fig, master=plot_frame)
        imu_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.imu_canvas = imu_canvas

        # Top-right — IMU tilt difference (left Y) vs Rotor RPM (right Y)
        # Left axis:  fix−stab pitch & roll difference (degrees) — mechanical input proxy
        # Right axis: rotor RPM from TYPE_RPM packets
        mech_fig = Figure(figsize=(5, 2.5))
        self.mech_ax  = mech_fig.add_subplot(111)  # left Y — tilt difference
        self.mech_ax2 = self.mech_ax.twinx()       # right Y — RPM
        self.mech_ax.set_title("Mechanical Input: IMU Tilt Difference & Rotor RPM")
        self.mech_ax.set_ylabel("pendulum − buoy (°)", color="tab:red")
        self.mech_ax2.set_ylabel("RPM", color="tab:blue")
        self.mech_ax.tick_params(axis="y", labelcolor="tab:red")
        self.mech_ax2.tick_params(axis="y", labelcolor="tab:blue")
        self.mech_ax.set_ylim(-60, 60)
        self.mech_ax2.set_ylim(0, 450)
        self.mech_line_dpitch, = self.mech_ax.plot([], [], label="Δpitch", color="tab:red",    linestyle="-")
        self.mech_line_droll,  = self.mech_ax.plot([], [], label="Δroll",  color="tab:orange", linestyle="--")
        self.mech_line_rpm,    = self.mech_ax2.plot([], [], label="RPM",   color="tab:blue",   linestyle="-")
        # Combined legend for both axes
        lines  = [self.mech_line_dpitch, self.mech_line_droll, self.mech_line_rpm]
        labels = ["Δpitch (°)", "Δroll (°)", "RPM"]  # tilt diff: pendulum − buoy
        self.mech_ax.legend(lines, labels, loc="upper right", fontsize=8)
        # Extra left/right margin so both y-axis labels are fully visible
        mech_fig.subplots_adjust(left=0.15, right=0.85)
        mech_canvas = FigureCanvasTkAgg(mech_fig, master=plot_frame)
        mech_canvas.get_tk_widget().grid(row=0, column=1, sticky="nsew")
        self.mech_canvas = mech_canvas
        self.mech_fig    = mech_fig

        # Bottom-left — Stabilized IMU Pitch & Roll (live radio telemetry)
        stab_fig = Figure(figsize=(5, 2.5))
        self.stab_ax = stab_fig.add_subplot(111)
        self.stab_ax.set_title("Attitude: Pitch & Roll (buoy IMU — live radio)")
        self.stab_ax.set_ylabel("degrees")
        self.stab_ax.set_ylim(-60, 60)
        self.stab_line_pitch, = self.stab_ax.plot([], [], label="pitch", color="tab:blue")
        self.stab_line_roll,  = self.stab_ax.plot([], [], label="roll",  color="tab:orange")
        self.stab_ax.legend(loc="upper right")
        stab_fig.tight_layout()
        stab_canvas = FigureCanvasTkAgg(stab_fig, master=plot_frame)
        stab_canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        self.stab_canvas = stab_canvas

        # Bottom-right — placeholder for future plot
        placeholder = tk.Frame(plot_frame, bg="#1a1a2e", relief="sunken", bd=2)
        placeholder.grid(row=1, column=1, sticky="nsew")
        tk.Label(
            placeholder,
            text="[ Future Plot ]",
            bg="#1a1a2e", fg="#555577",
            font=("TkDefaultFont", 12, "italic")
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Kick off the update loop
        root.after(100, self.update)

    # -----------------------------------------------------------------------
    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        menu = self.com_menu["menu"]
        menu.delete(0, "end")
        for p in ports:
            menu.add_command(label=p, command=lambda v=p: self.port_var.set(v))
        if ports:
            self.port_var.set(ports[0])

    def connect_serial(self):
        port = self.port_var.get()
        try:
            # IMPORTANT — do not let pyserial assert RTS/DTR on open.
            #
            # The RedBoard Artemis Nano uses a CH340E whose RTS line is wired to
            # the Artemis reset pin (it is how the SVL bootloader is triggered).
            # pyserial asserts BOTH dtr and rts by default when opening a port,
            # so a plain serial.Serial(port, ...) REBOOTS THE BUOY — losing the
            # in-progress SD log, restarting millis(), and appending a second
            # session to the same file if the RTC minute has not rolled over.
            #
            # This was observed on 2026-09-02: connecting the GUI ~14 s after
            # power-up produced a log containing two complete boot sequences with
            # ts_ms resetting 10002 -> 591.
            #
            # Constructing with port=None defers opening, so rts/dtr can be
            # cleared BEFORE the port is opened. Setting them after the fact
            # would be too late — the reset pulse has already happened.
            self.ser = serial.Serial(baudrate=115200, timeout=0.1)
            self.ser.port = port
            try:
                self.ser.rts = False
                self.ser.dtr = False
            except (OSError, AttributeError, ValueError):
                # Some drivers/platforms reject setting these while closed.
                # Not fatal: fall through and open anyway rather than refusing
                # to connect at all.
                pass
            self.ser.open()
            self.buffer = bytearray()
            messagebox.showinfo(
                "Connected",
                f"Opened {port} @115200 baud\n"
                "(RTS/DTR held low so the board is not reset)")
        except Exception as e:
            self.ser = None
            messagebox.showerror("Error", f"Could not open {port}:\n{e}")

    def _set_sd_status(self, ok: bool):
        """Update the SD status indicator label colour and text."""
        if ok == self._sd_ok:
            return  # no change — skip redundant widget update
        self._sd_ok = ok
        if ok:
            self.sd_status_label.config(text="  SD: OK  ", bg="green")
        else:
            self.sd_status_label.config(text=" SD: ERROR ", bg="red")

    # -----------------------------------------------------------------------
    def load_bin_file(self):
        """Open a file dialog, parse the selected .BIN file, write CSVs, and
        update the lower plot with the stabilized IMU pitch & roll data."""
        bin_path = filedialog.askopenfilename(
            title="Select VertiSea SD binary log",
            filetypes=[("Binary log", "*.BIN *.bin"), ("All files", "*.*")]
        )
        if not bin_path:
            return  # user cancelled

        try:
            data = parse_binary_file(bin_path)
        except Exception as e:
            messagebox.showerror("Parse Error", f"Failed to parse {bin_path}:\n{e}")
            return

        # Write CSVs alongside the BIN file
        out_dir   = os.path.dirname(bin_path)
        base_name = os.path.splitext(os.path.basename(bin_path))[0]
        try:
            written = write_csvs_from_parsed(data, out_dir, base_name)
        except Exception as e:
            messagebox.showwarning("CSV Write Warning",
                                   f"Parsed OK but could not write CSVs:\n{e}")
            written = []

        # Report genuine parse warnings only. Informational messages live in
        # data['notes'] and are folded into the summary dialog instead, so that a
        # warning popup always means something actually needs attention.
        if data['errors']:
            messagebox.showwarning(
                "Parse Warnings",
                f"{len(data['errors'])} warning(s) during parse:\n" +
                "\n".join(data['errors'][:10]) +
                ("\n…" if len(data['errors']) > 10 else "")
            )

        bin_fname = base_name + ".BIN"

        # ---- Update upper plot with fixed IMU pitch & roll from BIN file ---
        fixed_records = data.get('fixed_imu', [])
        if fixed_records:
            t_s     = [r['ts_ms'] / 1000.0 for r in fixed_records]
            pitches = [r['pitch']           for r in fixed_records]
            rolls   = [r['roll']            for r in fixed_records]
            self.imu_line1.set_data(t_s, pitches)
            self.imu_line2.set_data(t_s, rolls)
            self.imu_ax.relim()
            self.imu_ax.autoscale_view()
            self.imu_ax.set_xlabel("time (s)")
            self.imu_ax.set_title(
                f"Attitude: Pitch & Roll (pendulum IMU — {bin_fname})"
            )
            self.imu_canvas.draw()

        # ---- Update lower plot with stabilized IMU pitch & roll ------------
        stab_records = data.get('stab_imu', [])
        if not stab_records:
            messagebox.showinfo(
                "No Buoy IMU Data",
                "The BIN file contained no TYPE_STAB_IMU (0x02) packets."
            )
        else:
            t_s     = [r['ts_ms'] / 1000.0 for r in stab_records]
            pitches = [r['pitch']           for r in stab_records]
            rolls   = [r['roll']            for r in stab_records]
            self.stab_line_pitch.set_data(t_s, pitches)
            self.stab_line_roll.set_data(t_s, rolls)
            self.stab_ax.relim()
            self.stab_ax.autoscale_view()
            self.stab_ax.set_xlabel("time (s)")
            self.stab_ax.set_title(
                f"Attitude: Pitch & Roll (buoy IMU — {bin_fname})"
            )
            self.stab_canvas.draw()

        # Summary message
        summary_lines = [f"Parsed: {os.path.basename(bin_path)}"]
        for key in ('fixed_imu', 'stab_imu', 'bme', 'gps', 'mag', 'current',
                    'current_fast', 'current_cal', 'battery_cal',
                    'battery_voltage', 'lpf_cal', 'hall_edge', 'rpm'):
            n = len(data.get(key, []))
            if n:
                summary_lines.append(f"  {key}: {n:,} records")
        if written:
            summary_lines.append(f"\nCSVs written ({len(written)}):")
            for p in written:
                summary_lines.append(f"  {os.path.basename(p)}")
        if data.get('notes'):
            summary_lines.append("\nNotes:")
            for n in data['notes']:
                summary_lines.append(f"  {n}")
        messagebox.showinfo("Parse Complete", "\n".join(summary_lines))

    # -----------------------------------------------------------------------
    def update(self):
        # Read all available bytes from the serial port
        if self.ser and self.ser.in_waiting:
            self.buffer.extend(self.ser.read(self.ser.in_waiting))

        # Parse packets — consume as many complete packets as possible
        while len(self.buffer) >= 1:
            p = self.buffer[0]

            # ---- TYPE_TELEM_IMU (0x06) — 13 bytes -------------------------
            # Payload: uint16 ts10,
            #          int16 fix_pitch_cdeg, int16 fix_roll_cdeg,  (centidegrees ×100)
            #          int16 vertDisp_mm,
            #          int16 stab_pitch_cdeg, int16 stab_roll_cdeg (centidegrees ×100)
            # Angle scale ×100 supports ±327.67° without int16 overflow.
            if p == TYPE_TELEM_IMU:
                if len(self.buffer) < 13:
                    break  # wait for more data
                pkt = self.buffer[:13]
                del self.buffer[:13]
                _, ts10, pitch_cdeg, roll_cdeg, disp_mm, stab_pitch_cdeg, stab_roll_cdeg = \
                    struct.unpack('<BHhhhhh', pkt)
                # Detect ts10 rollover and accumulate offset (fixes IDENTIFIED_ISSUES #16)
                if ts10 < self._ts10_last:
                    self._ts10_offset += 65536 * 0.01  # one full uint16 wrap = 655.36 s
                self._ts10_last = ts10
                t          = ts10 * 0.01 + self._ts10_offset  # monotonic seconds since boot
                pitch      = pitch_cdeg      / 100.0   # fixed IMU pitch (degrees)
                roll       = roll_cdeg       / 100.0   # fixed IMU roll  (degrees)
                disp       = disp_mm         / 1000.0  # vertical displacement (metres)
                stab_pitch = stab_pitch_cdeg / 100.0   # stabilized IMU pitch (degrees)
                stab_roll  = stab_roll_cdeg  / 100.0   # stabilized IMU roll  (degrees)
                self.time_data.append(t)
                self.pitch_data.append(pitch)
                self.roll_data.append(roll)
                self.disp_data.append(disp)
                self.stab_pitch_data.append(stab_pitch)
                self.stab_roll_data.append(stab_roll)
                # Tilt difference: fixed IMU minus stabilized IMU
                self.diff_pitch_data.append(pitch - stab_pitch)
                self.diff_roll_data.append(roll  - stab_roll)
                # Update upper plot — fixed IMU pitch & roll
                self.imu_line1.set_data(self.time_data, self.pitch_data)
                self.imu_line2.set_data(self.time_data, self.roll_data)
                self.imu_ax.relim()
                self.imu_ax.autoscale_view()
                self.imu_canvas.draw()
                # Update lower plot — stabilized IMU pitch & roll
                self.stab_line_pitch.set_data(self.time_data, self.stab_pitch_data)
                self.stab_line_roll.set_data(self.time_data, self.stab_roll_data)
                self.stab_ax.relim()
                self.stab_ax.autoscale_view()
                self.stab_canvas.draw()
                # Update third plot — tilt difference (left axis)
                self.mech_line_dpitch.set_data(self.time_data, self.diff_pitch_data)
                self.mech_line_droll.set_data(self.time_data, self.diff_roll_data)
                self.mech_ax.relim()
                self.mech_ax.autoscale_view(scaley=False)  # scroll x; y fixed at ±60°
                self.mech_canvas.draw()
                continue

            # ---- TYPE_GPS (0x04) — 12 bytes (radio format) -----------------
            # Payload: uint16 ts10, uint8 sats, float lat, float lon
            elif p == TYPE_GPS:
                if len(self.buffer) < 12:
                    break
                pkt = self.buffer[:12]
                del self.buffer[:12]
                _, ts10, sats, lat, lon = struct.unpack('<BHBff', pkt)
                self.sats_var.set(str(sats))
                self.lat_var.set(f"{lat:.6f}")
                self.lon_var.set(f"{lon:.6f}")
                continue

            # ---- TYPE_BME (0x03) — 15 bytes (radio format) -----------------
            # Payload: uint16 ts10, float pressure (Pa), float humidity (%), float temp (°C)
            elif p == TYPE_BME:
                if len(self.buffer) < 15:
                    break
                pkt = self.buffer[:15]
                del self.buffer[:15]
                _, ts10, pres, hum, tmp = struct.unpack('<BHfff', pkt)
                self.press_var.set(f"{pres/100.0:.1f} hPa")
                self.hum_var.set(f"{hum:.1f} %")
                self.temp_var.set(f"{tmp:.1f} °C")
                continue

            # ---- TYPE_CURRENT_STATS (0x0F) — 27 bytes (radio format) -------
            # Payload: uint16 ts10, uint16 window_s, uint16 peak_mA,
            #          float charge_mC, float i2t_mA2s, float integ_s,
            #          uint32 n_samples, uint32 n_dropped
            elif p == TYPE_CURRENT_STATS:
                if len(self.buffer) < 27:
                    break
                pkt = self.buffer[:27]
                del self.buffer[:27]
                (_, ts10, window_s, peak_mA, charge_mC, i2t_mA2s, integ_s,
                 n_samples, n_dropped) = struct.unpack('<BHHHfffII', pkt)

                self.peak_var.set(f"{peak_mA} mA")
                self.charge_var.set(f"{charge_mC:.1f} mC")
                self.i2t_var.set(f"{i2t_mA2s:.1f} mA\u00b2s")

                # Average and RMS must be divided by the TRUE integration time
                # (integ_s), not the wall-clock window. When the sampler cannot
                # hit its requested rate the two differ substantially and using
                # window_s understates both by exactly that ratio.
                if integ_s > 0:
                    i_avg = charge_mC / integ_s
                    self._latest_i_avg_mA = i_avg
                    self.iavg_var.set(f"{i_avg:.3f} mA")
                    self.irms_var.set(f"{(i2t_mA2s / integ_s) ** 0.5:.3f} mA")
                    # The System Status "Current:" field used to come from the 5 Hz
                    # TYPE_CURRENT (0x0A) packet, which was retired because a point
                    # sample of a bursty signal reads ~2.1x high. It now shows the
                    # window average, which is unbiased. Labelled "avg" so it is not
                    # mistaken for an instantaneous reading.
                    self.current_var.set(f"{i_avg:.2f} mA avg")
                    if self._latest_battery_v is not None:
                        self.power_var.set(
                            f"{self._latest_battery_v * i_avg:.3f} mW")
                    else:
                        self.power_var.set("--")
                else:
                    self._latest_i_avg_mA = None
                    self.iavg_var.set("--")
                    self.irms_var.set("--")
                    self.current_var.set("--")
                    self.power_var.set("--")

                # Effective sample rate and duty give an immediate read on
                # whether the sampler is keeping up.
                if window_s > 0:
                    rate = n_samples / window_s
                    duty = 100.0 * integ_s / window_s
                    self.window_var.set(
                        f"{window_s}s  n={n_samples}  {rate:.0f}Hz  duty={duty:.0f}%")
                else:
                    self.window_var.set(f"{window_s}s  n={n_samples}")

                if n_dropped:
                    self.drops_var.set(f"{n_dropped}  (rate below request)")
                else:
                    self.drops_var.set("0")
                continue

            # ---- TYPE_BATTERY_VOLTAGE (0x14) — 5 bytes (radio format) ------
            # Payload: uint16 ts10, uint16 battery_mV. Calibration stays in the
            # SD-only 0x13 record; telemetry is already converted by firmware.
            elif p == TYPE_BATTERY_VOLTAGE:
                if len(self.buffer) < 5:
                    break
                pkt = self.buffer[:5]
                del self.buffer[:5]
                _, ts10, battery_mV = struct.unpack('<BHH', pkt)
                self._latest_battery_v = battery_mV / 1000.0
                self.battery_var.set(f"{self._latest_battery_v:.3f} V")
                if self._latest_i_avg_mA is not None:
                    self.power_var.set(
                        f"{self._latest_battery_v * self._latest_i_avg_mA:.3f} mW")
                continue

            # ---- TYPE_RPM (0x0C) — 5 bytes (radio format) ------------------
            # Payload: uint16 ts10, uint16 rpm
            elif p == TYPE_RPM:
                if len(self.buffer) < 5:
                    break
                pkt = self.buffer[:5]
                del self.buffer[:5]
                _, ts10, rpm = struct.unpack('<BHH', pkt)
                self.rpm_var.set(f"{rpm} RPM")
                # Reuse ts10 rollover offset from the IMU packet stream
                t_rpm = ts10 * 0.01 + self._ts10_offset
                self.rpm_time_data.append(t_rpm)
                self.rpm_data.append(rpm)
                # Update third plot — RPM (right axis)
                self.mech_line_rpm.set_data(self.rpm_time_data, self.rpm_data)
                self.mech_ax2.relim()
                self.mech_ax2.autoscale_view(scaley=False)  # scroll x; y fixed at 0–500 RPM
                self.mech_canvas.draw()
                continue

            # ---- TYPE_STATUS (0x0B) — 4 bytes (radio only) -----------------
            # Payload: uint16 ts10, uint8 flags
            #   flags bit 0 = sdError (0=OK, 1=SD write failure)
            elif p == TYPE_STATUS:
                if len(self.buffer) < 4:
                    break
                pkt = self.buffer[:4]
                del self.buffer[:4]
                _, ts10, flags = struct.unpack('<BHB', pkt)
                sd_ok = not bool(flags & STATUS_FLAG_SD_ERROR)
                self._set_sd_status(sd_ok)
                continue

            # ---- Unknown / out-of-sync byte --------------------------------
            # Drop one byte and try again. This handles framing errors and
            # any packet types not yet implemented in this parser.
            else:
                del self.buffer[0]
                continue

        # Schedule next update (100 ms poll interval)
        self.root.after(100, self.update)


if __name__ == "__main__":
    root = tk.Tk()
    app = VertiSeaGUI(root)
    root.mainloop()
