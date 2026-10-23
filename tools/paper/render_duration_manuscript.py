"""Render the diagnostic figure from aggregate data; never fit or score models."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'paper/evidence/manuscript_20261023/figure1_data.csv')
    parser.add_argument('--output', type=Path, default=ROOT / 'paper/evidence/manuscript_20261023')
    args = parser.parse_args()
    rows = list(csv.DictReader(args.data.open()))
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
                         'pdf.fonttype': 42, 'ps.fonttype': 42})
    fig, axes = plt.subplots(1, 2, figsize=(6.7, 2.55), sharey=True)
    methods = [('recorded_previous_mb', 'Earlier model (recorded live)', '#777777', 's', '--'),
               ('duration_posthoc_mb', 'Duration-aware (post hoc)', '#0072B2', 'o', '-'),
               ('cumulative_mb', 'Cumulative extrapolation', '#D55E00', '^', ':')]
    for ax, run in zip(axes, ('A', 'B')):
        subset = sorted((r for r in rows if r['run'] == run), key=lambda r: int(r['checkpoint_minutes']))
        assert [int(r['checkpoint_minutes']) for r in subset] == [30, 60, 120]
        assert len({r['actual_final_mb'] for r in subset}) == 1
        x = [int(r['checkpoint_minutes']) for r in subset]
        for column, label, color, marker, line in methods:
            ax.plot(x, [float(r[column]) for r in subset], label=label,
                    color=color, marker=marker, linestyle=line, linewidth=1.4, markersize=4.5)
        ax.axhline(float(subset[0]['actual_final_mb']), color='#111111', linewidth=1.1,
                   linestyle='-.', label='Actual final yield')
        ax.text(.025, .94, run, transform=ax.transAxes, fontweight='bold', fontsize=11)
        ax.set(xlabel='Checkpoint (min)', xticks=[30, 60, 120], xlim=(20, 130), ylim=(0, 650))
        ax.grid(axis='y', color='#dedede', linewidth=.6)
        ax.set_axisbelow(True)
        ax.spines[['top', 'right']].set_visible(False)
    axes[0].set_ylabel('Final passed yield (Mb)')
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=2, frameon=False, fontsize=8)
    fig.subplots_adjust(left=.10, right=.99, top=.98, bottom=.36, wspace=.13)
    args.output.mkdir(parents=True, exist_ok=True)
    files = []
    for extension in ('pdf', 'png'):
        path = args.output / f'figure1.{extension}'
        fig.savefig(path, dpi=600, facecolor='white')
        files.append(path)
    plt.close(fig)
    record = {'interpretation': 'Two related technical runs; new-model predictions post hoc, not independent validation',
              'matplotlib_version': matplotlib.__version__,
              'data_sha256': hashlib.sha256(args.data.read_bytes()).hexdigest(),
              'renderer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'figure_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (args.output / 'figure_manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Rendered', ', '.join(str(p) for p in files))


if __name__ == '__main__':
    main()
