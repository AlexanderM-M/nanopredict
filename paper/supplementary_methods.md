# Supplementary Methods and Results

NanoPredict: local MinION monitoring with duration-aware yield forecasts

Version 0.11.0; evidence reviewed 23 October 2026. This supplement describes development, implementation checks and two technical examples. It does not report independent predictive validation. Supplementary Historical Results is a separate, preserved record of earlier mixed-device models.

## S1. Model versions and evidence provenance

Three model generations must be distinguished. The legacy package contained mixed MinION/PromethION raw-yield ridge models at 30 and 60 minutes and an extremely randomized tree ensemble at 120 minutes. The 16 October MinION-only revision used 40 numerical features, log-target ridge at 30 and 120 minutes and 600 extra trees at 60 minutes. The 22 October duration-aware revision uses only cumulative passed bases, observed seconds and configured hours at every checkpoint. This last revision is bundled in version 0.11.0. Earlier artifacts, frozen predictions and their performance records were preserved.

The original collection contained 244 acquisitions, including 183 MinION acquisitions represented by 539 checkpoint rows and 61 PromethION acquisitions represented by 115 rows. Only MinION rows entered the two replacement development procedures. Recorded sample-folder and flowcell connections defined 86 related groups. A sample-folder label is not proof of a distinct patient; unrecorded biological relationships remain unresolved. The original partition assigned 64 groups (146 acquisitions) to fitting/model selection and 22 groups (37 acquisitions) to development calibration, using seed 20261016. The duration-aware analysis reproduced the partition and verified original input hashes.

The two October technical acquisitions influenced the decision to revise the model and the choice of inputs. Their records and outcomes were not read by the parameter-fitting script and did not enter fitting or calibration. Exclusion from parameter fitting does not make them independent tests of a design they informed. The historical 20-run assessment also cannot establish independent accuracy: 14 acquisitions occurred in legacy training. These distinct sources of dependence are retained in the interpretation.

## S2. Inputs, endpoint and availability

At each 30-, 60- or 120-minute checkpoint, B is cumulative passed bases, t is the elapsed time represented by that counter in hours, and T is planned sequencing duration in hours. The exact fields are `observed_passed_bases`, `observed_through_seconds` (converted to hours), and `planned_run_limit_hours`. The live recorder preserves the collected numerical values. An observation timestamp alone does not establish when all underlying basecalls became available.

The development endpoint is final passed bases divided by 10^9 (Gb). This observed-ending outcome may reflect intentional stopping, interruption or failure. The deployed point forecast assumes continued production towards T, so development error against an early-stopped outcome does not estimate counterfactual yield had sequencing continued. Future evaluation should retain end reasons and report this distinction. Actual future stop time must not be substituted for planned duration at a checkpoint.

Rows require finite inputs, B >= 0, t > 0, T > 0 and, for development eligibility, T >= t. No missing duration or passed counter is imputed. At runtime, T <= t yields observed passed yield, with no projected additional production. Invalid inputs make the forecast unavailable while live yield monitoring continues. Historical replay retains missing-input snapshots and their observed measurements instead of inventing forecasts. The 40-field audit includes recent-rate and quality statistics for diagnostics/comparators, but these cannot affect the three-input model.

Table S1. Checkpoint availability in the original fixed partition. Excluded counts concern rows with missing, invalid or inconsistent required inputs; they are not failures of an otherwise available forecast. Counts at different checkpoints overlap and must not be summed as independent acquisitions.

| Checkpoint (min) | Partition | Original rows | Eligible rows | Excluded rows | Eligible groups |
|---|---|---:|---:|---:|---:|
| 30 | fit | 141 | 133 | 8 | 56 |
| 30 | calibration | 35 | 32 | 3 | 18 |
| 60 | fit | 144 | 134 | 10 | 57 |
| 60 | calibration | 37 | 33 | 4 | 19 |
| 120 | fit | 145 | 134 | 11 | 58 |
| 120 | calibration | 37 | 33 | 4 | 19 |

## S3. Point estimator and model selection

Let Y = B / 10^9 and R = max(T - t, 0). The forecast is

$$\widehat{Y}_{final}=Y+s(Y/t)D(R;\lambda),$$

where D(R; lambda) = (1 - exp(-lambda R)) / lambda when lambda > 0, and D(R; 0) = R. For a finite half-life H, lambda = log(2) / H. This is an extrapolation rule; the fitted half-life is not a directly measured pore lifetime. With s = 1 and no decay, the rule is cumulative-rate extrapolation. The nonnegative scale ensures the point forecast cannot fall below observed yield. Zero passed bases produce zero projected yield, rather than an assumed startup recovery.

The fixed candidate grid crossed H in {3, 6, 12, 24 hours, no decay} with either s = 1 or a fitted scale. Fitting weights each acquisition by the inverse number of acquisitions from its related group. For a given H, the fitted scale minimizes weighted absolute yield error: it is the weighted median of (final yield - Y) divided by the unscaled projected additional yield, with weights equal to the acquisition weights multiplied by that additional yield. Rows with zero additional yield contribute no information about scale. The fitted value is clipped to [0, 2]. No imputer, quality feature, sampling-resolution feature or feature scaler enters this estimator.

Five-fold shuffled GroupKFold with seed 20261016 is applied within eligible fitting groups. Every candidate is fitted separately within each fold. Selection uses the mean of within-group MAEs, not a pooled checkpoint analysis. Eligible alternatives must reduce overall group-weighted MAE by at least 1% relative to cumulative extrapolation and have no more than 5% higher group-weighted MAE in the short-run subset (T <= 6 h). Among eligible candidates, the smallest overall error wins; exact ties retain the earlier grid entry, with cumulative extrapolation first. The selected configuration is fitted to all eligible fitting rows. The candidate grid and rule were written to a timestamped plan before this revision's cross-validation scores were computed, after the live-run diagnosis; this was development planning, not preregistration of an independent test.

Table S2. Selected parameters. Scales are shown to six decimal places; serialized artifacts retain full precision.

| Checkpoint (min) | Half-life (h) | Fitted scale | Fitting groups | Calibration groups |
|---|---:|---:|---:|---:|
| 30 | 6 | 1.760871 | 56 | 18 |
| 60 | 12 | 1.187506 | 57 | 19 |
| 120 | 12 | 1.136099 | 58 | 19 |

## S4. Residual intervals and target probabilities

For each eligible calibration acquisition, the signed residual is log(1 + actual Gb) - log(1 + predicted Gb). For each related group, the interval score is the maximum absolute residual among its acquisitions. With G groups and nominal coverage c, the radius is the ceiling((G + 1)c)-th ordered group score; when this rank exceeds G, the interval is unbounded above. Bounds are obtained by adding/subtracting that radius around log(1 + the point forecast), transforming back with expm1, and applying the observed-yield floor. At 30 minutes only 18 calibration groups are eligible, so the nominal 95% upper bound is unbounded. Finite 80% and 90% radii and all 60-/120-minute radii are retained in the artifact audit.

For a target q in Gb, each calibration residual receives weight 1/n_g, where n_g is the number of eligible calibration acquisitions in its group. The reported probability is (weighted count of residuals at least log(1 + q) - log(1 + point forecast) + 1) / (G + 2). If q has already been reached under the same passed-yield definition, the probability is one. These empirical, smoothed probabilities depend on the duration-aware point forecast; they are not fitted separately to a 72-hour endpoint. Nominal interval levels and group weighting do not establish coverage or probability calibration on future operational runs. Calibration data were excluded from estimator fitting and grid selection, but belong to a development collection inspected during earlier work.

## S5. Development comparisons

All methods in Table S3 use identical eligible rows at each checkpoint. Cumulative extrapolation is Y times T/t for T >= t. The previous model is the 16 October MinION-only artifact at the corresponding checkpoint. Run MAE gives each acquisition equal weight. Group MAE first averages absolute errors within each related group and then averages across groups. Short-run MAE is run-weighted within T <= 6 h (18 acquisitions in nine groups at each checkpoint). These summaries were recomputed from saved calibration predictions for the manuscript; no estimator was refitted. No significance test or independent-test confidence interval is inferred from this inspected development partition.

Table S3. Development-calibration errors (Gb).

| Checkpoint (min) | Model | Run MAE | Group MAE | Short-run MAE |
|---|---|---:|---:|---:|
| 30 | Duration-aware | 0.298138 | 0.330496 | 0.205447 |
| 30 | Cumulative | 0.374391 | 0.526824 | 0.133695 |
| 30 | Previous MinION | 0.438262 | 0.260062 | 0.656199 |
| 60 | Duration-aware | 0.258533 | 0.336855 | 0.101288 |
| 60 | Cumulative | 0.371031 | 0.537417 | 0.108474 |
| 60 | Previous MinION | 0.326652 | 0.266349 | 0.474051 |
| 120 | Duration-aware | 0.236364 | 0.327173 | 0.076192 |
| 120 | Cumulative | 0.350691 | 0.531924 | 0.082477 |
| 120 | Previous MinION | 0.386534 | 0.242591 | 0.589271 |

The previous model's previously reported full-calibration MAEs (0.482/0.574/0.587 Gb) use 35/37/37 rows. They must not be compared directly with the new model on 32/33/33 rows. Table S3 and the main table instead recompute the previous model's metrics on the common eligible subset. Lower pooled run error and higher group error can coexist because the two summaries weight related groups differently. The short-run selection safeguard applies to fitting folds, not to an independent guarantee of short-run performance.

## S6. Live technical examples and diagnostic recomputation

Run A began on 20 October 2026 using the legacy artifacts; run B began on 21 October using the previous MinION-only artifacts. Both were configured for three hours and completed acquisition after approximately 10,804 seconds. They used the same flowcell. The archive name for run B refers to its 22 October export, not a third acquisition. Final passed yields were 225,955,031 bases (187,580 passed reads) and 136,929,085 bases (82,001 passed reads), respectively. Report/summary linkage, final passed counts, captured planned duration and the three passed-base checkpoint counters were checked. For run B, the archive review verified 100 internal file hashes and all 35 specified integrity/reconciliation checks. One extra failed summary read had zero bases and no output; this numerically accounts for a failed-read-count discrepancy and does not alter the passed-yield endpoint. It does not prove the mapping of that read to a specific report-discard category.

Run A's recorder indicated hidden forecasts, but the operator had reported viewing dashboard forecasts; blinding cannot be inferred from that flag. Run B enabled forecast visibility, with actual operator viewing unverified. These are qualification examples, not independent blinded evaluations. Clock-qualified latency, resource burden, a real barcode/restart matrix and cross-site reliability were not established.

In run B, live sampling resolution was 1800 seconds and the first checkpoint lacked recent-rate inputs. All 18 fitting acquisitions configured for three hours used 600-second intervals. Sensitivity substitutions showed dependence on sampling metadata and missingness; some used final-report information whose live availability was unproven. Such substitutions isolated model behavior but were not valid corrected operational forecasts. The duration-aware model excludes these inputs, but does not resolve every possible counter, timing or basecalling-backlog discrepancy.

Table S4. Figure 1 values in Mb (10^6 passed bases). “Recorded earlier” refers to different earlier model generations for A and B. The duration-aware column is post-hoc recomputation from saved checkpoint inputs. Both examples informed design. Cumulative extrapolation was closer than the new model at every checkpoint.

| Run | Checkpoint (min) | Actual final | Recorded earlier | Duration-aware post hoc | Cumulative |
|---|---:|---:|---:|---:|---:|
| A | 30 | 225.955031 | 407.776179 | 327.397197 | 227.174988 |
| A | 60 | 225.955031 | 593.118148 | 255.271858 | 236.147145 |
| A | 120 | 225.955031 | 546.272995 | 240.434082 | 232.385053 |
| B | 30 | 136.929085 | 406.573705 | 237.289900 | 164.651166 |
| B | 60 | 136.929085 | 296.877026 | 160.186265 | 148.185270 |
| B | 120 | 136.929085 | 210.389845 | 144.758597 | 139.912503 |

## S7. Software checks and reproduction

The version 0.11.0 replacement snapshot passed 103 source tests and 59 tests included in an extracted transfer package. Tests cover default model selection, freeze hashes, comparator provenance, duration dependence, missing-input behavior, monitoring recovery and report handling, using synthetic or mocked services where applicable. The 98 saved calibration predictions were verified through the serialized runtime consumer. All 513 anonymous replay snapshots were processed: 480 had forecasts and 33 had missing required inputs. Replay histories overlap development and are demonstrations, not an independent evaluation cohort. These are recorded checks of the model-replacement snapshot; editing this manuscript does not create a new hardware qualification.

Table S5. SHA-256 identities of the bundled artifacts.

- `calibrated_yield_120min.joblib`: `b03db53063c4e816eb60c12c8151d8045a38c2194e382b7be32e05449da44400`
- `calibrated_yield_30min.joblib`: `bda9ca5e17b48bf3aeccd712c611e890abf9befeffd745c37bd5421d0dc6f526`
- `calibrated_yield_60min.joblib`: `5a31f33b0e94762e3ea5b395cba4815a6cdd55f08dfcc702a1ff3160ead53cf0`

The repository README provides installation and operation instructions. From the exact version 0.11.0 source checkout, with Python 3.11 and the pinned dependencies:

```bash
python -m pip install --editable .
python -m unittest discover -s tests -v
python -m nanopredict start --source replay --foreground --no-browser
```

To monitor MinKNOW, use `--source minknow`. Remove stale `NANOPREDICT_MODELS_DIR` overrides to select the bundled defaults. The initial forecast is available only when its checkpoint inputs are available. To record a new technical acquisition, prepare a protocol and initialize a new directory:

```bash
python -m nanopredict.study init --study NEW_RECORDER \
  --protocol PROTOCOL_FILE --qualification --predictions-visible
python -m nanopredict.study collect --study NEW_RECORDER
```

Enrollment requires run linkage and related-material declarations as described by `python -m nanopredict.study --help` and the operator guide. A new acquisition must be enrolled before its first checkpoint. Existing recorders retain their original environments and model freezes. Qualification records cannot be relabeled as independent validation.

Training reproduction requires the original access-controlled development table, membership record and preceding development plan, whose hashes are recorded. It writes a new directory and does not read the two qualification outcomes:

```bash
python tools/paper/train_duration.py \
  --features /path/to/original/report_features.csv \
  --membership /path/to/original/private_membership.json \
  --previous-development /path/to/minion-model-development-20261016 \
  --output /path/to/new-duration-development
```

To regenerate the figure from the supplied aggregate CSV, using Matplotlib 3.9.4:

```bash
python tools/paper/render_duration_manuscript.py \
  --data paper/evidence/manuscript_20261023/figure1_data.csv \
  --output /path/to/new-figure-directory
```

The figure renderer performs no model fitting or rescoring. The source Word manuscript is generated with `tools/paper/export_word.py` and the supplied Bioinformatics Advances template. The manuscript evidence audit records input hashes, availability counts, recomputed errors and artifact identities. Aggregate evidence supports inspection of the reported numbers; it does not replace access to original inputs for full training reproduction. Public availability of the exact source/model snapshot and permitted access to underlying data must be finalized by the authors.
