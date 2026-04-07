from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONTRACT_PATH = SCRIPT_DIR / "nnue_contract.json"
MAX_PIECES = 32

PIECE_FROM_FEN = {
    "P": 1,
    "N": 2,
    "B": 3,
    "R": 4,
    "Q": 5,
    "K": 6,
    "p": 7,
    "n": 8,
    "b": 9,
    "r": 10,
    "q": 11,
    "k": 12,
}

DATASET_DTYPE = np.dtype(
    [
        ("side_to_move", np.uint8),
        ("piece_count", np.uint8),
        ("pieces", np.uint8, (MAX_PIECES,)),
        ("squares", np.uint8, (MAX_PIECES,)),
        ("score", np.int32),
        ("result", np.int8),
    ]
)


def load_contract(path: Path | None = None) -> Dict[str, object]:
    contract_path = Path(path) if path is not None else DEFAULT_CONTRACT_PATH
    with contract_path.open("r", encoding="utf-8") as handle:
        contract = json.load(handle)
    contract["contract_sha256"] = contract_sha256(contract)
    contract["contract_path"] = str(contract_path)
    return contract


def contract_sha256(contract: Dict[str, object]) -> str:
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def piece_color(piece: int) -> int:
    if piece == 0:
        raise ValueError("EMPTY piece has no color")
    return 0 if piece <= 6 else 1


def piece_type(piece: int) -> int:
    if piece == 0:
        return 0
    if piece in (1, 7):
        return 1
    if piece in (2, 8):
        return 2
    if piece in (3, 9):
        return 3
    if piece in (4, 10):
        return 4
    if piece in (5, 11):
        return 5
    return 6


def mirror_square(square: int) -> int:
    rank = square >> 3
    file = square & 7
    return (7 - rank) * 8 + file


def normalized_square(piece: int, square: int) -> int:
    return square if piece <= 6 else mirror_square(square)


def parse_fen_sparse(fen: str) -> Tuple[int, List[int], List[int]]:
    fields = fen.strip().split()
    if len(fields) != 6:
        raise ValueError(f"Expected full FEN with 6 fields, got: {fen}")

    board_field, side_field = fields[0], fields[1]
    ranks = board_field.split("/")
    if len(ranks) != 8:
        raise ValueError(f"Expected 8 ranks in FEN, got: {fen}")

    pieces: List[int] = []
    squares: List[int] = []
    white_kings = 0
    black_kings = 0

    for fen_rank_index, rank_text in enumerate(ranks):
        board_rank = 7 - fen_rank_index
        file_index = 0
        for ch in rank_text:
            if ch.isdigit():
                file_index += int(ch)
                continue
            if ch not in PIECE_FROM_FEN:
                raise ValueError(f"Unexpected piece token {ch!r} in FEN: {fen}")
            if file_index >= 8:
                raise ValueError(f"Rank overflow in FEN: {fen}")
            piece = PIECE_FROM_FEN[ch]
            square = board_rank * 8 + file_index
            pieces.append(piece)
            squares.append(square)
            white_kings += 1 if piece == 6 else 0
            black_kings += 1 if piece == 12 else 0
            file_index += 1
        if file_index != 8:
            raise ValueError(f"Rank width mismatch in FEN: {fen}")

    if len(pieces) > MAX_PIECES:
        raise ValueError(f"Too many pieces ({len(pieces)}) in FEN: {fen}")
    if white_kings != 1 or black_kings != 1:
        raise ValueError(f"Expected exactly one king of each color in FEN: {fen}")
    if side_field not in ("w", "b"):
        raise ValueError(f"Unexpected side-to-move field {side_field!r} in FEN: {fen}")

    order = sorted(range(len(pieces)), key=lambda idx: squares[idx])
    ordered_pieces = [pieces[idx] for idx in order]
    ordered_squares = [squares[idx] for idx in order]
    side_to_move = 0 if side_field == "w" else 1
    return side_to_move, ordered_pieces, ordered_squares


def encode_sample(fen: str, score: int, result: int) -> np.void:
    side_to_move, pieces, squares = parse_fen_sparse(fen)
    encoded = np.zeros((), dtype=DATASET_DTYPE)
    encoded["side_to_move"] = side_to_move
    encoded["piece_count"] = len(pieces)
    encoded["pieces"][: len(pieces)] = np.asarray(pieces, dtype=np.uint8)
    encoded["squares"][: len(squares)] = np.asarray(squares, dtype=np.uint8)
    encoded["score"] = int(score)
    encoded["result"] = int(result)
    return encoded


def file_centrality(square: int) -> int:
    file_index = square & 7
    distance = min(abs(file_index - 3), abs(file_index - 4))
    return 3 - distance


def rank_centrality(square: int) -> int:
    rank = square >> 3
    distance = min(abs(rank - 3), abs(rank - 4))
    return 3 - distance


def centrality(square: int) -> int:
    return file_centrality(square) + rank_centrality(square)


def piece_square_weight(piece_type_value: int, square: int) -> int:
    rank = square >> 3
    if piece_type_value == 1:
        return rank * 4 + file_centrality(square) * 2 - (2 if rank == 1 else 0)
    if piece_type_value == 2:
        return centrality(square) * 8 - 12
    if piece_type_value == 3:
        return centrality(square) * 5 + rank * 2 - 10
    if piece_type_value == 4:
        return rank * 2 + file_centrality(square) * 2 - 6
    if piece_type_value == 5:
        return centrality(square) * 3 + rank - 8
    if piece_type_value == 6:
        return (7 - rank) * 4 + (6 if file_centrality(square) == 0 else 0) - centrality(square) * 2 - 10
    return 0


def pawn_advance_weight(square: int) -> int:
    return (square >> 3) * 4


def build_seeded_weights(contract: Dict[str, object]) -> Dict[str, np.ndarray | int]:
    hidden_size = int(contract["hidden_size"])
    input_weights = np.zeros((2, 13, 64, hidden_size), dtype=np.int16)
    hidden_bias = np.zeros((hidden_size,), dtype=np.int16)
    output_weights = np.zeros((hidden_size,), dtype=np.int16)
    output_bias = 0

    friendly_count_base = 0
    enemy_count_base = 5
    friendly_pst_unit = 10
    enemy_pst_unit = 11
    friendly_pawn_advance_unit = 12
    enemy_pawn_advance_unit = 13
    friendly_bishop_pair_unit = 14
    enemy_bishop_pair_unit = 15

    hidden_bias[friendly_pst_unit] = 128
    hidden_bias[enemy_pst_unit] = 128
    hidden_bias[friendly_pawn_advance_unit] = 128
    hidden_bias[enemy_pawn_advance_unit] = 128
    hidden_bias[friendly_bishop_pair_unit] = -64
    hidden_bias[enemy_bishop_pair_unit] = -64

    output_weights[friendly_count_base + 0] = 100
    output_weights[friendly_count_base + 1] = 320
    output_weights[friendly_count_base + 2] = 330
    output_weights[friendly_count_base + 3] = 500
    output_weights[friendly_count_base + 4] = 900
    output_weights[enemy_count_base + 0] = -100
    output_weights[enemy_count_base + 1] = -320
    output_weights[enemy_count_base + 2] = -330
    output_weights[enemy_count_base + 3] = -500
    output_weights[enemy_count_base + 4] = -900
    output_weights[friendly_pst_unit] = 1
    output_weights[enemy_pst_unit] = -1
    output_weights[friendly_pawn_advance_unit] = 1
    output_weights[enemy_pawn_advance_unit] = -1
    output_weights[friendly_bishop_pair_unit] = 1
    output_weights[enemy_bishop_pair_unit] = -1

    for perspective in range(2):
        for piece in range(1, 13):
            friendly = piece_color(piece) == perspective
            piece_type_value = piece_type(piece)
            for square in range(64):
                norm_square = normalized_square(piece, square)
                weights = input_weights[perspective, piece, square]
                if 1 <= piece_type_value <= 5:
                    unit = friendly_count_base + (piece_type_value - 1) if friendly else enemy_count_base + (piece_type_value - 1)
                    weights[unit] = 1

                pst_unit = friendly_pst_unit if friendly else enemy_pst_unit
                weights[pst_unit] += piece_square_weight(piece_type_value, norm_square)

                if piece_type_value == 1:
                    pawn_unit = friendly_pawn_advance_unit if friendly else enemy_pawn_advance_unit
                    weights[pawn_unit] += pawn_advance_weight(norm_square)

                if piece_type_value == 3:
                    pair_unit = friendly_bishop_pair_unit if friendly else enemy_bishop_pair_unit
                    weights[pair_unit] += 64

    return {
        "input_weights": input_weights,
        "hidden_bias": hidden_bias,
        "output_weights": output_weights,
        "output_bias": output_bias,
    }


def trunc_divide_by_two(value: int) -> int:
    return value // 2 if value >= 0 else -((-value) // 2)


def integer_model_eval(
    weights: Dict[str, np.ndarray | int],
    side_to_move: int,
    pieces: Sequence[int],
    squares: Sequence[int],
    clip_max: int,
) -> int:
    input_weights = weights["input_weights"]
    hidden_bias = weights["hidden_bias"].astype(np.int32)
    output_weights = weights["output_weights"].astype(np.int32)
    output_bias = int(weights["output_bias"])

    perspective_scores: List[int] = []
    for perspective in (0, 1):
        hidden = hidden_bias.copy()
        for piece, square in zip(pieces, squares):
            hidden += input_weights[perspective, piece, square].astype(np.int32)
        activated = np.clip(hidden, 0, clip_max)
        score = output_bias + int((activated * output_weights).sum())
        perspective_scores.append(score)

    combined = trunc_divide_by_two(perspective_scores[0] - perspective_scores[1])
    return combined if side_to_move == 0 else -combined


def samples_to_batch_arrays(samples: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    return (
        samples["pieces"].astype(np.int64, copy=False),
        samples["squares"].astype(np.int64, copy=False),
        samples["piece_count"].astype(np.int64, copy=False),
        samples["side_to_move"].astype(np.int64, copy=False),
    )


def compact_json(data: Dict[str, object]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"
