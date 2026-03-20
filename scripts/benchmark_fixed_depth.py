#!/usr/bin/env python3

import argparse
import json
import re
import statistics
import subprocess
import time
from pathlib import Path

DEFAULT_POSITIONS = [
    ("startpos", "position startpos"),
    ("middlegame", "position fen r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"),
    ("tactical", "position fen rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"),
]

INFO_RE = re.compile(r"^info depth (\d+) score .* nodes (\d+) time (\d+) nps (\d+)")


def parse_position(value):
    if "::" not in value:
        raise argparse.ArgumentTypeError("position must have the form 'name::uci position command'")
    name, command = value.split("::", 1)
    name = name.strip()
    command = command.strip()
    if not name or not command:
        raise argparse.ArgumentTypeError("position name and command must both be non-empty")
    return name, command


def run_once(binary, position_cmd, depth):
    cmd = f"uci\n{position_cmd}\ngo depth {depth}\nquit\n"
    start = time.perf_counter()
    proc = subprocess.run([str(binary)], input=cmd, text=True, capture_output=True, check=True)
    wall_ms = (time.perf_counter() - start) * 1000.0

    last_info = None
    for line in proc.stdout.splitlines():
        match = INFO_RE.match(line)
        if match and int(match.group(1)) == depth:
            last_info = {
                "nodes": int(match.group(2)),
                "engine_ms": int(match.group(3)),
                "nps": int(match.group(4)),
                "line": line,
            }

    if last_info is None:
        raise RuntimeError(
            f"no depth {depth} info line for {binary} / {position_cmd}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    last_info["wall_ms"] = wall_ms
    return last_info


def summarize_variant(runs):
    return {
        "runs": runs,
        "median_engine_ms": statistics.median(run["engine_ms"] for run in runs),
        "median_wall_ms": round(statistics.median(run["wall_ms"] for run in runs), 3),
        "median_nps": statistics.median(run["nps"] for run in runs),
        "nodes": runs[0]["nodes"],
    }


def main():
    parser = argparse.ArgumentParser(description="Compare two UCI binaries at a fixed search depth.")
    parser.add_argument("--baseline", required=True, help="Path to the baseline UCI binary")
    parser.add_argument("--candidate", required=True, help="Path to the candidate UCI binary")
    parser.add_argument("--depth", type=int, default=6, help="Fixed search depth")
    parser.add_argument("--runs", type=int, default=5, help="Measured runs per position and binary")
    parser.add_argument("--warmups", type=int, default=1, help="Warm-up runs per position and binary")
    parser.add_argument(
        "--position",
        action="append",
        default=[],
        type=parse_position,
        help="Benchmark position as 'name::uci position command'; can be repeated",
    )
    parser.add_argument("--output-dir", help="Optional directory for JSON and text summaries")
    args = parser.parse_args()

    baseline = Path(args.baseline)
    candidate = Path(args.candidate)
    positions = args.position if args.position else DEFAULT_POSITIONS

    results = {
        "depth": args.depth,
        "runs": args.runs,
        "warmups": args.warmups,
        "positions": [],
    }

    for position_name, position_cmd in positions:
        position_result = {"name": position_name, "cmd": position_cmd, "variants": {}}

        for variant_name, binary in (("baseline", baseline), ("candidate", candidate)):
            for _ in range(args.warmups):
                run_once(binary, position_cmd, args.depth)
            measured_runs = [run_once(binary, position_cmd, args.depth) for _ in range(args.runs)]
            position_result["variants"][variant_name] = summarize_variant(measured_runs)

        base = position_result["variants"]["baseline"]
        cand = position_result["variants"]["candidate"]
        position_result["delta"] = {
            "engine_ms_pct": round((cand["median_engine_ms"] - base["median_engine_ms"]) * 100.0 / base["median_engine_ms"], 2),
            "wall_ms_pct": round((cand["median_wall_ms"] - base["median_wall_ms"]) * 100.0 / base["median_wall_ms"], 2),
            "nps_pct": round((cand["median_nps"] - base["median_nps"]) * 100.0 / base["median_nps"], 2),
        }
        results["positions"].append(position_result)

    lines = []
    lines.append(
        f"Fixed-depth search benchmark: depth {args.depth}, {args.runs} measured runs after {args.warmups} warm-up run(s)"
    )
    lines.append("")
    for position in results["positions"]:
        lines.append(f"[{position['name']}]")
        for variant_name in ("baseline", "candidate"):
            variant = position["variants"][variant_name]
            lines.append(
                f"  {variant_name}: nodes={variant['nodes']} median_engine_ms={variant['median_engine_ms']} "
                f"median_wall_ms={variant['median_wall_ms']:.3f} median_nps={variant['median_nps']}"
            )
        delta = position["delta"]
        lines.append(
            f"  delta candidate-vs-baseline: engine_ms={delta['engine_ms_pct']}% "
            f"wall_ms={delta['wall_ms_pct']}% nps={delta['nps_pct']}%"
        )
        lines.append("")

    summary = "\n".join(lines)
    print(summary)

    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "benchmark_fixed_depth.json").write_text(json.dumps(results, indent=2))
        (output_dir / "benchmark_fixed_depth.txt").write_text(summary)


if __name__ == "__main__":
    main()
