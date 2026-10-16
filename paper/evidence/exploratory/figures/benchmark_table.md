# EXPLORATORY anonymous-group cross-validation; NOT independent validation

All methods use the same complete-case comparison set at each horizon. Native availability is in metrics.csv.

| Minutes | Method | N | MAE Gb | RMSE Gb | 90% coverage | Mean width Gb | Unbounded 90% intervals |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | train_median | 31 | 0.379 | 0.507 | 0.935 | 1.629 | 0 |
| 30 | train_mean | 31 | 0.345 | 0.418 | 1.000 | 1.898 | 0 |
| 30 | linear_planned | 31 | 0.824 | 2.719 | 0.871 | 1.535 | 0 |
| 30 | recent_planned | 31 | 1.009 | 3.567 | 1.000 | inf | 31 |
| 30 | ridge | 31 | 0.226 | 0.266 | 1.000 | 1.488 | 0 |
| 30 | extra_trees | 31 | 0.282 | 0.429 | 1.000 | 1.430 | 0 |
| 60 | train_median | 160 | 0.417 | 0.826 | 0.944 | 1.610 | 0 |
| 60 | train_mean | 160 | 0.550 | 0.807 | 0.950 | 1.925 | 0 |
| 60 | linear_planned | 160 | 0.356 | 1.587 | 0.931 | 1.256 | 0 |
| 60 | recent_planned | 160 | 0.398 | 1.899 | 0.912 | 1.468 | 0 |
| 60 | ridge | 160 | 0.238 | 0.464 | 0.969 | 1.202 | 0 |
| 60 | extra_trees | 160 | 0.183 | 0.432 | 0.938 | 0.991 | 0 |
| 120 | train_median | 160 | 0.417 | 0.826 | 0.944 | 1.610 | 0 |
| 120 | train_mean | 160 | 0.550 | 0.807 | 0.950 | 1.925 | 0 |
| 120 | linear_planned | 160 | 0.361 | 1.720 | 0.919 | 1.338 | 0 |
| 120 | recent_planned | 160 | 0.401 | 2.013 | 0.931 | 1.634 | 0 |
| 120 | ridge | 160 | 0.227 | 0.458 | 0.963 | 1.198 | 0 |
| 120 | extra_trees | 160 | 0.178 | 0.407 | 0.963 | 0.935 | 0 |

Unbounded intervals are vacuous and contribute to empirical coverage. High coverage alone is not calibration evidence.
