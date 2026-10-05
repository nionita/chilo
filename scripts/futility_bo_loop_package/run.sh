#!/usr/bin/env bash
set -euo pipefail
package_root=$(cd -- "$(dirname -- "$0")" && pwd -P)
exec "$package_root/loop.sh" run "$@"
