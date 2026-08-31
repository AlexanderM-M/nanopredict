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

Replay mode contains 513 snapshots from 171 complete MinION runs. Its table
contains only anonymous `SampleN` labels, the numerical model inputs, and the
historical outcome. It contains no report paths, original run identifiers,
device serials, names, or N-numbers.

## Live collector and safety

The package pins `minknow_api` 6.10.3 because the first two client version
components must match MinKNOW Core 6.10. The collector auto-detects an active
MinION, verifies the Core version, and reads acquisition output, basecall
boxplots, duty time, temperature, basecaller settings, and pore-scan results.

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
