# Nanopredict Application Note preparation

**Public package cleanup (16 October 2026):** The distribution now contains yield forecasting and monitoring only. Barcode counting accepts ordinary unaligned BAMs. The current source suite has 90 passing tests and the fresh installed wheel passes nine dashboard tests; see [verification](evidence/public_package_cleanup/verification.json). Earlier test counts describe historical source snapshots. Existing model artifacts are unchanged. Source changes require a new recorder freeze for future qualification; preserved frozen studies retain their original source.

## MinION-only candidate training — 16 October 2026

The [candidate record](evidence/minion_model_development/summary.json) documents new models trained exclusively on the recovered MinION development collection: 183 acquisitions, 539 checkpoint rows and 86 connected groups defined by recorded sample labels or shared flowcells. All 115 PromethION checkpoint rows were excluded. A fixed seed reserved 22 groups (37 acquisitions) for development calibration; the other 64 groups (146 acquisitions) supplied fitting and five-fold grouped model selection. Checkpoint availability reduces the counts at some horizons. [Integrity checks](evidence/minion_model_development/integrity_checks.json) found no recorded sample, flowcell, protocol or acquisition overlap between fitting and calibration. Unrecorded biological relationships remain unresolved.

| Checkpoint | Selected model | Fitting runs | Calibration runs |
| --- | --- | ---: | ---: |
| 30 min | Ridge on log1p final yield, alpha 10 | 141 | 35 |
| 60 min | 600 extra trees, minimum leaf size 3 | 144 | 37 |
| 120 min | Ridge on log1p final yield, alpha 10 | 145 | 37 |

Selection minimized mean within-group MAE across fitting-only folds. Each fold fitted its own median imputer with missingness indicators and, for ridge, standardization. Predictions are floored at passed yield already observed. Separate calibration groups supply maximum absolute log1p residuals per group for interval order statistics; empirical threshold probabilities weight each group equally. These probabilities have not been independently validated. The random calibration partition is drawn from previously inspected development data; it is not a new independent test cohort. Selected-model cross-validation scores are also model-selection results, not unbiased estimates of final performance. Calibration MAE was 0.482/0.574/0.587 Gb at 30/60/120 minutes, so improved independent accuracy cannot be assumed from the fitting-fold comparisons.

Candidate artifacts, the prespecified training plan, private split manifest and preserved source files are in ignored `paper/archive/minion-model-development-20261016/`. All 109 calibration predictions matched after loading through the runtime predictor. All 107 automated tests pass. Bundled production models and the manuscript's existing retrospective results remain unchanged; the new candidates are frozen for technical qualification and subsequent evaluation, not promoted as validated replacements. No newly uploaded run was added to development.

Reproduction uses a new output directory and the original private inputs:

```bash
python tools/paper/train_minion.py \
  --features /path/to/recovered/report_features.csv \
  --membership archive/training-provenance-20261016/private_membership.json \
  --output paper/archive/minion-model-development-repeat
```

For local technical qualification, the updated runtime can load the staged models using `NANOPREDICT_MODELS_DIR=paper/archive/minion-model-development-20261016/models`. The candidate artifacts require this runtime's device restriction, observed-yield floor and weighted-residual handling. Older installations must be updated before loading them. Training and qualification do not establish live/historical feature equivalence; that remains the next evidence requirement before independent evaluation.

**Early-model investigation completed:** The [development-only diagnosis](evidence/early_model_diagnosis/summary.json) reproduces the original data and fits, and finds that device pooling, raw-yield ridge behavior and weak grouping warrant a separate replacement-development phase. MinION-specific/log-target/tree ablations improve development errors, but extrapolation still wins in the three-hour 60-minute subset. Existing models remain unchanged; no new evaluation cases were used for these experiments.

**16 October 2026 provenance correction:** Original training scripts, tables and reports were recovered locally, and all three original model files match the bundled artifacts byte-for-byte. Matching protocol and acquisition IDs establish that 14/20 retrospective runs contributed to every deployed model; S9 additionally shares a training flow cell. The 20-run results are not independent validation. See [the recovery record](evidence/training_provenance_recovery.json). Earlier statements below that these materials were unavailable describe the prior search and are superseded.

The [current dataset screen](evidence/current_dataset_eligibility.csv) identifies S1, S2, S3, S4 and S10 as having no recorded training acquisition/protocol/flowcell match; they form four flowcell groups because S1 and S3 share a cell. All five were already inspected and remain a post hoc retrospective subset pending biological relationship review, not a newly reserved test set. The [training-method review](evidence/training_method_review.json) records reused flowcells across original folds and the identity-first intake steps for additional uploads. No new uploaded cases have been scored or assigned to training.

The subsequent [S21–S30 identity screen](evidence/s21_s30_intake.json) found that all ten uploads match original training acquisitions, with matching protocol IDs and consistent final-summary linkage. S29 also duplicates S15; S21 and S22 share a flowcell. No new independent evaluation candidates were identified, and no new outcomes or predictions were examined. A private 244-run identity lookup is available under `archive/intake-s21-s30-20261016/training_run_lookup.csv` to screen candidate reports before transferring BAMs.

**Replacement-upload update:** S25–S30 were subsequently replaced. The [versioned replacement screen](evidence/s25_s30_replacement_intake.json) supersedes the earlier identity findings for those six folder labels: no current acquisition matches training; current S25 repeats S4; current S30 shares a training flowcell. Current S26–S29 are four new acquisitions without a training flowcell match, but share three flowcell groups with previously scored non-training cases. They are candidates for a grouped retrospective assessment, not a new group-independent confirmatory cohort. Original upload records and replacement report snapshots are preserved separately; no new yields or predictions were analysed.

**Subsequent authorised assessment:** After the investigator confirmed complete-run exports and requested continuation, the [replacement assessment](evidence/replacement_assessment/summary.json) scored S26–S29 descriptively (four acquisitions, three flowcell groups), with S30 separate and S25 excluded as a repeat of S4. All six report/summary endpoints reconciled exactly. Primary NanoPredict MAE was 0.313/0.137/0.009 Gb at 30/60/120 minutes versus 0.017/0.015/0.012 Gb for cumulative extrapolation. No model was changed. S29 contains 36 foreign BAM files; scoring used its reconciled whole-run report/summary, not BAM subtotals. This is not a fresh group-independent confirmatory cohort or live validation.

This branch prepares Nanopredict for a Bioinformatics Advances Application Note. It contains a verified repository audit, reproducible exploratory retraining, validation procedures and a draft with evidence placeholders. It includes a completed, limited retrospective report-reconstruction analysis; it does not establish prospective forecasting accuracy, interval calibration or real-device reliability.

## Start here

- [Repository and model audit](audit.md): available evidence, missing dependencies and corrected provenance.
- [Feature definitions and timing](feature_audit.md): historical versus live inputs and unresolved parity checks.
- [Benchmark methods](benchmark_methods.md): estimand, grouping, baselines, calibration and interpretation.
- [Validation protocol](validation_protocol.md): prospective collection, barcode yield, restarts, latency and resources.
- [Journal requirements](journal_requirements.md): Bioinformatics Advances selected on 16 October 2026; current Application Note requirements.
- [Manuscript draft](manuscript.md): proposed title, structured abstract, main text and explicit missing evidence.
- [Evidence inventory](evidence/inventory.json), [field audit](evidence/replay_fields.csv), and [exploratory results](evidence/exploratory/metadata.json).

## Local material and machine qualification

The paper focuses on yield forecasting and monitoring. Follow the [sequencing-machine handoff](machine_handoff.md) for non-study qualification with `study init --qualification`. This purpose is rejected by the independent evaluator. Qualification is not study enrollment or protocol approval.

## New dataset intake

The [15 October intake](evidence/dataset_intake.json) records four investigator-confirmed complete P2 Solo runs. Header inspection confirms distinct acquisitions; training overlap and related-material groups remain unresolved. These runs support assessment of PromethION monitoring, not the current MinION-only forecast evaluation. See [readiness](readiness.md) for the remaining data requirements.

Reproduce the file/header-only intake with coded `SampleN` or `RunN` directories, writing a fresh output file:

```bash
python tools/paper/inventory_datasets.py --data-root /path/to/coded_runs --output /path/to/new_intake.json --declared-distinct-runs --declared-device P2_SOLO --declared-complete-runs
```

The declaration flags record the investigator's statements. They do not prove biological independence, complete export scope or platform qualification. The utility does not scan reads or calculate predictions/outcomes.

## Expanded MinION cohort and retrospective extraction

The [20-run intake](evidence/minion_cohort_20.json) supersedes the earlier seven-run intake for current cohort size. The [prepared retrospective plan](retrospective_plan.json) specifies the analysis and unresolved gates. These historical cases must not be imported as prospective recorder events.

```bash
.venv/bin/python tools/paper/extract_retrospective.py --data-root /path/to/datasets --output paper/archive/retrospective-new --declarations paper/evidence/retrospective_declarations.json
```

Use an interpreter with the project dependencies installed; the output directory must be new. Outputs are candidate numerical inputs, a per-feature missingness/source audit, a coded cohort table and a hashed manifest. Temperature timing has been recovered from linked HTML/JSON reports, and all 20 final passed yields and read counts reconcile with sequencing summaries. Report/live window differences remain unresolved; numerical extraction is not a validated forecast result.

## Completed retrospective reconstruction

The [execution record](evidence/retrospective/analysis_record.json), [aggregate metrics](evidence/retrospective/metrics.csv), [paired comparisons](evidence/retrospective/paired.csv) and [figure manifest/captions](evidence/retrospective/figure_manifest.json) document the separate analysis. Both full-cohort and prespecified configuration-error sensitivity results are reported; the sensitivity does not support a general advantage over extrapolation. The [manuscript](manuscript.md) contains the results and interpretation.

Original execution commands (the inputs and full freeze remain private):

```bash
python tools/paper/evaluate_retrospective.py freeze --extraction paper/archive/retrospective-20-runs-v3 --outcomes paper/archive/yield-reconciliation-20-v1/manifest.json --plan paper/retrospective_plan.json --output paper/archive/retrospective-freeze-v1
python tools/paper/evaluate_retrospective.py score --freeze paper/archive/retrospective-freeze-v1/freeze.json --output paper/archive/retrospective-results-v1
python tools/paper/render_retrospective.py --results paper/archive/retrospective-results-v1 --output paper/evidence/retrospective
```

Each output directory must be new. To reproduce the existing frozen analysis, use its preserved input files and a new scoring output directory; the scorer rejects changed input/source/model/environment hashes. The renderer requires Matplotlib 3.9.4 and reads saved results only. Raw-data re-extraction creates a new provenance record; its timestamps/hashes must be reviewed against the original specification rather than overwritten into the old freeze. Model refitting or recalibration would require a separately declared development phase and new reserved evaluation cases.

## Prospective collection and independent validation

Use the [frozen independent protocol](independent_protocol.md) and [exact operator instructions](operator_instructions.md). The new `python -m nanopredict.study` command records predictions without a dashboard, freezes model/preprocessing/calibration and comparator settings, retains pseudonymous checkpoint linkage, and accepts reconciled outcomes and end reasons. `tools/paper/evaluate_frozen.py` scores only stored forecasts and never fits or recalibrates on evaluation outcomes.

See [matched validation](matched_validation.md) for executable live/historical feature and timing/resource comparisons , [readiness](readiness.md) for claim-specific missing evidence, and [release checklist](release_checklist.md) for the local archive. The manuscript remains **not submission-ready**.

## Reproduce locally

From the repository root, using Python 3.11:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --editable .
.venv/bin/python -m pip install -r paper/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/paper/audit.py --output paper/evidence
.venv/bin/python tools/paper/benchmark.py --output paper/evidence/exploratory
.venv/bin/python tools/paper/render.py --results paper/evidence/exploratory --output paper/evidence/exploratory/figures
```

`environment-freeze.txt` records the environment used here; `pyproject.toml` pins direct runtime dependencies. To recreate all installed versions, first install the freeze file and then install the checkout with `--editable . --no-deps`. Platform-specific wheels may differ. The benchmark records input and script hashes, versions, seed and group assignments. No original training artifact is modified. Checkpoints are evaluated separately. Reports and figures retain the exploratory label.

For genuinely dated data with verified group relationships and feature timing, create a separate CSV in the replay feature schema plus a completed [split manifest](templates/split_manifest.csv):

```bash
.venv/bin/python tools/paper/benchmark.py --data /path/to/verified_features.csv --split-manifest /path/to/split_manifest.csv --output /path/to/heldout_results
.venv/bin/python tools/paper/render.py --results /path/to/heldout_results --output /path/to/heldout_figures
```

The held-out mode retrains models. It does not certify the data's provenance or evaluate a frozen deployed artifact. It rejects known replay feature rows even after relabelling/reordering and requires chronology, outcome availability dates, group separation and a timing-verification assertion. Do not fill missing dates with labels, file mtimes or model metadata. No valid split manifest is provided because those facts are unavailable.

## Evidence still needed

Original training scripts, source exports, sample/run membership and historical benchmark CSVs have now been recovered and preserved under ignored `archive/training-provenance-20261016/`. Biological relatedness remains unverified. Fourteen of the 20 retrospective cases overlap training; these results cannot support independent validation. Recovery alone does not require retraining: first verify source extraction and related groups, then choose whether to retain or revise the models before reserving a new evaluation cohort. Collect paired live/historical features and independent run outcomes, real barcode-yield/restart fixtures and timed resource traces. The suggested 20–30-run consecutive prospective pilot is a feasibility plan, not a journal minimum or proof of calibration.

Local commits and a preparation archive preserve the reviewed work. Publication, archival deposit, submission and pushing require separate instruction.

## Word manuscript using the journal template

Use [NanoPredict_manuscript_bioadv.docx](NanoPredict_manuscript_bioadv.docx) for
author revision. It is generated from `manuscript.md` using the supplied
[bioadv-word-template.docx](bioadv-word-template.docx), retaining the template's
title/abstract block, two-column body, headers and paragraph styles. The results
table and figure use full-width sections. Publication metadata and example text
are omitted from the draft; unresolved author details remain explicit.

To regenerate from Markdown, use Python with `lxml` installed and `pandoc` on PATH:

```bash
python tools/paper/export_word.py
```

The default command replaces the generated Word file. Preserve Word edits before
regenerating, or choose a separate destination with `--output`. Verify pagination
in Word against the four-page Application Note limit after author revision.
