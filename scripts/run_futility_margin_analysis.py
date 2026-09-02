#!/usr/bin/env python3
"""Prepare and resume one exact, recursive futility-margin analysis run."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Sequence


SCHEMA = "chilo.futility_margin_analysis.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> Dict[str, Any]:
    return {"path": str(path), "sha256": sha256(path), "size": path.stat().st_size}


def resolve(config: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (config.parent / path).resolve() if not path.is_absolute() else path.resolve()


def require_int(raw: Any, name: str, minimum: int = 0) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < minimum:
        raise SystemExit(f"{name} must be an integer >= {minimum}")
    return raw


def load_settings(config_path: Path) -> Dict[str, Any]:
    raw_bytes = config_path.read_bytes()
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid JSON config: {error}") from error
    allowed = {"analyzer", "input", "weights", "target_depth", "previous_margins", "max_fens", "sample_seed", "report_every", "mate_position_policy"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise SystemExit("config must be an object with only analyzer, input, weights, target_depth, previous_margins, max_fens, sample_seed, report_every, and mate_position_policy")
    for key in ("analyzer", "input", "weights", "target_depth", "previous_margins", "max_fens", "sample_seed", "report_every", "mate_position_policy"):
        if key not in raw:
            raise SystemExit(f"missing required config field: {key}")
    analyzer = resolve(config_path, raw["analyzer"])
    input_path = resolve(config_path, raw["input"])
    weights = resolve(config_path, raw["weights"])
    if not analyzer.is_file() or not input_path.is_file() or not weights.is_file():
        raise SystemExit("analyzer, input, and weights must be existing files")
    target_depth = require_int(raw["target_depth"], "target_depth", 1)
    if target_depth > 7:
        raise SystemExit("target_depth must be <= 7")
    margins = raw["previous_margins"]
    if not isinstance(margins, list) or len(margins) != target_depth - 1 or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in margins):
        raise SystemExit("previous_margins must contain exactly target_depth - 1 nonnegative integers")
    max_fens = require_int(raw["max_fens"], "max_fens")
    seed = require_int(raw["sample_seed"], "sample_seed")
    report_every = require_int(raw["report_every"], "report_every", 1)
    policy = raw["mate_position_policy"]
    if policy not in ("keep_finite_moves", "exclude_position"):
        raise SystemExit("mate_position_policy must be keep_finite_moves or exclude_position")
    sidecar = Path(str(input_path) + ".manifest.json")
    if not sidecar.is_file():
        raise SystemExit(f"input manifest not found: {sidecar}")
    try:
        source_manifest = json.loads(sidecar.read_text(encoding="utf-8"))
        expected = source_manifest["output"]["sha256"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SystemExit(f"invalid input manifest: {sidecar}") from error
    if expected != sha256(input_path):
        raise SystemExit("input SHA-256 does not match its adjacent collector manifest")
    return {"raw_sha256": hashlib.sha256(raw_bytes).hexdigest(), "analyzer": analyzer, "input": input_path, "weights": weights,
            "target_depth": target_depth, "previous_margins": margins, "max_fens": max_fens, "sample_seed": seed,
            "report_every": report_every, "mate_position_policy": policy, "input_manifest": identity(sidecar)}


def select_fens(input_path: Path, maximum: int, seed: int) -> List[str]:
    with input_path.open(encoding="utf-8") as handle:
        fens = [line.strip() for line in handle if line.strip()]
    if maximum == 0 or maximum >= len(fens):
        return fens
    rng = random.Random(seed)
    reservoir = fens[:maximum]
    for index in range(maximum, len(fens)):
        replacement = rng.randrange(index + 1)
        if replacement < maximum:
            reservoir[replacement] = fens[index]
    return reservoir


def atomic_json(path: Path, value: Dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-dir", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--new", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    config = Path(args.config).expanduser().resolve()
    settings = load_settings(config)
    run_dir = Path(args.run_dir).expanduser().resolve()
    manifest_path = run_dir / "analysis_manifest.json"
    selected_path = run_dir / "selected.fens"
    result_path = run_dir / "positions.jsonl"
    mates_path = run_dir / "mate-risks.jsonl"
    completed_path = run_dir / "completed.indices"

    manifest = {"schema": SCHEMA, "config": {"path": str(config), "sha256": settings.pop("raw_sha256")},
                "analyzer": identity(settings["analyzer"]), "input": identity(settings["input"]),
                "input_manifest": settings.pop("input_manifest"), "weights": identity(settings["weights"]),
                "target_depth": settings["target_depth"], "previous_margins": settings["previous_margins"],
                "max_fens": settings["max_fens"], "sample_seed": settings["sample_seed"],
                "report_every": settings["report_every"], "mate_position_policy": settings["mate_position_policy"]}
    if args.new:
        if run_dir.exists():
            raise SystemExit(f"new run directory already exists: {run_dir}")
        if args.dry_run:
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0
        run_dir.mkdir(parents=True)
        selected = select_fens(settings["input"], settings["max_fens"], settings["sample_seed"])
        selected_path.write_text("".join(fen + "\n" for fen in selected), encoding="utf-8")
        manifest["selected_fens"] = identity(selected_path)
        manifest["selected_count"] = len(selected)
        atomic_json(manifest_path, manifest)
    else:
        if not manifest_path.is_file() or not selected_path.is_file():
            raise SystemExit("resume requires analysis_manifest.json and selected.fens")
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = dict(manifest)
        expected["selected_fens"] = existing.get("selected_fens")
        expected["selected_count"] = existing.get("selected_count")
        if existing != expected:
            raise SystemExit("run manifest does not match configured artifacts; use a new run directory")

    command = [str(settings["analyzer"]), "--input", str(selected_path), "--weights", str(settings["weights"]),
               "--target-depth", str(settings["target_depth"]), "--previous-margins", ",".join(str(value) for value in settings["previous_margins"]) or "-",
               "--mate-policy", settings["mate_position_policy"], "--results", str(result_path), "--mates", str(mates_path),
               "--completed", str(completed_path), "--report-every", str(settings["report_every"])]
    print("Command:", subprocess.list2cmdline(command))
    if args.dry_run:
        return 0
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
