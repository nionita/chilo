#!/usr/bin/env python3
from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from nnue_common import integer_model_eval, load_contract
from export_nnue import load_torch_checkpoint, quantize_weights


ROOT_DIR = Path(__file__).resolve().parent.parent
GENERATED_HEADER = ROOT_DIR / "generated_nnue_weights.h"
GENERATED_MANIFEST = ROOT_DIR / "generated_nnue_manifest.json"


def run(*args: str) -> None:
    subprocess.run(list(args), cwd=ROOT_DIR, check=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        csv_path = temp_dir / "samples.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["eval_fen", "score", "result"])
            writer.writerow(["4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "901", "1"])
            writer.writerow(["4k3/8/8/8/8/8/8/3QK3 b - - 0 1", "-901", "-1"])
            writer.writerow(["4k3/8/8/8/3N4/8/8/4K3 w - - 0 1", "31", "0"])
            writer.writerow(["4k3/8/8/8/8/8/8/4K3 w - - 0 1", "0", "0"])

        dataset_dir = temp_dir / "dataset"
        training_dir = temp_dir / "training"
        export_dir = temp_dir / "export"
        export_dir.mkdir(parents=True, exist_ok=True)

        run(
            sys.executable,
            str(ROOT_DIR / "scripts" / "prepare_nnue_dataset.py"),
            "--input",
            str(csv_path),
            "--output-dir",
            str(dataset_dir),
            "--samples-per-shard",
            "2",
            "--validation-fraction",
            "0.5",
            "--seed",
            "7",
            "--overwrite",
        )
        run(
            sys.executable,
            str(ROOT_DIR / "scripts" / "train_nnue.py"),
            "--dataset",
            str(dataset_dir),
            "--output-dir",
            str(training_dir),
            "--epochs",
            "2",
            "--batch-size",
            "2",
            "--shuffle-buffer-size",
            "4",
            "--report-batches",
            "1",
        )

        exported_header = export_dir / "generated_nnue_weights.h"
        exported_manifest = export_dir / "generated_nnue_manifest.json"
        checkpoint_path = training_dir / "best.pt"
        run(
            sys.executable,
            str(ROOT_DIR / "scripts" / "export_nnue.py"),
            "--checkpoint",
            str(checkpoint_path),
            "--dataset-dir",
            str(dataset_dir),
            "--validation-samples",
            "4",
            "--tolerance",
            "8",
            "--output-header",
            str(exported_header),
            "--output-manifest",
            str(exported_manifest),
        )

        original_header = read_text(GENERATED_HEADER)
        original_manifest = read_text(GENERATED_MANIFEST)
        try:
            GENERATED_HEADER.write_text(read_text(exported_header), encoding="utf-8")
            GENERATED_MANIFEST.write_text(read_text(exported_manifest), encoding="utf-8")

            run("make", "eval_fen_debug")
            run("make", "engine_tests_debug")
            run(str(ROOT_DIR / "engine_tests_debug"))

            contract = load_contract()
            _, float_weights = load_torch_checkpoint(checkpoint_path)
            quantized = quantize_weights(float_weights)
            test_fens = [
                "4k3/8/8/8/8/8/8/3QK3 w - - 0 1",
                "4k3/8/8/8/8/8/8/3QK3 b - - 0 1",
                "4k3/8/8/8/3N4/8/8/4K3 w - - 0 1",
            ]
            completed = subprocess.run(
                [str(ROOT_DIR / "eval_fen_debug"), *test_fens],
                cwd=ROOT_DIR,
                check=True,
                capture_output=True,
                text=True,
            )
            cpp_scores = [int(line) for line in completed.stdout.strip().splitlines()]
            python_scores = []
            for fen in test_fens:
                fields = fen.split()
                board = fields[0]
                side_to_move = 0 if fields[1] == "w" else 1
                pieces = []
                squares = []
                for rank_index, rank_text in enumerate(board.split("/")):
                    board_rank = 7 - rank_index
                    file_index = 0
                    for ch in rank_text:
                        if ch.isdigit():
                            file_index += int(ch)
                            continue
                        piece = {
                            "P": 1, "N": 2, "B": 3, "R": 4, "Q": 5, "K": 6,
                            "p": 7, "n": 8, "b": 9, "r": 10, "q": 11, "k": 12,
                        }[ch]
                        pieces.append(piece)
                        squares.append(board_rank * 8 + file_index)
                        file_index += 1
                python_scores.append(integer_model_eval(quantized, side_to_move, pieces, squares, int(contract["clip_max"])))

            if cpp_scores != python_scores:
                raise SystemExit(f"C++ / Python eval mismatch: cpp={cpp_scores} python={python_scores}")
        finally:
            GENERATED_HEADER.write_text(original_header, encoding="utf-8")
            GENERATED_MANIFEST.write_text(original_manifest, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
