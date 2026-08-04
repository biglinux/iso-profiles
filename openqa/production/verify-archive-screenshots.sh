#!/usr/bin/env bash
set -euo pipefail

: "${BIGLINUX_OPENQA_RESULTS_DIR:?BIGLINUX_OPENQA_RESULTS_DIR is required}"
[[ -d "$BIGLINUX_OPENQA_RESULTS_DIR" ]] || {
    echo "Missing openQA results directory: $BIGLINUX_OPENQA_RESULTS_DIR" >&2
    exit 1
}

invalid=0
while IFS= read -r -d '' screenshot; do
    signature=$(od -An -tx1 -N8 -- "$screenshot" | tr -d '[:space:]')
    if [[ "$signature" != 89504e470d0a1a0a ]]; then
        size=$(stat --printf='%s' -- "$screenshot")
        file_type=$(file -b -- "$screenshot" 2>/dev/null || printf 'unknown')
        printf 'Archived screenshot is not a PNG: path=%s size=%s type=%s\n' \
            "$screenshot" "$size" "$file_type" >&2
        invalid=1
    fi
done < <(find "$BIGLINUX_OPENQA_RESULTS_DIR" -type f -name '*.png' -print0)

((invalid == 0))
