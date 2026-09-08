#!/usr/bin/env bash
# Runs one release-gate plan with isotovideo, in the pinned container.
#
# There is no openQA server anywhere in this path: isotovideo is the backend
# openQA itself drives, and running it directly removes the database, the
# scheduler, the asset store and the HTTP hop between a test and its own
# results. Everything that used to be a job setting is an argument here, and
# the exit status is the verdict - `-e` returns 0 only when every module ended
# ok or softfail.
#
# The results directory is the isotovideo working directory: testresults/,
# ulogs/, autoinst-log.txt, video.ogv and vars.json all land there, already
# owned by the invoking user.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: run-plan.sh --plan NAME --iso PATH --results DIR [options]

  --plan NAME         a plan from openqa/release-gate.yaml
  --iso PATH          the ISO to test
  --results DIR       where isotovideo works and writes its results
  --password-file F   file holding the test user's password (required)
  --image REF         container image (default: openqa/openqa-image.txt)
  --build ID          build identifier recorded in the results
  --iso-sha256 SUM    checksum of the ISO, recorded in the results
  --commit SHA        commit the tests came from, recorded in the results
  --uefi-code PATH    OVMF code, required by a UEFI plan
  --uefi-vars PATH    OVMF variable store, required by a UEFI plan
  --timeout SECONDS   hard limit for the whole plan (default: 7200)

The results directory needs room for the guest disk: HDDSIZEGB plus a fifth,
so 48 GiB free for the default 40. isotovideo refuses to start otherwise.
EOF
}

die() {
    echo "run-plan.sh: $*" >&2
    exit 1
}

plan=
iso=
results=
password_file=
image=
build=
commit=
iso_sha256=
uefi_code=
uefi_vars=
timeout_seconds=7200

while (($# > 0)); do
    case "$1" in
        --plan | --iso | --results | --password-file | --image | --build | --commit | --iso-sha256 | --uefi-code | --uefi-vars | --timeout)
            (($# >= 2)) || { usage >&2; exit 2; }
            case "$1" in
                --plan) plan=$2 ;;
                --iso) iso=$2 ;;
                --results) results=$2 ;;
                --password-file) password_file=$2 ;;
                --image) image=$2 ;;
                --build) build=$2 ;;
                --commit) commit=$2 ;;
                --iso-sha256) iso_sha256=$2 ;;
                --uefi-code) uefi_code=$2 ;;
                --uefi-vars) uefi_vars=$2 ;;
                --timeout) timeout_seconds=$2 ;;
            esac
            shift 2
            ;;
        --help | -h)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
done

repository=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
gate_file="$repository/openqa/release-gate.yaml"
image=${image:-$(tr -d '[:space:]' <"$repository/openqa/openqa-image.txt")}

# Pinned by digest, and from a registry we chose. ghcr.io is the mirror this
# repository pushes to, because the openSUSE devel registry keeps only a
# handful of tags and garbage-collected the digest the gate trusted.
[[ "$image" =~ ^(ghcr\.io|registry\.opensuse\.org)/.+@sha256:[[:xdigit:]]{64}$ ]] \
    || die "the container image must be pinned by digest: $image"
[[ -n "$plan" ]] || die 'a plan is required'
[[ -n "$iso" && -f "$iso" ]] || die "the ISO is not readable: $iso"
[[ -n "$results" ]] || die 'a results directory is required'
[[ -n "$password_file" && -r "$password_file" ]] || die 'a readable --password-file is required'
[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || die 'invalid --timeout'
command -v docker >/dev/null || die 'docker is required'
[[ -r /dev/kvm && -w /dev/kvm ]] || die '/dev/kvm must be readable and writable'

# The plan's settings, one KEY=VALUE per line. Ruby reads the YAML the same way
# the repository already does elsewhere, and refuses anything it does not
# recognise rather than testing something other than what was asked for.
plan_settings=$(ruby - "$gate_file" "$plan" <<'RUBY'
require 'yaml'

path, wanted = ARGV
gate = YAML.safe_load(File.read(path), permitted_classes: [], aliases: false)
abort 'release-gate.yaml must contain version: 2' unless gate.is_a?(Hash) && gate['version'] == 2

plans = gate['plans']
abort 'release-gate.yaml must contain a plans list' unless plans.is_a?(Array)
plan = plans.find { |candidate| candidate.is_a?(Hash) && candidate['name'] == wanted }
abort "no plan named #{wanted}" unless plan

machine = gate.dig('machines', plan['machine'])
abort "plan #{wanted} names an unknown machine" unless machine.is_a?(Hash)

settings = machine.merge(plan['settings'] || {})
settings['BIGLINUX_SCHEDULE'] = plan['schedule']
settings['TEST'] = plan['name']

# The shard count is how many application plans there are - not a separate key
# that can disagree with them. Their indexes have to be exactly 0..n-1, or a
# shard would be tested twice and another not at all.
shards = plans.select { |candidate| candidate['schedule'] == 'applications' }
if plan['schedule'] == 'applications'
  indexes = shards.map { |candidate| candidate.dig('settings', 'BIGLINUX_APPLICATION_SHARD_INDEX').to_i }.sort
  abort "application shard indexes must be 0..#{shards.length - 1}, got #{indexes.join(',')}" \
    unless indexes == (0...shards.length).to_a
  settings['BIGLINUX_APPLICATION_SHARD_COUNT'] = shards.length.to_s
end

settings.each do |key, value|
  abort "setting #{key} is not a scalar" unless value.is_a?(String) || value.is_a?(Integer)
  abort "setting #{key} contains a newline" if value.to_s.include?("\n")
  puts "#{key}=#{value}"
end
RUBY
) || die "could not read plan '$plan' from $gate_file"

uefi=0
grep -qx 'UEFI=1' <<<"$plan_settings" && uefi=1
if ((uefi)); then
    [[ -f "$uefi_code" && -f "$uefi_vars" ]] \
        || die 'a UEFI plan needs --uefi-code and --uefi-vars'
fi

mkdir -p -- "$results"
results=$(cd -- "$results" && pwd -P)
iso_directory=$(cd -- "$(dirname -- "$iso")" && pwd -P)
iso_name=$(basename -- "$iso")
# docker --volume needs absolute paths, and the readability checks above accept
# relative ones.
password_file=$(realpath -- "$password_file")
if ((uefi)); then
    uefi_code=$(realpath -- "$uefi_code")
    uefi_vars=$(realpath -- "$uefi_vars")
fi

# isotovideo writes the whole working directory as the invoking user, so the
# results need no ownership repair afterwards and no root-owned file can be
# left behind for the next step to trip over.
container_name="biglinux-plan-$plan-$$"
docker_arguments=(
    run --rm
    --name "$container_name"
    --user "$(id -u):$(id -g)"
    --group-add "$(stat -c '%g' /dev/kvm)"
    --device /dev/kvm
    --volume "$repository:/case:ro"
    --volume "$iso_directory:/iso:ro"
    --volume "$results:/work"
    --volume "$password_file:/run/secrets/test-password:ro"
    --workdir /work
    --entrypoint isotovideo
)
if ((uefi)); then
    docker_arguments+=(
        --volume "$uefi_code:/run/ovmf/code.fd:ro"
        --volume "$uefi_vars:/run/ovmf/vars.fd:ro"
    )
fi

# Every variable the tests read. The password is deliberately absent: it is a
# file the tests open, because isotovideo writes vars.json without redacting
# and this directory is uploaded as an artifact.
isotovideo_arguments=(
    -e
    "CASEDIR=/case"
    "PRODUCTDIR=openqa"
    "NEEDLES_DIR=openqa/needles"
    "ISO=/iso/$iso_name"
    "BIGLINUX_ISO_FILENAME=$iso_name"
    "BIGLINUX_ISO_SHA256=$iso_sha256"
    "BIGLINUX_TEST_PASSWORD_FILE=/run/secrets/test-password"
    BIGLINUX_TEST_USER=openqa
    BIGLINUX_TEST_HOSTNAME=biglinux-openqa
    BIGLINUX_RELEASE_GATE=1
    BIGLINUX_APPLICATION_TIMEOUT=30
    TIMEOUT_SCALE=1
    QEMU_NO_KVM=0
    SERIALDEV=hvc0
    # The default marker installs a PROMPT_COMMAND hook in the guest so command
    # exit codes reach the serial log. These tests read the virtio terminal
    # directly, so the hook only adds noise to a channel they parse.
    PRETTY_SERIAL_MARKER=0
    DISTRI=biglinux
    VERSION=candidate
    FLAVOR=Live
    ARCH=x86_64
)
[[ -n "$build" ]] && isotovideo_arguments+=("BIGLINUX_OPENQA_BUILD=$build")
[[ -n "$commit" ]] && isotovideo_arguments+=("BIGLINUX_OPENQA_COMMIT=$commit")
if ((uefi)); then
    isotovideo_arguments+=("UEFI_PFLASH_CODE=/run/ovmf/code.fd" "UEFI_PFLASH_VARS=/run/ovmf/vars.fd")
fi
while IFS= read -r setting; do
    [[ -n "$setting" ]] && isotovideo_arguments+=("$setting")
done <<<"$plan_settings"

printf 'Running plan %s against %s\n' "$plan" "$iso_name"

# isotovideo's own exit codes are the verdict: 0 when every module ended ok or
# softfail, 100 when no module ran at all, 101 when one failed. They pass
# through untouched; the timeout below is the outer bound, so a wedged backend
# cannot hold a CI runner for six hours.
# isotovideo logs to standard output; the file both the report and the KVM
# check read is written by openQA's worker, which is not here.
set +e
timeout --kill-after=60 "$timeout_seconds" \
    docker "${docker_arguments[@]}" "$image" "${isotovideo_arguments[@]}" \
    2>&1 | tee "$results/autoinst-log.txt"
status=${PIPESTATUS[0]}
set -e

if ((status == 124 || status == 137)); then
    # SIGKILL reaches the docker client, which merely detaches: the container
    # and its QEMU keep the disk and /dev/kvm until they are stopped by name.
    docker rm --force "$container_name" >/dev/null 2>&1 || true
    echo "run-plan.sh: plan $plan exceeded $timeout_seconds seconds" >&2
    exit 1
fi

# KVM is not implied by QEMU_NO_KVM=0: os-autoinst adds -enable-kvm only when
# /dev/kvm is readable *inside* the container (backend/qemu.pm), and silently
# runs TCG otherwise - which would make every timing in the results a fiction.
grep -q -- '-enable-kvm' "$results/autoinst-log.txt" \
    || die 'the archived QEMU command line does not prove KVM'

exit "$status"
