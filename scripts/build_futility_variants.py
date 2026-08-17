#!/usr/bin/env python3
"""Build named AVX2 Chilo binaries for fixed futility-margin variants."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


SCHEMA = "chilo.futility_variants.v1"
MAX_FUTILITY_DEPTH = 7
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REPO_ROOT = Path(__file__).resolve().parents[1]


class VariantBuildError(Exception):
    pass


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build named AVX2 Chilo futility-margin variants.")
    parser.add_argument("--manifest", required=True, help="Variant manifest JSON file")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing destination binaries")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print build commands without building")
    return parser.parse_args(argv)


def require_object(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise VariantBuildError(f"{label} must be an object")
    return dict(value)


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise VariantBuildError(f"{label} must be a non-empty string")
    return value


def require_margins(value: Any, label: str) -> List[int]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FUTILITY_DEPTH:
        raise VariantBuildError(f"{label} must contain 1 to {MAX_FUTILITY_DEPTH} margins")
    if any(isinstance(margin, bool) or not isinstance(margin, int) for margin in value):
        raise VariantBuildError(f"{label} margins must be integers")
    if any(margin < 0 for margin in value):
        raise VariantBuildError(f"{label} margins must be nonnegative")
    if any(left > right for left, right in zip(value, value[1:])):
        raise VariantBuildError(f"{label} margins must be nondecreasing")
    return list(value)


def resolve_config_path(value: str, manifest_dir: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (manifest_dir / path).resolve()


def validate_note(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    return require_string(value, label)


def load_manifest(path: Path) -> Dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        raise VariantBuildError(f"invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise VariantBuildError(f"failed to read manifest {path}: {exc}") from exc

    root = require_object(raw, "manifest")
    allowed = {"schema", "base_version", "engine_directory", "build_root", "baseline", "variants"}
    unknown = sorted(set(root) - allowed)
    if unknown:
        raise VariantBuildError(f"unknown manifest field(s): {', '.join(unknown)}")
    if root.get("schema") != SCHEMA:
        raise VariantBuildError(f"manifest schema must be {SCHEMA!r}")

    base_version = require_string(root.get("base_version"), "base_version")
    if not VERSION_RE.fullmatch(base_version):
        raise VariantBuildError("base_version may contain only letters, digits, '.', '_', and '-'")
    manifest_dir = path.parent
    engine_directory = resolve_config_path(require_string(root.get("engine_directory"), "engine_directory"), manifest_dir)
    build_root = resolve_config_path(require_string(root.get("build_root"), "build_root"), manifest_dir)

    baseline = require_object(root.get("baseline"), "baseline")
    baseline_unknown = sorted(set(baseline) - {"margins", "note"})
    if baseline_unknown:
        raise VariantBuildError(f"unknown baseline field(s): {', '.join(baseline_unknown)}")
    normalized_baseline = {
        "margins": require_margins(baseline.get("margins"), "baseline.margins"),
        "note": validate_note(baseline.get("note"), "baseline.note"),
    }

    raw_variants = root.get("variants")
    if not isinstance(raw_variants, list) or not raw_variants:
        raise VariantBuildError("variants must be a non-empty array")
    variants: List[Dict[str, Any]] = []
    seen_codes = set()
    seen_margins = set()
    for index, raw_variant in enumerate(raw_variants):
        label = f"variants[{index}]"
        variant = require_object(raw_variant, label)
        unknown_variant = sorted(set(variant) - {"code", "margins", "note"})
        if unknown_variant:
            raise VariantBuildError(f"unknown {label} field(s): {', '.join(unknown_variant)}")
        code = require_string(variant.get("code"), f"{label}.code")
        if not CODE_RE.fullmatch(code):
            raise VariantBuildError(f"{label}.code must be a short filename-safe identifier")
        if code in seen_codes:
            raise VariantBuildError(f"duplicate variant code {code!r}")
        margins = require_margins(variant.get("margins"), f"{label}.margins")
        tuple_margins = tuple(margins)
        if tuple_margins in seen_margins:
            raise VariantBuildError(f"duplicate margin tuple for variant {code!r}")
        seen_codes.add(code)
        seen_margins.add(tuple_margins)
        variants.append({"code": code, "margins": margins, "note": validate_note(variant.get("note"), f"{label}.note")})

    return {
        "schema": SCHEMA,
        "path": path,
        "base_version": base_version,
        "engine_directory": engine_directory,
        "build_root": build_root,
        "baseline": normalized_baseline,
        "variants": variants,
    }


def variant_version(base_version: str, code: str) -> str:
    return f"{base_version}-{code}"


def variant_output_path(engine_directory: Path, base_version: str, code: str) -> Path:
    return engine_directory / f"chilo-{variant_version(base_version, code)}-avx2"


def variant_build_dir(variant: Mapping[str, Any], manifest: Mapping[str, Any]) -> Path:
    margins = "-".join(str(margin) for margin in variant["margins"])
    name = f"{variant_version(str(manifest['base_version']), str(variant['code']))}-d{len(variant['margins'])}-{margins}"
    return Path(manifest["build_root"]) / name


def build_command(variant: Mapping[str, Any], manifest: Mapping[str, Any]) -> List[str]:
    margins = list(variant["margins"])
    padded_margins = [0] + margins + [0] * (MAX_FUTILITY_DEPTH - len(margins))
    build_dir = variant_build_dir(variant, manifest)
    target = build_dir / "release-avx2" / "chilo"
    cppflags = " ".join(
        (
            f"-DCHILO_VERSION_OVERRIDE={variant_version(str(manifest['base_version']), str(variant['code']))}",
            f"-DCHILO_FUTILITY_MAX_DEPTH={len(margins)}",
            "-DCHILO_FUTILITY_MARGINS=" + ",".join(str(margin) for margin in padded_margins),
        )
    )
    return ["make", f"BUILD_DIR={build_dir}", f"EXTRA_CPPFLAGS={cppflags}", str(target)]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_state() -> Dict[str, Any]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True).strip())
        return {"source_commit": commit, "source_dirty": dirty}
    except (OSError, subprocess.CalledProcessError) as exc:
        raise VariantBuildError(f"failed to determine source revision: {exc}") from exc


def verify_version(binary: Path, expected: str) -> None:
    try:
        completed = subprocess.run([str(binary), "--version"], check=False, capture_output=True, text=True)
    except OSError as exc:
        raise VariantBuildError(f"failed to run {binary}: {exc}") from exc
    actual = completed.stdout.strip()
    if completed.returncode != 0 or actual != expected:
        raise VariantBuildError(f"{binary} reported {actual!r}; expected {expected!r}")


def receipt_path(manifest_path: Path) -> Path:
    return manifest_path.with_name(f"{manifest_path.stem}.build-receipt.json")


def preflight_outputs(manifest: Mapping[str, Any], overwrite: bool) -> None:
    existing = [
        variant_output_path(Path(manifest["engine_directory"]), str(manifest["base_version"]), str(variant["code"]))
        for variant in manifest["variants"]
        if variant_output_path(Path(manifest["engine_directory"]), str(manifest["base_version"]), str(variant["code"])).exists()
    ]
    if existing and not overwrite:
        names = ", ".join(str(path) for path in existing)
        raise VariantBuildError(f"destination binary already exists: {names}; pass --overwrite to replace it")


def build_variants(manifest: Mapping[str, Any], overwrite: bool, dry_run: bool) -> List[Dict[str, Any]]:
    preflight_outputs(manifest, overwrite)
    entries: List[Dict[str, Any]] = []
    for variant in manifest["variants"]:
        command = build_command(variant, manifest)
        output = variant_output_path(Path(manifest["engine_directory"]), str(manifest["base_version"]), str(variant["code"]))
        expected_version = variant_version(str(manifest["base_version"]), str(variant["code"])) + " avx2"
        entry: Dict[str, Any] = {
            "code": variant["code"],
            "margins": variant["margins"],
            "note": variant["note"],
            "expected_version": expected_version,
            "build_command": command,
            "output": str(output),
        }
        if dry_run:
            entries.append(entry)
            continue

        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(command, cwd=REPO_ROOT, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise VariantBuildError(f"build failed for {variant['code']}: {exc}") from exc
        built_binary = variant_build_dir(variant, manifest) / "release-avx2" / "chilo"
        if not built_binary.is_file():
            raise VariantBuildError(f"build for {variant['code']} did not create {built_binary}")
        shutil.copy2(built_binary, output)
        verify_version(output, expected_version)
        entry["sha256"] = sha256_file(output)
        entries.append(entry)
    return entries


def write_receipt(manifest: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> Path:
    path = receipt_path(Path(manifest["path"]))
    receipt = {
        "schema": "chilo.futility_variant_build_receipt.v1",
        "created_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "manifest": str(manifest["path"]),
        "base_version": manifest["base_version"],
        "baseline": manifest["baseline"],
        "variants": list(entries),
    }
    receipt.update(source_state())
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        manifest_path = Path(args.manifest).expanduser().resolve()
        manifest = load_manifest(manifest_path)
        entries = build_variants(manifest, args.overwrite, args.dry_run)
        if args.dry_run:
            print(json.dumps({"manifest": str(manifest_path), "variants": entries}, indent=2))
            return 0
        receipt = write_receipt(manifest, entries)
        print(f"built {len(entries)} variant(s); receipt: {receipt}")
        return 0
    except VariantBuildError as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
