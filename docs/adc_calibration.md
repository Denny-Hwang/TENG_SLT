# ADC Gain Calibration — A14 (current) and A15 (battery)

**Measured:** 2026-09-09 · **Board:** the project's SparkFun RedBoard Artemis Nano (Apollo3) ·
**Applies to:** the two analog channels read by `VertiSea.ino` — `A14` (harvested-current
sensor, Apollo3 pad 35 / ADC SE7) and `A15` (battery divider, pad 32 / ADC SE4).

This document is the record of the known-voltage calibration performed with the isolated
`tools/adc_timer_dma_experiment/adc_timer_dma_experiment.ino` sketch (version 4). It exists so the
result survives independently of the DMA experiment, which was paused on 2026-09-10 in favour
of the polled (`analogRead()`) production firmware on `master`. The DMA branch history lives in
`docs/CHANGELOG_tools__adc_timer_dma_experiment__adc_timer_dma_experiment.ino.md`.

---

## 1. Result (use these numbers)

Both channels read **high by a consistent gain (scale) factor**. No meaningful offset or
non-linearity was detected at the 3-point level.

| Channel | Gain-only fit (meas / DMM) | Effective ADC reference | Nominal | Correction |
|---|---|---|---|---|
| **A14** (current)  | **1.014071** | **1.97225 V** | 2.000 V | −1.39 % |
| **A15** (battery)  | **1.011584** | **1.97710 V** | 2.000 V | −1.15 % |

> ### ⚠ Scope limit — this calibration does not cover the battery divider
>
> Both channels were driven **directly from low-impedance bench supplies**, with the DMM on
> the pin (§2). So these numbers calibrate the **ADC's gain** and say nothing about whether a
> given source can *feed* the ADC. The battery channel in service sits behind a 98.9 k/98.8 k
> divider whose Thevenin impedance is **49.4 kΩ**, and on 2026-09-15 that path measured
> **17.6 % low** — pad metered at 1.65 V, ADC reporting 1.36 V — because the Apollo3 SAR
> cannot charge its sample capacitor through that impedance in one sample window. The gain
> figures below remain correct; they are simply not the whole conversion chain. See
> IDENTIFIED_ISSUES.md Issue 72. Fit 0.1 µF from the ADC pad to GND before trusting a
> divider-fed channel.

*Effective reference* = 2.000 V / gain. Substituting it for the nominal 2.0 V in
`counts × VREF / 16383` corrects the channel with **no other change** to the conversion chain,
which is how `VertiSea.ino` applies it (Section 5).

Practical impact of the uncorrected error:

- **Current (A14):** 1 count = 0.012208 mA nominal → **0.012039 mA calibrated**. Full scale
  200.0 mA → 197.2 mA. A true 150 mA read as ~152.1 mA uncorrected.
- **Battery (A15):** through the installed 1.998:1 divider, a true 3.60 V LiFePO4 cell read
  as ~3.64 V uncorrected (+42 mV) — significant for state-of-charge estimation on a chemistry
  whose usable plateau spans only ~3.2–3.4 V.

---

## 2. Setup

| Item | Value |
|---|---|
| Sketch | `tools/adc_timer_dma_experiment/adc_timer_dma_experiment.ino`, version 4, `TEST_CONFIG 0` |
| ADC configuration | 14-bit, internal 2.0 V reference, no hardware averaging — **identical to production `analogReadResolution(14)` semantics** |
| Acquisition | CTIMER-triggered 500 Hz two-slot scan (A14 slot 0, A15 slot 1) into 64-word ping-pong DMA buffers |
| Duration | 120 s per run → **60,000 samples per channel per run** |
| Foreground load | Injected 10 ms / 45 ms stalls ON (irrelevant to voltage; confirms timing held during the capture) |
| Reference | Bench DC sources on both pins simultaneously; voltage **measured at the pin with a DMM** and recorded in the capture filename |
| Statistics | Firmware-computed running mean / std / min / max in raw counts, and `*_mean_uv` = counts × 2,000,000 / 16383 |

The two channels were driven with *different* voltages in every run so that a wiring swap
would be unambiguous (Section 3.1).

Raw captures (committed on branch `experiment/dual-adc-dma`, `tools/adc_timer_dma_experiment/`):

- `knownV_500Hz_A14_93mV_A15_1719mV_120s.txt`
- `knownV_500Hz_A14_1028mV_A15_1447mV_120s.txt`
- `knownV_500Hz_A14_1864mV_A15_1217mV_120s.txt`

---

## 3. Measurements

### 3.1 Wiring check

Each channel's mean tracked *its own* DMM value in every run (e.g. run 1: 92.8 mV on A14 vs
DMM 93 mV; 1738 mV on A15 vs DMM 1719 mV). A swap would have shown the opposite pairing.
**A14/A15 are not swapped.**

### 3.2 Mean vs DMM (`FINAL` line of each capture)

| Run | Pin | DMM (mV) | Mean (counts) | Mean (mV, nominal 2.0 V) | Error | Std (mV) | Min–Max (counts) |
|---|---|---|---|---|---|---|---|
| 1 | A14 | 93   | 760   | 92.84   | −0.16 mV (−0.17 %) | 5.86 | 348 – 1274 |
| 2 | A14 | 1028 | 8535  | 1042.05 | +14.05 mV (+1.37 %) | 5.74 | 8110 – 9093 |
| 3 | A14 | 1864 | 15486 | 1890.53 | +26.53 mV (+1.42 %) | 6.23 | 15062 – 15999 |
| 3 | A15 | 1217 | 10091 | 1231.92 | +14.92 mV (+1.23 %) | 5.49 | 9721 – 10575 |
| 2 | A15 | 1447 | 11989 | 1463.69 | +16.69 mV (+1.15 %) | 5.37 | 11514 – 12424 |
| 1 | A15 | 1719 | 14240 | 1738.39 | +19.39 mV (+1.13 %) | 5.62 | 13848 – 14966 |

Noise (std) is 5.4–6.2 mV ≈ 45–51 counts on both channels, independent of level — consistent
with a DC input plus source/wiring noise. The **min–max spans are ~10–12 σ**; see Section 6.

### 3.3 Fits

Two fits were computed per channel from the three (DMM, measured) pairs, in millivolts:

| Channel | Two-parameter fit `meas = a + b·DMM` | Residuals (mV) | Gain-only fit `meas = g·DMM` | Residuals (mV) |
|---|---|---|---|---|
| A14 | b = 1.015073, a = −1.53 mV | +0.07, −0.04, −0.04 | **g = 1.014071** | −0.42, +0.30, −1.47 |
| A15 | b = 1.008937, a = +3.94 mV | −0.18, +0.10, +0.08 | **g = 1.011584** | −0.07, +0.82, −0.52 |

**The gain-only fit is the one adopted**, for three reasons:

1. Both intercepts (−1.5 mV, +3.9 mV ≈ 12 and 32 counts) are smaller than the per-sample noise
   std and are determined from only three points, so they are not robustly distinguishable
   from zero.
2. Gain-only residuals are ≤ 1.5 mV (A14) and ≤ 0.8 mV (A15) — already ~15–30× better than
   uncorrected, and well below the noise floor.
3. A pure gain folds into the existing `vref` field of the self-describing `TYPE_CURRENT_CAL`
   (0x0D) and `TYPE_BATTERY_CAL` (0x13) records, so the parser and the binary protocol need no
   change. An offset term would require a new packet field.

The magnitude (+1.0–1.4 %) is within the Apollo3 internal 2.0 V band-gap reference tolerance,
and the two channels differ by ~0.25 %, which is plausible channel-to-channel variation
(pad/mux path). This is a **property of this specific board**, not of the firmware.

---

## 4. Verification of the correction (offline)

Applying `corrected = measured / g` to the run means:

| Channel | DMM (mV) | Corrected (mV) | Residual |
|---|---|---|---|
| A14 | 93   | 91.55   | −1.45 mV |
| A14 | 1028 | 1027.59 | −0.41 mV |
| A14 | 1864 | 1864.30 | +0.30 mV |
| A15 | 1217 | 1217.81 | +0.81 mV |
| A15 | 1447 | 1446.93 | −0.07 mV |
| A15 | 1719 | 1718.48 | −0.52 mV |

The largest residual (A14 at 93 mV, −1.45 mV ≈ 12 counts ≈ 0.15 mA) hints at a small negative
offset on A14 that a gain-only model cannot remove. It is within one noise σ and is accepted.

---

## 5. Where the constants live

`VertiSea.ino`, HARDWARE CONSTANTS section:

```cpp
constexpr float VREF_NOMINAL = 2.0f;        // Apollo3 internal band-gap, datasheet value
constexpr float ADC_GAIN_A14 = 1.014071f;   // measured / DMM, gain-only fit (this doc)
constexpr float ADC_GAIN_A15 = 1.011584f;
constexpr float VREF_A14 = VREF_NOMINAL / ADC_GAIN_A14;   // 1.97225 V effective
constexpr float VREF_A15 = VREF_NOMINAL / ADC_GAIN_A15;   // 1.97710 V effective
```

- `COUNTS_TO_MA` and the boot-time `CurrentCal.vref` (0x0D) use `VREF_A14`.
- `COUNTS_TO_BATTERY_V`, the `BatteryVoltagePacket.battery_mV` telemetry, and the boot-time
  `BatteryCal.vref` (0x13) use `VREF_A15`.
- Because `vertisea_plot_v7.py` converts SD counts using the `vref` it reads from 0x0D/0x13,
  parsed CSVs from a calibrated firmware are corrected automatically, and logs recorded
  *before* the calibration still convert with their own (nominal 2.0 V) constants. **The `vref`
  field therefore means "effective reference voltage", not "nominal reference voltage".**

---

## 6. Limitations and open items

- **Three points per channel.** Sufficient to establish gain and to bound offset/non-linearity
  at the ~1 mV level, not to characterise curvature. A 5–7 point sweep would tighten this.
- **DMM accuracy not recorded.** The correction is only as good as the meter. Record the DMM
  model, range, and stated accuracy (typically ±0.1–0.5 % + digits for a handheld) the next time
  the procedure is run; if the DMM's own error is ≳0.3 %, the two channels' 0.25 % difference
  is not resolved.
- **Single board, room temperature.** The internal reference drifts with temperature; the buoy
  sees a much wider range than the bench. A cold-soak check would quantify this. If the Artemis
  Nano is replaced, **re-run the calibration** — the constants are per unit.
- **A15 was calibrated at the pin, without the battery divider.** The installed divider
  (EE, 2026-09-10) is 98.7 kΩ / 98.9 kΩ, both DMM-measured, ratio 1.99798; these are now in
  `BATTERY_R_TOP_OHM` / `BATTERY_R_BOTTOM_OHM`. The ADC gain and the divider ratio are
  independent multiplicative terms, so this calibration remains valid with the divider in
  place — but the *combination* has not yet been checked end-to-end against a DMM on the cell.
- **Source impedance.** Bench sources are low-impedance. The installed divider presents
  R_TOP ‖ R_BOTTOM ≈ 49.4 kΩ to the ADC sampling capacitor — high enough that incomplete
  settling after the mux switch is a real possibility even with one discarded conversion. A
  reading that is systematically low with the divider but correct at the bare pin points to
  this; the remedy is a 100 nF cap across R_BOTTOM (the EE's "C1"), not a software factor.
  The current sensor's output impedance has not been characterised either.
- **Outlier tails (unresolved).** Min–max spans of ~10–12 σ were seen on both channels in every
  run while the mean was unaffected. Production reports *peak* current, so tails matter. The
  planned square-wave / per-sample run (DMA sketch version 5, configured but **not executed**)
  was designed to attribute them to scan/DMA-buffer position vs. random source noise. That
  attribution does not affect the gain constants above, but it does bear on `peak_mA` in
  `TYPE_CURRENT_STATS` (0x0F) and on the U22 despiking proposal.
- **Acquisition path.** Calibration used direct HAL/DMA conversions; production uses
  `analogRead()`. Both program the same 14-bit / internal-2.0 V / no-averaging configuration on
  the same ADC, so the reference gain error is expected to transfer 1:1. A single spot check with
  the production firmware (`_batteryVoltage.csv` or `_currentFast.csv` against a DMM) will
  confirm this and is the confirmation gate for the `VertiSea.ino` changelog entry.

---

## 7. Reproducing the calibration

1. Flash `tools/adc_timer_dma_experiment/adc_timer_dma_experiment.ino` with `TEST_CONFIG 0`,
   `PRINT_EVERY_SAMPLE=0`, `TEST_DURATION_S=120`, `SERIAL_BAUD=115200`, stalls ON.
2. With the board held in reset, set both pins from stable DC sources. **Never exceed 2.0 V at
   either pin.** Measure each pin with the DMM and note the values.
3. Release reset, capture the full serial output through `FINAL`/`RESULT`, and save it as
   `knownV_500Hz_A14_<mV>mV_A15_<mV>mV_120s.txt` using the DMM-measured millivolts.
4. Repeat for at least three level pairs spanning the ranges of interest (use different voltages
   on the two pins so a swap is detectable).
5. For each capture, read `current_mean` / `battery_mean` (counts) from the `FINAL` line, convert
   with the nominal 2.0 V, fit `meas = g·DMM` through the origin per channel, and set
   `ADC_GAIN_A14` / `ADC_GAIN_A15` in `VertiSea.ino`. Also check that every integrity counter in
   `FINAL` is zero (`dma_errors`, `fifo_ovr2`, `lost_buffers`, `rearm_failures`,
   `unexpected_slots`, `order_errors`, `out_of_range`) so the statistics are trustworthy.
