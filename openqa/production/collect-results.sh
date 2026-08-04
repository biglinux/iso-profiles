#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
openqa_cli="$script_dir/openqa-cli.sh"

: "${BIGLINUX_OPENQA_URL:?BIGLINUX_OPENQA_URL is required}"
: "${BIGLINUX_OPENQA_DIAGNOSTICS_DIR:?BIGLINUX_OPENQA_DIAGNOSTICS_DIR is required}"
: "${BIGLINUX_OPENQA_JOB_IDS_FILE:?BIGLINUX_OPENQA_JOB_IDS_FILE is required}"
[[ "$BIGLINUX_OPENQA_URL" =~ ^https://[^[:space:]/]+(/[^[:space:]]*)?$ ]] || {
    echo 'Invalid openQA URL' >&2
    exit 2
}
asset_size_limit=${BIGLINUX_OPENQA_ASSET_SIZE_LIMIT:-1073741824}
archive_size_limit=${BIGLINUX_OPENQA_ARCHIVE_SIZE_LIMIT:-8589934592}
[[ "$asset_size_limit" =~ ^[1-9][0-9]*$ ]] || {
    echo 'BIGLINUX_OPENQA_ASSET_SIZE_LIMIT must be a positive integer' >&2
    exit 2
}
[[ "$archive_size_limit" =~ ^[1-9][0-9]*$ ]] || {
    echo 'BIGLINUX_OPENQA_ARCHIVE_SIZE_LIMIT must be a positive integer' >&2
    exit 2
}

mapfile -t job_ids <"$BIGLINUX_OPENQA_JOB_IDS_FILE"
(( ${#job_ids[@]} > 0 )) || {
    echo 'No openQA job IDs to collect' >&2
    exit 1
}
for job_id in "${job_ids[@]}"; do
    [[ "$job_id" =~ ^[1-9][0-9]*$ ]] || {
        echo 'Invalid openQA job ID' >&2
        exit 2
    }
done

mkdir -p -- "$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/results"
status=0

validate_archive_tree() {
    local result_dir=$1
    local path relative
    while IFS= read -r -d '' path; do
        relative=${path#"$result_dir"/}
        [[ "$relative" != /* && "$relative" != *'..'* ]] || {
            echo "Unsafe path in openQA archive: $relative" >&2
            return 1
        }
        if [[ -L "$path" || (! -f "$path" && ! -d "$path") ]]; then
            echo "Unsupported filesystem object in openQA archive: $relative" >&2
            return 1
        fi
    done < <(find "$result_dir" -xdev -mindepth 1 -print0)

    local total_bytes
    total_bytes=$(du -sb -- "$result_dir" | awk '{print $1}')
    ((total_bytes <= archive_size_limit)) || {
        echo "openQA archive exceeds the configured total size limit" >&2
        return 1
    }
}

for job_id in "${job_ids[@]}"; do
    result_dir="$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/results/$job_id"
    archive_log="$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/archive-$job_id.log"
    mkdir -p -- "$result_dir"
    if ! "$openqa_cli" archive --host "$BIGLINUX_OPENQA_URL" \
        --asset-size-limit "$asset_size_limit" "$job_id" "$result_dir" \
        >"$archive_log" 2>&1; then
        echo "Failed to archive openQA job $job_id" >&2
        status=1
        continue
    fi

    if ! validate_archive_tree "$result_dir"; then
        status=1
        continue
    fi
    [[ -s "$result_dir/testresults/autoinst-log.txt" ]] || {
        echo "Missing autoinst log for openQA job $job_id" >&2
        status=1
    }
    if ! find "$result_dir" -type f \( -name '*.ogv' -o -name '*.webm' \) -size +0c -print -quit | grep -q .; then
        echo "Missing openQA video for job $job_id; verify video configuration" >&2
        status=1
    fi
done

exit "$status"
