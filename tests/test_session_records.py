import struct
import tempfile
import unittest
from pathlib import Path

from vertisea_protocol import parse_binary_file


class SessionRecordTests(unittest.TestCase):
    def test_new_records_and_simultaneous_imu(self):
        records = [(0x16, struct.pack('<f', 0.25)),
                   (0x17, struct.pack('<HHfffII', 20, 100, 40, 80, 20, 16000, 100)),
                   (0x18, struct.pack('<HHhHH', 1, 79, -420, 104, 1000)),
                   (0x12, struct.pack('<3h3i3h3iH', *([0] * 12), 10000)),
                   (0x01, struct.pack('<9fH', *([1.0] * 9), 10000)),
                   (0x02, struct.pack('<9fH', *([2.0] * 9), 10000))]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'new.BIN'
            source.write_bytes(b''.join(struct.pack('<BI', kind, 20000) + payload
                                       for kind, payload in records))
            parsed = parse_binary_file(str(source))
        self.assertEqual(parsed['displacement'][0]['displacement_m'], 0.25)
        self.assertEqual(parsed['current_stats'][0]['n_samples'], 16000)
        self.assertEqual(parsed['session_meta'][0]['utc_offset_minutes'], -420)
        for name in ('imu_raw', 'fixed_imu', 'stab_imu'):
            self.assertEqual(len(parsed[name]), 1)
        self.assertFalse(any('Truncated' in error for error in parsed['errors']))


if __name__ == '__main__':
    unittest.main()