"""Incremental telemetry capture; HDF5 and serial dependencies are lazy."""

import argparse
from collections import deque
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import struct
import time

from vertisea_protocol import (
    TYPE_BME, TYPE_GPS, TYPE_TELEM_IMU, TYPE_STATUS, TYPE_RPM,
    TYPE_CURRENT_STATS, TYPE_BATTERY_VOLTAGE, STATUS_FLAG_SD_ERROR,
)


RADIO_SCHEMAS = {
    TYPE_BME: ("bme", "<BHfff", ("pressure", "humidity", "temperature")),
    TYPE_GPS: ("gps", "<BHBff", ("satellites", "latitude", "longitude")),
    TYPE_TELEM_IMU: ("telem_imu", "<BHhhhhh", (
        "fix_pitch_cdeg", "fix_roll_cdeg", "vertDisp_mm", "stab_pitch_cdeg", "stab_roll_cdeg")),
    TYPE_STATUS: ("status", "<BHB", ("flags",)),
    TYPE_RPM: ("rpm", "<BHH", ("rpm",)),
    TYPE_CURRENT_STATS: ("current_stats", "<BHHHfffII", (
        "window_s", "peak_mA", "charge_mC", "i2t_mA2s", "integ_s", "n_samples", "n_dropped")),
    TYPE_BATTERY_VOLTAGE: ("battery_voltage", "<BHH", ("battery_mV",)),
}


class TimestampClock:
    """Unwrap uint16 10 ms ticks relative to the high-water mark, not arrival order."""

    def __init__(self):
        self.high_ticks = None

    def seconds(self, ts10):
        if not 0 <= ts10 < 65536:
            raise ValueError("ts10 must be uint16")
        if self.high_ticks is None:
            ticks = ts10
        else:
            delta = (ts10 - self.high_ticks + 32768) % 65536 - 32768
            ticks = self.high_ticks + delta
        self.high_ticks = ticks if self.high_ticks is None else max(self.high_ticks, ticks)
        return ticks * 0.01


def current_interval_stats(previous, current, battery_voltage=None, battery_time=None,
                           max_gap_s=2.5):
    """Difference cumulative accepted-time statistics without bridging resets/gaps.

    Inputs use timestamp (seconds), window_s, charge_mC, integ_s, n_samples and
    optional i2t_mA2s. First packet has no interval. Power is a latest-fresh-voltage
    estimate, not high-rate instantaneous power or a full-cycle energy integral.
    """
    timestamp = current["timestamp"]
    accepted = current["integ_s"]
    average = current["charge_mC"] / accepted if accepted > 0 else math.nan
    squared = current.get("i2t_mA2s", math.nan)
    rms = math.sqrt(squared / accepted) if accepted > 0 and squared >= 0 else math.nan
    fresh = (battery_voltage is not None and math.isfinite(battery_voltage)
             and battery_time is not None and 0 <= timestamp - battery_time <= max_gap_s)
    flags = []
    interval_current = interval_rms = math.nan
    elapsed = integration_delta = 0.0
    if previous is None:
        flags.append("first_statistics_packet")
    else:
        elapsed = timestamp - previous["timestamp"]
        integration_delta = accepted - previous["integ_s"]
        reset = (current["window_s"] < previous["window_s"]
                 or current["n_samples"] < previous["n_samples"]
                 or current["charge_mC"] < previous["charge_mC"]
                 or integration_delta < 0
                 or squared < previous.get("i2t_mA2s", math.nan))
        if reset:
            flags.append("statistics_reset")
        elif not 0 < elapsed <= max_gap_s:
            flags.append("timestamp_gap_or_out_of_order")
        elif not integration_delta > 0:
            flags.append("no_accepted_integration_time")
        else:
            interval_current = (current["charge_mC"] - previous["charge_mC"]) / integration_delta
            square_delta = squared - previous.get("i2t_mA2s", math.nan)
            if square_delta >= 0:
                interval_rms = math.sqrt(square_delta / integration_delta)
    if not fresh:
        flags.append("voltage_missing_or_stale")
    return {"timestamp": timestamp, "ts_ms": timestamp * 1000,
            "window_average_mA": average, "window_rms_mA": rms,
            "window_power_mW": average * battery_voltage if fresh else math.nan,
            "current_mA": interval_current, "rms_mA": interval_rms,
            "power_mW": interval_current * battery_voltage if fresh else math.nan,
            "voltage_V": battery_voltage if fresh else math.nan,
            "voltage_fresh": fresh, "interval_s": elapsed,
            "accepted_integration_delta_s": integration_delta,
            "current_interval_valid": math.isfinite(interval_current), "flags": flags}


class TelemetryParser:
    """Frameless known-schema byte scanner, retaining incomplete packet tails."""

    def __init__(self):
        self.buffer = bytearray()
        self.clock = TimestampClock()
        self.spans = deque()
        self.offset = 0
        self.skipped_bytes = 0

    def _consume(self, count):
        del self.buffer[:count]
        self.offset += count
        while count:
            span = self.spans[0]
            consumed = min(count, span[0])
            span[0] -= consumed
            count -= consumed
            if not span[0]:
                self.spans.popleft()

    def feed(self, chunk, host_receive_utc_ns=None, chunk_index=0):
        host_receive_utc_ns = time.time_ns() if host_receive_utc_ns is None else host_receive_utc_ns
        self.buffer.extend(chunk)
        if chunk:
            self.spans.append([len(chunk), host_receive_utc_ns, chunk_index])
        records = []
        while self.buffer:
            packet_type = self.buffer[0]
            schema = RADIO_SCHEMAS.get(packet_type)
            if schema is None:
                self.skipped_bytes += 1
                self._consume(1)
                continue
            name, layout, fields = schema
            size = struct.calcsize(layout)
            if len(self.buffer) < size:
                break
            values = struct.unpack_from(layout, self.buffer)
            raw_fields = dict(zip(fields, values[2:]))
            timestamp = self.clock.seconds(values[1])
            engineering = dict(raw_fields)
            if packet_type == TYPE_TELEM_IMU:
                engineering = {
                    "pitch": raw_fields["fix_pitch_cdeg"] / 100,
                    "roll": raw_fields["fix_roll_cdeg"] / 100,
                    "displacement_m": raw_fields["vertDisp_mm"] / 1000,
                    "stab_pitch": raw_fields["stab_pitch_cdeg"] / 100,
                    "stab_roll": raw_fields["stab_roll_cdeg"] / 100,
                }
            elif packet_type == TYPE_BATTERY_VOLTAGE:
                engineering["voltage_V"] = raw_fields["battery_mV"] / 1000
            elif packet_type == TYPE_STATUS:
                engineering["sd_ok"] = not bool(raw_fields["flags"] & STATUS_FLAG_SD_ERROR)
            remaining = size
            completion = self.spans[0]
            for span in self.spans:
                completion = span
                remaining -= span[0]
                if remaining <= 0:
                    break
            records.append({"kind": name, "packet_type": packet_type,
                            "source": "live_telemetry", "source_index": 0,
                            "source_row_index": self.offset, "byte_offset": self.offset,
                            "chunk_index": self.spans[0][2], "completion_chunk_index": completion[2],
                            "host_receive_utc_ns": completion[1],
                            "first_byte_receive_utc_ns": self.spans[0][1],
                            "ts10": values[1], "timestamp": timestamp, "ts_ms": timestamp * 1000,
                            "raw_fields": raw_fields, "engineering": engineering,
                            **engineering})
            self._consume(size)
        return records


class LiveRecorder:
    """Single-owner, append-only gzip HDF5 writer, shared by CLI and Tk polling."""

    def __init__(self, output, port=None):
        try:
            import h5py
        except ImportError as error:
            raise RuntimeError("Live recording requires h5py; install it in the selected environment") from error
        destination = Path(output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.path = destination
        self.parser = TelemetryParser()
        self.previous_stats = None
        self.battery_voltage = self.battery_time = None
        self.chunk_index = 0
        self.closed = False
        self.archive = h5py.File(destination, "x")
        self.text_type = h5py.string_dtype("utf-8")
        try:
            for name in ("raw", "onboard", "derived", "meta", "health", "events"):
                self.archive.create_group(name)
            self.archive.attrs["schema_version"] = "1.0"
            metadata = self.archive["meta"].attrs
            metadata["capture_mode"] = "live_telemetry"
            metadata["created_utc"] = datetime.now(timezone.utc).isoformat()
            metadata["port"] = port or "unspecified"
            metadata["time_provenance"] = "host UTC reception; device uint16 ticks unwrapped at 10 ms"
            metadata["timestamp_limitation"] = "No device UTC anchor/reboot detection; gaps >= half wrap (327.68 s) are ambiguous"
            metadata["limitation"] = "Telemetry cannot supply high-rate raw IMU/current; use SD BIN for quantitative cycle analysis"
            metadata["battery_metadata"] = "Telemetry firmware-converted mV; ADC calibration and chemistry are not transmitted"
            metadata["source"] = "live_telemetry"
            metadata["source_index"] = 0
            metadata["units_json"] = json.dumps({"ts10": "10 ms uint16 ticks", "ts_ms": "ms since boot (unwrapped)",
                "host_receive_utc_ns": "Unix UTC nanoseconds", "current_mA": "mA", "rms_mA": "mA",
                "power_mW": "mW", "voltage_V": "V", "pressure": "Pa", "temperature": "deg C",
                "humidity": "%", "pitch": "degrees", "roll": "degrees", "displacement_m": "m"})
            self.archive["health"].attrs["status_limitation"] = "SD flags are last reported device status, not proof of SD completeness; no status means unknown"
            self.archive["health"].attrs["transport_limitation"] = "Frameless telemetry has no checksum/sequence counter; packet loss and false resync cannot be fully detected"
            self.archive["derived"].attrs["algorithm_version"] = "live-interval-1"
            self.archive["derived"].attrs["parameters_json"] = json.dumps({"max_gap_s": 2.5})
            self.archive["raw"].create_dataset("bytes", (0,), maxshape=(None,), dtype="u1",
                                                chunks=True, compression="gzip")
            self._append("events/records", {"kind": "recording_start", "source": "live_telemetry",
                                            "host_receive_utc_ns": time.time_ns()})
            self.archive.flush()
        except Exception:
            self.archive.close()
            raise

    def _append(self, path, row):
        group = self.archive.require_group(path)
        if "records_json" not in group:
            group.create_dataset("records_json", (0,), maxshape=(None,), dtype=self.text_type,
                                 chunks=True, compression="gzip")
        dataset = group["records_json"]
        index = len(dataset)
        dataset.resize((index + 1,))
        dataset[index] = json.dumps(row, ensure_ascii=True, allow_nan=True, separators=(",", ":"))
        group.attrs["row_count"] = index + 1

    def feed(self, chunk, host_receive_utc_ns=None):
        if self.closed:
            raise RuntimeError("Recorder is closed")
        payload = bytes(chunk)
        received = time.time_ns() if host_receive_utc_ns is None else host_receive_utc_ns
        dataset = self.archive["raw/bytes"]
        offset = len(dataset)
        dataset.resize((offset + len(payload),))
        if payload:
            dataset[offset:] = list(payload)
        self._append("raw/chunks", {"chunk_index": self.chunk_index, "byte_offset": offset,
                                    "byte_count": len(payload), "host_receive_utc_ns": received,
                                    "source": "live_telemetry"})
        skipped = self.parser.skipped_bytes
        records = self.parser.feed(payload, received, self.chunk_index)
        for record in records:
            category = "health" if record["kind"] == "status" else "onboard"
            self._append(f"{category}/{record['kind']}", record)
            if record["kind"] == "battery_voltage":
                if self.battery_time is None or record["timestamp"] >= self.battery_time:
                    self.battery_voltage = record["voltage_V"]
                    self.battery_time = record["timestamp"]
            elif record["kind"] == "current_stats":
                derived = current_interval_stats(self.previous_stats, record,
                                                 self.battery_voltage, self.battery_time)
                self._append("derived/charging", dict(derived, source="live_interval_statistics",
                             source_index=0, byte_offset=record["byte_offset"],
                             host_receive_utc_ns=record["host_receive_utc_ns"]))
                if self.previous_stats is None or record["timestamp"] > self.previous_stats["timestamp"]:
                    self.previous_stats = record
        if self.parser.skipped_bytes > skipped:
            self._append("events/records", {"kind": "unknown_bytes_skipped",
                         "byte_count": self.parser.skipped_bytes - skipped,
                         "host_receive_utc_ns": received, "chunk_index": self.chunk_index})
        self.chunk_index += 1
        self.archive.flush()
        return records

    def event(self, kind, **details):
        if not self.closed:
            self._append("events/records", dict(details, kind=kind, host_receive_utc_ns=time.time_ns()))
            self.archive.flush()

    def close(self, reason="closed"):
        if self.closed:
            return
        try:
            self.event("recording_stop", reason=reason, trailing_unparsed_bytes=len(self.parser.buffer),
                       skipped_bytes=self.parser.skipped_bytes)
        finally:
            self.closed = True
            self.archive.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close("error" if exc_type else "closed")


def open_serial(port):
    import serial
    connection = serial.Serial(port=None, baudrate=115200, timeout=0.1)
    try:
        connection.rts = False
        connection.dtr = False
        connection.port = port
        connection.open()
    except Exception:
        connection.close()
        raise
    return connection


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration", type=float, help="Seconds to record; default until Ctrl-C")
    arguments = parser.parse_args(argv)
    if arguments.duration is not None and (not math.isfinite(arguments.duration) or arguments.duration <= 0):
        parser.error("duration must be finite and positive")
    with LiveRecorder(arguments.output, arguments.port) as recorder:
        connection = open_serial(arguments.port)
        try:
            started = time.monotonic()
            while arguments.duration is None or time.monotonic() - started < arguments.duration:
                payload = connection.read(max(1, connection.in_waiting))
                if payload:
                    recorder.feed(payload)
        except KeyboardInterrupt:
            recorder.event("interrupted")
        except Exception as error:
            recorder.event("link_lost", message=str(error))
            raise
        finally:
            connection.close()
    print(f"Recorded: {recorder.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())