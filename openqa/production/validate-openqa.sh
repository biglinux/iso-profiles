#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=./openqa/production/ssh-common.sh
source "$script_dir/ssh-common.sh"

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

openqa_production_setup_ssh
remote_check=$(cat <<'REMOTE'
set -euo pipefail
url=$1
group=$2
worker_class=$3
iso_dir=$4

command -v openqa-cli >/dev/null || { echo 'openqa-cli is missing on the persistent server' >&2; exit 1; }
command -v jq >/dev/null || { echo 'jq is missing on the persistent server' >&2; exit 1; }
systemctl is-active --quiet openqa-webui || { echo 'openqa-webui is not active' >&2; exit 1; }
systemctl is-active --quiet openqa-scheduler || { echo 'openqa-scheduler is not active' >&2; exit 1; }
timedatectl show --property=NTPSynchronized --value | grep -qx yes \
    || { echo 'NTP is not synchronized on the persistent server' >&2; exit 1; }
test -d "$iso_dir" -a -w "$iso_dir" \
    || { echo 'openQA ISO asset directory is not writable' >&2; exit 1; }
df -h "$iso_dir"

workers=$(openqa-cli --host "$url" api workers)
jq -e --arg worker_class "$worker_class" '
    ([.workers[] | select(.status == "idle" or .status == "running")
      | select((.properties.WORKER_CLASS // "") | split(",") | index($worker_class))] | length) >= 2
' <<<"$workers" >/dev/null \
    || { echo "fewer than two healthy workers in class $worker_class" >&2; exit 1; }

groups=$(openqa-cli --host "$url" api groups)
jq -e --arg group "$group" '[.groups[] | select(.name == $group)] | length == 1' <<<"$groups" >/dev/null \
    || { echo "openQA group does not exist: $group" >&2; exit 1; }

if [[ -r /dev/kvm && -w /dev/kvm ]]; then
    echo 'KVM device is readable and writable on the openQA server host'
else
    echo 'KVM is provided by separate worker hosts; final job archives must prove -enable-kvm' >&2
fi
echo 'Persistent openQA web, scheduler, time sync, group and worker class are ready'
REMOTE
)
openqa_production_ssh_stdin "$remote_check" bash -s -- \
    "$BIGLINUX_OPENQA_URL" \
    "$BIGLINUX_OPENQA_GROUP" \
    "$BIGLINUX_OPENQA_WORKER_CLASS" \
    "$BIGLINUX_OPENQA_REMOTE_ISO_DIR"
