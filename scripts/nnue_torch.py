from __future__ import annotations

import math

import numpy as np

from nnue_common import BYTE_ACTIVATION_SCALE, build_seeded_weights, is_power_of_two, log2_power_of_two


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
RANDOM_EXPECTED_ACTIVE_PIECES = 16.0
RANDOM_ACCUMULATOR_BIAS = 1.0
RANDOM_HIDDEN2_BIAS = 1.0
RANDOM_OUTPUT_STD_NUMERATOR = 64.0
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
QUANTIZATION_MODE_CHOICES = ("float", "fake-byte-shift")
DEFAULT_QAT_INPUT_SCALE = 32
DEFAULT_QAT_HIDDEN_SCALE = 4
DEFAULT_QAT_OUTPUT_SCALE = 8


def torch_round(values):
    return values.round()


def fake_quantize_to_int(values, scale: int, qmin: int, qmax: int):
    scaled = values * float(scale)
    quantized = torch_round(scaled).clamp(float(qmin), float(qmax))
    return scaled + (quantized - scaled).detach()


def fake_byte_activation_from_scaled(values, scale: int, activation_scale: int = BYTE_ACTIVATION_SCALE):
    shift = log2_power_of_two(scale) + 1
    divisor = float(1 << shift)
    base = (values / divisor).clamp(0.0, float(activation_scale))
    quantized = (values.clamp_min(0.0) / divisor + 0.5).floor().clamp(0.0, float(activation_scale))
    return base + (quantized - base).detach()


def fake_round_shift_signed(values, scale: int):
    shift = log2_power_of_two(scale)
    if shift == 0:
        return values
    divisor = float(1 << shift)
    base = values / divisor
    quantized = values.sign() * (values.abs() / divisor + 0.5).floor()
    return base + (quantized - base).detach()


def validate_byte_shift_scales(input_scale: int, hidden_scale: int, output_scale: int) -> None:
    for name, value in (("input_scale", input_scale), ("hidden_scale", hidden_scale), ("output_scale", output_scale)):
        if not is_power_of_two(int(value)):
            raise ValueError(f"{name} must be a positive power of two for fake-byte-shift QAT.")


def initialize_random_fan_in(model, nn) -> None:
    input_std = 1.0 / math.sqrt(RANDOM_EXPECTED_ACTIVE_PIECES)
    hidden2_fan_in = int(model.hidden2_weights.shape[1])
    hidden2_std = math.sqrt(2.0 / hidden2_fan_in)
    output_fan_in = int(model.output_weights.numel())
    output_std = RANDOM_OUTPUT_STD_NUMERATOR / math.sqrt(output_fan_in)

    nn.init.normal_(model.input_weights, mean=0.0, std=input_std)
    nn.init.constant_(model.hidden_bias, RANDOM_ACCUMULATOR_BIAS)
    nn.init.normal_(model.hidden2_weights, mean=0.0, std=hidden2_std)
    nn.init.constant_(model.hidden2_bias, RANDOM_HIDDEN2_BIAS)
    nn.init.normal_(model.output_weights, mean=0.0, std=output_std)
    nn.init.zeros_(model.output_bias)

    hidden2_weights = model.hidden2_weights.detach()
    hidden2_weights.sub_(hidden2_weights.mean(dim=1, keepdim=True))
    if output_fan_in > 1:
        output_weights = model.output_weights.detach()
        output_weights.sub_(output_weights.mean())


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
        def __init__(
            self,
            contract_data: dict,
            hidden_size: int,
            hidden2_size: int,
            init_mode: str,
            quantization_mode: str = "float",
            input_scale: int = DEFAULT_QAT_INPUT_SCALE,
            hidden_scale: int = DEFAULT_QAT_HIDDEN_SCALE,
            output_scale: int = DEFAULT_QAT_OUTPUT_SCALE,
        ):
            super().__init__()
            if quantization_mode not in QUANTIZATION_MODE_CHOICES:
                raise ValueError(f"Unsupported quantization mode: {quantization_mode}")
            if quantization_mode == "fake-byte-shift":
                validate_byte_shift_scales(input_scale, hidden_scale, output_scale)
            self.clip_max = float(contract_data["clip_max"])
            self.quantization_mode = quantization_mode
            self.input_scale = int(input_scale)
            self.hidden_scale = int(hidden_scale)
            self.output_scale = int(output_scale)
            self.activation_scale = BYTE_ACTIVATION_SCALE
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
                initialize_random_fan_in(self, nn)
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

        def accumulator_with_weights(self, color: int, pieces, squares, mask, input_weights, hidden_bias):
            relative_pieces, normalized_squares = self.relative_features(color, pieces, squares)
            selected = input_weights[relative_pieces, normalized_squares]
            return hidden_bias.unsqueeze(0) + (selected * mask.unsqueeze(-1)).sum(dim=1)

        def accumulator(self, color: int, pieces, squares, mask):
            return self.accumulator_with_weights(color, pieces, squares, mask, self.input_weights, self.hidden_bias)

        def clamp_quantization_ranges(self) -> None:
            if self.quantization_mode != "fake-byte-shift":
                return
            input_limit = np.iinfo(np.int16).max / float(self.input_scale)
            hidden2_weight_limit = self.activation_scale / float(self.hidden_scale * 2)
            output_weight_limit = self.activation_scale / float(self.output_scale * 2)
            with torch.no_grad():
                self.input_weights.clamp_(-input_limit, input_limit)
                self.hidden_bias.clamp_(-input_limit, input_limit)
                self.hidden2_weights.clamp_(-hidden2_weight_limit, hidden2_weight_limit)
                self.output_weights.clamp_(-output_weight_limit, output_weight_limit)

        def dense_input_from_accumulators(self, white, black, side_to_move):
            white_first = torch.cat([white, black], dim=1)
            black_first = torch.cat([black, white], dim=1)
            stm_is_white = (side_to_move == 0).float().unsqueeze(1)
            return stm_is_white * white_first + (1.0 - stm_is_white) * black_first

        def _float_components_from_mask(self, pieces, squares, mask, side_to_move):
            white = self.accumulator(0, pieces, squares, mask)
            black = self.accumulator(1, pieces, squares, mask)
            dense_input = self.dense_input_from_accumulators(white, black, side_to_move)
            activated = torch.clamp(dense_input, 0.0, self.clip_max)
            hidden2_pre = torch.nn.functional.linear(activated, self.hidden2_weights, self.hidden2_bias)
            hidden2 = torch.clamp(hidden2_pre, 0.0, self.clip_max)
            score = (self.output_bias + (hidden2 * self.output_weights.unsqueeze(0)).sum(dim=1)).squeeze(-1)
            return score, dense_input, hidden2_pre

        def _fake_byte_shift_components_from_mask(self, pieces, squares, mask, side_to_move):
            input_weights_q = fake_quantize_to_int(
                self.input_weights,
                self.input_scale,
                np.iinfo(np.int16).min,
                np.iinfo(np.int16).max,
            )
            hidden_bias_q = fake_quantize_to_int(
                self.hidden_bias,
                self.input_scale,
                np.iinfo(np.int16).min,
                np.iinfo(np.int16).max,
            )
            white = self.accumulator_with_weights(0, pieces, squares, mask, input_weights_q, hidden_bias_q)
            black = self.accumulator_with_weights(1, pieces, squares, mask, input_weights_q, hidden_bias_q)
            accumulator_pre = self.dense_input_from_accumulators(white, black, side_to_move)
            accumulator_byte = fake_byte_activation_from_scaled(
                accumulator_pre,
                self.input_scale,
                self.activation_scale,
            )

            hidden2_weights_q = fake_quantize_to_int(
                self.hidden2_weights,
                self.hidden_scale * 2,
                -self.activation_scale,
                self.activation_scale,
            )
            hidden2_bias_q = fake_quantize_to_int(
                self.hidden2_bias,
                self.hidden_scale,
                np.iinfo(np.int32).min,
                np.iinfo(np.int32).max,
            )
            hidden2_pre = torch.nn.functional.linear(accumulator_byte, hidden2_weights_q, hidden2_bias_q)
            hidden2_byte = fake_byte_activation_from_scaled(hidden2_pre, self.hidden_scale, self.activation_scale)

            output_weights_q = fake_quantize_to_int(
                self.output_weights,
                self.output_scale * 2,
                -self.activation_scale,
                self.activation_scale,
            )
            output_bias_q = fake_quantize_to_int(
                self.output_bias,
                self.output_scale,
                np.iinfo(np.int32).min,
                np.iinfo(np.int32).max,
            )
            score_int = (output_bias_q + (hidden2_byte * output_weights_q.unsqueeze(0)).sum(dim=1)).squeeze(-1)
            score = fake_round_shift_signed(score_int, self.output_scale)

            with torch.no_grad():
                _, dense_input_float, hidden2_pre_float = self._float_components_from_mask(
                    pieces,
                    squares,
                    mask,
                    side_to_move,
                )
            return score, {
                "accumulator_pre": dense_input_float,
                "hidden2_pre": hidden2_pre_float,
                "accumulator_byte": accumulator_byte,
                "hidden2_byte": hidden2_byte,
                "hidden2_weights_q": hidden2_weights_q,
                "output_weights_q": output_weights_q,
            }

        def _forward_components(self, pieces, squares, piece_count, side_to_move):
            max_pieces = pieces.shape[1]
            mask = (torch.arange(max_pieces, device=pieces.device).unsqueeze(0) < piece_count.unsqueeze(1)).float()
            if self.quantization_mode == "fake-byte-shift":
                return self._fake_byte_shift_components_from_mask(pieces, squares, mask, side_to_move)
            score, dense_input, hidden2_pre = self._float_components_from_mask(pieces, squares, mask, side_to_move)
            return score, {
                "accumulator_pre": dense_input,
                "hidden2_pre": hidden2_pre,
            }

        def forward_with_intermediates(self, pieces, squares, piece_count, side_to_move):
            return self._forward_components(pieces, squares, piece_count, side_to_move)

        def forward(self, pieces, squares, piece_count, side_to_move):
            score, _ = self._forward_components(pieces, squares, piece_count, side_to_move)
            return score

    return TinyNnueModel
