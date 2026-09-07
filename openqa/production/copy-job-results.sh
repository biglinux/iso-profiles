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

# Through the container, not from here: openQA archives into the mounted
# results directory as root, so a previous run leaves files this user
# cannot delete. On a GitHub runner that failed the whole collection step
# for a job whose plan had passed.
purge_in_container() {
    "$docker_bin" exec "$container" find "$results_mount/$job_id" \
        -mindepth 1 -delete 2>/dev/null || true
}
purge_in_container
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
    "$docker_bin" exec "$container" \
        rm -f -- "$results_mount/$job_id/${image#"$destination/"}"
    discarded=$((discarded + 1))
done < <(find "$destination/testresults" -type f -name '*.png' -print0)

# A screenshot that a step *compared* is evidence: the report shows the match
# areas over it, and without the file nobody can check the comparison. Those
# have to be here. A step that only recorded the screen is different - openQA
# answers 403 for many of them, and the archive client stores the error page
# under the name it asked for. The applications module records over a thousand
# such steps, so failing on them would fail every release for evidence openQA
# never offered. This runs after the discard above, so an error page counts as
# missing rather than passing as a file.
missing=0
unserved=0
while IFS= read -r line; do
    screenshot=${line#* }
    [[ -s "$destination/testresults/$screenshot" ]] && continue
    if [[ "$line" == compared\ * ]]; then
        echo "Screenshot compared by a step is missing: $screenshot" >&2
        missing=$((missing + 1))
    else
        unserved=$((unserved + 1))
    fi
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
        if not isinstance(detail, dict):
            continue
        screenshot = detail.get("screenshot")
        if not isinstance(screenshot, str):
            continue
        # "area" is present when the step compared the screen against a needle.
        kind = "compared" if detail.get("area") else "recorded"
        print(f"{kind} {screenshot}")
PY_END
)
((missing == 0)) || {
    echo "Archived result for openQA job $job_id is missing $missing compared screenshots" >&2
    exit 1
}

printf 'Archived openQA job %s with %s screenshots, %s error pages discarded, %s recorded screenshots openQA did not serve\n' \
    "$job_id" "$(find "$destination/testresults" -maxdepth 1 -name '*.png' | wc -l)" \
    "$discarded" "$unserved"
