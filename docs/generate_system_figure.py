"""
VertiSea System Architecture Figure
Generates a publication-quality diagram for technical milestone reports.

Usage:
    python docs/generate_system_figure.py

Output:
    docs/vertisea_system_diagram.png  (300 dpi, suitable for reports)
    docs/vertisea_system_diagram.pdf  (vector, suitable for LaTeX)
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

# ── Colour palette ────────────────────────────────────────────────────────────
C_BUOY      = "#1a3a5c"
C_BUOY_LITE = "#d6e4f0"
C_PEND      = "#7b2d00"
C_PEND_LITE = "#fde8d8"
C_STAB_LITE = "#d8f0e4"
C_STAB      = "#1a5c35"
C_SENSOR    = "#2c3e50"
C_SENSOR_BG = "#ecf0f1"
C_RADIO     = "#6c3483"
C_RADIO_BG  = "#f5eef8"
C_LAPTOP    = "#1a3a5c"
C_LAPTOP_BG = "#eaf4fb"
C_MADG      = "#b7950b"
C_MADG_BG   = "#fef9e7"
C_SD        = "#117a65"
C_SD_BG     = "#d1f2eb"
C_TEXT      = "#1c1c1c"
C_SUBTEXT   = "#555555"
C_BORDER    = "#95a5a6"

FONT = "DejaVu Sans"

# ── Canvas ────────────────────────────────────────────────────────────────────
W, H = 21.0, 12.8
fig = plt.figure(figsize=(W, H), facecolor="white")
ax  = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def rbox(x, y, w, h, fc, ec, lw=1.3, r=0.20, z=2):
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle=f"round,pad=0,rounding_size={r}",
                       facecolor=fc, edgecolor=ec, linewidth=lw, zorder=z)
    ax.add_patch(p)

def txt(x, y, s, sz=10, c=C_TEXT, w="normal", ha="center", va="center",
        z=5, style="normal"):
    ax.text(x, y, s, fontsize=sz, color=c, fontweight=w,
            ha=ha, va=va, zorder=z, fontstyle=style, fontfamily=FONT)

def hdr(x, y, w, h, fc, ec, title, tsz=10.5, tc="white", r=0.20, lw=1.3, z=3):
    rbox(x, y, w, h, fc=fc, ec=ec, lw=lw, r=r, z=z-1)
    rbox(x, y+h-0.56, w, 0.56, fc=ec, ec=ec, lw=0, r=r, z=z)
    txt(x+w/2, y+h-0.28, title, sz=tsz, c=tc, w="bold", z=z+1)

def arr(x0, y0, x1, y1, c=C_TEXT, lw=1.8, cs="arc3,rad=0.0", z=4):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="-|>", color=c, lw=lw,
                                connectionstyle=cs), zorder=z)

def darr(x0, y0, x1, y1, c=C_TEXT, lw=1.6, z=4):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="-|>", color=c, lw=lw,
                                linestyle="dashed",
                                connectionstyle="arc3,rad=0.0"), zorder=z)

# ─────────────────────────────────────────────────────────────────────────────
# 0.  Page title
# ─────────────────────────────────────────────────────────────────────────────
txt(W/2, 11.65,
    "Wave-Energy Buoy Data-Acquisition & Telemetry System",
    sz=16, c=C_BUOY, w="bold", z=10)

# ─────────────────────────────────────────────────────────────────────────────
# 1.  BUOY HOUSING
# ─────────────────────────────────────────────────────────────────────────────
BX, BY, BW, BH = 0.45, 0.35, 12.20, 11.00
hdr(BX, BY, BW, BH, fc=C_BUOY_LITE, ec=C_BUOY,
    title="BUOY  ·  SparkFun RedBoard Artemis Nano",
    tsz=11.5, tc="white", r=0.35, lw=2.2, z=2)

# ─────────────────────────────────────────────────────────────────────────────
# 2.  Pendulum IMU
# ─────────────────────────────────────────────────────────────────────────────
PX, PY, PW, PH = 0.80, 7.55, 3.60, 3.00
hdr(PX, PY, PW, PH, fc=C_PEND_LITE, ec=C_PEND, title="2-DOF Pendulum IMU",
    tsz=10.5, r=0.22, lw=1.8, z=3)

txt(PX+PW/2, PY+2.22, "ISM330DHCX", sz=9.5, w="bold")
txt(PX+PW/2, PY+1.78, "I²C  addr 0x6A", sz=9, c=C_SUBTEXT)
txt(PX+PW/2, PY+1.30, "Accel + Gyro  @  104 Hz", sz=9)
txt(PX+PW/2, PY+0.82, "Madgwick 6-DOF  →  pitch, roll", sz=9,
    c=C_PEND, w="bold")
txt(PX+PW/2, PY+0.36, "Attached to pendulum", sz=8.5,
    c=C_SUBTEXT, style="italic")

# ─────────────────────────────────────────────────────────────────────────────
# 3.  Buoy IMU
# ─────────────────────────────────────────────────────────────────────────────
SX, SY, SW, SH = 0.80, 4.20, 3.60, 3.00
hdr(SX, SY, SW, SH, fc=C_STAB_LITE, ec=C_STAB, title="Buoy IMU",
    tsz=10.5, r=0.22, lw=1.8, z=3)

txt(SX+SW/2, SY+2.22, "ISM330DHCX  +  MMC5983MA", sz=9.5, w="bold")
txt(SX+SW/2, SY+1.78, "I²C  addr 0x6B  (IMU)  /  auto  (Mag)", sz=8.5,
    c=C_SUBTEXT)
txt(SX+SW/2, SY+1.30, "Accel + Gyro + Mag  @  104 Hz", sz=9)
txt(SX+SW/2, SY+0.82, "Madgwick 9-DOF  →  pitch, roll, heading", sz=9,
    c=C_STAB, w="bold")
txt(SX+SW/2, SY+0.36, "Attached to buoy housing", sz=8.5,
    c=C_SUBTEXT, style="italic")

# ─────────────────────────────────────────────────────────────────────────────
# 4.  Environmental & Navigation
# ─────────────────────────────────────────────────────────────────────────────
EX, EY, EW, EH = 0.80, 0.68, 3.60, 3.18
hdr(EX, EY, EW, EH, fc=C_SENSOR_BG, ec=C_SENSOR,
    title="Environmental & Navigation", tsz=10, r=0.22, lw=1.4, z=3)

sensors = [
    ("BME280",       "Pressure / Humidity / Temp  @  1 Hz"),
    ("u-blox GNSS",  "Lat, Lon, Alt, Sats  @  1 Hz"),
    ("RV8803 RTC",   "Wall-clock timestamp  (I²C)"),
    ("Supercap ADC", "Voltage divider  →  pin A14  @  5 Hz"),
]
for i, (name, desc) in enumerate(sensors):
    yy = EY + EH - 0.92 - i * 0.60
    txt(EX+0.22, yy,      f"▸ {name}", sz=9, w="bold", ha="left", c=C_SENSOR)
    txt(EX+0.22, yy-0.27, desc,        sz=8.2, ha="left", c=C_SUBTEXT)

# ─────────────────────────────────────────────────────────────────────────────
# 5.  Signal Processing
# ─────────────────────────────────────────────────────────────────────────────
MX, MY, MW, MH = 4.80, 5.60, 3.55, 4.70
hdr(MX, MY, MW, MH, fc=C_MADG_BG, ec=C_MADG,
    title="Signal Processing", tsz=10.5, tc=C_TEXT, r=0.22, lw=1.8, z=3)

txt(MX+MW/2, MY+4.00, "1-pole IIR Low-Pass Filter", sz=9.5, w="bold")
txt(MX+MW/2, MY+3.56, "Accel: 20 Hz  |  Gyro: 40 Hz  |  Mag: 2 Hz",
    sz=9, c=C_SUBTEXT)

# Thin divider
ax.axhline(MY+3.22, xmin=(MX+0.15)/W, xmax=(MX+MW-0.15)/W,
           color=C_MADG, lw=0.7, zorder=5, alpha=0.5)

txt(MX+MW/2, MY+2.90, "Madgwick AHRS  (6-DOF / 9-DOF*)", sz=9.5, w="bold")
txt(MX+MW/2, MY+2.46, "pitch  ·  roll  ·  heading", sz=9)
txt(MX+MW/2, MY+2.06, "* 9-DOF on Buoy IMU only  (mag fusion)", sz=8.5,
    c=C_SUBTEXT, style="italic")

ax.axhline(MY+1.72, xmin=(MX+0.15)/W, xmax=(MX+MW-0.15)/W,
           color=C_MADG, lw=0.7, zorder=5, alpha=0.5)

txt(MX+MW/2, MY+1.40, "Differential Rotation", sz=9.5, w="bold")
txt(MX+MW/2, MY+0.96, "Buoy orientation  −  Pendulum orientation", sz=9)
txt(MX+MW/2, MY+0.54, "→  harvested motion estimate", sz=9, c=C_SUBTEXT)
txt(MX+MW/2, MY+0.18, "pitch Δ  ·  roll Δ", sz=8.5, c=C_SUBTEXT)

# ─────────────────────────────────────────────────────────────────────────────
# 6.  Binary Packet Formatter
# ─────────────────────────────────────────────────────────────────────────────
PKX, PKY, PKW, PKH = 4.80, 0.68, 3.55, 4.58
hdr(PKX, PKY, PKW, PKH, fc=C_SENSOR_BG, ec=C_SENSOR,
    title="Binary Packet Formatter", tsz=10, r=0.22, lw=1.4, z=3)

packets = [
    ("TYPE_FIXED_IMU  /  TYPE_STAB_IMU", "104 Hz  →  SD card"),
    ("TYPE_MAG",                          "104 Hz  →  SD card"),
    ("TYPE_BME  /  TYPE_GPS",             "1 Hz    →  SD card"),
    ("TYPE_SUPERCAP",                     "5 Hz    →  SD card"),
    ("TYPE_TELEM_IMU",                    "5 Hz    →  Radio"),
    ("TYPE_TELEM_GPS  /  TYPE_TELEM_BME", "0.2 / 0.067 Hz  →  Radio"),
]
for i, (pkt, rate) in enumerate(packets):
    yy = PKY + PKH - 0.88 - i * 0.56
    txt(PKX+0.20, yy,      pkt,  sz=8.5, w="bold", ha="left", c=C_SENSOR)
    txt(PKX+0.20, yy-0.25, rate, sz=8.0, ha="left", c=C_SUBTEXT)

# ─────────────────────────────────────────────────────────────────────────────
# 7.  microSD Card
# ─────────────────────────────────────────────────────────────────────────────
SDX, SDY, SDW, SDH = 8.80, 3.30, 3.10, 2.30
hdr(SDX, SDY, SDW, SDH, fc=C_SD_BG, ec=C_SD,
    title="microSD Card", tsz=10.5, tc="white", r=0.22, lw=1.8, z=3)

txt(SDX+SDW/2, SDY+1.46, "SPI  (CS = pin 4)", sz=9, w="bold")
txt(SDX+SDW/2, SDY+0.96, "MMDDHHMM.BIN", sz=10, w="bold", c=C_SD)
txt(SDX+SDW/2, SDY+0.46, "FAT32  ·  up to 104 Hz", sz=9, c=C_SUBTEXT)

# ─────────────────────────────────────────────────────────────────────────────
# 8.  RFD900x  (Buoy side)
# ─────────────────────────────────────────────────────────────────────────────
RBX, RBY, RBW, RBH = 8.80, 6.20, 3.10, 2.70
hdr(RBX, RBY, RBW, RBH, fc=C_RADIO_BG, ec=C_RADIO,
    title="RFD900x  (Buoy)", tsz=10.5, r=0.22, lw=1.8, z=3)

txt(RBX+RBW/2, RBY+1.86, "Serial1  @  115200 baud", sz=9, w="bold")
txt(RBX+RBW/2, RBY+1.38, "900 MHz  FHSS", sz=9)
txt(RBX+RBW/2, RBY+0.90, "Telemetry subset only", sz=8.5, c=C_SUBTEXT)
txt(RBX+RBW/2, RBY+0.42, "pitch · roll · GPS · env", sz=8.5, c=C_SUBTEXT)

# ─────────────────────────────────────────────────────────────────────────────
# 9.  Wireless link
# ─────────────────────────────────────────────────────────────────────────────
# RFD900x (Base) placed higher to give Python GUI more vertical room
RGX = 14.70
RGW = 3.10
RGH = 2.70
RGY = 8.80   # raised above buoy modem level

WL_X1 = RBX + RBW + 0.10
WL_X2 = RGX - 0.10
WL_Y1 = RBY + RBH / 2   # buoy modem midpoint
WL_Y2 = RGY + RGH / 2   # base modem midpoint

ax.annotate("", xy=(WL_X2, WL_Y2), xytext=(WL_X1, WL_Y1),
            arrowprops=dict(arrowstyle="<->", color=C_RADIO, lw=2.2,
                            linestyle=(0, (4, 3)),
                            connectionstyle="arc3,rad=0.0"),
            zorder=5)
mid_x = (WL_X1 + WL_X2) / 2
mid_y = (WL_Y1 + WL_Y2) / 2
txt(mid_x + 0.10, mid_y + 1.00, "900 MHz  FHSS", sz=9, c=C_RADIO, w="bold")
txt(mid_x + 0.10, mid_y - 0.80, "wireless link", sz=8.5,
    c=C_RADIO, style="italic")

# Antenna arcs (drawn at each modem's midpoint height)
for sign, cx, cy in [(-1, WL_X1-0.06, WL_Y1), (1, WL_X2+0.06, WL_Y2)]:
    for r, a in [(0.22, 60), (0.36, 70), (0.50, 75)]:
        theta = np.linspace(np.radians(90-a), np.radians(90+a), 40)
        ax.plot(cx + sign*r*np.cos(theta), cy + r*np.sin(theta),
                color=C_RADIO, lw=1.4, zorder=5)

# ─────────────────────────────────────────────────────────────────────────────
# 10.  RFD900x  (Base)
# ─────────────────────────────────────────────────────────────────────────────
hdr(RGX, RGY, RGW, RGH, fc=C_RADIO_BG, ec=C_RADIO,
    title="RFD900x  (Base)", tsz=10.5, r=0.22, lw=1.8, z=3)

txt(RGX+RGW/2, RGY+1.86, "USB  →  Laptop", sz=9, w="bold")
txt(RGX+RGW/2, RGY+1.38, "900 MHz  FHSS", sz=9)
txt(RGX+RGW/2, RGY+0.90, "Transparent serial bridge", sz=8.5, c=C_SUBTEXT)

# ─────────────────────────────────────────────────────────────────────────────
# 11.  Python GUI
# ─────────────────────────────────────────────────────────────────────────────
LPX, LPY, LPW, LPH = 14.70, 0.40, 6.00, 6.20
hdr(LPX, LPY, LPW, LPH, fc=C_LAPTOP_BG, ec=C_LAPTOP,
    title="Python GUI", tsz=11.5, r=0.28, lw=2.0, z=3)

# Divider 1  (below header, above live telemetry section label)
div_y = LPY + 5.34
ax.axhline(div_y, xmin=(LPX+0.20)/W, xmax=(LPX+LPW-0.20)/W,
           color=C_BORDER, lw=0.9, zorder=5, linestyle="--")

# Mode A: Live telemetry
txt(LPX+0.28, div_y - 0.28, "▸ Live Telemetry  (RFD900x)", sz=10, w="bold",
    ha="left", c=C_RADIO)
live_items = [
    ("GPS Panel",  "Sats · Lat · Lon  @  0.2 Hz"),
    ("BME Panel",  "Pressure · Humidity · Temp  @  0.067 Hz"),
    ("IMU Plot",   "Pendulum & Buoy pitch / roll  @  5 Hz"),
    ("Diff Plot",  "Differential rotation  @  5 Hz"),
]
for i, (panel, desc) in enumerate(live_items):
    yy = div_y - 0.72 - i*0.58
    txt(LPX+0.50, yy,      f"– {panel}", sz=9.5, w="bold", ha="left", c=C_LAPTOP)
    txt(LPX+0.50, yy-0.26, desc,         sz=8.5, ha="left", c=C_SUBTEXT)

# Divider 2  (above SD card section)
div_y2 = LPY + 2.20
ax.axhline(div_y2, xmin=(LPX+0.20)/W, xmax=(LPX+LPW-0.20)/W,
           color=C_BORDER, lw=0.9, zorder=5, linestyle="--")

# Mode B: Binary → CSV conversion
txt(LPX+0.28, div_y2 - 0.28, "▸ SD Card  —  Binary → CSV Conversion", sz=10,
    w="bold", ha="left", c=C_SD)
txt(LPX+0.50, div_y2 - 0.68,
    "Load MMDDHHMM.BIN  →  parse all packet types  →  export CSV",
    sz=9, ha="left", c=C_SUBTEXT)
txt(LPX+0.50, div_y2 - 1.10,
    "imuFixed · imuStab · bme280 · gps · mag · supcap · rtcEvt",
    sz=8.5, ha="left", c=C_SUBTEXT)

# ─────────────────────────────────────────────────────────────────────────────
# 12.  Arrows
# ─────────────────────────────────────────────────────────────────────────────

# Pendulum IMU → Signal Processing
arr(PX+PW, PY+PH*0.55, MX, MY+MH*0.82, c=C_PEND, lw=2.0)

# Buoy IMU → Signal Processing
arr(SX+SW, SY+SH*0.55, MX, MY+MH*0.50, c=C_STAB, lw=2.0)

# Environmental → Packet Formatter
arr(EX+EW, EY+EH*0.50, PKX, PKY+PKH*0.50, c=C_SENSOR, lw=1.8)

# Signal Processing → Packet Formatter
arr(MX+MW/2, MY, PKX+PKW/2, PKY+PKH, c=C_MADG, lw=2.0)

# Packet Formatter → SD Card
arr(PKX+PKW, PKY+PKH*0.34, SDX, SDY+SDH*0.50, c=C_SD, lw=2.0)

# Packet Formatter → RFD900x buoy
arr(PKX+PKW, PKY+PKH*0.76, RBX, RBY+RBH*0.45, c=C_RADIO, lw=2.0)

# RFD900x base → Python GUI (live telemetry path)
arr(RGX+RGW/2, RGY, LPX+LPW*0.72, LPY+LPH, c=C_RADIO, lw=2.0,
    cs="arc3,rad=0.0")

# SD Card → Python GUI (binary→CSV path, dashed — centre-right to centre-left)
darr(SDX+SDW, SDY+SDH*0.50,
     LPX,     LPY+LPH*0.25,
     c=C_SD, lw=1.8)

# ─────────────────────────────────────────────────────────────────────────────
# 13.  Save
# ─────────────────────────────────────────────────────────────────────────────
out_png = "docs/vertisea_system_diagram.png"
out_pdf = "docs/vertisea_system_diagram.pdf"

fig.savefig(out_png, dpi=300, bbox_inches="tight", facecolor="white")
fig.savefig(out_pdf, bbox_inches="tight", facecolor="white")
print(f"Saved  {out_png}  (300 dpi PNG)")
print(f"Saved  {out_pdf}  (vector PDF)")
plt.close(fig)
