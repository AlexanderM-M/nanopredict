# NanoPredict: live nanopore run monitoring with early yield forecasts

**Draft for Bioinformatics Advances — Application Note; training overlap confirmed in retrospective results; independent validation pending**

Provisional authors: Alexander Miller-Michlits, Yelyzaveta Miller-Michlits, Christian Rohrandt, Franz-Josef Müller, Matthias Demetz, Christian Freyschlag, Adelheid Woehrer. [ORDER, SPELLING, CONTRIBUTIONS AND APPROVAL TO BE CONFIRMED; EXTERNAL COLLABORATORS’ PARTICIPATION PENDING.]

Affiliations: [DEPARTMENTS, INSTITUTIONS, CITIES, POSTCODES, COUNTRIES]

Corresponding author: [INSTITUTIONAL EMAIL AND ADDRESS]

Running head: NanoPredict: nanopore yield monitoring

## Abstract

**Motivation:** NanoPredict combines local, read-only nanopore monitoring with early yield forecasts and barcode-level progress.

**Results:** In retrospective reconstruction from 20 MinION runs, mean absolute errors were 0.295, 0.357 and 0.088 Gb at 30, 60 and 120 minutes. Comparisons with cumulative-rate extrapolation were sensitive to duration-setting errors: excluding two prespecified cases, extrapolation performed better at 30 and 60 minutes and similarly at 120 minutes. Recovered training records show that 14 of these 20 runs contributed to all three deployed models. Training overlap, report aggregation and unknown contemporaneous availability prevent interpreting these results as independent validation or live forecasting accuracy. Prospective recording and real-device qualification remain pending.

**Availability and Implementation:** NanoPredict is implemented in Python with a browser interface and released under GPL-3.0-only at https://github.com/AlexanderM-M/nanopredict. [ARCHIVED SOFTWARE VERSION AND TEST-DATA URL]

**Keywords:** nanopore sequencing; yield forecasting; real-time monitoring; MinION; bioinformatics software

## Introduction

Nanopore sequencing produces data continuously, allowing operators to inspect yield while acquisition and basecalling remain in progress. Routine monitoring must account for delayed basecalls, barcoded libraries and progress towards yield targets. A yield forecast also depends on when input statistics become available and on how the run ends. Interpreting early forecasts therefore requires both timely inputs and an explicit definition of final yield.

Existing tools address several aspects of nanopore monitoring. NanoPack provides visualization and processing of long-read data (De Coster et al., 2018), and pycoQC provides interactive quality control (Leger and Leonardi, 2019). BoardION supports real-time instrument monitoring and run comparison (Bruno et al., 2021), while minoTour combines live metrics, sequence analysis and run archiving (Munro et al., 2022). NanoPredict focuses on combining local monitoring with explicit final-yield forecasts, uncertainty intervals and target probabilities at fixed early checkpoints. Its forecasting contribution requires comparison with simple yield extrapolation.

NanoPredict provides a local dashboard integrating live run statistics, early yield forecasts and barcode-level yield progress. It connects to the MinKNOW API through read-only queries (Oxford Nanopore Technologies, 2026) and offers a completed-BAM fallback when essential statistics cannot be read. It does not control sequencing or issue automated stopping instructions.

## Implementation

The Python package uses scikit-learn pipelines for prediction (Pedregosa et al., 2011) and contains collectors, diagnostic components, a standard-library HTTP server, and browser assets. The default server binds to the local loopback interface. It supervises active supported positions and exposes aggregate and barcode views. Users can set yield targets and inspect current progress, recent production rate and estimated time to target. Anonymous JSON and CSV reports use a field allow-list. A separate headless study recorder stores coded run and related-group identifiers, exact numerical inputs, missingness, receipt and prediction times, frozen software/model hashes, and all forecast intervals. SQLite transactions retain checkpoints across restart. The recorder creates no dashboard or run-control interface. A controlled site registry supplies patient/sample relationships and acquisition-end adjudication; exported study records are pseudonymous rather than anonymous.

MinKNOW statistics support forecast checkpoints at 30, 60 and 120 minutes. Inputs include passed and failed yield, read counts and lengths, basecalling progress, Q-score and translocation summaries, temperature, duty time and pore scans. The interface currently enables these forecasts for MinION; PromethION, barcode and BAM-fallback views provide monitoring without applying the run-level forecast. Acquisition-time selection does not by itself prove real-time feature availability, particularly when the application starts late or basecalling is delayed. Supplementary feature definitions specify these timing constraints.

NanoPredict predicts final passed sequencing yield (Gb) using 40 features at 30, 60 and 120 minutes. Missing values are median-imputed with missingness indicators. The 30- and 60-minute pipelines standardize inputs and use ridge regression; the 120-minute pipeline uses 600 extremely randomized trees. Recovered scripts and tables identify 198, 213 and 243 training observations, respectively, drawn from 244 run labels (183 MinION and 61 PromethION) under 238 sample-folder labels. These labels are not verified unique patients. The original model files are byte-identical to the bundled artifacts, and reconstructed fits reproduce their predictions within numerical tolerance. Deployment models were fitted on all available horizon rows. Uncertainty calibration used sample-label-grouped five-fold out-of-fold residuals on the log1p scale, with device-specific residual groups. The historical chronological 80/20 evaluation used separate models; its test rows were subsequently included in deployment fitting. RidgeCV internal tuning was not explicitly group-aware. Patient/specimen/library relationships and live feature availability still require verification.

## Evaluation design and results

The repository contains 513 snapshots from 171 anonymous MinION histories with all three checkpoints. Every packaged snapshot matches the recovered training table on all exported fields; replay therefore demonstrates software behavior and does not independently validate the bundled models. The minimized public table omits acquisition dates and source identifiers, which are now available in the private training archive. Biological relationships between sample-folder labels remain unverified.

A reproducible supplementary framework trains new comparators using group-separated fitting, calibration and test partitions. It includes fitting-set mean and median yield, cumulative and recent-rate extrapolation to planned duration, ridge regression and extra trees. Preprocessing is fitted only on training observations. Point errors, missing-prediction denominators, interval coverage and width, interval scores and target-probability scores are reported separately by checkpoint. The exploratory outputs are labelled as such and are excluded from claims of independent validation. For future independent data, a frozen protocol specifies consecutive enrolment, related-patient/sample grouping, blinded recording and an observed-ending yield endpoint including intentional stops and failures. A separate evaluator scores stored predictions on identical eligible runs, with related-group bootstrap uncertainty; it performs no fitting or recalibration. Prospective collection remains pending; the separately specified retrospective cohort is described below.

The retrospective reconstruction comprised 20 MinION Mk1D runs from 20 different patients, with distinct specimens and libraries according to the investigator. Although these cases were initially declared separate from development, a subsequent audit of recovered training records confirmed matching protocol and acquisition identifiers for 14 runs, present at all three training checkpoints. Of the remaining six runs, one shared a training flow cell; five had no acquisition, protocol or flow-cell match. Biological relationships still require review. The 20-run results below are retained as an overlapping retrospective demonstration, not an independent evaluation. The investigator stated that NanoPredict forecasts did not influence stopping decisions. The cases were described as randomly selected, but no formal sampling frame or consecutive recruitment was documented. Seventeen flow-cell identifiers defined related groups, including one group of two and one group of three runs.

Final passed-base totals and passed-read counts matched the corresponding sequencing summaries exactly for all 20 runs; no duplicate, missing or foreign-run read identifiers were detected. Eighteen runs completed their configured protocols and two stopped intentionally after sufficient data had been obtained. Configured limits were 3 h (eight runs), 12 h (ten), 6 h (one) and 72 h (one). The latter two were confirmed setting errors in intended 3-h workflows. The primary endpoint retained observed final yield and configured model inputs; a prespecified sensitivity analysis excluded these two cases without replacing their inputs with intended duration.

Inputs at 30, 60 and 120 minutes were reconstructed from JSON and linked HTML reports using native 10- or 30-minute bins. Explicit source timestamps constrained cumulative statistics, duty time, temperature and pore scans. Boxplot indexing followed report bucket width. These reconstructed inputs cannot establish when historical basecalls were available or reproduce the live collector’s windows. Therefore this analysis assesses the bundled predictors on report reconstruction, not contemporaneous live accuracy. No additional model fitting or recalibration occurred during retrospective scoring, but the deployed models had already used outcomes from the 14 overlapping runs. Missing recent-rate inputs affected 11 first checkpoints and were retained as missing; comparison denominators were method-specific, with paired comparisons restricted to the same runs. The analysis specification, inputs, models, scripts and environment were frozen before prediction generation. Uncertainty was estimated separately at each horizon with 2,000 flow-cell-group bootstrap replicates.

All 60 reconstructed checkpoints produced bundled-model estimates. Final passed yield ranged from 0.000064 to 1.955 Gb (median 0.269 Gb). Table 1 reports point-error estimates and paired differences. In the full cohort, all three confidence intervals for the MAE difference crossed zero. S15, mistakenly configured for 72 h and stopped at approximately 2 h 25 min, contributed 85–93% of cumulative-extrapolation absolute error across checkpoints. The prespecified sensitivity therefore materially changed the comparison.

Table 1. Retrospective reconstruction error in Gb in a cohort with 14/20 training-overlapping runs; not independent validation. Lower MAE is better. Differences are NanoPredict minus cumulative-rate extrapolation; brackets give 95% flow-cell-group bootstrap percentile intervals.

| Analysis | Checkpoint | NanoPredict MAE | Extrapolation MAE | Paired MAE difference [95% interval] |
|---|---:|---:|---:|---:|
| All 20 runs | 30 min | 0.295 | 0.841 | -0.546 [-2.250, +0.203] |
| All 20 runs | 60 min | 0.357 | 0.960 | -0.603 [-2.631, +0.279] |
| All 20 runs | 120 min | 0.088 | 1.001 | -0.913 [-3.237, +0.032] |
| Sensitivity, 18 runs | 30 min | 0.233 | 0.118 | +0.115 [+0.027, +0.204] |
| Sensitivity, 18 runs | 60 min | 0.282 | 0.091 | +0.191 [+0.056, +0.326] |
| Sensitivity, 18 runs | 120 min | 0.071 | 0.071 | +0.000 [-0.060, +0.042] |

Observed coverage of nominal 90% bundled intervals was 19/20, 19/20 and 20/20 at the three checkpoints, with mean widths of 1.271, 1.889 and 0.829 Gb. High coverage in a small selected cohort, together with these widths, does not establish calibrated uncertainty. Four runs exceeded 1 Gb; none reached 5 or 10 Gb, so the latter thresholds cannot assess performance on positive events. Recent-rate extrapolation was available for 9/20 runs at 30 minutes and all runs subsequently; all comparator, probability and interval summaries are retained in the supplementary aggregate tables.

[PENDING SOFTWARE VALIDATION: barcode-level yield agreement; restart and fallback cases; measured latency and CPU/memory under stated hardware and workloads. Automated tests provide implementation evidence only.]

Figure 1 shows point errors and paired differences for both the full cohort and the prespecified sensitivity analysis. Detailed feature definitions, provenance, configuration, all comparator summaries and reproduction commands are supplied with the analysis tools.

![Retrospective point errors and paired comparisons](evidence/retrospective/retrospective_comparison.png)

Figure 1. Retrospective reconstruction on report-native inputs. Panels A/C include all 20 runs; B/D exclude the two prespecified configuration errors. Bars show 95% percentile intervals from 2,000 flow-cell-group bootstrap replicates. Axis ranges differ between panels. Negative paired differences favor NanoPredict. Fourteen of the 20 runs overlap deployment training. These are neither independent validation nor measurements of contemporaneous live accuracy.

A subsequent descriptive assessment considered five newly supplied acquisitions after identity screening. Four acquisitions (S26–S29), representing three flow-cell groups with no training flow-cell match, formed the main subset; these cells were also represented among previously scored non-training cases. S30 shared a training flow cell and was assessed separately; S25 duplicated S4 and was not counted again. Whole-run passed-base and read totals reconciled exactly between reports and sequencing summaries. In the four-run subset, NanoPredict MAE was 0.313, 0.137 and 0.009 Gb at 30, 60 and 120 minutes, compared with 0.017, 0.015 and 0.012 Gb for cumulative-rate extrapolation. The models were unchanged. These small, selected retrospective results favor extrapolation at the early checkpoints and do not establish a general forecasting advantage or live accuracy.

## Discussion

NanoPredict integrates early yield forecasting and barcode-level progress with routine monitoring. The retrospective results do not support a general superiority claim over cumulative-rate extrapolation. Apparent advantages in the full cohort were strongly influenced by an erroneous 72-h setting. With the two setting errors excluded, the bundled 30- and 60-minute predictors had larger errors than extrapolation; 120-minute errors were similar. This distinction should remain visible rather than selecting the more favorable analysis. Observed final yield also reflects operator stopping decisions and must not be interpreted as yield attainable under a common fixed duration.

The cohort is small, selected at one site and dominated by yields below 2 Gb. Shared flow cells reduce the number of independent operational groups. Confirmed training overlap precludes treating this cohort as independent validation. Unverified biological relationships, report aggregation, retrospective basecall availability and checkpoint configuration history further constrain interpretation. No model was selected, refitted or recalibrated on these results. Any future model revision requires newly reserved evaluation cases. A prospective phase should test contemporaneous inputs, operational failures and performance under frozen software. An independent installation and evaluation at a second institute would broaden the operational evidence; no such evaluation has yet been completed.

## Data and software availability

**Supplementary Information:** [SUPPLEMENTARY METHODS, TEST DATA AND REPRODUCTION COMMANDS TO ACCOMPANY SUBMISSION]

Source code and packaged anonymous replay data are available in the NanoPredict repository. [ARCHIVE RELEASE AND TEST DATA WITH PERSISTENT IDENTIFIERS AFTER AUTHOR APPROVAL.] Original training scripts, feature exports, split tables and source reports were recovered locally and preserved in a private archive. An aggregate provenance audit records hashes, reconstruction checks and evaluation overlap; original identifiers and source reports are not included in the public repository. Validation data and reproduction scripts: [REPOSITORY/ACCESSION AND DATA-GOVERNANCE STATEMENT].

## Ethics and author contributions

[ETHICS COMMITTEE, APPROVAL OR WAIVER IDENTIFIER, CONSENT BASIS, AND PERMITTED DATA SHARING TO BE PROVIDED BY THE INVESTIGATOR.]

[AUTHOR CONTRIBUTIONS AND FINAL APPROVALS TO BE CONFIRMED. No external-site evaluation is claimed until performed.]

## Acknowledgements and funding

[FUNDING SOURCES AND GRANT NUMBERS, OR CONFIRMED NONE.]

AI assistance was used to help audit the repository, draft text and implement analysis utilities. [AUTHORS TO VERIFY AND FINALIZE DISCLOSURE AND RESPONSIBILITY STATEMENT; ALSO INCLUDE IN COVER LETTER.]

Conflicts of interest: [AUTHOR DECLARATIONS].

## References

Bruno, A., Aury, J.-M. and Engelen, S. (2021) BoardION: real-time monitoring of Oxford Nanopore sequencing instruments. *BMC Bioinformatics*, **22**, 245. [doi:10.1186/s12859-021-04161-0](https://doi.org/10.1186/s12859-021-04161-0).

De Coster, W., D’Hert, S., Schultz, D.T., Cruts, M. and Van Broeckhoven, C. (2018) NanoPack: visualizing and processing long-read sequencing data. *Bioinformatics*, **34**, 2666–2669. [doi:10.1093/bioinformatics/bty149](https://doi.org/10.1093/bioinformatics/bty149).

Leger, A. and Leonardi, T. (2019) pycoQC, interactive quality control for Oxford Nanopore Sequencing. *Journal of Open Source Software*, **4**, 1236. [doi:10.21105/joss.01236](https://doi.org/10.21105/joss.01236).

Munro, R. et al. (2022) minoTour, real-time monitoring and analysis for nanopore sequencers. *Bioinformatics*, **38**, 1133–1135. [doi:10.1093/bioinformatics/btab780](https://doi.org/10.1093/bioinformatics/btab780). Published online 15 November 2021.

Oxford Nanopore Technologies (2026) MinKNOW API: protobuf and gRPC specifications. [Source and documentation](https://github.com/nanoporetech/minknow_api). Accessed 15 October 2026; analysis client version 6.10.3.

Pedregosa, F. et al. (2011) Scikit-learn: Machine Learning in Python. *Journal of Machine Learning Research*, **12**, 2825–2830. [Article](https://jmlr.org/papers/v12/pedregosa11a.html).
