#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

from nnue_common import (
    build_seeded_weights,
    compact_json,
    integer_model_eval,
    iter_dataset_records,
    load_contract,
    load_dataset_manifest,
    relative_feature,
)


def load_torch_checkpoint(path: Path) -> Tuple[Dict[str, object], Dict[str, np.ndarray | int]]:
    try:
        import torch
    except ImportError as exc:
        raise SystemExit("PyTorch is required to export from a training checkpoint.") from exc

    checkpoint = torch.load(path, map_location="cpu")
    if "contract" not in checkpoint or "state_dict" not in checkpoint:
        raise SystemExit("Checkpoint does not contain the expected contract/state_dict fields.")
    contract = checkpoint["contract"]
    state_dict = checkpoint["state_dict"]
    weights = {
        "input_weights": state_dict["input_weights"].detach().cpu().numpy(),
        "hidden_bias": state_dict["hidden_bias"].detach().cpu().numpy(),
        "output_weights": state_dict["output_weights"].detach().cpu().numpy(),
        "output_bias": float(state_dict["output_bias"].detach().cpu().numpy().reshape(-1)[0]),
    }
    return contract, weights


def quantize_weights(weights: Dict[str, np.ndarray | int]) -> Dict[str, np.ndarray | int]:
    quantized = {}
    for name in ("input_weights", "hidden_bias", "output_weights"):
        rounded = np.rint(np.asarray(weights[name], dtype=np.float64))
        if np.any(rounded < np.iinfo(np.int16).min) or np.any(rounded > np.iinfo(np.int16).max):
            raise SystemExit(f"{name} does not fit in int16 after rounding; export refused.")
        quantized[name] = rounded.astype(np.int16)

    output_bias = int(round(float(weights["output_bias"])))
    if output_bias < np.iinfo(np.int16).min or output_bias > np.iinfo(np.int16).max:
        raise SystemExit("output_bias does not fit in int16 after rounding; export refused.")
    quantized["output_bias"] = output_bias
    return quantized


def validate_dataset(dataset_path: Path, contract: Dict[str, object], float_weights, quantized_weights, tolerance: float,
                     max_samples: int) -> Dict[str, object]:
    load_dataset_manifest(dataset_path, contract)

    input_weights_float = np.asarray(float_weights["input_weights"], dtype=np.float64)
    hidden_bias_float = np.asarray(float_weights["hidden_bias"], dtype=np.float64)
    output_weights_float = np.asarray(float_weights["output_weights"], dtype=np.float64)
    output_bias_float = float(float_weights["output_bias"])

    diffs = []
    clip_max = int(contract["clip_max"])

    split = "val"
    records = list(iter_dataset_records(dataset_path, split=split, max_records=max_samples))
    if not records:
        split = None
        records = list(iter_dataset_records(dataset_path, split=split, max_records=max_samples))
    if not records:
        return {"validation_samples": 0, "validation_split": "none", "max_abs_diff": 0.0, "mean_abs_diff": 0.0}

    for record in records:
        side_to_move = int(record["side_to_move"])
        pieces = record["pieces"][: int(record["piece_count"])].tolist()
        squares = record["squares"][: int(record["piece_count"])].tolist()

        perspective_scores = []
        for perspective in (0, 1):
            hidden = hidden_bias_float.copy()
            for piece, square in zip(pieces, squares):
                relative_piece_value, relative_square = relative_feature(side_to_move, perspective, piece, square)
                hidden += input_weights_float[perspective, relative_piece_value, relative_square]
            activated = np.clip(hidden, 0.0, float(clip_max))
            perspective_scores.append(output_bias_float + float((activated * output_weights_float).sum()))
        float_score = 0.5 * (perspective_scores[0] - perspective_scores[1])
        quantized_score = integer_model_eval(
            quantized_weights,
            side_to_move,
            pieces,
            squares,
            clip_max,
        )
        diffs.append(abs(float_score - quantized_score))

    max_abs_diff = float(max(diffs))
    mean_abs_diff = float(sum(diffs) / len(diffs))
    if max_abs_diff > tolerance:
        raise SystemExit(
            f"Quantized export drift is too high: max_abs_diff={max_abs_diff:.2f}, tolerance={tolerance:.2f}"
        )
    return {
        "validation_samples": len(diffs),
        "validation_split": split if split is not None else "all",
        "max_abs_diff": max_abs_diff,
        "mean_abs_diff": mean_abs_diff,
    }


def format_nested_initializer(array: np.ndarray, indent: int = 4) -> str:
    if array.ndim == 0:
        return str(int(array))
    if array.ndim == 1:
        return "{ " + ", ".join(str(int(value)) for value in array.tolist()) + " }"

    inner_indent = " " * (indent + 4)
    items = [format_nested_initializer(subarray, indent + 4) for subarray in array]
    joined = (",\n" + inner_indent).join(items)
    return "{\n" + inner_indent + joined + "\n" + " " * indent + "}"


def write_header(path: Path, contract: Dict[str, object], weights: Dict[str, np.ndarray | int]) -> None:
    header = f"""#ifndef GENERATED_NNUE_WEIGHTS_H
#define GENERATED_NNUE_WEIGHTS_H

#include <cstdint>

namespace chilo {{
namespace nnue_generated {{

inline constexpr char kContractId[] = "{contract['contract_id']}";
inline constexpr char kContractSha256[] = "{contract['contract_sha256']}";
inline constexpr int kVersion = {int(contract['version'])};
inline constexpr int kHiddenSize = {int(contract['hidden_size'])};
inline constexpr int kClipMax = {int(contract['clip_max'])};
inline constexpr int kPerspectiveCount = {int(contract['perspectives'])};
inline constexpr int kPiecePlaneCount = {int(contract['piece_planes'])};
inline constexpr int kSquareCount = {int(contract['board_squares'])};

struct TinyNnueData {{
    int16_t inputWeights[kPerspectiveCount][kPiecePlaneCount][kSquareCount][kHiddenSize];
    int16_t hiddenBias[kHiddenSize];
    int16_t outputWeights[kHiddenSize];
    int16_t outputBias;
}};

inline constexpr TinyNnueData kTinyNnue = {{
    {format_nested_initializer(np.asarray(weights['input_weights']), 4)},
    {format_nested_initializer(np.asarray(weights['hidden_bias']), 4)},
    {format_nested_initializer(np.asarray(weights['output_weights']), 4)},
    {int(weights['output_bias'])}
}};

}}  // namespace nnue_generated
}}  // namespace chilo

#endif
"""
    path.write_text(header, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export NNUE weights to a generated C++ header.")
    parser.add_argument("--checkpoint", default=None, help="PyTorch checkpoint produced by train_nnue.py.")
    parser.add_argument("--seeded", action="store_true", help="Export the current heuristic-seeded weights instead of a checkpoint.")
    parser.add_argument("--contract", default=None, help="Optional path to nnue_contract.json.")
    parser.add_argument("--dataset-dir", default=None, help="Optional sharded dataset root or manifest used to validate quantization drift.")
    parser.add_argument("--validation-samples", type=int, default=256, help="Maximum number of validation positions to sample from the dataset.")
    parser.add_argument("--tolerance", type=float, default=0.0, help="Maximum allowed max absolute drift during quantization validation.")
    parser.add_argument("--output-header", required=True, help="Path to write the generated_nnue_weights.h file.")
    parser.add_argument("--output-manifest", required=True, help="Path to write the export manifest JSON.")
    args = parser.parse_args()
    if args.seeded == bool(args.checkpoint):
        parser.error("Choose exactly one of --seeded or --checkpoint.")
    return args


def main() -> int:
    args = parse_args()
    contract = load_contract(Path(args.contract) if args.contract else None)

    source = "seeded"
    if args.seeded:
        float_weights = build_seeded_weights(contract)
    else:
        checkpoint_contract, float_weights = load_torch_checkpoint(Path(args.checkpoint))
        source = str(Path(args.checkpoint).resolve())
        if checkpoint_contract["contract_id"] != contract["contract_id"]:
            raise SystemExit("Checkpoint contract_id does not match the requested export contract.")
        if checkpoint_contract["contract_sha256"] != contract["contract_sha256"]:
            raise SystemExit("Checkpoint contract_sha256 does not match the requested export contract.")

    quantized_weights = quantize_weights(float_weights)
    validation = {"validation_samples": 0, "validation_split": "none", "max_abs_diff": 0.0, "mean_abs_diff": 0.0}
    if args.dataset_dir:
        validation = validate_dataset(
            Path(args.dataset_dir),
            contract,
            float_weights,
            quantized_weights,
            args.tolerance,
            args.validation_samples,
        )

    output_header = Path(args.output_header)
    output_manifest = Path(args.output_manifest)
    write_header(output_header, contract, quantized_weights)
    manifest = {
        "format": "chilo.nnue_export.v2",
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "architecture": contract["architecture"],
        "hidden_size": int(contract["hidden_size"]),
        "clip_max": int(contract["clip_max"]),
        "source": source,
        "quantization": "round_to_int16",
        "validation": validation,
    }
    output_manifest.write_text(compact_json(manifest), encoding="utf-8")
    print(f"Wrote {output_header} and {output_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
