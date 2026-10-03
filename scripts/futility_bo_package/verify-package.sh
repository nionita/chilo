#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
sha256sum --quiet -c package-files.sha256
