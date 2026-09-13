#!/usr/bin/env python3
"""Live dashboard for the point-kinetics reactor simulator.

The dashboard reads the 23-field telemetry CSV stream from stdin or UART. It
shows trend charts, the reactor core, telemetry, and controls. It sends the
same one-letter commands accepted by the PC solver and ARM application through
stderr or the serial port.
"""

import argparse
import csv
import math
import os
import queue
import random
import sys
import threading
import time
from bisect import bisect_left
from datetime import datetime

import numpy as np
import matplotlib

if "--smoke" in sys.argv:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import colors as mcolors
from matplotlib.animation import FuncAnimation
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.widgets import Button, RadioButtons, Slider, TextBox


COMMAND_PREFIX = "PLOTTER_CMD\t"
DEFAULT_WINDOW_SECONDS = 6 * 3600.0
INITIAL_X_SECONDS = 30.0

# Matches config PK_DECAY_FRACTION_* (sum 0.066): thermal = 0.934*n + decay.
PROMPT_FRACTION = 0.934

NAN = float("nan")
FIELD_NAMES = (
    "sim_time_s", "n", "Tf", "rho", "rho_dollars", "Tc", "I_norm", "Xe_norm",
    "rho_xe", "achieved_factor", "rod_position", "rod_target", "engine_status",
    "target_h_s", "step_real_time_s", "decay_heat", "plant_mode",
    "rho_rod_dollars", "rho_fuel_dollars", "rho_coolant_dollars",
    "rho_xenon_dollars", "critical_rod_position", "scram_active",
)
FIELD_DEFAULTS = (
    NAN, NAN, NAN, NAN, NAN, NAN, NAN, NAN,
    NAN, NAN, NAN, NAN, 1.0,
    NAN, NAN, 0.0, 0.0,
    NAN, NAN, NAN,
    NAN, 0.75, 0.0,
)

PLANT_NAMES = {
    0: "PWR-SMR Passive Safe",
    1: "RBMK-like Demonstrator",
    2: "TMI-inspired Cooling Loss",
}

WINDOW_PRESETS = (
    ("30 s", 30.0),
    ("5 min", 300.0),
    ("1 h", 3600.0),
    ("all", None),
)

# Merge rapid ±1% rod clicks into one marker after this quiet gap (sim seconds).
ROD_COALESCE_S = 1.5
ROD_EVENT_MIN_DELTA = 0.008

# Session captures land in this folder next to the working directory.
CAPTURE_DIRNAME = "captures"

# Simple threshold alarms evaluated on every newest telemetry row.
ALARM_DEFS = (
    ("rho_dollars", lambda v: v >= 0.90, "rho ≥ 0.9$"),
    ("Tf", lambda v: v >= 800.0, "Tf > 800 °C"),
)

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

BG = "#0d1117"
PANEL = "#151b23"
PANEL_EDGE = "#2b3543"
TEXT = "#e6edf3"
MUTED = "#8b98a8"
GRID = "#222b37"
ACCENT = "#4ea1ff"

C_POWER = "#ff6b4a"
C_THERMAL = "#ffb26b"
C_FUEL = "#4cc9f0"
C_COOL = "#57d9a3"
C_RHO = "#a3e635"
C_IODINE = "#fbbf24"
C_XENON = "#c084fc"
C_TARGET_H = "#e879f9"
C_STEP = "#22d3ee"
C_SCRAM = "#da3633"
C_SCRAM_HOVER = "#f0524f"
C_SCRAM_DIM = "#5a2528"
C_CLEAR = "#1f6f4a"
C_CLEAR_HOVER = "#2ea06b"
C_CLEAR_ARMED = "#2ea06b"
C_CLEAR_ARMED_HOVER = "#3ecf85"
C_CLEAR_DIM = "#1a2e24"
C_BTN = "#21262d"
C_BTN_HOVER = "#30363d"
C_BTN_ACTIVE = "#2d4a6f"
C_EVENT = {
    "SCRAM": "#da3633",
    "clear": "#2ea06b",
    "rod": "#4ea1ff",
    "plant": "#fbbf24",
    "trip": "#ff7b72",
}

CHART_DEFS = (
    {"key": "power", "ylabel": "Power", "series": (
        ("n", "neutron", C_POWER, "-", 1.9),
        ("thermal", "thermal", C_THERMAL, "--", 1.4),
    )},
    {"key": "temp", "ylabel": "Temperature (°C)", "series": (
        ("Tf", "fuel", C_FUEL, "-", 1.7),
        ("Tc", "coolant", C_COOL, "-", 1.5),
    )},
    {"key": "rho", "ylabel": "Reactivity ($)", "hline": (1.0, "prompt critical"), "series": (
        ("rho_dollars", "ρ total", C_RHO, "-", 1.7),
    )},
    {"key": "poison", "ylabel": "Poison ratio", "series": (
        ("I_norm", "I-135", C_IODINE, "-", 1.5),
        ("Xe_norm", "Xe-135", C_XENON, "-", 1.7),
    )},
    {"key": "components", "ylabel": "ρ components ($)", "hidden": True, "series": (
        ("rho_rod_dollars", "rod", "#4ea1ff", "-", 1.4),
        ("rho_fuel_dollars", "fuel", C_FUEL, "-", 1.4),
        ("rho_coolant_dollars", "coolant", C_COOL, "-", 1.4),
        ("rho_xenon_dollars", "xenon", C_XENON, "-", 1.4),
    )},
    {"key": "timing", "ylabel": "Step time (s)", "log": True, "hidden": True, "series": (
        ("target_h_s", "target h", C_TARGET_H, "-", 1.4),
        ("step_real_time_s", "real / step", C_STEP, "-", 1.4),
    )},
)
# D cycles the bottom optional chart among these three.
OPTIONAL_CHARTS = ("poison", "components", "timing")
SERIES_FIELDS = tuple(field for spec in CHART_DEFS for field, *_ in spec["series"])


def apply_theme():
    plt.rcParams.update({
        "figure.facecolor": BG,
        "axes.facecolor": PANEL,
        "axes.edgecolor": PANEL_EDGE,
        "axes.labelcolor": MUTED,
        "axes.titlecolor": TEXT,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "axes.labelsize": 9,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "text.color": TEXT,
        "font.family": "sans-serif",
        "legend.frameon": False,
    })
    # Free the keys we use for reactor commands (R=SCRAM, K=clear, P=reset,
    # L=load session; S/E/O are unbound by default).
    for keymap, blocked in (
        ("keymap.home", "r"),
        ("keymap.xscale", "k"),
        ("keymap.pan", "p"),
        ("keymap.fullscreen", "f"),
        ("keymap.quit", "q"),
        ("keymap.yscale", "l"),
    ):
        plt.rcParams[keymap] = [k for k in plt.rcParams[keymap] if k.lower() != blocked]
    plt.rcParams["keymap.quit"] = [k for k in plt.rcParams["keymap.quit"] if k != " "]


def log(message):
    print(message, file=sys.stderr, flush=True)


def _file_dialog(title, save=False, default_name=None):
    """Native file chooser; returns a path or None. Falls back to None when
    no GUI toolkit is available (headless runs use the smoke API directly)."""
    try:
        from tkinter import Tk, filedialog
    except ImportError as exc:
        log(f"File dialog unavailable ({exc}).")
        return None
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    filetypes = (("Session CSV", "*.csv"), ("All files", "*.*"))
    try:
        if save:
            path = filedialog.asksaveasfilename(
                title=title, defaultextension=".csv",
                initialfile=default_name or "pk_run.csv",
                initialdir=CAPTURE_DIRNAME, filetypes=filetypes)
        else:
            path = filedialog.askopenfilename(
                title=title, initialdir=CAPTURE_DIRNAME, filetypes=filetypes)
    finally:
        root.destroy()
    return path or None


def parse_duration(value):
    text = str(value).strip().lower()
    multiplier = 1.0
    for suffix, unit in (("h", 3600.0), ("hr", 3600.0), ("hours", 3600.0), ("hour", 3600.0),
                         ("m", 60.0), ("min", 60.0), ("mins", 60.0), ("minutes", 60.0),
                         ("s", 1.0), ("sec", 1.0), ("secs", 1.0), ("seconds", 1.0)):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            multiplier = unit
            break
    try:
        duration = float(text) * multiplier
    except ValueError as exc:
        raise argparse.ArgumentTypeError("duration must be a number, optionally followed by s, m, or h") from exc
    if duration <= 0:
        raise argparse.ArgumentTypeError("duration must be greater than zero")
    return duration


# ---------------------------------------------------------------------------
# Communication
# ---------------------------------------------------------------------------

class StdinComm:
    """Reads simulator data from stdin and emits UI commands on stderr."""

    def open(self):
        log("[StdinComm] Reading data from stdin")

    def read_line(self):
        return sys.stdin.readline()

    def write(self, data):
        command = data.strip()
        if command:
            print(f"{COMMAND_PREFIX}{command}", file=sys.stderr, flush=True)

    def close(self):
        log("[StdinComm] Input closed.")


class SerialComm:
    """Wrapper for PySerial to communicate with the FPGA/UART.

    Drops into a disconnected state on any read/write failure and retries
    the port every few seconds so a board replug never kills the dashboard.
    """

    REOPEN_INTERVAL_S = 2.0

    def __init__(self, port="COM7", baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.connected = False
        self._last_reopen = 0.0

    def open(self):
        try:
            import serial
        except ImportError as exc:
            raise ImportError("pyserial not installed. Run 'pip install pyserial'") from exc
        self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
        self.connected = True
        log(f"[SerialComm] Opened port {self.port} at {self.baudrate} baud")

    def _drop(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.connected = False

    def try_reopen(self):
        if self.connected:
            return
        now = time.monotonic()
        if now - self._last_reopen < self.REOPEN_INTERVAL_S:
            return
        self._last_reopen = now
        try:
            self.open()
            log("[SerialComm] Reconnected")
        except Exception as exc:
            log(f"[SerialComm] Waiting for {self.port}: {exc}")

    def read_line(self):
        if self.ser and self.ser.is_open:
            try:
                return self.ser.readline().decode("utf-8", errors="ignore")
            except Exception as exc:
                log(f"Serial read error: {exc}")
                self._drop()
        return ""

    def write(self, data):
        if self.ser:
            try:
                self.ser.write(data.encode("utf-8"))
            except Exception as exc:
                log(f"Serial write error: {exc}")
                self._drop()

    def close(self):
        if self.ser:
            self.ser.close()
            self.connected = False
            log("[SerialComm] Port closed.")


class DummyComm:
    """No-op transport used by the offline smoke render."""

    def open(self):
        pass

    def read_line(self):
        return ""

    def write(self, data):
        pass

    def close(self):
        pass


data_queue = queue.Queue()
sim_finished = threading.Event()


def parse_telemetry(line):
    """Parse one CSV telemetry line into a field dict, or None."""
    parts = line.split(",")
    if len(parts) < 5:
        return None
    row = {}
    for index, (name, default) in enumerate(zip(FIELD_NAMES, FIELD_DEFAULTS)):
        text = parts[index].strip() if index < len(parts) else ""
        if not text:
            row[name] = default
            continue
        try:
            row[name] = float(text)
        except ValueError:
            return None
    if not math.isfinite(row["sim_time_s"]):
        return None
    return row


def read_session_csv(path):
    """Read a session CSV into (times, table{column: list[float]}), or None."""
    try:
        with open(path, newline="") as handle:
            rows = list(csv.reader(handle))
    except OSError as exc:
        log(f"Session read error: {exc}")
        return None
    if len(rows) < 2:
        log("Session file has no data rows.")
        return None
    header = [name.strip() for name in rows[0]]
    if "sim_time_s" not in header:
        log("Session file lacks a sim_time_s column.")
        return None
    times = []
    table = {name: [] for name in header}
    for record in rows[1:]:
        if len(record) != len(header):
            continue
        try:
            t = float(record[header.index("sim_time_s")])
        except ValueError:
            continue
        if not math.isfinite(t):
            continue
        times.append(t)
        for name, text in zip(header, record):
            try:
                table[name].append(float(text))
            except ValueError:
                table[name].append(NAN)
    return times, table


def load_overlay_csv(path):
    """Load a saved session CSV as a reference trace for chart overlay.

    Accepts any CSV with a header row containing `sim_time_s` plus at least
    one known series field (e.g. files written by the dashboard capture).
    Returns {"label", "t", columns{field: np.ndarray}} or None.
    """
    loaded = read_session_csv(path)
    if loaded is None:
        return None
    times, table = loaded
    columns = {}
    for field in SERIES_FIELDS:
        if field in table and field != "sim_time_s":
            columns[field] = np.asarray(table[field], dtype=float)
    if not columns:
        log("Overlay file contains no recognized series fields.")
        return None
    label = os.path.splitext(os.path.basename(path))[0]
    return {"label": label, "t": np.asarray(times, dtype=float), "columns": columns}


def reader_thread(comm):
    log("Reader thread started.")
    while not sim_finished.is_set():
        line = comm.read_line()
        if not line:
            if isinstance(comm, StdinComm):
                break
            if isinstance(comm, SerialComm):
                comm.try_reopen()
                time.sleep(0.1)
            continue
        line = line.strip()
        if not line or "," not in line or "DATA_START" in line:
            continue
        row = parse_telemetry(line)
        if row is not None:
            data_queue.put(row)
    log("Reader thread finished.")
    sim_finished.set()


# ---------------------------------------------------------------------------
# Reactor-core schematic (raster particle renderer)
# ---------------------------------------------------------------------------

def _rgb(color):
    return np.asarray(mcolors.to_rgb(color), dtype=np.float32)


def _gaussian_kernel(radius, sigma):
    axis = np.arange(-radius, radius + 1, dtype=np.float32)
    xx, yy = np.meshgrid(axis, axis)
    kernel = np.exp(-(xx * xx + yy * yy) / (2.0 * sigma * sigma))
    peak = float(kernel.max())
    return kernel / peak if peak > 0.0 else kernel


class FissionField:
    """Many small split sparks. Count and speed follow neutron power."""

    MAX_FISSIONS = 460
    MEAN_LIFE = 0.24

    def __init__(self, fuel_x, core_bottom, core_top):
        self.fuel_x = fuel_x
        self.core_bottom = core_bottom
        self.core_top = core_top
        self.rng = random.Random()
        self.events = []

    def _intensity(self, n):
        n = n if math.isfinite(n) and n > 0.0 else 0.0
        return min(1.0, n / 1.5)

    def _target_count(self, n):
        if not math.isfinite(n) or n < 0.003:
            return 0
        density = self._intensity(n) ** 0.5
        return min(self.MAX_FISSIONS, int(round(24 + 430 * density)))

    def _spawn(self, speed, intensity, age=0.0):
        cx = self.rng.choice(self.fuel_x)
        for _ in range(8):
            mid = self.rng.random()
            if self.rng.random() < 0.28 + 0.72 * math.sin(math.pi * mid):
                break
        y = self.core_bottom + mid * (self.core_top - self.core_bottom)
        angle = self.rng.uniform(0.0, math.tau)
        life = self.rng.uniform(0.14, 0.34)
        self.events.append({
            "x": cx + self.rng.uniform(-0.42, 0.42),
            "y": y,
            "ux": math.cos(angle),
            "uy": math.sin(angle),
            "n_angle": angle + self.rng.choice((-1.0, 1.0)) * self.rng.uniform(0.6, 1.4),
            "speed": speed * self.rng.uniform(0.7, 1.3),
            "age": min(age, life * 0.85),
            "life": life,
            "neutrons": intensity > 0.08,
        })

    def update(self, n, dt):
        intensity = self._intensity(n)
        target = self._target_count(n)
        speed = 0.22 + 1.15 * intensity
        dt = max(0.0, min(0.12, dt))
        for event in self.events:
            event["age"] += dt
        self.events = [event for event in self.events if event["age"] < event["life"]]
        if len(self.events) > target:
            self.events.sort(key=lambda event: event["age"], reverse=True)
            del self.events[target:]
        seed_field = not self.events
        while len(self.events) < target:
            age = self.rng.uniform(0.0, self.MEAN_LIFE * 0.75) if seed_field else 0.0
            self._spawn(speed, intensity, age=age)
        return intensity


class CoreView:
    """Rasterized core: gradient fuel/moderator plus additive fission sparks."""

    WORLD_W = 10.4
    WORLD_H = 11.85
    IMG_W = 440
    IMG_H = 780

    FUEL_X = (2.35, 3.55, 4.75, 5.95, 7.15, 8.35)
    CTRL_X = (2.95, 4.15, 5.35, 6.55, 7.75)
    CTRL_STAGGER = (0.00, 0.08, -0.05, 0.06, -0.04)
    CORE_BOTTOM = 2.6
    CORE_TOP = 8.9
    ROD_TOP = 10.85

    COOL_COLD = _rgb("#16324f")
    COOL_HOT = _rgb("#8a4632")
    FUEL_COLD = _rgb("#3f231b")
    FUEL_HOT = _rgb("#ff8c2e")
    VESSEL = _rgb("#10161e")
    VESSEL_EDGE = _rgb("#3a4654")
    ROD = _rgb("#5b6878")
    ROD_EDGE = _rgb("#8b98a8")
    CHERENKOV = np.array([0.22, 0.78, 1.00], dtype=np.float32)
    FRAG = np.array([1.00, 0.82, 0.42], dtype=np.float32)
    FLASH = np.array([1.00, 0.96, 0.82], dtype=np.float32)
    NEUTRON = np.array([0.70, 0.90, 1.00], dtype=np.float32)

    def __init__(self, ax):
        self.ax = ax
        ax.set_xlim(0, self.WORLD_W)
        ax.set_ylim(0, self.WORLD_H)
        ax.axis("off")

        ax.text(0.02, 1.00, "REACTOR CORE", transform=ax.transAxes, va="top",
                fontsize=10, fontweight="bold", color=TEXT, zorder=10)
        self.plant_txt = ax.text(0.02, 0.955, PLANT_NAMES[0], transform=ax.transAxes,
                                 va="top", fontsize=8, color=MUTED, zorder=10)
        self.rod_txt = ax.text(0.98, 1.00, "", transform=ax.transAxes, va="top",
                               ha="right", fontsize=8, color=MUTED, zorder=10)

        self._rgb = np.zeros((self.IMG_H, self.IMG_W, 3), dtype=np.float32)
        self._base = np.zeros_like(self._rgb)
        self._build_base()
        self._rgb[:] = self._base
        self.image = ax.imshow(
            self._rgb, origin="upper", aspect="auto", interpolation="bilinear",
            extent=(0.0, self.WORLD_W, 0.0, self.WORLD_H), zorder=1,
        )

        self._last_tick = None
        self.fission = FissionField(self.FUEL_X, self.CORE_BOTTOM, self.CORE_TOP)
        self._kern_frag = _gaussian_kernel(1, 0.50)
        self._kern_flash = _gaussian_kernel(1, 0.70)
        self._kern_neu = _gaussian_kernel(1, 0.42)

        self.badge = ax.text(5.2, 9.42, "", ha="center", va="center", fontsize=11,
                             fontweight="bold", color="#ffdcd7", zorder=12,
                             bbox={"boxstyle": "round,pad=0.45", "facecolor": C_SCRAM,
                                   "edgecolor": "none", "alpha": 0.92})
        self.badge.set_visible(False)

        for x, color, label in ((0.95, "#b3541e", "fuel"),
                                (3.05, "#5b6878", "control rods"),
                                (6.15, "#16324f", "moderator"),
                                (8.45, "#c9a36a", "fission")):
            ax.add_patch(Rectangle((x, 0.42), 0.38, 0.38, facecolor=color,
                                   edgecolor=PANEL_EDGE, linewidth=0.6, zorder=10))
            ax.text(x + 0.50, 0.61, label, va="center", fontsize=7.2, color=MUTED, zorder=10)

    def _px(self, x):
        return x / self.WORLD_W * (self.IMG_W - 1)

    def _py(self, y):
        return (1.0 - y / self.WORLD_H) * (self.IMG_H - 1)

    def _clamp_rect(self, x0, y0, x1, y1):
        ix0 = max(0, min(self.IMG_W, int(round(min(x0, x1)))))
        ix1 = max(0, min(self.IMG_W, int(round(max(x0, x1)))))
        iy0 = max(0, min(self.IMG_H, int(round(min(y0, y1)))))
        iy1 = max(0, min(self.IMG_H, int(round(max(y0, y1)))))
        return ix0, iy0, ix1, iy1

    def _fill(self, buf, x0, y0, x1, y1, color):
        ix0, iy0, ix1, iy1 = self._clamp_rect(x0, y0, x1, y1)
        if ix1 > ix0 and iy1 > iy0:
            buf[iy0:iy1, ix0:ix1] = color

    def _build_base(self):
        bg = _rgb(BG)
        self._base[:] = bg
        # Vessel shell, then a slightly inset inner well.
        self._fill(self._base, self._px(0.85), self._py(10.50), self._px(9.55), self._py(1.45),
                   self.VESSEL_EDGE)
        self._fill(self._base, self._px(0.92), self._py(10.42), self._px(9.48), self._py(1.53),
                   self.VESSEL)
        # Guide tubes.
        for cx in self.CTRL_X:
            self._fill(self._base, self._px(cx - 0.20), self._py(10.05),
                       self._px(cx + 0.20), self._py(self.CORE_BOTTOM),
                       np.array([0.12, 0.16, 0.21], dtype=np.float32))
        # Drive housings.
        for cx in self.CTRL_X:
            self._fill(self._base, self._px(cx - 0.28), self._py(11.00),
                       self._px(cx + 0.28), self._py(10.05),
                       np.array([0.07, 0.09, 0.12], dtype=np.float32))
        self._mod_x0, self._mod_y0, self._mod_x1, self._mod_y1 = self._clamp_rect(
            self._px(1.30), self._py(10.05), self._px(9.10), self._py(1.90),
        )

    def _stamp(self, cx, cy, kernel, rgb, gain):
        if gain <= 0.002:
            return
        radius = kernel.shape[0] // 2
        x = int(round(cx))
        y = int(round(cy))
        if x < self._mod_x0 or x >= self._mod_x1 or y < self._mod_y0 or y >= self._mod_y1:
            return
        x0 = x - radius
        y0 = y - radius
        x1 = x0 + kernel.shape[1]
        y1 = y0 + kernel.shape[0]
        kx0 = 0 if x0 >= 0 else -x0
        ky0 = 0 if y0 >= 0 else -y0
        kx1 = kernel.shape[1] - max(0, x1 - self.IMG_W)
        ky1 = kernel.shape[0] - max(0, y1 - self.IMG_H)
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.IMG_W, x1)
        y1 = min(self.IMG_H, y1)
        if x1 <= x0 or y1 <= y0:
            return
        patch = kernel[ky0:ky1, kx0:kx1] * gain
        self._rgb[y0:y1, x0:x1] += patch[:, :, None] * rgb

    def _draw_fuel_rod(self, cx, tf, n):
        x0 = self._px(cx - 0.31)
        x1 = self._px(cx + 0.31)
        y_top = self._py(self.CORE_TOP)
        y_bot = self._py(self.CORE_BOTTOM)
        ix0, iy0, ix1, iy1 = self._clamp_rect(x0, y_top, x1, y_bot)
        if ix1 <= ix0 or iy1 <= iy0:
            return
        rows = iy1 - iy0
        # Image y increases downward; top of rod is CORE_TOP.
        mid = (np.arange(rows, dtype=np.float32) + 0.5) / rows
        peaking = 0.35 + 0.65 * np.sin(np.pi * mid)
        heat = np.clip((tf - 265.0) / 500.0, 0.0, 1.2)
        mix = np.clip(heat * peaking, 0.0, 1.0)[:, None]
        body = self.FUEL_COLD[None, :] + (self.FUEL_HOT - self.FUEL_COLD)[None, :] * mix
        self._rgb[iy0:iy1, ix0:ix1] = body[:, None, :]
        # Thin inner filament.
        hx0 = int(round(self._px(cx - 0.08)))
        hx1 = int(round(self._px(cx + 0.08)))
        hx0 = max(ix0, hx0)
        hx1 = min(ix1, hx1)
        if hx1 > hx0:
            filament = np.clip(body * (1.12 + 0.10 * min(1.0, n / 1.5)), 0.0, 1.0)
            self._rgb[iy0:iy1, hx0:hx1] = filament[:, None, :]

    def _draw_control_rod(self, cx, tip_y):
        x0 = self._px(cx - 0.16)
        x1 = self._px(cx + 0.16)
        y_top = self._py(self.ROD_TOP)
        y_bot = self._py(tip_y)
        ix0, iy0, ix1, iy1 = self._clamp_rect(x0, y_top, x1, y_bot)
        if ix1 <= ix0 or iy1 <= iy0:
            return
        width = ix1 - ix0
        shade = np.linspace(1.18, 0.72, width, dtype=np.float32)
        metal = np.clip(self.ROD[None, :] * shade[:, None], 0.0, 1.0)
        self._rgb[iy0:iy1, ix0:ix1] = metal[None, :, :]
        # Specular edge.
        if width > 2:
            self._rgb[iy0:iy1, ix0:ix0 + 1] = np.clip(self.ROD_EDGE, 0.0, 1.0)

    def _draw_fission(self, intensity):
        for event in self.fission.events:
            life_left = 1.0 - event["age"] / event["life"]
            fade = life_left * life_left
            travel = event["speed"] * event["age"]
            x0, y0 = event["x"], event["y"]
            dx = event["ux"] * travel
            dy = event["uy"] * travel
            px0, py0 = self._px(x0), self._py(y0)
            px1, py1 = self._px(x0 + dx), self._py(y0 + dy)
            px2, py2 = self._px(x0 - dx), self._py(y0 - dy)

            frag_gain = (0.16 + 0.10 * intensity) * (0.45 + 0.55 * fade)
            self._stamp(px1, py1, self._kern_frag, self.FRAG, frag_gain)
            self._stamp(px2, py2, self._kern_frag, self.FRAG, frag_gain * 0.8)

            if event["age"] < 0.04:
                flash_gain = (0.18 + 0.08 * intensity) * (1.0 - event["age"] / 0.04)
                self._stamp(px0, py0, self._kern_flash, self.FLASH, flash_gain)

            if event["neutrons"]:
                n_travel = travel * 1.7
                nx = math.cos(event["n_angle"])
                ny = math.sin(event["n_angle"])
                neu_gain = (0.10 + 0.08 * intensity) * fade
                self._stamp(self._px(x0 + nx * n_travel), self._py(y0 + ny * n_travel),
                            self._kern_neu, self.NEUTRON, neu_gain)
                self._stamp(self._px(x0 - nx * n_travel * 0.4), self._py(y0 - ny * n_travel * 0.4),
                            self._kern_neu, self.NEUTRON, neu_gain * 0.5)

    def set_plant(self, mode):
        self.plant_txt.set_text(PLANT_NAMES.get(mode, "Unknown preset"))

    def update(self, n, tf, tc, rod_position, scram, fault):
        n = n if math.isfinite(n) else 0.0
        tf = tf if math.isfinite(tf) else 293.0
        tc = tc if math.isfinite(tc) else 293.0
        rod_position = rod_position if math.isfinite(rod_position) else 0.0
        rod_position = min(1.0, max(0.0, rod_position))

        now = time.monotonic()
        dt = 0.05 if self._last_tick is None else now - self._last_tick
        self._last_tick = now

        intensity = self.fission.update(n, dt)
        self._rgb[:] = self._base

        cool = self.COOL_COLD + (self.COOL_HOT - self.COOL_COLD) * np.clip((tc - 275.0) / 175.0, 0.0, 1.0)
        cherenkov = min(0.16, max(0.0, 0.12 * n / 1.5))
        moderator = np.clip(cool * (1.0 - 0.35 * cherenkov) + self.CHERENKOV * cherenkov, 0.0, 1.0)
        self._rgb[self._mod_y0:self._mod_y1, self._mod_x0:self._mod_x1] = moderator

        for cx in self.FUEL_X:
            self._draw_fuel_rod(cx, tf, n)
        self._draw_fission(intensity)

        inserted = 1.0 - rod_position
        for cx, stagger in zip(self.CTRL_X, self.CTRL_STAGGER):
            tip_y = self.CORE_TOP - inserted * (self.CORE_TOP - self.CORE_BOTTOM) + stagger * inserted
            tip_y = min(self.CORE_TOP, max(self.CORE_BOTTOM, tip_y))
            self._draw_control_rod(cx, tip_y)

        np.clip(self._rgb, 0.0, 1.0, out=self._rgb)
        self.image.set_data(self._rgb)

        self.rod_txt.set_text(f"rods {rod_position * 100.0:.1f}% withdrawn")
        if fault:
            self.badge.set_text("NUMERICAL TRIP")
            self.badge.set_visible(True)
        elif scram:
            self.badge.set_text("SCRAM")
            self.badge.set_visible(True)
        else:
            self.badge.set_visible(False)


# ---------------------------------------------------------------------------
# Telemetry panel
# ---------------------------------------------------------------------------

def fmt_float(digits):
    def inner(value):
        return f"{value:.{digits}f}" if math.isfinite(value) else "—"
    return inner


def fmt_signed(value):
    return f"{value:+.3f} $" if math.isfinite(value) else "—"


def fmt_percent(value):
    return f"{value * 100.0:.1f} %" if math.isfinite(value) else "—"


def fmt_celsius(value):
    return f"{value:.1f} °C" if math.isfinite(value) else "—"


class StatusPanel:
    ROWS = (
        (("Neutron power", "n", fmt_float(4)), ("Thermal power", "thermal", fmt_float(4))),
        (("Fuel temp", "Tf", fmt_celsius), ("Coolant temp", "Tc", fmt_celsius)),
        (("Reactivity", "rho_dollars", fmt_signed), ("Critical rod", "critical_rod_position", fmt_percent)),
        (("Rod position", "rod_position", fmt_percent), ("Rod target", "rod_target", fmt_percent)),
        (("Iodine ratio", "I_norm", fmt_float(3)), ("Xenon ratio", "Xe_norm", fmt_float(3))),
    )

    def __init__(self, ax):
        ax.axis("off")
        ax.add_patch(FancyBboxPatch((0.012, 0.02), 0.976, 0.96, transform=ax.transAxes,
                                    boxstyle="round,pad=0.008,rounding_size=0.03",
                                    facecolor=PANEL, edgecolor=PANEL_EDGE, linewidth=1.0))
        ax.text(0.045, 0.90, "TELEMETRY", fontsize=8.5, fontweight="bold",
                color=MUTED, transform=ax.transAxes, va="center")
        self.values = {}
        columns = ((0.045, 0.475), (0.545, 0.965))
        for row_index, row in enumerate(self.ROWS):
            y = 0.76 - row_index * 0.13
            for (label, key, formatter), (label_x, value_x) in zip(row, columns):
                ax.text(label_x, y, label, fontsize=7.8, color=MUTED,
                        transform=ax.transAxes, va="center")
                text = ax.text(value_x, y, "—", fontsize=8.8, fontweight="bold",
                               color=TEXT, transform=ax.transAxes, va="center", ha="right")
                self.values[key] = (text, formatter)

    def update(self, latest, thermal):
        merged = dict(latest)
        merged["thermal"] = thermal
        for key, (text, formatter) in self.values.items():
            text.set_text(formatter(merged.get(key, NAN)))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def style_axes(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(PANEL_EDGE)
    ax.grid(True, alpha=0.55)
    ax.tick_params(length=0)


def build_dashboard(args, comm):
    apply_theme()
    fig = plt.figure(figsize=(15.4, 9.0))
    if fig.canvas.manager:
        fig.canvas.manager.set_window_title("Point-Kinetics Reactor")

    fig.text(0.052, 0.972, "Point-Kinetics Reactor Simulator", fontsize=13,
             fontweight="bold", color=TEXT)
    source_label = "UART" if args.source == "serial" else "PIPE"
    fig.text(0.052, 0.952, f"source {source_label}", fontsize=8, color=MUTED)
    alarm_txt = fig.text(0.205, 0.970, "", fontsize=9, color=C_SCRAM,
                         fontweight="bold", va="center")
    live_txt = fig.text(0.494, 0.965, "", fontsize=9, color=MUTED, ha="right")

    # --- Trend charts -------------------------------------------------------
    charts = []
    for spec in CHART_DEFS:
        ax = fig.add_axes((0.052, 0.1, 0.442, 0.1))
        style_axes(ax)
        ax.set_ylabel(spec["ylabel"])
        if spec.get("log"):
            ax.set_yscale("log")
        if "hline" in spec:
            level, label = spec["hline"]
            ax.axhline(level, color=C_SCRAM, linestyle="--", linewidth=1.0, alpha=0.65, label=label)
        lines = {}
        for field, label, color, linestyle, width in spec["series"]:
            line, = ax.plot([], [], color=color, linestyle=linestyle, linewidth=width, label=label)
            lines[field] = line
        ax.legend(loc="upper left", fontsize=7.4, ncol=4, handlelength=1.6,
                  borderaxespad=0.2, labelcolor=MUTED)
        value_txt = ax.text(0.995, 0.96, "", transform=ax.transAxes, ha="right",
                            va="top", fontsize=7.8, color=TEXT, fontweight="bold")
        charts.append({
            "spec": spec, "ax": ax, "lines": lines, "value_txt": value_txt,
            "visible": not spec.get("hidden", False),
            "event_artists": [],
        })

    # Optional-chart cycle starts on poison (visible); components and timing hidden.
    optional_index = 0

    def layout_charts():
        visible = [chart for chart in charts if chart["visible"]]
        top, bottom, gap = 0.940, 0.075, 0.032
        height = (top - bottom - gap * (len(visible) - 1)) / max(1, len(visible))
        y = top
        for index, chart in enumerate(visible):
            ax = chart["ax"]
            ax.set_visible(True)
            ax.set_position((0.052, y - height, 0.442, height))
            last = index == len(visible) - 1
            ax.tick_params(labelbottom=last)
            ax.set_xlabel("Time (s)" if last else "")
            y -= height + gap
        for chart in charts:
            if not chart["visible"]:
                chart["ax"].set_visible(False)
        fig.canvas.draw_idle()

    layout_charts()

    # --- Core schematic and telemetry panel ---------------------------------
    core = CoreView(fig.add_axes((0.516, 0.330, 0.252, 0.610)))
    status = StatusPanel(fig.add_axes((0.516, 0.062, 0.252, 0.248)))

    # --- Controls ------------------------------------------------------------
    def section(label, y):
        fig.text(0.802, y, label, fontsize=7.6, fontweight="bold", color=MUTED)

    def style_button(button, color, hover, size=9):
        button.color = color
        button.hovercolor = hover
        button.ax.set_facecolor(color)
        button.label.set_color(TEXT)
        button.label.set_fontsize(size)
        button.label.set_fontweight("bold")
        for spine in button.ax.spines.values():
            spine.set_edgecolor(PANEL_EDGE)

    widgets = []

    section("SAFETY", 0.936)
    scram_btn = Button(fig.add_axes((0.802, 0.868, 0.168, 0.058)), "SCRAM")
    style_button(scram_btn, C_SCRAM, C_SCRAM_HOVER, size=11)
    widgets.append(scram_btn)
    clear_btn = Button(fig.add_axes((0.802, 0.818, 0.168, 0.040)), "Clear SCRAM")
    style_button(clear_btn, C_CLEAR_DIM, C_CLEAR, size=8)
    widgets.append(clear_btn)

    section("CONTROL ROD TARGET", 0.778)
    rod_ax = fig.add_axes((0.808, 0.736, 0.156, 0.026))
    rod_ax.set_facecolor("#232b36")
    rod_slider = Slider(rod_ax, "", 0.0, 1.0, valinit=0.75, initcolor="none",
                        color=ACCENT, track_color="#232b36",
                        handle_style={"facecolor": TEXT, "edgecolor": ACCENT, "size": 10})
    rod_slider.valtext.set_visible(False)
    # Critical-rod tick on the slider track.
    crit_line = rod_ax.axvline(0.75, color="#fbbf24", linewidth=1.6, alpha=0.95, zorder=5)
    crit_label = fig.text(0.886, 0.700, "crit —   target 75.0%", fontsize=7.2,
                          color=MUTED, ha="center")
    widgets.append(rod_slider)

    section("VIEW WINDOW", 0.668)
    window_buttons = []
    window_width = 0.038
    window_gap = 0.004
    for index, (label, _) in enumerate(WINDOW_PRESETS):
        x = 0.802 + index * (window_width + window_gap)
        btn = Button(fig.add_axes((x, 0.628, window_width, 0.032)), label)
        style_button(btn, C_BTN, C_BTN_HOVER, size=7)
        window_buttons.append(btn)
        widgets.append(btn)

    pause_btn = Button(fig.add_axes((0.802, 0.582, 0.056, 0.036)), "Pause")
    style_button(pause_btn, C_BTN, C_BTN_HOVER, size=6.5)
    widgets.append(pause_btn)
    save_btn = Button(fig.add_axes((0.862, 0.582, 0.036, 0.036)), "Save")
    style_button(save_btn, C_BTN, C_BTN_HOVER, size=6.5)
    widgets.append(save_btn)
    load_btn = Button(fig.add_axes((0.902, 0.582, 0.036, 0.036)), "Load")
    style_button(load_btn, C_BTN, C_BTN_HOVER, size=6.5)
    widgets.append(load_btn)
    overlay_btn = Button(fig.add_axes((0.942, 0.582, 0.036, 0.036)), "Ref")
    style_button(overlay_btn, C_BTN, C_BTN_HOVER, size=6.5)
    widgets.append(overlay_btn)

    section("SIMULATION SPEED", 0.548)
    speed_ax = fig.add_axes((0.802, 0.432, 0.168, 0.104))
    speed_ax.set_facecolor(PANEL)
    speed_radio = RadioButtons(speed_ax, ("Realtime 1x", "Training 10x", "Xenon 1000x"),
                               active=0, activecolor=ACCENT)
    widgets.append(speed_radio)

    section("PLANT PRESET", 0.396)
    plant_ax = fig.add_axes((0.802, 0.280, 0.168, 0.104))
    plant_ax.set_facecolor(PANEL)
    plant_radio = RadioButtons(plant_ax, ("PWR-SMR", "RBMK-like", "TMI-loss"),
                               active=0, activecolor=ACCENT)
    widgets.append(plant_radio)

    for radio in (speed_radio, plant_radio):
        for label in radio.labels:
            label.set_color(TEXT)
            label.set_fontsize(8)
        for spine in radio.ax.spines.values():
            spine.set_edgecolor(PANEL_EDGE)

    section("POWER RESET", 0.244)
    power_ax = fig.add_axes((0.802, 0.190, 0.168, 0.040))
    power_box = TextBox(power_ax, "", initial=f"{args.power:.2f}")
    power_ax.set_facecolor("#232b36")
    power_box.text_disp.set_color(TEXT)
    power_box.text_disp.set_fontsize(9)
    if hasattr(power_box, "cursor"):
        power_box.cursor.set_color(TEXT)
    for spine in power_ax.spines.values():
        spine.set_edgecolor(PANEL_EDGE)
    widgets.append(power_box)
    reset_btn = Button(fig.add_axes((0.802, 0.140, 0.168, 0.040)), "Reset at power")
    style_button(reset_btn, C_BTN, C_BTN_HOVER, size=8)
    widgets.append(reset_btn)

    section("NEUTRON SOURCE", 0.100)
    source_ax = fig.add_axes((0.802, 0.052, 0.078, 0.040))
    source_box = TextBox(source_ax, "", initial="0.000")
    source_ax.set_facecolor("#232b36")
    for spine in source_ax.spines.values():
        spine.set_edgecolor(PANEL_EDGE)
    source_box.text_disp.set_color(TEXT)
    source_box.text_disp.set_fontsize(9)
    if hasattr(source_box, "cursor"):
        source_box.cursor.set_color(TEXT)
    widgets.append(source_box)
    source_btn = Button(fig.add_axes((0.888, 0.052, 0.082, 0.040)), "Set source")
    style_button(source_btn, C_BTN, C_BTN_HOVER, size=7)
    widgets.append(source_btn)

    fig.text(0.802, 0.040,
             "Keys:  R scram  K clear  P reset\n"
             "Space pause  D cycle  E capture\n"
             "S save as  L load  O ref  ↑↓ rod",
             fontsize=6.2, color=MUTED, linespacing=1.3, va="top")

    # --- State ----------------------------------------------------------------
    history = {"t": []}
    for field in SERIES_FIELDS:
        history[field] = []
    rows_log = []  # full-fidelity telemetry rows for session export/reload
    events = []  # list of {"t", "kind", "label"}
    latest = {}
    state = {
        "plant": 0,
        "slider_suppressed": False,
        "paused": False,
        "window_seconds": None if args.plot_mode == "full" else args.window,
        "window_all": args.plot_mode == "full",
        "prev_scram": False,
        "prev_fault": False,
        "prev_plant": None,
        "prev_rod_target": None,
        "scram_ui": False,
        # Pending rod-adjustment burst: coalesce rapid ±1% clicks into one marker.
        "rod_burst": None,  # {"start", "end", "last_t"} or None
        # Reference overlay trace (dict from load_overlay_csv) or None.
        "overlay": None,
        # Active alarm labels.
        "alarms": set(),
    }

    def clear_history():
        for values in history.values():
            values.clear()
        rows_log.clear()
        events.clear()
        for chart in charts:
            for line in chart["lines"].values():
                line.set_data([], [])
            chart["value_txt"].set_text("")
            chart["ax"].set_xlim(0, INITIAL_X_SECONDS)
            for artist in chart["event_artists"]:
                artist.remove()
            chart["event_artists"] = []
        state["prev_scram"] = False
        state["prev_fault"] = False
        state["prev_plant"] = None
        state["prev_rod_target"] = None
        state["rod_burst"] = None

    def drain_queue():
        while True:
            try:
                data_queue.get_nowait()
            except queue.Empty:
                break

    def record_event(t, kind, label):
        if events and abs(events[-1]["t"] - t) < 0.05 and events[-1]["kind"] == kind:
            return
        events.append({"t": t, "kind": kind, "label": label})

    def flush_rod_burst(at_time=None):
        """Commit a coalesced rod-target change as a single chart marker.

        Place the vertical line at the first click, where the physics response
        begins. Do not place it at the quiet timeout or the last click.
        """
        burst = state["rod_burst"]
        if burst is None:
            return
        start = burst["start"]
        end = burst["end"]
        t = burst["first_t"]
        state["rod_burst"] = None
        if abs(end - start) < ROD_EVENT_MIN_DELTA:
            return
        record_event(t, "rod", f"rod {start * 100:.0f}->{end * 100:.0f}%")

    def note_rod_target(t, rod_target, scram_now):
        """Accumulate rod changes; emit one marker after ROD_COALESCE_S of quiet."""
        if rod_target is None:
            return
        prev = state["prev_rod_target"]
        if prev is None:
            state["prev_rod_target"] = rod_target
            return

        changed = abs(rod_target - prev) > ROD_EVENT_MIN_DELTA
        if changed and not scram_now:
            burst = state["rod_burst"]
            if burst is None:
                state["rod_burst"] = {
                    "start": prev,
                    "end": rod_target,
                    "first_t": t,
                    "last_t": t,
                }
            else:
                burst["end"] = rod_target
                burst["last_t"] = t
        elif changed and scram_now:
            # SCRAM forces target to 0; drop any pending burst without a rod marker.
            state["rod_burst"] = None

        state["prev_rod_target"] = rod_target

        burst = state["rod_burst"]
        if burst is not None and (t - burst["last_t"]) >= ROD_COALESCE_S:
            flush_rod_burst()

    def detect_events(row, t):
        scram_now = row["scram_active"] >= 0.5
        fault_now = row["engine_status"] <= 0.0
        plant_now = int(row["plant_mode"]) if math.isfinite(row["plant_mode"]) else state["plant"]
        rod_target = row["rod_target"] if math.isfinite(row["rod_target"]) else None

        if state["prev_scram"] is False and scram_now and not fault_now:
            flush_rod_burst()
            record_event(t, "SCRAM", "SCRAM")
        if state["prev_scram"] is True and not scram_now:
            record_event(t, "clear", "clear")
        if state["prev_fault"] is False and fault_now:
            flush_rod_burst()
            record_event(t, "trip", "trip")
        if state["prev_plant"] is not None and plant_now != state["prev_plant"]:
            flush_rod_burst()
            record_event(t, "plant", f"C{plant_now}")

        note_rod_target(t, rod_target, scram_now)

        state["prev_scram"] = scram_now
        state["prev_fault"] = fault_now
        state["prev_plant"] = plant_now

    def redraw_event_markers(window_start, window_end):
        top_visible = next((chart for chart in charts if chart["visible"]), None)
        for chart in charts:
            for artist in chart["event_artists"]:
                artist.remove()
            chart["event_artists"] = []
            if not chart["visible"]:
                continue
            ax = chart["ax"]
            # Deduplicate labels only for one-shot kinds (SCRAM/clear/trip/plant).
            # Rod bursts each get their own label — otherwise later adjustments
            # leave an unexplained vertical line.
            labeled_once = set()
            for event in events:
                if event["t"] < window_start or event["t"] > window_end:
                    continue
                color = C_EVENT.get(event["kind"], MUTED)
                line = ax.axvline(event["t"], color=color, linewidth=1.15,
                                  alpha=0.85, linestyle="--", zorder=3)
                chart["event_artists"].append(line)
                if chart is not top_visible:
                    continue
                if event["kind"] != "rod" and event["kind"] in labeled_once:
                    continue
                labeled_once.add(event["kind"])
                txt = ax.text(event["t"], 0.98, event["label"], transform=ax.get_xaxis_transform(),
                              fontsize=6.5, color=color, ha="center", va="top",
                              clip_on=True, zorder=4)
                chart["event_artists"].append(txt)

    def set_scram_button_state(scram_active):
        state["scram_ui"] = scram_active
        if scram_active:
            style_button(scram_btn, C_SCRAM_DIM, C_SCRAM_DIM, size=11)
            style_button(clear_btn, C_CLEAR_ARMED, C_CLEAR_ARMED_HOVER, size=8)
            clear_btn.label.set_text("Clear SCRAM  ●")
        else:
            style_button(scram_btn, C_SCRAM, C_SCRAM_HOVER, size=11)
            style_button(clear_btn, C_CLEAR_DIM, C_CLEAR, size=8)
            clear_btn.label.set_text("Clear SCRAM")

    def highlight_window_buttons():
        for index, (btn, (_, seconds)) in enumerate(zip(window_buttons, WINDOW_PRESETS)):
            if state["window_all"] and seconds is None:
                style_button(btn, C_BTN_ACTIVE, C_BTN_HOVER, size=7)
            elif (not state["window_all"] and seconds is not None
                  and abs(state["window_seconds"] - seconds) < 0.5):
                style_button(btn, C_BTN_ACTIVE, C_BTN_HOVER, size=7)
            else:
                style_button(btn, C_BTN, C_BTN_HOVER, size=7)

    def set_window_preset(index):
        label, seconds = WINDOW_PRESETS[index]
        if seconds is None:
            state["window_all"] = True
            state["window_seconds"] = None
        else:
            state["window_all"] = False
            state["window_seconds"] = seconds
        highlight_window_buttons()
        fig.canvas.draw_idle()

    def set_pause(paused):
        state["paused"] = paused
        if paused:
            pause_btn.label.set_text("Resume")
            style_button(pause_btn, C_BTN_ACTIVE, C_BTN_HOVER, size=7)
            live_txt.set_text("PAUSED")
            live_txt.set_color(ACCENT)
        else:
            pause_btn.label.set_text("Pause")
            style_button(pause_btn, C_BTN, C_BTN_HOVER, size=7)
        fig.canvas.draw_idle()

    # --- Capture / reference overlay -----------------------------------------
    def export_session(dest=None):
        """Write the full history as CSV plus a PNG snapshot of the dashboard.

        `dest` may be a directory (auto timestamped name) or a full CSV path
        from the save dialog. Returns the CSV path or None when empty.
        """
        if not history["t"]:
            log("Capture skipped: no telemetry received yet.")
            return None
        target = dest or CAPTURE_DIRNAME
        if os.path.splitext(target)[1].lower() == ".csv":
            csv_path = target
            outdir = os.path.dirname(csv_path)
        else:
            outdir = target
            os.makedirs(outdir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = os.path.join(outdir, f"pk_run_{stamp}.csv")
        fields = list(FIELD_NAMES) + ["thermal"]
        with open(csv_path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            for row in rows_log:
                writer.writerow([row.get(name, NAN) for name in fields])
        png_path = os.path.splitext(csv_path)[0] + ".png"
        fig.savefig(png_path, dpi=115, facecolor=BG)
        log(f"Captured session: {csv_path}")
        log(f"Captured snapshot: {png_path}")
        return csv_path

    def set_overlay(reference):
        """Attach or clear a reference trace (dict from load_overlay_csv)."""
        state["overlay"] = reference
        for chart in charts:
            for artist in chart.get("overlay_artists", {}).values():
                artist.remove()
            chart["overlay_artists"] = {}
        if reference is not None:
            log(f"Overlaying reference: {reference['label']} "
                f"({len(reference['t'])} rows)")
        else:
            log("Overlay cleared.")
        fig.canvas.draw_idle()

    def pick_overlay_file():
        path = _file_dialog("Load reference session CSV", save=False)
        set_overlay(load_overlay_csv(path) if path else None)

    def save_session_as():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _file_dialog(f"pk_run_{stamp}.csv", save=True)
        if path:
            export_session(path)

    def load_session_dialog():
        path = _file_dialog("Load session CSV", save=False)
        if path:
            load_session(path)

    def load_session(path):
        """Restore a saved CSV as the dashboard history (paused review view)."""
        loaded = read_session_csv(path)
        if loaded is None:
            return
        times, table = loaded
        drain_queue()
        clear_history()
        history["t"].extend(times)
        for field in SERIES_FIELDS:
            history[field].extend(table.get(field, [NAN] * len(times)))

        # Reconstruct SCRAM / clear / trip markers from the status columns.
        prev_scram = False
        prev_fault = False
        for index, t in enumerate(times):
            scram_now = (table.get("scram_active", [0.0] * len(times))[index]) >= 0.5
            fault_now = (table.get("engine_status", [1.0] * len(times))[index]) <= 0.0
            if scram_now and not prev_scram and not fault_now:
                record_event(t, "SCRAM", "SCRAM")
            if prev_scram and not scram_now:
                record_event(t, "clear", "clear")
            if fault_now and not prev_fault:
                record_event(t, "trip", "trip")
            prev_scram = scram_now
            prev_fault = fault_now

        latest.clear()
        for name in FIELD_NAMES:
            if name in table and table[name]:
                latest[name] = table[name][-1]

        state["window_all"] = True
        highlight_window_buttons()
        set_pause(False)
        update(0)
        set_pause(True)
        log(f"Loaded session {os.path.basename(path)} ({len(times)} rows, paused). "
            "Incoming telemetry starts a new trace.")

    def update_alarms(row):
        firing = set()
        for field, predicate, label in ALARM_DEFS:
            value = row.get(field, NAN)
            if math.isfinite(value) and predicate(value):
                firing.add(label)
        if firing == state["alarms"]:
            return
        for label in firing - state["alarms"]:
            log(f"ALARM raised: {label}")
        for label in state["alarms"] - firing:
            log(f"ALARM cleared: {label}")
        state["alarms"] = firing
        if firing:
            alarm_txt.set_text("⚠ " + "   ".join(sorted(firing)))
            alarm_txt.set_color(C_SCRAM)
        else:
            alarm_txt.set_text("")

    # --- Commands ---------------------------------------------------------------
    def set_slider(value):
        state["slider_suppressed"] = True
        try:
            rod_slider.set_val(min(1.0, max(0.0, value)))
        finally:
            state["slider_suppressed"] = False

    def on_slider(value):
        crit = latest.get("critical_rod_position", NAN)
        crit_txt = f"{crit * 100.0:.1f}%" if math.isfinite(crit) else "—"
        crit_label.set_text(f"crit {crit_txt}   target {value * 100.0:.1f}%")
        if not state["slider_suppressed"]:
            comm.write(f"W {value:.3f}\n")

    def scram():
        comm.write("R\n")
        set_slider(0.0)
        set_scram_button_state(True)

    def clear_scram():
        comm.write("K\n")
        set_scram_button_state(False)

    def reset_power(text):
        try:
            power = max(0.0, min(1.5, float(text)))
        except ValueError:
            return
        drain_queue()
        clear_history()
        set_scram_button_state(False)
        comm.write(f"P {power}\n")
        fig.canvas.draw_idle()

    def set_source(text):
        try:
            source = max(0.0, min(0.01, float(text)))
        except ValueError:
            return
        source_box.set_val(f"{source:.4f}")
        comm.write(f"S {source}\n")
        fig.canvas.draw_idle()

    def set_speed(label):
        comm.write(f"M{('Realtime', 'Training', 'Xenon').index(label.split()[0])}\n")

    def set_plant(label):
        mode = ("PWR-SMR", "RBMK-like", "TMI-loss").index(label)
        state["plant"] = mode
        core.set_plant(mode)
        drain_queue()
        clear_history()
        set_scram_button_state(False)
        comm.write(f"C{mode}\n")
        fig.canvas.draw_idle()

    def cycle_optional_chart():
        nonlocal optional_index
        optional_index = (optional_index + 1) % len(OPTIONAL_CHARTS)
        active = OPTIONAL_CHARTS[optional_index]
        for chart in charts:
            if chart["spec"]["key"] in OPTIONAL_CHARTS:
                chart["visible"] = chart["spec"]["key"] == active
        layout_charts()

    def on_key(event):
        key = (event.key or "").lower()
        if key == "r":
            scram()
        elif key == "k":
            clear_scram()
        elif key == "p":
            reset_power(power_box.text)
        elif key == "d":
            cycle_optional_chart()
        elif key == "e":
            export_session()
        elif key == "s":
            save_session_as()
        elif key == "l":
            load_session_dialog()
        elif key == "o":
            pick_overlay_file()
        elif key in (" ", "space"):
            set_pause(not state["paused"])
        elif key in ("up", "+", "="):
            comm.write("+\n")
        elif key in ("down", "-", "_"):
            comm.write("-\n")

    rod_slider.on_changed(on_slider)
    scram_btn.on_clicked(lambda event: scram())
    clear_btn.on_clicked(lambda event: clear_scram())
    reset_btn.on_clicked(lambda event: reset_power(power_box.text))
    power_box.on_submit(reset_power)
    source_btn.on_clicked(lambda event: set_source(source_box.text))
    source_box.on_submit(set_source)
    save_btn.on_clicked(lambda event: save_session_as())
    load_btn.on_clicked(lambda event: load_session_dialog())
    overlay_btn.on_clicked(lambda event: pick_overlay_file())
    speed_radio.on_clicked(set_speed)
    plant_radio.on_clicked(set_plant)
    pause_btn.on_clicked(lambda event: set_pause(not state["paused"]))
    for index, btn in enumerate(window_buttons):
        btn.on_clicked(lambda event, i=index: set_window_preset(i))
    fig.canvas.mpl_connect("key_press_event", on_key)
    fig.canvas.mpl_connect("close_event", lambda event: sim_finished.set())

    # Match CLI --window / --plot-mode to a preset highlight when possible.
    if state["window_all"]:
        highlight_window_buttons()
    else:
        matched = False
        for index, (_, seconds) in enumerate(WINDOW_PRESETS):
            if seconds is not None and abs(state["window_seconds"] - seconds) < 0.5:
                set_window_preset(index)
                matched = True
                break
        if not matched:
            highlight_window_buttons()

    # --- Frame update -------------------------------------------------------------
    def update(_frame):
        while True:
            try:
                row = data_queue.get_nowait()
            except queue.Empty:
                break
            t = row["sim_time_s"]
            if history["t"] and t < history["t"][-1]:
                clear_history()
            latest.clear()
            latest.update(row)
            history["t"].append(t)
            thermal = PROMPT_FRACTION * row["n"] + row["decay_heat"]
            row["thermal"] = thermal
            rows_log.append(dict(row))
            for field in SERIES_FIELDS:
                value = thermal if field == "thermal" else row.get(field, NAN)
                if field in ("target_h_s", "step_real_time_s") and math.isfinite(value):
                    value = max(1.0e-9, value)
                history[field].append(value)
            detect_events(row, t)

        if not latest:
            return

        # Always keep SCRAM button / critical tick current even while paused.
        fault = latest["engine_status"] <= 0.0
        scram_active = latest["scram_active"] >= 0.5
        if scram_active != state["scram_ui"]:
            set_scram_button_state(scram_active)

        crit = latest.get("critical_rod_position", NAN)
        if math.isfinite(crit):
            crit_line.set_xdata([crit, crit])
            crit_txt = f"{crit * 100.0:.1f}%"
        else:
            crit_txt = "—"
        crit_label.set_text(f"crit {crit_txt}   target {rod_slider.val * 100.0:.1f}%")

        update_alarms(latest)

        if state["paused"]:
            return

        thermal = PROMPT_FRACTION * latest["n"] + latest["decay_heat"]
        times = history["t"]
        max_t = times[-1]

        if state["window_all"]:
            window_start = 0.0
            window_end = max(INITIAL_X_SECONDS, max_t + 10.0)
            start_index = 0
        else:
            window = state["window_seconds"]
            if max_t <= window:
                window_start = 0.0
                window_end = min(window, max(INITIAL_X_SECONDS, max_t + 10.0))
            else:
                window_start = max_t - window
                window_end = max_t
            start_index = bisect_left(times, window_start)
        visible_times = times[start_index:]

        overlay = state["overlay"]
        for chart in charts:
            if not chart["visible"]:
                continue
            ax = chart["ax"]
            finite = []
            for field, line in chart["lines"].items():
                values = history[field][start_index:]
                line.set_data(visible_times, values)
                finite.extend(v for v in values if math.isfinite(v) and (v > 0 or not chart["spec"].get("log")))
            if overlay is not None:
                artists = chart.setdefault("overlay_artists", {})
                mask = (overlay["t"] >= window_start) & (overlay["t"] <= window_end)
                for spec in chart["spec"]["series"]:
                    field, color = spec[0], spec[2]
                    data = overlay["columns"].get(field)
                    if data is None or not mask.any():
                        continue
                    artist = artists.get(field)
                    if artist is None:
                        artist, = ax.plot([], [], color=color, linestyle=":",
                                          linewidth=1.3, alpha=0.8)
                        artists[field] = artist
                    artist.set_data(overlay["t"][mask], data[mask])
                    finite.extend(v for v in data[mask] if math.isfinite(v) and (v > 0 or not chart["spec"].get("log")))
            ax.set_xlim(window_start, window_end)
            key = chart["spec"]["key"]
            if finite:
                low, high = min(finite), max(finite)
                if key == "power":
                    ax.set_ylim(0.0, max(2.0, high * 1.25))
                elif key == "temp":
                    pad = max(15.0, (high - low) * 0.15)
                    ax.set_ylim(low - pad, high + pad)
                elif key == "rho":
                    pad = max(0.4, (high - low) * 0.3)
                    ax.set_ylim(low - pad, max(high + pad, 1.2))
                elif key == "poison":
                    pad = max(0.05, (high - low) * 0.25)
                    ax.set_ylim(low - pad, high + pad)
                elif key == "components":
                    pad = max(0.15, (high - low) * 0.25)
                    ax.set_ylim(low - pad, high + pad)
                elif key == "timing":
                    ax.set_ylim(low * 0.5, high * 2.0)
            if key == "power":
                chart["value_txt"].set_text(f"N {latest['n']:.4f}   thermal {thermal:.4f}")
            elif key == "temp":
                chart["value_txt"].set_text(f"Tf {latest['Tf']:.1f}   Tc {latest['Tc']:.1f} °C")
            elif key == "rho":
                chart["value_txt"].set_text(f"{latest['rho_dollars']:+.4f} $")
            elif key == "poison":
                chart["value_txt"].set_text(f"I {latest['I_norm']:.3f}   Xe {latest['Xe_norm']:.3f}")
            elif key == "components":
                chart["value_txt"].set_text(
                    f"rod {latest['rho_rod_dollars']:+.2f}  "
                    f"fuel {latest['rho_fuel_dollars']:+.2f}  "
                    f"cool {latest['rho_coolant_dollars']:+.2f}  "
                    f"Xe {latest['rho_xenon_dollars']:+.2f}"
                )
            elif key == "timing" and math.isfinite(latest["step_real_time_s"]):
                chart["value_txt"].set_text(f"real {latest['step_real_time_s']:.2e} s")

        redraw_event_markers(window_start, window_end)

        plant_mode = int(latest["plant_mode"]) if math.isfinite(latest["plant_mode"]) else state["plant"]
        if plant_mode != state["plant"]:
            state["plant"] = plant_mode
            core.set_plant(plant_mode)

        core.update(latest["n"], latest["Tf"], latest["Tc"], latest["rod_position"],
                    scram_active, fault)
        status.update(latest, thermal)

        sim_time = f"{max_t / 3600.0:.2f} h" if max_t >= 7200.0 else f"{max_t:.1f} s"
        factor = latest["achieved_factor"]
        factor_text = f"×{factor:.0f}" if math.isfinite(factor) else "×—"
        reconnecting = isinstance(comm, SerialComm) and not comm.connected
        live_txt.set_text(("NUMERICAL TRIP   " if fault else "")
                          + f"t {sim_time}   {factor_text}"
                          + ("   RECONNECTING…" if reconnecting else ""))
        live_txt.set_color(C_SCRAM if fault else (ACCENT if reconnecting else MUTED))

        target = latest["rod_target"]
        dragging = getattr(rod_slider, "drag_active", False)
        if math.isfinite(target) and not dragging and abs(rod_slider.val - target) > 0.004:
            set_slider(target)

    return {
        "fig": fig,
        "update": update,
        "widgets": widgets,
        "state": state,
        "events": events,
        "history": history,
        "cycle_optional_chart": cycle_optional_chart,
        "export_session": export_session,
        "set_overlay": set_overlay,
        "load_session": load_session,
    }


# ---------------------------------------------------------------------------
# Offline smoke render (development aid)
# ---------------------------------------------------------------------------

def synthetic_row(t, **overrides):
    row = dict(zip(FIELD_NAMES, FIELD_DEFAULTS))
    row.update({
        "sim_time_s": t, "n": 1.0, "Tf": 543.0, "Tc": 293.0, "rho": 0.0,
        "rho_dollars": 0.0, "I_norm": 1.0, "Xe_norm": 1.0, "rho_xe": 0.0,
        "achieved_factor": 1.0, "rod_position": 0.75, "rod_target": 0.75,
        "engine_status": 1.0, "target_h_s": 1.0e-4, "step_real_time_s": 2.0e-6,
        "decay_heat": 0.066, "rho_rod_dollars": 0.02, "rho_fuel_dollars": -0.015,
        "rho_coolant_dollars": -0.004, "rho_xenon_dollars": -0.001,
        "critical_rod_position": 0.75, "plant_mode": 0.0, "scram_active": 0.0,
    })
    row.update(overrides)
    return row


def run_smoke(dashboard, output_path):
    for frame in range(900):
        t = frame * 0.1
        if t < 15.0:
            row = synthetic_row(t)
        else:
            rise = 1.0 - math.exp(-(t - 15.0) / 12.0)
            n = 1.0 + 0.32 * rise
            row = synthetic_row(
                t, n=n, Tf=543.0 + 55.0 * (n - 1.0), Tc=293.0 + 9.0 * (n - 1.0),
                rho_dollars=0.22 * math.exp(-(t - 15.0) / 9.0),
                rod_position=min(0.80, 0.75 + 0.01 * (t - 15.0)), rod_target=0.80,
                I_norm=1.0 + 0.004 * (t / 90.0), Xe_norm=1.0 - 0.006 * (t / 90.0),
                rho_rod_dollars=0.09, rho_fuel_dollars=-0.055,
                rho_coolant_dollars=-0.012, rho_xenon_dollars=0.004,
                critical_rod_position=0.72 + 0.04 * rise,
            )
        data_queue.put(row)
    dashboard["update"](0)
    dashboard["fig"].savefig(output_path, dpi=115, facecolor=BG)
    log(f"Smoke render written to {output_path}")

    for frame in range(400):
        t = 90.0 + frame * 0.1
        decay = math.exp(-(t - 90.0) / 1.2)
        row = synthetic_row(
            t, n=1.32 * decay + 0.015, Tf=543.0 - 120.0 * (1.0 - decay),
            Tc=293.0 - 6.0 * (1.0 - decay), rho_dollars=-10.9,
            rod_position=max(0.0, 0.80 - 0.05 * (t - 90.0)), rod_target=0.0,
            scram_active=1.0, decay_heat=0.055,
            rho_rod_dollars=-2.7, rho_fuel_dollars=0.35,
            rho_coolant_dollars=0.02, rho_xenon_dollars=-0.01,
            critical_rod_position=0.90,
        )
        data_queue.put(row)
    dashboard["update"](0)
    scram_path = output_path.replace(".png", "_scram.png")
    dashboard["fig"].savefig(scram_path, dpi=115, facecolor=BG)
    log(f"SCRAM smoke render written to {scram_path}")

    dashboard["cycle_optional_chart"]()  # poison -> components
    dashboard["update"](0)
    components_path = output_path.replace(".png", "_components.png")
    dashboard["fig"].savefig(components_path, dpi=115, facecolor=BG)
    log(f"Components smoke render written to {components_path}")

    # Addition-3 regression: capture round-trip and reference overlay.
    smoke_dir = os.path.dirname(output_path)
    csv_path = dashboard["export_session"](dest=smoke_dir)
    if not csv_path:
        raise AssertionError("smoke capture produced no CSV")
    reference = load_overlay_csv(csv_path)
    assert reference is not None and len(reference["t"]) == 1300, "overlay load lost rows"
    assert "n" in reference["columns"], "overlay missing power column"
    dashboard["set_overlay"](reference)
    dashboard["update"](0)
    compare_path = output_path.replace(".png", "_compare.png")
    dashboard["fig"].savefig(compare_path, dpi=115, facecolor=BG)
    log(f"Overlay comparison render written to {compare_path}")
    alarm_rows = [synthetic_row(5.0, rho_dollars=0.5), synthetic_row(6.0, rho_dollars=1.2, Tf=850.0)]
    for row in alarm_rows:
        data_queue.put(row)
    dashboard["update"](0)
    assert dashboard["state"]["alarms"], "threshold alarms did not fire"
    log(f"Alarms fired as designed: {sorted(dashboard['state']['alarms'])}")
    dashboard["set_overlay"](None)
    dashboard["update"](0)

    # Save/load round trip: restore the captured session into the dashboard.
    dashboard["load_session"](csv_path)
    assert len(dashboard["history"]["t"]) == 1300, "load_session lost rows"
    assert dashboard["state"]["paused"], "loaded session must open paused"
    assert "SCRAM" in {event["kind"] for event in dashboard["events"]}, \
        "load_session did not reconstruct SCRAM markers"
    log("Loaded session reconstructed history and SCRAM marker")
    log("Smoke addition-3 checks passed")


# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Real-Time Reactor Dashboard")
    parser.add_argument("--source", choices=("serial", "stdout"), default="serial",
                        help="Input source: serial reads COM/UART, stdout reads CSV lines piped from a process")
    parser.add_argument("--port", default="COM7", help="Serial port (COMx or /dev/ttyUSBx)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--power", type=float, default=1.0, help="Initial power fraction")
    parser.add_argument("--plot-mode", choices=("sliding", "full"), default="sliding",
                        help="Plot range mode: sliding grows until the window size, full shows all history")
    parser.add_argument("--window", type=parse_duration, default=DEFAULT_WINDOW_SECONDS,
                        help="Sliding window size in simulation seconds, e.g. 21600, 30m, or 6h")
    parser.add_argument("--smoke", metavar="PNG", help=argparse.SUPPRESS)
    return parser.parse_args()


def main():
    args = parse_args()
    sim_finished.clear()

    if args.smoke:
        comm = DummyComm()
    elif args.source == "serial":
        comm = SerialComm(args.port, args.baud)
    else:
        comm = StdinComm()

    try:
        comm.open()
    except Exception as exc:
        if isinstance(comm, SerialComm):
            log(f"[SerialComm] {exc}")
            log("[SerialComm] Dashboard will keep retrying in the background.")
        else:
            log(f"Error opening connection: {exc}")
            return

    if args.power != 1.0 and not args.smoke:
        comm.write(f"P {args.power}\n")

    dashboard = build_dashboard(args, comm)

    if args.smoke:
        run_smoke(dashboard, args.smoke)
        return

    thread = threading.Thread(target=reader_thread, args=(comm,), daemon=True)
    thread.start()

    animation = FuncAnimation(dashboard["fig"], dashboard["update"], interval=50,
                              blit=False, cache_frame_data=False)

    log("\n=== Real-Time Reactor Dashboard ===")
    log(f"Source: {args.source.upper()}")
    if args.source == "serial":
        log(f"Port: {args.port} @ {args.baud}")
    log("\nControls:")
    log("  [R]       SCRAM")
    log("  [K]       Clear SCRAM")
    log("  [P]       Reset at the power in the box")
    log("  [Space]   Pause / resume display")
    log("  [D]       Cycle poison / ρ components / step-time chart")
    log("  [E]       Quick-capture session CSV + snapshot to captures/")
    log("  [S]       Save session as... (choose file)")
    log("  [L]       Load a saved session (paused review view)")
    log("  [O]       Overlay a saved session as reference traces")
    log("  [Up/+]    Withdraw rod target 1%")
    log("  [Down/-]  Insert rod target 1%")
    plt.show()

    _ = animation
    sim_finished.set()
    comm.close()


if __name__ == "__main__":
    main()
