#!/usr/bin/env python3

import argparse
import json
import random
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_POSITIONS = [
    ("startpos", "position startpos"),
    ("middlegame", "position fen r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"),
    ("tactical", "position fen rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"),
]

INFO_RE = re.compile(r"^info depth (\d+) score .* nodes (\d+) time (\d+) nps (\d+)(.*)$")
BESTMOVE_RE = re.compile(r"^bestmove\s+(\S+)")
EXTRA_INFO_RE = re.compile(
    r"\b(qnodes|qcheck|qnormal|qgen|qsee_skip|qdelta_skip|qsearched|qstandpat_cut|"
    r"qcut1|qcut2|qcut3|qcut4p|cut1|cut2|cut3|cut4p|cut_tt|cut_cap|cut_killer|"
    r"cut_quiet|cut_promo|cut_other|null_try|null_cut|null_try_d2|null_cut_d2|"
    r"null_try_d3|null_cut_d3|null_try_d4p|null_cut_d4p)\s+(\d+)\b"
)
SEARCH_STAT_KEYS = (
    "qnodes",
    "qcheck",
    "qnormal",
    "qgen",
    "qsee_skip",
    "qdelta_skip",
    "qsearched",
    "qstandpat_cut",
    "qcut1",
    "qcut2",
    "qcut3",
    "qcut4p",
    "cut1",
    "cut2",
    "cut3",
    "cut4p",
    "cut_tt",
    "cut_cap",
    "cut_killer",
    "cut_quiet",
    "cut_promo",
    "cut_other",
    "null_try",
    "null_cut",
    "null_try_d2",
    "null_cut_d2",
    "null_try_d3",
    "null_cut_d3",
    "null_try_d4p",
    "null_cut_d4p",
)


def parse_position(value):
    if "::" not in value:
        raise argparse.ArgumentTypeError("position must have the form 'name::uci position command'")
    name, command = value.split("::", 1)
    name = name.strip()
    command = command.strip()
    if not name or not command:
        raise argparse.ArgumentTypeError("position name and command must both be non-empty")
    return name, command


def parse_probability(value):
    try:
        probability = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("probability must be a number") from exc
    if probability < 0.0 or probability > 1.0:
        raise argparse.ArgumentTypeError("probability must be between 0 and 1")
    return probability


def strip_inline_comment(line):
    return line.split("#", 1)[0].strip()


def fen_position_name(line_number):
    return f"fen_{line_number:06d}"


def load_fen_positions(path, offset, max_positions, sample_rate, seed):
    rng = random.Random(seed)
    positions = []
    valid_rows = 0
    source = Path(path)
    with source.open() as handle:
        for line_number, line in enumerate(handle, start=1):
            fen = strip_inline_comment(line)
            if not fen:
                continue
            valid_rows += 1
            if valid_rows <= offset:
                continue
            if sample_rate < 1.0 and rng.random() > sample_rate:
                continue
            if len(fen.split()) < 6:
                raise ValueError(f"{source}:{line_number}: expected a full FEN with at least 6 fields")
            positions.append(
                {
                    "name": fen_position_name(line_number),
                    "cmd": f"position fen {fen}",
                    "fen": fen,
                    "source": str(source),
                    "line_number": line_number,
                }
            )
            if max_positions and len(positions) >= max_positions:
                break
    if not positions:
        raise ValueError(f"no FEN positions selected from {source}")
    return positions


def build_engine_argv(binary, weights):
    argv = [str(binary)]
    if weights:
        argv.extend(["--weights", str(weights)])
    return argv


def run_once(engine_argv, position_cmd, depth):
    search_cmd = f"uci\n{position_cmd}\ngo depth {depth}\n"
    start = time.perf_counter()
    proc = subprocess.Popen(
        engine_argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines = []
    last_info = None
    bestmove = None
    try:
        proc.stdin.write(search_cmd)
        proc.stdin.flush()

        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            stdout_lines.append(line)
            match = INFO_RE.match(line)
            if match and int(match.group(1)) == depth:
                extra_info = {key: int(value) for key, value in EXTRA_INFO_RE.findall(match.group(5))}
                last_info = {
                    "nodes": int(match.group(2)),
                    "engine_ms": int(match.group(3)),
                    "nps": int(match.group(4)),
                    "line": line,
                }
                for key in SEARCH_STAT_KEYS:
                    if key in extra_info:
                        last_info[key] = extra_info[key]
            bestmove_match = BESTMOVE_RE.match(line)
            if bestmove_match:
                bestmove = bestmove_match.group(1)
                break

        wall_ms = (time.perf_counter() - start) * 1000.0
        if proc.stdin is not None:
            try:
                proc.stdin.write("quit\n")
                proc.stdin.flush()
            except BrokenPipeError:
                pass
        try:
            remaining_stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            remaining_stdout, stderr = proc.communicate()
            raise RuntimeError(f"engine did not exit after bestmove: {' '.join(engine_argv)}")
        stdout_lines.extend(remaining_stdout.splitlines())
    except Exception:
        proc.kill()
        proc.communicate()
        raise

    stdout_text = "\n".join(stdout_lines)
    if proc.returncode != 0:
        raise RuntimeError(
            f"engine command failed with exit code {proc.returncode}: {' '.join(engine_argv)}\n"
            f"STDOUT:\n{stdout_text}\nSTDERR:\n{stderr}"
        )

    if last_info is None:
        raise RuntimeError(
            f"no depth {depth} info line for {' '.join(engine_argv)} / {position_cmd}\n"
            f"STDOUT:\n{stdout_text}\nSTDERR:\n{stderr}"
        )

    last_info["wall_ms"] = wall_ms
    last_info["bestmove"] = bestmove
    return last_info


def summarize_variant(runs):
    median_engine_ms = statistics.median(run["engine_ms"] for run in runs)
    median_wall_ms = statistics.median(run["wall_ms"] for run in runs)
    median_nodes = statistics.median(run["nodes"] for run in runs)
    summary = {
        "runs": runs,
        "median_engine_ms": median_engine_ms,
        "median_wall_ms": round(median_wall_ms, 3),
        "median_nps": statistics.median(run["nps"] for run in runs),
        "nodes": median_nodes,
    }
    for key in SEARCH_STAT_KEYS:
        values = [run[key] for run in runs if key in run]
        if len(values) == len(runs):
            summary[key] = statistics.median(values)
    return summary


def pct_delta(candidate, baseline):
    if baseline == 0:
        return None
    return round((candidate - baseline) * 100.0 / baseline, 2)


def summarize_totals(positions):
    totals = {"baseline": {}, "candidate": {}}
    for variant_name in ("baseline", "candidate"):
        variant_summaries = [position["variants"][variant_name] for position in positions]
        total_nodes = sum(variant["nodes"] for variant in variant_summaries)
        total_engine_ms = sum(variant["median_engine_ms"] for variant in variant_summaries)
        total_wall_ms = sum(variant["median_wall_ms"] for variant in variant_summaries)
        totals[variant_name] = {
            "total_nodes": total_nodes,
            "total_engine_ms": total_engine_ms,
            "total_wall_ms": round(total_wall_ms, 3),
            "median_engine_ms_per_position": statistics.median(
                variant["median_engine_ms"] for variant in variant_summaries
            ),
            "weighted_nps": int(total_nodes * 1000 / total_engine_ms) if total_engine_ms > 0 else 0,
        }
        for key in SEARCH_STAT_KEYS:
            if all(key in variant for variant in variant_summaries):
                totals[variant_name][f"total_{key}"] = sum(variant[key] for variant in variant_summaries)

    base = totals["baseline"]
    cand = totals["candidate"]
    totals["delta"] = {
        "total_nodes_pct": pct_delta(cand["total_nodes"], base["total_nodes"]),
        "total_engine_ms_pct": pct_delta(cand["total_engine_ms"], base["total_engine_ms"]),
        "total_wall_ms_pct": pct_delta(cand["total_wall_ms"], base["total_wall_ms"]),
        "weighted_nps_pct": pct_delta(cand["weighted_nps"], base["weighted_nps"]),
    }
    for key in SEARCH_STAT_KEYS:
        total_key = f"total_{key}"
        if total_key in base and total_key in cand:
            totals["delta"][f"{key}_pct"] = pct_delta(cand[total_key], base[total_key])
    return totals


def format_search_stats(values):
    if "qnodes" not in values:
        return ""
    cut_values = [values.get(key, 0) for key in ("cut1", "cut2", "cut3", "cut4p")]
    cut_total = sum(cut_values)
    cut1_pct = round(cut_values[0] * 100.0 / cut_total, 2) if cut_total else 0.0
    qnode_pct = round(values["qnodes"] * 100.0 / values["nodes"], 2) if values["nodes"] else 0.0
    parts = [
        f" qnodes={format_number(values['qnodes'])} qnodes_pct={qnode_pct}% "
        f"cuts={format_number(cut_total)} cut1={format_number(cut_values[0])} "
        f"cut2={format_number(cut_values[1])} cut3={format_number(cut_values[2])} "
        f"cut4p={format_number(cut_values[3])} cut1_pct={cut1_pct}%"
    ]
    if "qcheck" in values:
        qcheck_pct = round(values["qcheck"] * 100.0 / values["qnodes"], 2) if values["qnodes"] else 0.0
        qsearched_pct = round(values.get("qsearched", 0) * 100.0 / values["qgen"], 2) if values.get("qgen", 0) else 0.0
        qcut_values = [values.get(key, 0) for key in ("qcut1", "qcut2", "qcut3", "qcut4p")]
        qcut_total = sum(qcut_values)
        qcut1_pct = round(qcut_values[0] * 100.0 / qcut_total, 2) if qcut_total else 0.0
        parts.append(
            f" qcheck={format_number(values['qcheck'])} qcheck_pct={qcheck_pct}% "
            f"qnormal={format_number(values.get('qnormal', 0))} qgen={format_number(values.get('qgen', 0))} "
            f"qsearched={format_number(values.get('qsearched', 0))} qsearched_pct={qsearched_pct}% "
            f"qsee_skip={format_number(values.get('qsee_skip', 0))} "
            f"qdelta_skip={format_number(values.get('qdelta_skip', 0))} "
            f"qstandpat_cut={format_number(values.get('qstandpat_cut', 0))} "
            f"qcuts={format_number(qcut_total)} qcut1={format_number(qcut_values[0])} "
            f"qcut2={format_number(qcut_values[1])} qcut3={format_number(qcut_values[2])} "
            f"qcut4p={format_number(qcut_values[3])} qcut1_pct={qcut1_pct}%"
        )
    if "cut_tt" in values:
        parts.append(
            f" cut_tt={format_number(values.get('cut_tt', 0))} "
            f"cut_cap={format_number(values.get('cut_cap', 0))} "
            f"cut_killer={format_number(values.get('cut_killer', 0))} "
            f"cut_quiet={format_number(values.get('cut_quiet', 0))} "
            f"cut_promo={format_number(values.get('cut_promo', 0))} "
            f"cut_other={format_number(values.get('cut_other', 0))}"
        )
    if "null_try" in values:
        null_cut_pct = round(values.get("null_cut", 0) * 100.0 / values["null_try"], 2) if values["null_try"] else 0.0
        null_cut_d2_pct = (
            round(values.get("null_cut_d2", 0) * 100.0 / values["null_try_d2"], 2)
            if values.get("null_try_d2", 0)
            else 0.0
        )
        null_cut_d3_pct = (
            round(values.get("null_cut_d3", 0) * 100.0 / values["null_try_d3"], 2)
            if values.get("null_try_d3", 0)
            else 0.0
        )
        null_cut_d4p_pct = (
            round(values.get("null_cut_d4p", 0) * 100.0 / values["null_try_d4p"], 2)
            if values.get("null_try_d4p", 0)
            else 0.0
        )
        parts.append(
            f" null_try={format_number(values['null_try'])} "
            f"null_cut={format_number(values.get('null_cut', 0))} "
            f"null_cut_pct={null_cut_pct}% "
            f"null_try_d2={format_number(values.get('null_try_d2', 0))} "
            f"null_cut_d2={format_number(values.get('null_cut_d2', 0))} "
            f"null_cut_d2_pct={null_cut_d2_pct}% "
            f"null_try_d3={format_number(values.get('null_try_d3', 0))} "
            f"null_cut_d3={format_number(values.get('null_cut_d3', 0))} "
            f"null_cut_d3_pct={null_cut_d3_pct}% "
            f"null_try_d4p={format_number(values.get('null_try_d4p', 0))} "
            f"null_cut_d4p={format_number(values.get('null_cut_d4p', 0))} "
            f"null_cut_d4p_pct={null_cut_d4p_pct}%"
        )
    return "".join(parts)


def format_number(value):
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def progress_interval(position_count):
    if position_count <= 0:
        return 1
    return max(1, position_count // 50)


def main():
    parser = argparse.ArgumentParser(description="Compare two UCI binaries at a fixed search depth.")
    parser.add_argument("--baseline", required=True, help="Path to the baseline UCI binary")
    parser.add_argument("--candidate", required=True, help="Path to the candidate UCI binary")
    parser.add_argument("--depth", type=int, default=6, help="Fixed search depth")
    parser.add_argument("--runs", type=int, default=5, help="Measured runs per position and binary")
    parser.add_argument("--warmups", type=int, default=1, help="Warm-up runs per position and binary")
    parser.add_argument("--fen-file", help="Optional file with one FEN per non-empty line")
    parser.add_argument("--max-positions", type=int, default=0, help="Maximum selected FEN positions; 0 means unlimited")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many valid FEN rows before selecting")
    parser.add_argument("--sample-rate", type=parse_probability, default=1.0, help="Randomly keep FEN rows with probability P")
    parser.add_argument("--seed", type=int, default=1, help="Random seed for --sample-rate")
    parser.add_argument("--weights", help="NNUE weights file to pass to both engines")
    parser.add_argument("--baseline-weights", help="NNUE weights file to pass only to the baseline engine")
    parser.add_argument("--candidate-weights", help="NNUE weights file to pass only to the candidate engine")
    parser.add_argument(
        "--position",
        action="append",
        default=[],
        type=parse_position,
        help="Benchmark position as 'name::uci position command'; can be repeated",
    )
    parser.add_argument("--output-dir", help="Optional directory for JSON and text summaries")
    parser.add_argument("--no-progress", action="store_true", help="Do not print progress updates to stderr")
    args = parser.parse_args()
    if args.depth <= 0:
        parser.error("--depth must be positive")
    if args.runs <= 0:
        parser.error("--runs must be positive")
    if args.warmups < 0:
        parser.error("--warmups must be non-negative")
    if args.max_positions < 0:
        parser.error("--max-positions must be non-negative")
    if args.offset < 0:
        parser.error("--offset must be non-negative")

    baseline = Path(args.baseline)
    candidate = Path(args.candidate)
    baseline_weights = args.baseline_weights or args.weights
    candidate_weights = args.candidate_weights or args.weights

    positions = []
    if args.fen_file:
        positions.extend(
            load_fen_positions(args.fen_file, args.offset, args.max_positions, args.sample_rate, args.seed)
        )
    if args.position:
        positions.extend({"name": name, "cmd": cmd} for name, cmd in args.position)
    if not positions:
        positions = [{"name": name, "cmd": cmd} for name, cmd in DEFAULT_POSITIONS]

    results = {
        "depth": args.depth,
        "runs": args.runs,
        "warmups": args.warmups,
        "fen_file": args.fen_file,
        "max_positions": args.max_positions,
        "offset": args.offset,
        "sample_rate": args.sample_rate,
        "seed": args.seed,
        "baseline": str(baseline),
        "candidate": str(candidate),
        "baseline_weights": str(baseline_weights) if baseline_weights else None,
        "candidate_weights": str(candidate_weights) if candidate_weights else None,
        "positions": [],
    }

    engine_argvs = {
        "baseline": build_engine_argv(baseline, baseline_weights),
        "candidate": build_engine_argv(candidate, candidate_weights),
    }

    total_positions = len(positions)
    report_every = progress_interval(total_positions)
    progress_start = time.perf_counter()
    if not args.no_progress:
        runs_per_position = 2 * (args.warmups + args.runs)
        print(
            f"progress: 0/{total_positions} positions complete, "
            f"{runs_per_position} engine runs per position",
            file=sys.stderr,
            flush=True,
        )

    for position_index, position in enumerate(positions, start=1):
        position_result = {**position, "variants": {}}

        for variant_name in ("baseline", "candidate"):
            for _ in range(args.warmups):
                run_once(engine_argvs[variant_name], position["cmd"], args.depth)
            measured_runs = [
                run_once(engine_argvs[variant_name], position["cmd"], args.depth)
                for _ in range(args.runs)
            ]
            position_result["variants"][variant_name] = summarize_variant(measured_runs)

        base = position_result["variants"]["baseline"]
        cand = position_result["variants"]["candidate"]
        position_result["delta"] = {
            "nodes_pct": pct_delta(cand["nodes"], base["nodes"]),
            "engine_ms_pct": pct_delta(cand["median_engine_ms"], base["median_engine_ms"]),
            "wall_ms_pct": pct_delta(cand["median_wall_ms"], base["median_wall_ms"]),
            "nps_pct": pct_delta(cand["median_nps"], base["median_nps"]),
        }
        results["positions"].append(position_result)

        if not args.no_progress and (
            position_index == 1 or position_index == total_positions or position_index % report_every == 0
        ):
            elapsed = time.perf_counter() - progress_start
            remaining = total_positions - position_index
            eta = (elapsed / position_index) * remaining if position_index > 0 else 0
            print(
                f"progress: {position_index}/{total_positions} positions complete "
                f"({remaining} left), elapsed {format_duration(elapsed)}, "
                f"eta {format_duration(eta)}, last={position['name']}",
                file=sys.stderr,
                flush=True,
            )

    results["aggregate"] = summarize_totals(results["positions"])

    lines = []
    lines.append(
        f"Fixed-depth search benchmark: depth {args.depth}, {args.runs} measured runs after {args.warmups} warm-up run(s)"
    )
    lines.append(f"Positions: {len(results['positions'])}")
    if args.fen_file:
        lines.append(
            f"FEN file: {args.fen_file} offset={args.offset} max_positions={args.max_positions} "
            f"sample_rate={args.sample_rate} seed={args.seed}"
        )
    if baseline_weights or candidate_weights:
        lines.append(f"weights: baseline={baseline_weights or '(sidecar/builtin)'} candidate={candidate_weights or '(sidecar/builtin)'}")
    lines.append("")
    for position in results["positions"]:
        lines.append(f"[{position['name']}]")
        for variant_name in ("baseline", "candidate"):
            variant = position["variants"][variant_name]
            lines.append(
                f"  {variant_name}: nodes={format_number(variant['nodes'])} "
                f"median_engine_ms={format_number(variant['median_engine_ms'])} "
                f"median_wall_ms={variant['median_wall_ms']:.3f} median_nps={format_number(variant['median_nps'])} "
                f"bestmove={variant['runs'][0]['bestmove']}"
                f"{format_search_stats(variant)}"
            )
        delta = position["delta"]
        lines.append(
            f"  delta candidate-vs-baseline: nodes={delta['nodes_pct']}% engine_ms={delta['engine_ms_pct']}% "
            f"wall_ms={delta['wall_ms_pct']}% nps={delta['nps_pct']}%"
        )
        lines.append("")

    aggregate = results["aggregate"]
    lines.append("[aggregate]")
    for variant_name in ("baseline", "candidate"):
        variant = aggregate[variant_name]
        lines.append(
            f"  {variant_name}: total_nodes={format_number(variant['total_nodes'])} "
            f"total_engine_ms={format_number(variant['total_engine_ms'])} "
            f"median_engine_ms_per_position={format_number(variant['median_engine_ms_per_position'])} "
            f"weighted_nps={variant['weighted_nps']}"
            f"{format_search_stats({'nodes': variant['total_nodes'], **{key: variant[f'total_{key}'] for key in SEARCH_STAT_KEYS if f'total_{key}' in variant}})}"
        )
    delta = aggregate["delta"]
    lines.append(
        f"  delta candidate-vs-baseline: total_nodes={delta['total_nodes_pct']}% "
        f"total_engine_ms={delta['total_engine_ms_pct']}% weighted_nps={delta['weighted_nps_pct']}%"
    )

    summary = "\n".join(lines)
    print(summary)

    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "benchmark_fixed_depth.json").write_text(json.dumps(results, indent=2))
        (output_dir / "benchmark_fixed_depth.txt").write_text(summary)


if __name__ == "__main__":
    main()
