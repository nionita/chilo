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
- On the cloud, stage incoming and outgoing tar archives under `/tmp`. Extract run packages into a permanent directory under `/home/ubuntu`, not into `/tmp`; running jobs and evidence must survive temporary-file cleanup. Report cloud commands with `/tmp/archive.tgz` as the archive path, rather than assuming the archive was copied into the home or package directory.
- This helper does not delete remote files. It refuses to overwrite either a remote or local file unless `--overwrite` is explicitly supplied.

## Commands

From the repository root:

```sh
python3 skills/chilo-ftp-transfer/scripts/ftp_transfer.py list
python3 skills/chilo-ftp-transfer/scripts/ftp_transfer.py put /path/to/archive.tgz
python3 skills/chilo-ftp-transfer/scripts/ftp_transfer.py get archive-results.tgz --output /path/to/archive-results.tgz
```

`put` uses the local basename as the remote filename; `--remote-name NAME` changes it. `get` defaults to writing into the current directory; `--output PATH` selects another destination. For an intentional replacement, add `--overwrite` to `put` or `get`. The helper prints the byte count and SHA-256 after transfer and checks the server-reported size when available.

## Integrity checks

- The SHA-256 printed by `put` is the **local source** hash, not proof of the remote file's content. After uploading a package, download it to a fresh inspection path with `get` and compare its SHA-256 or bytes with the original. Use `gzip -t` for a `.tgz` as an additional format check, not a substitute for hash equality.
- Preserve the known-good source SHA-256 across the Windows/WebDAV and SCP hops. On the cloud, use `sha256sum /tmp/archive.tgz` and `gzip -t /tmp/archive.tgz` before extracting. On Windows, use `Get-FileHash -Algorithm SHA256` on both the received local file and the mapped WebDAV copy. Ask for the source hash when receiving results if it was not supplied; without one, report that end-to-end source equality has not been verified.
- A prior result transfer had different source and WebDAV hashes even though a file with the expected name was present. A fresh filename for a newly recopied, known-good archive resolved that case. On a mismatch, do not extract/import the archive or relabel its hash as expected. Report the mismatch and request a verified recopy, preferably under a fresh filename; do not silently overwrite files or keep retrying indefinitely.

## Typical round trip

1. On this workstation, use `list` to confirm the staging folder and `put` to upload the package or result archive. Download it back to a fresh path and verify equality with the source before reporting the upload as verified.
2. On Windows, the same `/PUBLIC/transf` contents are available through the operator's WebDAV drive. Copy the file to or from the cloud server's `/tmp` with the usual SSH/SCP workflow, checking against the source SHA-256. The helper does not automate credentials or remote SSH access.
3. After the cloud task completes, create its result archive under `/tmp`, record its source SHA-256, and copy it to the staging folder. Use `get` here and compare that hash before accepting the results. Transfer only the requested results/evidence, not a broad home directory or runtime environment.
4. Do not remove staged files as part of a transfer. Clean them up only after confirming that the destination copy is complete and verified.
