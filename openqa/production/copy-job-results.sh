#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Collect one openQA job's results, screenshots included.
#
# Copying the result directory out of the container does not work: openQA keeps
# screenshots as content-addressed images and the details on disk only name the
# PNG, so the copy produced details pointing at files that were never beside
# them. The web UI resolves those names when it serves a job, and openQA ships a
# client for exactly this, so use it and let it write straight into the mount the
# host already shares with the container.

set -euo pipefail

if (($# != 3)); then
    echo "Usage: $0 CONTAINER JOB_ID DESTINATION" >&2
    exit 2
fi

container=$1
job_id=$2
destination=$3
docker_bin=${DOCKER_BIN:-docker}
# Must match the results volume the workflow gives the container.
results_mount=${BIGLINUX_OPENQA_RESULTS_MOUNT:-/var/lib/openqa/biglinux-results}

[[ "$container" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || {
    echo "Invalid container name: $container" >&2
    exit 2
}
[[ "$job_id" =~ ^[1-9][0-9]*$ ]] || {
    echo "Invalid openQA job ID: $job_id" >&2
    exit 2
}
[[ "$destination" == */"$job_id" ]] || {
    echo "Destination must end in the job ID so it maps onto $results_mount: $destination" >&2
    exit 2
}

rm -rf -- "$destination"
"$docker_bin" exec "$container" openqa-cli archive --host http://localhost \
    --with-thumbnails "$job_id" "$results_mount/$job_id"

test -s "$destination/testresults/vars.json" || {
    echo "Archived result for openQA job $job_id has no vars.json" >&2
    exit 1
}
find "$destination/testresults" -maxdepth 1 -type f -name 'details-*.json' \
    -print -quit | grep -q . || {
    echo "Archived result for openQA job $job_id has no module details" >&2
    exit 1
}

# The archive client asks for a screenshot per step number, and openQA answers
# 403 for the steps that never had one. Those replies land as .png files holding
# an Apache error page. Nothing references them, so drop them here rather than
# shipping error pages named like evidence.
discarded=0
while IFS= read -r -d '' image; do
    [[ "$(od -An -tx1 -N8 -- "$image" | tr -d '[:space:]')" == 89504e470d0a1a0a ]] && continue
    rm -f -- "$image"
    discarded=$((discarded + 1))
done < <(find "$destination/testresults" -type f -name '*.png' -print0)

# Every screenshot the details name has to be beside them, otherwise the report
# and the artifact describe evidence nobody can look at. This runs after the
# discard above, so a details-named screenshot that arrived as an error page is
# reported as missing instead of passing as a file.
missing=0
while IFS= read -r screenshot; do
    [[ -s "$destination/testresults/$screenshot" ]] && continue
    echo "Screenshot named by the details is missing: $screenshot" >&2
    missing=$((missing + 1))
done < <(python3 - "$destination/testresults" <<'PY_END'
import json
import sys
from pathlib import Path

for details in sorted(Path(sys.argv[1]).glob("details-*.json")):
    try:
        payload = json.loads(details.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Invalid openQA details file {details}: {error}")
    for detail in payload.get("details", []):
        if isinstance(detail, dict) and isinstance(detail.get("screenshot"), str):
            print(detail["screenshot"])
PY_END
)
((missing == 0)) || {
    echo "Archived result for openQA job $job_id is missing $missing screenshots" >&2
    exit 1
}

printf 'Archived openQA job %s with %s screenshots, %s error pages discarded\n' \
    "$job_id" "$(find "$destination/testresults" -maxdepth 1 -name '*.png' | wc -l)" \
    "$discarded"
