#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np

try:
    from torch.utils.data import IterableDataset, get_worker_info
except ImportError:
    IterableDataset = object  # type: ignore[assignment,misc]

    def get_worker_info():  # type: ignore[no-redef]
        return None

from nnue_common import (
    compact_json,
    contract_hidden2_size,
    contract_hidden_size,
    load_contract,
    load_dataset_manifest,
    shard_metas_for_split,
    shard_path_from_meta,
)
from nnue_torch import (
    DEFAULT_QAT_HIDDEN_SCALE,
    DEFAULT_QAT_INPUT_SCALE,
    DEFAULT_QAT_OUTPUT_SCALE,
    INIT_CHOICES,
    QUANTIZATION_MODE_CHOICES,
    load_torch,
    make_tiny_nnue_model,
)

DEFAULT_BATCH_SIZE = 4096
DEFAULT_LEARNING_RATE = 1e-3
DEFAULT_WEIGHT_DECAY = 0.0
DEFAULT_SHUFFLE_BUFFER_SIZE = 262144
LR_SCHEDULE_CHOICES = ("constant", "step", "cosine")


def learning_rate_for_epoch(
    schedule: str,
    base_learning_rate: float,
    min_learning_rate: float,
    local_epoch: int,
    total_epochs: int,
    step_size: int,
    gamma: float,
) -> float:
    if schedule == "constant":
        return base_learning_rate
    if schedule == "step":
        return base_learning_rate * (gamma ** ((local_epoch - 1) // step_size))
    if schedule == "cosine":
        if total_epochs <= 1 or local_epoch <= 1:
            return base_learning_rate
        if local_epoch >= total_epochs:
            return min_learning_rate
        progress = (local_epoch - 1) / (total_epochs - 1)
        cosine = 0.5 * (1.0 + math.cos(math.pi * progress))
        return min_learning_rate + (base_learning_rate - min_learning_rate) * cosine
    raise ValueError(f"Unsupported learning-rate schedule: {schedule}")


class ActivationAccumulator:
    def __init__(self) -> None:
        self.value_count = 0
        self.sample_count = 0
        self.value_sum = 0.0
        self.value_sum_sq = 0.0
        self.zero_counts: np.ndarray | None = None
        self.clip_counts: np.ndarray | None = None

    def update(self, values, clip_max: float) -> None:
        detached = values.detach()
        self.value_count += int(detached.numel())
        self.sample_count += int(detached.shape[0])
        self.value_sum += float(detached.sum().item())
        self.value_sum_sq += float((detached * detached).sum().item())

        zero_counts = (detached <= 0.0).sum(dim=0).cpu().numpy().astype(np.int64, copy=False)
        clip_counts = (detached >= clip_max).sum(dim=0).cpu().numpy().astype(np.int64, copy=False)
        if self.zero_counts is None:
            self.zero_counts = zero_counts.copy()
            self.clip_counts = clip_counts.copy()
        else:
            self.zero_counts += zero_counts
            self.clip_counts += clip_counts

    def summary(self) -> Dict[str, object]:
        if self.value_count == 0 or self.sample_count == 0 or self.zero_counts is None or self.clip_counts is None:
            return {
                "zero_frac": 0.0,
                "clip_frac": 0.0,
                "linear_frac": 0.0,
                "pre_mean": 0.0,
                "pre_std": 0.0,
                "dead_unit_count": 0,
                "saturated_unit_count": 0,
                "per_unit_zero_frac": np.asarray([], dtype=np.float32),
                "per_unit_clip_frac": np.asarray([], dtype=np.float32),
            }

        zero_frac = float(self.zero_counts.sum() / self.value_count)
        clip_frac = float(self.clip_counts.sum() / self.value_count)
        mean = self.value_sum / self.value_count
        variance = max(0.0, self.value_sum_sq / self.value_count - mean * mean)
        per_unit_zero = self.zero_counts.astype(np.float64) / self.sample_count
        per_unit_clip = self.clip_counts.astype(np.float64) / self.sample_count
        return {
            "zero_frac": zero_frac,
            "clip_frac": clip_frac,
            "linear_frac": max(0.0, 1.0 - zero_frac - clip_frac),
            "pre_mean": mean,
            "pre_std": math.sqrt(variance),
            "dead_unit_count": int((per_unit_zero >= 0.99).sum()),
            "saturated_unit_count": int((per_unit_clip >= 0.99).sum()),
            "per_unit_zero_frac": per_unit_zero.astype(np.float32),
            "per_unit_clip_frac": per_unit_clip.astype(np.float32),
        }


class ShardedSparseDataset(IterableDataset):
    def __init__(
        self,
        root: Path,
        shard_metas: List[Dict[str, object]],
        shuffle: bool,
        shuffle_buffer_size: int,
        base_seed: int,
        epoch: int,
    ):
        super().__init__()
        self.root = root
        self.shard_metas = list(shard_metas)
        self.shuffle = shuffle
        self.shuffle_buffer_size = shuffle_buffer_size
        self.base_seed = base_seed
        self.epoch = epoch

    def _worker_shards(self) -> List[Dict[str, object]]:
        worker_info = get_worker_info()
        if worker_info is None:
            return list(self.shard_metas)
        return list(self.shard_metas[worker_info.id::worker_info.num_workers])

    @staticmethod
    def _record_to_sample(record: np.void) -> Dict[str, np.ndarray | np.integer | np.floating]:
        return {
            "pieces": record["pieces"].astype(np.int64),
            "squares": record["squares"].astype(np.int64),
            "piece_count": np.int64(record["piece_count"]),
            "side_to_move": np.int64(record["side_to_move"]),
            "score": np.float32(record["score"]),
            "result": np.float32(record["result"]),
        }

    def __iter__(self) -> Iterable[Dict[str, np.ndarray | np.integer | np.floating]]:
        shard_metas = self._worker_shards()
        worker_info = get_worker_info()
        worker_id = 0 if worker_info is None else worker_info.id
        rng = np.random.default_rng(self.base_seed + self.epoch * 1000003 + worker_id)

        if self.shuffle:
            shard_metas = list(shard_metas)
            rng.shuffle(shard_metas)
            buffer: List[Dict[str, np.ndarray | np.integer | np.floating]] = []
            for shard_meta in shard_metas:
                shard = np.load(shard_path_from_meta(self.root, shard_meta), mmap_mode="r")
                for record in shard:
                    sample = self._record_to_sample(record)
                    if len(buffer) < self.shuffle_buffer_size:
                        buffer.append(sample)
                        continue
                    replace_index = int(rng.integers(len(buffer)))
                    yield buffer[replace_index]
                    buffer[replace_index] = sample

            while buffer:
                pop_index = int(rng.integers(len(buffer)))
                yield buffer.pop(pop_index)
            return

        for shard_meta in shard_metas:
            shard = np.load(shard_path_from_meta(self.root, shard_meta), mmap_mode="r")
            for record in shard:
                yield self._record_to_sample(record)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the tiny Chilo NNUE with PyTorch on sharded datasets.")
    parser.add_argument("-d", "--dataset", "--dataset-dir", dest="dataset", required=True,
                        help="Dataset root directory or manifest.json path produced by prepare_nnue_dataset.py.")
    parser.add_argument("-o", "--output-dir", required=True, help="Directory for checkpoints and training metadata.")
    parser.add_argument("--contract", default=None, help="Optional path to nnue_contract.json.")
    parser.add_argument("-e", "--epochs", type=int, default=8)
    parser.add_argument("-b", "--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("-l", "--learning-rate", type=float, default=DEFAULT_LEARNING_RATE)
    parser.add_argument("--lr-schedule", choices=LR_SCHEDULE_CHOICES, default="constant",
                        help="Learning-rate schedule applied over this training run.")
    parser.add_argument("--lr-step-size", type=int, default=10,
                        help="Epoch interval for --lr-schedule step.")
    parser.add_argument("--lr-gamma", type=float, default=0.5,
                        help="Learning-rate multiplier for --lr-schedule step.")
    parser.add_argument("--min-learning-rate", type=float, default=0.0,
                        help="Final learning rate for --lr-schedule cosine.")
    parser.add_argument("-w", "--weight-decay", type=float, default=DEFAULT_WEIGHT_DECAY)
    parser.add_argument("-s", "--score-scale", type=float, default=600.0)
    parser.add_argument("-r", "--result-weight", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=None, help="Training RNG seed. Defaults to a time/process-derived seed.")
    parser.add_argument("-D", "--device", default="auto", help="Training device: auto, cpu, cuda, or another torch device string.")
    parser.add_argument("-i", "--init", choices=INIT_CHOICES, default="random")
    parser.add_argument("--quantization-mode", choices=QUANTIZATION_MODE_CHOICES, default="float",
                        help="Training forward path: float or fake byte-shift quantization-aware training.")
    parser.add_argument("--input-scale", type=int, default=DEFAULT_QAT_INPUT_SCALE,
                        help="Power-of-two input scale used by fake-byte-shift QAT and matching export.")
    parser.add_argument("--hidden-scale", type=int, default=DEFAULT_QAT_HIDDEN_SCALE,
                        help="Power-of-two hidden scale used by fake-byte-shift QAT and matching export.")
    parser.add_argument("--output-scale", type=int, default=DEFAULT_QAT_OUTPUT_SCALE,
                        help="Power-of-two output scale used by fake-byte-shift QAT and matching export.")
    parser.add_argument("-H", "--hidden-size", type=int, default=0,
                        help="Accumulator hidden layer size. Defaults to the contract value, or the checkpoint size when resuming.")
    parser.add_argument("--hidden2-size", type=int, default=0,
                        help="Second dense hidden layer size. Defaults to the contract value, or the checkpoint size when resuming.")
    parser.add_argument("-W", "--num-workers", type=int, default=None,
                        help="DataLoader worker count. Defaults to 3 on CUDA and 0 otherwise.")
    parser.add_argument("-B", "--shuffle-buffer-size", type=int, default=DEFAULT_SHUFFLE_BUFFER_SIZE)
    parser.add_argument("--no-shuffle", dest="shuffle", action="store_false", help="Disable training shard/sample shuffling.")
    parser.set_defaults(shuffle=True)
    parser.add_argument("--report-batches", type=int, default=200, help="Print a progress line every N training batches.")
    parser.add_argument("-T", "--tensorboard-dir", default=None, help="Optional TensorBoard log directory for training diagnostics.")
    parser.add_argument("--no-tb-hist", dest="tensorboard_histograms", action="store_false",
                        help="Disable TensorBoard histogram logging.")
    parser.set_defaults(tensorboard_histograms=True)
    parser.add_argument("--resume-checkpoint", default=None, help="Optional checkpoint path to resume from by loading model weights.")
    return parser.parse_args()


def shard_sample_total(shard_metas: List[Dict[str, object]]) -> int:
    return sum(int(shard_meta["sample_count"]) for shard_meta in shard_metas)


def load_summary_writer(log_dir: str):
    try:
        from torch.utils.tensorboard import SummaryWriter
    except ImportError as exc:
        raise SystemExit(
            "TensorBoard logging requested, but tensorboard is not installed. "
            "Run make python-env or install requirements-nnue.txt in .venv."
        ) from exc
    return SummaryWriter(log_dir=log_dir)


def checkpoint_history_length(checkpoint: Dict[str, object]) -> int:
    training = checkpoint.get("training", {})
    if not isinstance(training, dict):
        return 0
    history = training.get("history", [])
    return len(history) if isinstance(history, list) else 0


def derive_seed() -> int:
    entropy = random.SystemRandom().getrandbits(32)
    return (time.time_ns() ^ (os.getpid() << 16) ^ entropy) & 0x7FFFFFFF


def resolve_device(torch, requested_device: str) -> str:
    if requested_device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested_device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("--device cuda was requested, but CUDA is not available.")
    return requested_device


def resolve_tensorboard_dir(output_dir: Path, tensorboard_dir: str | None) -> str | None:
    if tensorboard_dir is None:
        return None
    path = Path(tensorboard_dir)
    if not path.is_absolute():
        path = output_dir / path
    return str(path)


def main() -> int:
    args = parse_args()
    if args.shuffle_buffer_size <= 0:
        raise SystemExit("--shuffle-buffer-size must be positive.")
    if args.num_workers is not None and args.num_workers < 0:
        raise SystemExit("--num-workers must be zero or positive.")
    if args.report_batches <= 0:
        raise SystemExit("--report-batches must be positive.")
    if args.learning_rate <= 0.0:
        raise SystemExit("--learning-rate must be positive.")
    if args.lr_step_size <= 0:
        raise SystemExit("--lr-step-size must be positive.")
    if args.lr_gamma <= 0.0:
        raise SystemExit("--lr-gamma must be positive.")
    if args.min_learning_rate < 0.0 or args.min_learning_rate > args.learning_rate:
        raise SystemExit("--min-learning-rate must be in the range [0, --learning-rate].")

    contract = load_contract(Path(args.contract) if args.contract else None)
    torch, nn, DataLoader = load_torch()
    requested_device = args.device
    resolved_device = resolve_device(torch, requested_device)
    resolved_num_workers = args.num_workers if args.num_workers is not None else (3 if resolved_device.startswith("cuda") else 0)
    resolved_seed = args.seed if args.seed is not None else derive_seed()

    resume_checkpoint = None
    resume_epoch_offset = 0
    if args.resume_checkpoint:
        resume_checkpoint = torch.load(args.resume_checkpoint, map_location="cpu")
        checkpoint_model = resume_checkpoint.get("model", {})
        if not isinstance(checkpoint_model, dict):
            raise SystemExit(f"Checkpoint {args.resume_checkpoint} does not contain model metadata.")
        checkpoint_architecture = checkpoint_model.get("architecture")
        if checkpoint_architecture != contract["architecture"]:
            raise SystemExit(
                f"Checkpoint architecture {checkpoint_architecture!r} does not match contract architecture {contract['architecture']!r}."
            )
        checkpoint_hidden_size = int(checkpoint_model.get("hidden_size", 0))
        if checkpoint_hidden_size <= 0:
            raise SystemExit(f"Checkpoint {args.resume_checkpoint} does not contain a valid hidden size.")
        checkpoint_hidden2_size = int(checkpoint_model.get("hidden2_size", 0))
        if checkpoint_hidden2_size <= 0:
            raise SystemExit(f"Checkpoint {args.resume_checkpoint} does not contain a valid second hidden size.")
        if args.hidden_size > 0 and args.hidden_size != checkpoint_hidden_size:
            raise SystemExit(
                f"--hidden-size {args.hidden_size} does not match checkpoint hidden size {checkpoint_hidden_size}."
            )
        if args.hidden2_size > 0 and args.hidden2_size != checkpoint_hidden2_size:
            raise SystemExit(
                f"--hidden2-size {args.hidden2_size} does not match checkpoint second hidden size {checkpoint_hidden2_size}."
            )
        resume_epoch_offset = checkpoint_history_length(resume_checkpoint)

    if args.hidden_size > 0:
        hidden_size = args.hidden_size
    elif resume_checkpoint is not None:
        hidden_size = int(resume_checkpoint["model"]["hidden_size"])
    else:
        hidden_size = contract_hidden_size(contract)
    if args.hidden2_size > 0:
        hidden2_size = args.hidden2_size
    elif resume_checkpoint is not None:
        hidden2_size = int(resume_checkpoint["model"]["hidden2_size"])
    else:
        hidden2_size = contract_hidden2_size(contract)
    if hidden_size <= 0 or hidden2_size <= 0:
        raise SystemExit("--hidden-size and --hidden2-size must be positive.")
    manifest_path, manifest = load_dataset_manifest(Path(args.dataset), contract)

    train_shards = shard_metas_for_split(manifest, "train")
    val_shards = shard_metas_for_split(manifest, "val")
    if not train_shards:
        raise SystemExit("Training dataset contains no train shards.")

    dataset_root = manifest_path.parent
    train_samples = shard_sample_total(train_shards)
    val_samples = shard_sample_total(val_shards)

    print(f"Using seed={resolved_seed} device={resolved_device} num_workers={resolved_num_workers}")
    random.seed(resolved_seed)
    np.random.seed(resolved_seed)
    torch.manual_seed(resolved_seed)

    def build_loader(shards: List[Dict[str, object]], shuffle: bool, epoch: int):
        if not shards:
            return None
        dataset = ShardedSparseDataset(
            dataset_root,
            shards,
            shuffle=shuffle,
            shuffle_buffer_size=args.shuffle_buffer_size,
            base_seed=resolved_seed,
            epoch=epoch,
        )
        return DataLoader(
            dataset,
            batch_size=args.batch_size,
            shuffle=False,
            num_workers=resolved_num_workers,
        )

    def bounded_target(score_tensor, result_tensor):
        score_target = torch.tanh(score_tensor / args.score_scale)
        return (1.0 - args.result_weight) * score_target + args.result_weight * result_tensor

    def target_loss(pred_cp, score_tensor, result_tensor):
        pred = torch.tanh(pred_cp / args.score_scale)
        target = bounded_target(score_tensor, result_tensor)
        return torch.mean((pred - target) ** 2)

    def prediction_stats(pred_cp):
        values = pred_cp.detach().float().reshape(-1)
        if values.numel() == 0:
            return {"mean": 0.0, "std": 0.0, "p05": 0.0, "p95": 0.0}
        quantiles = torch.quantile(values, torch.tensor([0.05, 0.95], device=values.device))
        return {
            "mean": float(values.mean().item()),
            "std": float(values.std(unbiased=False).item()),
            "p05": float(quantiles[0].item()),
            "p95": float(quantiles[1].item()),
        }

    def activation_diagnostics(intermediates) -> Dict[str, object]:
        accumulator = ActivationAccumulator()
        hidden2 = ActivationAccumulator()
        accumulator.update(intermediates["accumulator_pre"], model.clip_max)
        hidden2.update(intermediates["hidden2_pre"], model.clip_max)
        diag = {
            "activations": {
                "accumulator": accumulator.summary(),
                "hidden2": hidden2.summary(),
            },
            "activation_tensors": {
                "accumulator": intermediates["accumulator_pre"].detach().cpu(),
                "hidden2": intermediates["hidden2_pre"].detach().cpu(),
            },
        }
        if "accumulator_byte" in intermediates and "hidden2_byte" in intermediates:
            diag["qat"] = {
                "accumulator_byte": byte_activation_stats(intermediates["accumulator_byte"], model.activation_scale),
                "hidden2_byte": byte_activation_stats(intermediates["hidden2_byte"], model.activation_scale),
                "hidden2_weight_clip_frac": signed_byte_clip_frac(intermediates["hidden2_weights_q"], model.activation_scale),
                "output_weight_clip_frac": signed_byte_clip_frac(intermediates["output_weights_q"], model.activation_scale),
            }
            diag["activation_tensors"]["accumulator_byte"] = intermediates["accumulator_byte"].detach().cpu()
            diag["activation_tensors"]["hidden2_byte"] = intermediates["hidden2_byte"].detach().cpu()
        return diag

    def byte_activation_stats(values, activation_scale: int) -> Dict[str, float]:
        detached = values.detach()
        total = max(detached.numel(), 1)
        return {
            "zero_frac": float((detached <= 0.0).sum().item() / total),
            "max_frac": float((detached >= float(activation_scale)).sum().item() / total),
        }

    def signed_byte_clip_frac(values, activation_scale: int) -> float:
        detached = values.detach()
        total = max(detached.numel(), 1)
        return float((detached.abs() >= float(activation_scale)).sum().item() / total)

    def qat_weight_stats() -> Dict[str, float]:
        if model.quantization_mode != "fake-byte-shift":
            return {}
        hidden2_q = torch.round(model.hidden2_weights.detach().float() * float(model.hidden_scale * 2))
        output_q = torch.round(model.output_weights.detach().float() * float(model.output_scale * 2))
        return {
            "hidden2_weight_clip_frac": signed_byte_clip_frac(hidden2_q, model.activation_scale),
            "output_weight_clip_frac": signed_byte_clip_frac(output_q, model.activation_scale),
            "input_scale": float(model.input_scale),
            "hidden_scale": float(model.hidden_scale),
            "output_scale": float(model.output_scale),
        }

    def weight_stats():
        input_values = model.input_weights.detach().float()
        hidden_bias_values = model.hidden_bias.detach().float()
        hidden2_values = model.hidden2_weights.detach().float()
        hidden2_bias_values = model.hidden2_bias.detach().float()
        output_values = model.output_weights.detach().float()
        return {
            "input_std": float(input_values.std(unbiased=False).item()),
            "hidden_bias_mean": float(hidden_bias_values.mean().item()),
            "hidden_bias_std": float(hidden_bias_values.std(unbiased=False).item()),
            "hidden2_std": float(hidden2_values.std(unbiased=False).item()),
            "hidden2_bias_mean": float(hidden2_bias_values.mean().item()),
            "hidden2_bias_std": float(hidden2_bias_values.std(unbiased=False).item()),
            "output_std": float(output_values.std(unbiased=False).item()),
            "output_abs_max": float(output_values.abs().max().item()),
        }

    def grad_norm(parameter):
        if parameter.grad is None:
            return 0.0
        return float(parameter.grad.detach().norm().item())

    def log_tensorboard_stats(writer, epoch: int, train_diag, val_diag, train_loss, val_loss, learning_rate: float) -> None:
        writer.add_scalar("loss/train", train_loss, epoch)
        if val_loss is not None:
            writer.add_scalar("loss/val", val_loss, epoch)
        writer.add_scalar("lr", learning_rate, epoch)

        for prefix, diag in (("train", train_diag), ("val", val_diag)):
            if diag is None:
                continue
            for key, value in diag["pred"].items():
                writer.add_scalar(f"pred/{prefix}_{key}", value, epoch)
            accumulator_stats = diag["activations"]["accumulator"]
            for key in ("zero_frac", "clip_frac", "linear_frac"):
                value = accumulator_stats[key]
                writer.add_scalar(f"activation/{prefix}_{key}", value, epoch)
            for layer in ("accumulator", "hidden2"):
                for key, value in diag["activations"][layer].items():
                    if key.startswith("per_unit_"):
                        continue
                    writer.add_scalar(f"activation/{layer}_{prefix}_{key}", value, epoch)

        for key, value in weight_stats().items():
            writer.add_scalar(f"weights/{key}", value, epoch)
        for key, value in qat_weight_stats().items():
            writer.add_scalar(f"qat/{key}", value, epoch)
        if train_diag is not None:
            for key, value in train_diag["grads"].items():
                writer.add_scalar(f"grads/{key}", value, epoch)
        for prefix, diag in (("train", train_diag), ("val", val_diag)):
            if diag is None or "qat" not in diag:
                continue
            for layer in ("accumulator_byte", "hidden2_byte"):
                for key, value in diag["qat"][layer].items():
                    writer.add_scalar(f"qat/{layer}_{prefix}_{key}", value, epoch)
            writer.add_scalar(f"qat/hidden2_weight_clip_frac_{prefix}", diag["qat"]["hidden2_weight_clip_frac"], epoch)
            writer.add_scalar(f"qat/output_weight_clip_frac_{prefix}", diag["qat"]["output_weight_clip_frac"], epoch)

        if args.tensorboard_histograms:
            if train_diag is not None:
                writer.add_histogram("hist/pred_cp_train", train_diag["pred_tensor"], epoch)
                writer.add_histogram("hist/hidden_pre_activation_train", train_diag["activation_tensors"]["accumulator"], epoch)
                if train_diag["input_grad"] is not None:
                    writer.add_histogram("hist/input_grad", train_diag["input_grad"], epoch)
                if train_diag["hidden_bias_grad"] is not None:
                    writer.add_histogram("hist/hidden_bias_grad", train_diag["hidden_bias_grad"], epoch)
                if train_diag["hidden2_grad"] is not None:
                    writer.add_histogram("hist/hidden2_grad", train_diag["hidden2_grad"], epoch)
                if train_diag["hidden2_bias_grad"] is not None:
                    writer.add_histogram("hist/hidden2_bias_grad", train_diag["hidden2_bias_grad"], epoch)
                if train_diag["output_grad"] is not None:
                    writer.add_histogram("hist/output_grad", train_diag["output_grad"], epoch)
            if val_diag is not None:
                writer.add_histogram("hist/pred_cp_val", val_diag["pred_tensor"], epoch)
                writer.add_histogram("hist/hidden_pre_activation_val", val_diag["activation_tensors"]["accumulator"], epoch)
            for prefix, diag in (("train", train_diag), ("val", val_diag)):
                if diag is None or "qat" not in diag:
                    continue
                writer.add_histogram(f"hist/accumulator_byte_{prefix}", diag["activation_tensors"]["accumulator_byte"], epoch)
                writer.add_histogram(f"hist/hidden2_byte_{prefix}", diag["activation_tensors"]["hidden2_byte"], epoch)
            for prefix, diag in (("train", train_diag), ("val", val_diag)):
                if diag is None:
                    continue
                for layer in ("accumulator", "hidden2"):
                    writer.add_histogram(
                        f"hist/{layer}_pre_activation_{prefix}",
                        diag["activation_tensors"][layer],
                        epoch,
                    )
                    writer.add_histogram(
                        f"hist/{layer}_zero_frac_{prefix}",
                        diag["activations"][layer]["per_unit_zero_frac"],
                        epoch,
                    )
                    writer.add_histogram(
                        f"hist/{layer}_clip_frac_{prefix}",
                        diag["activations"][layer]["per_unit_clip_frac"],
                        epoch,
                    )
            writer.add_histogram("hist/input_weights", model.input_weights.detach().cpu(), epoch)
            writer.add_histogram("hist/hidden_bias", model.hidden_bias.detach().cpu(), epoch)
            writer.add_histogram("hist/hidden2_weights", model.hidden2_weights.detach().cpu(), epoch)
            writer.add_histogram("hist/hidden2_bias", model.hidden2_bias.detach().cpu(), epoch)
            writer.add_histogram("hist/output_weights", model.output_weights.detach().cpu(), epoch)

    device = torch.device(resolved_device)
    TinyNnueModel = make_tiny_nnue_model(torch, nn)
    model = TinyNnueModel(
        contract,
        hidden_size,
        hidden2_size,
        args.init,
        quantization_mode=args.quantization_mode,
        input_scale=args.input_scale,
        hidden_scale=args.hidden_scale,
        output_scale=args.output_scale,
    ).to(device)
    if resume_checkpoint is not None:
        state_dict = resume_checkpoint.get("state_dict")
        if not isinstance(state_dict, dict):
            raise SystemExit(f"Checkpoint {args.resume_checkpoint} does not contain a valid state_dict.")
        model.load_state_dict(state_dict)
    model.clamp_quantization_ranges()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_tensorboard_dir = resolve_tensorboard_dir(output_dir, args.tensorboard_dir)
    tensorboard_writer = load_summary_writer(resolved_tensorboard_dir) if resolved_tensorboard_dir else None

    best_val_loss = None
    history = []
    try:
        for local_epoch in range(1, args.epochs + 1):
            epoch = resume_epoch_offset + local_epoch
            epoch_learning_rate = learning_rate_for_epoch(
                args.lr_schedule,
                args.learning_rate,
                args.min_learning_rate,
                local_epoch,
                args.epochs,
                args.lr_step_size,
                args.lr_gamma,
            )
            for parameter_group in optimizer.param_groups:
                parameter_group["lr"] = epoch_learning_rate
            train_loader = build_loader(train_shards, shuffle=args.shuffle, epoch=epoch)
            val_loader = build_loader(val_shards, shuffle=False, epoch=epoch)

            model.train()
            train_loss_sum = 0.0
            train_items = 0
            train_batches = 0
            train_diag = None
            for batch in train_loader:
                pieces = batch["pieces"].to(device)
                squares = batch["squares"].to(device)
                piece_count = batch["piece_count"].to(device)
                side_to_move = batch["side_to_move"].to(device)
                score = batch["score"].to(device)
                result = batch["result"].to(device)

                optimizer.zero_grad(set_to_none=True)
                pred_cp, intermediates = model.forward_with_intermediates(pieces, squares, piece_count, side_to_move)
                loss = target_loss(pred_cp, score, result)
                loss.backward()

                if tensorboard_writer is not None and train_diag is None:
                    train_diag = activation_diagnostics(intermediates)
                    train_diag.update({
                        "pred": prediction_stats(pred_cp),
                        "grads": {
                            "input_norm": grad_norm(model.input_weights),
                            "hidden_bias_norm": grad_norm(model.hidden_bias),
                            "hidden2_norm": grad_norm(model.hidden2_weights),
                            "hidden2_bias_norm": grad_norm(model.hidden2_bias),
                            "output_norm": grad_norm(model.output_weights),
                        },
                        "pred_tensor": pred_cp.detach().cpu(),
                        "input_grad": model.input_weights.grad.detach().cpu() if model.input_weights.grad is not None else None,
                        "hidden_bias_grad": model.hidden_bias.grad.detach().cpu() if model.hidden_bias.grad is not None else None,
                        "hidden2_grad": model.hidden2_weights.grad.detach().cpu() if model.hidden2_weights.grad is not None else None,
                        "hidden2_bias_grad": model.hidden2_bias.grad.detach().cpu() if model.hidden2_bias.grad is not None else None,
                        "output_grad": model.output_weights.grad.detach().cpu() if model.output_weights.grad is not None else None,
                    })

                optimizer.step()
                model.clamp_quantization_ranges()

                batch_items = int(pieces.shape[0])
                train_loss_sum += float(loss.item()) * batch_items
                train_items += batch_items
                train_batches += 1

                if train_batches % args.report_batches == 0:
                    print(
                        f"epoch={epoch} batch={train_batches} processed={train_items}/{train_samples} "
                        f"train_loss={train_loss_sum / max(train_items, 1):.6f}"
                    )

            train_loss = train_loss_sum / max(train_items, 1)

            val_loss = None
            val_diag = None
            if val_loader is not None:
                model.eval()
                val_loss_sum = 0.0
                val_items = 0
                val_accumulator_activations = ActivationAccumulator()
                val_hidden2_activations = ActivationAccumulator()
                val_first_batch = None
                with torch.no_grad():
                    for batch in val_loader:
                        pieces = batch["pieces"].to(device)
                        squares = batch["squares"].to(device)
                        piece_count = batch["piece_count"].to(device)
                        side_to_move = batch["side_to_move"].to(device)
                        score = batch["score"].to(device)
                        result = batch["result"].to(device)
                        pred_cp, intermediates = model.forward_with_intermediates(pieces, squares, piece_count, side_to_move)
                        loss = target_loss(pred_cp, score, result)
                        if tensorboard_writer is not None:
                            val_accumulator_activations.update(intermediates["accumulator_pre"], model.clip_max)
                            val_hidden2_activations.update(intermediates["hidden2_pre"], model.clip_max)
                        if tensorboard_writer is not None and val_first_batch is None:
                            val_first_batch = {
                                "pred": prediction_stats(pred_cp),
                                "pred_tensor": pred_cp.detach().cpu(),
                                "activation_tensors": {
                                    "accumulator": intermediates["accumulator_pre"].detach().cpu(),
                                    "hidden2": intermediates["hidden2_pre"].detach().cpu(),
                                },
                            }
                            if "accumulator_byte" in intermediates and "hidden2_byte" in intermediates:
                                val_first_batch["qat"] = {
                                    "accumulator_byte": byte_activation_stats(
                                        intermediates["accumulator_byte"],
                                        model.activation_scale,
                                    ),
                                    "hidden2_byte": byte_activation_stats(
                                        intermediates["hidden2_byte"],
                                        model.activation_scale,
                                    ),
                                    "hidden2_weight_clip_frac": signed_byte_clip_frac(
                                        intermediates["hidden2_weights_q"],
                                        model.activation_scale,
                                    ),
                                    "output_weight_clip_frac": signed_byte_clip_frac(
                                        intermediates["output_weights_q"],
                                        model.activation_scale,
                                    ),
                                }
                                val_first_batch["activation_tensors"]["accumulator_byte"] = (
                                    intermediates["accumulator_byte"].detach().cpu()
                                )
                                val_first_batch["activation_tensors"]["hidden2_byte"] = (
                                    intermediates["hidden2_byte"].detach().cpu()
                                )
                        batch_items = int(pieces.shape[0])
                        val_loss_sum += float(loss.item()) * batch_items
                        val_items += batch_items
                val_loss = val_loss_sum / max(val_items, 1)
                if val_first_batch is not None:
                    val_diag = val_first_batch
                    val_diag["activations"] = {
                        "accumulator": val_accumulator_activations.summary(),
                        "hidden2": val_hidden2_activations.summary(),
                    }

            if tensorboard_writer is not None:
                log_tensorboard_stats(
                    tensorboard_writer,
                    epoch,
                    train_diag,
                    val_diag,
                    train_loss,
                    val_loss,
                    epoch_learning_rate,
                )
                tensorboard_writer.flush()

            epoch_summary = {
                "epoch": epoch,
                "learning_rate": epoch_learning_rate,
                "train_loss": train_loss,
                "val_loss": val_loss,
                "train_samples": train_items,
                "val_samples": val_samples,
            }
            history.append(epoch_summary)
            print(
                f"epoch={epoch} lr={epoch_learning_rate:.6g} train_loss={train_loss:.6f} train_samples={train_items}" +
                (f" val_loss={val_loss:.6f} val_samples={val_samples}" if val_loss is not None else "")
            )

            checkpoint = {
                "contract": {key: value for key, value in contract.items() if key not in ("contract_path",)},
                "model": {
                    "architecture": contract["architecture"],
                    "hidden_size": hidden_size,
                    "hidden2_size": hidden2_size,
                    "clip_max": int(contract["clip_max"]),
                    "quantization_mode": args.quantization_mode,
                    "input_scale": args.input_scale,
                    "hidden_scale": args.hidden_scale,
                    "output_scale": args.output_scale,
                },
                "dataset": {
                    "manifest_path": str(manifest_path.resolve()),
                    "train_shards": len(train_shards),
                    "val_shards": len(val_shards),
                    "train_samples": train_samples,
                    "val_samples": val_samples,
                },
                "state_dict": model.state_dict(),
                "training": {
                    "epochs": args.epochs,
                    "batch_size": args.batch_size,
                    "learning_rate": args.learning_rate,
                    "lr_schedule": args.lr_schedule,
                    "lr_step_size": args.lr_step_size,
                    "lr_gamma": args.lr_gamma,
                    "min_learning_rate": args.min_learning_rate,
                    "weight_decay": args.weight_decay,
                    "score_scale": args.score_scale,
                    "result_weight": args.result_weight,
                    "seed": resolved_seed,
                    "requested_device": requested_device,
                    "resolved_device": resolved_device,
                    "init": args.init,
                    "quantization_mode": args.quantization_mode,
                    "input_scale": args.input_scale,
                    "hidden_scale": args.hidden_scale,
                    "output_scale": args.output_scale,
                    "num_workers": resolved_num_workers,
                    "shuffle": args.shuffle,
                    "shuffle_buffer_size": args.shuffle_buffer_size,
                    "tensorboard_dir": resolved_tensorboard_dir,
                    "tensorboard_histograms": args.tensorboard_histograms,
                    "resume_checkpoint": str(Path(args.resume_checkpoint).resolve()) if args.resume_checkpoint else None,
                    "resume_epoch_offset": resume_epoch_offset,
                    "history": history,
                },
            }
            torch.save(checkpoint, output_dir / "last.pt")
            if val_loss is None or best_val_loss is None or val_loss < best_val_loss:
                best_val_loss = val_loss if val_loss is not None else train_loss
                torch.save(checkpoint, output_dir / "best.pt")
    finally:
        if tensorboard_writer is not None:
            tensorboard_writer.close()

    training_manifest = {
        "format": "chilo.nnue_training.v2",
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "dataset_manifest": str(manifest_path.resolve()),
        "hidden_size": hidden_size,
        "hidden2_size": hidden2_size,
        "train_shards": len(train_shards),
        "val_shards": len(val_shards),
        "train_samples": train_samples,
        "val_samples": val_samples,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "lr_schedule": args.lr_schedule,
        "lr_step_size": args.lr_step_size,
        "lr_gamma": args.lr_gamma,
        "min_learning_rate": args.min_learning_rate,
        "weight_decay": args.weight_decay,
        "score_scale": args.score_scale,
        "result_weight": args.result_weight,
        "seed": resolved_seed,
        "requested_device": requested_device,
        "resolved_device": resolved_device,
        "init": args.init,
        "quantization_mode": args.quantization_mode,
        "input_scale": args.input_scale,
        "hidden_scale": args.hidden_scale,
        "output_scale": args.output_scale,
        "num_workers": resolved_num_workers,
        "shuffle": args.shuffle,
        "shuffle_buffer_size": args.shuffle_buffer_size,
        "tensorboard_dir": resolved_tensorboard_dir,
        "tensorboard_histograms": args.tensorboard_histograms,
        "resume_checkpoint": str(Path(args.resume_checkpoint).resolve()) if args.resume_checkpoint else None,
        "resume_epoch_offset": resume_epoch_offset,
        "history": history,
        "best_checkpoint": str((output_dir / "best.pt").resolve()),
    }
    (output_dir / "training_manifest.json").write_text(compact_json(training_manifest), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
