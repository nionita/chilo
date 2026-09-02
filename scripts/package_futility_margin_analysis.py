#!/usr/bin/env python3
"""Create a self-contained Windows package for one futility-margin stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": sha256(path),
        "size": path.stat().st_size,
    }


def checked_file(value: str, name: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"{name} is not a file: {path}")
    return path


def copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="New package directory, without the .zip suffix")
    parser.add_argument("--analyzer", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--target-depth", type=int, required=True)
    parser.add_argument("--previous-margins", default="")
    parser.add_argument("--max-fens", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, required=True)
    parser.add_argument("--report-every", type=int, default=100)
    parser.add_argument("--mate-position-policy", choices=("keep_finite_moves", "exclude_position"), default="keep_finite_moves")
    args = parser.parse_args()
    if not 1 <= args.target_depth <= 7:
        raise SystemExit("--target-depth must be in 1..7")
    if args.max_fens < 0 or args.sample_seed < 0 or args.report_every < 1:
        raise SystemExit("--max-fens and --sample-seed must be nonnegative; --report-every must be positive")
    try:
        margins = [] if not args.previous_margins else [int(value) for value in args.previous_margins.split(",")]
    except ValueError as error:
        raise SystemExit("--previous-margins must be comma-separated integers") from error
    if len(margins) != args.target_depth - 1 or any(value < 0 for value in margins):
        raise SystemExit("--previous-margins must contain target-depth - 1 nonnegative integers")

    output = Path(args.output_dir).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing package directory: {output}")
    archive = output.with_suffix(".zip")
    if archive.exists():
        raise SystemExit(f"refusing to overwrite existing archive: {archive}")
    analyzer = checked_file(args.analyzer, "analyzer")
    input_path = checked_file(args.input, "input")
    weights = checked_file(args.weights, "weights")
    input_manifest = Path(str(input_path) + ".manifest.json")
    if not input_manifest.is_file():
        raise SystemExit(f"input collector manifest not found: {input_manifest}")
    try:
        if json.loads(input_manifest.read_text(encoding="utf-8"))["output"]["sha256"] != sha256(input_path):
            raise SystemExit("input does not match its collector manifest")
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SystemExit(f"invalid collector manifest: {input_manifest}") from error

    runner = Path(__file__).with_name("run_futility_margin_analysis.py").resolve()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    output.mkdir(parents=True)
    copy(analyzer, output / "analyzer" / "futility_margin_analysis.exe")
    copy(input_path, output / "input" / "sites.fen")
    copy(input_manifest, output / "input" / "sites.fen.manifest.json")
    copy(weights, output / "weights" / weights.name)
    copy(runner, output / "scripts" / runner.name)
    config = {
        "analyzer": "../analyzer/futility_margin_analysis.exe",
        "input": "../input/sites.fen",
        "weights": f"../weights/{weights.name}",
        "target_depth": args.target_depth,
        "previous_margins": margins,
        "max_fens": args.max_fens,
        "sample_seed": args.sample_seed,
        "report_every": args.report_every,
        "mate_position_policy": args.mate_position_policy,
    }
    (output / "config").mkdir()
    (output / "config" / "calibration.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (output / "run-analysis.cmd").write_text(
        "@echo off\r\nsetlocal\r\n"
        "if exist run\\analysis_manifest.json (\r\n"
        "  echo Existing run detected. Use resume-analysis.cmd.\r\n"
        "  exit /b 1\r\n)\r\n"
        "python scripts\\run_futility_margin_analysis.py --config config\\calibration.json --run-dir run --new\r\n",
        encoding="utf-8",
    )
    (output / "resume-analysis.cmd").write_text(
        "@echo off\r\nsetlocal\r\n"
        "python scripts\\run_futility_margin_analysis.py --config config\\calibration.json --run-dir run --resume\r\n",
        encoding="utf-8",
    )
    (output / "README.txt").write_text(
        "Futility margin analysis: depth %d\r\n\r\n"
        "Requirements: Windows x64 with AVX2 and Python available as `python`.\r\n"
        "Run run-analysis.cmd once. It creates run/ and refuses to overwrite it.\r\n"
        "After an interruption, run resume-analysis.cmd. Do not edit config or packaged artifacts before resume.\r\n\r\n"
        "Expected run outputs:\r\n"
        "  run/analysis_manifest.json\r\n  run/selected.fens\r\n  run/positions.jsonl\r\n"
        "  run/mate-risks.jsonl\r\n  run/completed.indices\r\n" % args.target_depth,
        encoding="utf-8",
    )
    files = [path for path in sorted(output.rglob("*")) if path.is_file()]
    manifest = {
        "schema": "chilo.futility_margin_analysis.package.v1",
        "purpose": "Exact recursive futility-margin analysis on Windows",
        "git_revision": revision,
        "source_dirty": dirty,
        "command": "run-analysis.cmd",
        "target_depth": args.target_depth,
        "previous_margins": margins,
        "max_fens": args.max_fens,
        "sample_seed": args.sample_seed,
        "mate_position_policy": args.mate_position_policy,
        "files": [identity(path, output) for path in files],
    }
    manifest_path = output / "package_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(output.parent))
    with zipfile.ZipFile(archive) as zipped:
        expected = {str(path.relative_to(output.parent)).replace("\\", "/") for path in output.rglob("*") if path.is_file()}
        if set(zipped.namelist()) != expected:
            raise SystemExit("archive content verification failed")
    print(f"Created {archive}")
    print(f"SHA-256 {sha256(archive)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
