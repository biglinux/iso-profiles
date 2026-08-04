#!/usr/bin/env bash
set -euo pipefail

: "${BIGLINUX_OPENQA_RESULTS_DIR:?BIGLINUX_OPENQA_RESULTS_DIR is required}"
: "${BIGLINUX_OPENQA_JOB_IDS_FILE:?BIGLINUX_OPENQA_JOB_IDS_FILE is required}"
mapfile -t job_ids <"$BIGLINUX_OPENQA_JOB_IDS_FILE"
(( ${#job_ids[@]} > 0 )) || { echo 'No openQA jobs to verify' >&2; exit 1; }

for job_id in "${job_ids[@]}"; do
    [[ "$job_id" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid job ID: $job_id" >&2; exit 2; }
    log_file="$BIGLINUX_OPENQA_RESULTS_DIR/$job_id/testresults/autoinst-log.txt"
    [[ -s "$log_file" ]] || { echo "Missing log for job $job_id" >&2; exit 1; }

    kvm_pattern='(^|[[:space:]"=])-enable-kvm($|[[:space:]"=])|(^|[[:space:]"=])-accel[=[:space:]]+kvm($|[[:space:]"=])|(^|[[:space:]"=])accel=kvm($|[[:space:]"=])'
    tcg_pattern='QEMU_NO_KVM=1|-accel[=[:space:]]+tcg|(^|[[:space:]"=])accel=tcg($|[[:space:]"=])|falling back to TCG|TCG fallback'
    kvm_evidence=$(grep -En -- "$kvm_pattern" "$log_file" || true)
    tcg_evidence=$(grep -En -- "$tcg_pattern" "$log_file" || true)
    [[ -n "$kvm_evidence" ]] || {
        echo "Job $job_id has no supported QEMU KVM evidence" >&2
        exit 1
    }
    if [[ -n "$tcg_evidence" ]]; then
        printf '%s\n' "$tcg_evidence" >&2
        echo "Job $job_id contains evidence of QEMU TCG" >&2
        exit 1
    fi
    printf '%s\n' "$kvm_evidence" >"$BIGLINUX_OPENQA_RESULTS_DIR/$job_id/kvm-evidence.txt"
    printf 'KVM evidence for job %s:\n%s\n' "$job_id" "$kvm_evidence"
done
