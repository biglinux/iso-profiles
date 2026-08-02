#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: schedule-release-gate.sh [--dry-run]

Schedules every mandatory plan in release-gate.yaml against an existing ISO.
The same command is used by the local development bridge and GitHub Actions.
EOF
}

dry_run=0
while (($# > 0)); do
    case "$1" in
        --dry-run)
            dry_run=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
done

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
plan_file="$script_dir/release-gate.yaml"

die() {
    echo "schedule-release-gate.sh: $*" >&2
    exit 1
}

command -v ruby >/dev/null || die 'ruby is required to read release-gate.yaml'
[[ -r "$plan_file" ]] || die "plan file is not readable: $plan_file"

container_name=${BIGLINUX_OPENQA_CONTAINER:-openqa}
openqa_version=${BIGLINUX_OPENQA_VERSION:-candidate}
openqa_build=${BIGLINUX_OPENQA_BUILD:-}
iso_filename=${BIGLINUX_ISO_FILENAME:-}
test_user=${BIGLINUX_TEST_USER:-openqa}
test_password=${BIGLINUX_TEST_PASSWORD:-}
casedir=${BIGLINUX_OPENQA_CASEDIR:-/workspace}
scenario_definitions=${BIGLINUX_OPENQA_SCENARIO_DEFINITIONS:-/workspace/openqa/scenario-definitions.yaml}
test_git_refspec=${BIGLINUX_OPENQA_TEST_GIT_REFSPEC:-}
productdir=${BIGLINUX_OPENQA_PRODUCTDIR:-openqa}
needles_dir=${BIGLINUX_OPENQA_NEEDLES_DIR:-'%%CASEDIR%%/openqa/needles'}

[[ "$container_name" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'invalid BIGLINUX_OPENQA_CONTAINER'
[[ "$openqa_version" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'invalid BIGLINUX_OPENQA_VERSION'
[[ "$openqa_build" =~ ^[A-Za-z0-9_.:-]+$ ]] || die 'invalid or missing BIGLINUX_OPENQA_BUILD'
[[ "$iso_filename" =~ ^[A-Za-z0-9._-]+$ ]] || die 'invalid or missing BIGLINUX_ISO_FILENAME'
[[ "$test_user" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'invalid BIGLINUX_TEST_USER'
[[ "$casedir" != *$'\n'* && "$scenario_definitions" != *$'\n'* ]] \
    || die 'path settings must not contain newlines'
if ((dry_run == 0)); then
    [[ -n "$test_password" ]] || die 'BIGLINUX_TEST_PASSWORD is required'
    command -v docker >/dev/null || die 'docker is required'
fi

plan_data=$(ruby - "$plan_file" <<'RUBY'
require 'yaml'

path = ARGV.fetch(0)
data = YAML.safe_load(File.read(path), permitted_classes: [], aliases: false)
abort 'release-gate.yaml must contain version: 1' unless data.is_a?(Hash) && data['version'] == 1

plans = data['plans']
abort 'release-gate.yaml must contain a non-empty plans list' unless plans.is_a?(Array) && !plans.empty?

seen = {}
plans.each do |plan|
  abort 'each release plan must be a mapping' unless plan.is_a?(Hash)
  test = plan['test']
  schedule = plan['schedule']
  firmware = plan['firmware']
  valid_name = ->(value) { value.is_a?(String) && value.match?(/\A[A-Za-z0-9_.-]+\z/) }
  abort 'release plan has an invalid test name' unless valid_name.call(test)
  abort 'release plan has an invalid schedule name' unless valid_name.call(schedule)
  abort 'release plan has an invalid firmware name' unless %w[bios uefi].include?(firmware)
  abort "duplicate release plan: #{test}" if seen.key?(test)
  seen[test] = true
  puts [test, schedule, firmware].join("\t")
end
RUBY
) || die 'release-gate.yaml is invalid'
mapfile -t plan_lines <<<"$plan_data"

overall=0
for plan_line in "${plan_lines[@]}"; do
    IFS=$'\t' read -r test_suite biglinux_schedule firmware <<<"$plan_line"
    plan_build="${openqa_build}-${test_suite}"
    echo "Running BigLinux openQA plan: $test_suite ($firmware, schedule=$biglinux_schedule)"

    args=(
        openqa-cli schedule --monitor
        async=1
        "SCENARIO_DEFINITIONS_YAML_FILE=$scenario_definitions"
        DISTRI=biglinux
        "VERSION=$openqa_version"
        FLAVOR=Live
        ARCH=x86_64
        "TEST=$test_suite"
        "BIGLINUX_SCHEDULE=$biglinux_schedule"
        "BIGLINUX_TEST_USER=$test_user"
        BIGLINUX_TEST_HOSTNAME=biglinux-openqa
        "_SECRET_BIGLINUX_TEST_PASSWORD=$test_password"
        BIGLINUX_RELEASE_GATE=1
        TIMEOUT_SCALE=1
        _GROUP_ID=0
        "BUILD=$plan_build"
        "ISO=$iso_filename"
        "CASEDIR=$casedir"
        "PRODUCTDIR=$productdir"
        "NEEDLES_DIR=$needles_dir"
        SERIALDEV=hvc0
    )
    [[ -n "$test_git_refspec" ]] && args+=("TEST_GIT_REFSPEC=$test_git_refspec")

    if ((dry_run)); then
        printf '  plan=%s firmware=%s build=%s\n' "$test_suite" "$firmware" "$plan_build"
        continue
    fi

    if ! docker exec "$container_name" "${args[@]}"; then
        echo "openQA failed for $test_suite" >&2
        overall=1
    fi
done

exit "$overall"
