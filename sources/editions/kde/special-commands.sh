#!/bin/bash
#
# Runs from the repository root. The workflow invokes this with bash, so it
# does not inherit the step's -e: without this line a failed sed is invisible
# and a half-built profile gets committed.
set -euo pipefail

# Graft four sections of Manjaro's own KDE Packages-Desktop onto ours.
#
# Packages-Desktop is the one list with no Manjaro base: the workflow writes
# Desktop-add over it instead of appending to upstream. These four sections are
# the parts we do want verbatim from upstream -- this is where xorg-server and
# the printing stack come from, so look here before concluding a package is
# missing from Desktop-add.
#
# Sections run from an exact header down to the first blank line (including
# whitespace-only lines). Validate every section before appending any of them:
# a renamed header must not silently produce an incomplete desktop profile.
upstreamDesktop=manjaro-iso-profiles/manjaro/kde/Packages-Desktop
generatedDesktop=biglinux/kde/Packages-Desktop

sections=(
    "## Printing"
    "## Xorg Server and Graphics"
    "## Xorg Input Drivers"
    "## Misc"
)
sectionContents=()
for section in "${sections[@]}"; do
    content=$(sed -n "/^${section}[[:space:]]*$/,/^[[:space:]]*$/p" "$upstreamDesktop")
    if [[ -z "$content" ]]; then
        printf 'ERROR: missing section "%s" in %s\n' "$section" "$upstreamDesktop" >&2
        exit 1
    fi
    # Upstream legitimately leaves Misc empty. The three essential sections
    # must still carry package entries, not just a header and comments.
    if [[ "$section" != "## Misc" ]] && ! grep -q '^[[:space:]]*[^#[:space:]]' <<< "$content"; then
        printf 'ERROR: no packages in section "%s" in %s\n' "$section" "$upstreamDesktop" >&2
        exit 1
    fi
    sectionContents+=("$content")
done
# Command substitution strips trailing newlines; restore the section separator.
printf '%s\n\n' "${sectionContents[@]}" >> "$generatedDesktop"

# Came in with "## Xorg Input Drivers" above and is not wanted: the void driver
# claims input devices and nothing uses it. Anchored so it cannot match a
# longer package name.
sed -i '/^xf86-input-void$/d' "$generatedDesktop"
