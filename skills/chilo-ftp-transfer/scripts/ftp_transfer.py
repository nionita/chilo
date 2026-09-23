#!/usr/bin/env python3
"""Small, guarded FTP helper for the Chilo shared transfer directory."""

from __future__ import annotations

import argparse
import ftplib
import getpass
import hashlib
import os
from pathlib import Path
import sys
import tempfile


HOST = "10.0.0.6"
USERNAME = "ftp"
REMOTE_DIR = "/PUBLIC/transf"
TIMEOUT_SECONDS = 30
BLOCK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_remote_name(name: str) -> str:
    if not name or name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError(f"remote name must be a simple filename, got {name!r}")
    return name


def connect() -> ftplib.FTP:
    password = getpass.getpass(f"FTP password for {USERNAME}@{HOST}: ")
    client = ftplib.FTP()
    client.connect(HOST, 21, timeout=TIMEOUT_SECONDS)
    client.login(USERNAME, password)
    client.set_pasv(True)
    client.cwd(REMOTE_DIR)
    return client


def remote_names(client: ftplib.FTP) -> set[str]:
    return {Path(item.rstrip("/")).name for item in client.nlst()}


def command_list(client: ftplib.FTP, _args: argparse.Namespace) -> None:
    names = sorted(remote_names(client))
    for name in names:
        try:
            size = client.size(name)
        except ftplib.all_errors:
            size = None
        suffix = f"\t{size} bytes" if size is not None else ""
        print(f"{name}{suffix}")
    if not names:
        print("(empty)")


def command_put(client: ftplib.FTP, args: argparse.Namespace) -> None:
    local_path = Path(args.file).expanduser().resolve(strict=True)
    if not local_path.is_file():
        raise ValueError(f"not a regular file: {local_path}")
    remote_name = validate_remote_name(args.remote_name or local_path.name)
    if remote_name in remote_names(client) and not args.overwrite:
        raise FileExistsError(f"remote file already exists: {remote_name} (use --overwrite to replace it)")

    size = local_path.stat().st_size
    digest = sha256_file(local_path)
    with local_path.open("rb") as source:
        client.storbinary(f"STOR {remote_name}", source, blocksize=BLOCK_SIZE)
    try:
        remote_size = client.size(remote_name)
    except ftplib.all_errors:
        remote_size = None
    if remote_size is not None and remote_size != size:
        raise OSError(f"uploaded size mismatch: local={size}, remote={remote_size}")
    print(f"uploaded {remote_name}: {size} bytes sha256={digest}")


def command_get(client: ftplib.FTP, args: argparse.Namespace) -> None:
    remote_name = validate_remote_name(args.remote_name)
    destination = Path(args.output or remote_name).expanduser().absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not args.overwrite:
        raise FileExistsError(f"destination already exists: {destination} (use --overwrite to replace it)")

    try:
        expected_size = client.size(remote_name)
    except ftplib.all_errors:
        expected_size = None

    digest = hashlib.sha256()
    received = 0
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{destination.name}.", suffix=".part",
            dir=destination.parent, delete=False,
        ) as target:
            temp_path = Path(target.name)

            def write_block(block: bytes) -> None:
                nonlocal received
                target.write(block)
                digest.update(block)
                received += len(block)

            client.retrbinary(f"RETR {remote_name}", write_block, blocksize=BLOCK_SIZE)
            target.flush()
            os.fsync(target.fileno())

        if expected_size is not None and received != expected_size:
            raise OSError(f"download size mismatch: expected={expected_size}, received={received}")
        if destination.exists() and not args.overwrite:
            raise FileExistsError(f"destination appeared during download: {destination}")
        os.replace(temp_path, destination)
        temp_path = None
        print(f"downloaded {remote_name} -> {destination}: {received} bytes sha256={digest.hexdigest()}")
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list files in /PUBLIC/transf")
    list_parser.set_defaults(handler=command_list)

    put_parser = subparsers.add_parser("put", help="upload one local file")
    put_parser.add_argument("file", help="local file to upload")
    put_parser.add_argument("--remote-name", help="remote filename (default: local basename)")
    put_parser.add_argument("--overwrite", action="store_true", help="replace an existing remote file")
    put_parser.set_defaults(handler=command_put)

    get_parser = subparsers.add_parser("get", help="download one remote file")
    get_parser.add_argument("remote_name", help="filename in /PUBLIC/transf")
    get_parser.add_argument("--output", help="local destination (default: current directory / remote name)")
    get_parser.add_argument("--overwrite", action="store_true", help="replace an existing local destination")
    get_parser.set_defaults(handler=command_get)
    return parser


def main() -> int:
    args = make_parser().parse_args()
    client: ftplib.FTP | None = None
    try:
        client = connect()
        args.handler(client, args)
        return 0
    except (OSError, ValueError) as exc:
        print(f"ftp transfer failed: {exc}", file=sys.stderr)
        return 1
    except ftplib.all_errors as exc:
        print(f"ftp transfer failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            try:
                client.quit()
            except ftplib.all_errors:
                client.close()


if __name__ == "__main__":
    raise SystemExit(main())
