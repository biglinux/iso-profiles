#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: start-gate-local.sh [--firmware bios|uefi] /absolute/path/to/biglinux.iso

Starts the same ephemeral openQA instance the release workflow starts, on this
machine, so a release plan can be scheduled with schedule-release-gate.sh.

Unlike start-mcp.sh, which exists to let an agent read job results through MCP,
this instance carries what the release gate needs: the test password, the
worker class the scheduled job asks for, a writable results directory the host
can read, and the OVMF pair for UEFI plans.

The script prints the environment schedule-release-gate.sh expects and also
writes it to <state dir>/gate-env.sh, ready to be sourced.

Options:
  --firmware bios|uefi   prepare the OVMF pair for a UEFI plan (default: bios)
  --state-dir DIR        where password, worker config, OVMF and results live
                         (default: $HOME/.cache/biglinux-openqa-gate)
EOF
}

firmware=bios
state_dir=${BIGLINUX_GATE_STATE_DIR:-$HOME/.cache/biglinux-openqa-gate}
while (($# > 0)); do
    case "$1" in
        --firmware)
            (($# >= 2)) || { usage >&2; exit 2; }
            firmware=$2
            shift 2
            ;;
        --state-dir)
            (($# >= 2)) || { usage >&2; exit 2; }
            state_dir=$2
            shift 2
            ;;
        --help | -h)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done

if (($# != 1)); then
    usage >&2
    exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "$script_dir/../.." && pwd -P)
image_file="$repo_root/openqa/openqa-image.txt"

die() {
    echo "start-gate-local.sh: $*" >&2
    exit 1
}

[[ "$firmware" == bios || "$firmware" == uefi ]] || die 'firmware must be bios or uefi'
[[ -e "$1" ]] || die "ISO does not exist: $1"
iso_path=$(realpath -- "$1") || die "could not resolve ISO path: $1"
iso_name=$(basename -- "$iso_path")
iso_dir=$(dirname -- "$iso_path")
[[ -f "$iso_path" && -r "$iso_path" ]] || die "ISO is not a readable regular file: $iso_path"
[[ "$iso_name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.iso$ ]] \
    || die "ISO filename contains unsupported characters: $iso_name"

openqa_image=$(tr -d '[:space:]' < "$image_file")
[[ "$openqa_image" =~ ^registry\.opensuse\.org/.+:[^@[:space:]]+@sha256:[[:xdigit:]]{64}$ ]] \
    || die "openQA image must include a version tag and registry digest: $image_file"
[[ "$openqa_image" != *:latest@sha256:* ]] \
    || die 'openQA image must not use the mutable latest tag'

command -v docker >/dev/null || die 'docker is required'
command -v curl >/dev/null || die 'curl is required'
command -v jq >/dev/null || die 'jq is required'
[[ -c /dev/kvm ]] || die '/dev/kvm is required: the gate never accepts TCG'
[[ -r /dev/kvm && -w /dev/kvm ]] || die '/dev/kvm is not readable and writable by this user'

# QEMU/KVM and VirtualBox cannot hold the virtualisation extensions at the same
# time; the worker would start and every job would fail deep inside the backend.
if command -v VBoxManage >/dev/null 2>&1; then
    running_virtualbox_vms=$(VBoxManage list runningvms 2>/dev/null || true)
    [[ -z "${running_virtualbox_vms//[[:space:]]/}" ]] \
        || die 'a VirtualBox VM is running; stop it before starting the QEMU/KVM openQA worker'
fi
if pgrep -x VirtualBoxVM >/dev/null 2>&1 || pgrep -x VBoxHeadless >/dev/null 2>&1; then
    die 'a VirtualBox process is running; stop it before starting the QEMU/KVM openQA worker'
fi

container_name=${BIGLINUX_OPENQA_CONTAINER:-biglinux-openqa-gate}
http_port=${BIGLINUX_OPENQA_HTTP_PORT:-1080}
[[ "$container_name" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'invalid BIGLINUX_OPENQA_CONTAINER'
valid_port() {
    [[ "$1" =~ ^[0-9]+$ ]] || return 1
    ((10#$1 >= 1024 && 10#$1 <= 65535))
}
valid_port "$http_port" || die 'BIGLINUX_OPENQA_HTTP_PORT must be between 1024 and 65535'
docker container inspect "$container_name" >/dev/null 2>&1 \
    && die "container already exists: $container_name"

umask 077
mkdir -p -- "$state_dir/results" "$state_dir/ovmf" "$state_dir/diagnostics"
password_file="$state_dir/test-password"
worker_config="$state_dir/worker.ini"
openssl rand -hex 18 | tr -d '\n' >"$password_file"
chmod 0600 -- "$password_file"

# The scheduled job asks for WORKER_CLASS=biglinux-kvm. A worker without that
# class leaves the job scheduled until the monitor times out hours later.
printf '[global]\nHOST = http://localhost\nBACKEND = qemu\nWORKER_CLASS = biglinux-kvm\n' \
    >"$worker_config"
chmod 0644 -- "$worker_config"
# The umask above keeps the state directory private, which is right for the
# password but wrong for the two directories the container has to reach as
# _openqa-worker: it cannot even traverse a 0700 directory. The OVMF pair is
# public firmware, and the results directory holds no secret.
chmod 0755 -- "$state_dir/results" "$state_dir/ovmf"

uefi_code=
uefi_vars=
if [[ "$firmware" == uefi ]]; then
    # A UEFI plan needs a non-Secure-Boot pair. The names differ per
    # distribution, so try the known ones instead of hard-coding one path.
    for pair in \
        /usr/share/edk2/x64/OVMF_CODE.4m.fd:/usr/share/edk2/x64/OVMF_VARS.4m.fd \
        /usr/share/edk2/x64/OVMF_CODE.fd:/usr/share/edk2/x64/OVMF_VARS.fd \
        /usr/share/OVMF/OVMF_CODE_4M.fd:/usr/share/OVMF/OVMF_VARS_4M.fd \
        /usr/share/OVMF/OVMF_CODE.fd:/usr/share/OVMF/OVMF_VARS.fd; do
        candidate_code=${pair%%:*}
        candidate_vars=${pair#*:}
        if [[ -s "$candidate_code" && -s "$candidate_vars" ]]; then
            uefi_code=$candidate_code
            uefi_vars=$candidate_vars
            break
        fi
    done
    [[ -n "$uefi_code" && -n "$uefi_vars" ]] \
        || die 'no non-Secure-Boot OVMF code/vars pair was found; install edk2-ovmf'
    cp -- "$uefi_code" "$state_dir/ovmf/OVMF_CODE.fd"
    cp -- "$uefi_vars" "$state_dir/ovmf/OVMF_VARS.fd"
    chmod 0444 -- "$state_dir/ovmf/OVMF_CODE.fd"
    # os-autoinst writes the variable store while the guest runs, and it does
    # so as _openqa-worker rather than as the invoking user.
    chmod 0666 -- "$state_dir/ovmf/OVMF_VARS.fd"
fi

kvm_gid=$(stat --format '%g' /dev/kvm)
startup_complete=0
cleanup_on_failure() {
    if ((startup_complete == 0)); then
        docker logs "$container_name" >&2 2>/dev/null || true
        docker stop "$container_name" >/dev/null 2>&1 || true
        docker rm -f "$container_name" >/dev/null 2>&1 || true
    fi
}
trap cleanup_on_failure EXIT

# Mirrors the container the release workflow starts, including the four mounts
# schedule-release-gate.sh depends on.
docker run --detach \
    --name "$container_name" \
    --publish "127.0.0.1:${http_port}:80" \
    --tmpfs /srv/www/htdocs:mode=0755 \
    --tmpfs /var/log/apache2:mode=0755 \
    --volume "$repo_root:/workspace-source:ro" \
    --volume "$iso_dir:/var/lib/openqa/share/factory/iso:ro" \
    --volume "$state_dir/results:/var/lib/openqa/biglinux-results:rw" \
    --volume "$password_file:/run/secrets/biglinux-test-password:ro" \
    --volume "$worker_config:/etc/openqa/workers.ini.d/99-biglinux.ini:ro" \
    --volume "$state_dir/ovmf:/run/ovmf:rw" \
    --device /dev/kvm \
    --env "KVM_GID=$kvm_gid" \
    --env OPENQA_MCP_ENABLED=0 \
    --entrypoint /bin/bash \
    "$openqa_image" \
    /workspace-source/openqa/development/start-container.sh >/dev/null

# Readiness means all three: the API answers, the scheduler runs, and exactly
# one worker carries the class the job will ask for.
for attempt in {1..180}; do
    api_ready=0
    worker_ready=0
    scheduler_ready=0
    if curl --fail --silent --show-error \
        "http://127.0.0.1:${http_port}/api/v1/jobs" >/dev/null; then
        api_ready=1
    fi
    if curl --fail --silent --show-error \
        "http://127.0.0.1:${http_port}/api/v1/workers" >"$state_dir/workers.json" \
        && jq -e '[.workers[]? | select(.status == "idle" or .status == "running")
                  | select((.properties.WORKER_CLASS // "") | contains("biglinux-kvm"))]
                  | length == 1' "$state_dir/workers.json" >/dev/null \
        && docker exec "$container_name" su _openqa-worker -c \
            'test -r /dev/kvm -a -w /dev/kvm'; then
        worker_ready=1
    fi
    if docker exec "$container_name" pgrep -f openqa-scheduler-daemon >/dev/null 2>&1; then
        scheduler_ready=1
    fi
    ((api_ready && worker_ready && scheduler_ready)) && break
    if [[ "$(docker inspect --format '{{.State.Running}}' "$container_name" 2>/dev/null)" != true ]]; then
        die 'the openQA container stopped before becoming ready'
    fi
    ((attempt == 180)) && die 'the openQA API, scheduler, and worker were not ready within 15 minutes'
    sleep 5
done

iso_sha256=$(sha256sum -- "$iso_path" | awk '{print $1}')
env_file="$state_dir/gate-env.sh"
{
    printf '# Generated by start-gate-local.sh; source before schedule-release-gate.sh\n'
    printf 'export BIGLINUX_OPENQA_CONTAINER=%q\n' "$container_name"
    printf 'export BIGLINUX_ISO_FILENAME=%q\n' "$iso_name"
    printf 'export BIGLINUX_ISO_SHA256=%q\n' "$iso_sha256"
    printf 'export BIGLINUX_OPENQA_BUILD=%q\n' "local-$(date -u +%Y%m%dT%H%M%SZ)"
    printf 'export BIGLINUX_TEST_PASSWORD_FILE=%q\n' "$password_file"
    printf 'export BIGLINUX_OPENQA_DIAGNOSTICS_DIR=%q\n' "$state_dir/diagnostics"
    printf 'export BIGLINUX_OPENQA_RESULTS_MOUNT=%q\n' '/var/lib/openqa/biglinux-results'
    if [[ "$firmware" == uefi ]]; then
        printf 'export BIGLINUX_OPENQA_UEFI_PFLASH_CODE=%q\n' /run/ovmf/OVMF_CODE.fd
        printf 'export BIGLINUX_OPENQA_UEFI_PFLASH_VARS=%q\n' /run/ovmf/OVMF_VARS.fd
    fi
} >"$env_file"
chmod 0600 -- "$env_file"

startup_complete=1
trap - EXIT

cat <<EOF
openQA gate instance is ready.
Web UI:    http://127.0.0.1:${http_port}/
Container: ${container_name}
ISO:       ${iso_path}
Firmware:  ${firmware}
State:     ${state_dir}

Schedule a plan with:
  source ${env_file}
  ./openqa/development/schedule-release-gate.sh --firmware ${firmware}

Stop it with:
  docker rm -f ${container_name}
EOF
