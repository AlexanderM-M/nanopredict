# Matched live features and timing checks

## Feature definitions and availability

The prospective study export stores the exact 40 numerical model inputs at receipt, including missing values, together with source observation time and prediction-ready time. It does not expose raw RPC messages or infer when unobserved internal statistics first became available. Basecalling version/model, chemistry, plan changes and site settings must additionally be recorded in the controlled registry.

Copy `templates/feature_contract.json` privately. Its units are derived from the current formulas; all definition IDs start as `UNVERIFIED`. Map each feature to a reviewed historical definition specifying units, denominator, sampling interval, aggregation and cutoff semantics. Assign a common versioned definition ID only after the mapping is justified. Numeric equality alone must not create a verified definition. For field-specific tolerances, compare separate feature subsets with prespecified tolerances, preserving the complete set in the final report.

```bash
python tools/paper/export_study_features.py --study-export /restricted/study-export.json --contract /restricted/feature_contract.json --output /restricted/live_features.csv
python tools/paper/compare_features.py --live /restricted/live_features.csv --historical /restricted/historical_features.csv --output /restricted/feature_comparison.csv --atol 0 --rtol 0
```

Both feature tables require `run_code,horizon_minutes,feature,value,unit,definition_id,observed_through_seconds,available_at_utc,checkpoint_at_utc`. There must be one row per matched run/checkpoint/feature. Use an empty numeric value for missing data and an empty availability time when unknown; do not infer dates from anonymous labels. Historical extraction from a completed report can be compared numerically but does not establish that its values existed at the live checkpoint. The tool reports value differences, missingness discordance, definition/unit agreement, future observation flags, availability lags and checkpoint timestamp agreement. It does not issue an automatic validity verdict.

Qualify 600-second versus 1,800-second resolution, late starts, changed run plans/filters, clearing basecalling backlog, sparse boxplots, temperatures, duty-time group mappings and pore scans around boundaries. The zero target-temperature placeholder remains unresolved and must not be described as a physical setpoint. A failed parity check requires investigation and, if definitions change, a newly frozen prospective phase.

## Latency and resources

Instrument actual source, completed-BAM, discovery, processing and browser-display events using `templates/latency_events.csv`, retaining synchronization error and software/hardware conditions in the site log. The headless recorder has no browser-display event; use prediction readiness as the headless endpoint and keep dashboard measurements as a separate qualification experiment. Do not manufacture display timestamps for the headless mode. The latency script requires a fully observed five-stage dashboard trace; it reports component and end-to-end median/p95/max and rejects negative times or duplicate event keys.

```bash
python tools/paper/analyze_latency.py --events /restricted/latency_events.csv --output /restricted/latency-summary
python tools/paper/profile_process.py --pid PROCESS_PID --seconds 600 --interval 1 --output /restricted/resource_samples.csv
```

The process sampler is Linux-only and records summed RSS and lifetime CPU seconds for the currently visible process tree. Short-lived child processes between samples and exited children can be missed; shared memory may be counted more than once. It stops on root PID reuse or disappearance. On Windows use a site-approved process-tree profiler and record its semantics. The finite-command wrapper reports POSIX child usage and maximum RSS, not simultaneous process-tree peak memory. Compare with/without monitoring, cold/warm cache, one/multiple positions and barcode counts under recorded hardware and batching settings.
