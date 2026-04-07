#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

from nnue_common import build_seeded_weights, compact_json, load_contract


def load_torch():
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, Dataset
    except ImportError as exc:
        raise SystemExit(
            "PyTorch is required for training. Install torch in this environment and rerun train_nnue.py."
        ) from exc
    return torch, nn, Dataset, DataLoader


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the tiny Chilo NNUE with PyTorch.")
    parser.add_argument("--dataset-dir", required=True, help="Directory containing samples.npy and manifest.json.")
    parser.add_argument("--output-dir", required=True, help="Directory for checkpoints and training metadata.")
    parser.add_argument("--contract", default=None, help="Optional path to nnue_contract.json.")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--score-scale", type=float, default=600.0)
    parser.add_argument("--result-weight", type=float, default=0.25)
    parser.add_argument("--validation-fraction", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--init", choices=("seeded", "random"), default="seeded")
    return parser.parse_args()


def load_dataset(dataset_dir: Path, contract: dict) -> np.ndarray:
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["contract_id"] != contract["contract_id"]:
        raise SystemExit("Dataset contract_id does not match the current trainer contract.")
    if manifest["contract_sha256"] != contract["contract_sha256"]:
        raise SystemExit("Dataset contract_sha256 does not match the current trainer contract.")
    samples = np.load(dataset_dir / "samples.npy", mmap_mode="r")
    dtype_descr = json.loads(json.dumps(samples.dtype.descr))
    if dtype_descr != manifest["dtype_descr"]:
        raise SystemExit("Dataset dtype does not match its manifest.")
    return samples


def main() -> int:
    args = parse_args()
    contract = load_contract(Path(args.contract) if args.contract else None)
    samples = load_dataset(Path(args.dataset_dir), contract)
    if samples.shape[0] == 0:
        raise SystemExit("Training dataset is empty.")

    torch, nn, Dataset, DataLoader = load_torch()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    class SparseDataset(Dataset):
        def __init__(self, storage: np.ndarray, indices: np.ndarray):
            self.storage = storage
            self.indices = indices

        def __len__(self) -> int:
            return int(self.indices.shape[0])

        def __getitem__(self, item: int):
            record = self.storage[int(self.indices[item])]
            return {
                "pieces": record["pieces"].astype(np.int64),
                "squares": record["squares"].astype(np.int64),
                "piece_count": np.int64(record["piece_count"]),
                "side_to_move": np.int64(record["side_to_move"]),
                "score": np.float32(record["score"]),
                "result": np.float32(record["result"]),
            }

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

    def bounded_target(score_tensor, result_tensor):
        score_target = torch.tanh(score_tensor / args.score_scale)
        return (1.0 - args.result_weight) * score_target + args.result_weight * result_tensor

    def target_loss(pred_cp, score_tensor, result_tensor):
        pred = torch.tanh(pred_cp / args.score_scale)
        target = bounded_target(score_tensor, result_tensor)
        return torch.mean((pred - target) ** 2), pred, target

    all_indices = np.arange(samples.shape[0], dtype=np.int64)
    rng = np.random.default_rng(args.seed)
    rng.shuffle(all_indices)
    val_count = int(round(samples.shape[0] * args.validation_fraction))
    if val_count <= 0:
        val_count = 1 if samples.shape[0] > 1 else 0
    if val_count >= samples.shape[0]:
        val_count = samples.shape[0] - 1
    train_indices = all_indices[val_count:]
    val_indices = all_indices[:val_count]

    train_loader = DataLoader(SparseDataset(samples, train_indices), batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(SparseDataset(samples, val_indices), batch_size=args.batch_size, shuffle=False) if val_count > 0 else None

    device = torch.device(args.device)
    model = TinyNnueModel(contract, args.init).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    best_val_loss = None
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss_sum = 0.0
        train_items = 0
        for batch in train_loader:
            pieces = batch["pieces"].to(device)
            squares = batch["squares"].to(device)
            piece_count = batch["piece_count"].to(device)
            side_to_move = batch["side_to_move"].to(device)
            score = batch["score"].to(device)
            result = batch["result"].to(device)

            optimizer.zero_grad(set_to_none=True)
            pred_cp = model(pieces, squares, piece_count, side_to_move)
            loss, _, _ = target_loss(pred_cp, score, result)
            loss.backward()
            optimizer.step()

            batch_items = int(pieces.shape[0])
            train_loss_sum += float(loss.item()) * batch_items
            train_items += batch_items

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
                    loss, _, _ = target_loss(pred_cp, score, result)
                    batch_items = int(pieces.shape[0])
                    val_loss_sum += float(loss.item()) * batch_items
                    val_items += batch_items
            val_loss = val_loss_sum / max(val_items, 1)

        epoch_summary = {"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss}
        history.append(epoch_summary)
        print(
            f"epoch={epoch} train_loss={train_loss:.6f}" +
            (f" val_loss={val_loss:.6f}" if val_loss is not None else "")
        )

        checkpoint = {
            "contract": {k: v for k, v in contract.items() if k not in ("contract_path",)},
            "state_dict": model.state_dict(),
            "training": {
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "learning_rate": args.learning_rate,
                "weight_decay": args.weight_decay,
                "score_scale": args.score_scale,
                "result_weight": args.result_weight,
                "validation_fraction": args.validation_fraction,
                "seed": args.seed,
                "init": args.init,
                "history": history,
            },
        }
        torch.save(checkpoint, output_dir / "last.pt")
        if val_loss is None or best_val_loss is None or val_loss < best_val_loss:
            best_val_loss = val_loss if val_loss is not None else train_loss
            torch.save(checkpoint, output_dir / "best.pt")

    training_manifest = {
        "format": "chilo.nnue_training.v1",
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "dataset_dir": str(Path(args.dataset_dir).resolve()),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
        "score_scale": args.score_scale,
        "result_weight": args.result_weight,
        "validation_fraction": args.validation_fraction,
        "seed": args.seed,
        "init": args.init,
        "history": history,
        "best_checkpoint": str((output_dir / "best.pt").resolve()),
    }
    (output_dir / "training_manifest.json").write_text(compact_json(training_manifest), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
