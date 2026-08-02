#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: start-mcp.sh [--write-repo] /absolute/path/to/biglinux.iso

Starts a loopback-only, development openQA instance with read-only MCP.
The repository is mounted read-only unless --write-repo is supplied.
EOF
}

write_repo=0
while (($# > 0)); do
    case "$1" in
        --write-repo)
            write_repo=1
            shift
            ;;
        --help|-h)
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
mcp_config="$script_dir/50-mcp-read-only.ini"

die() {
    echo "start-mcp.sh: $*" >&2
    exit 1
}

[[ -e "$1" ]] || die "ISO does not exist: $1"
iso_path=$(realpath -- "$1") || die "could not resolve ISO path: $1"
iso_name=$(basename -- "$iso_path")
iso_dir=$(dirname -- "$iso_path")
openqa_image=$(tr -d '[:space:]' < "$image_file")

[[ -f "$iso_path" && -r "$iso_path" ]] || die "ISO is not a readable regular file: $iso_path"
[[ "$iso_name" =~ ^[A-Za-z0-9._-]+$ ]] || die "ISO filename contains unsupported characters: $iso_name"
[[ "$openqa_image" =~ ^registry\.opensuse\.org/.+@sha256:[[:xdigit:]]{64}$ ]] \
    || die "openQA image is not pinned by a registry digest: $image_file"
command -v docker >/dev/null || die 'docker is required'
command -v curl >/dev/null || die 'curl is required'
[[ -c /dev/kvm ]] || die '/dev/kvm is required for the graphical worker'

base_digest=${openqa_image##*@sha256:}
[[ "$base_digest" != "$openqa_image" ]] || die 'openQA image must use a sha256 digest'
mcp_image="biglinux-openqa-dev-mcp:sha256-${base_digest}"
mcp_version=$(docker run --rm --entrypoint /bin/sh "$openqa_image" \
    -c 'rpm -q --qf "%{VERSION}-%{RELEASE}" openQA') \
    || die 'could not determine the openQA package version from the pinned image'
[[ "$mcp_version" =~ ^[A-Za-z0-9.+~:-]+$ ]] \
    || die 'pinned image returned an invalid openQA package version'
if ! docker image inspect "$mcp_image" >/dev/null 2>&1; then
    echo "Building local MCP development image: $mcp_image" >&2
    docker build --pull=false \
        --build-arg "OPENQA_IMAGE=$openqa_image" \
        --build-arg "OPENQA_MCP_VERSION=$mcp_version" \
        --tag "$mcp_image" \
        --file "$script_dir/Dockerfile.mcp" \
        "$script_dir"
fi
docker run --rm --entrypoint /bin/sh "$mcp_image" \
    -c 'test -r /usr/share/openqa/lib/OpenQA/WebAPI/Plugin/MCP.pm' \
    || die 'local development image does not contain the openQA MCP plugin'

container_name=${OPENQA_DEV_CONTAINER:-biglinux-openqa-dev}
http_port=${OPENQA_DEV_HTTP_PORT:-1080}
mcp_user=${OPENQA_MCP_USER:-openqa-agent}

[[ "$container_name" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'invalid OPENQA_DEV_CONTAINER'
[[ "$mcp_user" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'invalid OPENQA_MCP_USER'
valid_port() {
    [[ "$1" =~ ^[0-9]+$ ]] || return 1
    ((10#$1 >= 1024 && 10#$1 <= 65535))
}

valid_port "$http_port" || die 'OPENQA_DEV_HTTP_PORT must be between 1024 and 65535'
docker container inspect "$container_name" >/dev/null 2>&1 \
    && die "container already exists: $container_name"

kvm_gid=$(stat --format '%g' /dev/kvm)
repo_mode=ro
((write_repo)) && repo_mode=rw
startup_complete=0

cleanup_on_failure() {
    if ((startup_complete == 0)); then
        docker logs "$container_name" >&2 2>/dev/null || true
        docker stop "$container_name" >/dev/null 2>&1 || true
        docker rm -f "$container_name" >/dev/null 2>&1 || true
    fi
}
trap cleanup_on_failure EXIT

docker run --detach \
    --name "$container_name" \
    --publish "127.0.0.1:${http_port}:80" \
    --tmpfs /srv/www/htdocs:mode=0755 \
    --tmpfs /var/log/apache2:mode=0755 \
    --volume "$repo_root:/workspace:$repo_mode" \
    --volume "$iso_dir:/var/lib/openqa/share/factory/iso:ro" \
    --volume "$mcp_config:/etc/openqa/openqa.ini.d/50-mcp-read-only.ini:ro" \
    --volume "$script_dir/mcp-forwarded-proto.conf:/etc/apache2/vhosts.d/openqa-mcp-forwarded-proto.conf:ro" \
    --device /dev/kvm \
    --env "KVM_GID=$kvm_gid" \
    --env "OPENQA_MCP_USER=$mcp_user" \
    --entrypoint /bin/bash \
    "$mcp_image" \
    /workspace/openqa/development/start-container.sh

for attempt in {1..120}; do
    if curl --fail --silent --show-error \
        "http://127.0.0.1:${http_port}/api/v1/jobs" >/dev/null \
        && docker exec "$container_name" su _openqa-worker -c \
            'test -r /dev/kvm -a -w /dev/kvm'; then
        break
    fi
    if [[ "$(docker inspect --format '{{.State.Running}}' "$container_name")" != true ]]; then
        die 'openQA container stopped before becoming ready'
    fi
    if ((attempt == 120)); then
        die 'openQA API/worker was not ready within 10 minutes'
    fi
    sleep 5
done

credentials=$(docker exec "$container_name" su geekotest -c \
    '/usr/bin/perl /workspace/openqa/development/create-mcp-credentials.pl')
mcp_key=$(sed -n 's/^Key: //p' <<<"$credentials")
mcp_secret=$(sed -n 's/^Secret: //p' <<<"$credentials")
[[ "$mcp_key" =~ ^[[:xdigit:]]{16}$ ]] || die 'openQA did not return a valid MCP API key'
[[ "$mcp_secret" =~ ^[[:xdigit:]]{16}$ ]] || die 'openQA did not return a valid MCP API secret'

startup_complete=1
trap - EXIT

cat <<EOF
openQA development instance is ready.
Web UI:       http://127.0.0.1:${http_port}/
MCP endpoint: http://127.0.0.1:${http_port}/mcp
MCP bearer:   Bearer ${mcp_user}:${mcp_key}:${mcp_secret}
Container:    ${container_name}
ISO:          ${iso_path}
Repository:   /workspace (${repo_mode})

Stop it with:
  docker stop ${container_name}
EOF
