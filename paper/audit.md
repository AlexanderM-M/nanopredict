# Repository and model provenance audit

**16 October 2026 provenance correction:** Original training scripts, tables and reports were recovered locally, and all three original model files match the bundled artifacts byte-for-byte. Matching protocol and acquisition IDs establish that 14/20 retrospective runs contributed to every deployed model; S9 additionally shares a training flow cell. The 20-run results are not independent validation. See [the recovery record](evidence/training_provenance_recovery.json). Earlier statements below that these materials were unavailable describe the prior search and are superseded.

The GitHub checkout at `6a613a2b05a3e61df41a23d4fdf959c7c4d813bd` reports package version 0.10.0. GitHub HEAD matched that revision on 8 October 2026. Work is on `paper/application-note-preparation` under `/gpfs/data/fs72584/alexander_m/nanopredict`, the destination confirmed after the originally requested fs72864 user directory was absent. No applicable `AGENTS.md` was found in inspected parents or the clone. Development follows the README.

## Available evidence

| Asset | Verified contents | Permitted use |
| --- | --- | --- |
| Python package | CLI, local HTTP/browser dashboard, MinKNOW collectors, replay, yield predictor, peer diagnostics, health checks, anonymous reports, BAM fallback | Implementation description and reproducible software tests |
| Replay CSV | 513 rows, 171 anonymous labels, exactly one 30/60/120-minute row per label, all `MINION_MK1D`; 40 numerical inputs plus label, device, horizon and final passed-base outcome | Demonstration and explicitly exploratory retraining |
| Prediction artifacts | Three joblib dictionaries, fitted pipelines, feature names, calibration metadata, residuals and warning text | Metadata inspection and software smoke tests; no independent performance estimate on replay |
| Diagnostic reference | Quantiles for MinION and PromethION horizon groups; source string `nanoprediction/report_features.csv` | Describe existing diagnostic rules; not labelled failure validation |
| Tests | 37 original unittest cases in six files | Mocked/synthetic behaviour checks, not live instrument or clinical validation |
| Documentation | README, GPL-3.0-only license, third-party notices, packaging and CI configuration | Installation and source availability |

File sizes and SHA-256 values are in `evidence/inventory.json`. The compressed target-table hash matches the generated-target hash in metadata.

## Training is different from replay

| Checkpoint | Stored estimator | Artifact training_samples | Global residual count | MinION residual count | PromethION residual count |
| --- | --- | --- | --- | --- | --- |
| 30 min | Median imputation with indicators, scaling, RidgeCV | 198 | 198 | 176 | 22 |
| 60 min | Median imputation with indicators, scaling, RidgeCV | 213 | 213 | 181 | 32 |
| 120 min | Median imputation with indicators, ExtraTrees, 600 trees | 243 | 243 | 182 | 61 |

All artifacts name `sample_grouped_5fold_oof_log_residuals` as their calibration method and `log1p` as the calibration transform. They report latest training start `2026-08-25T16:49:34.026140225Z`; this is an artifact assertion, not reconstructed chronology. The three training-sample counts sum to 654 horizon observations but do not identify a unique-run cohort. Metadata directly contradict the prior README statement that training involved only the 171 MinION replay histories. PromethION residual groups establish mixed-device calibration metadata; they do not alone reconstruct every estimator's training membership.

The original RidgeCV sits after imputation and scaling. Without the training script, one cannot verify grouped tuning or whether preprocessing was refitted inside tuning folds. Stored out-of-fold residuals do not establish held-out or prospective coverage. Their generation, group identities and model selection history are unavailable. The new benchmark uses fixed model settings and a separately held calibration partition.

The dashboard's MinION restriction remains appropriate as an implementation policy pending device-specific validation. Its warning now describes absent independent PromethION validation instead of claiming a MinION-only training cohort. Historical residual calibration is distinct from demonstrated prospective calibration.

## Replay quality and split feasibility

All three rows of each anonymous label carry a consistent final outcome. Two labels have zero final passed yield and missing passed-base counters; zero outcomes are retained, not discarded as failures. Minimum-Q settings are absent in six rows; planned duration is absent in 27 rows (nine histories). The recent passed-base rate is absent in 144 rows. There are 140 histories at 1,800-second resolution and 31 at 600-second resolution. Every `observed_through_seconds` equals its nominal checkpoint. Target temperature is zero in all 513 rows.

`SampleN` identifies a replay history. It is not evidence of date order or a unique biological sample. No acquisition start dates, actual final durations, stop reasons, source paths, original run IDs, library IDs or flow-cell relationships remain. Grouping by anonymous label prevents that history's snapshots crossing partitions. It cannot keep related but differently labelled histories together. The complete-three-checkpoint selection also excludes some shorter or incomplete histories and limits generalization.

Consequently: chronological evaluation, sample/flow-cell-disjoint evaluation and independently held-out evaluation of bundled artifacts are not justified by the packaged data. The exploratory runner never loads those artifacts and never invents missing metadata.

## Missing evidence and bounded local search

The historical `nanoprediction` analysis directory, raw reports, training scripts, fold manifests, original benchmark CSVs and written reports are absent from the clone. A depth-three directory-name search under the current GPFS user directory and home did not locate it; this was not an exhaustive search of all cluster storage. No old-cluster transfers were attempted.

The user's earlier observations—244 runs spanning devices, byte-identical original and packaged models, disagreements between benchmark prose and CSVs, inconsistent gains over linear extrapolation, and scheduled/intentional/failed endings—are historical audit reports, not independently reproduced results here. The current artifact counts corroborate parts of the mixed-device metadata story only. Hash equality to absent original files cannot be tested.

## Readiness limits

The README's unsupported MinION-only training claim and unqualified live validation wording were corrected. Automated tests verify code behaviour. Claims about forecasting benefit, reliable target probabilities, live performance and operational readiness require new evidence. The exported anonymous report omits persistent study linkage and full raw feature snapshots; use a separate controlled study registry and checkpoint recorder for prospective validation rather than assuming the dashboard report is sufficient.

## Continuation provenance verification

A fresh inventory matched the prior replay, artifact metadata, diagnostic references and data-file hashes exactly. Git history shows all three model files and the anonymous replay CSV were introduced together at `53cbbc3` (Initial replay dashboard and CLI); no later blob changes or original training scripts/manifests occur in their path history through base `6a613a2`. Their common initial inclusion does not establish disjointness between replay and training/calibration. These are four distinct roles: fitted training cohort (membership unknown), residual calibration cohort (counts/groups stored but split identities unknown), the 171-history replay/development subset, and a future untouched independently recruited evaluation cohort (currently absent). The new study recorder freezes existing artifacts and explicitly developmental baseline settings before new acquisitions. It does not reconstruct the unavailable historical cohort.

## Development diagnosis of the early models (16 October 2026)

The [development-only diagnosis](evidence/early_model_diagnosis/summary.json) reproduced all 654 original feature rows (26,814 feature/target cells) and both early ridge fits within numerical tolerance. It found negative raw predictions on 35/176 and 46/181 MinION fitting observations at 30/60 minutes; the deployed predictor clips these to zero. Controlled ablations used the original development collection only, with five outer folds over 121 connected sample-label/flowcell components. No newly uploaded evaluation case was used, and no deployed artifact was modified.

On identical baseline-available MinION rows (165 at 30 min; 167 at 60 min), mean absolute errors in Gb were:

| Recipe refitted within development folds | 30 min | 60 min |
| --- | ---: | ---: |
| Original mixed-device raw-yield ridge | 0.427 | 0.412 |
| MinION-only raw-yield ridge | 0.291 | 0.285 |
| Mixed-device log1p-target ridge | 0.218 | 0.217 |
| MinION-only log1p-target ridge | 0.213 | 0.221 |
| MinION-only extra trees | 0.161 | 0.169 |
| Cumulative-rate extrapolation | 0.326 | 0.356 |

These are exploratory development comparisons, not evaluation of new deployed models. Baseline-missing cases remain in the separate all-MinION results (176/181 rows), where tree MAE is 0.264/0.296 Gb. The apparent aggregate gain does not apply uniformly: trees beat extrapolation on only 85/165 and 82/167 matched runs; among 26 three-hour runs, 60-minute MAE is 0.140 Gb for trees versus 0.069 Gb for extrapolation. Original RidgeCV internal tuning was retained for controlled ablation and remains a limitation.

The evidence supports a separate MinION-specific development phase, with related-group tuning and preprocessing, an explicit observed-yield lower bound, recalibration of the final predictor, and new reserved evaluation cases. It does not justify silently replacing the deployed models or claiming general superiority over extrapolation.
