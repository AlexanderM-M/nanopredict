# Nanopredict

Nanopredict is a local browser dashboard for calibrated early prediction of
Oxford Nanopore MinION run yield. It connects read-only to MinKNOW Core 6.10,
collects live run statistics, and predicts final passed yield at 30, 60, and
120 minutes. An anonymous historical replay mode is included for testing.

> **Research-use prototype:** prospective validation is required. Predictions
> and suspected-problem flags must not replace MinKNOW QC or operator judgement.

## Quick start from a clone

Requirements: MinKNOW Core 6.10.x, Git, and 64-bit Python 3.9–3.12 on the
sequencing computer. The live collector targets Core 6.10.12 and MinION.

```powershell
git clone https://github.com/AlexanderM-M/nanopredict.git
cd nanopredict
py -m pip install .
nanopredict
```

The installation command is required once because cloning a repository cannot
register a shell command or install Python dependencies. Every later launch is
just:

```powershell
nanopredict
```

Nanopredict starts in the background, binds only to `127.0.0.1`, and opens the
dashboard in the default browser. It waits for an active MinION run and detects
new runs automatically. If several MinION positions are active, it monitors all
of them simultaneously and lists them in the dashboard. Closing the browser does
not stop monitoring.

In the dashboard, enter the desired final passed-yield target and select
**Apply target**. During sequencing, the dashboard continuously displays the
current passed-base count, target progress, remaining bases, recent production
rate, and estimated time to target. The target changes to **TARGET REACHED**
when the live passed yield crosses it. The first final-yield prediction appears
at 30 minutes and is updated at 60 and 120 minutes. Nanopredict may be started
before or after sequencing begins.

The dashboard also follows completed MinKNOW BAM batches and counts covered CpG
features used by the NanoDx Capper classifier. It displays progress toward the
institute-defined threshold of 180 CpGs and changes to **THRESHOLD REACHED** as
soon as that count is reached. This is a local report-readiness indicator, not
a guarantee that ichorCNA or the complete NanoDx report will succeed.

```powershell
nanopredict status
nanopredict stop
```

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
- A live 30/60/120-minute checkpoint timeline
- One selectable overview of every active MinION position
- Live NanoDx classifier CpGs and progress toward the institute threshold of 180
- Recent CpG accumulation rate and estimated time to the 180-CpG threshold

Replay mode contains 513 snapshots from 171 complete MinION runs. Its table
contains only anonymous `SampleN` labels, the numerical model inputs, and the
historical outcome. It contains no report paths, original run identifiers,
device serials, names, or N-numbers.

## Live collector and safety

The package pins `minknow_api` 6.10.3 because the first two client version
components must match MinKNOW Core 6.10. The collector auto-detects an active
MinION, verifies the Core version, and reads acquisition output, basecall
boxplots, duty time, temperature, basecaller settings, and pore-scan results.

### Live NanoDx CpG counter

For CpG counting, configure the MinKNOW sequencing run with all three of the
following:

- BAM output enabled
- Live alignment against the hg38 reference
- A modified-base basecalling model that writes MM and ML tags

Nanopredict detects these settings and shows a direct setup message if BAM
output, alignment, or MM/ML tags are missing. It processes only BAM batches that
MinKNOW has finished writing, so the CpG count updates after each completed BAM
batch in addition to the 20-second scan interval. A BAM batch duration of about
60–120 seconds gives a more responsive display than MinKNOW's longer batching
defaults. The CpG ETA appears after two completed batches show measurable CpG
growth and is recalculated from the recent accumulation rate after every batch.

The bundled target table represents 366,217 of the 366,263 features selected by
the NanoDx `Capper_et_al` model; 46 source features could not be cleanly lifted
from hg19 to hg38. Calls use a NanoDx/modkit-compatible confidence filter and
the same final-27-base edge exclusion. Anonymous incremental state is stored
locally so restarting Nanopredict does not recount completed BAM batches. Before
using the counter operationally, compare its result on at least one completed
local run with NanoDx's reported `num_features`.

It uses only documented getter and statistics-stream RPCs. It contains no code
to start, stop, pause, unblock, change voltage, change temperature, or otherwise
control a run. Run IDs, flow-cell IDs, sample names, and patient identifiers are
not sent to the browser or stored by Nanopredict. MinKNOW position names are
shown only in the local dashboard so an operator can select the correct device;
Nanopredict does not persist or transmit them externally.

By default, every active MinION position is monitored. To deliberately restrict
monitoring to one position, launch with `nanopredict --position POSITION_NAME`.
To show connection errors in the terminal, use `nanopredict --foreground`.

## Development

```powershell
py -m pip install --editable .
python -m unittest discover -s tests -v
nanopredict --foreground --no-browser
```

The server uses Python's standard HTTP library and no external web framework.
Models and all dashboard assets are installed inside the Python package.

## License

Nanopredict is free software licensed under the
[GNU General Public License version 3 only](LICENSE). It is distributed without
any warranty. Third-party data provenance and licensing information are listed
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
