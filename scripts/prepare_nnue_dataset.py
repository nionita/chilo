#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path
from typing import Dict, List

import numpy as np

from nnue_common import (
    DATASET_DTYPE,
    DATASET_FORMAT,
    DATASET_MANIFEST_NAME,
    SHARD_DIR_NAME,
    assign_shard_splits,
    compact_json,
    encode_sample,
    json_dtype_descr,
    load_contract,
)

EXPECTED_COLUMNS = ("eval_fen", "score", "result")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a sharded NNUE dataset cache from self-play CSV files.")
    parser.add_argument("--input", nargs="+", required=True, help="One or more CSV files with eval_fen,score,result columns.")
    parser.add_argument("--output-dir", required=True, help="Dataset root directory for manifest.json and shards/.")
    parser.add_argument("--contract", default=None, help="Optional path to nnue_contract.json.")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of rows to ingest.")
    parser.add_argument("--samples-per-shard", type=int, default=1000000, help="Maximum sample count per output shard.")
    parser.add_argument("--validation-fraction", type=float, default=0.05, help="Fraction of shards reserved for validation.")
    parser.add_argument("--seed", type=int, default=1, help="Seed used for deterministic shard split assignment.")
    parser.add_argument("--report-every", type=int, default=100000, help="Print a progress line every N processed rows.")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output directory if it already contains data.")
    return parser.parse_args()


def ensure_output_dir(output_dir: Path, overwrite: bool) -> Path:
    manifest_path = output_dir / DATASET_MANIFEST_NAME
    shard_dir = output_dir / SHARD_DIR_NAME
    if manifest_path.exists() or shard_dir.exists():
        if not overwrite:
            raise SystemExit(
                f"{output_dir} already contains a dataset manifest or shards; rerun with --overwrite to replace it."
            )
        if manifest_path.exists():
            manifest_path.unlink()
        if shard_dir.exists():
            shutil.rmtree(shard_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    return shard_dir


def finalize_shard(
    shard_dir: Path,
    shard_index: int,
    buffer: List[np.void],
    shard_metas: List[Dict[str, object]],
) -> None:
    if not buffer:
        return

    shard_array = np.asarray(buffer, dtype=DATASET_DTYPE)
    shard_name = f"shard_{shard_index:06d}.npy"
    shard_path = shard_dir / shard_name
    np.save(shard_path, shard_array, allow_pickle=False)
    shard_metas.append(
        {
            "index": shard_index,
            "path": f"{SHARD_DIR_NAME}/{shard_name}",
            "sample_count": int(shard_array.shape[0]),
            "score_min": int(shard_array["score"].min()),
            "score_max": int(shard_array["score"].max()),
            "result_counts": {
                "-1": int((shard_array["result"] == -1).sum()),
                "0": int((shard_array["result"] == 0).sum()),
                "1": int((shard_array["result"] == 1).sum()),
            },
        }
    )
    buffer.clear()


def main() -> int:
    args = parse_args()
    if args.samples_per_shard <= 0:
        raise SystemExit("--samples-per-shard must be positive.")
    if args.validation_fraction < 0.0 or args.validation_fraction >= 1.0:
        raise SystemExit("--validation-fraction must be in the range [0.0, 1.0).")
    if args.report_every <= 0:
        raise SystemExit("--report-every must be positive.")

    contract = load_contract(Path(args.contract) if args.contract else None)
    input_paths = [Path(path) for path in args.input]
    output_dir = Path(args.output_dir)
    shard_dir = ensure_output_dir(output_dir, args.overwrite)

    total_samples = 0
    buffer: List[np.void] = []
    shard_index = 0
    shard_metas: List[Dict[str, object]] = []
    score_min = None
    score_max = None
    result_counts = {"-1": 0, "0": 0, "1": 0}

    for path in input_paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            sniffer = csv.Sniffer()
            has_header = sniffer.has_header(sample) if sample else False

            if has_header:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None or tuple(reader.fieldnames[:3]) != EXPECTED_COLUMNS:
                    raise ValueError(f"{path} does not contain the required columns {list(EXPECTED_COLUMNS)}")
                row_iter = (
                    (row_index, row["eval_fen"], row["score"], row["result"])
                    for row_index, row in enumerate(reader, start=2)
                )
            else:
                reader = csv.reader(handle)
                def iter_headerless_rows():
                    for row_index, row in enumerate(reader, start=1):
                        if not row:
                            continue
                        if len(row) != 3:
                            raise ValueError(f"{path}:{row_index}: expected exactly 3 columns in headerless input")
                        yield row_index, row[0], row[1], row[2]
                row_iter = iter_headerless_rows()

            for row_index, eval_fen, score_text, result_text in row_iter:
                try:
                    score = int(score_text)
                    result = int(result_text)
                    encoded = encode_sample(eval_fen, score, result)
                except Exception as exc:
                    raise ValueError(f"{path}:{row_index}: {exc}") from exc

                if result not in (-1, 0, 1):
                    raise ValueError(f"{path}:{row_index}: result must be -1, 0 or 1")

                buffer.append(encoded)
                total_samples += 1
                score_min = score if score_min is None else min(score_min, score)
                score_max = score if score_max is None else max(score_max, score)
                result_counts[str(result)] += 1

                if len(buffer) >= args.samples_per_shard:
                    finalize_shard(shard_dir, shard_index, buffer, shard_metas)
                    shard_index += 1

                if total_samples % args.report_every == 0:
                    print(f"processed {total_samples} samples, wrote {len(shard_metas)} shard(s)")

                if args.limit > 0 and total_samples >= args.limit:
                    break

        if args.limit > 0 and total_samples >= args.limit:
            break

    if buffer:
        finalize_shard(shard_dir, shard_index, buffer, shard_metas)

    splits = assign_shard_splits(len(shard_metas), args.validation_fraction, args.seed)
    split_counts = {"train": 0, "val": 0}
    split_samples = {"train": 0, "val": 0}
    for shard_meta, split in zip(shard_metas, splits):
        shard_meta["split"] = split
        split_counts[split] += 1
        split_samples[split] += int(shard_meta["sample_count"])

    manifest = {
        "format": DATASET_FORMAT,
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "architecture": contract["architecture"],
        "dtype_descr": json_dtype_descr(DATASET_DTYPE),
        "max_pieces": int(contract["max_pieces"]),
        "total_samples": total_samples,
        "total_shards": len(shard_metas),
        "samples_per_shard": args.samples_per_shard,
        "validation_fraction": args.validation_fraction,
        "split_seed": args.seed,
        "sources": [str(path) for path in input_paths],
        "score_min": int(score_min) if score_min is not None else 0,
        "score_max": int(score_max) if score_max is not None else 0,
        "result_counts": result_counts,
        "split_counts": {
            "train_shards": split_counts["train"],
            "val_shards": split_counts["val"],
            "train_samples": split_samples["train"],
            "val_samples": split_samples["val"],
        },
        "shards": shard_metas,
    }
    (output_dir / DATASET_MANIFEST_NAME).write_text(compact_json(manifest), encoding="utf-8")
    print(
        f"Wrote {total_samples} sample(s) across {len(shard_metas)} shard(s) to {output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
