"""Duration-aware yield extrapolation from cumulative counters only.

The sampling interval and window-local QC statistics are deliberately absent.
Decay is a development-selected assumption, not a measured pore lifetime.
"""
from __future__ import annotations

import math

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.utils.validation import check_is_fitted

FEATURE_COLUMNS = (
    'observed_passed_bases',
    'observed_through_seconds',
    'planned_run_limit_hours',
)


class DurationYieldRegressor(RegressorMixin, BaseEstimator):
    """Observed yield + average passed rate * effective remaining hours.

With no half-life this is ordinary cumulative-rate extrapolation. A finite
half-life applies exponential decline from the current average rate. Optional
scale fitting minimizes weighted absolute yield error on fitting rows only.
An outcome-dependent stopping policy is not modeled by this construction.
"""

    def __init__(self, half_life_hours=None, learn_scale=False):
        self.half_life_hours = half_life_hours
        self.learn_scale = learn_scale

    def _components(self, X):
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != len(FEATURE_COLUMNS):
            raise ValueError('Require passed bases, observed seconds and planned hours')
        if not np.isfinite(X).all() or (X[:, 0] < 0).any() or (X[:, 1:] <= 0).any():
            raise ValueError('Finite nonnegative passed bases and positive observed time/planned duration required')
        observed = X[:, 0] / 1e9
        elapsed = X[:, 1] / 3600
        remaining = np.maximum(X[:, 2] - elapsed, 0)
        if self.half_life_hours is not None:
            if not math.isfinite(self.half_life_hours) or self.half_life_hours <= 0:
                raise ValueError('Half-life must be positive and finite')
            decay = math.log(2) / self.half_life_hours
            remaining = -np.expm1(-decay * remaining) / decay
        return observed, observed / elapsed * remaining

    def fit(self, X, y, sample_weight=None):
        observed, additional = self._components(X)
        y = np.asarray(y, dtype=float)
        if y.shape != observed.shape or not np.isfinite(y).all() or (y < observed).any():
            raise ValueError('Final yield must be finite and at least observed yield')
        weights = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, dtype=float)
        if weights.shape != y.shape or not np.isfinite(weights).all() or (weights <= 0).any():
            raise ValueError('Sample weights must be positive and finite')
        self.scale_ = 1.0
        if self.learn_scale:
            active = additional > 0
            if not active.any():
                raise ValueError('No positive remaining production to fit')
            ratios = (y[active] - observed[active]) / additional[active]
            order = np.argsort(ratios, kind='stable')
            mass = (weights[active] * additional[active])[order]
            median = ratios[order][np.searchsorted(np.cumsum(mass), mass.sum() / 2)]
            # A prespecified guard against an unstable unconstrained multiplier.
            self.scale_ = float(np.clip(median, 0, 2))
        self.n_features_in_ = len(FEATURE_COLUMNS)
        return self

    def predict(self, X):
        check_is_fitted(self, 'scale_')
        observed, additional = self._components(X)
        result = observed + self.scale_ * additional
        if not np.isfinite(result).all():
            raise ValueError('Non-finite duration forecast')
        return result
