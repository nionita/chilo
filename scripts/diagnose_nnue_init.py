#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path
from typing import Dict, List

import numpy as np

from nnue_common import (
    contract_hidden_size,
    load_contract,
    load_dataset_manifest,
    shard_metas_for_split,
)
from nnue_torch import INIT_CHOICES, load_torch, make_tiny_nnue_model
from train_nnue import ShardedSparseDataset, shard_sample_total

DEFAULT_SWEEP_INPUT_STDS = "0.05,0.1,0.2,0.5,1.0"
DEFAULT_SWEEP_HIDDEN_BIASES = "0.0,0.5,2.0,4.0,8.0,16.0"
DEFAULT_SWEEP_OUTPUT_STDS = "25,100,250,500,1000,2000"
SWEEP_TABLE_LIMIT = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure the initial prediction distribution of a Tiny NNUE init on a prepared dataset."
    )
    parser.add_argument("--dataset", "--dataset-dir", dest="dataset", required=True,
                        help="Dataset root directory or manifest.json path produced by prepare_nnue_dataset.py.")
    parser.add_argument("--contract", default=None, help="Optional path to nnue_contract.json.")
    parser.add_argument("--hidden-size", type=int, default=0,
                        help="Hidden layer size. Defaults to the contract's default hidden size.")
    parser.add_argument("--init", choices=INIT_CHOICES, default="random")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=4096)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--split", choices=("train", "val", "all"), default="train")
    parser.add_argument("--max-samples", type=int, default=1000000,
                        help="Maximum samples to inspect. Use 0 to scan the whole selected split.")
    parser.add_argument("--percentile-samples", type=int, default=200000,
                        help="Reservoir size for approximate percentiles. Use 0 to disable percentiles.")
    parser.add_argument("--score-scale", type=float, default=600.0)
    parser.add_argument("--result-weight", type=float, default=0.25)
    parser.add_argument("--report-batches", type=int, default=200)
    parser.add_argument("--sweep", action="store_true",
                        help="Evaluate a grid of diagnostic-only random-scaled initialization constants.")
    parser.add_argument("--sweep-input-stds", default=DEFAULT_SWEEP_INPUT_STDS,
                        help="Comma-separated input weight std values for --sweep.")
    parser.add_argument("--sweep-hidden-biases", default=DEFAULT_SWEEP_HIDDEN_BIASES,
                        help="Comma-separated hidden bias constants for --sweep.")
    parser.add_argument("--sweep-output-stds", default=DEFAULT_SWEEP_OUTPUT_STDS,
                        help="Comma-separated output weight std values for --sweep.")
    parser.add_argument("--output-csv", default=None, help="Optional CSV path for sweep results.")
    return parser.parse_args()


class OnlineStats:
    def __init__(self) -> None:
        self.count = 0
        self.sum = 0.0
        self.sum_sq = 0.0
        self.min_value = float("inf")
        self.max_value = float("-inf")

    def update(self, values: np.ndarray) -> None:
        if values.size == 0:
            return
        values64 = values.astype(np.float64, copy=False)
        self.count += int(values64.size)
        self.sum += float(values64.sum())
        self.sum_sq += float((values64 * values64).sum())
        self.min_value = min(self.min_value, float(values64.min()))
        self.max_value = max(self.max_value, float(values64.max()))

    def mean(self) -> float:
        return self.sum / self.count if self.count else 0.0

    def std(self) -> float:
        if self.count <= 1:
            return 0.0
        mean = self.mean()
        variance = max(0.0, self.sum_sq / self.count - mean * mean)
        return variance ** 0.5


class Reservoir:
    def __init__(self, capacity: int, seed: int) -> None:
        self.capacity = capacity
        self.items: List[float] = []
        self.seen = 0
        self.rng = np.random.default_rng(seed)

    def update(self, values: np.ndarray) -> None:
        if self.capacity <= 0:
            return
        for value in values.astype(np.float64, copy=False):
            self.seen += 1
            if len(self.items) < self.capacity:
                self.items.append(float(value))
                continue
            index = int(self.rng.integers(self.seen))
            if index < self.capacity:
                self.items[index] = float(value)

    def percentiles(self) -> Dict[str, float]:
        if not self.items:
            return {}
        values = np.asarray(self.items, dtype=np.float64)
        return {
            "p01": float(np.percentile(values, 1)),
            "p05": float(np.percentile(values, 5)),
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)),
        }


class FractionStats:
    def __init__(self) -> None:
        self.zero_count = 0
        self.clip_count = 0
        self.total_count = 0

    def update(self, hidden, clip_max: float) -> None:
        self.zero_count += int((hidden <= 0.0).sum().item())
        self.clip_count += int((hidden >= clip_max).sum().item())
        self.total_count += int(hidden.numel())

    def zero_frac(self) -> float:
        return self.zero_count / self.total_count if self.total_count else 0.0

    def clip_frac(self) -> float:
        return self.clip_count / self.total_count if self.total_count else 0.0


def print_stats(name: str, stats: OnlineStats, reservoir: Reservoir | None = None) -> None:
    print(
        f"{name}: n={stats.count} mean={stats.mean():.3f} std={stats.std():.3f} "
        f"min={stats.min_value:.3f} max={stats.max_value:.3f}"
    )
    if reservoir is not None:
        percentiles = reservoir.percentiles()
        if percentiles:
            print(
                f"{name}_percentiles: "
                f"p01={percentiles['p01']:.3f} p05={percentiles['p05']:.3f} "
                f"p50={percentiles['p50']:.3f} p95={percentiles['p95']:.3f} p99={percentiles['p99']:.3f}"
            )


def parse_float_list(text: str, name: str) -> List[float]:
    values = []
    for raw_item in text.split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            values.append(float(item))
        except ValueError as exc:
            raise SystemExit(f"{name} must be a comma-separated list of numbers: {text!r}") from exc
    if not values:
        raise SystemExit(f"{name} must contain at least one value.")
    return values


def build_loader(DataLoader, dataset_root: Path, shard_metas: List[Dict[str, object]], args: argparse.Namespace):
    dataset = ShardedSparseDataset(
        dataset_root,
        shard_metas,
        shuffle=False,
        shuffle_buffer_size=1,
        base_seed=args.seed,
        epoch=0,
    )
    return DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)


def initialize_custom_random_scaled(model, nn, input_std: float, hidden_bias: float, output_std: float) -> None:
    nn.init.normal_(model.input_weights, mean=0.0, std=input_std)
    nn.init.constant_(model.hidden_bias, hidden_bias)
    nn.init.normal_(model.output_weights, mean=0.0, std=output_std)
    nn.init.zeros_(model.output_bias)


def update_activation_stats(model, pieces, squares, piece_count, side_to_move, activation_stats: FractionStats) -> None:
    torch = __import__("torch")
    max_pieces = pieces.shape[1]
    mask = (torch.arange(max_pieces, device=pieces.device).unsqueeze(0) < piece_count.unsqueeze(1)).float()
    for perspective in (0, 1):
        relative_pieces, normalized_squares = model.relative_features(perspective, pieces, squares, side_to_move)
        selected = model.input_weights[perspective, relative_pieces, normalized_squares]
        hidden = model.hidden_bias.unsqueeze(0) + (selected * mask.unsqueeze(-1)).sum(dim=1)
        activation_stats.update(hidden, model.clip_max)


def evaluate_model(
    model,
    loader,
    sample_limit: int,
    args: argparse.Namespace,
    progress_prefix: str = "",
) -> Dict[str, object]:
    pred_stats = OnlineStats()
    score_stats = OnlineStats()
    target_stats = OnlineStats()
    error_stats = OnlineStats()
    loss_stats = OnlineStats()
    activation_stats = FractionStats()
    pred_reservoir = Reservoir(args.percentile_samples, args.seed + 17) if args.percentile_samples else None
    score_reservoir = Reservoir(args.percentile_samples, args.seed + 29) if args.percentile_samples else None

    processed = 0
    batches = 0
    model.eval()
    torch = __import__("torch")
    with torch.no_grad():
        for batch in loader:
            remaining = sample_limit - processed
            if remaining <= 0:
                break
            pieces = batch["pieces"][:remaining].to(next(model.parameters()).device)
            squares = batch["squares"][:remaining].to(next(model.parameters()).device)
            piece_count = batch["piece_count"][:remaining].to(next(model.parameters()).device)
            side_to_move = batch["side_to_move"][:remaining].to(next(model.parameters()).device)
            score = batch["score"][:remaining].to(next(model.parameters()).device)
            result = batch["result"][:remaining].to(next(model.parameters()).device)

            pred_cp = model(pieces, squares, piece_count, side_to_move)
            pred_bounded = torch.tanh(pred_cp / args.score_scale)
            target = (1.0 - args.result_weight) * torch.tanh(score / args.score_scale) + args.result_weight * result
            loss = (pred_bounded - target) ** 2
            update_activation_stats(model, pieces, squares, piece_count, side_to_move, activation_stats)

            pred_np = pred_cp.detach().cpu().numpy()
            score_np = score.detach().cpu().numpy()
            target_np = target.detach().cpu().numpy()
            error_np = (pred_cp - score).detach().cpu().numpy()
            loss_np = loss.detach().cpu().numpy()

            pred_stats.update(pred_np)
            score_stats.update(score_np)
            target_stats.update(target_np)
            error_stats.update(error_np)
            loss_stats.update(loss_np)
            if pred_reservoir is not None:
                pred_reservoir.update(pred_np)
            if score_reservoir is not None:
                score_reservoir.update(score_np)

            processed += int(pred_np.size)
            batches += 1
            if batches % args.report_batches == 0:
                prefix = f"{progress_prefix} " if progress_prefix else ""
                print(f"{prefix}processed={processed}/{sample_limit}")

    pred_percentiles = pred_reservoir.percentiles() if pred_reservoir is not None else {}
    score_percentiles = score_reservoir.percentiles() if score_reservoir is not None else {}
    return {
        "processed": processed,
        "pred_stats": pred_stats,
        "score_stats": score_stats,
        "target_stats": target_stats,
        "error_stats": error_stats,
        "loss_stats": loss_stats,
        "pred_percentiles": pred_percentiles,
        "score_percentiles": score_percentiles,
        "zero_frac": activation_stats.zero_frac(),
        "clip_frac": activation_stats.clip_frac(),
    }


def print_single_report(
    manifest_path: Path,
    split: str,
    selected_samples: int,
    init: str,
    hidden_size: int,
    seed: int,
    result: Dict[str, object],
) -> None:
    print(
        f"dataset={manifest_path.resolve()} split={split} inspected={result['processed']}/{selected_samples} "
        f"init={init} hidden_size={hidden_size} seed={seed}"
    )
    print_stats("pred_cp", result["pred_stats"], None)
    if result["pred_percentiles"]:
        percentiles = result["pred_percentiles"]
        print(
            f"pred_cp_percentiles: p01={percentiles['p01']:.3f} p05={percentiles['p05']:.3f} "
            f"p50={percentiles['p50']:.3f} p95={percentiles['p95']:.3f} p99={percentiles['p99']:.3f}"
        )
    print_stats("dataset_score_cp", result["score_stats"], None)
    if result["score_percentiles"]:
        percentiles = result["score_percentiles"]
        print(
            f"dataset_score_cp_percentiles: p01={percentiles['p01']:.3f} p05={percentiles['p05']:.3f} "
            f"p50={percentiles['p50']:.3f} p95={percentiles['p95']:.3f} p99={percentiles['p99']:.3f}"
        )
    print_stats("bounded_target", result["target_stats"])
    print_stats("pred_minus_score_cp", result["error_stats"])
    print_stats("bounded_mse", result["loss_stats"])
    print(f"hidden_activation: zero_frac={result['zero_frac']:.6f} clip_frac={result['clip_frac']:.6f}")


def sweep_rows(
    torch,
    nn,
    TinyNnueModel,
    contract: Dict[str, object],
    hidden_size: int,
    device,
    DataLoader,
    dataset_root: Path,
    shard_metas: List[Dict[str, object]],
    sample_limit: int,
    args: argparse.Namespace,
) -> List[Dict[str, object]]:
    input_stds = parse_float_list(args.sweep_input_stds, "--sweep-input-stds")
    hidden_biases = parse_float_list(args.sweep_hidden_biases, "--sweep-hidden-biases")
    output_stds = parse_float_list(args.sweep_output_stds, "--sweep-output-stds")
    rows: List[Dict[str, object]] = []
    total = len(input_stds) * len(hidden_biases) * len(output_stds)
    row_index = 0
    for input_std in input_stds:
        for hidden_bias in hidden_biases:
            for output_std in output_stds:
                row_index += 1
                row_seed = args.seed + row_index * 1009
                random.seed(row_seed)
                np.random.seed(row_seed)
                torch.manual_seed(row_seed)
                model = TinyNnueModel(contract, hidden_size, "random").to(device)
                initialize_custom_random_scaled(model, nn, input_std, hidden_bias, output_std)
                loader = build_loader(DataLoader, dataset_root, shard_metas, args)
                result = evaluate_model(
                    model,
                    loader,
                    sample_limit,
                    args,
                    progress_prefix=f"row={row_index}/{total}",
                )
                pred_stats = result["pred_stats"]
                loss_stats = result["loss_stats"]
                pred_percentiles = result["pred_percentiles"]
                row = {
                    "rank": 0,
                    "row": row_index,
                    "input_std": input_std,
                    "hidden_bias": hidden_bias,
                    "output_std": output_std,
                    "seed": row_seed,
                    "samples": result["processed"],
                    "pred_mean": pred_stats.mean(),
                    "pred_std": pred_stats.std(),
                    "pred_min": pred_stats.min_value,
                    "pred_max": pred_stats.max_value,
                    "pred_p05": pred_percentiles.get("p05", 0.0),
                    "pred_p50": pred_percentiles.get("p50", 0.0),
                    "pred_p95": pred_percentiles.get("p95", 0.0),
                    "bounded_mse_mean": loss_stats.mean(),
                    "zero_frac": result["zero_frac"],
                    "clip_frac": result["clip_frac"],
                }
                rows.append(row)
                print(
                    f"row={row_index}/{total} input_std={input_std:g} hidden_bias={hidden_bias:g} "
                    f"output_std={output_std:g} pred_std={row['pred_std']:.3f} "
                    f"mse={row['bounded_mse_mean']:.6f} zero={row['zero_frac']:.4f} clip={row['clip_frac']:.4f}"
                )
    rows.sort(key=lambda item: float(item["bounded_mse_mean"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def print_sweep_table(
    rows: List[Dict[str, object]],
    manifest_path: Path,
    split: str,
    selected_samples: int,
    sample_limit: int,
    hidden_size: int,
) -> None:
    print(
        f"dataset={manifest_path.resolve()} split={split} inspected={sample_limit}/{selected_samples} "
        f"hidden_size={hidden_size} sweep_candidates={len(rows)}"
    )
    print(
        "rank row input_std hidden_bias output_std pred_std pred_p05 pred_p50 pred_p95 "
        "mse zero_frac clip_frac"
    )
    for row in rows[:SWEEP_TABLE_LIMIT]:
        print(
            f"{int(row['rank']):4d} {int(row['row']):3d} "
            f"{float(row['input_std']):9.3g} {float(row['hidden_bias']):11.3g} {float(row['output_std']):10.3g} "
            f"{float(row['pred_std']):8.3f} {float(row['pred_p05']):8.3f} "
            f"{float(row['pred_p50']):8.3f} {float(row['pred_p95']):8.3f} "
            f"{float(row['bounded_mse_mean']):.6f} {float(row['zero_frac']):.6f} {float(row['clip_frac']):.6f}"
        )


def write_sweep_csv(rows: List[Dict[str, object]], path: Path) -> None:
    fieldnames = [
        "rank",
        "row",
        "input_std",
        "hidden_bias",
        "output_std",
        "seed",
        "samples",
        "pred_mean",
        "pred_std",
        "pred_min",
        "pred_max",
        "pred_p05",
        "pred_p50",
        "pred_p95",
        "bounded_mse_mean",
        "zero_frac",
        "clip_frac",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fieldnames})


def main() -> int:
    args = parse_args()
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive.")
    if args.num_workers < 0:
        raise SystemExit("--num-workers must be zero or positive.")
    if args.max_samples < 0:
        raise SystemExit("--max-samples must be zero or positive.")
    if args.percentile_samples < 0:
        raise SystemExit("--percentile-samples must be zero or positive.")
    if args.report_batches <= 0:
        raise SystemExit("--report-batches must be positive.")

    contract = load_contract(Path(args.contract) if args.contract else None)
    hidden_size = args.hidden_size if args.hidden_size > 0 else contract_hidden_size(contract)
    if hidden_size <= 0:
        raise SystemExit("--hidden-size must be positive.")
    manifest_path, manifest = load_dataset_manifest(Path(args.dataset), contract)
    dataset_root = manifest_path.parent

    if args.split == "all":
        shard_metas = shard_metas_for_split(manifest, None)
    else:
        shard_metas = shard_metas_for_split(manifest, args.split)
    if not shard_metas:
        raise SystemExit(f"Dataset contains no {args.split} shards.")
    selected_samples = shard_sample_total(shard_metas)
    sample_limit = selected_samples if args.max_samples == 0 else min(selected_samples, args.max_samples)

    torch, nn, DataLoader = load_torch()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    device = torch.device(args.device)
    TinyNnueModel = make_tiny_nnue_model(torch, nn)

    if args.sweep:
        rows = sweep_rows(
            torch,
            nn,
            TinyNnueModel,
            contract,
            hidden_size,
            device,
            DataLoader,
            dataset_root,
            shard_metas,
            sample_limit,
            args,
        )
        print_sweep_table(rows, manifest_path, args.split, selected_samples, sample_limit, hidden_size)
        if args.output_csv:
            write_sweep_csv(rows, Path(args.output_csv))
            print(f"wrote_csv={Path(args.output_csv).resolve()}")
        return 0

    loader = build_loader(DataLoader, dataset_root, shard_metas, args)
    model = TinyNnueModel(contract, hidden_size, args.init).to(device)
    result = evaluate_model(model, loader, sample_limit, args)
    print_single_report(manifest_path, args.split, selected_samples, args.init, hidden_size, args.seed, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
