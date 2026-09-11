#!/usr/bin/env python3
"""Round-trip tests for the VertiSea SD binary protocol.

WHY THIS EXISTS
---------------
`vertisea_plot_v7.py` is the *only* reader of the SD log format. Every packet layout is
duplicated by hand in two places — the packed structs in `VertiSea/VertiSea.ino` and the
`struct.unpack` format strings here — with nothing but discipline keeping them aligned.
A silent divergence corrupts every CSV produced from that point on, and the corruption is
not obvious: a wrong field width shifts subsequent columns into plausible-looking numbers.

So this file builds `.BIN` byte streams from the layouts documented in
`docs/binary_protocol.md`, feeds them through `parse_binary_file()`, and asserts the values
come back unchanged. It is a *writer* independent of the parser: if the parser's field
order or width drifts, the assertion fails.

WHAT IT DOES NOT PROVE
----------------------
That the firmware emits these bytes. Nothing here compiles or runs the sketch, so a change
made to `VertiSea.ino` alone will not fail these tests — they pin the parser against the
protocol document, not against the firmware. Issue 35 is the standing reminder that a
round-trip test proves the *transport* is right and says nothing about whether the chosen
types can hold real values: an int16 gyro field round-tripped perfectly and still wrapped
sign on hardware. Check a real log against physical expectations too.

USAGE
-----
    python3 tests/test_binary_protocol.py        # stdlib only, no pytest required
    python3 -m pytest tests/test_binary_protocol.py -q    # also works under pytest
"""

import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vertisea_protocol as vs  # noqa: E402


# ---------------------------------------------------------------------------
# Record writers — independent of the parser, built from docs/binary_protocol.md
# ---------------------------------------------------------------------------

def record(pkt_type: int, ts_ms: int, payload: bytes) -> bytes:
    """The 5-byte common header (uint8 type + uint32 little-endian ms) plus payload."""
    return struct.pack('<BI', pkt_type, ts_ms) + payload


def imu_raw(ts_ms, fix_a, fix_g, stab_a, stab_g, interval_us) -> bytes:
    """0x12 — '<3h3i3h3iH', 38-byte payload."""
    return record(vs.TYPE_IMU_RAW, ts_ms,
                  struct.pack('<3h3i3h3iH', *fix_a, *fix_g, *stab_a, *stab_g, interval_us))


def current_block(ts_ms, span_ms, samples) -> bytes:
    """0x0E — uint16 span_ms, uint16 count, count x uint16. Variable length."""
    return record(vs.TYPE_CURRENT_BLOCK, ts_ms,
                  struct.pack('<HH', span_ms, len(samples))
                  + struct.pack(f'<{len(samples)}H', *samples))


def hall_edge(ts_ms, edges_us) -> bytes:
    """0x11 — uint8 count, count x uint32 micros(). Variable length."""
    return record(vs.TYPE_HALL_EDGE, ts_ms,
                  struct.pack('<B', len(edges_us))
                  + struct.pack(f'<{len(edges_us)}I', *edges_us))


def sys_health(ts_ms, loop_max_us=3000, sd_write_max_us=1200, sd_write_failures=0,
               sd_recoveries=0, hall_rejected=0, hall_lost=0,
               sd_queue_high_water=512, sd_overruns=0, flags=0) -> bytes:
    """0x15 — '<6I2HB', 29-byte payload."""
    return record(vs.TYPE_SYS_HEALTH, ts_ms,
                  struct.pack('<6I2HB', loop_max_us, sd_write_max_us,
                              sd_write_failures, sd_recoveries, hall_rejected,
                              hall_lost, sd_queue_high_water, sd_overruns, flags))


def current_cal(ts_ms, vref, adc_max, div_ratio, sens) -> bytes:
    return record(vs.TYPE_CURRENT_CAL, ts_ms,
                  struct.pack('<4f', vref, adc_max, div_ratio, sens))


def battery_cal(ts_ms, vref, adc_max, r_top, r_bottom, ratio) -> bytes:
    return record(vs.TYPE_BATTERY_CAL, ts_ms,
                  struct.pack('<5f', vref, adc_max, r_top, r_bottom, ratio))


# `data['errors']` mixes two different things: structural failures that stop the parse
# (truncated record, unknown type) and advisory warnings about an otherwise-fine log
# (no calibration record, so the derived column stays blank). Most tests care only about
# the former, so they assert on this filtered view rather than on an empty list.
_STRUCTURAL = ('Truncated', 'Unknown packet type', 'Skipped known-type')


def structural_errors(data: dict) -> list:
    return [e for e in data['errors'] if any(k in e for k in _STRUCTURAL)]


def parse_bytes(blob: bytes) -> dict:
    """Write `blob` to a temp .BIN and run the production parser over it."""
    fd, path = tempfile.mkstemp(suffix='.BIN')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(blob)
        return vs.parse_binary_file(path)
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------


class TestFixedLayouts(unittest.TestCase):
    """Every fixed-size packet survives a write/parse round trip."""

    def test_imu_raw_round_trip(self):
        data = parse_bytes(imu_raw(
            12345,
            fix_a=(-1000, 2000, 980), fix_g=(-250000, 250000, 1),
            stab_a=(11, -22, 1001), stab_g=(7, -8, 9),
            interval_us=10780))
        self.assertEqual(data['errors'], [])
        self.assertEqual(len(data['imu_raw']), 1)
        r = data['imu_raw'][0]
        self.assertEqual(r['ts_ms'], 12345)
        self.assertEqual((r['fix_ax_mg'], r['fix_ay_mg'], r['fix_az_mg']), (-1000, 2000, 980))
        self.assertEqual((r['fix_gx_mdps'], r['fix_gy_mdps'], r['fix_gz_mdps']),
                         (-250000, 250000, 1))
        self.assertEqual((r['stab_ax_mg'], r['stab_ay_mg'], r['stab_az_mg']), (11, -22, 1001))
        self.assertEqual(r['interval_us'], 10780)

    def test_imu_raw_gyro_holds_full_scale(self):
        """Issue 35: at ISM_500dps the gyro reaches 500000 mdps, 15x the int16 range.

        An int32 field must carry it without wrapping sign. This is the regression that
        int16 passed structurally and failed on hardware.
        """
        full_scale = 500000
        data = parse_bytes(imu_raw(
            1, fix_a=(0, 0, 1000), fix_g=(full_scale, -full_scale, full_scale),
            stab_a=(0, 0, 1000), stab_g=(-full_scale, full_scale, -full_scale),
            interval_us=0))
        r = data['imu_raw'][0]
        self.assertEqual(r['fix_gx_mdps'], full_scale)
        self.assertEqual(r['fix_gy_mdps'], -full_scale)
        self.assertEqual(r['stab_gx_mdps'], -full_scale)

    def test_processed_imu_round_trip(self):
        payload = struct.pack('<9fH', 1.5, -2.5, 999.9, 0.1, 0.2, 0.3,
                              0.01, 0.02, 1.0, 9615)
        data = parse_bytes(record(vs.TYPE_FIXED_IMU, 7, payload)
                           + record(vs.TYPE_STAB_IMU, 8, payload))
        self.assertEqual(data['errors'], [])
        f = data['fixed_imu'][0]
        self.assertAlmostEqual(f['pitch'], 1.5, places=5)
        self.assertAlmostEqual(f['roll'], -2.5, places=5)
        self.assertAlmostEqual(f['heading'], 999.9, places=3)
        self.assertEqual(f['interval_us'], 9615)
        self.assertEqual(data['stab_imu'][0]['ts_ms'], 8)

    def test_rtc_event_year_offset(self):
        """Year is stored as an offset from 2000; the parser must add it back exactly once.

        Issue 28 was a double-add of 2000 producing years near 4074.
        """
        data = parse_bytes(record(vs.TYPE_RTC_EVENT, 100,
                                  struct.pack('<6B', 26, 9, 11, 17, 42, 7)))
        r = data['rtc_event'][0]
        self.assertEqual(r['year'], 2026)
        self.assertEqual((r['month'], r['day'], r['hour'], r['minute'], r['second']),
                         (9, 11, 17, 42, 7))

    def test_bme_gps_rpm_round_trip(self):
        blob = (record(vs.TYPE_BME, 1, struct.pack('<3f', 101325.0, 43.5, 21.25))
                + record(vs.TYPE_GPS, 2, struct.pack('<B', 9)
                         + struct.pack('<3f', 46.25, -119.5, 120.0))
                + record(vs.TYPE_RPM, 3, struct.pack('<H', 1987)))
        data = parse_bytes(blob)
        self.assertEqual(data['errors'], [])
        self.assertAlmostEqual(data['bme'][0]['pressure'], 101325.0, places=1)
        self.assertEqual(data['gps'][0]['satellites'], 9)
        self.assertAlmostEqual(data['gps'][0]['latitude'], 46.25, places=4)
        self.assertEqual(data['rpm'][0]['rpm'], 1987)

    def test_cal_packets_field_order(self):
        """The nine IMUCal floats must land in bias/scale/bias order, not shuffled."""
        vals = (1.0, 2.0, 3.0, 1004.5, 1007.0, 999.0, -2.36, -396.8, -192.5)
        data = parse_bytes(record(vs.TYPE_FIXED_CAL, 5, struct.pack('<9f', *vals)))
        c = data['fixed_cal'][0]
        self.assertAlmostEqual(c['accel_bias_x'], 1.0, places=5)
        self.assertAlmostEqual(c['accel_scale_x'], 1004.5, places=3)
        # gyro_bias is in MILLIdegrees/s, not deg/s — see Issue 42.
        self.assertAlmostEqual(c['gyro_bias_y'], -396.8, places=3)

    def test_payload_table_matches_the_writers(self):
        """_SD_PAYLOAD_BYTES is used to skip unhandled packets; a wrong entry desyncs.

        Variable-length types must stay OUT of the table — they cannot be skipped from a
        fixed size.
        """
        self.assertEqual(vs._SD_PAYLOAD_BYTES[vs.TYPE_IMU_RAW], 38)
        self.assertEqual(vs._SD_PAYLOAD_BYTES[vs.TYPE_FIXED_CAL], 36)
        self.assertEqual(vs._SD_PAYLOAD_BYTES[vs.TYPE_LPF_CAL], 52)
        self.assertEqual(vs._SD_PAYLOAD_BYTES[vs.TYPE_BATTERY_CAL], 20)
        self.assertNotIn(vs.TYPE_CURRENT_BLOCK, vs._SD_PAYLOAD_BYTES)
        self.assertNotIn(vs.TYPE_HALL_EDGE, vs._SD_PAYLOAD_BYTES)


class TestSysHealth(unittest.TestCase):
    """0x15 is the record that makes a field failure diagnosable after the fact."""

    def test_round_trip_and_flags(self):
        data = parse_bytes(sys_health(
            1000, loop_max_us=2837, sd_write_max_us=1104,
            sd_write_failures=2, sd_recoveries=1, hall_rejected=17, hall_lost=3,
            sd_queue_high_water=1536, sd_overruns=1,
            flags=vs.HEALTH_FLAG_NO_MAG))
        self.assertEqual(structural_errors(data), [])
        r = data['sys_health'][0]
        self.assertEqual(r['loop_max_us'], 2837)
        self.assertEqual(r['sd_write_max_us'], 1104)
        self.assertEqual(r['sd_write_failures'], 2)
        self.assertEqual(r['sd_recoveries'], 1)
        self.assertEqual(r['hall_rejected'], 17)
        self.assertEqual(r['hall_lost'], 3)
        self.assertEqual(r['sd_queue_high_water'], 1536)
        self.assertEqual(r['sd_overruns'], 1)
        self.assertFalse(r['sd_error'])
        self.assertTrue(r['mag_absent'])

    def test_counters_hold_a_multi_day_deployment(self):
        """uint32 must not wrap over a 2-day run — that is the design target."""
        two_days_us = 2 * 86400 * 1000000
        self.assertGreater(2**32 - 1, 600000)          # loop stalls are ms-scale
        data = parse_bytes(sys_health(two_days_us % (2**32), loop_max_us=4294967295,
                                      hall_rejected=4000000))
        r = data['sys_health'][0]
        self.assertEqual(r['loop_max_us'], 4294967295)
        self.assertEqual(r['hall_rejected'], 4000000)

    def test_healthy_log_produces_no_warning(self):
        data = parse_bytes(b''.join(sys_health(i * 1000) for i in range(10)))
        self.assertEqual(structural_errors(data), [])
        self.assertEqual(data['errors'], [], "a healthy log must not raise warnings")
        self.assertTrue(any('Health:' in n for n in data['notes']))

    def test_loop_stall_is_reported_as_an_led_freeze(self):
        blob = (sys_health(1000) + sys_health(2000, loop_max_us=812000)
                + sys_health(3000))
        data = parse_bytes(blob)
        msg = ' '.join(data['errors'])
        self.assertIn('LOOP STALL', msg)
        self.assertIn('812 ms', msg)
        self.assertIn('I2C', msg, "no SD write to blame -> must point elsewhere")

    def test_loop_stall_blamed_on_sd_when_the_write_explains_it(self):
        data = parse_bytes(sys_health(1000, loop_max_us=700000,
                                      sd_write_max_us=690000)
                           + sys_health(2000))
        msg = ' '.join(data['errors'])
        self.assertIn('LOOP STALL', msg)
        self.assertIn('SD write', msg)

    def test_hall_interference_is_named_as_interference(self):
        blob = sys_health(1000) + sys_health(11000, hall_rejected=9000)
        data = parse_bytes(blob)
        msg = ' '.join(data['errors'])
        self.assertIn('HALL EDGE NOISE', msg)
        self.assertIn('900.0/s', msg)

    def test_sd_failure_points_at_the_sibling_files(self):
        data = parse_bytes(sys_health(1000, sd_write_failures=3, sd_recoveries=3))
        msg = ' '.join(data['errors'])
        self.assertIn('SD WRITE FAILURES', msg)
        self.assertIn('sibling files', msg)

    def test_health_csv_columns(self):
        data = parse_bytes(sys_health(1000, hall_rejected=5))
        with tempfile.TemporaryDirectory() as d:
            written = vs.write_csvs_from_parsed(data, d, 'H')
            path = [p for p in written if p.endswith('_sysHealth.csv')][0]
            with open(path, newline='') as f:
                rows = f.read().splitlines()
        self.assertTrue(rows[0].startswith('timestamp_ms,loop_max_us,sd_write_max_us'))
        self.assertIn('5', rows[1].split(','))


class TestVariableLengthLayouts(unittest.TestCase):

    def test_current_block_expands_across_measured_span(self):
        """Per-sample timestamps interpolate over span_ms, which covers n-1 intervals."""
        samples = tuple(range(100, 110))          # 10 samples
        data = parse_bytes(current_block(1000, span_ms=90, samples=samples))
        self.assertEqual(structural_errors(data), [])
        fast = data['current_fast']
        self.assertEqual(len(fast), 10)
        self.assertEqual(tuple(r['counts'] for r in fast), samples)
        self.assertAlmostEqual(fast[0]['ts_ms'], 1000.0, places=6)
        self.assertAlmostEqual(fast[-1]['ts_ms'], 1090.0, places=6)   # 1000 + span_ms

    def test_current_block_single_sample_does_not_divide_by_zero(self):
        data = parse_bytes(current_block(50, span_ms=0, samples=(4095,)))
        self.assertEqual(structural_errors(data), [])
        self.assertEqual(len(data['current_fast']), 1)
        self.assertAlmostEqual(data['current_fast'][0]['ts_ms'], 50.0, places=6)

    def test_block_boundary_does_not_shift_following_records(self):
        """A variable-length record must leave the stream aligned for the next one."""
        blob = (current_block(10, 90, tuple(range(10)))
                + record(vs.TYPE_RPM, 20, struct.pack('<H', 4242))
                + hall_edge(30, (1_000_000, 1_030_000))
                + record(vs.TYPE_RPM, 40, struct.pack('<H', 99)))
        data = parse_bytes(blob)
        self.assertEqual(structural_errors(data), [])
        self.assertEqual([r['rpm'] for r in data['rpm']], [4242, 99])
        self.assertEqual(len(data['hall_edge']), 2)

    def test_hall_edge_period_and_rpm(self):
        """30 000 us between edges with one magnet is 2000 RPM."""
        data = parse_bytes(hall_edge(0, (1_000_000, 1_030_000, 1_060_000)))
        edges = data['hall_edge']
        self.assertIsNone(edges[0]['period_us'])          # no predecessor
        self.assertEqual(edges[1]['period_us'], 30_000)
        self.assertAlmostEqual(edges[1]['rpm'], 2000.0, places=6)

    def test_hall_edge_micros_wrap(self):
        """micros() wraps every ~71.6 min; the period must stay positive across it."""
        data = parse_bytes(hall_edge(0, (0xFFFF_F000, 0x0000_2530)))
        # 0xFFFFF000 -> 0x2530 is 0x3530 = 13616 us once the uint32 wrap is unwound.
        self.assertEqual(data['hall_edge'][1]['period_us'], 0x3530)


class TestDerivedConversions(unittest.TestCase):

    def test_current_conversion_uses_the_logged_cal(self):
        """Counts become mA via the log's own 0x0D record, whatever its position."""
        # Cal record written AFTER the data, to prove ordering does not matter.
        blob = (current_block(0, 9, tuple([8192] * 10))
                + current_cal(1, vref=1.97225, adc_max=16383.0,
                              div_ratio=1.0, sens=100.0))
        data = parse_bytes(blob)
        self.assertEqual(structural_errors(data), [])
        # Rebuild the expectation from the values as they came back: the cal record stores
        # float32, so comparing against float64 literals fails at ~1e-7 for no real reason.
        cal = data['current_cal'][0]
        expected = 8192 * (cal['vref'] * cal['div_ratio']
                           * cal['sens_mA_per_V'] / cal['adc_max'])
        self.assertAlmostEqual(data['current_fast'][0]['current_mA'], expected, places=9)
        self.assertAlmostEqual(data['current_fast'][0]['current_mA'], 98.62, places=2)

    def test_current_without_cal_leaves_mA_blank_and_warns(self):
        data = parse_bytes(current_block(0, 9, tuple([100] * 10)))
        self.assertEqual(structural_errors(data), [])
        self.assertIsNone(data['current_fast'][0]['current_mA'])
        self.assertTrue(any('No CURRENT_CAL' in e for e in data['errors']))

    def test_battery_conversion_and_full_charge_headroom(self):
        """3.65 V LiFePO4 through the installed ~2:1 divider must not clip the ADC."""
        r_top, r_bottom = 98700.0, 98900.0
        ratio = (r_top + r_bottom) / r_bottom
        vref, adc_max = 1.97710, 16383.0
        counts = int(round(3.65 / ratio / vref * adc_max))
        blob = (battery_cal(0, vref, adc_max, r_top, r_bottom, ratio)
                + record(vs.TYPE_BATTERY_VOLTAGE, 1, struct.pack('<H', counts)))
        data = parse_bytes(blob)
        self.assertEqual(structural_errors(data), [])
        self.assertLess(counts, adc_max, "a full cell must stay below ADC full scale")
        self.assertAlmostEqual(data['battery_voltage'][0]['voltage_V'], 3.65, places=2)

    def test_zero_adc_max_is_reported_not_crashed(self):
        blob = (current_block(0, 9, tuple([1] * 10))
                + current_cal(1, vref=2.0, adc_max=0.0, div_ratio=1.0, sens=100.0))
        data = parse_bytes(blob)
        self.assertTrue(any('adc_max=0' in e for e in data['errors']))
        self.assertIsNone(data['current_fast'][0]['current_mA'])


class TestMalformedInput(unittest.TestCase):
    """The parser reads field deployment logs, which can be truncated by a dead battery."""

    def test_truncated_final_record_stops_cleanly(self):
        good = record(vs.TYPE_RPM, 1, struct.pack('<H', 123))
        data = parse_bytes(good + imu_raw(2, (0, 0, 0), (0, 0, 0),
                                          (0, 0, 0), (0, 0, 0), 0)[:20])
        self.assertEqual(len(data['rpm']), 1, "records before the truncation survive")
        self.assertTrue(any('Truncated' in e for e in data['errors']))

    def test_truncated_header_is_not_an_error(self):
        """A log cut mid-header is normal for a power-loss capture, not a warning."""
        data = parse_bytes(record(vs.TYPE_RPM, 1, struct.pack('<H', 5)) + b'\x0c\x00')
        self.assertEqual(len(data['rpm']), 1)
        self.assertEqual(data['errors'], [])

    def test_unknown_type_stops_with_a_diagnostic(self):
        data = parse_bytes(record(vs.TYPE_RPM, 1, struct.pack('<H', 5))
                           + record(0x7F, 2, b'\x00' * 4))
        self.assertEqual(len(data['rpm']), 1)
        self.assertTrue(any('Unknown packet type 0x7F' in e for e in data['errors']))

    def test_empty_file(self):
        data = parse_bytes(b'')
        self.assertEqual(data['errors'], [])
        self.assertEqual(data['rpm'], [])

    def test_retired_0x0A_still_loads(self):
        """0x0A was retired in 2026-09-03 firmware; existing logs must still parse."""
        data = parse_bytes(record(vs.TYPE_CURRENT, 1, struct.pack('<H', 682)))
        self.assertEqual(structural_errors(data), [])
        self.assertEqual(data['current'][0]['counts'], 682)


class TestCsvExport(unittest.TestCase):

    def test_csv_written_for_present_types_only(self):
        data = parse_bytes(imu_raw(1, (1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12), 13)
                           + record(vs.TYPE_RPM, 2, struct.pack('<H', 500)))
        with tempfile.TemporaryDirectory() as d:
            written = vs.write_csvs_from_parsed(data, d, 'TESTLOG')
            names = sorted(os.path.basename(p) for p in written)
        self.assertEqual(names, ['TESTLOG_imuRaw.csv', 'TESTLOG_rpm.csv'])

    def test_csv_header_and_none_cells(self):
        """ts_ms is renamed timestamp_ms; a None cell is empty, never the text 'None'."""
        data = parse_bytes(current_block(0, 9, tuple([7] * 10)))   # no cal -> mA is None
        with tempfile.TemporaryDirectory() as d:
            written = vs.write_csvs_from_parsed(data, d, 'X')
            with open(written[0], newline='') as f:
                rows = f.read().splitlines()
        self.assertEqual(rows[0], 'timestamp_ms,counts,current_mA')
        self.assertTrue(rows[1].endswith(',7,'), rows[1])
        self.assertNotIn('None', '\n'.join(rows))

    def test_every_schema_key_exists_in_the_parser_output(self):
        """A _CSV_SCHEMAS key with no matching parser key would silently never export.

        The GUI's parse summary now iterates this same table (Issue 51), so a stale key
        here would also show as a permanently-zero row.
        """
        produced = set(parse_bytes(b'').keys()) - {'errors', 'notes'}
        self.assertEqual(set(vs._CSV_SCHEMAS) - produced, set())


if __name__ == '__main__':
    unittest.main(verbosity=2)
