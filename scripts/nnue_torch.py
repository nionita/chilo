from __future__ import annotations

import numpy as np

from nnue_common import build_seeded_weights


SEEDED_NOISE_INPUT_STD = 0.01
SEEDED_NOISE_HIDDEN_BIAS_STD = 0.01
SEEDED_NOISE_OUTPUT_STD = 0.05
RANDOM_SCALED_INPUT_STD = 0.05
RANDOM_SCALED_HIDDEN_BIAS = 0.5
RANDOM_SCALED_OUTPUT_STD = 25.0
INIT_CHOICES = ("seeded", "seeded-noise", "random", "random-scaled")


def load_torch():
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader
    except ImportError as exc:
        raise SystemExit(
            "PyTorch is required. Install torch in .venv with scripts/setup_python_env.sh and rerun."
        ) from exc
    return torch, nn, DataLoader


def make_tiny_nnue_model(torch, nn):
    class TinyNnueModel(nn.Module):
        def __init__(self, contract_data: dict, hidden_size: int, init_mode: str):
            super().__init__()
            self.clip_max = float(contract_data["clip_max"])
            self.register_buffer("square_mirror_mask", torch.tensor(56, dtype=torch.int64))
            self.input_weights = nn.Parameter(torch.zeros(2, 13, 64, hidden_size, dtype=torch.float32))
            self.hidden_bias = nn.Parameter(torch.zeros(hidden_size, dtype=torch.float32))
            self.output_weights = nn.Parameter(torch.zeros(hidden_size, dtype=torch.float32))
            self.output_bias = nn.Parameter(torch.zeros(1, dtype=torch.float32))

            if init_mode in ("seeded", "seeded-noise"):
                seeded = build_seeded_weights(contract_data, hidden_size)
                self.input_weights.data.copy_(torch.from_numpy(seeded["input_weights"].astype(np.float32)))
                self.hidden_bias.data.copy_(torch.from_numpy(seeded["hidden_bias"].astype(np.float32)))
                self.output_weights.data.copy_(torch.from_numpy(seeded["output_weights"].astype(np.float32)))
                self.output_bias.data.fill_(float(seeded["output_bias"]))
                if init_mode == "seeded-noise":
                    self.input_weights.data.add_(torch.randn_like(self.input_weights) * SEEDED_NOISE_INPUT_STD)
                    self.hidden_bias.data.add_(torch.randn_like(self.hidden_bias) * SEEDED_NOISE_HIDDEN_BIAS_STD)
                    self.output_weights.data.add_(torch.randn_like(self.output_weights) * SEEDED_NOISE_OUTPUT_STD)
            elif init_mode == "random":
                nn.init.normal_(self.input_weights, mean=0.0, std=0.05)
                nn.init.zeros_(self.hidden_bias)
                nn.init.normal_(self.output_weights, mean=0.0, std=0.05)
                nn.init.zeros_(self.output_bias)
            elif init_mode == "random-scaled":
                nn.init.normal_(self.input_weights, mean=0.0, std=RANDOM_SCALED_INPUT_STD)
                nn.init.constant_(self.hidden_bias, RANDOM_SCALED_HIDDEN_BIAS)
                nn.init.normal_(self.output_weights, mean=0.0, std=RANDOM_SCALED_OUTPUT_STD)
                nn.init.zeros_(self.output_bias)
            else:
                raise ValueError(f"Unsupported init mode: {init_mode}")

        def relative_features(self, perspective: int, pieces, squares, side_to_move):
            perspective_color = side_to_move if perspective == 0 else 1 - side_to_move
            piece_type = torch.where(
                pieces == 0,
                torch.zeros_like(pieces),
                torch.where(pieces <= 6, pieces, pieces - 6),
            )
            raw_color = (pieces > 6).to(torch.int64)
            friendly = raw_color == perspective_color.unsqueeze(1)
            relative_pieces = torch.where(
                piece_type == 0,
                torch.zeros_like(piece_type),
                torch.where(friendly, piece_type, piece_type + 6),
            )
            normalized_squares = torch.where(
                perspective_color.unsqueeze(1) == 0,
                squares,
                torch.bitwise_xor(squares, self.square_mirror_mask),
            )
            return relative_pieces, normalized_squares

        def perspective_score(self, perspective: int, pieces, squares, mask, side_to_move):
            relative_pieces, normalized_squares = self.relative_features(perspective, pieces, squares, side_to_move)
            selected = self.input_weights[perspective, relative_pieces, normalized_squares]
            hidden = self.hidden_bias.unsqueeze(0) + (selected * mask.unsqueeze(-1)).sum(dim=1)
            activated = torch.clamp(hidden, 0.0, self.clip_max)
            return self.output_bias + (activated * self.output_weights.unsqueeze(0)).sum(dim=1)

        def forward(self, pieces, squares, piece_count, side_to_move):
            max_pieces = pieces.shape[1]
            mask = (torch.arange(max_pieces, device=pieces.device).unsqueeze(0) < piece_count.unsqueeze(1)).float()
            active_score = self.perspective_score(0, pieces, squares, mask, side_to_move)
            passive_score = self.perspective_score(1, pieces, squares, mask, side_to_move)
            return (0.5 * (active_score - passive_score)).squeeze(-1)

    return TinyNnueModel
