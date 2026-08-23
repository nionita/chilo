#!/usr/bin/env python3
"""Create a deterministic, FEN-disjoint reservoir sample from a collector CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_new_file(path: Path, description: str) -> None:
    if path.exists():
        raise ValueError(f"{description} already exists: {path}")
    if not path.parent.is_dir():
        raise ValueError(f"{description} parent directory does not exist: {path.parent}")


def write_csv(path: Path, rows: list[tuple[str, str, str]]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise ValueError(f"temporary output already exists: {temporary}")
    with temporary.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["eval_fen", "score", "result"])
        writer.writerows(rows)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sample one new FEN-disjoint futility corpus from a collector CSV."
    )
    parser.add_argument("--source", type=Path, required=True, help="Headered collector CSV")
    parser.add_argument("--exclude", type=Path, required=True, help="One existing corpus CSV")
    parser.add_argument("--output", type=Path, required=True, help="New corpus CSV; must not exist")
    parser.add_argument("--metadata", type=Path, required=True, help="Provenance JSON; must not exist")
    parser.add_argument("--seed", type=int, required=True, help="Deterministic random seed")
    parser.add_argument("--count", type=int, default=25_000, help="Positions to retain (default: 25000)")
    args = parser.parse_args()

    if args.count <= 0:
        parser.error("--count must be positive")
    if args.output.resolve() == args.metadata.resolve():
        parser.error("--output and --metadata must differ")
    require_new_file(args.output, "output")
    require_new_file(args.metadata, "metadata")

    with args.exclude.open(newline="") as handle:
        excluded = {row["eval_fen"] for row in csv.DictReader(handle)}

    rng = random.Random(args.seed)
    sample: list[tuple[str, str, str]] = []
    selected_fens: set[str] = set()
    selection_events = 0
    source_rows = 0
    skipped_existing = 0
    skipped_selected = 0
    with args.source.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["eval_fen", "score", "result"]:
            raise ValueError(f"unexpected source header: {reader.fieldnames}")
        for row in reader:
            source_rows += 1
            fen = row["eval_fen"]
            if fen in excluded:
                skipped_existing += 1
                continue
            if fen in selected_fens:
                skipped_selected += 1
                continue
            selection_events += 1
            item = (fen, row["score"], row["result"])
            if len(sample) < args.count:
                sample.append(item)
                selected_fens.add(fen)
            else:
                slot = rng.randrange(selection_events)
                if slot < args.count:
                    selected_fens.remove(sample[slot][0])
                    sample[slot] = item
                    selected_fens.add(fen)

    if len(sample) != args.count:
        raise ValueError(f"only {len(sample)} eligible rows for requested {args.count}")
    sampled_fens = [item[0] for item in sample]
    duplicate_fens = len(sampled_fens) - len(set(sampled_fens))
    overlap_fens = len(set(sampled_fens) & excluded)
    if duplicate_fens or overlap_fens:
        raise ValueError(
            f"sample integrity failure: duplicate_fens={duplicate_fens}, overlap_fens={overlap_fens}"
        )

    write_csv(args.output, sample)
    metadata = {
        "source": str(args.source),
        "source_rows": source_rows,
        "selection_events": selection_events,
        "sample_rows": len(sample),
        "seed": args.seed,
        "method": "reservoir_sampling_v1_excluding_prior_and_selected_fens",
        "excluded_corpus": str(args.exclude),
        "excluded_corpus_sha256": sha256_file(args.exclude),
        "excluded_fens": len(excluded),
        "skipped_existing_fens": skipped_existing,
        "skipped_selected_fens": skipped_selected,
        "duplicate_fens": duplicate_fens,
        "overlap_fens": overlap_fens,
        "output_sha256": sha256_file(args.output),
    }
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
