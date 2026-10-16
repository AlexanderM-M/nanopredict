# Sequencing-machine handoff: qualification first, study separately

**Current status: NOT submission-ready. No study enrollment is authorized by this handoff.** The current cluster work supplies software tests and forecast-validation infrastructure. It supplies no independent yield results or live performance measurements.

## Installation from Git and a run already in progress

Use a separate checkout and virtual environment on the sequencing computer so that the installed older version remains recoverable. Clone the `update/application-note` branch and check out the exact reviewed commit supplied with the handoff. Keep the whole repository: a package-only installation omits the recorder evaluation tools and protocol templates. Record `git rev-parse HEAD` alongside the environment information. A branch update does not publish a PyPI release.

If sequencing is already active, leave acquisition running. Installation and `nanopredict doctor --json` can establish connectivity, but a newly initialized recorder refuses acquisitions that began before its freeze, including in qualification mode. Do not change clocks or restart sequencing to get around that rule. Use the next acquisition for the complete checkpoint qualification after initializing the recorder. Doctor findings about hg38 alignment or modified-base tags are outside the yield-forecast scope and do not justify changing the current run.

## Upcoming Linux MinION run: practical starting sequence

The investigator has confirmed Linux access for an upcoming MinION acquisition. Use the first live acquisition for technical qualification. Its results must not be relabelled as independent prospective validation. The headless recorder captures forecasts and input/timing records without opening a dashboard. A later study phase uses a new freeze/directory after qualification.

Copy the complete reviewed checkout to the sequencing computer. From that checkout, prepare the environment before the acquisition starts:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r paper/environment-freeze.txt
.venv/bin/python -m pip install --editable . --no-deps
.venv/bin/python -m pip check
.venv/bin/nanopredict stop
umask 077
export NP_QUAL_DIR="$HOME/nanopredict-qualification/run-01"
mkdir -p "$NP_QUAL_DIR"
.venv/bin/python -m pip freeze > "$NP_QUAL_DIR/environment.txt"
.venv/bin/nanopredict doctor --json > "$NP_QUAL_DIR/doctor.json"
cp paper/templates/qualification_record.json "$NP_QUAL_DIR/plan.json"
```

Choose a fresh directory, inspect `doctor.json`, and complete `plan.json` with the machine/Core/basecaller information, clock check, qualification designation and operational limits. Check the configured run duration in MinKNOW before starting. A missing Python 3.11 or failed dependency/connection check must be resolved before collection. The `stop` command stops NanoPredict only, not sequencing.

In terminal 1, initialize and start the recorder before sequencing:

```bash
.venv/bin/python -m nanopredict.study init --qualification --study "$NP_QUAL_DIR/recorder" --protocol "$NP_QUAL_DIR/plan.json"
.venv/bin/python -m nanopredict.study collect --study "$NP_QUAL_DIR/recorder"
```

Keep terminal 1 open. Once the sequencing acquisition is active, use terminal 2 in the same checkout. Set `NP_QUAL_DIR` to the same path in this terminal, obtain a group UUID, then substitute it and the actual MinKNOW position name in the enrolment command. Enrol before minute 30:

```bash
export NP_QUAL_DIR="$HOME/nanopredict-qualification/run-01"
.venv/bin/python -m nanopredict.study new-group
.venv/bin/python -m nanopredict.study enroll --study "$NP_QUAL_DIR/recorder" --position POSITION_NAME --group GROUP_UUID --eligibility eligible --reason qualification
.venv/bin/python -m nanopredict.study status --study "$NP_QUAL_DIR/recorder"
```

Keep the recorder active through 120 minutes if the acquisition normally lasts that long. Do not prolong sequencing for the software check. Inspect `status` after each checkpoint; retain late/missing/error states. For a controlled recorder-restart check, restart only `collect` between checkpoints and verify that stored checkpoints remain. Preserve normal sequencing decisions and record the actual ending reason.

After the run and basecalling complete, save the JSON and HTML MinKNOW reports, sequencing summary, final summary and any plan changes alongside the coded qualification record. Export the recorder:

```bash
.venv/bin/python -m nanopredict.study export --study "$NP_QUAL_DIR/recorder" --output "$NP_QUAL_DIR/export.json"
```

Return the coded qualification export, completed plan, environment/doctor records and corresponding run reports through the same private transfer route as the retrospective data. Keep identity crosswalks and the recorder's private key on the sequencing machine. Exact timestamps and the study export are controlled research records, not public anonymous data. Use sections 3–5 below for feature parity, barcode/restart fixtures and measured resource/display timing; this initial recording alone does not complete every qualification test.

## Required files and responsibilities

Transfer the reviewed preparation archive and its SHA-256/file manifest through the site's approved route. Keep the complete extracted checkout, including `tools/paper/evaluate_frozen.py`, `paper/`, tests and packaged assets; the study workflow cannot initialize from a package-only installation. Keep the earlier `0fa3bca` archive as historical evidence, not the updated qualification build. Check the new archive's revision against its manifest and record its hash before extraction.

The site supplies: a supported MinION with live basecalling; authorized local MinKNOW access; a **non-study** acquisition reserved for qualification; immutable completed BAMs and indexes for yield/barcode checks; reconciled final reports and available timestamped MinKNOW statistics; chemistry/basecaller/filter/plan information; and synchronized clocks. Neither hg38 alignment nor modified-base tags are required for yield validation. No files from the unavailable old cluster are required.

Use a private local directory outside the checkout. Examples below use `/private/np-qualification` and assume Linux and a terminal in the extracted checkout. Substitute site-approved paths; Windows operators need equivalent permission and process-monitoring tools. Never commit raw BAMs, clinical reports, private crosswalks, qualification exports or recorder databases. The operator/custodian must name qualification material explicitly before running commands against it. Unknown or reserved evaluation material remains unopened.

## 1. Installation and non-study plan

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r paper/environment-freeze.txt
.venv/bin/python -m pip install --editable . --no-deps
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
mkdir -m 700 /private/np-qualification
.venv/bin/python -m pip freeze > /private/np-qualification/environment.txt
.venv/bin/nanopredict doctor --json > /private/np-qualification/doctor.json
cp paper/templates/qualification_record.json /private/np-qualification/plan.json
cp paper/templates/feature_contract.json /private/np-qualification/feature_contract.json
```

Complete `plan.json` before initialization: site/operator/date, hardware and OS, Core/API/basecaller versions, workload and batch settings, non-study designation, measured clock error, and site-selected latency/resource acceptance limits. Null fields are unknown, not passed checks. Limits are site operational requirements, not journal requirements or newly chosen scientific success criteria. Check `doctor` contents: process exit success alone is not proof of connectivity or supported device status. Record source/environment/model hashes, and inspect that forecasts will remain hidden in headless mode.

Acceptance: dependency check and tests pass; actual MinKNOW connection and eligible MinION/basecalling are confirmed; private storage is durable; clocks and filesystem timestamps are characterized; no planned qualification acquisition has started yet. Do not change frozen files to work around an error.

## 2. Non-study recorder qualification

The new flag below freezes `purpose=qualification`; it cannot be converted into an independent study by reusing its directory. It uses the same predictors and checkpoint timing. `eligible` in this mode means eligible for **technical capture only**, and the reason must be `qualification`. Never supply `--independence-reviewed` in this mode.

```bash
.venv/bin/python -m nanopredict.study init --qualification --study /private/np-qualification/recorder --protocol /private/np-qualification/plan.json
.venv/bin/python -m nanopredict.study new-group
.venv/bin/python -m nanopredict.study collect --study /private/np-qualification/recorder
```

Keep `collect` running. Start the designated non-study acquisition through normal site operation. In a second terminal, replace `POSITION_NAME` and `GROUP_UUID` with actual values, and register before minute 30:

```bash
.venv/bin/python -m nanopredict.study enroll --study /private/np-qualification/recorder --position POSITION_NAME --group GROUP_UUID --eligibility eligible --reason qualification
.venv/bin/python -m nanopredict.study status --study /private/np-qualification/recorder
```

For a planned qualification run lasting beyond 120 minutes, verify 30/60/120-minute capture. Restart only the recorder between checkpoints using Ctrl-C and the same `collect` command; do not stop or restart sequencing for this test. Repeat `status`. Test recorder outage/missed-window handling in a separately designated qualification case; never invent missing predictions. Record device disconnection, plan changes, basecalling backlog and restart acquisitions as separate cases when available. A new acquisition needs a new run code and the same group where related.

```bash
.venv/bin/python -m nanopredict.study export --study /private/np-qualification/recorder --output /private/np-qualification/export.json
.venv/bin/python tools/paper/evaluate_frozen.py --study-export /private/np-qualification/export.json --output /private/np-qualification/must-not-exist
```

The evaluator command **must fail** with `Non-study qualification exports cannot enter independent evaluation`, without results. This is a negative acceptance check, not an analysis. Retain the error privately. Qualification outcomes may be recorded with the ordinary `end` command only after reconciliation; they cannot become study evidence.

Acceptance: purpose prints `qualification`; timely cases have exactly one stored checkpoint per horizon, source snapshot age and ready-time delay each at most the existing 120-second limits, no direct identity fields in export, predictions absent from stdout/UI, and identical stored checkpoints after restart. Missing/stale/late/error cases must be explicit. RPC/read-only behaviour, real timing and actual device compatibility require site observation; synthetic tests alone do not pass these gates.

## 3. Matched live feature inputs

```bash
.venv/bin/python tools/paper/export_study_features.py --study-export /private/np-qualification/export.json --contract /private/np-qualification/feature_contract.json --output /private/np-qualification/live_features.csv
.venv/bin/python tools/paper/compare_features.py --live /private/np-qualification/live_features.csv --historical /private/np-qualification/historical_features.csv --output /private/np-qualification/feature_comparison.csv --atol 0 --rtol 0
```

The site supplies `historical_features.csv` in the [documented schema](matched_validation.md). The original historical extractor remains unavailable. A newly specified extractor supports comparison to that replacement, not a claim of reproducing original training features. Save sanitized source-response/window metadata at collection and final reports separately. Resolve every `UNVERIFIED` definition against units, denominator, sampling interval, cutoff and availability evidence; numeric equality alone is insufficient. Prespecify nonzero tolerances by feature if required, before examining paired differences.

Acceptance for a parity claim: identical run/horizon/feature keys, reviewed definitions for all 40 inputs, all differences within the prespecified tolerances, explained missingness, no use of future observations, and measured contemporaneous availability. Otherwise report the mismatch and restrict the claim. Include 600/1800-second resolutions, sparse boxplots, changed plans, late starts, backlog and pore-scan boundaries. Do not change frozen model inputs or retrospectively select a favorable extraction.

## 4. Barcode yield, BAM fallback and restarts

Use designated non-study completed BAMs from one acquisition at a time. Compare the monitor's passed/failed primary-read base totals with an independently specified counter using identical read filters and file boundaries. Confirm whether each export includes the whole run or only selected barcodes; a barcode subset cannot establish whole-run final yield. Retain input checksums and reconciliation records privately.

Exercise BC/RG/path assignment, unclassified and absent assignments, API loss and fallback, incomplete files, reconnects and multiple positions using the [validation matrix](validation_protocol.md). Compare uninterrupted monitoring with recorder/counter restarts. Include copied and renamed files: path/size/mtime fingerprints do not establish content deduplication. Record failures and deviations rather than assuming persisted state proves reliability.

Acceptance: reconciled yield totals at matched boundaries, accounted-for barcode and unassigned totals, no unexplained duplicate bases or cross-run state, correct checkpoint retention and explicit missing forecasts. Run-level forecasts must remain unavailable for individual barcodes, PromethION and BAM fallback. Yield-target ETA and crossing times require measured time series; transferred file mtimes are not live completion times. Prespecify operational tolerances before qualification.

## 5. Measured latency and resources

On the qualification machine, record source-event, BAM-completion, discovery, processing and browser-display UTC timestamps using `paper/templates/latency_events.csv`. The software does not currently instrument all five stages automatically: the site's observer/instrumentation must supply actual timestamps with synchronization error and the observation method. A missing display/source event makes end-to-end dashboard latency unmeasurable; do not use mtime or offline scan duration as a substitute. Headless prediction readiness is a separate endpoint present in recorder exports, not a browser event.

```bash
.venv/bin/python tools/paper/analyze_latency.py --events /private/np-qualification/latency_events.csv --output /private/np-qualification/latency
.venv/bin/python tools/paper/profile_process.py --pid PROCESS_PID --seconds 600 --interval 1 --output /private/np-qualification/resources.csv
```

Run actual dashboard qualification separately from blinded headless collection; use `nanopredict start --source minknow --foreground --no-browser --position POSITION_NAME` if that is the interface being measured, and record browser observations through the local UI. Collect equivalent workloads with and without monitoring, cold/warm caches, one/multiple positions and relevant barcode counts. Record hardware, workload, monitor/basecaller process separation and repetitions. Linux RSS sums can double-count shared pages; sampling misses short-lived processes. Any separate finite-command benchmark measures offline processing only, not live monitoring overhead.

Acceptance: complete nonnegative stage traces, stated clock uncertainty, workload/configuration records, paired monitoring/no-monitoring measurements, and comparison against the site's **previously recorded** latency/memory/CPU budgets. No universal numerical performance budget has been established here. Missing clocks, traces or budgets remain an incomplete qualification, not a passed test.

## 6. Independent enrollment is a separate decision

Finish the qualification report and resolve deviations first. Then the investigator and custodian separately approve [independent_protocol.md](independent_protocol.md), document training-overlap/related-group review, endpoint/filter reconciliation and blinding. If original training membership cannot support the planned independence claim, decide whether to develop an auditable replacement before reserving any new evaluation cohort. Do not use qualification cases as independent cases.

Only after that decision use [operator_instructions.md](operator_instructions.md) to initialize a **new** directory without `--qualification`, before untouched acquisitions start. Never edit a qualification freeze, copy its database into the study, retrain against reserved outcomes, or upgrade code mid-phase. Existing frozen directories require their original checkout/evaluator; this new build intentionally fails source-drift checks for older freezes. No enrollment was initiated on the cluster.
