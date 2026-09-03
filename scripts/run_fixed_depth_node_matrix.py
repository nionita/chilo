#!/usr/bin/env python3
"""Run fixed-depth node-count searches for a configured engine matrix.

Configured candidates share a bounded worker pool.  Results are restart-safe
per engine and intentionally compare tree size, not score quality.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA = "chilo.fixed_depth_node_matrix.v1"
INFO_RE = re.compile(r"^info depth (\d+) score .* nodes (\d+) time (\d+) nps (\d+)(.*)$")
BESTMOVE_RE = re.compile(r"^bestmove\s+(\S+)")
STAT_RE = re.compile(r"\b(cut_tt|cut_cap|cut_killer|cut_quiet|cut_promo|cut_other)\s+(\d+)\b")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    # Windows Defender/indexing can transiently hold the old checkpoint open.
    # The completed record is already durable, so retry the atomic replacement.
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.25)


def load_fens(path: Path) -> list[str]:
    result: list[str] = []
    for line_number, raw in enumerate(path.read_text().splitlines(), start=1):
        fen = raw.split("#", 1)[0].strip()
        if not fen:
            continue
        if len(fen.split()) < 6:
            raise ValueError(f"{path}:{line_number}: expected a full FEN")
        result.append(fen)
    if not result:
        raise ValueError(f"no FENs in {path}")
    return result


def run_one(engine: Path, weights: Path, fen: str, depth: int) -> dict[str, Any]:
    process = subprocess.Popen(
        [str(engine), "--weights", str(weights)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(f"uci\nposition fen {fen}\ngo depth {depth}\n")
    process.stdin.flush()
    info: dict[str, Any] | None = None
    bestmove: str | None = None
    stdout: list[str] = []
    for raw in process.stdout:
        line = raw.rstrip("\n")
        stdout.append(line)
        match = INFO_RE.match(line)
        if match and int(match.group(1)) == depth:
            info = {"nodes": int(match.group(2)), "engine_ms": int(match.group(3)), "nps": int(match.group(4))}
            info.update({key: int(value) for key, value in STAT_RE.findall(match.group(5))})
        match = BESTMOVE_RE.match(line)
        if match:
            bestmove = match.group(1)
            break
    process.stdin.write("quit\n")
    process.stdin.flush()
    _, stderr = process.communicate(timeout=10)
    if process.returncode != 0 or info is None or bestmove is None:
        raise RuntimeError(f"engine failure for {engine}: stdout={' | '.join(stdout)} stderr={stderr.strip()}")
    info["bestmove"] = bestmove
    return info


def recover_records(records_path: Path) -> tuple[int, dict[str, int]]:
    """Return the contiguous completed prefix and totals from durable records."""
    if not records_path.exists():
        return 0, {}
    by_index: dict[int, dict[str, Any]] = {}
    for line_number, line in enumerate(records_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        index = record.get("index")
        if not isinstance(index, int) or index < 0 or index in by_index:
            raise ValueError(f"{records_path}:{line_number}: invalid or duplicate record index")
        by_index[index] = record
    totals: dict[str, int] = {}
    index = 0
    while index in by_index:
        for key, value in by_index[index].items():
            if key not in ("index", "bestmove"):
                totals[key] = totals.get(key, 0) + int(value)
        index += 1
    if len(by_index) != index:
        raise ValueError(f"{records_path}: records do not form a contiguous prefix")
    return index, totals


def configured_candidates(config: dict[str, Any]) -> list[dict[str, str]]:
    raw_candidates = config.get("candidates")
    if not isinstance(raw_candidates, list) or len(raw_candidates) < 2:
        raise ValueError("config must contain at least two candidates")

    candidates: list[dict[str, str]] = []
    candidates_by_id: dict[str, dict[str, str]] = {}
    for index, item in enumerate(raw_candidates):
        if not isinstance(item, dict):
            raise ValueError(f"candidate {index}: expected an object")
        for key in ("id", "engine", "weights"):
            if not isinstance(item.get(key), str) or not item[key]:
                raise ValueError(f"candidate {index}: {key} must be a non-empty string")
        candidate = {key: item[key] for key in ("id", "engine", "weights")}
        if candidate["id"] in candidates_by_id:
            raise ValueError(f"duplicate candidate id: {candidate['id']}")
        candidates.append(candidate)
        candidates_by_id[candidate["id"]] = candidate

    # Older packages described sequential two-engine groups.  Preserve their
    # declared order, but intentionally discard the old barriers.
    groups = config.get("groups")
    if groups is None:
        return candidates
    if not isinstance(groups, list):
        raise ValueError("groups must be a list")
    flattened: list[str] = []
    for group_index, group in enumerate(groups):
        if not isinstance(group, list) or not group:
            raise ValueError(f"group {group_index}: expected a non-empty list")
        for candidate_id in group:
            if not isinstance(candidate_id, str) or candidate_id not in candidates_by_id:
                raise ValueError(f"group {group_index}: unknown candidate {candidate_id!r}")
            flattened.append(candidate_id)
    if len(flattened) != len(candidates) or len(set(flattened)) != len(flattened):
        raise ValueError("groups must contain every candidate exactly once")
    return [candidates_by_id[candidate_id] for candidate_id in flattened]


def validate_candidate_artifacts(candidates: list[dict[str, str]], root: Path) -> None:
    for candidate in candidates:
        candidate_id = candidate["id"]
        engine = root / candidate["engine"]
        weights = root / candidate["weights"]
        if not engine.is_file():
            raise ValueError(f"{candidate_id}: missing engine {engine}")
        if not weights.is_file():
            raise ValueError(f"{candidate_id}: missing weights {weights}")


def run_candidate(candidate: dict[str, str], root: Path, fens: list[str], depth: int, resume: bool) -> dict[str, Any]:
    candidate_id = candidate["id"]
    engine = root / candidate["engine"]
    weights = root / candidate["weights"]
    directory = root / "run" / candidate_id
    state_path = directory / "state.json"
    records_path = directory / "records.jsonl"
    if not engine.is_file() or not weights.is_file():
        raise ValueError(f"{candidate_id}: missing engine or weights")
    if directory.exists() and not resume:
        raise ValueError(f"{candidate_id}: {directory} already exists; use the resume launcher")
    directory.mkdir(parents=True, exist_ok=True)
    state = {"schema": SCHEMA, "candidate": candidate_id, "depth": depth, "next_index": 0, "totals": {}}
    if resume and state_path.exists():
        state = json.loads(state_path.read_text())
        if state.get("schema") != SCHEMA or state.get("candidate") != candidate_id or state.get("depth") != depth:
            raise ValueError(f"{candidate_id}: state does not match this run")
    if resume:
        start, totals = recover_records(records_path)
        # Records are written before the checkpoint.  Rebuild a stale/missing
        # state from those records, including the entry that survived a failed
        # Windows rename.
        state = {"schema": SCHEMA, "candidate": candidate_id, "depth": depth, "next_index": start, "totals": totals}
        atomic_json(state_path, state)
    else:
        start = 0
        totals: dict[str, int] = {}
    with records_path.open("a") as records:
        for index in range(start, len(fens)):
            result = run_one(engine, weights, fens[index], depth)
            records.write(json.dumps({"index": index, **result}) + "\n")
            records.flush()
            # The checkpoint must never claim a record that is still only in a
            # buffered user-space write.
            os.fsync(records.fileno())
            for key, value in result.items():
                if key != "bestmove":
                    totals[key] = totals.get(key, 0) + int(value)
            state = {"schema": SCHEMA, "candidate": candidate_id, "depth": depth, "next_index": index + 1, "totals": totals}
            atomic_json(state_path, state)
            if index == start or (index + 1) % 100 == 0 or index + 1 == len(fens):
                print(f"{candidate_id}: {index + 1}/{len(fens)} nodes={totals.get('nodes', 0)}", flush=True)
    summary = {**state, "complete": True, "positions": len(fens), "engine_sha256": sha256(engine), "weights_sha256": sha256(weights)}
    atomic_json(directory / "summary.json", summary)
    return summary


def run_candidate_matrix(
    candidates: list[dict[str, str]],
    root: Path,
    fens: list[str],
    depth: int,
    resume: bool,
    workers: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    summaries: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_candidates = {
            pool.submit(run_candidate, candidate, root, fens, depth, resume): candidate
            for candidate in candidates
        }
        for future in concurrent.futures.as_completed(future_candidates):
            candidate = future_candidates[future]
            candidate_id = candidate["id"]
            try:
                summaries[candidate_id] = future.result()
                print(f"{candidate_id}: complete", flush=True)
            except Exception as error:
                failures[candidate_id] = f"{type(error).__name__}: {error}"
                print(f"{candidate_id}: failed: {failures[candidate_id]}", file=sys.stderr, flush=True)

    ordered_summaries = [summaries[candidate["id"]] for candidate in candidates if candidate["id"] in summaries]
    ordered_failures = [
        {"candidate": candidate["id"], "error": failures[candidate["id"]]}
        for candidate in candidates
        if candidate["id"] in failures
    ]
    return ordered_summaries, ordered_failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--depth", required=True, type=int)
    parser.add_argument("--workers", required=True, type=int, choices=(2, 3, 4))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if args.depth < 1:
        parser.error("--depth must be positive")
    config_path = Path(args.config).resolve()
    root = config_path.parent.parent
    config = json.loads(config_path.read_text())
    if config.get("schema") != SCHEMA:
        raise ValueError("unsupported config schema")
    fens = load_fens(root / config["fen_file"])
    candidates = configured_candidates(config)
    validate_candidate_artifacts(candidates, root)
    (root / "run").mkdir(parents=True, exist_ok=True)
    matrix, failures = run_candidate_matrix(candidates, root, fens, args.depth, args.resume, args.workers)
    atomic_json(
        root / "run" / "matrix-summary.json",
        {
            "schema": SCHEMA,
            "depth": args.depth,
            "workers": args.workers,
            "positions": len(fens),
            "complete": not failures,
            "candidates": matrix,
            "failures": failures,
        },
    )
    if failures:
        detail = "; ".join(f"{failure['candidate']}: {failure['error']}" for failure in failures)
        raise RuntimeError(f"candidate failures: {detail}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"fatal: {error}", file=sys.stderr)
        raise SystemExit(1)
