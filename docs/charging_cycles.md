# Battery-side charging cycles

## Current calibration

From 2026-10-16 the reported 0.5 ohm sense resistor uses 200 mA/V with unchanged
amplifier gain. Current in mA = counts / 16383 * (2 / 1.014071) * 200.
One count is approximately 0.024079 mA; full scale is approximately 394.45 mA.
Firmware must be rebuilt and uploaded. Each new SD log archives the coefficient.
Do not apply another factor of two in the GUI or to correctly calibrated logs.

Logs recorded after the resistor swap but before uploading the new coefficient
retain 100 mA/V metadata. For those logs only, recompute from counts at 200 mA/V
or double exported current/charge and quadruple I-squared integrals. Earlier
1 ohm captures must retain their original conversion.

## Selecting a cycle

Recommended first pass: load an SD BIN and select an explicit start/end interval
around one approximately 20-second charging event in the currentFast export.
Align its timestamp_ms with the batteryVoltage export and RPM/IMU where available.
Use rotor motion or a sustained current rise to identify event onset, then allow
the current tail to finish rather than assuming every event lasts exactly 20 s.
Mechanical idle may still contain electrical charging, so inspect current too.

After manual verification of several cycles, automate onset/end detection using
separate start/stop thresholds based on the measured idle noise, minimum duration,
and a quiet-time requirement. Preserve event boundaries and quality flags.

Compute power_mW(t) = battery_V(t) * current_mA(t) and cumulative energy_mJ as
the time integral of power_mW. Use time-aware trapezoidal integration, bracketed
battery interpolation, and do not bridge long missing-data intervals. Report
coverage, clipping, charge, peak, duration and energy for each cycle. Plot relative
time from onset so cycles can be overlaid. If subtracting idle background, report
both gross charging energy and background-subtracted energy separately.

The current and voltage must describe the same PMC-to-battery boundary. This is
battery-side delivered energy, not raw TENG output or net stored chemical energy.
The 1 Hz battery stream cannot resolve fast voltage transients. Raw current block
timestamps are interpolated; individual within-block timing jitter is unavailable.

## Live display limits

The GUI plots approximately one-second interval means derived from cumulative
stats. These reveal a 20-second event envelope but not individual fast pulses.
The existing two-minute summary is not a cycle-energy accumulator. Its displayed
Avg P is latest voltage times window-average current, not integrated cycle energy.
Use SD raw data for cycle profiles; live raw-waveform streaming or interactive
cycle-selection controls are not implemented by this change.