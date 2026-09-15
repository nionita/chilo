#!/usr/bin/env bash
# Create the immutable cloud-side futility validation store.
#
# This is a deliberately guarded one-time migration.  It moves an already
# completed validation-shard run into the store, then leaves a symlink at the
# old location so the original package remains inspectable and runnable.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: setup_futility_validation_store.sh STORE_ROOT LEGACY_PACKAGE_DIR [LEGACY_SMOKE_PACKAGE_DIR]

Move a completed five-shard sr3v run into:
  STORE_ROOT/populations/selection/sr3v/run

The legacy package must contain ``run/``, ``tools/futility_probe-avx2``, and
``weights/chilo-g4t1-64x8.bin``.  The exact probe and weights are copied once
into ``STORE_ROOT/artifacts/<probe-sha256>-<weights-sha256>/``.  The run
destination must not already exist.  ``LEGACY_PACKAGE_DIR/run`` is replaced
with a symlink to its new location after the move.  No probe or rescue work is
run.  If the optional smoke package is supplied, its two completed test shards
are moved to ``populations/selection/sr3v-smoke/run`` in the same operation.
EOF
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
    usage >&2
    exit 2
fi

store_root=$(realpath -m -- "$1")
legacy_package=$(realpath -e -- "$2")
legacy_run="$legacy_package/run"
destination="$store_root/populations/selection/sr3v/run"
smoke_package=""
smoke_run=""
smoke_destination="$store_root/populations/selection/sr3v-smoke/run"

if [[ ! -d "$legacy_package" ]]; then
    echo "fatal: legacy package directory does not exist: $legacy_package" >&2
    exit 1
fi
if [[ ! -d "$legacy_run" ]]; then
    echo "fatal: legacy package has no run directory: $legacy_run" >&2
    exit 1
fi
if [[ -L "$legacy_run" ]]; then
    echo "fatal: legacy run directory is already a symlink: $legacy_run" >&2
    exit 1
fi
if [[ ! -f "$legacy_run/complete.json" ]]; then
    echo "fatal: legacy run has no top-level completion receipt: $legacy_run/complete.json" >&2
    exit 1
fi
for shard in sr3v-01 sr3v-02 sr3v-03 sr3v-04 sr3v-05; do
    receipt="$legacy_run/shards/$shard/rescue/completion.json"
    if [[ ! -f "$receipt" ]]; then
        echo "fatal: missing completed rescue receipt: $receipt" >&2
        exit 1
    fi
done
if [[ -e "$destination" ]]; then
    echo "fatal: destination already exists; refusing to merge or overwrite: $destination" >&2
    exit 1
fi

if [[ $# -eq 3 ]]; then
    smoke_package=$(realpath -e -- "$3")
    smoke_run="$smoke_package/run"
    if [[ ! -d "$smoke_package" || ! -d "$smoke_run" || -L "$smoke_run" ]]; then
        echo "fatal: smoke package must contain a real run directory: $smoke_package" >&2
        exit 1
    fi
    if [[ ! -f "$smoke_run/complete.json" ]]; then
        echo "fatal: smoke run has no top-level completion receipt: $smoke_run/complete.json" >&2
        exit 1
    fi
    for shard in sr3v-test1 sr3v-test2; do
        receipt="$smoke_run/shards/$shard/rescue/completion.json"
        if [[ ! -f "$receipt" ]]; then
            echo "fatal: missing completed smoke rescue receipt: $receipt" >&2
            exit 1
        fi
    done
    if [[ -e "$smoke_destination" ]]; then
        echo "fatal: smoke destination already exists; refusing to merge or overwrite: $smoke_destination" >&2
        exit 1
    fi
fi

probe_source="$legacy_package/tools/futility_probe-avx2"
weights_source="$legacy_package/weights/chilo-g4t1-64x8.bin"
if [[ ! -f "$probe_source" || ! -f "$weights_source" ]]; then
    echo "fatal: legacy package must contain tools/futility_probe-avx2 and weights/chilo-g4t1-64x8.bin" >&2
    exit 1
fi
probe_sha=$(sha256sum -- "$probe_source" | awk '{print $1}')
weights_sha=$(sha256sum -- "$weights_source" | awk '{print $1}')
artifact_dir="$store_root/artifacts/$probe_sha-$weights_sha"

mkdir -p "$store_root/populations/development" \
    "$store_root/populations/selection" \
    "$store_root/artifacts" \
    "$store_root/evals"
mkdir -p "$(dirname "$destination")"

if [[ -e "$artifact_dir" ]]; then
    if [[ ! -f "$artifact_dir/futility_probe-avx2" || ! -f "$artifact_dir/chilo-g4t1-64x8.bin" ]] || \
       [[ $(sha256sum -- "$artifact_dir/futility_probe-avx2" | awk '{print $1}') != "$probe_sha" ]] || \
       [[ $(sha256sum -- "$artifact_dir/chilo-g4t1-64x8.bin" | awk '{print $1}') != "$weights_sha" ]]; then
        echo "fatal: existing artifact directory does not contain the expected frozen artifacts: $artifact_dir" >&2
        exit 1
    fi
else
    mkdir -p "$artifact_dir"
    cp --reflink=auto --preserve=mode,timestamps -- "$probe_source" "$artifact_dir/futility_probe-avx2"
    cp --reflink=auto --preserve=mode,timestamps -- "$weights_source" "$artifact_dir/chilo-g4t1-64x8.bin"
fi

mv -- "$legacy_run" "$destination"
ln -s -- "$destination" "$legacy_run"
if [[ -n "$smoke_package" ]]; then
    mkdir -p "$(dirname "$smoke_destination")"
    mv -- "$smoke_run" "$smoke_destination"
    ln -s -- "$smoke_destination" "$smoke_run"
fi

echo "validation store initialized: $store_root"
echo "immutable sr3v population: $destination"
echo "frozen artifacts: $artifact_dir"
echo "legacy path retained as symlink: $legacy_run -> $destination"
if [[ -n "$smoke_package" ]]; then
    echo "immutable smoke population: $smoke_destination"
    echo "smoke legacy path retained as symlink: $smoke_run -> $smoke_destination"
fi
