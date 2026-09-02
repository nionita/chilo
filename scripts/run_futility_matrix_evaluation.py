#!/usr/bin/env python3
"""Run a fixed matrix of full futility probes and compare trusted controls.

The package configuration declares candidate tuples to probe, immutable
candidate-output controls, and full per-root development/selection corpora.
All candidate-by-corpus probes run concurrently up to ``worker_limit``.  A
fresh ``run/`` directory proves one coherent matrix and is never overwritten.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


SCHEMA = "chilo.futility_matrix_evaluation.v1"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object: {path}")
    return value


def package_path(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} must be a non-empty package-relative path")
    path = (root / value).resolve()
    if root not in path.parents and path != root:
        raise RuntimeError(f"{label} escapes package root: {value}")
    return path


def require_file(root: Path, value: Any, label: str) -> Path:
    path = package_path(root, value, label)
    if not path.is_file():
        raise RuntimeError(f"missing {label}: {path}")
    return path


def require_int(value: Any, label: str, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise RuntimeError(f"{label} must be an integer >= {minimum}")
    return value


def margins(value: Any, label: str) -> List[int]:
    if not isinstance(value, list) or not value or not all(isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in value):
        raise RuntimeError(f"{label} must be a non-empty list of non-negative integers")
    if value != sorted(value):
        raise RuntimeError(f"{label} must be nondecreasing")
    return list(value)


def variant_entries(value: Any, label: str, include_outputs: bool = False) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"{label} must be a non-empty list")
    result = []
    identifiers = set()
    for index, item in enumerate(value):
        expected = {"id", "margins", "outputs"} if include_outputs else {"id", "margins"}
        if not isinstance(item, dict) or set(item) != expected:
            fields = "id, margins, outputs" if include_outputs else "id and margins"
            raise RuntimeError(f"{label}[{index}] must contain only {fields}")
        identifier = item["id"]
        if not isinstance(identifier, str) or not identifier or identifier == "f01" or identifier in identifiers:
            raise RuntimeError(f"{label}[{index}].id must be a unique non-f01 identifier")
        identifiers.add(identifier)
        entry = {"id": identifier, "margins": margins(item["margins"], f"{label}[{index}].margins")}
        if include_outputs:
            entry["outputs"] = item["outputs"]
        result.append(entry)
    return result


def load_config(root: Path, path: Path) -> Dict[str, Any]:
    config = dict(read_json(path, "matrix-evaluation config"))
    allowed = {
        "schema", "purpose", "probe", "weights", "candidate_nodes", "worker_limit", "score_scale",
        "baseline_margins", "report_every", "corpora", "candidates", "controls",
    }
    unknown = sorted(set(config) - allowed)
    required = allowed - {"purpose"}
    missing = sorted(required - set(config))
    if config.get("schema") != SCHEMA or unknown or missing:
        detail = []
        if config.get("schema") != SCHEMA:
            detail.append(f"schema must be {SCHEMA}")
        if unknown:
            detail.append("unknown=" + ", ".join(unknown))
        if missing:
            detail.append("missing=" + ", ".join(missing))
        raise RuntimeError("invalid matrix-evaluation config: " + "; ".join(detail))
    probe = require_file(root, config["probe"], "probe")
    weights = require_file(root, config["weights"], "weights")
    candidate_nodes = require_int(config["candidate_nodes"], "candidate_nodes")
    workers = require_int(config["worker_limit"], "worker_limit")
    report_every = require_int(config["report_every"], "report_every")
    baseline = margins(config["baseline_margins"], "baseline_margins")
    score_scale = config["score_scale"]
    if isinstance(score_scale, bool) or not isinstance(score_scale, (int, float)) or score_scale <= 0:
        raise RuntimeError("score_scale must be a finite number > 0")
    candidates = variant_entries(config["candidates"], "candidates")
    controls = variant_entries(config["controls"], "controls", include_outputs=True)
    overlap = {item["id"] for item in candidates} & {item["id"] for item in controls}
    if overlap:
        raise RuntimeError("candidate/control identifiers overlap: " + ", ".join(sorted(overlap)))
    corpora_raw = config["corpora"]
    if not isinstance(corpora_raw, list) or not corpora_raw:
        raise RuntimeError("corpora must be a non-empty list")
    corpora = []
    corpus_ids = set()
    for index, corpus in enumerate(corpora_raw):
        if not isinstance(corpus, dict) or set(corpus) != {"id", "input", "anchor_dir", "rescue_dir"}:
            raise RuntimeError(f"corpora[{index}] must contain only id, input, anchor_dir, rescue_dir")
        identifier = corpus["id"]
        if not isinstance(identifier, str) or not identifier or identifier in corpus_ids:
            raise RuntimeError(f"corpora[{index}].id must be unique and non-empty")
        corpus_ids.add(identifier)
        source = require_file(root, corpus["input"], f"{identifier} input")
        anchor = package_path(root, corpus["anchor_dir"], f"{identifier} anchor_dir")
        rescue = package_path(root, corpus["rescue_dir"], f"{identifier} rescue_dir")
        for artifact in (
            anchor / "probes" / "reference.jsonl", anchor / "probes" / "baseline.jsonl",
            rescue / "rescue_reference.jsonl", rescue / "rescue_baseline.jsonl", rescue / "rescue_manifest.json",
            rescue / "rescue_results.json", rescue / "combined_population.json",
        ):
            if not artifact.is_file():
                raise RuntimeError(f"missing {identifier} provenance artifact: {artifact}")
        corpora.append({"id": identifier, "input": source, "anchor": anchor, "rescue": rescue})
    for control in controls:
        outputs = control["outputs"]
        if not isinstance(outputs, dict) or set(outputs) != corpus_ids:
            raise RuntimeError(f"control {control['id']!r} must name one output for every corpus")
        control["outputs"] = {
            corpus_id: require_file(root, relative, f"control {control['id']} {corpus_id} output")
            for corpus_id, relative in outputs.items()
        }
    return {
        "raw": config, "probe": probe, "weights": weights, "candidate_nodes": candidate_nodes,
        "workers": workers, "report_every": report_every, "score_scale": float(score_scale), "baseline": baseline,
        "candidates": candidates, "controls": controls, "corpora": corpora,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    config_path = package_path(root, args.config, "config")
    settings = load_config(root, config_path)
    raw = settings["raw"]
    jobs = [(candidate, corpus) for candidate in settings["candidates"] for corpus in settings["corpora"]]
    if args.dry_run:
        print(f"validated {len(jobs)} full-evaluation jobs; worker ceiling={settings['workers']}, actual parallel jobs={min(settings['workers'], len(jobs))}")
        for candidate, corpus in jobs:
            print(f"{corpus['id']}: {candidate['id']} margins={','.join(str(value) for value in candidate['margins'])}")
        return 0
    run_dir = root / "run"
    if run_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing result directory: {run_dir}")
    run_dir.mkdir()
    write_json(run_dir / "launch_config.json", raw)
    command_base = [str(settings["probe"]), "--nodes", str(settings["candidate_nodes"]), "--weights", str(settings["weights"]), "--report-every", str(settings["report_every"])]

    def run_probe(candidate: Mapping[str, Any], corpus: Mapping[str, Any]) -> Dict[str, Any]:
        corpus_dir = run_dir / str(corpus["id"])
        probes_dir, logs_dir = corpus_dir / "probes", corpus_dir / "logs"
        probes_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(exist_ok=True)
        output = probes_dir / f"{candidate['id']}.jsonl"
        log = logs_dir / f"{candidate['id']}.log"
        command = command_base + ["--futility-margins", ",".join(str(value) for value in candidate["margins"]), "--output", str(output), "--overwrite", str(corpus["input"])]
        with log.open("w", encoding="utf-8") as handle:
            handle.write("command=" + json.dumps(command) + "\n")
            handle.flush()
            completed = subprocess.run(command, cwd=root, stdout=handle, stderr=subprocess.STDOUT, text=True, check=False)
            handle.write(f"exit_code={completed.returncode}\n")
        if completed.returncode:
            raise RuntimeError(f"probe failed for {candidate['id']} on {corpus['id']}; see {log}")
        return {"candidate": candidate["id"], "corpus": corpus["id"], "output": str(output), "log": str(log)}

    outcomes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(settings["workers"], len(jobs))) as executor:
        futures = [executor.submit(run_probe, candidate, corpus) for candidate, corpus in jobs]
        for future in concurrent.futures.as_completed(futures):
            outcome = future.result()
            outcomes.append(outcome)
            print(f"matrix progress: {outcome['corpus']} {outcome['candidate']} complete", file=sys.stderr, flush=True)
    by_candidate_corpus = {(item["candidate"], item["corpus"]): Path(item["output"]) for item in outcomes}
    analyzer = root / "scripts" / "analyze_futility_risk.py"
    for corpus in settings["corpora"]:
        variants = [{"id": "f01", "margins": settings["baseline"], "output": str(Path(corpus["anchor"]) / "probes" / "baseline.jsonl")}]
        variants.extend({"id": control["id"], "margins": control["margins"], "output": str(control["outputs"][corpus["id"]])} for control in settings["controls"])
        variants.extend({"id": candidate["id"], "margins": candidate["margins"], "output": str(by_candidate_corpus[(candidate["id"], corpus["id"])])} for candidate in settings["candidates"])
        risk_config = {
            "candidate_nodes": settings["candidate_nodes"], "baseline_margins": settings["baseline"], "score_scale": settings["score_scale"],
            "development": {"reference_dir": str(corpus["anchor"]), "contract": "per_root_v1", "rescue_dir": str(corpus["rescue"])},
            "variants": variants, "tail_fractions": [0.05, 0.01], "regret_thresholds": [0.1, 0.25, 0.5, 1.0],
            "semantic_thresholds": {"advantage_cp": 150, "loss_cp": -150},
        }
        corpus_dir = run_dir / str(corpus["id"])
        risk_config_path = corpus_dir / "risk_config.json"
        write_json(risk_config_path, risk_config)
        subprocess.run([sys.executable, str(analyzer), "--config", str(risk_config_path), "--output-dir", str(corpus_dir / "risk-analysis")], cwd=root, check=True)
    completion = {"schema": SCHEMA, "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(), "jobs": outcomes}
    write_json(run_dir / "completion.json", completion)
    print(f"matrix complete: {len(outcomes)} probes and two consolidated risk reports under {run_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(1)
