#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: schedule-release-gate.sh

Schedules and monitors the mandatory BIOS and UEFI plans through the openQA API.
EOF
}

(($# == 0)) || {
    usage >&2
    exit 2
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
openqa_cli="$script_dir/openqa-cli.sh"
scenario_file="$script_dir/../scenario-definitions.yaml"

: "${BIGLINUX_OPENQA_URL:?BIGLINUX_OPENQA_URL is required}"
: "${BIGLINUX_OPENQA_GROUP:?BIGLINUX_OPENQA_GROUP is required}"
: "${BIGLINUX_OPENQA_WORKER_CLASS:?BIGLINUX_OPENQA_WORKER_CLASS is required}"
: "${BIGLINUX_OPENQA_VERSION:?BIGLINUX_OPENQA_VERSION is required}"
: "${BIGLINUX_OPENQA_BUILD:?BIGLINUX_OPENQA_BUILD is required}"
: "${BIGLINUX_ISO_FILENAME:?BIGLINUX_ISO_FILENAME is required}"
: "${BIGLINUX_OPENQA_CASEDIR:?BIGLINUX_OPENQA_CASEDIR is required}"
: "${BIGLINUX_OPENQA_TEST_GIT_REFSPEC:?BIGLINUX_OPENQA_TEST_GIT_REFSPEC is required}"
: "${BIGLINUX_TEST_USER:?BIGLINUX_TEST_USER is required}"
: "${BIGLINUX_TEST_PASSWORD:?BIGLINUX_TEST_PASSWORD is required}"
: "${BIGLINUX_OPENQA_DIAGNOSTICS_DIR:?BIGLINUX_OPENQA_DIAGNOSTICS_DIR is required}"

[[ "$BIGLINUX_OPENQA_URL" =~ ^https://[^[:space:]/]+(/[^[:space:]]*)?$ ]] || {
    echo 'Invalid openQA URL' >&2
    exit 2
}
[[ "$BIGLINUX_OPENQA_GROUP" =~ ^[A-Za-z0-9_.-]+$ ]] || {
    echo 'Invalid openQA group' >&2
    exit 2
}
[[ "$BIGLINUX_OPENQA_WORKER_CLASS" =~ ^[A-Za-z0-9_.:-]+$ ]] || {
    echo 'Invalid worker class' >&2
    exit 2
}
[[ "$BIGLINUX_TEST_USER" =~ ^[A-Za-z0-9_.-]+$ ]] || {
    echo 'Invalid test user' >&2
    exit 2
}
[[ "$BIGLINUX_OPENQA_VERSION" =~ ^[A-Za-z0-9_.-]+$ ]] || {
    echo 'Invalid openQA version' >&2
    exit 2
}
[[ "$BIGLINUX_OPENQA_BUILD" =~ ^[A-Za-z0-9_.:-]+$ ]] || {
    echo 'Invalid openQA build' >&2
    exit 2
}
[[ "$BIGLINUX_ISO_FILENAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.iso$ ]] || {
    echo 'Invalid ISO filename' >&2
    exit 2
}
[[ "$BIGLINUX_OPENQA_TEST_GIT_REFSPEC" =~ ^[0-9a-f]{40}$ ]] || {
    echo 'Test refspec must be a full commit SHA' >&2
    exit 2
}
[[ "$BIGLINUX_OPENQA_CASEDIR" == *"#${BIGLINUX_OPENQA_TEST_GIT_REFSPEC}" ]] || {
    echo 'CASEDIR is not pinned to TEST_GIT_REFSPEC' >&2
    exit 2
}
[[ -f "$scenario_file" && -r "$scenario_file" ]] || {
    echo "Scenario definitions are missing: $scenario_file" >&2
    exit 1
}
[[ "$BIGLINUX_TEST_PASSWORD" != *$'\n'* && "$BIGLINUX_TEST_PASSWORD" != *$'\r'* ]] || {
    echo 'BIGLINUX_TEST_PASSWORD must not contain line breaks' >&2
    exit 2
}

poll_interval=${BIGLINUX_OPENQA_POLL_INTERVAL:-5}
schedule_timeout=${BIGLINUX_OPENQA_SCHEDULE_TIMEOUT:-300}
[[ "$poll_interval" =~ ^[1-9][0-9]*$ ]] || {
    echo 'BIGLINUX_OPENQA_POLL_INTERVAL must be a positive integer' >&2
    exit 2
}
[[ "$schedule_timeout" =~ ^[1-9][0-9]*$ ]] || {
    echo 'BIGLINUX_OPENQA_SCHEDULE_TIMEOUT must be a positive integer' >&2
    exit 2
}

mkdir -p -- "$BIGLINUX_OPENQA_DIAGNOSTICS_DIR"
password_file=$(mktemp "${RUNNER_TEMP:-/tmp}/biglinux-openqa-test-password.XXXXXX")
chmod 600 "$password_file"
printf '%s' "$BIGLINUX_TEST_PASSWORD" >"$password_file"
trap '[[ -f "$password_file" ]] && unlink -- "$password_file"' EXIT

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
    local response_file="$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/schedule-$firmware.json"
    local log_file="$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/schedule-$firmware.log"
    local status_file="$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/scheduled-product-$firmware.json"
    local scheduled_product_id status
    local -a job_ids=()

    printf 'Starting openQA plan: %s (%s)\n' "$test_suite" "$firmware" | tee "$log_file"
    if ! "$openqa_cli" api --host "$BIGLINUX_OPENQA_URL" -X POST isos \
        --param-file "SCENARIO_DEFINITIONS_YAML=$scenario_file" \
        --param-file "_SECRET_BIGLINUX_TEST_PASSWORD=$password_file" \
        async=1 \
        DISTRI=biglinux \
        "VERSION=$BIGLINUX_OPENQA_VERSION" \
        FLAVOR=Live \
        ARCH=x86_64 \
        "TEST=$test_suite" \
        "BIGLINUX_SCHEDULE=$biglinux_schedule" \
        "BIGLINUX_TEST_USER=$BIGLINUX_TEST_USER" \
        BIGLINUX_TEST_HOSTNAME=biglinux-openqa \
        BIGLINUX_RELEASE_GATE=1 \
        BIGLINUX_APPLICATION_FILTER='dolphin,libreoffice,gimp,brave,biglinux-control-center,control-center' \
        TIMEOUT_SCALE=1 \
        QEMU_NO_KVM=0 \
        "_GROUP=$BIGLINUX_OPENQA_GROUP" \
        "WORKER_CLASS=$BIGLINUX_OPENQA_WORKER_CLASS" \
        "BUILD=$plan_build" \
        "ISO=$BIGLINUX_ISO_FILENAME" \
        "CASEDIR=$BIGLINUX_OPENQA_CASEDIR" \
        PRODUCTDIR=openqa \
        NEEDLES_DIR='%%CASEDIR%%/openqa/needles' \
        SERIALDEV=hvc0 \
        "TEST_GIT_REFSPEC=$BIGLINUX_OPENQA_TEST_GIT_REFSPEC" \
        >"$response_file" 2>>"$log_file"; then
        echo 'openQA API scheduling request failed' >>"$log_file"
        return 1
    fi
    cat "$response_file" >>"$log_file"
    jq -e 'type == "object"' "$response_file" >/dev/null || {
        echo 'openQA scheduling response is not valid JSON' >>"$log_file"
        return 1
    }

    scheduled_product_id=$(jq -r '.scheduled_product_id // empty' "$response_file")
    if [[ -z "$scheduled_product_id" ]]; then
        jq -e '.ids or .id' "$response_file" >/dev/null || {
            echo 'openQA scheduling response has no job or scheduled-product ID' >>"$log_file"
            return 1
        }
        mapfile -t job_ids < <(jq -r '(.ids // [])[]?, (.id // empty)' "$response_file" | sort -nu)
    else
        deadline=$((SECONDS + schedule_timeout))
        while :; do
            if ! "$openqa_cli" api --host "$BIGLINUX_OPENQA_URL" "isos/$scheduled_product_id" \
                >"$status_file" 2>>"$log_file"; then
                echo "could not query scheduled product $scheduled_product_id" >>"$log_file"
                return 1
            fi
            status=$(jq -r '.status // empty' "$status_file")
            case "$status" in
                scheduled)
                    mapfile -t job_ids < <(
                        jq -r '.results.successful_job_ids[]? // empty' "$status_file" | sort -nu
                    )
                    break
                    ;;
                added|scheduling)
                    ((SECONDS < deadline)) || {
                        echo "scheduled product $scheduled_product_id did not become scheduled" >>"$log_file"
                        return 1
                    }
                    sleep "$poll_interval"
                    ;;
                *)
                    echo "scheduled product $scheduled_product_id ended in state: $status" >>"$log_file"
                    return 1
                    ;;
            esac
        done
    fi

    ((${#job_ids[@]} > 0)) || {
        echo 'openQA returned no successful job IDs' >>"$log_file"
        return 1
    }
    printf '%s\n' "${job_ids[@]}" | sort -nu >"$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids-$firmware.txt"
    printf 'Scheduled %s job IDs: %s\n' "$firmware" "${job_ids[*]}" >>"$log_file"
}

declare -A plan_pids=()
for plan_line in "${plan_lines[@]}"; do
    IFS=$'\t' read -r _test _schedule firmware <<<"$plan_line"
    schedule_plan "$plan_line" &
    plan_pids["$firmware"]=$!
done

status=0
for firmware in bios uefi; do
    if ! wait "${plan_pids[$firmware]}"; then
        status=1
    fi
done

: >"$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids.txt"
for firmware in bios uefi; do
    ids_file="$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids-$firmware.txt"
    [[ -f "$ids_file" ]] || continue
    cat "$ids_file" >>"$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids.txt"
done
sort -nu -o "$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids.txt" "$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids.txt"

if [[ -s "$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids.txt" ]]; then
    mapfile -t all_job_ids <"$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/job-ids.txt"
    if ! "$openqa_cli" monitor --host "$BIGLINUX_OPENQA_URL" \
        --poll-interval "$poll_interval" "${all_job_ids[@]}" \
        >"$BIGLINUX_OPENQA_DIAGNOSTICS_DIR/monitor.log" 2>&1; then
        status=1
    fi
else
    echo 'No openQA job IDs were returned by the API' >&2
    status=1
fi

exit "$status"
