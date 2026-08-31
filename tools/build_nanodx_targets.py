#!/usr/bin/env python3
"""Build the packaged hg38 NanoDx CpG target table from pinned source assets."""

from __future__ import annotations

import argparse
import gzip
import re
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChainBlock:
    source_start: int
    source_end: int
    target_name: str
    target_start: int
    target_end: int
    reverse: bool


def load_chains(path: Path) -> dict[str, tuple[list[int], list[ChainBlock]]]:
    blocks: dict[str, list[ChainBlock]] = {}
    with gzip.open(path, "rt", encoding="ascii") as handle:
        lines = iter(handle)
        for line in lines:
            if not line.startswith("chain "):
                continue
            fields = line.split()
            source_name = fields[2]
            source_start = int(fields[5])
            target_name = fields[7]
            target_size = int(fields[8])
            target_strand = fields[9]
            target_start = int(fields[10])
            source_cursor = source_start
            target_cursor = target_start
            for block_line in lines:
                block_fields = block_line.split()
                if not block_fields:
                    break
                size = int(block_fields[0])
                if target_strand == "+":
                    mapped_start = target_cursor
                    mapped_end = target_cursor + size
                    reverse = False
                else:
                    mapped_start = target_size - (target_cursor + size)
                    mapped_end = target_size - target_cursor
                    reverse = True
                blocks.setdefault(source_name, []).append(
                    ChainBlock(
                        source_start=source_cursor,
                        source_end=source_cursor + size,
                        target_name=target_name,
                        target_start=mapped_start,
                        target_end=mapped_end,
                        reverse=reverse,
                    )
                )
                if len(block_fields) == 1:
                    break
                source_cursor += size + int(block_fields[1])
                target_cursor += size + int(block_fields[2])
    result = {}
    for name, chrom_blocks in blocks.items():
        ordered = sorted(chrom_blocks, key=lambda block: block.source_start)
        result[name] = ([block.source_start for block in ordered], ordered)
    return result


def lift_interval(
    chains: dict[str, tuple[list[int], list[ChainBlock]]],
    chrom: str,
    start: int,
    end: int,
) -> tuple[str, int, int] | None:
    index = chains.get(chrom)
    if index is None:
        return None
    starts, blocks = index
    candidate = bisect_right(starts, start) - 1
    if candidate < 0:
        return None
    block = blocks[candidate]
    if end > block.source_end:
        return None
    left = start - block.source_start
    right = end - block.source_start
    if block.reverse:
        mapped_start = block.target_end - right
        mapped_end = block.target_end - left
    else:
        mapped_start = block.target_start + left
        mapped_end = block.target_start + right
    return block.target_name, mapped_start, mapped_end


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--chain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    features = {
        match.decode("ascii")
        for match in re.findall(rb"cg[0-9]{8}", args.model.read_bytes())
    }
    chains = load_chains(args.chain)
    lifted: list[tuple[str, int, int, str]] = []
    source_count = 0
    with args.mapping.open(encoding="ascii") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 4 or fields[3] not in features:
                continue
            source_count += 1
            mapped = lift_interval(chains, fields[0], int(fields[1]), int(fields[2]))
            if mapped is not None:
                lifted.append((*mapped, fields[3]))

    lifted.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(b"#assembly=hg38\tmodel=Capper_et_al\tsource=nanoDx-crossNN\n")
            for chrom, start, end, probe in lifted:
                zipped.write(f"{chrom}\t{start}\t{end}\t{probe}\n".encode("ascii"))

    print(f"Model features in hg19 mapping: {source_count}")
    print(f"Features lifted to hg38: {len(lifted)}")
    print(f"Unmapped features: {source_count - len(lifted)}")


if __name__ == "__main__":
    main()
