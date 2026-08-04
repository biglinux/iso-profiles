#!/usr/bin/env bash
set -euo pipefail

: "${OPENQA_API_KEY:?OPENQA_API_KEY is required}"
: "${OPENQA_API_SECRET:?OPENQA_API_SECRET is required}"

readonly client_image='registry.opensuse.org/devel/openqa/containers/tumbleweed@sha256:4d2f4736d18939aaaff5f5b0616d594255243a8974c33fd3a4731909ab44702e'

command -v docker >/dev/null 2>&1 || {
    echo 'Docker is required to run the pinned official openQA client image' >&2
    exit 127
}

docker_args=(
    run
    --rm
    --read-only
    --cap-drop=ALL
    --security-opt=no-new-privileges
    --tmpfs
    '/tmp:rw,nosuid,nodev,noexec,size=64m'
    --env=OPENQA_API_KEY
    --env=OPENQA_API_SECRET
)

if (($# == 1)) && [[ "$1" == --version ]]; then
    docker "${docker_args[@]}" "$client_image" rpm -q openQA-client
    exit 0
fi

cli_args=()
mounts=()
expect_param_file=0

for arg in "$@"; do
    if ((expect_param_file)); then
        [[ "$arg" == *=* ]] || {
            echo '--param-file requires KEY=FILE' >&2
            exit 2
        }
        param_key=${arg%%=*}
        param_file=${arg#*=}
        [[ "$param_key" =~ ^[A-Za-z0-9_.:-]+$ ]] || {
            echo 'Invalid openQA parameter name' >&2
            exit 2
        }
        [[ "$param_file" = /* && -f "$param_file" && -r "$param_file" ]] || {
            echo 'openQA parameter file is not a readable absolute file' >&2
            exit 2
        }
        param_file=$(realpath -e -- "$param_file")
        mounts+=(--volume "$param_file:$param_file:ro")
        cli_args+=(--param-file "$param_key=$param_file")
        expect_param_file=0
        continue
    fi

    case "$arg" in
        --param-file)
            cli_args+=(--param-file)
            expect_param_file=1
            ;;
        --apikey|--apisecret|--apikey=*|--apisecret=*)
            echo 'Pass openQA credentials through environment variables, not argv' >&2
            exit 2
            ;;
        *)
            cli_args+=("$arg")
            ;;
    esac
done

((expect_param_file == 0)) || {
    echo '--param-file is missing its value' >&2
    exit 2
}

archive_help=0
for arg in "${cli_args[@]}"; do
    if [[ "$arg" == --help || "$arg" == -h ]]; then
        archive_help=1
        break
    fi
done

if [[ ${cli_args[0]:-} == archive && $archive_help == 0 ]]; then
    archive_path=${cli_args[${#cli_args[@]}-1]}
    [[ "$archive_path" = /* && -d "$archive_path" ]] || {
        echo 'openQA archive destination must be an existing absolute directory' >&2
        exit 2
    }
    archive_path=$(realpath -e -- "$archive_path")
    mounts+=(--volume "$archive_path:$archive_path:rw")
fi

docker "${docker_args[@]}" "${mounts[@]}" "$client_image" openqa-cli "${cli_args[@]}"
