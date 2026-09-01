# Nanopredict

Nanopredict is a local browser dashboard for calibrated early prediction of
Oxford Nanopore MinION run yield. It connects read-only to MinKNOW, adapts to
the capabilities exposed by the installed Core version, and predicts final
passed yield at 30, 60, and 120 minutes when the required statistics are
available. A version-independent BAM fallback and an anonymous historical
replay mode are included.

> **Research-use prototype:** prospective validation is required. Predictions
> and suspected-problem flags must not replace MinKNOW QC or operator judgement.

## Install from PyPI

Requirements: MinKNOW and 64-bit Python 3.9–3.12 on the sequencing computer.

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

For an editable checkout, Git is also required. The fully validated live
collector targets Core 6.10.12 and MinION; other Core generations are detected
and handled as described below.

```powershell
git clone https://github.com/AlexanderM-M/nanopredict.git
cd nanopredict
py -m pip install .
nanopredict
```

The installation command is required once because cloning a repository cannot
register a shell command or install Python dependencies. Every later launch is:

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
- One selectable overview of every active MinION position
- Live NanoDx classifier CpGs and progress toward the institute threshold of 180
- Recent CpG accumulation rate and estimated time to the 180-CpG threshold

Replay mode contains 513 snapshots from 171 complete MinION runs. Its table
contains only anonymous `SampleN` labels, the numerical model inputs, and the
historical outcome. It contains no report paths, original run identifiers,
device serials, names, or N-numbers.

## Live collector and safety

The package includes `minknow_api` 6.10.3 as its validated baseline. Oxford
Nanopore recommends matching the first two client-version components to Core,
and notes that RPCs may change between minor versions. Nanopredict therefore
checks capabilities instead of rejecting another version immediately, makes
optional statistics non-fatal, and falls back to completed BAM batches when the
essential API counters are incompatible. The validated collector reads
acquisition output, basecall boxplots, duty time, temperature, basecaller
settings, and pore-scan results.

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

### MinKNOW version compatibility

Nanopredict chooses the best available read-only path automatically:

- **Validated API:** Core 6.10.x with the bundled 6.10 API client. This provides
  live yield, calibrated final-yield predictions, QC features, and CpGs.
- **Compatibility API:** another Core version that still exposes compatible
  acquisition and statistics fields. Nanopredict uses the available fields and
  labels the session as compatibility mode. Because Oxford Nanopore may change
  the API between minor Core releases, this path should be checked locally
  before operational use.
- **BAM fallback:** if the statistics API cannot be read, Nanopredict discovers
  completed `bam_pass` and `bam_fail` batches and continues to display passed
  bases, target progress, yield ETA, NanoDx CpGs, and CpG ETA. A calibrated
  final-yield prediction is not shown in this mode because the trained model
  requires statistics that cannot be reconstructed reliably from BAM alone.

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

By default, every active MinION position is monitored. To deliberately restrict
API monitoring to one position, launch with
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

## License

Nanopredict is free software licensed under the
[GNU General Public License version 3 only](LICENSE). It is distributed without
any warranty. Third-party data provenance and licensing information are listed
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
