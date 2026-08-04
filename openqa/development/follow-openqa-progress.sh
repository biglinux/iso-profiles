#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: follow-openqa-progress.sh CONTAINER SCHEDULER_PID

Prints application progress recorded by openQA while SCHEDULER_PID is running.
The output is intentionally plain text so it remains visible in GitHub Actions.
EOF
}

(( $# == 2 )) || { usage >&2; exit 2; }
container_name=$1
scheduler_pid=$2

[[ "$container_name" =~ ^[A-Za-z0-9_.-]+$ ]] || {
    echo 'follow-openqa-progress.sh: invalid container name' >&2
    exit 2
}
[[ "$scheduler_pid" =~ ^[1-9][0-9]*$ ]] || {
    echo 'follow-openqa-progress.sh: invalid scheduler PID' >&2
    exit 2
}

declare -A log_offsets=()

clean_message() {
    local message=$1
    message=${message//\\r/ }
    message=${message//\\n/ }
    message=$(printf '%s' "$message" | tr -cd '\11\15\40-\176' | tr '\r' ' ')
    printf '%s' "${message:0:240}"
}

emit_record() {
    local line=$1
    local title output message
    [[ "$line" == *'record_info(title="'* ]] || return 0

    title=$(sed -n 's/.*record_info(title="\([^"]*\)", output=".*/\1/p' <<<"$line")
    output=$(sed -n 's/.*record_info(title="[^"]*", output="\([^"]*\)".*/\1/p' <<<"$line")
    [[ -n "$title" ]] || return 0
    case "$title" in
        *' / starting'|*' / launched'|*' / started'|*' / opened'|*' / cleaning'|*' / cleanup'|*' / passed'|*' / failed')
            ;;
        *)
            return 0
            ;;
    esac

    message=$(clean_message "$output")
    if [[ -n "$message" ]]; then
        printf 'openQA: %s — %s\n' "$title" "$message"
    else
        printf 'openQA: %s\n' "$title"
    fi
}

read_log_updates() {
    local path current_lines offset line new_lines
    local paths
    paths=$(docker exec "$container_name" find /var/lib/openqa/pool \
        -type f -name autoinst-log.txt -print 2>/dev/null || true)
    while IFS= read -r path; do
        [[ -n "$path" ]] || continue
        [[ "$path" == /var/lib/openqa/pool/*/autoinst-log.txt ]] || continue

        current_lines=$(docker exec "$container_name" sh -c 'wc -l < "$1"' sh "$path" 2>/dev/null || true)
        [[ "$current_lines" =~ ^[0-9]+$ ]] || continue
        offset=${log_offsets[$path]:-1}
        if (( current_lines + 1 < offset )); then
            offset=1
        fi
        if (( offset <= current_lines )); then
            new_lines=$(docker exec "$container_name" sed -n "${offset},\$p" "$path" 2>/dev/null || true)
            while IFS= read -r line || [[ -n "$line" ]]; do
                emit_record "$line"
            done <<<"$new_lines"
        fi
        log_offsets[$path]=$((current_lines + 1))
    done <<<"$paths"
}

echo "openQA: progress monitor attached to $container_name (scheduler PID $scheduler_pid)"
while kill -0 "$scheduler_pid" 2>/dev/null; do
    read_log_updates
    sleep 2
done

# Drain records written just before the scheduler exited.
read_log_updates
exit 0
