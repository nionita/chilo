#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
GENERATED_DIR = ROOT_DIR / "generated"
GENERATED_HEADER = GENERATED_DIR / "generated_nnue_weights.h"
GENERATED_MANIFEST = GENERATED_DIR / "generated_nnue_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Chilo NNUE data workflow: optional dedup, prepare, train, export, and optional engine verification."
    )
    parser.add_argument(
        "--input",
        nargs="*",
        default=[],
        help="One or more collector CSV files. Required unless --dataset is supplied.",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="Existing prepared dataset root or manifest.json path. Skips dedup and prepare.",
    )
    parser.add_argument("--output-root", required=True, help="Directory for workflow outputs and summary logs.")
    parser.add_argument("--contract", default=None, help="Optional path to nnue_contract.json.")

    parser.add_argument("--dedup-mode", choices=("none", "exact-row"), default="none")
    parser.add_argument("--sort-buffer-size", default="50%")
    parser.add_argument("--sort-temp-dir", default=None)
    parser.add_argument("--sort-parallel", type=int, default=0)
    parser.add_argument("--dedup-report-every", type=int, default=1000000)

    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--samples-per-shard", type=int, default=1000000)
    parser.add_argument("--validation-fraction", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--prepare-report-every", type=int, default=100000)

    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--score-scale", type=float, default=600.0)
    parser.add_argument("--result-weight", type=float, default=0.25)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--init", choices=("seeded", "random"), default="seeded")
    parser.add_argument("--hidden-size", type=int, default=0)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--shuffle-buffer-size", type=int, default=8192)
    parser.add_argument("--report-batches", type=int, default=200)

    parser.add_argument("--skip-export", action="store_true")
    parser.add_argument("--validation-samples", type=int, default=256)
    parser.add_argument("--tolerance", type=float, default=256.0)
    parser.add_argument("--output-header", default=None)
    parser.add_argument("--output-manifest", default=None)
    parser.add_argument("--output-bin", default=None)

    parser.add_argument("--verify-engine", action="store_true")
    return parser.parse_args()


def run_step(summary: Dict[str, object], name: str, command: List[str]) -> None:
    print(f"[{name}] {' '.join(command)}")
    started = time.monotonic()
    subprocess.run(command, cwd=ROOT_DIR, check=True)
    elapsed = time.monotonic() - started
    summary["steps"].append(
        {
            "name": name,
            "command": command,
            "elapsed_seconds": elapsed,
        }
    )
    print(f"[{name}] completed in {elapsed:.1f}s")


def write_summary(path: Path, summary: Dict[str, object]) -> None:
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_engine_with_export(summary: Dict[str, object], header_path: Path, manifest_path: Path) -> None:
    original_header = GENERATED_HEADER.read_text(encoding="utf-8")
    original_manifest = GENERATED_MANIFEST.read_text(encoding="utf-8")
    try:
        GENERATED_HEADER.write_text(header_path.read_text(encoding="utf-8"), encoding="utf-8")
        GENERATED_MANIFEST.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
        run_step(summary, "build-engine-tests", ["make", "engine_tests_debug"])
        run_step(summary, "run-engine-tests", [str(ROOT_DIR / "build" / "debug" / "engine_tests_debug")])
    finally:
        GENERATED_HEADER.write_text(original_header, encoding="utf-8")
        GENERATED_MANIFEST.write_text(original_manifest, encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not args.input and not args.dataset:
        raise SystemExit("Provide at least one --input CSV file or an existing --dataset.")
    if args.verify_engine and args.skip_export:
        raise SystemExit("--verify-engine requires export output; remove --skip-export.")

    python_exe = sys.executable
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    summary_path = output_root / "run_summary.json"

    summary: Dict[str, object] = {
        "output_root": str(output_root.resolve()),
        "inputs": [str(Path(path).resolve()) for path in args.input],
        "dataset": None,
        "dedup_mode": args.dedup_mode,
        "status": "running",
        "steps": [],
    }
    try:
        dataset_path: Path
        if args.dataset:
            dataset_path = Path(args.dataset)
            summary["dataset"] = str(dataset_path.resolve())
        else:
            input_paths = [Path(path) for path in args.input]
            current_inputs = input_paths

            if args.dedup_mode == "exact-row":
                dedup_output = output_root / "dedup.csv"
                dedup_cmd = [
                    python_exe,
                    str(SCRIPT_DIR / "dedup_training_csv.py"),
                    "--input",
                    *[str(path) for path in input_paths],
                    "--output",
                    str(dedup_output),
                    "--sort-buffer-size",
                    args.sort_buffer_size,
                    "--report-every",
                    str(args.dedup_report_every),
                    "--overwrite",
                ]
                if args.sort_temp_dir:
                    dedup_cmd.extend(["--sort-temp-dir", args.sort_temp_dir])
                if args.sort_parallel > 0:
                    dedup_cmd.extend(["--sort-parallel", str(args.sort_parallel)])
                run_step(summary, "dedup", dedup_cmd)
                current_inputs = [dedup_output]
                summary["dedup_output"] = str(dedup_output.resolve())

            dataset_path = output_root / "dataset"
            prepare_cmd = [
                python_exe,
                str(SCRIPT_DIR / "prepare_nnue_dataset.py"),
                "--input",
                *[str(path) for path in current_inputs],
                "--output-dir",
                str(dataset_path),
                "--samples-per-shard",
                str(args.samples_per_shard),
                "--validation-fraction",
                str(args.validation_fraction),
                "--seed",
                str(args.seed),
                "--report-every",
                str(args.prepare_report_every),
                "--overwrite",
            ]
            if args.contract:
                prepare_cmd.extend(["--contract", args.contract])
            if args.limit > 0:
                prepare_cmd.extend(["--limit", str(args.limit)])
            run_step(summary, "prepare", prepare_cmd)
            summary["dataset"] = str(dataset_path.resolve())

        training_dir = output_root / "training"
        train_cmd = [
            python_exe,
            str(SCRIPT_DIR / "train_nnue.py"),
            "--dataset",
            str(dataset_path),
            "--output-dir",
            str(training_dir),
            "--epochs",
            str(args.epochs),
            "--batch-size",
            str(args.batch_size),
            "--learning-rate",
            str(args.learning_rate),
            "--weight-decay",
            str(args.weight_decay),
            "--score-scale",
            str(args.score_scale),
            "--result-weight",
            str(args.result_weight),
            "--seed",
            str(args.seed),
            "--device",
            args.device,
            "--init",
            args.init,
            "--hidden-size",
            str(args.hidden_size),
            "--num-workers",
            str(args.num_workers),
            "--shuffle-buffer-size",
            str(args.shuffle_buffer_size),
            "--report-batches",
            str(args.report_batches),
        ]
        if args.contract:
            train_cmd.extend(["--contract", args.contract])
        run_step(summary, "train", train_cmd)
        summary["training_dir"] = str(training_dir.resolve())
        summary["best_checkpoint"] = str((training_dir / "best.pt").resolve())

        if not args.skip_export:
            export_header = Path(args.output_header) if args.output_header else output_root / "export" / "generated_nnue_weights.h"
            export_manifest = Path(args.output_manifest) if args.output_manifest else output_root / "export" / "generated_nnue_manifest.json"
            export_bin = Path(args.output_bin) if args.output_bin else output_root / "export" / "weights.bin"
            export_header.parent.mkdir(parents=True, exist_ok=True)
            export_manifest.parent.mkdir(parents=True, exist_ok=True)
            export_bin.parent.mkdir(parents=True, exist_ok=True)

            export_cmd = [
                python_exe,
                str(SCRIPT_DIR / "export_nnue.py"),
                "--checkpoint",
                str(training_dir / "best.pt"),
                "--dataset-dir",
                str(dataset_path),
                "--validation-samples",
                str(args.validation_samples),
                "--tolerance",
                str(args.tolerance),
                "--output-header",
                str(export_header),
                "--output-manifest",
                str(export_manifest),
                "--output-bin",
                str(export_bin),
            ]
            if args.contract:
                export_cmd.extend(["--contract", args.contract])
            run_step(summary, "export", export_cmd)
            summary["export_header"] = str(export_header.resolve())
            summary["export_manifest"] = str(export_manifest.resolve())
            summary["export_bin"] = str(export_bin.resolve())

            if args.verify_engine:
                verify_engine_with_export(summary, export_header, export_manifest)

        summary["status"] = "completed"
        return 0
    except subprocess.CalledProcessError as exc:
        summary["status"] = "failed"
        summary["error"] = {
            "returncode": exc.returncode,
            "command": exc.cmd,
        }
        raise
    finally:
        write_summary(summary_path, summary)
        print(f"Wrote workflow summary to {summary_path}")


if __name__ == "__main__":
    raise SystemExit(main())
