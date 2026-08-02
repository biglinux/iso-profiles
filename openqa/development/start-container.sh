#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' \
    'APACHE_CONF_INCLUDE_FILES="/etc/apache2/vhosts.d/openqa-mcp-forwarded-proto.conf"' \
    >> /etc/sysconfig/apache2

groupmod --gid "$KVM_GID" --non-unique kvm
usermod --append --groups kvm _openqa-worker
exec /usr/share/openqa/script/openqa-bootstrap
