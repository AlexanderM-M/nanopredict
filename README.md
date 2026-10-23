# Nanopredict

Nanopredict is a local browser dashboard for live Oxford Nanopore run
monitoring and calibrated early prediction of MinION yield. It connects
read-only to MinKNOW, adapts to the capabilities exposed by the installed Core
version, and monitors MinION and PromethION sequencing. Calibrated final-yield
prediction at 30, 60, and 120 minutes is currently available for MinION runs.
A version-independent BAM fallback and an anonymous historical replay mode are
included.

> **Research-use prototype:** prospective validation is required. Predictions
> and suspected-problem flags must not replace MinKNOW QC or operator judgement.

## Install from PyPI

The duration-aware 0.11.0 update is available from the GitHub `main` branch.
It has not been published to PyPI; use the clone instructions below for this version.

Requirements: MinKNOW and 64-bit Python 3.9–3.12 on the sequencing computer.
MinION, MinION Mk1C/Mk1D, PromethION, P2 Solo, and P2 Integrated positions are
detected automatically.

```powershell
pip install nanopredict
nanopredict
```

Every later launch is simply `nanopredict`. To install a newer release, run
`pip install --upgrade nanopredict`.

If Windows does not recognize `pip` or `nanopredict`, use the Python launcher:

```powershell
py -m pip install nanopredict
py -m nanopredict
```

## Install from a clone

For an editable checkout, Git is also required. The live collector targets
Core 6.10.12 and MinION; other Core generations are detected and handled as
described below. Automated tests use mocked services and synthetic BAM fixtures;
they do not establish prospective instrument validation.

```powershell
git clone https://github.com/AlexanderM-M/nanopredict.git
cd nanopredict
py -m pip install --editable .
nanopredict
```

The installation command is required once because cloning a repository cannot
register a shell command or install Python dependencies. Every later launch is:

```powershell
nanopredict
```

Nanopredict starts in the background, binds only to `127.0.0.1`, and opens the
dashboard in the default browser. It waits for an active supported run and
detects new runs automatically. If several positions are active, it monitors
all of them simultaneously and lists them in the dashboard. Closing the browser
does not stop monitoring.

In the dashboard, enter the desired final passed-yield target and select
**Apply target**. During sequencing, the dashboard continuously displays the
current passed-base count, target progress, remaining bases, recent production
rate, and estimated time to target. The target changes to **TARGET REACHED**
when the live passed yield crosses it. For MinION, the first final-yield
prediction appears at 30 minutes and is updated at 60 and 120 minutes.
Nanopredict may be started before or after sequencing begins.

For multiplexed runs, select **Sample / barcode** to see that barcode's passed
yield, target progress, and yield ETA. Nanopredict
detects `barcodeNN` and `unclassified` assignments from BAM `BC`/`RG` tags or
standard barcode output directories. Each barcode can have its own target. The
calibrated MinION forecast remains run-level and is deliberately not shown for
an individual barcode.

The **Anonymous run report** panel downloads the current results as structured
JSON or analysis-ready CSV. The report contains yield progress,
target and ETA times, prediction checkpoints, detected problems, barcode
metrics, and software versions. It is generated from an explicit allow-list and
does not contain sample IDs, run IDs, flow-cell IDs, MinKNOW position names, or
filesystem paths. CSV exports contain one run-level row followed by one row per
detected barcode.

```powershell
nanopredict doctor
nanopredict status
nanopredict stop
```

Run `nanopredict doctor` before the first operational use. It checks the Python
and API versions, MinKNOW connection, supported positions, live basecalling,
BAM output, BAM readability, and barcode detection. Alignment is not required
for yield monitoring. For a non-standard output location, use
`nanopredict doctor --bam-dir "D:\data"`. Add `--json` for machine-readable output.

### Repository launcher on Windows

Instead of installing the command, PowerShell users can run:

```powershell
.\nanopredict.cmd
```

On its first invocation, the launcher creates a private environment inside the
clone and installs Nanopredict there. PowerShell requires the `./` or `.\`
prefix for executables in the current directory.

On Linux or macOS, the equivalent self-bootstrapping command is:

```bash
./nanopredict
```

## Test without a sequencing run

Stop an already running dashboard, then launch anonymous replay mode:

```powershell
nanopredict stop
nanopredict --replay
```

The repository launcher accepts the same option: `.\nanopredict.cmd --replay`.

## What the dashboard shows

- Predicted final passed yield and a calibrated 90% interval
- Continuously updated passed bases and target progress
- Remaining bases, recent yield rate, and estimated time to target
- Probability of reaching an operator-selected yield target
- GOOD, BAD, or UNCERTAIN status with an explanation
- Concise peer-based suspected QC problem flags
- Observed passed yield, reads, and temperature
- One selectable overview of every active supported position
- Per-barcode passed yield, target, and yield ETA
- PromethION live yield monitoring without applying the MinION model
- Evidence-backed live problems with a specific corrective action
- Privacy-preserving JSON and CSV run reports

Replay mode contains 513 snapshots from 171 MinION run histories with all three
checkpoints. Its table
contains only anonymous `SampleN` labels, the numerical model inputs, and the
historical outcome. It contains no report paths, original run identifiers,
device serials, names, or N-numbers.

## Live collector and safety

The package includes `minknow_api` 6.10.3 as its compatibility baseline. Oxford
Nanopore recommends matching the first two client-version components to Core,
and notes that RPCs may change between minor versions. Nanopredict therefore
checks capabilities instead of rejecting another version immediately, makes
optional statistics non-fatal, and falls back to completed BAM batches when the
essential API counters are incompatible. The collector reads
acquisition output, basecall boxplots, duty time, temperature, basecaller
settings, and pore-scan results.

### PromethION support

For `PROMETHION`, `P2_SOLO`, and `P2_INTEGRATED` positions, Nanopredict displays
live passed bases, operator-defined target progress, recent yield rate, target
ETA, and completed-BAM monitoring. The calibrated final-
yield card is deliberately disabled: PromethION forecasting has not been
independently validated. Version 0.11.0 bundles the MinION-only duration-aware
models developed on 22 October 2026. Earlier mixed-device model results remain
historical evidence; they do not describe the replacement models. See the
[replacement record](paper/evidence/duration_model_default_replacement/replacement.json)
and [development results](paper/evidence/duration_model_development/summary.json).
Monitoring support does not establish forecast validity.

### Live problem detection

The dashboard reports only problems supported by current run evidence. Checks
cover disabled basecalling/BAM output, an inaccessible output directory, no
completed BAM after 10 minutes, no passed yield after 15 minutes, and a substantial basecalling
backlog. Every problem includes the observed reason and a concrete action. These
rules complement the calibrated peer-based MinION flags; neither is an
automated stop recommendation.

### MinKNOW version compatibility

Nanopredict chooses the best available read-only path automatically:

- **Baseline API** (labelled `validated` internally): Core 6.10.x with the bundled
  6.10 API client. This provides
  live yield for supported devices, plus calibrated final-yield
  predictions for MinION.
- **Compatibility API:** another Core version that still exposes compatible
  acquisition and statistics fields. Nanopredict uses the available fields and
  labels the session as compatibility mode. Because Oxford Nanopore may change
  the API between minor Core releases, this path should be checked locally
  before operational use.
- **BAM fallback:** if the statistics API cannot be read, Nanopredict discovers
  completed `bam_pass` and `bam_fail` batches and continues to display passed
  bases, target progress, and yield ETA. A calibrated
  final-yield prediction is not shown in this mode because the trained model
  requires a reliable planned duration and aligned cumulative counters, which
  this fallback does not supply.

The default BAM locations are detected automatically (`C:\data` on Windows and
`/data` or `~/data` on Linux). If MinKNOW writes elsewhere, supply the directory
when starting Nanopredict:

```powershell
nanopredict --bam-dir "D:\data"
```

Alternatively, set the `NANOPREDICT_BAM_DIR` environment variable. The selected
mode, Core version, and API-client version are shown at the top of the dashboard.
This capability-based approach covers a much wider range of Core releases, but
it does not claim that every past or future undocumented API will provide all
prediction inputs.

It uses only documented getter and statistics-stream RPCs. It contains no code
to start, stop, pause, unblock, change voltage, change temperature, or otherwise
control a run. Run IDs, flow-cell IDs, sample names, and patient identifiers are
not sent to the browser or stored by Nanopredict. MinKNOW position names are
shown only in the local dashboard so an operator can select the correct device;
Nanopredict does not persist or transmit them externally.

By default, every active supported position is monitored. To deliberately
restrict API monitoring to one position, launch with
`nanopredict --position POSITION_NAME`. BAM-only runs have anonymous `BAM-XXXXXX`
labels and remain selectable in the dashboard because BAM output does not
reliably expose the MinKNOW position name. To show connection errors in the
terminal, use `nanopredict --foreground`.

## Development

```powershell
py -m pip install --editable .
python -m unittest discover -s tests -v
nanopredict --foreground --no-browser
```

The server uses Python's standard HTTP library and no external web framework.
Models and all dashboard assets are installed inside the Python package.

### Default duration-aware models (0.11.0)

The 22 October development revision predicts accumulated passed yield plus
production during the remaining configured time. It uses cumulative passed
bases, observation time and planned duration; sampling resolution, recent-rate
missingness and window-local QC values do not enter the model. Missing duration
or invalid counters make the forecast unavailable rather than inventing a run
length. Historical replays with missing duration still show observations and
final yield, with the forecast marked unavailable. A development-selected decay
and rate multiplier can adjust extrapolation.
These assumptions do not predict future interruptions or operator stopping.

The duration-aware artifacts are now the bundled defaults at all three
checkpoints (30, 60 and 120 minutes). A configured three-hour run therefore
produces a forecast for the end of those three hours. Target probabilities use
that same forecast endpoint and historical calibration residuals. Neither uses
an assumed 72-hour duration. Forecasts remain checkpoint snapshots.

Update the whole package: the serialized estimator requires
`nanopredict.duration_model`. Remove any old `NANOPREDICT_MODELS_DIR` override
from your launcher to use the bundled defaults. A new recorder uses the bundled
models automatically; `--models-dir` remains available for explicit selection.

```bash
python -m nanopredict start --source minknow --foreground --no-browser
python -m nanopredict.study init --study /new/qualification/recorder \
  --protocol /path/to/protocol.txt --qualification --predictions-visible
```

Use `--predictions-visible` when a dashboard may expose forecasts. Model files
are validated, copied and hashed before new collection; old freezes must stay
unchanged. The recorder retains the broader feature audit and recent-rate
comparator even though these inputs are excluded from the model.
The bundled artifacts carry their fitting-only comparator constants and separate
development-calibration residuals into the freeze.

Training uses `tools/paper/train_duration.py` with the original feature table,
membership record and `--previous-development` directory. Its grouped selection
and calibration partitions stay separate. Development and post-hoc diagnostic
results do not establish independent accuracy; simple extrapolation remains a
required comparator, especially for short runs.

## Model provenance and paper preparation

The packaged intervals use historical residual calibration; nominal 90% coverage
is not evidence of 90% coverage on future runs. Replay demonstrates software
behaviour and must not be used as independent validation of bundled models.
The original analysis folder `nanoprediction` is not included. An audit,
reproducible exploratory retraining benchmark, feature timing review, validation
protocols and manuscript draft are in [paper/README.md](paper/README.md).
For a frozen, blinded prospective study, use the separate headless recorder
`python -m nanopredict.study --help` and follow the
[operator instructions](paper/operator_instructions.md). This collection path
has simulated fixture coverage; real-device validation remains outstanding.

## License

Nanopredict is free software licensed under the
[GNU General Public License version 3 only](LICENSE). It is distributed without
any warranty.

## Local workspace layout

Use the repository root as the single working checkout. `src/`, `tests/`,
`tools/`, `paper/`, `.github/`, launchers and packaging files belong to the
repository. `datasets/` holds local validation inputs; `archive/` holds historical
transfers and source snapshots. Both are ignored by Git. `paper/archive/` retains
private frozen analyses and the original sequencing-machine qualification package.
These local records are not recreated by a fresh clone. Keep the original
qualification package with any recorder initialized from it; use a fresh freeze
for a future phase using changed source.
