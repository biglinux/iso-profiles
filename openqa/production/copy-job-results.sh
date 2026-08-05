#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

if (($# != 3)); then
    echo "Usage: $0 CONTAINER JOB_ID DESTINATION" >&2
    exit 2
fi

container=$1
job_id=$2
destination=$3
docker_bin=${DOCKER_BIN:-docker}

[[ "$container" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || {
    echo "Invalid container name: $container" >&2
    exit 2
}
[[ "$job_id" =~ ^[1-9][0-9]*$ ]] || {
    echo "Invalid openQA job ID: $job_id" >&2
    exit 2
}
[[ -n "$destination" ]] || {
    echo 'Destination must not be empty' >&2
    exit 2
}

printf -v padded_job_id '%08d' "$job_id"
mapfile -t result_dirs < <(
    "$docker_bin" exec "$container" find /var/lib/openqa/testresults \
        -mindepth 2 -maxdepth 2 -type d -name "${padded_job_id}-*" -print
)

((${#result_dirs[@]} == 1)) || {
    echo "Expected one result directory for openQA job $job_id, found ${#result_dirs[@]}" >&2
    exit 1
}
result_dir=${result_dirs[0]}
[[ "$result_dir" == /var/lib/openqa/testresults/* ]] || {
    echo "Invalid result directory for openQA job $job_id: $result_dir" >&2
    exit 1
}

rm -rf -- "$destination"
mkdir -p -- "$destination/testresults"
"$docker_bin" cp "$container:$result_dir/." "$destination/testresults/"

test -s "$destination/testresults/vars.json" || {
    echo "Copied result for openQA job $job_id has no vars.json" >&2
    exit 1
}
find "$destination/testresults" -maxdepth 1 -type f -name 'details-*.json' \
    -print -quit | grep -q . || {
    echo "Copied result for openQA job $job_id has no module details" >&2
    exit 1
}

# Screenshots are content-addressed under /var/lib/openqa/images and referenced
# by details-*.json. Materialize them under their module screenshot names so
# the artifact is complete without using the HTTP image route.
screenshot_map=$(mktemp)
image_cache=
cleanup_temporary_files() {
    rm -f -- "$screenshot_map"
    [[ -z "$image_cache" ]] || rm -rf -- "$image_cache"
}
trap cleanup_temporary_files EXIT
if ! python3 - "$destination/testresults" >"$screenshot_map" <<'PY_END'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
images = set()
for details_path in sorted(root.glob("details-*.json")):
    try:
        payload = json.loads(details_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Invalid openQA details file {details_path}: {error}")
    for detail in payload.get("details", []):
        if not isinstance(detail, dict) or "screenshot" not in detail:
            continue
        if "frametime" in detail and "md5_basename" not in detail:
            # Video-frame references have no content-addressed image file.
            continue
        values = (
            detail.get("screenshot"),
            detail.get("md5_dirname"),
            detail.get("md5_basename"),
        )
        if not all(isinstance(value, str) and value for value in values):
            raise SystemExit(f"Incomplete screenshot metadata in {details_path}")
        images.add(values)
for values in sorted(images):
    print("\t".join(values))
PY_END
then
    echo "Could not parse screenshot metadata for openQA job $job_id" >&2
    exit 1
fi

if [[ -s "$screenshot_map" ]]; then
    image_cache=$(mktemp -d)
    "$docker_bin" cp "$container:/var/lib/openqa/images/." "$image_cache/"
fi

while IFS=$'\t' read -r screenshot md5_dirname md5_basename; do
    [[ "$screenshot" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*\.png$ ]] || {
        echo "Invalid screenshot name in openQA details: $screenshot" >&2
        exit 1
    }
    [[ "$md5_dirname" =~ ^[0-9a-f]{3}/[0-9a-f]{3}$ ]] || {
        echo "Invalid screenshot directory in openQA details: $md5_dirname" >&2
        exit 1
    }
    [[ "$md5_basename" =~ ^[0-9a-f]{26}\.png$ ]] || {
        echo "Invalid screenshot basename in openQA details: $md5_basename" >&2
        exit 1
    }
    image_source="$image_cache/$md5_dirname/$md5_basename"
    test -s "$image_source" || {
        echo "Referenced screenshot image is missing: $md5_dirname/$md5_basename" >&2
        exit 1
    }
    rm -f -- "$destination/testresults/$screenshot"
    cp -- "$image_source" "$destination/testresults/$screenshot"
done <"$screenshot_map"

printf 'Copied openQA job %s directly from %s\n' "$job_id" "$result_dir"
