#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: schedule-release-gate.sh [--dry-run] [--firmware bios|uefi]
       schedule-release-gate.sh [--dry-run] --applications-shard INDEX COUNT

Schedules and monitors one mandatory BigLinux plan in a local openQA instance.
BIOS and UEFI are intentionally separate invocations and runners.
EOF
}

dry_run=0
firmware=${BIGLINUX_OPENQA_FIRMWARE:-}
application_shard_index=${BIGLINUX_APPLICATION_SHARD_INDEX:-}
application_shard_count=${BIGLINUX_APPLICATION_SHARD_COUNT:-}
while (($# > 0)); do
    case "$1" in
        --dry-run)
            dry_run=1
            shift
            ;;
        --firmware)
            (($# >= 2)) || { usage >&2; exit 2; }
            firmware=$2
            shift 2
            ;;
        --applications-shard)
            (($# >= 3)) || { usage >&2; exit 2; }
            application_shard_index=$2
            application_shard_count=$3
            shift 3
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
command -v jq >/dev/null || die 'jq is required to read openQA API responses'
[[ -r "$plan_file" ]] || die "plan file is not readable: $plan_file"

if [[ -n "$firmware" && "$firmware" != bios && "$firmware" != uefi ]]; then
    die 'firmware must be bios or uefi'
fi
if [[ -n "$firmware" && ( -n "$application_shard_index" || -n "$application_shard_count" ) ]]; then
    die 'firmware and application shard selectors cannot be combined'
fi
if [[ -n "$application_shard_index" || -n "$application_shard_count" ]]; then
    [[ "$application_shard_index" =~ ^[0-9]+$ ]] || die 'invalid application shard index'
    [[ "$application_shard_count" =~ ^[1-9][0-9]*$ ]] || die 'invalid application shard count'
    ((application_shard_index < application_shard_count)) || die 'application shard index is out of range'
elif ((dry_run == 0)) && [[ -z "$firmware" ]]; then
    die 'a non-dry run must select one firmware or application shard'
fi

container_name=${BIGLINUX_OPENQA_CONTAINER:-openqa}
openqa_version=${BIGLINUX_OPENQA_VERSION:-candidate}
openqa_build=${BIGLINUX_OPENQA_BUILD:-}
iso_filename=${BIGLINUX_ISO_FILENAME:-}
test_user=${BIGLINUX_TEST_USER:-openqa}
password_file=${BIGLINUX_TEST_PASSWORD_FILE:-}
container_password_file=${BIGLINUX_TEST_PASSWORD_CONTAINER_FILE:-/run/secrets/biglinux-test-password}
casedir=${BIGLINUX_OPENQA_CASEDIR:-/workspace}
scenario_definitions=${BIGLINUX_OPENQA_SCENARIO_DEFINITIONS:-/workspace/openqa/scenario-definitions.yaml}
test_git_refspec=${BIGLINUX_OPENQA_TEST_GIT_REFSPEC:-}
productdir=${BIGLINUX_OPENQA_PRODUCTDIR:-openqa}
application_timeout=${BIGLINUX_APPLICATION_TIMEOUT:-8}
policy_file=${BIGLINUX_APPLICATION_POLICY_FILE:-$script_dir/../application-policy.yaml}
iso_sha256=${BIGLINUX_ISO_SHA256:-}
needles_git_hash=${BIGLINUX_NEEDLES_GIT_HASH:-$test_git_refspec}
diagnostics_dir=${BIGLINUX_OPENQA_DIAGNOSTICS_DIR:-}
poll_interval=${BIGLINUX_OPENQA_POLL_INTERVAL:-5}
schedule_timeout=${BIGLINUX_OPENQA_SCHEDULE_TIMEOUT:-300}
job_timeout=${BIGLINUX_OPENQA_JOB_TIMEOUT:-18000}
uefi_pflash_code=${BIGLINUX_OPENQA_UEFI_PFLASH_CODE:-}
uefi_pflash_vars=${BIGLINUX_OPENQA_UEFI_PFLASH_VARS:-}

[[ "$container_name" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'invalid BIGLINUX_OPENQA_CONTAINER'
[[ "$openqa_version" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'invalid BIGLINUX_OPENQA_VERSION'
[[ "$openqa_build" =~ ^[A-Za-z0-9_.:-]+$ ]] || die 'invalid or missing BIGLINUX_OPENQA_BUILD'
[[ "$iso_filename" =~ ^[A-Za-z0-9._-]+\.iso$ ]] || die 'invalid or missing BIGLINUX_ISO_FILENAME'
[[ "$test_user" =~ ^[A-Za-z0-9_.-]+$ ]] || die 'invalid BIGLINUX_TEST_USER'
[[ "$application_timeout" =~ ^[1-9][0-9]*$ ]] || die 'invalid BIGLINUX_APPLICATION_TIMEOUT'
[[ -r "$policy_file" ]] || die "application policy is not readable: $policy_file"
if ((dry_run == 0)); then
    [[ "$iso_sha256" =~ ^[[:xdigit:]]{64}$ ]] || die 'invalid or missing BIGLINUX_ISO_SHA256'
fi
[[ "$poll_interval" =~ ^[1-9][0-9]*$ ]] || die 'invalid BIGLINUX_OPENQA_POLL_INTERVAL'
[[ "$schedule_timeout" =~ ^[1-9][0-9]*$ ]] || die 'invalid BIGLINUX_OPENQA_SCHEDULE_TIMEOUT'
[[ "$job_timeout" =~ ^[1-9][0-9]*$ ]] || die 'invalid BIGLINUX_OPENQA_JOB_TIMEOUT'
[[ "$casedir" != *$'\n'* && "$scenario_definitions" != *$'\n'* ]] \
    || die 'openQA paths must not contain newlines'

if ((dry_run == 0)); then
    if [[ "$firmware" == uefi ]]; then
        [[ "$uefi_pflash_code" = /* && "$uefi_pflash_vars" = /* ]] \
            || die 'UEFI firmware paths are required for a UEFI plan'
        [[ "$uefi_pflash_code" != *$'\n'* && "$uefi_pflash_vars" != *$'\n'* ]] \
            || die 'UEFI firmware paths must not contain newlines'
    fi
    command -v docker >/dev/null || die 'docker is required'
    [[ -n "$password_file" && -r "$password_file" ]] \
        || die 'BIGLINUX_TEST_PASSWORD_FILE must be readable'
    [[ -n "$diagnostics_dir" ]] || die 'BIGLINUX_OPENQA_DIAGNOSTICS_DIR is required'
    docker inspect "$container_name" >/dev/null 2>&1 \
        || die "openQA container is not running: $container_name"
    mkdir -p -- "$diagnostics_dir"
fi

plan_data=$(ruby - "$plan_file" "$firmware" "$application_shard_index" "$application_shard_count" <<'RUBY'
require 'yaml'

path, requested_firmware, requested_shard_index, requested_shard_count = ARGV
data = YAML.safe_load(File.read(path), permitted_classes: [], aliases: false)
abort 'release-gate.yaml must contain version: 1' unless data.is_a?(Hash) && data['version'] == 1
abort 'release-gate.yaml must define four application shards' unless data['application_shard_count'] == 4

plans = data['plans']
abort 'release-gate.yaml must contain a non-empty plans list' unless plans.is_a?(Array) && !plans.empty?

plans.each do |plan|
  abort 'each release plan must be a mapping' unless plan.is_a?(Hash)
  test = plan['test']
  schedule = plan['schedule']
  firmware = plan['firmware']
  kind = plan['kind']
  shard = plan['shard']
  valid_name = ->(value) { value.is_a?(String) && value.match?(/\A[A-Za-z0-9_.-]+\z/) }
  abort 'release plan has an invalid value' unless [test, schedule, firmware, kind].all? { |value| valid_name.call(value) }
  abort 'release plan has an invalid firmware' unless %w[bios uefi].include?(firmware)
  abort 'release plan has an invalid kind' unless %w[firmware applications].include?(kind)
  if kind == 'applications'
    abort 'application release plan has an invalid shard' unless shard.is_a?(Integer) && shard >= 0 && shard < data['application_shard_count']
  end
  if !requested_shard_index.empty?
    abort 'application shard count does not match release-gate.yaml' unless requested_shard_count.to_i == data['application_shard_count']
    next unless kind == 'applications' && shard == requested_shard_index.to_i
  else
    next unless kind == 'firmware' && !requested_firmware.empty? && firmware == requested_firmware
  end
  puts [test, schedule, firmware, kind, shard].join("\t")
end
RUBY
) || die 'release-gate.yaml is invalid'
# A here-string of the empty selection would still yield one (empty) line and
# defeat the single-plan guard below.
[[ -n "$plan_data" ]] || die 'no release plan matched the requested selector'
mapfile -t plan_lines <<<"$plan_data"
if ((dry_run == 0 && ${#plan_lines[@]} != 1)); then
    die "expected one matching plan, got ${#plan_lines[@]}"
fi

if ((dry_run)); then
    for plan_line in "${plan_lines[@]}"; do
        IFS=$'\t' read -r test_suite biglinux_schedule selected_firmware plan_kind plan_shard <<<"$plan_line"
        printf 'plan=%s firmware=%s schedule=%s kind=%s shard=%s build=%s-%s\n' \
            "$test_suite" "$selected_firmware" "$biglinux_schedule" "$plan_kind" \
            "${plan_shard:-none}" "$openqa_build" "$test_suite"
    done
    exit 0
fi

plan_line=${plan_lines[0]}
IFS=$'\t' read -r test_suite biglinux_schedule selected_firmware plan_kind plan_shard <<<"$plan_line"
plan_build="${openqa_build}-${test_suite}"
response_file="$diagnostics_dir/schedule-$selected_firmware.json"
schedule_log="$diagnostics_dir/schedule-$selected_firmware.log"
status_file="$diagnostics_dir/scheduled-product-$selected_firmware.json"
job_ids_file="$diagnostics_dir/job-ids-$selected_firmware.txt"

printf 'Starting local openQA plan: %s (%s)\n' "$test_suite" "$selected_firmware" | tee "$schedule_log"

policy_json=$(ruby - "$policy_file" <<'RUBY'
require 'json'
require 'yaml'

path = ARGV.fetch(0)
policy = YAML.safe_load(File.read(path), permitted_classes: [], aliases: false)
abort 'application policy must be a mapping' unless policy.is_a?(Hash)
canonical = lambda do |value|
  case value
  when Hash
    value.keys.sort.each_with_object({}) { |key, result| result[key] = canonical.call(value[key]) }
  when Array
    value.map { |item| canonical.call(item) }
  else
    value
  end
end
puts JSON.generate(canonical.call(policy))
RUBY
) || die 'application policy could not be converted to JSON'
policy_hash=$(printf '%s' "$policy_json" | sha256sum | awk '{print $1}')
printf 'application_policy_sha256=%s\n' "$policy_hash" | tee -a "$schedule_log"

api_post_args=(
    api --host http://localhost -X POST isos
    --param-file "SCENARIO_DEFINITIONS_YAML=$scenario_definitions"
    --param-file "_SECRET_BIGLINUX_TEST_PASSWORD=$container_password_file"
    async=1
    DISTRI=biglinux
    "VERSION=$openqa_version"
    FLAVOR=Live
    ARCH=x86_64
    "TEST=$test_suite"
    "BIGLINUX_SCHEDULE=$biglinux_schedule"
    "BIGLINUX_TEST_USER=$test_user"
    BIGLINUX_TEST_HOSTNAME=biglinux-openqa
    BIGLINUX_RELEASE_GATE=1
    TIMEOUT_SCALE=1
    "BIGLINUX_APPLICATION_TIMEOUT=$application_timeout"
    "BIGLINUX_ISO_FILENAME=$iso_filename"
    "BIGLINUX_ISO_SHA256=$iso_sha256"
    "BIGLINUX_OPENQA_BUILD=$openqa_build"
    "BIGLINUX_OPENQA_TEST_GIT_REFSPEC=$test_git_refspec"
    "BIGLINUX_NEEDLES_GIT_HASH=$needles_git_hash"
    "BIGLINUX_APPLICATION_POLICY_HASH=$policy_hash"
    "BIGLINUX_APPLICATION_POLICY_JSON=$policy_json"
    QEMU_NO_KVM=0
    WORKER_CLASS=biglinux-kvm
    "BUILD=$plan_build"
    "ISO=$iso_filename"
    "CASEDIR=$casedir"
    "PRODUCTDIR=$productdir"
    NEEDLES_DIR=%%CASEDIR%%/openqa/needles
    SERIALDEV=hvc0
)
if [[ "$selected_firmware" == uefi ]]; then
    api_post_args+=(
        "UEFI_PFLASH_CODE=$uefi_pflash_code"
        "UEFI_PFLASH_VARS=$uefi_pflash_vars"
    )
fi
if [[ "$selected_firmware" == bios && "$plan_kind" == firmware ]]; then
    api_post_args+=(BIGLINUX_APPLICATION_FILTER='dolphin,libreoffice,gimp,brave,biglinux-control-center,control-center')
fi
if [[ "$plan_kind" == applications ]]; then
    api_post_args+=(
        "BIGLINUX_APPLICATION_SHARD_INDEX=$plan_shard"
        "BIGLINUX_APPLICATION_SHARD_COUNT=$application_shard_count"
    )
fi
[[ -n "$test_git_refspec" ]] && api_post_args+=("TEST_GIT_REFSPEC=$test_git_refspec")

if ! docker exec "$container_name" openqa-cli "${api_post_args[@]}" \
    >"$response_file" 2>>"$schedule_log"; then
    echo 'Local openQA scheduling request failed' >>"$schedule_log"
    exit 1
fi
cat "$response_file" >>"$schedule_log"
jq -e 'type == "object"' "$response_file" >/dev/null \
    || die 'local openQA scheduling response is not valid JSON'

scheduled_product_id=$(jq -r '.scheduled_product_id // empty' "$response_file")
job_ids=()
if [[ -n "$scheduled_product_id" ]]; then
    deadline=$((SECONDS + schedule_timeout))
    while :; do
        if ! docker exec "$container_name" openqa-cli api --host http://localhost \
            "isos/$scheduled_product_id" >"$status_file" 2>>"$schedule_log"; then
            echo "Could not query scheduled product $scheduled_product_id" >>"$schedule_log"
            exit 1
        fi
        status=$(jq -r '.status // empty' "$status_file")
        case "$status" in
            scheduled)
                mapfile -t job_ids < <(jq -r '.results.successful_job_ids[]? // empty' "$status_file" | sort -nu)
                break
                ;;
            added|scheduling)
                ((SECONDS < deadline)) || {
                    echo "Scheduled product $scheduled_product_id did not become scheduled" >>"$schedule_log"
                    exit 1
                }
                sleep "$poll_interval"
                ;;
            *)
                echo "Scheduled product $scheduled_product_id ended in state: $status" >>"$schedule_log"
                exit 1
                ;;
        esac
    done
else
    mapfile -t job_ids < <(jq -r '(.ids // [])[]?, (.id // empty)' "$response_file" | sort -nu)
fi

if ((${#job_ids[@]} != 1)); then
    printf 'Expected one job, got %s\n' "${#job_ids[@]}" >>"$schedule_log"
    exit 1
fi
printf '%s\n' "${job_ids[0]}" >"$job_ids_file"
printf '%s\n' "${job_ids[0]}" >"$diagnostics_dir/job-ids.txt"
printf 'Scheduled local openQA job: %s\n' "${job_ids[0]}" | tee -a "$schedule_log"

job_id=${job_ids[0]}
job_json="$diagnostics_dir/job-$job_id.json"
job_deadline=$((SECONDS + job_timeout))
while :; do
    if ! docker exec "$container_name" openqa-cli api --host http://localhost \
        "jobs/$job_id" >"$job_json" 2>>"$schedule_log"; then
        echo "Could not query local openQA job $job_id" >>"$schedule_log"
        exit 1
    fi

    job_state=$(jq -r '(.job // .).state // empty' "$job_json")
    job_result=$(jq -r '(.job // .).result // empty' "$job_json")
    printf 'job=%s state=%s result=%s\n' "$job_id" "${job_state:-unknown}" "${job_result:-unknown}" \
        | tee "$diagnostics_dir/job-status-$job_id.log"
    case "$job_state" in
        done|cancelled|obsolete)
            if [[ "$job_state" == d* ]]; then
                if [[ "$job_result" == passed ]]; then
                    printf 'Local openQA job %s finished with %s\n' "$job_id" "$job_result" | tee -a "$schedule_log"
                    exit 0
                fi
            fi
            printf 'Local openQA job %s did not pass: state=%s result=%s\n' \
                "$job_id" "$job_state" "${job_result:-unknown}" | tee -a "$schedule_log" >&2
            exit 1
            ;;
    esac
    ((SECONDS < job_deadline)) || {
        echo "Local openQA job $job_id exceeded the monitoring timeout" | tee -a "$schedule_log" >&2
        exit 1
    }
    sleep "$poll_interval"
done
