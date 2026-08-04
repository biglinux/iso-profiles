#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=./openqa/production/ssh-common.sh
source "$script_dir/ssh-common.sh"

iso_file=${1:-}
[[ -n "$iso_file" ]] || { echo 'Usage: upload-iso.sh ISO' >&2; exit 2; }
[[ "$iso_file" != *$'\n'* && "$iso_file" != */* ]] || {
    echo 'ISO must be a regular file name, not a path' >&2
    exit 2
}
[[ "$iso_file" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.iso$ ]] || {
    echo 'ISO filename is unsafe' >&2
    exit 2
}
[[ -f "$iso_file" && -r "$iso_file" ]] || {
    echo 'ISO file is not readable' >&2
    exit 2
}

openqa_production_setup_ssh
iso_size=$(stat -c '%s' "$iso_file")
iso_sha=$(sha256sum "$iso_file" | awk '{print $1}')
printf 'Uploading %s (%s bytes, SHA-256 %s)\n' "$iso_file" "$iso_size" "$iso_sha"
{
    printf '%s\t%s\t%s\n' "$iso_file" "$iso_size" "$iso_sha"
    cat -- "$iso_file"
} | openqa_production_ssh_command iso-upload
