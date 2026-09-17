#!/usr/bin/env python3
"""Immutable content-addressed cache for completed normal-PVS futility probes."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, Sequence

import tune_futility


SCHEMA = "chilo.futility_probe_cache.v1"
MODE = "normal_pvs"


class CacheError(RuntimeError):
    pass


@dataclass(frozen=True)
class CacheEntry:
    key: str
    descriptor: Mapping[str, Any]
    directory: Path
    output: Path
    manifest: Path


def _portable_identity(path: Optional[Path]) -> Optional[dict[str, Any]]:
    if path is None:
        return None
    value = tune_futility.file_identity(path)
    return {"sha256": value["sha256"], "size": value["size"]}


def descriptor(
    probe: Path, weights: Optional[Path], inputs: Sequence[Path], nodes: int, margins: Sequence[int]
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "mode": MODE,
        "probe": _portable_identity(probe),
        "weights": _portable_identity(weights),
        "inputs": [_portable_identity(path) for path in inputs],
        "nodes": int(nodes),
        "margins": [int(value) for value in margins],
    }


def key_for(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def entry_for(root: Path, value: Mapping[str, Any]) -> CacheEntry:
    key = key_for(value)
    directory = root / "entries" / key[:2] / key
    return CacheEntry(key, value, directory, directory / "output.jsonl", directory / "manifest.json")


def initialize(root: Path) -> None:
    (root / "entries").mkdir(parents=True, exist_ok=True)
    (root / ".incoming").mkdir(parents=True, exist_ok=True)
    (root / ".locks").mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CacheError(f"invalid cache manifest {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise CacheError(f"invalid cache manifest {path}: root must be an object")
    return result


def _same_identity(left: Any, right: Mapping[str, Any]) -> bool:
    return isinstance(left, dict) and left.get("sha256") == right.get("sha256") and left.get("size") == right.get("size")


def validate(entry: CacheEntry, nodes: int, margins: Sequence[int]) -> Mapping[str, Any]:
    if not entry.manifest.is_file() or not entry.output.is_file():
        raise CacheError(f"incomplete cache entry {entry.key}")
    manifest = _read_json(entry.manifest)
    if manifest.get("schema") != SCHEMA or manifest.get("key") != entry.key or manifest.get("descriptor") != entry.descriptor:
        raise CacheError(f"cache entry {entry.key} manifest does not match its key")
    identity = tune_futility.file_identity(entry.output)
    if not _same_identity(manifest.get("output"), identity):
        raise CacheError(f"cache entry {entry.key} output differs from its manifest")
    try:
        return tune_futility.parse_probe_output(entry.output, nodes, margins)
    except tune_futility.TuningError as exc:
        raise CacheError(f"cache entry {entry.key} is not a complete normal-PVS probe") from exc


def receipt(entry: CacheEntry, status: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "key": entry.key,
        "status": status,
        "cache_output": tune_futility.file_identity(entry.output),
    }


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        shutil.copy2(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def restore(entry: CacheEntry, destination: Path, nodes: int, margins: Sequence[int]) -> Mapping[str, Any]:
    parsed = validate(entry, nodes, margins)
    atomic_copy(entry.output, destination)
    try:
        tune_futility.parse_probe_output(destination, nodes, margins)
    except tune_futility.TuningError as exc:
        raise CacheError(f"cached output could not be staged at {destination}") from exc
    return parsed


def publish(entry: CacheEntry, source: Path, nodes: int, margins: Sequence[int]) -> Mapping[str, Any]:
    """Publish a completed source output once; never overwrite a cache entry."""
    try:
        return validate(entry, nodes, margins)
    except CacheError as existing_error:
        if entry.directory.exists():
            raise existing_error
    try:
        parsed = tune_futility.parse_probe_output(source, nodes, margins)
    except tune_futility.TuningError as exc:
        raise CacheError(f"cannot publish incomplete probe output {source}") from exc
    incoming = entry.directory.parent.parent.parent / ".incoming" / (entry.key + "." + str(os.getpid()))
    try:
        incoming.mkdir(parents=True, exist_ok=False)
        output = incoming / "output.jsonl"
        atomic_copy(source, output)
        output_identity = tune_futility.file_identity(output)
        manifest = {"schema": SCHEMA, "key": entry.key, "descriptor": entry.descriptor, "output": output_identity}
        (incoming / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        entry.directory.parent.mkdir(parents=True, exist_ok=True)
        try:
            incoming.replace(entry.directory)
        except FileExistsError:
            return validate(entry, nodes, margins)
    finally:
        if incoming.exists():
            shutil.rmtree(incoming)
    return parsed


@contextlib.contextmanager
def lock(root: Path, key: str) -> Iterator[None]:
    """Use a per-key advisory lock for a cache miss and its promotion."""
    initialize(root)
    path = root / ".locks" / (key + ".lock")
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl  # Linux cloud runner; Windows callers retain safe local behaviour.
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        handle.close()

