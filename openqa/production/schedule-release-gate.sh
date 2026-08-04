#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: schedule-release-gate.sh

Schedules and monitors the mandatory BIOS and UEFI plans on persistent openQA.
EOF
}

(($# == 0)) || { usage >&2; exit 2; }

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=./openqa/production/ssh-common.sh
source "$script_dir/ssh-common.sh"

: "${BIGLINUX_OPENQA_URL:?BIGLINUX_OPENQA_URL is required}"
: "${BIGLINUX_OPENQA_GROUP:?BIGLINUX_OPENQA_GROUP is required}"
: "${BIGLINUX_OPENQA_WORKER_CLASS:?BIGLINUX_OPENQA_WORKER_CLASS is required}"
: "${BIGLINUX_OPENQA_VERSION:?BIGLINUX_OPENQA_VERSION is required}"
: "${BIGLINUX_OPENQA_BUILD:?BIGLINUX_OPENQA_BUILD is required}"
: "${BIGLINUX_ISO_FILENAME:?BIGLINUX_ISO_FILENAME is required}"
: "${BIGLINUX_OPENQA_CASEDIR:?BIGLINUX_OPENQA_CASEDIR is required}"
: "${BIGLINUX_OPENQA_TEST_GIT_REFSPEC:?BIGLINUX_OPENQA_TEST_GIT_REFSPEC is required}"
: "${BIGLINUX_OPENQA_SCENARIO_DEFINITIONS:?BIGLINUX_OPENQA_SCENARIO_DEFINITIONS is required}"
: "${BIGLINUX_TEST_USER:?BIGLINUX_TEST_USER is required}"
: "${BIGLINUX_TEST_PASSWORD:?BIGLINUX_TEST_PASSWORD is required}"
: "${BIGLINUX_OPENQA_DIAGNOSTICS_DIR:?BIGLINUX_OPENQA_DIAGNOSTICS_DIR is required}"

[[ "$BIGLINUX_OPENQA_URL" =~ ^https://[^[:space:]/]+(/[^[:space:]]*)?$ ]] || { echo 'Invalid openQA URL' >&2; exit 2; }
[[ "$BIGLINUX_OPENQA_GROUP" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'Invalid openQA group' >&2; exit 2; }
[[ "$BIGLINUX_OPENQA_WORKER_CLASS" =~ ^[A-Za-z0-9_.:-]+$ ]] || { echo 'Invalid worker class' >&2; exit 2; }
[[ "$BIGLINUX_TEST_USER" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'Invalid test user' >&2; exit 2; }
[[ "$BIGLINUX_OPENQA_VERSION" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'Invalid openQA version' >&2; exit 2; }
[[ "$BIGLINUX_OPENQA_BUILD" =~ ^[A-Za-z0-9_.:-]+$ ]] || { echo 'Invalid openQA build' >&2; exit 2; }
[[ "$BIGLINUX_ISO_FILENAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.iso$ ]] || { echo 'Invalid ISO filename' >&2; exit 2; }
[[ "$BIGLINUX_OPENQA_TEST_GIT_REFSPEC" =~ ^[0-9a-f]{40}$ ]] || { echo 'Test refspec must be a full commit SHA' >&2; exit 2; }
[[ "$BIGLINUX_OPENQA_CASEDIR" == *"#${BIGLINUX_OPENQA_TEST_GIT_REFSPEC}" ]] || { echo 'CASEDIR is not pinned to TEST_GIT_REFSPEC' >&2; exit 2; }
[[ "$BIGLINUX_OPENQA_SCENARIO_DEFINITIONS" == *"/${BIGLINUX_OPENQA_TEST_GIT_REFSPEC}/openqa/scenario-definitions.yaml" ]] || {
    echo 'Scenario definitions are not pinned to TEST_GIT_REFSPEC' >&2
    exit 2
}
[[ "$BIGLINUX_TEST_PASSWORD" != *$'\n'* && "$BIGLINUX_TEST_PASSWORD" != *$'\r'* ]] || {
    echo 'BIGLINUX_TEST_PASSWORD must not contain line breaks' >&2
    exit 2
}

mkdir -p -- "$BIGLINUX_OPENQA_DIAGNOSTICS_DIR"
openqa_production_setup_ssh

plan_data=$(ruby - "$script_dir/../development/release-gate.yaml" <<'RUBY'
require 'yaml'

path = ARGV.fetch(0)
data = YAML.safe_load(File.read(path), permitted_classes: [], aliases: false)
abort 'release-gate.yaml must contain version: 1' unless data.is_a?(Hash) && data['version'] == 1
plans = data['plans']
abort 'release-gate.yaml must contain exactly two plans' unless plans.is_a?(Array) && plans.length == 2
plans.each do |plan|
  abort 'invalid release plan' unless plan.is_a?(Hash)
  values = [plan['test'], plan['schedule'], plan['firmware']]
  abort 'invalid release plan value' unless values.all? { |value| value.is_a?(String) && value.match?(/\A[A-Za-z0-9_.-]+\z/) }
  abort 'invalid firmware' unless %w[bios uefi].include?(plan['firmware'])
  puts values.join("\t")
end
RUBY
)
mapfile -t plan_lines <<<"$plan_data"

schedule_plan() {
    local plan_line=$1
    local test_suite biglinux_schedule firmware
    IFS=$'\t' read -r test_suite biglinux_schedule firmware <<<"$plan_line"
    local plan_build="${BIGLINUX_OPENQA_BUILD}-${test_suite}"
    local log_file="$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/schedule-${firmware}.log"
    local remote_schedule
    remote_schedule=$(cat <<'REMOTE'
set -euo pipefail
url=$1
scenario_definitions=$2
test_suite=$3
biglinux_schedule=$4
worker_class=$5
group=$6
version=$7
plan_build=$8
iso_filename=$9
casedir=${10}
test_git_refspec=${11}
test_user=${12}
password_file=$(mktemp /tmp/biglinux-openqa-password.XXXXXX)
cleanup() {
    unlink -- "$password_file"
}
trap cleanup EXIT
chmod 600 "$password_file"
IFS= read -r password
[[ -n "$password" ]] || { echo 'empty test password received' >&2; exit 1; }
printf '%s' "$password" >"$password_file"
args=(
    openqa-cli --host "$url" schedule --monitor
    --param-file "_SECRET_BIGLINUX_TEST_PASSWORD=$password_file"
    async=1
    "SCENARIO_DEFINITIONS_YAML_FILE=$scenario_definitions"
    DISTRI=biglinux
    "VERSION=$version"
    FLAVOR=Live
    ARCH=x86_64
    "TEST=$test_suite"
    "BIGLINUX_SCHEDULE=$biglinux_schedule"
    "BIGLINUX_TEST_USER=$test_user"
    BIGLINUX_TEST_HOSTNAME=biglinux-openqa
    BIGLINUX_RELEASE_GATE=1
    TIMEOUT_SCALE=1
    QEMU_NO_KVM=0
    "_GROUP=$group"
    "WORKER_CLASS=$worker_class"
    "BUILD=$plan_build"
    "ISO=$iso_filename"
    "CASEDIR=$casedir"
    PRODUCTDIR=openqa
    NEEDLES_DIR=%%CASEDIR%%/openqa/needles
    SERIALDEV=hvc0
    "TEST_GIT_REFSPEC=$test_git_refspec"
)
"${args[@]}"
REMOTE
)
    echo "Starting openQA plan: $test_suite ($firmware)"
    openqa_production_ssh_stdin "$BIGLINUX_TEST_PASSWORD"$'\n' \
        bash -c "$remote_schedule" -- \
        "$BIGLINUX_OPENQA_URL" \
        "$BIGLINUX_OPENQA_SCENARIO_DEFINITIONS" \
        "$test_suite" \
        "$biglinux_schedule" \
        "$BIGLINUX_OPENQA_WORKER_CLASS" \
        "$BIGLINUX_OPENQA_GROUP" \
        "$BIGLINUX_OPENQA_VERSION" \
        "$plan_build" \
        "$BIGLINUX_ISO_FILENAME" \
        "$BIGLINUX_OPENQA_CASEDIR" \
        "$BIGLINUX_OPENQA_TEST_GIT_REFSPEC" \
        "$BIGLINUX_TEST_USER" >"$log_file" 2>&1
}

status=0
for plan_line in "${plan_lines[@]}"; do
    schedule_plan "$plan_line" &
done
for plan_line in "${plan_lines[@]}"; do
    if ! wait -n 2>/dev/null; then
        status=1
    fi
done

for firmware in bios uefi; do
    log_file="$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/schedule-$firmware.log"
    [[ -f "$log_file" ]] || continue
    grep -oE '/tests/[0-9]+' "$log_file" | sed 's#.*/##' | sort -nu \
        >"$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids-$firmware.txt"
done
for log_file in "$BIGLINUX_OPENQA_DIAGNOSTICS_DIR"/schedule-*.log; do
    [[ -f "$log_file" ]] || continue
    grep -oE '/tests/[0-9]+' "$log_file" | sed 's#.*/##' | sort -nu
done | sort -nu >"$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids.txt"
[[ -s "$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids.txt" ]] || {
    echo 'No openQA job IDs were returned by the scheduler' >&2
    status=1
}

exit "$status"
