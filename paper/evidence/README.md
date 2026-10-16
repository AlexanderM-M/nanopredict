# Evidence produced on this cluster

The inventory and exploratory analysis describe the cloned assets and newly retrained comparators. They are not a reproduction of the missing historical analysis and do not independently validate the bundled models.

## Verified software checks

Python 3.11 editable installation succeeded. The original checkout passed 37 tests (`baseline_tests.txt`). After the preparation changes, 48 tests passed (`tests.txt`): the existing suite with its corrected provenance-message assertion, eight benchmark validity checks, and three comparison/resource utility checks. Dependency consistency and Python compilation checks passed. CI declares Linux and Windows Python 3.11 jobs; this session executed Linux only.

`reproduction.json` records a second run with identical prediction, metric, assignment and metadata files in the same environment. This demonstrates deterministic execution, not independent replication. Model/data hashes are in `inventory.json`; dependency versions are in `../environment-freeze.txt`.

## Interpretation of exploratory outputs

The five-fold analysis trains new models on the anonymous subset. Each horizon has 171 eligible replay labels; method availability varies. The intersection for all six methods contains only 31 labels at 30 minutes and 160 at 60 and 120 minutes. The restricted 30-minute comparison is especially unrepresentative because recent rates are missing in most histories. Review native-availability and common-case rows together in `exploratory/metrics.csv`.

The recent-rate baseline has unbounded 90% intervals for all 31 available 30-minute predictions because its finite calibration pool is too small. Their resulting 100% coverage is vacuous. The table exposes these counts and the plot explicitly includes unbounded intervals. Other high empirical coverage values and apparent error differences also remain exploratory, conditional on unknown related-run dependence, historical feature definitions and stopping decisions. They cannot resolve the earlier chronological benchmark findings.

## Continuation checks on 12 October 2026

The earlier 48-test state was reproduced before changes. The extended suite passes 67 tests; see [continuation_tests.txt](continuation_tests.txt) and [continuation_execution.json](continuation_execution.json). Synthetic end-to-end export, frozen scoring, rendering, 40-feature comparison and Linux process sampling smoke checks passed. Model/replay blob history is recorded in [provenance_history.json](provenance_history.json). No real study export is included. Earlier execution records and exploratory outputs are retained as historical development evidence; their recorded source hashes refer to the original preparation implementation.

## Local material qualification continuation

[Retrospective BAM header checks](retrospective_bam_headers.json) cover four explicitly approved candidates: all fail the existing hg38 header gate and therefore cannot supply direct agreement inputs for the current counter. Only headers/EOF markers were read; there was no read scan or full BAM checksum. Source paths and raw headers remain private.
