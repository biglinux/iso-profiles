#!/usr/bin/env bash
set -euo pipefail

: "${BIGLINUX_OPENQA_RESULTS_DIR:?BIGLINUX_OPENQA_RESULTS_DIR is required}"
: "${BIGLINUX_OPENQA_JOB_IDS_FILE:?BIGLINUX_OPENQA_JOB_IDS_FILE is required}"
mapfile -t job_ids <"$BIGLINUX_OPENQA_JOB_IDS_FILE"
(( ${#job_ids[@]} > 0 )) || { echo 'No openQA jobs to verify' >&2; exit 1; }

for job_id in "${job_ids[@]}"; do
    [[ "$job_id" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid job ID: $job_id" >&2; exit 2; }
    log_file="$BIGLINUX_OPENQA_RESULTS_DIR/$job_id/autoinst-log.txt"
    [[ -s "$log_file" ]] || { echo "Missing log for job $job_id" >&2; exit 1; }
    rg -q -- '-enable-kvm' "$log_file" || {
        echo "Job $job_id has no QEMU -enable-kvm evidence" >&2
        exit 1
    }
    if rg -n -- 'QEMU_NO_KVM=1|-accel[= ]tcg|accel=tcg|falling back to TCG' "$log_file"; then
        echo "Job $job_id contains evidence of QEMU TCG" >&2
        exit 1
    fi
    printf 'KVM evidence: job %s contains -enable-kvm and no TCG fallback\n' "$job_id"
done
