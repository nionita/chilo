#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np

from nnue_common import (
    build_seeded_weights,
    compact_json,
    load_contract,
    load_dataset_manifest,
    shard_metas_for_split,
    shard_path_from_meta,
)


def load_torch():
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, IterableDataset, get_worker_info
    except ImportError as exc:
        raise SystemExit(
            "PyTorch is required for training. Install torch in .venv with scripts/setup_python_env.sh and rerun train_nnue.py."
        ) from exc
    return torch, nn, IterableDataset, DataLoader, get_worker_info


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the tiny Chilo NNUE with PyTorch on sharded datasets.")
    parser.add_argument("--dataset", "--dataset-dir", dest="dataset", required=True,
                        help="Dataset root directory or manifest.json path produced by prepare_nnue_dataset.py.")
    parser.add_argument("--output-dir", required=True, help="Directory for checkpoints and training metadata.")
    parser.add_argument("--contract", default=None, help="Optional path to nnue_contract.json.")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--score-scale", type=float, default=600.0)
    parser.add_argument("--result-weight", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--init", choices=("seeded", "random"), default="seeded")
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--shuffle-buffer-size", type=int, default=8192)
    parser.add_argument("--report-batches", type=int, default=200, help="Print a progress line every N training batches.")
    return parser.parse_args()


def shard_sample_total(shard_metas: List[Dict[str, object]]) -> int:
    return sum(int(shard_meta["sample_count"]) for shard_meta in shard_metas)


def main() -> int:
    args = parse_args()
    if args.shuffle_buffer_size <= 0:
        raise SystemExit("--shuffle-buffer-size must be positive.")
    if args.num_workers < 0:
        raise SystemExit("--num-workers must be zero or positive.")
    if args.report_batches <= 0:
        raise SystemExit("--report-batches must be positive.")

    contract = load_contract(Path(args.contract) if args.contract else None)
    manifest_path, manifest = load_dataset_manifest(Path(args.dataset), contract)

    train_shards = shard_metas_for_split(manifest, "train")
    val_shards = shard_metas_for_split(manifest, "val")
    if not train_shards:
        raise SystemExit("Training dataset contains no train shards.")

    dataset_root = manifest_path.parent
    train_samples = shard_sample_total(train_shards)
    val_samples = shard_sample_total(val_shards)

    torch, nn, IterableDataset, DataLoader, get_worker_info = load_torch()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

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

    class TinyNnueModel(nn.Module):
        def __init__(self, contract_data: dict, init_mode: str):
            super().__init__()
            hidden_size = int(contract_data["hidden_size"])
            self.clip_max = float(contract_data["clip_max"])
            self.input_weights = nn.Parameter(torch.zeros(2, 13, 64, hidden_size, dtype=torch.float32))
            self.hidden_bias = nn.Parameter(torch.zeros(hidden_size, dtype=torch.float32))
            self.output_weights = nn.Parameter(torch.zeros(hidden_size, dtype=torch.float32))
            self.output_bias = nn.Parameter(torch.zeros(1, dtype=torch.float32))

            if init_mode == "seeded":
                seeded = build_seeded_weights(contract_data)
                self.input_weights.data.copy_(torch.from_numpy(seeded["input_weights"].astype(np.float32)))
                self.hidden_bias.data.copy_(torch.from_numpy(seeded["hidden_bias"].astype(np.float32)))
                self.output_weights.data.copy_(torch.from_numpy(seeded["output_weights"].astype(np.float32)))
                self.output_bias.data.fill_(float(seeded["output_bias"]))
            else:
                nn.init.normal_(self.input_weights, mean=0.0, std=0.05)
                nn.init.zeros_(self.hidden_bias)
                nn.init.normal_(self.output_weights, mean=0.0, std=0.05)
                nn.init.zeros_(self.output_bias)

        def perspective_score(self, perspective: int, pieces, squares, mask):
            selected = self.input_weights[perspective, pieces, squares]
            hidden = self.hidden_bias.unsqueeze(0) + (selected * mask.unsqueeze(-1)).sum(dim=1)
            activated = torch.clamp(hidden, 0.0, self.clip_max)
            return self.output_bias + (activated * self.output_weights.unsqueeze(0)).sum(dim=1)

        def forward(self, pieces, squares, piece_count, side_to_move):
            max_pieces = pieces.shape[1]
            mask = (torch.arange(max_pieces, device=pieces.device).unsqueeze(0) < piece_count.unsqueeze(1)).float()
            white_score = self.perspective_score(0, pieces, squares, mask)
            black_score = self.perspective_score(1, pieces, squares, mask)
            raw = 0.5 * (white_score - black_score)
            signed = torch.where(side_to_move == 0, raw, -raw)
            return signed.squeeze(-1)

    def build_loader(shards: List[Dict[str, object]], shuffle: bool, epoch: int):
        if not shards:
            return None
        dataset = ShardedSparseDataset(
            dataset_root,
            shards,
            shuffle=shuffle,
            shuffle_buffer_size=args.shuffle_buffer_size,
            base_seed=args.seed,
            epoch=epoch,
        )
        return DataLoader(
            dataset,
            batch_size=args.batch_size,
            shuffle=False,
            num_workers=args.num_workers,
        )

    def bounded_target(score_tensor, result_tensor):
        score_target = torch.tanh(score_tensor / args.score_scale)
        return (1.0 - args.result_weight) * score_target + args.result_weight * result_tensor

    def target_loss(pred_cp, score_tensor, result_tensor):
        pred = torch.tanh(pred_cp / args.score_scale)
        target = bounded_target(score_tensor, result_tensor)
        return torch.mean((pred - target) ** 2)

    device = torch.device(args.device)
    model = TinyNnueModel(contract, args.init).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    best_val_loss = None
    history = []

    for epoch in range(1, args.epochs + 1):
        train_loader = build_loader(train_shards, shuffle=True, epoch=epoch)
        val_loader = build_loader(val_shards, shuffle=False, epoch=epoch)

        model.train()
        train_loss_sum = 0.0
        train_items = 0
        train_batches = 0
        for batch in train_loader:
            pieces = batch["pieces"].to(device)
            squares = batch["squares"].to(device)
            piece_count = batch["piece_count"].to(device)
            side_to_move = batch["side_to_move"].to(device)
            score = batch["score"].to(device)
            result = batch["result"].to(device)

            optimizer.zero_grad(set_to_none=True)
            pred_cp = model(pieces, squares, piece_count, side_to_move)
            loss = target_loss(pred_cp, score, result)
            loss.backward()
            optimizer.step()

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
        if val_loader is not None:
            model.eval()
            val_loss_sum = 0.0
            val_items = 0
            with torch.no_grad():
                for batch in val_loader:
                    pieces = batch["pieces"].to(device)
                    squares = batch["squares"].to(device)
                    piece_count = batch["piece_count"].to(device)
                    side_to_move = batch["side_to_move"].to(device)
                    score = batch["score"].to(device)
                    result = batch["result"].to(device)
                    pred_cp = model(pieces, squares, piece_count, side_to_move)
                    loss = target_loss(pred_cp, score, result)
                    batch_items = int(pieces.shape[0])
                    val_loss_sum += float(loss.item()) * batch_items
                    val_items += batch_items
            val_loss = val_loss_sum / max(val_items, 1)

        epoch_summary = {
            "epoch": epoch,
            "train_loss": train_loss,
            "val_loss": val_loss,
            "train_samples": train_items,
            "val_samples": val_samples,
        }
        history.append(epoch_summary)
        print(
            f"epoch={epoch} train_loss={train_loss:.6f} train_samples={train_items}" +
            (f" val_loss={val_loss:.6f} val_samples={val_samples}" if val_loss is not None else "")
        )

        checkpoint = {
            "contract": {key: value for key, value in contract.items() if key not in ("contract_path",)},
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
                "weight_decay": args.weight_decay,
                "score_scale": args.score_scale,
                "result_weight": args.result_weight,
                "seed": args.seed,
                "init": args.init,
                "num_workers": args.num_workers,
                "shuffle_buffer_size": args.shuffle_buffer_size,
                "history": history,
            },
        }
        torch.save(checkpoint, output_dir / "last.pt")
        if val_loss is None or best_val_loss is None or val_loss < best_val_loss:
            best_val_loss = val_loss if val_loss is not None else train_loss
            torch.save(checkpoint, output_dir / "best.pt")

    training_manifest = {
        "format": "chilo.nnue_training.v2",
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "dataset_manifest": str(manifest_path.resolve()),
        "train_shards": len(train_shards),
        "val_shards": len(val_shards),
        "train_samples": train_samples,
        "val_samples": val_samples,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
        "score_scale": args.score_scale,
        "result_weight": args.result_weight,
        "seed": args.seed,
        "init": args.init,
        "num_workers": args.num_workers,
        "shuffle_buffer_size": args.shuffle_buffer_size,
        "history": history,
        "best_checkpoint": str((output_dir / "best.pt").resolve()),
    }
    (output_dir / "training_manifest.json").write_text(compact_json(training_manifest), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
