#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List

import numpy as np

from nnue_common import DATASET_DTYPE, compact_json, encode_sample, load_contract


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a binary NNUE dataset cache from self-play CSV files.")
    parser.add_argument("--input", nargs="+", required=True, help="One or more CSV files with eval_fen,score,result columns.")
    parser.add_argument("--output-dir", required=True, help="Directory to write samples.npy and manifest.json into.")
    parser.add_argument("--contract", default=None, help="Optional path to nnue_contract.json.")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of rows to ingest.")
    return parser.parse_args()


def read_rows(paths: List[Path], limit: int) -> np.ndarray:
    rows = []
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            expected = {"eval_fen", "score", "result"}
            if reader.fieldnames is None or not expected.issubset(reader.fieldnames):
                raise ValueError(f"{path} does not contain the required columns {sorted(expected)}")
            for row_index, row in enumerate(reader, start=2):
                try:
                    score = int(row["score"])
                    result = int(row["result"])
                    encoded = encode_sample(row["eval_fen"], score, result)
                except Exception as exc:
                    raise ValueError(f"{path}:{row_index}: {exc}") from exc
                if result not in (-1, 0, 1):
                    raise ValueError(f"{path}:{row_index}: result must be -1, 0 or 1")
                rows.append(encoded)
                if limit > 0 and len(rows) >= limit:
                    return np.asarray(rows, dtype=DATASET_DTYPE)
    return np.asarray(rows, dtype=DATASET_DTYPE)


def main() -> int:
    args = parse_args()
    contract = load_contract(Path(args.contract) if args.contract else None)
    input_paths = [Path(path) for path in args.input]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = read_rows(input_paths, args.limit)
    np.save(output_dir / "samples.npy", samples, allow_pickle=False)

    manifest = {
        "format": "chilo.nnue_dataset.v1",
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "architecture": contract["architecture"],
        "sample_count": int(samples.shape[0]),
        "max_pieces": int(contract["max_pieces"]),
        "dtype_descr": samples.dtype.descr,
        "sources": [str(path) for path in input_paths],
    }
    if samples.shape[0] > 0:
        manifest["score_min"] = int(samples["score"].min())
        manifest["score_max"] = int(samples["score"].max())
        manifest["result_counts"] = {
            "-1": int((samples["result"] == -1).sum()),
            "0": int((samples["result"] == 0).sum()),
            "1": int((samples["result"] == 1).sum()),
        }
    else:
        manifest["score_min"] = 0
        manifest["score_max"] = 0
        manifest["result_counts"] = {"-1": 0, "0": 0, "1": 0}

    (output_dir / "manifest.json").write_text(compact_json(manifest), encoding="utf-8")
    print(f"Wrote {samples.shape[0]} sample(s) to {output_dir / 'samples.npy'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
