# Operator instructions for silent prospective collection

Run the following from a dedicated Python 3.11 installation of the reviewed commit on the sequencing computer. These commands are implemented and tested with simulated fixtures; MinKNOW/Core compatibility, permissions, connectivity and clock behaviour must first be checked locally. Do not use the cluster as evidence of live-device qualification.

Complete the separate [machine handoff](machine_handoff.md) first using `init --qualification`. Do not attest independence for non-study runs or reuse their directory. These enrollment commands apply only after investigator/custodian sign-off; the current preparation request does not authorize enrollment.

## Before the first enrolled run

1. Review and sign off [independent_protocol.md](independent_protocol.md). Establish the site screening log, identity crosswalk, related-patient/sample grouping and outcome source. Complete the original run-registry fields for chemistry, kit, basecaller version/model, filter settings, plans and later interventions. These device/library facts are not all available from the existing API collector and must be recorded in the controlled registry.
2. Transfer the locally prepared archive to the sequencing computer through the site's approved route (no Git push is required), extract it, or otherwise install the exact reviewed Git commit, then run `python -m pip install --editable .` in a dedicated environment. Record `python -m pip freeze`. The new module works independently of the normal dashboard command. Keep the full checkout: initialization freezes the `tools/paper/evaluate_frozen.py` script as well as package source, so a PyPI-only installation is not sufficient for this study workflow.
3. Run `nanopredict doctor --json` locally and retain the result privately. Confirm live basecalling and the correct output directory. Alignment is not required for yield monitoring. Configure batch duration and record it. Check host clock synchronization and UTC offset.
4. Qualify with a non-study run. Confirm durable writes, timely checkpoint capture, recovery after restarting the recorder, and absent forecasts on the operator screen. Do not reuse qualification outcomes as independent evaluation cases.
5. Stop any existing Nanopredict dashboard with `nanopredict stop`; this stops the application, not sequencing. Do not run it during blinded study acquisitions. Continue normal MinKNOW operation and normal run decisions.

Initialize once, before any enrolled acquisition starts. Choose a new access-controlled directory outside the checkout. The examples use `/path/to/study-v2`; replace that path consistently. On Windows use a custodian-controlled local directory and replace `python` with `py -3.11` if needed.

```bash
python -m nanopredict.study init --study /path/to/study-v2 --protocol paper/independent_protocol.md
python -m nanopredict.study collect --study /path/to/study-v2
```

Run `collect` in a persistent foreground terminal or a locally approved service; it polls every 20 seconds, supervises active positions, and displays only generic errors. It can begin before acquisitions. Keep the terminal open. Add `--host localhost` when needed; the default is localhost. Remote API authentication/network configuration remains a sequencing-machine dependency, not something this work established.

## Enrol each acquisition promptly

Generate a group code for a genuinely new related-patient/sample group:

```bash
python -m nanopredict.study new-group
```

Save the returned UUID in the controlled identity crosswalk. Reuse it for every related specimen, patient, library, reused-flowcell run or restart in the connected group. Do not generate a fresh group for every run when relationships exist. The software checks UUID syntax; the site custodian establishes the relationships and independence.

Once the acquisition starts, enrol it before the first checkpoint:

```bash
python -m nanopredict.study enroll --study /path/to/study-v2 --position POSITION_NAME --group GROUP_UUID --eligibility eligible --reason consecutive_eligible --independence-reviewed
```

Save the returned run UUID and original acquisition linkage in the site log. The study stores a keyed local acquisition linkage and exports no original acquisition/position/patient identifier. For exclusions use `--eligibility excluded` with one of `not_minion`, `no_live_basecalling`, `prior_development_relation`, or `other_protocol_exclusion`. Do not assert independence without the recruitment review. Acquisitions beginning before initialization are rejected for enrolment; record them in the site screening log as development/qualification exclusions.

Monitor collection without revealing forecasts:

```bash
python -m nanopredict.study status --study /path/to/study-v2
```

Status lists run codes, eligibility and checkpoint states only. Restart the same `collect` command after application/OS restart. Already recorded checkpoints are retained; expired windows are marked missed. Do not change Python packages, source files, protocol or frozen models mid-phase. A drift failure needs a documented new phase, not an override of the freeze check. A new acquisition on the same position requires a new enrolment but the appropriate existing group code.

## Record the ending and reconciled outcome

After basecalling drains, reconcile final passed bases with the prespecified independent source using identical filtering and acquisition scope. Obtain its SHA-256, for example `sha256sum /private/path/final-source.json` on Linux or `Get-FileHash -Algorithm SHA256` on Windows. Keep the source private. Record the actual end time and reason separately from when the outcome becomes available.

```bash
python -m nanopredict.study end --study /path/to/study-v2 --run RUN_UUID --ended-utc 2026-10-20T14:00:00Z --reason planned_completion --final-bases 123456789 --source-sha256 SOURCE_SHA256 --predictions-hidden
```

The timestamp and count above are command syntax examples, not study data. Replace them with measured values. Allowed reasons are `planned_completion`, `intentional_stop`, `interrupted`, `failure`, `unknown`. Omit `--final-bases` when unresolved; never turn missing yield into zero. Use `--predictions-hidden` only when confirmed. The command records outcome entry time as availability time; retain the actual source availability time in the site log if earlier. Duplicate outcome entries are refused. Log corrections for investigator adjudication rather than editing the database or predictions.

## Export and analyze after outcome lock

The data custodian, rather than the blinded sequencing operator, runs:

```bash
python -m nanopredict.study export --study /path/to/study-v2 --output /restricted/path/study-export.json
python tools/paper/evaluate_frozen.py --study-export /restricted/path/study-export.json --output /restricted/path/evaluation-v1
python tools/paper/render_frozen.py --results /restricted/path/evaluation-v1 --output /restricted/path/evaluation-figures
```

Exports include full numerical inputs, missingness, receipt/prediction times, all frozen forecasts and intervals, baseline forecasts, model/source/environment hashes, grouping, outcomes, end reasons and audit events. They are pseudonymous, not anonymous: exact dates and related-group links require controlled access. Never add the database, secret key, identity crosswalk or real study export to Git or the public archive. Evaluation does not retrain or recalibrate. Review all exclusions and pairing denominators before interpreting metrics.

The study module freezes forecasting. Follow the yield-focused [machine handoff](machine_handoff.md) for qualification. Real latency, barcode-yield agreement and feature timing require measured evidence; the fixture suite alone does not establish them.
