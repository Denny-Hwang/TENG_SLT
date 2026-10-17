"""Generate a synthetic 20-second charging session, not a hardware capture."""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vertisea_session import export_cycles_csv, import_session


def record(kind, timestamp, payload):
    return struct.pack('<BI', kind, timestamp) + payload


def main():
    directory = Path(__file__).resolve().parents[1] / 'sessions' / 'synthetic_example'
    directory.mkdir(parents=True, exist_ok=True)
    payload = bytearray()
    payload.extend(record(0x18, 0, struct.pack('<HHhHH', 1, 79, -420, 104, 1000)))
    payload.extend(record(0x05, 0, struct.pack('<6B', 26, 10, 16, 12, 0, 0)))
    payload.extend(record(0x0D, 0, struct.pack('<4f', 2 / 1.014071, 16383, 1, 200)))
    payload.extend(record(0x13, 0, struct.pack('<5f', 2, 16383, 1000, 1000, 2)))
    for second in range(31):
        payload.extend(record(0x14, second * 1000, struct.pack('<H', 14745)))
    factor = (2 / 1.014071) * 200 / 16383
    for timestamp in range(0, 30001, 100):
        current = 20 if 5000 <= timestamp <= 25000 else 0
        counts = round(current / factor)
        payload.extend(record(0x0E, timestamp, struct.pack('<HHH', 0, 1, counts)))
        payload.extend(record(0x12, timestamp, struct.pack('<3h3i3h3iH', *([0] * 12), 10000)))
        for kind, pitch in ((0x01, 2.0), (0x02, 1.0)):
            payload.extend(record(kind, timestamp, struct.pack('<9fH', pitch, 0, 999.9,
                                                            0, 0, 0, 0, 0, 1, 10000)))
        payload.extend(record(0x16, timestamp, struct.pack('<f', 0.01)))
    source = directory / 'synthetic.BIN'
    source.write_bytes(payload)
    result = import_session([source], directory / 'session.h5', 5, 25)
    export_cycles_csv(result['output'], directory / 'cycles.csv')
    print('SYNTHETIC ONLY:', result['output'])
    print(result['cycles'])


if __name__ == '__main__':
    main()