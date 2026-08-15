#!/bin/bash
#
# set-biglinux-branch.sh - ship the BigLinux testing repository in the ISO when
#                          the ISO was built from it
#
# BigLinux branches are additive, unlike Manjaro's: enabling testing does not
# replace stable, it is inserted above it so testing wins where it has a package
# and stable still answers for everything else. build-iso.sh already does that
# for the build itself:
#
#   testing)
#       add_biglinux_testing | sudo tee -a "$config_file"
#       add_biglinux_stable  | sudo tee -a "$config_file"
#
# The profile's pacman.conf, however, only ever ships [biglinux-stable]. A
# testing ISO would therefore install and then update from stable alone, so the
# user never receives the testing packages the ISO was built with.
#
# Insert the section in the cloned profile before buildiso runs, keeping stable
# below it. With BIGLINUX_BRANCH=stable this is a no-op.
#
# The `$arch` inserted into pacman.conf is pacman's own variable and must reach
# the file unexpanded; the sed call below says how it survives.
set -euo pipefail

: "${BIGLINUX_BRANCH:?BIGLINUX_BRANCH must be set}"
: "${PROFILE_PATH_EDITION:?PROFILE_PATH_EDITION must be set}"

# The same host build-iso.sh installs the build from, so a fork that builds from
# its own repositories also ships an ISO that updates from them. build-iso.sh
# owns the default and exports it; required here rather than repeated, so the
# two can never name different hosts.
: "${BIGLINUX_REPO_HOST:?BIGLINUX_REPO_HOST must be set}"

case "$BIGLINUX_BRANCH" in
    stable)
        echo "  -> BigLinux stable: pacman.conf already ships [biglinux-stable]"
        exit 0
        ;;
    testing) ;;
    *)
        # build-iso.sh's add_repositories_to_pacman only knows stable and
        # testing, so any other value would build with no BigLinux repository at
        # all. Fail here rather than ship a mismatched ISO.
        echo "unsupported BigLinux branch: $BIGLINUX_BRANCH" >&2
        exit 1
        ;;
esac

patched=0
for overlay in root live; do
    conf="$PROFILE_PATH_EDITION/$overlay-overlay/etc/pacman.conf"
    [[ -f "$conf" ]] || continue

    if grep -q '^\[biglinux-testing\]' "$conf"; then
        echo "  -> $overlay-overlay pacman.conf already has [biglinux-testing]"
        patched=$((patched + 1))
        continue
    fi

    if ! grep -q '^\[biglinux-stable\]' "$conf"; then
        echo "no [biglinux-stable] section to insert above in $conf" >&2
        exit 1
    fi

    # Above [biglinux-stable], so testing takes precedence and stable remains.
    #
    # Double quotes, unlike the rest of this file, because the host has to be
    # interpolated. That makes every line ending significant: `\\` reaches sed
    # as the backslash its insert command needs, and `\$arch` reaches pacman.conf
    # as the literal `$arch` pacman expands. Plain `\` would be eaten here as a
    # line continuation and sed would see a one-line insert.
    sed -i "/^\[biglinux-stable\]/i\\
[biglinux-testing]\\
SigLevel = PackageRequired\\
Server = https://$BIGLINUX_REPO_HOST/testing/\$arch\\
" "$conf"

    testing_line=$(grep -n '^\[biglinux-testing\]' "$conf" | cut -d: -f1)
    stable_line=$(grep -n '^\[biglinux-stable\]' "$conf" | cut -d: -f1)
    if [[ -z "$testing_line" || -z "$stable_line" || "$testing_line" -ge "$stable_line" ]]; then
        echo "failed to insert [biglinux-testing] above [biglinux-stable] in $conf" >&2
        exit 1
    fi
    echo "  -> $overlay-overlay pacman.conf: [biglinux-testing] above [biglinux-stable]"
    patched=$((patched + 1))
done

if [[ $patched -eq 0 ]]; then
    echo "no pacman.conf found under $PROFILE_PATH_EDITION" >&2
    exit 1
fi
