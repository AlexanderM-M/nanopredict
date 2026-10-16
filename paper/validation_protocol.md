# Validation procedures and prospective collection plan

The operational specification is now [independent_protocol.md](independent_protocol.md), implemented by the silent study recorder and frozen evaluator; see [operator_instructions.md](operator_instructions.md). The detailed matched-comparison commands are in [matched_validation.md](matched_validation.md). This document specifies qualification for the yield-focused paper.

The repository supplies mock and synthetic tests. The following procedures require real matched inputs and prospectively recorded events before supporting operational or scientific claims. Empty CSV templates in `templates/` define the collection fields; they contain no invented runs or dates.

## Freeze and consecutive pilot

An initial pilot of approximately 20–30 consecutive eligible MinION runs can test feasibility, missingness and failure handling. This is a planning suggestion, not a journal requirement, sample-size calculation or sufficient demonstration of interval/probability calibration. Define eligibility before enrolment, retain an enrolment/exclusion log, and record failures and intentional stops as well as scheduled completions. Predict silently without influencing run decisions; record whether outputs were actually hidden and any deviations.

Before the first run, record the Nanopredict commit, environment, model hashes, yield targets, checkpoint rules, Core/API versions, basecaller model, chemistry and pass filter. Freeze the estimator and its calibration; do not tune or recalibrate on pilot outcomes. If code changes are necessary, log the reason and start a separately labelled phase. Define primary metrics, acceptable error/coverage precision and required sample size for a subsequent validation study before inspecting pilot performance. Keep model-independent baselines under the same timing constraints.

Use `run_registry.csv` with coded run IDs and stable related-run group IDs. Link reused flow cells, repeated libraries, samples and restarts within the controlled registry; do not expose identifying source paths in shareable outputs. A governance decision is needed on shareable derived data and any underlying human sequencing information [OWNER TO COMPLETE]. Preserve eligibility, outcome availability, stop reasons and timing even when a run lacks a checkpoint. A two-hour survivor cohort must not silently replace all enrolled runs.

## Yield and timing

The primary candidate endpoint is observed final passed yield under routine operation, conditional on the run having reached the specified checkpoint. Record actual ending time and scheduled, intentional, failed or other/unknown stop reason. Define a separate fixed-duration endpoint only when yield at that time is observed; an intentional stop makes counterfactual continued yield unobserved, not zero. Report endpoint/stop strata descriptively without post-hoc favourable selection.

At 30, 60 and 120 minutes, persist the numerical feature vector, missingness, source observation time, collection wall time, output time, model hash, point forecast, 80/90/95% intervals and target probabilities. `checkpoint_events.csv` complements the feature-schema CSV; it is not a substitute for the features. Mark late-start reconstructions explicitly. Anonymous dashboard reports alone do not retain the linkage and feature history needed for this study.

After completion and basecalling drain, obtain final passed bases from a frozen specified source and reconcile against an independent read/base summary using the same pass and primary-read definitions. Keep disagreements and absent outcomes visible. Score frozen predictions and prespecified baselines without refitting. Use run/related-group resampling for confidence intervals, show every checkpoint denominator and event count, and avoid pooled snapshot sample sizes. Report uncertainty coverage and width with uncertainty on the coverage estimates; a small pilot should emphasize descriptive feasibility rather than a calibration claim.

## Barcodes and BAM fallback

Use known synthetic mixtures plus real completed multiplexed batches. Exercise BC and RG tags separately and in conflict, directory-only assignments, zero-padded names, unclassified reads, unknown/no assignment and barcodes absent from one export. Confirm implemented precedence (BC then RG then directory) matches the intended demultiplexer. Do not silently merge missing assignment into a known barcode. Compare primary-read passed/failed bases against an independent counter; sum barcode bases with an explicit unassigned remainder at matched file boundaries.

Exercise API loss, incompatible RPCs, missing optional statistics, fallback activation, reconnection, simultaneous positions and new runs. Confirm forecasts are unavailable for BAM fallback, PromethION and individual barcodes. Compare completed-file totals with API totals only after accounting for flush/basecalling delay. The current failed-BAM detector partly uses path names; include adversarial names and record any misclassification before claiming reliable parity.

## Restarts and file integrity

For each fixture compare continuous processing with graceful restart and forced process interruption before/after file completion and state save. Cover incomplete BGZF, valid EOF marker, truncated/corrupt state, unavailable persistence, new runs on the same position, and changes to yield targets. Verify no duplicate primary bases, correct checkpoint reset, stable barcodes and explicitly defined ETA recovery.

The current file fingerprint uses resolved path, size and mtime, not content identity. Copied, renamed or touched BAMs can be processed again. Test these cases and surface failures; persisted progress alone does not prove content deduplication.

## Latency and resource use

Synchronize clocks and record clock error. Decompose source event to BAM completion, completion to discovery, scan/feature extraction, prediction generation and browser display. The default 20-second scan interval and BAM batching contribute separately. Log source event, statistics availability, collection start, prediction readiness and dashboard visibility; reject unexplained negative latencies. Use a monotonic clock for within-process durations and UTC for cross-process linkage. Report median, p95, maximum and denominator by hardware, batch size, barcode count and concurrent positions, including cold start/backlog and steady state.

For a finite replay or fixture command, the resource helper records wall time, child CPU time, peak RSS and exit status:

```bash
.venv/bin/python tools/paper/measure_resources.py --output /path/to/resources.json -- .venv/bin/python -m unittest discover -s tests -v
```

This example measures a test command, not sequencing overhead. For real monitoring, sample the full process tree at a fixed recorded interval using an approved OS profiler, capturing aggregate RSS/CPU, I/O, state growth and UI responsiveness. Measure with/without monitoring under matched workloads; log CPU/RAM/storage, OS, Core version, API and file-cache conditions. Report MinKNOW backlog separately from Nanopredict resource usage. Retain raw traces and profiler versions. Real latency/resource values remain [PENDING].

## Acceptance and reporting

Use `validation_cases.csv` to record expected versus observed behaviour, evidence hashes, versions and failures. Structural expectations such as no processing of incomplete BAMs and no cross-run state contamination are exact; scientific error tolerances and operational latency limits require prospective justification. Freeze those criteria before executing confirmatory tests. A passing mock suite, replay demo or one matching yield total must not be reported as comprehensive live validation.
