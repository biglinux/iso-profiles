#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=./openqa/production/ssh-common.sh
source "$script_dir/ssh-common.sh"

: "${BIGLINUX_OPENQA_URL:?BIGLINUX_OPENQA_URL is required}"
: "${BIGLINUX_OPENQA_DIAGNOSTICS_DIR:?BIGLINUX_OPENQA_DIAGNOSTICS_DIR is required}"
: "${BIGLINUX_OPENQA_JOB_IDS_FILE:?BIGLINUX_OPENQA_JOB_IDS_FILE is required}"
[[ "$BIGLINUX_OPENQA_URL" =~ ^https://[^[:space:]/]+(/[^[:space:]]*)?$ ]] || {
    echo 'Invalid openQA URL' >&2
    exit 2
}

mapfile -t job_ids <"$BIGLINUX_OPENQA_JOB_IDS_FILE"
(( ${#job_ids[@]} > 0 )) || { echo 'No openQA job IDs to collect' >&2; exit 1; }
for job_id in "${job_ids[@]}"; do
    [[ "$job_id" =~ ^[1-9][0-9]*$ ]] || { echo 'Invalid openQA job ID' >&2; exit 2; }
done

mkdir -p -- "$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/results"
openqa_production_setup_ssh
remote_archive=$(cat <<'REMOTE'
set -euo pipefail
url=$1
shift
archive_root=$(mktemp -d /tmp/biglinux-openqa-archive.XXXXXX)
cleanup() {
    rm -rf -- "$archive_root"
}
trap cleanup EXIT
for job_id in "$@"; do
    openqa-cli --host "$url" archive "$job_id" "$archive_root/$job_id"
done
tar --create --gzip --directory "$archive_root" --owner=0 --group=0 --numeric-owner .
REMOTE
)

archive_file="$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/results.tar.gz"
openqa_production_ssh_stdin "$remote_archive" bash -s -- \
    "$BIGLINUX_OPENQA_URL" "${job_ids[@]}" >"$archive_file"
while IFS= read -r member; do
    [[ "$member" =~ ^\./[1-9][0-9]*(/|$) ]] || {
        echo "Unsafe openQA archive member: $member" >&2
        exit 1
    }
    [[ "$member" != *'..'* ]] || {
        echo "Traversal in openQA archive member: $member" >&2
        exit 1
    }
done < <(tar --list --gzip --file "$archive_file")
tar --extract --gzip --file "$archive_file" --directory "$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/results" \
    --no-same-owner --no-overwrite-dir
unlink -- "$archive_file"

for job_id in "${job_ids[@]}"; do
    result_dir="$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/results/$job_id"
    [[ -d "$result_dir" ]] || { echo "Missing archive for openQA job $job_id" >&2; exit 1; }
    [[ -s "$result_dir/autoinst-log.txt" ]] || { echo "Missing autoinst log for openQA job $job_id" >&2; exit 1; }
    find "$result_dir" -type f -name '*.ogv' -size +0c -print -quit | grep -q . \
        || { echo "Missing openQA video for job $job_id" >&2; exit 1; }
done
