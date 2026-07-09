import argparse
import math
import queue
import sys
import threading
from bisect import bisect_left
from itertools import chain

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button, RadioButtons, TextBox


COMMAND_PREFIX = "PLOTTER_CMD\t"
DEFAULT_WINDOW_SECONDS = 6 * 3600.0
INITIAL_X_SECONDS = 30.0


def log(message):
    print(message, file=sys.stderr, flush=True)


def parse_duration(value):
    text = str(value).strip().lower()
    units = (
        ("seconds", 1.0),
        ("second", 1.0),
        ("secs", 1.0),
        ("sec", 1.0),
        ("s", 1.0),
        ("minutes", 60.0),
        ("minute", 60.0),
        ("mins", 60.0),
        ("min", 60.0),
        ("m", 60.0),
        ("hours", 3600.0),
        ("hour", 3600.0),
        ("hrs", 3600.0),
        ("hr", 3600.0),
        ("h", 3600.0),
    )

    multiplier = 1.0
    for suffix, unit_multiplier in units:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            multiplier = unit_multiplier
            break

    try:
        duration = float(text) * multiplier
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "duration must be a number, optionally followed by s, m, or h"
        ) from exc

    if duration <= 0:
        raise argparse.ArgumentTypeError("duration must be greater than zero")
    return duration


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
    """Wrapper for PySerial to communicate with the FPGA/UART."""

    def __init__(self, port="COM7", baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None

    def open(self):
        try:
            import serial
        except ImportError as exc:
            raise ImportError("pyserial not installed. Run 'pip install pyserial'") from exc

        self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
        log(f"[SerialComm] Opened port {self.port} at {self.baudrate} baud")

    def read_line(self):
        if self.ser and self.ser.is_open:
            try:
                return self.ser.readline().decode("utf-8", errors="ignore")
            except Exception as exc:
                log(f"Serial read error: {exc}")
        return ""

    def write(self, data):
        if self.ser:
            try:
                self.ser.write(data.encode("utf-8"))
            except Exception as exc:
                log(f"Serial write error: {exc}")

    def close(self):
        if self.ser:
            self.ser.close()
            log("[SerialComm] Port closed.")


data_queue = queue.Queue()
sim_finished = threading.Event()


def reader_thread(comm):
    """Reads data from the selected communication interface."""
    log("Reader thread started.")

    def value(parts, index, default=None):
        if len(parts) <= index:
            return default
        text = parts[index].strip()
        if not text:
            return default
        return float(text)

    while not sim_finished.is_set():
        line = comm.read_line()
        if not line:
            if isinstance(comm, StdinComm):
                break
            continue

        line = line.strip()
        if not line or "," not in line or "DATA_START" in line:
            continue

        try:
            parts = line.split(",")
            if len(parts) >= 5:
                data_queue.put(
                    (
                        value(parts, 0),  # time
                        value(parts, 1),  # power
                        value(parts, 2),  # fuel temperature
                        value(parts, 3),  # rho
                        value(parts, 4),  # dollars
                        value(parts, 5),  # coolant temperature
                        value(parts, 6),  # iodine
                        value(parts, 7),  # xenon
                        value(parts, 8),  # xenon reactivity
                        value(parts, 9),  # time compression factor
                        value(parts, 10),  # rod position
                        value(parts, 11),  # rod target
                        value(parts, 12),  # engine order
                        value(parts, 13),  # target h
                        value(parts, 14),  # real step time
                        value(parts, 15, 0.0),  # decay heat
                        value(parts, 16, 0.0),  # plant mode
                        value(parts, 17, float("nan")),  # rho_rod_dlr
                        value(parts, 18, float("nan")),  # rho_fuel_dlr
                        value(parts, 19, float("nan")),  # rho_coolant_dlr
                        value(parts, 20, float("nan")),  # rho_xenon_dlr
                        value(parts, 21, 0.75),  # rod_critical
                        value(parts, 22, 0.0),   # scram_active
                    )
                )
        except ValueError:
            continue

    log("Reader thread finished.")
    sim_finished.set()


def parse_args():
    parser = argparse.ArgumentParser(description="Real-Time Reactor Plotter")
    parser.add_argument(
        "--source",
        choices=("serial", "stdout"),
        default="serial",
        help="Input source: serial reads COM/UART, stdout reads CSV lines piped from a process",
    )
    parser.add_argument("--port", default="COM7", help="Serial port (COMx or /dev/ttyUSBx)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--power", type=float, default=1.0, help="Initial power fraction")
    parser.add_argument(
        "--plot-mode",
        choices=("sliding", "full"),
        default="sliding",
        help="Plot range mode: sliding grows until the window size, full shows all history",
    )
    parser.add_argument(
        "--window",
        type=parse_duration,
        default=DEFAULT_WINDOW_SECONDS,
        help="Sliding window size in simulation seconds, e.g. 21600, 30m, or 6h",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    source = args.source
    sim_finished.clear()

    if source == "serial":
        comm = SerialComm(args.port, args.baud)
    else:
        comm = StdinComm()

    try:
        comm.open()
    except Exception as exc:
        log(f"Error opening connection: {exc}")
        return

    if args.power != 1.0:
        comm.write(f"P {args.power}\n")

    window_seconds = args.window

    thread = threading.Thread(target=reader_thread, args=(comm,), daemon=True)
    thread.start()

    plt.style.use("dark_background")
    # Matplotlib defaults bind 'r' to reset the plot view; we use R for SCRAM.
    plt.rcParams["keymap.home"] = [k for k in plt.rcParams["keymap.home"] if k.lower() != "r"]
    fig, (ax_power, ax_temp, ax_rho, ax_poison, ax_time) = plt.subplots(
        5, 1, figsize=(11, 10), sharex=True
    )
    fig.suptitle(
        f"Real-Time Reactor Simulation ({source.upper()} Mode)",
        fontsize=13,
        color="white",
        fontweight="bold",
    )
    fig.subplots_adjust(hspace=0.22, top=0.92, bottom=0.08, left=0.10, right=0.65)

    ln_power, = ax_power.plot([], [], color="#FF6B35", lw=2, label="Power (N)")
    ln_thermal, = ax_power.plot(
        [], [], color="#FF9F1C", lw=2, linestyle="--", label="Thermal Power"
    )
    ax_power.set_ylabel("Power")
    ax_power.grid(True, alpha=0.2)
    ax_power.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    ax_power.set_xlim(0, INITIAL_X_SECONDS)
    ax_power.set_ylim(0, 2)

    ln_temp, = ax_temp.plot([], [], color="#00D4FF", lw=2, label="Fuel Temp (°C)")
    ax_temp.set_ylabel("Temperature (°C)")
    ln_coolant, = ax_temp.plot([], [], color="#4ECDC4", lw=2, label="Coolant Temp")
    ax_temp.grid(True, alpha=0.2)
    ax_temp.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    ax_temp.set_ylim(280, 700)

    ln_rho, = ax_rho.plot([], [], color="#7CFC00", lw=2, label="Reactivity ($)")
    ax_rho.axhline(y=1.0, color="red", linestyle="--", alpha=0.5, label="Prompt Critical")
    ax_rho.set_ylabel("Reactivity ($)")
    ax_rho.grid(True, alpha=0.2)
    ax_rho.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    ax_rho.set_ylim(-0.5, 1.5)

    ln_iodine, = ax_poison.plot([], [], color="#FFD166", lw=2, label="I-135 / I0")
    ln_xenon, = ax_poison.plot([], [], color="#B388FF", lw=2, label="Xe-135 / Xe0")
    ax_poison.set_ylabel("Poison ratio")
    ax_poison.grid(True, alpha=0.2)
    ax_poison.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    ax_poison.set_ylim(0.5, 1.5)

    ln_target_h, = ax_time.plot([], [], color="#E040FB", lw=2, label="Target step ($h$)")
    ln_real_time, = ax_time.plot([], [], color="#00E5FF", lw=2, label="Real step time")
    ax_time.set_ylabel("Step time (s)")
    ax_time.set_xlabel("Time (s)")
    ax_time.grid(True, alpha=0.2)
    ax_time.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    ax_time.set_yscale("log")
    ax_time.set_ylim(1e-8, 1e-1)

    rod_txt = ax_power.text(
        0.02,
        0.85,
        "Rods: all inserted",
        transform=ax_power.transAxes,
        color="lime",
        fontsize=10,
        fontweight="bold",
        bbox=dict(boxstyle="round", facecolor="black", alpha=0.7),
    )
    rod_pos_txt = ax_power.text(
        0.02,
        0.72,
        "",
        transform=ax_power.transAxes,
        color="yellow",
        fontsize=9,
        fontweight="bold",
        bbox=dict(boxstyle="round", facecolor="black", alpha=0.7),
    )
    plant_txt = ax_power.text(
        0.02,
        0.59,
        "Plant: PWR-SMR Passive Safe",
        transform=ax_power.transAxes,
        color="#00D4FF",
        fontsize=9,
        fontweight="bold",
        bbox=dict(boxstyle="round", facecolor="black", alpha=0.7),
    )
    time_txt = ax_power.text(
        0.50,
        0.94,
        "1x  sim:0.0s",
        transform=ax_power.transAxes,
        color="cyan",
        fontsize=9,
        ha="center",
        fontweight="bold",
        bbox=dict(boxstyle="round", facecolor="black", alpha=0.5),
    )

    val_power_txt = ax_power.text(
        1.0, 1.02, "", transform=ax_power.transAxes, color="#FF6B35", ha="right", va="bottom",
        fontweight="bold", fontsize=9
    )
    val_temp_txt = ax_temp.text(
        1.0, 1.02, "", transform=ax_temp.transAxes, color="#00D4FF", ha="right", va="bottom",
        fontweight="bold", fontsize=9
    )
    val_rho_txt = ax_rho.text(
        1.0, 1.02, "", transform=ax_rho.transAxes, color="#7CFC00", ha="right", va="bottom",
        fontweight="bold", fontsize=9
    )
    val_poison_txt = ax_poison.text(
        1.0, 1.02, "", transform=ax_poison.transAxes, color="#B388FF", ha="right", va="bottom",
        fontweight="bold", fontsize=9
    )
    val_time_txt = ax_time.text(
        1.0, 1.02, "", transform=ax_time.transAxes, color="#00E5FF", ha="right", va="bottom",
        fontweight="bold", fontsize=9
    )
    reactivity_txt = ax_rho.text(
        0.02,
        0.05,
        "",
        transform=ax_rho.transAxes,
        color="#7CFC00",
        fontsize=8.5,
        fontweight="bold",
        bbox=dict(boxstyle="round", facecolor="black", alpha=0.75),
    )

    plant_names = {
        0: "PWR-SMR Passive Safe",
        1: "RBMK-like Demonstrator",
        2: "TMI-inspired Cooling Loss",
    }
    plant_colors = {0: "#00D4FF", 1: "#FF6B35", 2: "#FFD166"}

    times = []
    powers = []
    thermal_powers = []
    temps = []
    coolants = []
    rhos_dollars = []
    iodine_ratios = []
    xenon_ratios = []
    target_hs = []
    real_step_times = []
    rhos_rod = []
    rhos_fuel = []
    rhos_coolant = []
    rhos_xenon = []
    critical_rods = []
    rod_position_display = 0.75
    rod_target_display = 0.75
    scram_state_display = False
    active_plant_mode_display = 0

    def update_plant_label():
        name = plant_names.get(active_plant_mode_display, "Unknown")
        plant_txt.set_text(f"Plant: {name}")
        plant_txt.set_color(plant_colors.get(active_plant_mode_display, "#FFFFFF"))

    def update_rod_display(position=None, target=None, scram_active=None):
        nonlocal rod_position_display, rod_target_display, scram_state_display

        if position is not None:
            rod_position_display = position
        if target is not None:
            rod_target_display = target
        if scram_active is not None:
            scram_state_display = bool(scram_active)

        if scram_state_display:
            rod_txt.set_text("SCRAM ACTIVE\nTrip reset required before restart")
            rod_txt.set_color("yellow")
        elif rod_position_display == 0.0 and rod_target_display == 0.0:
            rod_txt.set_text("SCRAM CLEARED\nWithdraw rods to restart")
            rod_txt.set_color("cyan")
        else:
            rod_txt.set_text(f"Rod target: {rod_target_display * 100:.1f}% withdrawn")
            rod_txt.set_color("red")
        rod_pos_txt.set_text(f"Rod pos: {rod_position_display * 100:.1f}%")

    update_rod_display()

    def drain_data_queue():
        while True:
            try:
                data_queue.get_nowait()
            except queue.Empty:
                break

    def clear_plot_data():
        times.clear()
        powers.clear()
        thermal_powers.clear()
        temps.clear()
        coolants.clear()
        rhos_dollars.clear()
        iodine_ratios.clear()
        xenon_ratios.clear()
        target_hs.clear()
        real_step_times.clear()
        rhos_rod.clear()
        rhos_fuel.clear()
        rhos_coolant.clear()
        rhos_xenon.clear()
        critical_rods.clear()
        update_plant_label()

        for line in (
            ln_power,
            ln_thermal,
            ln_temp,
            ln_coolant,
            ln_rho,
            ln_iodine,
            ln_xenon,
            ln_target_h,
            ln_real_time,
        ):
            line.set_data([], [])
        for txt in (val_power_txt, val_temp_txt, val_rho_txt, val_poison_txt, val_time_txt, reactivity_txt):
            txt.set_text("")
        ax_power.set_xlim(0, INITIAL_X_SECONDS)
        ax_power.set_ylim(0, 2)
        ax_temp.set_xlim(0, INITIAL_X_SECONDS)
        ax_temp.set_ylim(280, 700)
        ax_rho.set_xlim(0, INITIAL_X_SECONDS)
        ax_rho.set_ylim(-0.5, 1.5)
        ax_poison.set_xlim(0, INITIAL_X_SECONDS)
        ax_poison.set_ylim(0.5, 1.5)
        ax_time.set_xlim(0, INITIAL_X_SECONDS)
        ax_time.set_ylim(1e-8, 1e-1)

    def reset_power(power_fraction):
        drain_data_queue()
        clear_plot_data()
        comm.write(f"P {power_fraction}\n")
        fig.canvas.draw_idle()

    def scram():
        comm.write("R\n")
        update_rod_display(position=0.0, target=0.0, scram_active=1.0)

    def clear_scram():
        comm.write("K\n")
        update_rod_display(scram_active=0.0)

    def set_rod_target(value):
        try:
            target = max(0.0, min(1.0, float(value)))
        except ValueError:
            return
        comm.write(f"W {target}\n")
        update_rod_display(target=target)

    def move_rod_target(delta):
        comm.write("+\n" if delta > 0 else "-\n")

    def on_key(event):
        key = event.key
        try:
            if key in ("r", "R"):
                scram()
            elif key in ("k", "K"):
                clear_scram()
            elif key in ("p", "P"):
                reset_power(power_box.text)
            elif key in ("up", "+", "="):
                move_rod_target(0.01)
            elif key in ("down", "-", "_"):
                move_rod_target(-0.01)
        except Exception:
            pass

    ui_widgets = []

    button_bg = "#263241"
    button_hover = "#344457"
    action_bg = "#1E5E8C"
    action_hover = "#2675AD"
    scram_bg = "#8B1E2D"
    scram_hover = "#B3293C"
    clear_scram_bg = "#1A5F5A"
    clear_scram_hover = "#248780"
    rod_bg = "#5C4A16"
    rod_hover = "#80661D"
    text = "#F2F5F8"
    muted = "#AAB4C0"

    def style_button(button, color=button_bg, hover=button_hover, size=8):
        button.color = color
        button.hovercolor = hover
        button.label.set_color(text)
        button.label.set_fontsize(size)
        button.label.set_fontweight("bold")
        button.ax.set_facecolor(color)
        for spine in button.ax.spines.values():
            spine.set_edgecolor("#4B5563")

    def style_textbox(box, size=8):
        box.ax.set_facecolor(text)
        box.label.set_color(muted)
        box.label.set_fontsize(size)
        box.text_disp.set_color("#000000")
        box.text_disp.set_fontsize(size)
        if hasattr(box, "cursor"):
            box.cursor.set_color("#000000")
        for spine in box.ax.spines.values():
            spine.set_edgecolor("#4B5563")

    def style_radio(radio, size=8):
        radio.ax.set_facecolor("#E9EEF5")
        for label in radio.labels:
            label.set_color("#111827")
            label.set_fontsize(size)
        for spine in radio.ax.spines.values():
            spine.set_edgecolor("#4B5563")

    # Layout configuration helper
    def update_layout():
        left = 0.10
        right = 0.65
        width = right - left
        bottom = 0.08
        top = 0.92
        total_height = top - bottom

        is_time_visible = ax_time.get_visible()

        active_axes = [ax_power, ax_temp, ax_rho, ax_poison]
        if is_time_visible:
            active_axes.append(ax_time)

        N = len(active_axes)
        S = 0.035 if N == 5 else 0.045
        H = (total_height - (N - 1) * S) / N

        for idx, ax in enumerate(active_axes):
            y_bottom = top - (idx + 1) * H - idx * S
            ax.set_position([left, y_bottom, width, H])
            ax.set_visible(True)

            is_bottom = (idx == N - 1)
            ax.tick_params(labelbottom=is_bottom)
            if is_bottom:
                ax.set_xlabel("Time (s)")
            else:
                ax.set_xlabel("")

        if not is_time_visible:
            ax_time.set_visible(False)

        fig.canvas.draw_idle()

    # Define Section Header helper
    def add_section_header(text, y_pos):
        fig.text(
            0.81,
            y_pos,
            text,
            color=muted,
            fontsize=8,
            fontweight="bold",
            ha="left",
            va="bottom",
        )

    # 1. EMERGENCY Section
    add_section_header("SAFETY", 0.895)
    ax_scram_btn = fig.add_axes([0.81, 0.84, 0.16, 0.045])
    scram_btn = Button(ax_scram_btn, "SCRAM")
    style_button(scram_btn, scram_bg, scram_hover, size=9)
    scram_btn.on_clicked(lambda event: scram())
    ui_widgets.append(scram_btn)

    ax_clear_scram_btn = fig.add_axes([0.81, 0.79, 0.16, 0.04])
    clear_scram_btn = Button(ax_clear_scram_btn, "Clear SCRAM")
    style_button(clear_scram_btn, clear_scram_bg, clear_scram_hover, size=9)
    clear_scram_btn.on_clicked(lambda event: clear_scram())
    ui_widgets.append(clear_scram_btn)

    # 2. CONTROL ROD Section
    add_section_header("CONTROL ROD", 0.765)
    ax_rod_target_box = fig.add_axes([0.81, 0.71, 0.16, 0.045])
    rod_target_box = TextBox(ax_rod_target_box, "Rod", initial="0.75")
    style_textbox(rod_target_box)
    ui_widgets.append(rod_target_box)

    ax_rod_target_btn = fig.add_axes([0.81, 0.66, 0.16, 0.04])
    rod_target_btn = Button(ax_rod_target_btn, "Set Rod")
    style_button(rod_target_btn, rod_bg, rod_hover)
    rod_target_btn.on_clicked(lambda event: set_rod_target(rod_target_box.text))
    ui_widgets.append(rod_target_btn)

    ax_withdraw_btn = fig.add_axes([0.81, 0.605, 0.075, 0.04])
    withdraw_btn = Button(ax_withdraw_btn, "Withdraw")
    style_button(withdraw_btn, rod_bg, rod_hover, size=7)
    withdraw_btn.on_clicked(lambda event: move_rod_target(0.01))
    ui_widgets.append(withdraw_btn)

    ax_insert_btn = fig.add_axes([0.895, 0.605, 0.075, 0.04])
    insert_btn = Button(ax_insert_btn, "Insert")
    style_button(insert_btn, rod_bg, rod_hover, size=7)
    insert_btn.on_clicked(lambda event: move_rod_target(-0.01))
    ui_widgets.append(insert_btn)

    # 3. SIM SPEED & dt Section
    add_section_header("SIM SPEED & dt", 0.58)
    ax_mode = fig.add_axes([0.81, 0.45, 0.16, 0.12])
    mode_radio = RadioButtons(ax_mode, ("M0 Real", "M1 Train", "M2 Xenon"), active=0)
    style_radio(mode_radio)

    def set_mode(label):
        if label.startswith("M0"):
            comm.write("M0\n")
        elif label.startswith("M1"):
            comm.write("M1\n")
        elif label.startswith("M2"):
            comm.write("M2\n")

    mode_radio.on_clicked(set_mode)
    ui_widgets.append(mode_radio)

    ax_toggle_btn = fig.add_axes([0.81, 0.40, 0.16, 0.04])
    toggle_btn = Button(ax_toggle_btn, "Show dt Graph")
    style_button(toggle_btn)
    
    def toggle_time_plot(event):
        is_visible = ax_time.get_visible()
        ax_time.set_visible(not is_visible)
        toggle_btn.label.set_text("Hide dt Graph" if not is_visible else "Show dt Graph")
        update_layout()

    toggle_btn.on_clicked(toggle_time_plot)
    ui_widgets.append(toggle_btn)

    # 4. PLANT PRESETS Section
    add_section_header("PLANT PRESETS", 0.37)
    ax_plant = fig.add_axes([0.81, 0.24, 0.16, 0.12])
    plant_radio = RadioButtons(ax_plant, ("PWR-SMR", "RBMK-like", "TMI-loss"), active=0)
    style_radio(plant_radio)

    def set_plant(label):
        nonlocal active_plant_mode_display
        if label == "PWR-SMR":
            comm.write("C0\n")
            active_plant_mode_display = 0
        elif label == "RBMK-like":
            comm.write("C1\n")
            active_plant_mode_display = 1
        elif label == "TMI-loss":
            comm.write("C2\n")
            active_plant_mode_display = 2
        drain_data_queue()
        clear_plot_data()
        fig.canvas.draw_idle()

    plant_radio.on_clicked(set_plant)
    ui_widgets.append(plant_radio)

    # 5. POWER RESET Section
    add_section_header("POWER RESET", 0.20)
    ax_power_box = fig.add_axes([0.81, 0.14, 0.16, 0.045])
    power_box = TextBox(ax_power_box, "Power", initial=f"{args.power:.2f}")
    style_textbox(power_box)
    ui_widgets.append(power_box)

    ax_power_btn = fig.add_axes([0.81, 0.09, 0.16, 0.04])
    power_btn = Button(ax_power_btn, "Reset P")
    style_button(power_btn, action_bg, action_hover)
    power_btn.on_clicked(lambda event: reset_power(power_box.text))
    ui_widgets.append(power_btn)

    # Initialize layout and hide ax_time by default
    ax_time.set_visible(False)
    update_layout()

    fig.canvas.mpl_connect("key_press_event", on_key)

    def update(frame):
        nonlocal active_plant_mode_display

        while not data_queue.empty():
            try:
                parts_tuple = data_queue.get_nowait()
                (
                    t,
                    power,
                    temp,
                    _rho,
                    dollars,
                    coolant,
                    iodine,
                    xenon,
                    _rho_xe,
                    tc_factor,
                    rod_position,
                    rod_target,
                    engine_status,
                    target_h,
                    real_step_time,
                    decay_heat,
                    plant_mode,
                    rho_rod_dlr,
                    rho_fuel_dlr,
                    rho_coolant_dlr,
                    rho_xenon_dlr,
                    rod_critical,
                    scram_active,
                ) = parts_tuple

                if t is not None and times and t < times[-1]:
                    clear_plot_data()

                if plant_mode is not None:
                    active_plant_mode_display = int(plant_mode)
                if decay_heat is None:
                    decay_heat = 0.0

                times.append(t)
                powers.append(power)
                # Grouped decay heat owns 6.6% of equilibrium thermal power.
                thermal_powers.append(0.934 * power + decay_heat)
                temps.append(temp)
                coolants.append(coolant if coolant is not None else float("nan"))
                rhos_dollars.append(dollars)
                target_hs.append(max(1e-9, target_h) if target_h is not None else float("nan"))
                real_step_times.append(
                    max(1e-9, real_step_time) if real_step_time is not None else float("nan")
                )
                rhos_rod.append(rho_rod_dlr)
                rhos_fuel.append(rho_fuel_dlr)
                rhos_coolant.append(rho_coolant_dlr)
                rhos_xenon.append(rho_xenon_dlr)
                critical_rods.append(rod_critical)

                if tc_factor is not None:
                    status_suffix = (
                        "  NUMERICAL TRIP" if engine_status is not None and engine_status <= 0
                        else ""
                    )
                    time_txt.set_text(
                        f"{tc_factor:.0f}x  sim:{t:.1f}s{status_suffix}"
                    )
                if rod_position is not None and rod_target is not None:
                    update_rod_display(position=rod_position, target=rod_target, scram_active=scram_active)
                if iodine is not None and xenon is not None:
                    iodine_ratios.append(iodine)
                    xenon_ratios.append(xenon)
                else:
                    iodine_ratios.append(float("nan"))
                    xenon_ratios.append(float("nan"))
            except queue.Empty:
                break

        if not times:
            return (
                ln_power,
                ln_thermal,
                ln_temp,
                ln_coolant,
                ln_rho,
                ln_iodine,
                ln_xenon,
                ln_target_h,
                ln_real_time,
            )

        update_plant_label()

        max_t = times[-1]
        if args.plot_mode == "sliding":
            if max_t <= window_seconds:
                window_start = 0.0
                window_end = min(window_seconds, max(INITIAL_X_SECONDS, max_t + 10))
            else:
                window_start = max_t - window_seconds
                window_end = max_t
            visible_start = bisect_left(times, window_start)
        else:
            window_start = 0.0
            window_end = max_t + 10 if max_t > ax_power.get_xlim()[1] * 0.9 else ax_power.get_xlim()[1]
            visible_start = 0

        visible_times = times[visible_start:]
        visible_powers = powers[visible_start:]
        visible_thermal_powers = thermal_powers[visible_start:]
        visible_temps = temps[visible_start:]
        visible_coolants = coolants[visible_start:]
        visible_rhos = rhos_dollars[visible_start:]
        visible_iodine_ratios = iodine_ratios[visible_start:]
        visible_xenon_ratios = xenon_ratios[visible_start:]
        visible_target_hs = target_hs[visible_start:]
        visible_real_step_times = real_step_times[visible_start:]

        ln_power.set_data(visible_times, visible_powers)
        ln_thermal.set_data(visible_times, visible_thermal_powers)
        ln_temp.set_data(visible_times, visible_temps)
        ln_coolant.set_data(visible_times, visible_coolants)
        ln_rho.set_data(visible_times, visible_rhos)
        ln_iodine.set_data(visible_times, visible_iodine_ratios)
        ln_xenon.set_data(visible_times, visible_xenon_ratios)
        ln_target_h.set_data(visible_times, visible_target_hs)
        ln_real_time.set_data(visible_times, visible_real_step_times)

        val_power_txt.set_text(f"N: {powers[-1]:.4f}  Thermal: {thermal_powers[-1]:.4f}")
        val_temp_txt.set_text(f"Tf: {temps[-1]:.1f}°C  Tc: {coolants[-1]:.1f}°C")
        val_rho_txt.set_text(f"Rho: {rhos_dollars[-1]:.4f} $")
        if iodine_ratios and math.isfinite(iodine_ratios[-1]):
            val_poison_txt.set_text(f"I: {iodine_ratios[-1]:.3f}  Xe: {xenon_ratios[-1]:.3f}")
        if real_step_times and math.isfinite(real_step_times[-1]):
            val_time_txt.set_text(f"dt_real: {real_step_times[-1]:.2e} s")
        if rhos_rod:
            def component_text(value):
                return f"{value:+.4f} $" if math.isfinite(value) else "N/A"

            reactivity_txt.set_text(
                f"Rho Rod: {component_text(rhos_rod[-1])}\n"
                f"Rho Fuel: {component_text(rhos_fuel[-1])}\n"
                f"Rho Cool: {component_text(rhos_coolant[-1])}\n"
                f"Rho Xe: {component_text(rhos_xenon[-1])}\n"
                f"Rho Total: {rhos_dollars[-1]:+.4f} $\n"
                f"Crit Rod: {critical_rods[-1]*100:.2f}%"
            )

        ax_power.set_xlim(window_start, window_end)
        ax_time.set_xlim(window_start, window_end)

        valid_powers = [v for v in visible_thermal_powers if math.isfinite(v)]
        if valid_powers:
            max_p = max(valid_powers)
            ax_power.set_ylim(0, max(2.0, max_p * 1.3))

        valid_temps = [v for v in chain(visible_temps, visible_coolants) if math.isfinite(v)]
        if valid_temps:
            min_temp = min(valid_temps)
            max_temp = max(valid_temps)
            ax_temp.set_ylim(min_temp - 20, max_temp * 1.1)

        max_d = max(visible_rhos)
        min_d = min(visible_rhos)
        margin = max(0.5, (max_d - min_d) * 0.3)
        ax_rho.set_ylim(min_d - margin, max_d + margin)

        valid_poisons = [
            v for v in chain(visible_iodine_ratios, visible_xenon_ratios) if math.isfinite(v)
        ]
        if valid_poisons:
            max_poison = max(valid_poisons)
            min_poison = min(valid_poisons)
            poison_margin = max(0.05, (max_poison - min_poison) * 0.25)
            ax_poison.set_ylim(min_poison - poison_margin, max_poison + poison_margin)

        valid_times = [
            v
            for v in chain(visible_target_hs, visible_real_step_times)
            if math.isfinite(v) and v > 0
        ]
        if valid_times:
            max_time_val = max(valid_times)
            min_time_val = min(valid_times)
            ax_time.set_ylim(min_time_val * 0.5, max_time_val * 2.0)

        return (
            ln_power,
            ln_thermal,
            ln_temp,
            ln_coolant,
            ln_rho,
            ln_iodine,
            ln_xenon,
            ln_target_h,
            ln_real_time,
        )

    ani = FuncAnimation(fig, update, interval=50, blit=False, cache_frame_data=False)

    log("\n=== Real-Time Reactor Plotter ===")
    log(f"Source: {source.upper()}")
    if source == "serial":
        log(f"Port: {args.port} @ {args.baud}")
    log("\nControls:")
    log("  [Up/+] Withdraw rod target")
    log("  [Down/-] Insert rod target")
    log("  [R]    SCRAM (insert all)")
    log("  [K]    Clear SCRAM (Reset Trip)")
    log("  [P]    Reinitialize at a power fraction")
    plt.show()

    # Keep the animation alive for GUI backends that require a live reference.
    _ = ani
    sim_finished.set()
    comm.close()


if __name__ == "__main__":
    main()
