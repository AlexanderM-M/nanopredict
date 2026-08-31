# Nanopredict

Nanopredict is a local browser dashboard for calibrated early prediction of
Oxford Nanopore MinION run yield. It currently provides accelerated replay of
anonymous historical runs at the validated 30, 60, and 120-minute checkpoints.

> **Research-use prototype:** prospective validation is required. Predictions
> and suspected-problem flags must not replace MinKNOW QC or operator judgement.

## Quick start from a clone

Requirements: Git and 64-bit Python 3.9–3.13.

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
dashboard in the default browser. Closing the browser does not stop monitoring.

```powershell
nanopredict status
nanopredict stop
```

### Zero-setup repository launcher on Windows

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

## What the dashboard shows

- Predicted final passed yield and a calibrated 90% interval
- Probability of reaching an operator-selected yield target
- GOOD, BAD, or UNCERTAIN status with an explanation
- Peer-based suspected QC problems and suggested checks
- Observed passed yield, reads, and temperature
- An accelerated 30/60/120-minute replay timeline

Replay mode contains 513 snapshots from 171 complete MinION runs. Its table
contains only anonymous `SampleN` labels, the numerical model inputs, and the
historical outcome. It contains no report paths, original run identifiers,
device serials, names, or N-numbers.

## MinKNOW target

The planned live collector targets MinKNOW Core 6.4.9 on MinION. ONT's
[`minknow_api` documentation](https://pypi.org/project/minknow-api/) requires
the first two components of the API client and MinKNOW Core versions to match,
so the optional environment uses `minknow_api` 6.4.3.

```powershell
py -m pip install ".[minknow64]"
```

The current release is replay-only. Installing the optional client does not yet
enable live monitoring; the read-only feature collector must first be validated
on the sequencing computer.

## Development

```powershell
py -m pip install --editable .
python -m unittest discover -s tests -v
nanopredict --foreground --no-browser
```

The server uses Python's standard HTTP library and no external web framework.
Models and all dashboard assets are installed inside the Python package.
