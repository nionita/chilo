---
name: chilo-ftp-transfer
description: Transfer Chilo futility experiment archives and light result bundles between this workstation and the shared FTP/WebDAV staging folder, including preparing files for the cloud server or retrieving its results.
---

# Chilo FTP transfer

Use this skill when moving experiment packages or results through the shared transfer folder. The FTP endpoint is `10.0.0.6`, account `ftp`, remote directory `/PUBLIC/transf` (also exposed to the operator as a WebDAV drive). Use `scripts/ftp_transfer.py` to list, upload, or download files.

## Security and routing

- The helper prompts for the FTP password with input hidden. Never put the password in this skill, a script, a config, a command-line argument, or a log.
- This is plain FTP, so credentials and file contents are not encrypted on the network. Use it only on the expected trusted LAN; do not use it over an untrusted network.
- `10.0.0.6` is a private LAN address. Do not assume the cloud server can reach it. The normal route is workstation ↔ FTP/WebDAV staging folder ↔ cloud server, using the operator's mapped WebDAV drive and SSH/SCP as appropriate. Verify direct routing before attempting to use FTP from the cloud host.
- This helper does not delete remote files. It refuses to overwrite either a remote or local file unless `--overwrite` is explicitly supplied.

## Commands

From the repository root:

```sh
python3 skills/chilo-ftp-transfer/scripts/ftp_transfer.py list
python3 skills/chilo-ftp-transfer/scripts/ftp_transfer.py put /path/to/archive.tgz
python3 skills/chilo-ftp-transfer/scripts/ftp_transfer.py get archive-results.tgz --output /path/to/archive-results.tgz
```

`put` uses the local basename as the remote filename; `--remote-name NAME` changes it. `get` defaults to writing into the current directory; `--output PATH` selects another destination. For an intentional replacement, add `--overwrite` to `put` or `get`. The helper prints the byte count and SHA-256 after transfer and checks the server-reported size when available.

## Typical round trip

1. On this workstation, use `list` to confirm the staging folder and `put` to upload the package or result archive.
2. On Windows, the same `/PUBLIC/transf` contents are available through the operator's WebDAV drive. Copy the file to or from the cloud server with the usual SSH/SCP workflow; the helper does not automate credentials or remote SSH access.
3. After the cloud task completes, place its result archive in the staging folder, then use `get` here. Keep the printed SHA-256 with the transfer notes and verify it again if the file is copied through another machine.
4. Do not remove staged files as part of a transfer. Clean them up only after confirming that the destination copy is complete and verified.
