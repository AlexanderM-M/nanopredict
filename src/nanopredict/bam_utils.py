"""Generic BAM completion, barcode and reference-header helpers."""
from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Any

_BGZF_EOF = bytes.fromhex("1f8b08040000000000ff0600424302001b0003000000000000000000")
_BARCODE_PATTERN = re.compile(r"(?<![a-z0-9])(barcode\d{1,3}|unclassified)(?![a-z0-9])", re.I)

def _normalise_barcode(value: Any) -> str | None:
    match = _BARCODE_PATTERN.search(str(value or ""))
    return match.group(1).lower() if match else None


def _path_barcode(path: Path) -> str | None:
    for part in reversed(Path(path).parts):
        barcode = _normalise_barcode(part)
        if barcode:
            return barcode
    return None


def _read_barcode(read: Any, fallback: str | None) -> str | None:
    for tag in ("BC", "RG"):
        try:
            barcode = _normalise_barcode(read.get_tag(tag))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if barcode:
            return barcode
    return fallback


def _reference_lengths(alignment: Any) -> list[tuple[str, int]]:
    """Read reference lengths from bamnostic/pysam or a small test double."""
    names = getattr(alignment, "references", None)
    lengths = getattr(alignment, "lengths", None)
    if names is not None and lengths is not None:
        return [(str(name), int(length)) for name, length in zip(names, lengths)]

    header = getattr(alignment, "header", {})
    sequences = header.get("SQ", []) if hasattr(header, "get") else []
    if sequences:
        return [
            (str(sequence["SN"]), int(sequence["LN"]))
            for sequence in sequences
        ]

    # Kept for the deliberately minimal test alignment used by this project.
    pairs = []
    for value in getattr(header, "values", lambda: [])():
        if isinstance(value, (tuple, list)) and len(value) == 2:
            pairs.append((str(value[0]), int(value[1])))
    return pairs


def _bam_is_complete(path: Path) -> bool:
    try:
        if path.stat().st_size < len(_BGZF_EOF):
            return False
        with path.open("rb") as handle:
            handle.seek(-len(_BGZF_EOF), os.SEEK_END)
            return handle.read() == _BGZF_EOF
    except OSError:
        return False
