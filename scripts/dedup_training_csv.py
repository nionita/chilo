#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path


EXPECTED_HEADER = "eval_fen,score,result"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deduplicate collector CSV rows exactly using external sort."
    )
    parser.add_argument(
        "--input",
        nargs="+",
        required=True,
        help="One or more CSV files with eval_fen,score,result columns.",
    )
    parser.add_argument("--output", required=True, help="Output CSV path.")
    parser.add_argument(
        "--sort-buffer-size",
        default="50%",
        help="Value passed to sort --buffer-size (default: 50%%).",
    )
    parser.add_argument(
        "--sort-temp-dir",
        default=None,
        help="Optional temporary directory passed to sort --temporary-directory.",
    )
    parser.add_argument(
        "--sort-parallel",
        type=int,
        default=0,
        help="Optional value passed to sort --parallel.",
    )
    parser.add_argument(
        "--report-every",
        type=int,
        default=1000000,
        help="Print a progress line every N streamed data rows.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing output file if it exists.",
    )
    return parser.parse_args()


def validate_header(line: str, path: Path) -> None:
    header = line.strip()
    if header != EXPECTED_HEADER:
        raise SystemExit(
            f"{path} has unsupported header {header!r}; expected {EXPECTED_HEADER!r}"
        )


def main() -> int:
    args = parse_args()
    if args.report_every <= 0:
        raise SystemExit("--report-every must be positive.")
    if args.sort_parallel < 0:
        raise SystemExit("--sort-parallel must be zero or positive.")

    input_paths = [Path(path) for path in args.input]
    output_path = Path(args.output)
    if output_path.exists() and not args.overwrite:
        raise SystemExit(f"{output_path} already exists; rerun with --overwrite to replace it.")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temp_parent = Path(args.sort_temp_dir) if args.sort_temp_dir else output_path.parent
    temp_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=temp_parent,
        prefix="chilo-dedup-body-",
        suffix=".csv",
        delete=False,
    ) as sorted_body_handle:
        sorted_body_path = Path(sorted_body_handle.name)

    sort_command = [
        "sort",
        "--unique",
        "--buffer-size",
        args.sort_buffer_size,
        "--output",
        str(sorted_body_path),
    ]
    if args.sort_temp_dir:
        sort_command.extend(["--temporary-directory", args.sort_temp_dir])
    if args.sort_parallel > 0:
        sort_command.extend(["--parallel", str(args.sort_parallel)])

    env = os.environ.copy()
    env["LC_ALL"] = "C"

    total_rows = 0
    sort_process = subprocess.Popen(
        sort_command,
        stdin=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )

    try:
        assert sort_process.stdin is not None
        for input_path in input_paths:
            with input_path.open("r", encoding="utf-8", newline="") as handle:
                header = handle.readline()
                if not header:
                    raise SystemExit(f"{input_path} is empty.")
                validate_header(header, input_path)

                for line in handle:
                    if not line.strip():
                        continue
                    sort_process.stdin.write(line)
                    total_rows += 1
                    if total_rows % args.report_every == 0:
                        print(f"streamed {total_rows} row(s) into sort")

        sort_process.stdin.close()
        return_code = sort_process.wait()
        if return_code != 0:
            raise SystemExit(f"sort failed with exit code {return_code}")

        unique_rows = 0
        with output_path.open("w", encoding="utf-8", newline="") as output_handle:
            output_handle.write(f"{EXPECTED_HEADER}\n")
            with sorted_body_path.open("r", encoding="utf-8", newline="") as body_handle:
                for line in body_handle:
                    output_handle.write(line)
                    unique_rows += 1

        print(
            f"Wrote {unique_rows} unique row(s) to {output_path} from {total_rows} streamed row(s)"
        )
        return 0
    finally:
        if sort_process.stdin is not None and not sort_process.stdin.closed:
            sort_process.stdin.close()
        if sort_process.poll() is None:
            sort_process.terminate()
            sort_process.wait()
        if sorted_body_path.exists():
            sorted_body_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
