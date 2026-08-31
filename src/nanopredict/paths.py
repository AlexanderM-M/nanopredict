"""Resolve application resources in a source or editable installation."""

from __future__ import annotations

import os
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"


def models_dir() -> Path:
    return Path(
        os.environ.get(
            "NANOPREDICT_MODELS_DIR", DATA_DIR / "models"
        )
    )


def diagnostic_reference() -> Path:
    return Path(
        os.environ.get(
            "NANOPREDICT_DIAGNOSTIC_REFERENCE",
            DATA_DIR / "diagnostic_reference.json",
        )
    )


def replay_features() -> Path:
    return Path(
        os.environ.get(
            "NANOPREDICT_REPLAY_FEATURES",
            DATA_DIR / "replay_features_anonymous.csv",
        )
    )


def nanodx_cpg_targets() -> Path:
    return Path(
        os.environ.get(
            "NANOPREDICT_NANODX_TARGETS",
            DATA_DIR / "nanodx_capper_hg38.tsv.gz",
        )
    )


def static_dir() -> Path:
    return PACKAGE_DIR / "static"


def state_dir() -> Path:
    override = os.environ.get("NANOPREDICT_STATE_DIR")
    if override:
        path = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        path = base / "NanoporePredictor"
    else:
        path = Path.home() / ".local" / "state" / "nanopredict"
    path.mkdir(parents=True, exist_ok=True)
    return path
