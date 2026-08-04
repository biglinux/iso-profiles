#!/usr/bin/env bash

openqa_production_setup_ssh() {
    : "${BIGLINUX_OPENQA_SSH_HOST:?BIGLINUX_OPENQA_SSH_HOST is required}"
    : "${BIGLINUX_OPENQA_SSH_USER:?BIGLINUX_OPENQA_SSH_USER is required}"
    : "${BIGLINUX_OPENQA_SSH_KEY_FILE:?BIGLINUX_OPENQA_SSH_KEY_FILE is required}"
    : "${BIGLINUX_OPENQA_SSH_KNOWN_HOSTS:?BIGLINUX_OPENQA_SSH_KNOWN_HOSTS is required}"

    local port=${BIGLINUX_OPENQA_SSH_PORT:-22}
    [[ "$BIGLINUX_OPENQA_SSH_HOST" =~ ^[A-Za-z0-9_.:-]+$ ]] || {
        echo 'Invalid BIGLINUX_OPENQA_SSH_HOST' >&2
        return 2
    }
    [[ "$BIGLINUX_OPENQA_SSH_USER" =~ ^[A-Za-z0-9_.-]+$ ]] || {
        echo 'Invalid BIGLINUX_OPENQA_SSH_USER' >&2
        return 2
    }
    if [[ ! "$port" =~ ^[1-9][0-9]{0,4}$ ]] || ((port > 65535)); then
        echo 'Invalid BIGLINUX_OPENQA_SSH_PORT' >&2
        return 2
    fi
    [[ -f "$BIGLINUX_OPENQA_SSH_KEY_FILE" ]] || {
        echo 'SSH private key file is missing' >&2
        return 2
    }
    [[ -f "$BIGLINUX_OPENQA_SSH_KNOWN_HOSTS" ]] || {
        echo 'SSH known_hosts file is missing' >&2
        return 2
    }
    local key_mode
    key_mode=$(stat -c '%a' "$BIGLINUX_OPENQA_SSH_KEY_FILE")
    ((10#$key_mode <= 600)) || {
        echo 'SSH private key file is readable by group or others' >&2
        return 2
    }

    OPENQA_PRODUCTION_SSH=(
        ssh -T
        -p "$port"
        -i "$BIGLINUX_OPENQA_SSH_KEY_FILE"
        -o BatchMode=yes
        -o IdentitiesOnly=yes
        -o StrictHostKeyChecking=yes
        -o UserKnownHostsFile="$BIGLINUX_OPENQA_SSH_KNOWN_HOSTS"
        "$BIGLINUX_OPENQA_SSH_USER@$BIGLINUX_OPENQA_SSH_HOST"
    )
}

openqa_production_ssh_command() {
    local command arg quoted
    command=''
    for arg in "$@"; do
        printf -v quoted '%q' "$arg"
        command+="${command:+ }$quoted"
    done
    "${OPENQA_PRODUCTION_SSH[@]}" "$command"
}

openqa_production_ssh_stdin() {
    local input=$1
    shift
    local command arg quoted
    command=''
    for arg in "$@"; do
        printf -v quoted '%q' "$arg"
        command+="${command:+ }$quoted"
    done
    printf '%s' "$input" | "${OPENQA_PRODUCTION_SSH[@]}" "$command"
}
