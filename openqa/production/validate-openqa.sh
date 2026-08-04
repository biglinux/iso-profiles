#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
openqa_cli="$script_dir/openqa-cli.sh"

: "${BIGLINUX_OPENQA_URL:?BIGLINUX_OPENQA_URL is required}"
: "${BIGLINUX_OPENQA_GROUP:?BIGLINUX_OPENQA_GROUP is required}"
: "${BIGLINUX_OPENQA_WORKER_CLASS:?BIGLINUX_OPENQA_WORKER_CLASS is required}"
: "${BIGLINUX_OPENQA_REMOTE_ISO_DIR:?BIGLINUX_OPENQA_REMOTE_ISO_DIR is required}"
[[ "$BIGLINUX_OPENQA_URL" =~ ^https://[^[:space:]/]+(/[^[:space:]]*)?$ ]] || {
    echo 'BIGLINUX_OPENQA_URL must be an HTTPS URL' >&2
    exit 2
}
[[ "$BIGLINUX_OPENQA_GROUP" =~ ^[A-Za-z0-9_.-]+$ ]] || {
    echo 'Invalid BIGLINUX_OPENQA_GROUP' >&2
    exit 2
}
[[ "$BIGLINUX_OPENQA_WORKER_CLASS" =~ ^[A-Za-z0-9_.:-]+$ ]] || {
    echo 'Invalid BIGLINUX_OPENQA_WORKER_CLASS' >&2
    exit 2
}
[[ "$BIGLINUX_OPENQA_REMOTE_ISO_DIR" = /* && "$BIGLINUX_OPENQA_REMOTE_ISO_DIR" != *$'\n'* ]] || {
    echo 'Invalid BIGLINUX_OPENQA_REMOTE_ISO_DIR' >&2
    exit 2
}
command -v jq >/dev/null 2>&1 || {
    echo 'jq is required on the GitHub runner for openQA API validation' >&2
    exit 127
}

printf 'openQA client: '
"$openqa_cli" --version

workers_json=$( "$openqa_cli" api --host "$BIGLINUX_OPENQA_URL" workers )
jq -e 'type == "object" and (.workers | type == "array")' <<<"$workers_json" >/dev/null || {
    echo 'openQA workers response is not valid JSON' >&2
    exit 1
}

healthy_workers=$(
    jq -r --arg worker_class "$BIGLINUX_OPENQA_WORKER_CLASS" '
        [.workers[]?
         | select(.status == "idle" or .status == "running")
         | select(
             ((.properties.WORKER_CLASS // "")
              | tostring
              | split(",")
              | map(gsub("^\\s+|\\s+$"; ""))
              | index($worker_class)) != null
           )]
        | length
    ' <<<"$workers_json"
)
((healthy_workers >= 2)) || {
    echo "fewer than two healthy workers in class $BIGLINUX_OPENQA_WORKER_CLASS" >&2
    jq -r '.workers[]? | [.id, .host, .status, (.properties.WORKER_CLASS // "unknown")] | @tsv' \
        <<<"$workers_json" >&2
    exit 1
}

printf 'Healthy workers in class %s: %s\n' "$BIGLINUX_OPENQA_WORKER_CLASS" "$healthy_workers"
jq -r --arg worker_class "$BIGLINUX_OPENQA_WORKER_CLASS" '
    .workers[]?
    | select(.status == "idle" or .status == "running")
    | select(
        ((.properties.WORKER_CLASS // "")
         | tostring
         | split(",")
         | map(gsub("^\\s+|\\s+$"; ""))
         | index($worker_class)) != null
      )
    | ["worker=" + (.id | tostring), "host=" + (.host // "unknown"), "status=" + .status]
    | join(" ")
' <<<"$workers_json"

groups_json=$( "$openqa_cli" api --host "$BIGLINUX_OPENQA_URL" groups )
jq -e --arg group "$BIGLINUX_OPENQA_GROUP" '
    type == "object"
    and ([.groups[]? | select(.name == $group)] | length == 1)
' <<<"$groups_json" >/dev/null || {
    echo "openQA group does not exist: $BIGLINUX_OPENQA_GROUP" >&2
    exit 1
}

printf 'openQA API, group, and worker capacity are ready\n'
