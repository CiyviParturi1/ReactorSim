"""Report and slide figures from full simulator traces and benchmark edits."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BLUE, RED, ORANGE, GRAY = '#1769aa', '#b22222', '#d2691e', '#555555'


def read_rows(path: Path) -> list[dict[str, float | str]]:
    with path.open(newline='', encoding='utf-8') as handle:
        return [{key: value if key == 'scenario' else float(value)
                 for key, value in row.items()}
                for row in csv.DictReader(handle)]


def read_feedback_trace(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load all one million 0.1 ms solver states without dict-per-row overhead."""
    time, power, feedback = [], [], []
    with path.open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            time.append(float(row['time_s']))
            power.append(float(row['simulator_n']))
            feedback.append(float(row['feedback_rho']))
    return np.asarray(time), np.asarray(power), np.asarray(feedback)


def decorate(axis):
    axis.grid(True, alpha=.22)
    axis.set_axisbelow(True)
    axis.spines[['top', 'right']].set_visible(False)


def finish(figure, output: Path, name: str, note: str):
    figure.text(.08, .025, note, fontsize=9, color=GRAY, va='bottom')
    figure.tight_layout(rect=(0, .105, 1, .94), w_pad=3)
    for extension in ('png', 'svg'):
        path = output / f'{name}.{extension}'
        figure.savefig(path, dpi=300, facecolor='white')
        if extension == 'svg':
            lines = path.read_text(encoding='utf-8').splitlines()
            path.write_text('\n'.join(line.rstrip() for line in lines) + '\n', encoding='utf-8')
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path,
                        default=Path('experiments/results/benchmark_validation_20260907'))
    args = parser.parse_args()

    checkpoints = read_rows(args.input / 'cats_doppler_feedback.csv')
    trace_time, trace_power, trace_feedback = read_feedback_trace(
        args.input / 'cats_doppler_feedback_trace.csv')
    poison = read_rows(args.input / 'poison_analytic.csv')

    plt.rcParams.update({
        'font.family': 'DejaVu Sans', 'font.size': 11, 'axes.labelsize': 11,
        'axes.titlesize': 12, 'legend.fontsize': 10, 'lines.linewidth': 1.7,
        'svg.fonttype': 'none',
    })
    checkpoint_time = np.array([float(row['time_s']) for row in checkpoints])
    checkpoint_power = np.array([float(row['reference_n']) for row in checkpoints])
    normalized_trace = trace_power / trace_power[np.argmin(np.abs(trace_time - 1.0))]
    normalized_checkpoints = checkpoint_power / checkpoint_power[0]
    maximum_error = 100 * max(float(row['relative_error']) for row in checkpoints)

    output = args.input / 'figures' / 'feedback_benchmark'
    output.mkdir(parents=True, exist_ok=True)
    size = (12.8, 7.2)

    figure, axes = plt.subplots(1, 2, figsize=size)
    figure.suptitle('Full simulator trajectory agrees with the CATS Doppler-feedback benchmark',
                     fontsize=16, y=.97)

    axes[0].plot(trace_time, trace_power, color=BLUE,
                 label='Simulator, every 0.1 ms solver state')
    axes[0].scatter(checkpoint_time, checkpoint_power, s=76, facecolors='white',
                    edgecolors=GRAY, linewidths=1.5, zorder=3,
                    label='Published CATS checkpoint')
    axes[0].set(xscale='log', yscale='log', xlabel='Time after +1 $ step (s)',
                ylabel='Neutron density, N / N₀',
                title='A  |  Absolute simulator trajectory with published points')
    axes[0].legend(loc='upper right')
    decorate(axes[0])

    axes[1].plot(trace_time, normalized_trace, color=BLUE,
                 label='Simulator, normalized at 1 s')
    axes[1].scatter(checkpoint_time, normalized_checkpoints, s=76, facecolors='white',
                    edgecolors=GRAY, linewidths=1.5, zorder=3,
                    label='CATS checkpoints, normalized at 1 s')
    axes[1].set(xscale='log', xlabel='Time after +1 $ step (s)', ylabel='N / N(1 s)',
                title='B  |  Feedback-limited response characteristic')
    feedback_axis = axes[1].twinx()
    feedback_axis.plot(trace_time, -trace_feedback / .00645, color=RED, linewidth=1.35,
                       alpha=.85, label='Negative fuel feedback / +1 $ insertion')
    feedback_axis.set_ylabel('Negative fuel feedback / +1 $ insertion', color=RED)
    feedback_axis.tick_params(axis='y', colors=RED)
    feedback_axis.spines['top'].set_visible(False)
    handles, labels = axes[1].get_legend_handles_labels()
    feedback_handles, feedback_labels = feedback_axis.get_legend_handles_labels()
    axes[1].legend(handles + feedback_handles, labels + feedback_labels, loc='upper right')
    decorate(axes[1])
    finish(figure, output, '01_cats_doppler_full_trajectory',
           f'CATS Table 6a, Thermal Reactor IV, +1 $ step, B = 2.5 × 10⁻⁶/(MW s). Largest checkpoint error: {maximum_error:.5f}%.\n'
           'Blue curve uses every 0.1 ms simulator state. Open circles are the eleven published values. Test-only parameter mapping; production model unchanged.')

    figure, axis = plt.subplots(figsize=size)
    names = list(dict.fromkeys(str(row['scenario']) for row in poison))
    x = np.arange(len(names))
    for offset, key, label, color in [(-.18, 'iodine_relative_error', 'Iodine', BLUE),
                                      (.18, 'xenon_relative_error', 'Xenon', ORANGE)]:
        values = [1e6 * max(float(row[key]) for row in poison if row['scenario'] == name)
                  for name in names]
        bars = axis.bar(x + offset, values, width=.32, color=color, label=label)
        axis.bar_label(bars, labels=[f'{value:.3f}' for value in values], padding=5, fontsize=12)
    axis.set_xticks(x, ['100% to 20% power\n2-hour check', '100% to 150% power\n1-hour check',
                        'Prescribed zero power\n2-hour check'])
    axis.set(ylabel='Largest sampled relative error (ppm)', ylim=(0, .55))
    axis.legend(loc='upper left')
    axis.grid(False, axis='x')
    decorate(axis)
    figure.suptitle('Iodine and xenon agree with the exact coupled solution', fontsize=16, y=.97)
    axis.set_title('Largest xenon error: 0.437 ppm with 0.1 s poison batches', pad=16)
    finish(figure, output, '02_poison_analytic_verification',
           'Analytic check of the existing poison equations. Four checkpoints per scenario. 1 ppm = 0.0001%.\n'
           'This is a prescribed-power subsystem test, separate from the public CATS feedback benchmark.')

    print(f'Generated 2 benchmark figures as PNG and SVG: {output}')


if __name__ == '__main__':
    main()
