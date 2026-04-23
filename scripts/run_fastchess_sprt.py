#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


STATE_FILE_NAME = "fastchess_state.json"
PGN_FILE_NAME = "games.pgn"
LOG_FILE_NAME = "fastchess.log"
COMMAND_FILE_NAME = "fastchess_command.json"
NORMALIZED_OPENINGS_FILE_NAME = "openings.epd"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a two-engine fastchess SPRT match.")
    parser.add_argument("--config", required=True, help="JSON wrapper configuration file.")
    parser.add_argument("--run-dir", default=None, help="Dedicated output directory for this SPRT run.")
    parser.add_argument("--run-name", default=None, help="Run directory name under config work_root when --run-dir is omitted.")

    parser.add_argument("--engine-a", required=True, help="Path to the first UCI engine.")
    parser.add_argument("--engine-b", required=True, help="Path to the second UCI engine.")
    parser.add_argument("--name-a", default="engine-a", help="Unique fastchess name for engine A.")
    parser.add_argument("--name-b", default="engine-b", help="Unique fastchess name for engine B.")
    parser.add_argument("--net-a", default=None, help="Optional Chilo NNUE .bin passed to engine A as --weights.")
    parser.add_argument("--net-b", default=None, help="Optional Chilo NNUE .bin passed to engine B as --weights.")

    parser.add_argument("--sprt", default=None, help="SPRT profile name from config sprt_profiles.")
    parser.add_argument("--elo0", type=float, default=None, help="Override SPRT elo0.")
    parser.add_argument("--elo1", type=float, default=None, help="Override SPRT elo1.")
    parser.add_argument("--alpha", type=float, default=None, help="Override SPRT alpha.")
    parser.add_argument("--beta", type=float, default=None, help="Override SPRT beta.")
    parser.add_argument(
        "--sprt-model",
        choices=("normalized", "logistic", "bayesian"),
        default=None,
        help="Override SPRT model.",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--new", action="store_true", help="Start a new run; fail if the state file exists.")
    mode.add_argument("--force-new", action="store_true", help="Archive old run files and start a new run.")
    mode.add_argument("--resume", action="store_true", help="Resume; fail if the state file is missing.")
    parser.add_argument("--dry-run", action="store_true", help="Print the fastchess command without running it.")
    return parser.parse_args(argv)


def load_config(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise SystemExit("Config root must be a JSON object.")
    if "fastchess" not in config:
        raise SystemExit("Config must define 'fastchess'.")
    if "sprt_profiles" not in config or not isinstance(config["sprt_profiles"], dict):
        raise SystemExit("Config must define a 'sprt_profiles' object.")
    return config


def resolve_cli_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def resolve_config_path(value: str, config_dir: Path) -> str:
    expanded = Path(os.path.expanduser(value))
    if expanded.is_absolute():
        return str(expanded)
    if "/" in value or "\\" in value:
        return str((config_dir / expanded).resolve())
    return value


def resolve_config_file_path(value: str, config_dir: Path) -> str:
    expanded = Path(os.path.expanduser(value))
    if expanded.is_absolute():
        return str(expanded)
    return str((config_dir / expanded).resolve())


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def format_number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def mapping_items(mapping: Mapping[str, Any]) -> List[str]:
    items: List[str] = []
    for key, value in mapping.items():
        if value is None:
            continue
        items.append(f"{key}={format_value(value)}")
    return items


def normalize_fen_opening_line(line: str, source: Path, line_number: int) -> Optional[str]:
    stripped = line.strip()
    if not stripped:
        return None
    parts = stripped.split()
    if len(parts) not in (4, 6):
        raise SystemExit(f"{source}:{line_number}: expected 4-field or 6-field FEN, got {len(parts)} fields.")

    board, side_to_move, castling, ep_square = parts[:4]
    if side_to_move not in ("w", "b"):
        raise SystemExit(f"{source}:{line_number}: invalid side-to-move field '{side_to_move}'.")

    halfmove = 0
    fullmove = 1
    if len(parts) == 6:
        try:
            halfmove = int(parts[4])
            fullmove = int(parts[5])
        except ValueError as exc:
            raise SystemExit(f"{source}:{line_number}: halfmove/fullmove fields must be integers.") from exc

    halfmove = max(0, halfmove)
    fullmove = max(1, fullmove)
    return f"{board} {side_to_move} {castling} {ep_square} hmvc {halfmove}; fmvn {fullmove};"


def write_normalized_fen_book(source: Path, output: Path) -> int:
    written = 0
    with source.open("r", encoding="utf-8") as input_handle, output.open("w", encoding="utf-8", newline="\n") as output_handle:
        for line_number, line in enumerate(input_handle, start=1):
            normalized = normalize_fen_opening_line(line, source, line_number)
            if normalized is None:
                continue
            output_handle.write(normalized + "\n")
            written += 1
    if written == 0:
        raise SystemExit(f"No FEN openings found in {source}.")
    return written


def effective_opening_config(config: Mapping[str, Any], config_path: Path, run_dir: Path, materialize: bool) -> Tuple[Any, Optional[Dict[str, Any]]]:
    opening = config.get("opening")
    if opening is None:
        return None, None
    if not isinstance(opening, dict):
        raise SystemExit("Config 'opening' must be an object when present.")

    opening_format = opening.get("format")
    if opening_format != "fen":
        return opening, None
    if "file" not in opening:
        raise SystemExit("Config opening with format=fen must define 'file'.")

    source = Path(resolve_config_file_path(str(opening["file"]), config_path.parent))
    output = run_dir / NORMALIZED_OPENINGS_FILE_NAME
    generated = dict(opening)
    generated["file"] = str(output)
    generated["format"] = "epd"

    summary = {
        "source": str(source),
        "generated": str(output),
        "format": "fen-to-epd",
        "note": "FEN fullmove counters below 1 are written as fmvn 1 because FEN fullmove 0 is invalid.",
    }
    if materialize:
        output.parent.mkdir(parents=True, exist_ok=True)
        summary["positions"] = write_normalized_fen_book(source, output)
    return generated, summary


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-") or "run"


def timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def select_sprt_profile(config: Mapping[str, Any], profile_name: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    profiles = config["sprt_profiles"]
    if not isinstance(profiles, dict) or not profiles:
        raise SystemExit("Config sprt_profiles must contain at least one profile.")
    selected_name = profile_name
    if selected_name is None:
        selected_name = "normal" if "normal" in profiles else next(iter(profiles))
    if selected_name not in profiles:
        available = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown SPRT profile '{selected_name}'. Available profiles: {available}")
    profile = profiles[selected_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"SPRT profile '{selected_name}' must be an object.")
    result = dict(profile)
    for key in ("elo0", "elo1", "alpha", "beta"):
        if key not in result:
            raise SystemExit(f"SPRT profile '{selected_name}' is missing '{key}'.")
    result.setdefault("model", "normalized")
    return selected_name, result


def apply_sprt_overrides(profile: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    result = dict(profile)
    for attr, key in (("elo0", "elo0"), ("elo1", "elo1"), ("alpha", "alpha"), ("beta", "beta")):
        value = getattr(args, attr)
        if value is not None:
            result[key] = value
    if args.sprt_model is not None:
        result["model"] = args.sprt_model
    return result


def build_sprt_items(profile: Mapping[str, Any]) -> List[str]:
    return [
        f"elo0={format_number(profile['elo0'])}",
        f"elo1={format_number(profile['elo1'])}",
        f"alpha={format_number(profile['alpha'])}",
        f"beta={format_number(profile['beta'])}",
        f"model={profile.get('model', 'normalized')}",
    ]


def engine_options(command: Path, name: str, weights: Optional[Path]) -> List[str]:
    options = [f"cmd={command}", f"name={name}"]
    if weights is not None:
        options.append(f"args=--weights {weights}")
    return options


def resolve_run_dir(config: Mapping[str, Any], config_dir: Path, args: argparse.Namespace) -> Path:
    if args.run_dir:
        return resolve_cli_path(args.run_dir)

    work_root_value = str(config.get("work_root", "sprt-runs"))
    work_root = Path(resolve_config_file_path(work_root_value, config_dir)).expanduser()
    if args.run_name:
        run_name = safe_name(args.run_name)
    else:
        run_name = f"{safe_name(args.name_a)}-vs-{safe_name(args.name_b)}-{timestamp()}"
    return (work_root / run_name).resolve()


def choose_run_mode(args: argparse.Namespace, state_path: Path) -> str:
    if args.resume:
        if not state_path.exists():
            raise SystemExit(f"Cannot resume: state file does not exist: {state_path}")
        return "resume"
    if args.new:
        if state_path.exists():
            raise SystemExit(f"Cannot start new run: state file already exists: {state_path}")
        return "new"
    if args.force_new:
        return "new"
    return "resume" if state_path.exists() else "new"


def unique_backup_path(path: Path, suffix: str) -> Path:
    candidate = path.with_name(f"{path.name}.{suffix}.bak")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{suffix}.{counter}.bak")
        counter += 1
    return candidate


def archive_run_files(run_dir: Path) -> List[Tuple[str, str]]:
    suffix = timestamp()
    archived: List[Tuple[str, str]] = []
    for name in (STATE_FILE_NAME, PGN_FILE_NAME, LOG_FILE_NAME, COMMAND_FILE_NAME):
        path = run_dir / name
        if not path.exists():
            continue
        backup = unique_backup_path(path, suffix)
        path.rename(backup)
        archived.append((str(path), str(backup)))
    return archived


def append_opening_args(argv: List[str], opening: Any, config_dir: Path) -> None:
    if opening is None:
        return
    if not isinstance(opening, dict):
        raise SystemExit("Config 'opening' must be an object when present.")
    if "file" not in opening or "format" not in opening:
        raise SystemExit("Config 'opening' must define at least 'file' and 'format'.")
    items = []
    for key, value in opening.items():
        if key == "file":
            items.append(f"file={resolve_config_file_path(str(value), config_dir)}")
        else:
            items.append(f"{key}={format_value(value)}")
    argv.extend(["-openings", *items])


def append_adjudication_args(argv: List[str], adjudication: Any) -> None:
    if adjudication is None:
        return
    if not isinstance(adjudication, dict):
        raise SystemExit("Config 'adjudication' must be an object when present.")
    resign = adjudication.get("resign")
    if resign:
        argv.extend(["-resign", *str(resign).split()])
    draw = adjudication.get("draw")
    if draw:
        argv.extend(["-draw", *str(draw).split()])
    if adjudication.get("maxmoves") is not None:
        argv.extend(["-maxmoves", str(adjudication["maxmoves"])])


def append_pgn_args(argv: List[str], pgn: Any) -> None:
    if not pgn:
        return
    if not isinstance(pgn, dict):
        raise SystemExit("Config 'pgn' must be an object when present.")
    if not pgn.get("enabled", True):
        return
    items = [f"file={PGN_FILE_NAME}"]
    for key, value in pgn.items():
        if key in ("enabled", "file"):
            continue
        items.append(f"{key}={format_value(value)}")
    argv.extend(["-pgnout", *items])


def append_log_args(argv: List[str], log: Any) -> None:
    if not log:
        return
    if not isinstance(log, dict):
        raise SystemExit("Config 'log' must be an object when present.")
    if not log.get("enabled", True):
        return
    items = [f"file={LOG_FILE_NAME}"]
    for key, value in log.items():
        if key in ("enabled", "file"):
            continue
        items.append(f"{key}={format_value(value)}")
    argv.extend(["-log", *items])


def append_optional_scalar(argv: List[str], flag: str, config: Mapping[str, Any], key: str) -> None:
    value = config.get(key)
    if value is not None:
        argv.extend([flag, str(value)])


def build_fastchess_argv(
    config: Mapping[str, Any],
    config_path: Path,
    run_dir: Path,
    run_mode: str,
    sprt_profile: Mapping[str, Any],
    args: argparse.Namespace,
    opening_config: Any = None,
) -> List[str]:
    config_dir = config_path.parent
    fastchess = resolve_config_path(str(config["fastchess"]), config_dir)
    engine_a = resolve_cli_path(args.engine_a)
    engine_b = resolve_cli_path(args.engine_b)
    net_a = resolve_cli_path(args.net_a) if args.net_a else None
    net_b = resolve_cli_path(args.net_b) if args.net_b else None

    argv = [fastchess]
    argv.extend(["-engine", *engine_options(engine_a, args.name_a, net_a)])
    argv.extend(["-engine", *engine_options(engine_b, args.name_b, net_b)])

    each = config.get("each", {})
    if each:
        if not isinstance(each, dict):
            raise SystemExit("Config 'each' must be an object when present.")
        argv.extend(["-each", *mapping_items(each)])

    if opening_config is None:
        opening_config = config.get("opening")
    append_opening_args(argv, opening_config, config_dir)
    append_adjudication_args(argv, config.get("adjudication"))

    argv.extend(["-sprt", *build_sprt_items(sprt_profile)])
    append_optional_scalar(argv, "-rounds", config, "rounds")
    append_optional_scalar(argv, "-games", config, "games")
    append_optional_scalar(argv, "-concurrency", config, "concurrency")
    if config.get("force_concurrency"):
        argv.append("-force-concurrency")
    append_optional_scalar(argv, "-ratinginterval", config, "rating_interval")
    append_optional_scalar(argv, "-scoreinterval", config, "score_interval")
    append_optional_scalar(argv, "-event", config, "event")
    append_optional_scalar(argv, "-site", config, "site")
    if config.get("recover"):
        argv.append("-recover")

    output = config.get("output")
    if output:
        if isinstance(output, dict):
            argv.extend(["-output", *mapping_items(output)])
        else:
            raise SystemExit("Config 'output' must be an object when present.")

    report = config.get("report")
    if report:
        if isinstance(report, dict):
            argv.extend(["-report", *mapping_items(report)])
        else:
            raise SystemExit("Config 'report' must be an object when present.")

    append_pgn_args(argv, config.get("pgn"))
    append_log_args(argv, config.get("log"))

    extra_args = config.get("extra_args", [])
    if extra_args:
        if not isinstance(extra_args, list) or not all(isinstance(item, str) for item in extra_args):
            raise SystemExit("Config 'extra_args' must be a list of strings when present.")
        argv.extend(extra_args)

    if run_mode == "resume":
        argv.extend(["-config", f"file={STATE_FILE_NAME}", f"outname={STATE_FILE_NAME}", "stats=true"])
    else:
        argv.extend(["-config", f"outname={STATE_FILE_NAME}"])
    argv.extend(["-autosaveinterval", str(config.get("autosave_interval", 20))])

    return argv


def write_command_summary(
    path: Path,
    config_path: Path,
    run_dir: Path,
    run_mode: str,
    sprt_profile_name: str,
    sprt_profile: Mapping[str, Any],
    argv: Iterable[str],
    archived_files: List[Tuple[str, str]],
    opening_summary: Optional[Mapping[str, Any]],
    args: argparse.Namespace,
) -> None:
    summary = {
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "config": str(config_path),
        "run_dir": str(run_dir),
        "run_mode": run_mode,
        "sprt_profile": sprt_profile_name,
        "sprt": dict(sprt_profile),
        "engine_a": {
            "name": args.name_a,
            "command": str(resolve_cli_path(args.engine_a)),
            "weights": str(resolve_cli_path(args.net_a)) if args.net_a else None,
        },
        "engine_b": {
            "name": args.name_b,
            "command": str(resolve_cli_path(args.engine_b)),
            "weights": str(resolve_cli_path(args.net_b)) if args.net_b else None,
        },
        "archived_files": archived_files,
        "opening": dict(opening_summary) if opening_summary is not None else None,
        "fastchess_argv": list(argv),
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command_for_display(argv: Iterable[str]) -> str:
    return shlex.join(list(argv))


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    config_path = resolve_cli_path(args.config)
    config = load_config(config_path)
    run_dir = resolve_run_dir(config, config_path.parent, args)
    state_path = run_dir / STATE_FILE_NAME
    run_mode = choose_run_mode(args, state_path)
    sprt_profile_name, base_sprt_profile = select_sprt_profile(config, args.sprt)
    sprt_profile = apply_sprt_overrides(base_sprt_profile, args)
    opening_config, opening_summary = effective_opening_config(config, config_path, run_dir, materialize=not args.dry_run)

    fastchess_argv = build_fastchess_argv(config, config_path, run_dir, run_mode, sprt_profile, args, opening_config)

    if args.dry_run:
        print(command_for_display(fastchess_argv))
        return 0

    run_dir.mkdir(parents=True, exist_ok=True)
    archived_files: List[Tuple[str, str]] = []
    if args.force_new:
        archived_files = archive_run_files(run_dir)

    write_command_summary(
        run_dir / COMMAND_FILE_NAME,
        config_path,
        run_dir,
        run_mode,
        sprt_profile_name,
        sprt_profile,
        fastchess_argv,
        archived_files,
        opening_summary,
        args,
    )

    print(f"Run directory: {run_dir}")
    print(f"Mode: {run_mode}")
    print(f"Command: {command_for_display(fastchess_argv)}")
    subprocess.run(fastchess_argv, cwd=run_dir, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
