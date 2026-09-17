#!/usr/bin/env python3
"""Create a checksum-verified Linux bundle that installs legacy futility populations.

The bundle is deliberately data-only: it imports immutable anchor and mate-rescue
evidence into the common ``per-root-v1`` store without selecting a probe binary
for future candidate work.  That choice belongs to a later, explicit run config.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any


SCHEMA = "chilo.futility_population_sync.package.v1"
POPULATION_SCHEMA = "chilo.futility_population.v1"


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


def checked_file(path: Path, description: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"{description} is not a file: {resolved}")
    return resolved


def copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def load_combined_count(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        count = data["combined_position_count"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise SystemExit(f"invalid combined population sidecar: {path}") from error
    if not isinstance(count, int) or count < 1:
        raise SystemExit(f"combined population has invalid position count: {path}")
    return count


def population_files(source: Path, input_path: Path) -> list[tuple[Path, Path]]:
    """Return (source, payload-relative) files required for a reusable anchor."""
    required = [
        (input_path, Path("inputs") / input_path.name),
        (source / "probes" / "baseline.jsonl", Path("probes/baseline.jsonl")),
        (source / "probes" / "reference.jsonl", Path("probes/reference.jsonl")),
        (source / "rescue" / "combined_population.json", Path("rescue/combined_population.json")),
        (source / "rescue" / "rescue_baseline.jsonl", Path("rescue/rescue_baseline.jsonl")),
        (source / "rescue" / "rescue_reference.jsonl", Path("rescue/rescue_reference.jsonl")),
        (source / "rescue" / "rescue_manifest.json", Path("rescue/rescue_manifest.json")),
        (source / "rescue" / "rescue_results.json", Path("rescue/rescue_results.json")),
        (source / "tune.json", Path("provenance/tune.json")),
    ]
    return [(checked_file(item, f"required population artifact ({relative})"), relative) for item, relative in required]


def write_population(
    package: Path,
    *,
    source: Path,
    input_path: Path,
    role: str,
    name: str,
    expected_trusted: int,
) -> dict[str, Any]:
    destination = package / "payload" / "populations" / "per-root-v1" / role / name
    destination.mkdir(parents=True)
    copied: list[dict[str, Any]] = []
    for artifact, relative in population_files(source, input_path):
        output = destination / relative
        copy(artifact, output)
        copied.append(identity(output, destination))

    combined = destination / "rescue" / "combined_population.json"
    trusted = load_combined_count(combined)
    if trusted != expected_trusted:
        raise SystemExit(f"{name} expected {expected_trusted} trusted positions, found {trusted}")
    population = {
        "schema": POPULATION_SCHEMA,
        "name": name,
        "role": role,
        "reference_contract": "per_root_v1",
        "trusted_positions": trusted,
        "input": next(item for item in copied if item["path"].startswith("inputs/")),
        "artifacts": copied,
    }
    (destination / "population_manifest.json").write_text(
        json.dumps(population, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksums = [identity(path, destination) for path in sorted(destination.rglob("*")) if path.is_file()]
    (destination / "checksums.sha256").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in checksums), encoding="utf-8"
    )
    return {
        "name": name,
        "role": role,
        "trusted_positions": trusted,
        "path": str(destination.relative_to(package)).replace("\\", "/"),
        "manifest_sha256": sha256(destination / "population_manifest.json"),
    }


INSTALLER = r'''#!/usr/bin/env bash
# Install the v1 per-root futility populations into an existing cloud store.
#
# This script only moves completed SR3V directories and copies verified raw
# anchor evidence.  It never launches a chess probe or overwrites a population.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./install.sh STORE_ROOT

Normalizes the pre-v1 cloud paths:
  STORE_ROOT/populations/selection/sr3v
  STORE_ROOT/populations/selection/sr3v-smoke
into:
  STORE_ROOT/populations/per-root-v1/selection/sr3v-production
  STORE_ROOT/populations/per-root-v1/selection/sr3v-smoke
and leaves compatibility symlinks at the old paths.

It then installs the bundled G3-SR4 development and G3-SR3-R2M selection
evidence after validating every bundled file's SHA-256.
EOF
}

if [[ $# -ne 1 ]]; then
    usage >&2
    exit 2
fi

package_root=$(cd -- "$(dirname -- "$0")" && pwd -P)
store_root=$(realpath -m -- "$1")

if ! (cd -- "$package_root" && sha256sum --check --strict payload.sha256); then
    echo "fatal: bundle checksum validation failed" >&2
    exit 1
fi

normalize_legacy() {
    local old=$1
    local new=$2
    if [[ -d "$new" && ! -L "$new" ]]; then
        if [[ -e "$old" || -L "$old" ]]; then
            if [[ -L "$old" && "$(realpath -e -- "$old")" == "$(realpath -e -- "$new")" ]]; then
                echo "normalized: $old -> $new"
                return
            fi
            echo "fatal: legacy path conflicts with already-normalized population: $old" >&2
            exit 1
        fi
        mkdir -p "$(dirname -- "$old")"
        ln -s -- "$new" "$old"
        echo "normalized: created compatibility link $old -> $new"
        return
    fi
    if [[ -e "$new" || -L "$new" ]]; then
        echo "fatal: normalized destination is not a real directory: $new" >&2
        exit 1
    fi
    if [[ ! -d "$old" || -L "$old" ]]; then
        echo "fatal: expected legacy population directory is missing or is already a link: $old" >&2
        exit 1
    fi
    mkdir -p "$(dirname -- "$new")"
    mv -- "$old" "$new"
    ln -s -- "$new" "$old"
    echo "normalized: $old -> $new"
}

verify_population() {
    local root=$1
    [[ -f "$root/population_manifest.json" && -f "$root/checksums.sha256" ]] || {
        echo "fatal: incomplete installed population: $root" >&2
        exit 1
    }
    (cd -- "$root" && sha256sum --check --strict checksums.sha256)
}

install_population() {
    local relative=$1
    local source="$package_root/payload/$relative"
    local destination="$store_root/$relative"
    [[ -d "$source" ]] || { echo "fatal: package population missing: $source" >&2; exit 1; }
    if [[ -e "$destination" || -L "$destination" ]]; then
        if [[ ! -d "$destination" || -L "$destination" ]] || ! cmp -s -- "$source/population_manifest.json" "$destination/population_manifest.json"; then
            echo "fatal: destination exists but is not this exact population: $destination" >&2
            exit 1
        fi
        verify_population "$destination"
        echo "reused: $destination"
        return
    fi
    mkdir -p "$store_root/.incoming" "$(dirname -- "$destination")"
    local stage
    stage=$(mktemp -d "$store_root/.incoming/population-sync.XXXXXX")
    trap 'rm -rf -- "$stage"' RETURN
    cp -a -- "$source" "$stage/population"
    verify_population "$stage/population"
    mv -- "$stage/population" "$destination"
    rmdir -- "$stage"
    trap - RETURN
    verify_population "$destination"
    echo "installed: $destination"
}

mkdir -p "$store_root/populations/per-root-v1/development" \
         "$store_root/populations/per-root-v1/selection" \
         "$store_root/evals" "$store_root/artifacts"

normalize_legacy "$store_root/populations/selection/sr3v" \
    "$store_root/populations/per-root-v1/selection/sr3v-production"
normalize_legacy "$store_root/populations/selection/sr3v-smoke" \
    "$store_root/populations/per-root-v1/selection/sr3v-smoke"

install_population "populations/per-root-v1/development/g3-sr4"
install_population "populations/per-root-v1/selection/g3-sr3-r2m"

echo "population synchronization complete: $store_root"
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="New package directory without .tgz")
    parser.add_argument("--sr4-dir", required=True)
    parser.add_argument("--sr4-input", required=True)
    parser.add_argument("--sr3-r2m-dir", required=True)
    parser.add_argument("--sr3-r2m-input", required=True)
    args = parser.parse_args()

    output = Path(args.output_dir).expanduser().resolve()
    archive = output.with_suffix(".tgz")
    if output.exists() or archive.exists():
        raise SystemExit(f"refusing to overwrite existing package path: {output} or {archive}")
    sr4 = Path(args.sr4_dir).expanduser().resolve()
    sr3_r2m = Path(args.sr3_r2m_dir).expanduser().resolve()
    if not sr4.is_dir() or not sr3_r2m.is_dir():
        raise SystemExit("--sr4-dir and --sr3-r2m-dir must be directories")
    sr4_input = checked_file(Path(args.sr4_input), "--sr4-input")
    sr3_r2m_input = checked_file(Path(args.sr3_r2m_input), "--sr3-r2m-input")

    output.mkdir(parents=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    populations = [
        write_population(
            output,
            source=sr4,
            input_path=sr4_input,
            role="development",
            name="g3-sr4",
            expected_trusted=22825,
        ),
        write_population(
            output,
            source=sr3_r2m,
            input_path=sr3_r2m_input,
            role="selection",
            name="g3-sr3-r2m",
            expected_trusted=22934,
        ),
    ]
    (output / "install.sh").write_text(INSTALLER, encoding="utf-8")
    (output / "install.sh").chmod(0o755)
    (output / "README.md").write_text(
        "# Futility validation population sync (per-root-v1)\n\n"
        "This Linux bundle normalizes the existing SR3V cloud paths and installs the "
        "immutable G3-SR4 and G3-SR3-R2M raw populations. It does not run probes.\n\n"
        "On the cloud server, unpack it beside (not inside) the existing store, then run:\n\n"
        "```bash\n./install.sh /home/ubuntu/futility-validation\n```\n\n"
        "The operation is safe to rerun: it validates checksums and reuses only an exact "
        "already-installed population. It refuses unexpected collisions.\n\n"
        "Afterward the canonical store is:\n\n"
        "```text\n"
        "populations/per-root-v1/development/g3-sr4/\n"
        "populations/per-root-v1/selection/g3-sr3-r2m/\n"
        "populations/per-root-v1/selection/sr3v-production/\n"
        "populations/per-root-v1/selection/sr3v-smoke/\n"
        "```\n\n"
        "Old SR3V paths are retained as absolute compatibility symlinks.\n",
        encoding="utf-8",
    )
    files = [path for path in sorted((output / "payload").rglob("*")) if path.is_file()]
    (output / "payload.sha256").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(output).as_posix()}\n" for path in files), encoding="utf-8"
    )
    manifest_files = [path for path in sorted(output.rglob("*")) if path.is_file()]
    manifest = {
        "schema": SCHEMA,
        "purpose": "normalize cloud SR3V paths and install immutable per-root-v1 SR4/SR3-R2M evidence",
        "git_revision": revision,
        "source_dirty": dirty,
        "command": "./install.sh /home/ubuntu/futility-validation",
        "populations": populations,
        "files": [identity(path, output) for path in manifest_files],
    }
    (output / "package_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=f"{output.name}/{path.relative_to(output)}")
    with tarfile.open(archive, "r:gz") as tar:
        expected = {f"{output.name}/{path.relative_to(output).as_posix()}" for path in output.rglob("*") if path.is_file()}
        actual = {member.name for member in tar.getmembers() if member.isfile()}
        if actual != expected:
            raise SystemExit("archive content verification failed")
    print(f"Created {archive}")
    print(f"SHA-256 {sha256(archive)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
