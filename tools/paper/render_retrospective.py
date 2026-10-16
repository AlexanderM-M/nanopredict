"""Render aggregate retrospective results; never rerun or select predictors."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def read(path):
    with path.open() as handle:
        return list(csv.DictReader(handle))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.results, args.output
    provenance = json.loads((source / 'provenance.json').read_text())
    for name, expected in provenance['output_sha256'].items():
        if digest(source / name) != expected:
            raise ValueError('Results changed: ' + name)
    metrics, paired = read(source / 'metrics.csv'), read(source / 'paired.csv')
    lookup = lambda rows, s, m, h: next(r for r in rows if r['stratum'] == s and r['method'] == m and int(r['horizon_minutes']) == h)
    output.mkdir(parents=True, exist_ok=False)
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                         'pdf.fonttype': 42, 'svg.fonttype': 'none'})
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 7.2), layout='constrained')
    for col, (stratum, title) in enumerate((('all', 'All runs (20 runs, 17 flow-cell groups)'),
                                          ('excluding_configuration_errors', 'Prespecified sensitivity (18 runs, 15 groups)'))):
        ax = axes[0, col]
        for method, label, offset, color in (('bundled', 'NanoPredict', -.12, '#0072B2'),
                                              ('linear_planned', 'Cumulative-rate extrapolation', .12, '#D55E00')):
            rows = [lookup(metrics, stratum, method, h) for h in (30, 60, 120)]
            values = np.array([float(r['mae_gb']) for r in rows])
            low = np.array([float(r['mae_gb_ci_low']) for r in rows])
            high = np.array([float(r['mae_gb_ci_high']) for r in rows])
            ax.errorbar(values, np.arange(3) + offset, xerr=[values-low, high-values],
                        fmt='o', color=color, capsize=3, label=label, markersize=6)
        ax.set(title=('A. ' if col == 0 else 'B. ') + title, xlabel='Mean absolute error (Gb)',
               yticks=range(3), yticklabels=['30 min', '60 min', '120 min'])
        ax.set_ylim(2.5, -.5)
        ax.set_xlim(left=0)
        ax.grid(axis='x', alpha=.2)
        ax = axes[1, col]
        rows = [lookup(paired, stratum, 'bundled', h) for h in (30, 60, 120)]
        values = np.array([float(r['delta_mae_gb']) for r in rows])
        low = np.array([float(r['ci_low']) for r in rows])
        high = np.array([float(r['ci_high']) for r in rows])
        ax.errorbar(values, range(3), xerr=[values-low, high-values], fmt='o', color='#0072B2', capsize=3)
        ax.axvline(0, color='0.45', linestyle='--', linewidth=1)
        ax.set(title=('C. ' if col == 0 else 'D. ') + 'Paired error difference',
               xlabel='MAE(NanoPredict) − MAE(extrapolation), Gb', yticks=range(3),
               yticklabels=['30 min', '60 min', '120 min'])
        ax.set_ylim(2.5, -.5)
        ax.grid(axis='x', alpha=.2)
    fig.suptitle('Retrospective report reconstruction — live accuracy remains unverified', fontsize=13)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='outside lower center', ncol=2, fontsize=9)
    for ext in ('pdf', 'png'):
        fig.savefig(output / ('retrospective_comparison.' + ext), dpi=220)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), layout='constrained')
    for ax, (stratum, title) in zip(axes, (('all', 'All 20 runs'), ('excluding_configuration_errors', 'Sensitivity: 18 runs'))):
        for h, color in ((30, '#0072B2'), (60, '#D55E00'), (120, '#009E73')):
            row = lookup(metrics, stratum, 'bundled', h)
            ax.plot([80, 90, 95], [100*float(row['coverage_'+str(c)]) for c in (80,90,95)],
                    marker='o', label=str(h)+' min', color=color)
        ax.plot([75,100], [75,100], '--', color='0.5', linewidth=1)
        ax.set(title=title, xlabel='Nominal interval coverage (%)', ylabel='Observed coverage (%)',
               xticks=[80,90,95], ylim=(75,102))
        ax.legend(fontsize=8)
        ax.grid(alpha=.2)
    fig.suptitle('Descriptive interval coverage; small-cohort estimates are not calibration guarantees', fontsize=11)
    for ext in ('pdf', 'png'):
        fig.savefig(output / ('retrospective_coverage.' + ext), dpi=220)
    plt.close(fig)
    for name in ('metrics.csv', 'paired.csv', 'probabilities.csv'):
        # Normalize line endings in publication copies, preserving frozen results.
        (output / name).write_bytes((source / name).read_bytes().replace(b'\r\n', b'\n'))
    record = {'scope': provenance['scope'], 'freeze_sha256': provenance['freeze_sha256'],
              'result_provenance_sha256': digest(source / 'provenance.json'),
              'render_script_sha256': digest(Path(__file__)), 'matplotlib': matplotlib.__version__,
              'csv_format': 'LF publication copies; values unchanged from frozen CRLF CSV files',
              'files_sha256': {p.name: digest(p) for p in sorted(output.iterdir())},
              'figure_caption': 'Retrospective reconstruction on report-native inputs. A/C: all 20 runs; B/D: prespecified exclusion of configuration errors S15 and S16. Points and horizontal bars show estimates and 95% percentile intervals from 2000 flow-cell-group bootstrap replicates. Axis ranges differ between panels. Negative paired differences favor NanoPredict. These are not measurements of live availability or prospective accuracy.',
              'coverage_caption': 'Descriptive empirical coverage of unchanged bundled intervals at 30/60/120 minutes, with nominal coverage shown by the diagonal. All-run and prespecified sensitivity estimates are shown separately. Small sample size and report/live feature differences prevent a claim of calibrated live uncertainty.'}
    (output / 'figure_manifest.json').write_text(json.dumps(record, indent=2)+'\n')
    print(output)


if __name__ == '__main__':
    main()
