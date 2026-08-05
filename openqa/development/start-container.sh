#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' \
    'Starting the ephemeral BigLinux openQA instance.'

if [[ "${OPENQA_MCP_ENABLED:-0}" == 1 ]]; then
    printf '%s\n' \
        'APACHE_CONF_INCLUDE_FILES="/etc/apache2/vhosts.d/openqa-mcp-forwarded-proto.conf"' \
        >> /etc/sysconfig/apache2
fi

# The bootstrap unconditionally refreshes the openSUSE repositories and
# installs QEMU plus the openQA packages, with no switch to skip it. Every one
# of those packages is already in this image, which is pinned by digest, so the
# step buys nothing and makes a release gate depend on a mirror being
# reachable: one run lost four of its six jobs to stale repository metadata,
# retrying for twenty minutes while the worker never appeared. Replace the
# network repositories with an empty local one, which refreshes offline, and
# installing what is already installed is a no-op. A future image that really
# lacks a package still fails loudly, naming it.
install -d -m 0755 /var/lib/openqa-offline-repo
zypper --non-interactive removerepo --all >/dev/null 2>&1 || true
zypper --non-interactive addrepo --type plaindir \
	/var/lib/openqa-offline-repo openqa-offline

groupmod --gid "$KVM_GID" --non-unique kvm
usermod --append --groups kvm _openqa-worker
if [[ -d /workspace-source ]]; then
    install -d -m 0755 /workspace
    cp -a /workspace-source/. /workspace/
    chown -R _openqa-worker:_openqa-worker /workspace
fi
export skip_suse_specifics=1
export skip_suse_tests=1
exec /usr/share/openqa/script/openqa-bootstrap
