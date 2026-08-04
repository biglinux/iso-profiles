#!/usr/bin/env bash
set -euo pipefail

die() {
    echo "biglinux-iso-receiver: $*" >&2
    exit 1
}

[[ "${SSH_ORIGINAL_COMMAND-}" == iso-upload ]] || die 'command is not allowed'

iso_dir=${BIGLINUX_RECEIVER_ISO_DIR:-/var/lib/openqa/share/factory/iso}
max_bytes=${BIGLINUX_RECEIVER_MAX_BYTES:-17179869184}
[[ "$iso_dir" = /* && "$iso_dir" != *$'\n'* ]] || die 'invalid ISO directory'
[[ "$max_bytes" =~ ^[1-9][0-9]*$ ]] || die 'invalid maximum size'
[[ -d "$iso_dir" && -w "$iso_dir" ]] || die 'ISO directory is not writable'

IFS=$'\t' read -r filename declared_size declared_sha extra || die 'missing upload header'
[[ -z "${extra:-}" ]] || die 'upload header has extra fields'
[[ "$filename" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.iso$ ]] || die 'invalid ISO filename'
[[ "$filename" != *$'\n'* && "$filename" != *'/'* && "$filename" != *'..'* ]] || die 'unsafe ISO filename'
[[ "$declared_size" =~ ^[1-9][0-9]*$ ]] || die 'invalid ISO size'
((declared_size <= max_bytes)) || die 'ISO exceeds the configured size limit'
[[ "$declared_sha" =~ ^[[:xdigit:]]{64}$ ]] || die 'invalid SHA-256'

lock_dir="$iso_dir/.biglinux-iso-lock.$filename"
mkdir -- "$lock_dir" 2>/dev/null || die 'an upload with this name is already in progress'
temp_file=''
cleanup() {
    if [[ -n "$temp_file" && -e "$temp_file" ]]; then
        unlink -- "$temp_file"
    fi
    if [[ -d "$lock_dir" ]]; then
        rmdir -- "$lock_dir"
    fi
}
trap cleanup EXIT

temp_file=$(mktemp -- "$iso_dir/.biglinux-iso-upload.XXXXXX")
if ! dd if=/dev/stdin of="$temp_file" iflag=fullblock,count_bytes count="$declared_size" status=none; then
    die 'ISO transfer was interrupted'
fi
[[ "$(stat -c '%s' "$temp_file")" == "$declared_size" ]] || die 'ISO size does not match the declared size'

extra_bytes=$(dd if=/dev/stdin bs=1 count=1 status=none 2>/dev/null | wc -c)
extra_bytes=${extra_bytes//[[:space:]]/}
[[ "$extra_bytes" == 0 ]] || die 'extra bytes were received after the ISO'

actual_sha=$(sha256sum "$temp_file" | awk '{print $1}')
[[ "$actual_sha" == "$declared_sha" ]] || die 'SHA-256 does not match the declared value'

destination="$iso_dir/$filename"
if [[ -e "$destination" || -L "$destination" ]]; then
    [[ "$(stat -c '%s' "$destination")" == "$declared_size" ]] || die 'an ISO with this name already exists'
    existing_sha=$(sha256sum "$destination" | awk '{print $1}')
    [[ "$existing_sha" == "$declared_sha" ]] || die 'an ISO with this name has different content'
    unlink -- "$temp_file"
    temp_file=''
    echo "ISO already present with matching SHA-256: $filename"
    exit 0
fi

chmod 0640 -- "$temp_file"
sync -d -- "$temp_file"
ln -- "$temp_file" "$destination" || die 'could not publish ISO atomically'
unlink -- "$temp_file"
temp_file=''
echo "ISO accepted: $filename ($declared_size bytes, SHA-256 $declared_sha)"
