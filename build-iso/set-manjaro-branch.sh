#!/bin/bash
#
# set-manjaro-branch.sh - point the shipped CDN mirrors at the branch the ISO
#                         was actually built from
#
# The profile ships /etc/pacman.d/mirrorcdn with the branch hardcoded to
# "stable", and its pacman.conf includes mirrorcdn BEFORE mirrorlist:
#
#   [core]
#   Include = /etc/pacman.d/mirrorcdn      <- wins
#   Include = /etc/pacman.d/mirrorlist
#
# manjaro-tools writes the right branch into /etc/pacman-mirrors.conf, so
# mirrorlist is regenerated correctly, but the hardcoded CDN entries take
# precedence. A testing or unstable ISO would therefore install and then update
# from stable, mixing two branches on the user's disk.
#
# Rewrite the branch segment instead, in the cloned profile, before buildiso
# runs. With MANJARO_BRANCH=stable this is a no-op.
#
set -euo pipefail

: "${MANJARO_BRANCH:?MANJARO_BRANCH must be set}"
: "${PROFILE_PATH_EDITION:?PROFILE_PATH_EDITION must be set}"

case "$MANJARO_BRANCH" in
    stable|testing|unstable) ;;
    *) echo "unknown Manjaro branch: $MANJARO_BRANCH" >&2; exit 1 ;;
esac

patched=0
for overlay in root live; do
    conf="$PROFILE_PATH_EDITION/$overlay-overlay/etc/pacman.d/mirrorcdn"
    [[ -f "$conf" ]] || continue

    # The branch is the path segment right before /$repo/$arch, which is the one
    # shape all three CDN entries share. The delimiter must not be '|': sed reads
    # \| as an escaped delimiter, not as BRE alternation.
    sed -i "s#/\(stable\|testing\|unstable\)/\$repo/\$arch#/$MANJARO_BRANCH/\$repo/\$arch#g" "$conf"

    if grep -q "/\$repo/\$arch" "$conf" && ! grep -q "/$MANJARO_BRANCH/\$repo/\$arch" "$conf"; then
        echo "failed to set the branch in $conf" >&2
        exit 1
    fi
    echo "  -> $overlay-overlay mirrorcdn now on $MANJARO_BRANCH"
    patched=$((patched + 1))
done

if [[ $patched -eq 0 ]]; then
    echo "no mirrorcdn found under $PROFILE_PATH_EDITION" >&2
    exit 1
fi
