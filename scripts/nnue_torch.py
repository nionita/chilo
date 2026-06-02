from __future__ import annotations

import numpy as np

from nnue_common import build_seeded_weights


SEEDED_NOISE_INPUT_STD = 0.01
SEEDED_NOISE_HIDDEN_BIAS_STD = 0.01
SEEDED_NOISE_HIDDEN2_BIAS_STD = 0.01
SEEDED_NOISE_HIDDEN2_STD = 0.05
SEEDED_NOISE_OUTPUT_STD = 0.05
RANDOM_SCALED_INPUT_STD = 0.05
RANDOM_SCALED_HIDDEN_BIAS = 0.5
RANDOM_SCALED_HIDDEN2_STD = 0.05
RANDOM_SCALED_HIDDEN2_BIAS = 0.5
RANDOM_SCALED_OUTPUT_STD = 25.0
RANDOM_SCALE_PRESETS = {
    "random-scaled": (
        RANDOM_SCALED_INPUT_STD,
        RANDOM_SCALED_HIDDEN_BIAS,
        RANDOM_SCALED_HIDDEN2_STD,
        RANDOM_SCALED_HIDDEN2_BIAS,
        RANDOM_SCALED_OUTPUT_STD,
    ),
    "random-sweep-1": (0.05, 2.0, 0.05, 0.5, 1000.0),
    "random-sweep-2": (0.20, 2.0, 0.05, 0.5, 250.0),
    "random-sweep-3": (0.05, 8.0, 0.05, 0.5, 1000.0),
    "random-sweep-4": (0.20, 16.0, 0.05, 0.5, 250.0),
    "random-sweep-5": (0.50, 8.0, 0.05, 0.5, 100.0),
}
INIT_CHOICES = ("seeded", "seeded-noise", "random", *RANDOM_SCALE_PRESETS.keys())


def initialize_random_scaled(
    model,
    nn,
    input_std: float,
    hidden_bias: float,
    hidden2_std: float,
    hidden2_bias: float,
    output_std: float,
) -> None:
    nn.init.normal_(model.input_weights, mean=0.0, std=input_std)
    nn.init.constant_(model.hidden_bias, hidden_bias)
    nn.init.normal_(model.hidden2_weights, mean=0.0, std=hidden2_std)
    nn.init.constant_(model.hidden2_bias, hidden2_bias)
    nn.init.normal_(model.output_weights, mean=0.0, std=output_std)
    nn.init.zeros_(model.output_bias)


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
        def __init__(self, contract_data: dict, hidden_size: int, hidden2_size: int, init_mode: str):
            super().__init__()
            self.clip_max = float(contract_data["clip_max"])
            self.register_buffer("square_mirror_mask", torch.tensor(56, dtype=torch.int64))
            self.input_weights = nn.Parameter(torch.zeros(13, 64, hidden_size, dtype=torch.float32))
            self.hidden_bias = nn.Parameter(torch.zeros(hidden_size, dtype=torch.float32))
            self.hidden2_weights = nn.Parameter(torch.zeros(hidden2_size, 2 * hidden_size, dtype=torch.float32))
            self.hidden2_bias = nn.Parameter(torch.zeros(hidden2_size, dtype=torch.float32))
            self.output_weights = nn.Parameter(torch.zeros(hidden2_size, dtype=torch.float32))
            self.output_bias = nn.Parameter(torch.zeros(1, dtype=torch.float32))

            if init_mode in ("seeded", "seeded-noise"):
                seeded = build_seeded_weights(contract_data, hidden_size, hidden2_size)
                self.input_weights.data.copy_(torch.from_numpy(seeded["input_weights"].astype(np.float32)))
                self.hidden_bias.data.copy_(torch.from_numpy(seeded["hidden_bias"].astype(np.float32)))
                self.hidden2_weights.data.copy_(torch.from_numpy(seeded["hidden2_weights"].astype(np.float32)))
                self.hidden2_bias.data.copy_(torch.from_numpy(seeded["hidden2_bias"].astype(np.float32)))
                self.output_weights.data.copy_(torch.from_numpy(seeded["output_weights"].astype(np.float32)))
                self.output_bias.data.fill_(float(seeded["output_bias"]))
                if init_mode == "seeded-noise":
                    self.input_weights.data.add_(torch.randn_like(self.input_weights) * SEEDED_NOISE_INPUT_STD)
                    self.hidden_bias.data.add_(torch.randn_like(self.hidden_bias) * SEEDED_NOISE_HIDDEN_BIAS_STD)
                    self.hidden2_weights.data.add_(torch.randn_like(self.hidden2_weights) * SEEDED_NOISE_HIDDEN2_STD)
                    self.hidden2_bias.data.add_(torch.randn_like(self.hidden2_bias) * SEEDED_NOISE_HIDDEN2_BIAS_STD)
                    self.output_weights.data.add_(torch.randn_like(self.output_weights) * SEEDED_NOISE_OUTPUT_STD)
            elif init_mode == "random":
                nn.init.normal_(self.input_weights, mean=0.0, std=0.05)
                nn.init.zeros_(self.hidden_bias)
                nn.init.normal_(self.hidden2_weights, mean=0.0, std=0.05)
                nn.init.zeros_(self.hidden2_bias)
                nn.init.normal_(self.output_weights, mean=0.0, std=0.05)
                nn.init.zeros_(self.output_bias)
            elif init_mode in RANDOM_SCALE_PRESETS:
                initialize_random_scaled(self, nn, *RANDOM_SCALE_PRESETS[init_mode])
            else:
                raise ValueError(f"Unsupported init mode: {init_mode}")

        def relative_features(self, color: int, pieces, squares):
            piece_type = torch.where(
                pieces == 0,
                torch.zeros_like(pieces),
                torch.where(pieces <= 6, pieces, pieces - 6),
            )
            raw_color = (pieces > 6).to(torch.int64)
            friendly = raw_color == color
            relative_pieces = torch.where(
                piece_type == 0,
                torch.zeros_like(piece_type),
                torch.where(friendly, piece_type, piece_type + 6),
            )
            normalized_squares = squares if color == 0 else torch.bitwise_xor(squares, self.square_mirror_mask)
            return relative_pieces, normalized_squares

        def accumulator(self, color: int, pieces, squares, mask):
            relative_pieces, normalized_squares = self.relative_features(color, pieces, squares)
            selected = self.input_weights[relative_pieces, normalized_squares]
            return self.hidden_bias.unsqueeze(0) + (selected * mask.unsqueeze(-1)).sum(dim=1)

        def forward(self, pieces, squares, piece_count, side_to_move):
            max_pieces = pieces.shape[1]
            mask = (torch.arange(max_pieces, device=pieces.device).unsqueeze(0) < piece_count.unsqueeze(1)).float()
            white = self.accumulator(0, pieces, squares, mask)
            black = self.accumulator(1, pieces, squares, mask)
            white_first = torch.cat([white, black], dim=1)
            black_first = torch.cat([black, white], dim=1)
            stm_is_white = (side_to_move == 0).float().unsqueeze(1)
            dense_input = stm_is_white * white_first + (1.0 - stm_is_white) * black_first
            activated = torch.clamp(dense_input, 0.0, self.clip_max)
            hidden2 = torch.clamp(
                torch.nn.functional.linear(activated, self.hidden2_weights, self.hidden2_bias),
                0.0,
                self.clip_max,
            )
            return (self.output_bias + (hidden2 * self.output_weights.unsqueeze(0)).sum(dim=1)).squeeze(-1)

    return TinyNnueModel
