#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' \
    'Starting the ephemeral BigLinux openQA instance.'

if [[ "${OPENQA_MCP_ENABLED:-0}" == 1 ]]; then
    printf '%s\n' \
        'APACHE_CONF_INCLUDE_FILES="/etc/apache2/vhosts.d/openqa-mcp-forwarded-proto.conf"' \
        >> /etc/sysconfig/apache2
fi

groupmod --gid "$KVM_GID" --non-unique kvm
usermod --append --groups kvm _openqa-worker
export skip_suse_specifics=1
export skip_suse_tests=1
exec /usr/share/openqa/script/openqa-bootstrap
