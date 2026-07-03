import argparse
import os
import platform
import subprocess
import sys
import threading


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_FILE = os.path.join(BASE_DIR, "taylor_solver.cpp")
PLOTTER_FILE = os.path.join(BASE_DIR, "plot_realtime.py")
COMMAND_PREFIX = "PLOTTER_CMD\t"
DEFAULT_WINDOW = "6h"

if platform.system() == "Windows":
    EXECUTABLE = os.path.join(BASE_DIR, "taylor_solver.exe")
else:
    EXECUTABLE = os.path.join(BASE_DIR, "taylor_solver")


def compile_solver():
    """Compiles the C++ solver based on the current OS."""
    if not os.path.exists(SOURCE_FILE):
        print(f"[Build] Source not found at: {SOURCE_FILE}", file=sys.stderr)
        return False

    print(f"[Build] Compiling {SOURCE_FILE}...", file=sys.stderr)

    if platform.system() == "Windows":
        cmd = [
            "g++", "-o", EXECUTABLE, SOURCE_FILE, "-std=c++17",
            "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        ]
    else:
        cmd = [
            "g++", "-o", EXECUTABLE, SOURCE_FILE, "-std=c++17", "-pthread",
            "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print("[Build] Compilation successful.", file=sys.stderr)
            return True

        print(f"[Build] Compilation FAILED:\n{result.stderr}", file=sys.stderr)
        if "Permission denied" in result.stderr and platform.system() == "Windows":
            print(
                "[Build] taylor_solver.exe is probably still running. Close the plot/simulator "
                "window or kill the old process, then rerun.",
                file=sys.stderr,
            )
        return False
    except Exception as exc:
        print(f"[Build] Error calling g++: {exc}", file=sys.stderr)
        return False


def relay_solver_stderr(process):
    if not process.stderr:
        return
    for line in process.stderr:
        print(line, file=sys.stderr, end="")


def relay_plotter_stderr(plotter, solver):
    if not plotter.stderr:
        return

    for line in plotter.stderr:
        if line.startswith(COMMAND_PREFIX):
            command = line[len(COMMAND_PREFIX) :].strip()
            if command and solver.stdin and solver.poll() is None:
                try:
                    solver.stdin.write(command + "\n")
                    solver.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
        else:
            print(line, file=sys.stderr, end="")


def parse_args():
    parser = argparse.ArgumentParser(description="PC simulator launcher for the reactor plotter")
    parser.add_argument("--power", type=float, default=1.0, help="Initial power fraction")
    parser.add_argument("--skip-build", action="store_true", help="Skip C++ compilation")
    parser.add_argument("--plotter", default=PLOTTER_FILE, help="Path to plot_realtime.py")
    parser.add_argument("--executable", default=EXECUTABLE, help="Path to the solver executable")
    parser.add_argument(
        "--plot-mode",
        choices=("sliding", "full"),
        default="sliding",
        help="Plot range mode passed to the plotter",
    )
    parser.add_argument(
        "--window",
        default=DEFAULT_WINDOW,
        help="Sliding window size passed to the plotter, e.g. 21600, 30m, or 6h",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.skip_build and not compile_solver():
        print("Aborting: build failed; refusing to run a stale executable.", file=sys.stderr)
        return 1

    if not os.path.exists(args.executable):
        print(f"Executable not found: {args.executable}", file=sys.stderr)
        return 1
    if not os.path.exists(args.plotter):
        print(f"Plotter not found: {args.plotter}", file=sys.stderr)
        return 1

    print("\n=== Real-Time Reactor PC Launcher ===", file=sys.stderr)
    print(f"Solver:  {args.executable}", file=sys.stderr)
    print(f"Plotter: {args.plotter}", file=sys.stderr)

    solver = subprocess.Popen(
        [args.executable],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    plotter_cmd = [
        sys.executable,
        args.plotter,
        "--source",
        "stdout",
        "--power",
        f"{args.power}",
        "--plot-mode",
        args.plot_mode,
        "--window",
        args.window,
    ]
    plotter = subprocess.Popen(
        plotter_cmd,
        stdin=solver.stdout,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    if solver.stdout:
        solver.stdout.close()

    threads = [
        threading.Thread(target=relay_solver_stderr, args=(solver,), daemon=True),
        threading.Thread(target=relay_plotter_stderr, args=(plotter, solver), daemon=True),
    ]
    for thread in threads:
        thread.start()

    try:
        return_code = plotter.wait()
    except KeyboardInterrupt:
        return_code = 130
    finally:
        if plotter.poll() is None:
            plotter.terminate()
        if solver.poll() is None:
            solver.terminate()
        try:
            if solver.stdin:
                solver.stdin.close()
        except OSError:
            pass

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
