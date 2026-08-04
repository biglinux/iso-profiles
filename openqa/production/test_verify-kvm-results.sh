#!/usr/bin/env bash
set -euo pipefail

run_case() {
    local name=$1 expected=$2 log_line=$3 root status
    root=$(mktemp -d)
    mkdir -p -- "$root/results/1/testresults"
    printf '%s\n' "$log_line" >"$root/results/1/testresults/autoinst-log.txt"
    printf '1\n' >"$root/job-ids.txt"
    set +e
    BIGLINUX_OPENQA_RESULTS_DIR="$root/results" \
        BIGLINUX_OPENQA_JOB_IDS_FILE="$root/job-ids.txt" \
        ./openqa/production/verify-kvm-results.sh >"$root/output.txt" 2>&1
    status=$?
    set -e
    if [[ "$expected" == pass && "$status" -ne 0 ]]; then
        printf 'KVM fixture %s failed unexpectedly:\n' "$name" >&2
        cat "$root/output.txt" >&2
        exit 1
    fi
    if [[ "$expected" == fail && "$status" -eq 0 ]]; then
        printf 'KVM fixture %s was accepted unexpectedly\n' "$name" >&2
        exit 1
    fi
    for path in \
        "$root/results/1/testresults/autoinst-log.txt" \
        "$root/job-ids.txt" \
        "$root/output.txt" \
        "$root/results/1/kvm-evidence.txt"; do
        if [[ -e "$path" ]]; then
            unlink -- "$path"
        fi
    done
    rmdir -- "$root/results/1/testresults" "$root/results/1" "$root/results" "$root"
}

run_case enable-kvm pass 'starting qemu -enable-kvm -m 4096'
run_case accel-kvm pass 'starting qemu -accel kvm -m 4096'
run_case accel-equals-kvm pass 'starting qemu -accel=kvm -m 4096'
run_case tcg fail 'starting qemu -accel tcg -m 4096'
run_case no-evidence fail 'starting qemu -m 4096'
run_case contradictory fail 'starting qemu -enable-kvm -accel=tcg -m 4096'

printf '%s\n' 'KVM verifier fixtures passed.'
