#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

from nnue_common import (
    build_seeded_weights,
    compact_json,
    contract_hidden_size,
    feature_contract_compatible,
    integer_model_eval,
    iter_dataset_records,
    load_contract,
    load_dataset_manifest,
    relative_feature,
)

DEFAULT_INPUT_SCALE = 64
DEFAULT_OUTPUT_SCALE = 32
WEIGHTS_BIN_MAGIC = b"CHNNUEB1"
WEIGHTS_BIN_HEADER_STRUCT = struct.Struct("<8sIIIIIII64s64s")


def load_torch_checkpoint(path: Path) -> Tuple[Dict[str, object], Dict[str, np.ndarray | int]]:
    try:
        import torch
    except ImportError as exc:
        raise SystemExit("PyTorch is required to export from a training checkpoint.") from exc

    checkpoint = torch.load(path, map_location="cpu")
    if "contract" not in checkpoint or "state_dict" not in checkpoint:
        raise SystemExit("Checkpoint does not contain the expected contract/state_dict fields.")
    contract = checkpoint["contract"]
    model_meta = checkpoint.get("model", {})
    state_dict = checkpoint["state_dict"]
    hidden_size = int(model_meta.get("hidden_size", state_dict["hidden_bias"].shape[0]))
    weights = {
        "input_weights": state_dict["input_weights"].detach().cpu().numpy(),
        "hidden_bias": state_dict["hidden_bias"].detach().cpu().numpy(),
        "output_weights": state_dict["output_weights"].detach().cpu().numpy(),
        "output_bias": float(state_dict["output_bias"].detach().cpu().numpy().reshape(-1)[0]),
    }
    metadata = {
        "contract": contract,
        "hidden_size": hidden_size,
        "clip_max": int(model_meta.get("clip_max", contract.get("clip_max", 255))),
        "architecture": model_meta.get("architecture", contract.get("architecture", "TinyNnue")),
    }
    return metadata, weights


def quantize_weights(weights: Dict[str, np.ndarray | int], input_scale: int, output_scale: int) -> Dict[str, np.ndarray | int]:
    if input_scale <= 0 or output_scale <= 0:
        raise SystemExit("input_scale and output_scale must be positive integers.")
    quantized = {}
    for name in ("input_weights", "hidden_bias"):
        rounded = np.rint(np.asarray(weights[name], dtype=np.float64) * input_scale)
        if np.any(rounded < np.iinfo(np.int16).min) or np.any(rounded > np.iinfo(np.int16).max):
            raise SystemExit(f"{name} does not fit in int16 after rounding; export refused.")
        quantized[name] = rounded.astype(np.int16)

    rounded_output_weights = np.rint(np.asarray(weights["output_weights"], dtype=np.float64) * output_scale)
    if np.any(rounded_output_weights < np.iinfo(np.int16).min) or np.any(rounded_output_weights > np.iinfo(np.int16).max):
        raise SystemExit("output_weights do not fit in int16 after scaled rounding; export refused.")
    quantized["output_weights"] = rounded_output_weights.astype(np.int16)

    output_bias = int(round(float(weights["output_bias"]) * input_scale * output_scale))
    if output_bias < np.iinfo(np.int32).min or output_bias > np.iinfo(np.int32).max:
        raise SystemExit("output_bias does not fit in int32 after scaled rounding; export refused.")
    quantized["output_bias"] = output_bias
    quantized["input_scale"] = int(input_scale)
    quantized["output_scale"] = int(output_scale)
    return quantized


def hidden_size_from_weights(weights: Dict[str, np.ndarray | int]) -> int:
    return int(np.asarray(weights["hidden_bias"]).shape[0])


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
        quantized_score = integer_model_eval(quantized_weights, side_to_move, pieces, squares, clip_max)
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
    hidden_size = hidden_size_from_weights(weights)
    header = f"""#ifndef GENERATED_NNUE_WEIGHTS_H
#define GENERATED_NNUE_WEIGHTS_H

#include <cstdint>

namespace chilo {{
namespace nnue_generated {{

inline constexpr char kContractId[] = "{contract['contract_id']}";
inline constexpr char kContractSha256[] = "{contract['contract_sha256']}";
inline constexpr int kVersion = {int(contract['version'])};
inline constexpr int kHiddenSize = {hidden_size};
inline constexpr int kClipMax = {int(contract['clip_max'])};
inline constexpr int kInputScale = {int(weights['input_scale'])};
inline constexpr int kOutputScale = {int(weights['output_scale'])};
inline constexpr int kPerspectiveCount = {int(contract['perspectives'])};
inline constexpr int kPiecePlaneCount = {int(contract['piece_planes'])};
inline constexpr int kSquareCount = {int(contract['board_squares'])};

struct TinyNnueData {{
    int16_t inputWeights[kPerspectiveCount][kPiecePlaneCount][kSquareCount][kHiddenSize];
    int16_t hiddenBias[kHiddenSize];
    int16_t outputWeights[kHiddenSize];
    int32_t outputBias;
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


def fixed_ascii_bytes(text: str, size: int) -> bytes:
    encoded = text.encode("ascii")
    if len(encoded) > size:
        raise SystemExit(f"Field {text!r} is too long for fixed binary header size {size}.")
    return encoded + (b"\0" * (size - len(encoded)))


def write_bin(path: Path, contract: Dict[str, object], weights: Dict[str, np.ndarray | int], clip_max: int) -> None:
    hidden_size = hidden_size_from_weights(weights)
    header = WEIGHTS_BIN_HEADER_STRUCT.pack(
        WEIGHTS_BIN_MAGIC,
        hidden_size,
        int(clip_max),
        int(weights["input_scale"]),
        int(weights["output_scale"]),
        int(contract["perspectives"]),
        int(contract["piece_planes"]),
        int(contract["board_squares"]),
        fixed_ascii_bytes(str(contract["contract_id"]), 64),
        fixed_ascii_bytes(str(contract["contract_sha256"]), 64),
    )

    with path.open("wb") as handle:
        handle.write(header)
        handle.write(np.asarray(weights["input_weights"], dtype="<i2").tobytes(order="C"))
        handle.write(np.asarray(weights["hidden_bias"], dtype="<i2").tobytes(order="C"))
        handle.write(np.asarray(weights["output_weights"], dtype="<i2").tobytes(order="C"))
        handle.write(np.asarray([weights["output_bias"]], dtype="<i4").tobytes(order="C"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export NNUE weights to generated C++ and/or binary runtime artifacts.")
    parser.add_argument("--checkpoint", default=None, help="PyTorch checkpoint produced by train_nnue.py.")
    parser.add_argument("--seeded", action="store_true", help="Export the current heuristic-seeded weights instead of a checkpoint.")
    parser.add_argument("--contract", default=None, help="Optional path to nnue_contract.json.")
    parser.add_argument("--dataset-dir", default=None, help="Optional sharded dataset root or manifest used to validate quantization drift.")
    parser.add_argument("--validation-samples", type=int, default=256, help="Maximum number of validation positions to sample from the dataset.")
    parser.add_argument("--tolerance", type=float, default=0.0, help="Maximum allowed max absolute drift during quantization validation.")
    parser.add_argument("--input-scale", type=int, default=DEFAULT_INPUT_SCALE, help="Scale factor applied to input weights and hidden bias before integer export.")
    parser.add_argument("--output-scale", type=int, default=DEFAULT_OUTPUT_SCALE, help="Scale factor applied to output weights before integer export.")
    parser.add_argument("--output-header", default=None, help="Optional path to write the generated_nnue_weights.h file.")
    parser.add_argument("--output-manifest", default=None, help="Optional path to write the export manifest JSON.")
    parser.add_argument("--output-bin", default=None, help="Optional path to write the runtime-loadable NNUE binary artifact.")
    args = parser.parse_args()
    if args.seeded == bool(args.checkpoint):
        parser.error("Choose exactly one of --seeded or --checkpoint.")
    if not any((args.output_header, args.output_manifest, args.output_bin)):
        parser.error("Provide at least one output target via --output-header, --output-manifest, or --output-bin.")
    return args


def main() -> int:
    args = parse_args()
    contract = load_contract(Path(args.contract) if args.contract else None)

    source = "seeded"
    hidden_size = contract_hidden_size(contract)
    clip_max = int(contract["clip_max"])
    if args.seeded:
        float_weights = build_seeded_weights(contract, hidden_size)
    else:
        checkpoint_meta, float_weights = load_torch_checkpoint(Path(args.checkpoint))
        source = str(Path(args.checkpoint).resolve())
        checkpoint_contract = checkpoint_meta["contract"]
        if not feature_contract_compatible(contract, checkpoint_contract):
            raise SystemExit("Checkpoint feature contract does not match the requested export contract.")
        hidden_size = int(checkpoint_meta["hidden_size"])
        clip_max = int(checkpoint_meta["clip_max"])

    quantized_weights = quantize_weights(float_weights, args.input_scale, args.output_scale)
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

    output_header = Path(args.output_header) if args.output_header else None
    output_manifest = Path(args.output_manifest) if args.output_manifest else None
    output_bin = Path(args.output_bin) if args.output_bin else None
    if output_header:
        output_header.parent.mkdir(parents=True, exist_ok=True)
        write_header(output_header, contract, quantized_weights)
    if output_bin:
        output_bin.parent.mkdir(parents=True, exist_ok=True)
        write_bin(output_bin, contract, quantized_weights, clip_max)
    manifest = {
        "format": "chilo.nnue_export.v4",
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "architecture": contract["architecture"],
        "hidden_size": hidden_size,
        "clip_max": clip_max,
        "source": source,
        "quantization": "scaled_int16",
        "input_scale": int(args.input_scale),
        "output_scale": int(args.output_scale),
        "output_bin": str(output_bin.resolve()) if output_bin else None,
        "validation": validation,
    }
    if output_manifest:
        output_manifest.parent.mkdir(parents=True, exist_ok=True)
        output_manifest.write_text(compact_json(manifest), encoding="utf-8")
    written = [str(path) for path in (output_header, output_manifest, output_bin) if path is not None]
    print(f"Wrote {', '.join(written)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
