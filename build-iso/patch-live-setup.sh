#!/bin/bash
#
# patch-live-setup.sh - run manjaro-live-setup, then verify it produced a
#                       usable live home
#
# manjaro-live-base 20260722 moved live-user creation OUT of the boot-time
# manjaro-live.service and INTO manjaro-live-setup, which manjaro-tools r3071
# runs inside the livefs chroot at build time. /usr/bin/manjaro-live now only
# handles console font, locale and samba, so skipping the build-time call would
# leave the ISO with no live user at all.
#
# The build-time call is therefore kept. What it needs is checking: on the CI
# build filesystem `useradd -m` could not copy /etc/skel across the livefs
# overlayfs, and said so without failing:
#
#   -> Call manjaro-live-setup ...
#   useradd: /etc/skel/.bash_logout: Bad file descriptor
#   Created user biglinux with password biglinux: 0.062ms
#
# The live home was then missing the big-skel Plasma configuration, and the
# session booted to a black screen with no plasmashell. Re-sync skel afterwards
# and fail the build when the home still does not match, so a broken ISO is
# never published.
#
# Runs after build-iso.sh has (re)installed manjaro-tools, and mirrors what the
# local generator (gitrepo / Build ISO GUI) does before every build.
#
# The `$1` in the sed programs below belongs to the manjaro-tools function being
# patched, not to this script: it must reach the file unexpanded.
# shellcheck disable=SC2016
set -euo pipefail

image_lib=/usr/lib/manjaro-tools/util-iso-image.sh
[[ -f "$image_lib" ]] || exit 0

# Idempotent: build-iso.sh may reinstall manjaro-tools and re-run this patch in
# one job, and appending the function twice would break the library.
if grep -q '^mkiso_live_setup()' "$image_lib"; then
    exit 0
fi

cat >> "$image_lib" <<'MKISO_LIVE_SETUP'

# Added by BigLinux: see build-iso/patch-live-setup.sh in the iso-profiles repository.
mkiso_live_setup() {
    local path=$1 user home entry

    if [[ ! -x "$path/usr/bin/manjaro-live-setup" ]]; then
        # Older manjaro-live-base creates the live user at boot instead.
        msg2 "Skipping manjaro-live-setup (absent from livefs)"
        return 0
    fi

    chroot "$path" /usr/bin/manjaro-live-setup
    if [[ -f "$path/var/log/manjaro-live-setup.log" ]]; then
        chroot "$path" cat /var/log/manjaro-live-setup.log
    fi

    user=$(sed -n 's|^username=||p' "$path/etc/manjaro-tools/live.conf" | tail -n1)
    if [[ -z "$user" ]]; then
        error "live.conf declares no username; cannot verify the live home"
        return 1
    fi

    home="$path/home/$user"
    if [[ ! -d "$home" ]]; then
        error "manjaro-live-setup did not create /home/%s" "$user"
        return 1
    fi

    msg2 "Re-syncing /etc/skel into /home/%s" "$user"
    if ! cp -a "$path/etc/skel/." "$home/"; then
        error "could not copy /etc/skel into /home/%s" "$user"
        return 1
    fi
    chroot "$path" chown -R "$user:$user" "/home/$user"

    for entry in "$path/etc/skel"/* "$path/etc/skel"/.[!.]*; do
        [[ -e "$entry" ]] || continue
        if [[ ! -e "$home/${entry##*/}" ]]; then
            error "skel entry %s never reached /home/%s" "${entry##*/}" "$user"
            return 1
        fi
    done
}
MKISO_LIVE_SETUP

sed -i \
    -e 's|^\([[:space:]]*\)chroot \$1 /usr/bin/manjaro-live-setup$|\1mkiso_live_setup "$1"|' \
    -e 's|^\([[:space:]]*\)chroot \$1 cat /var/log/manjaro-live-setup.log$|\1:|' \
    "$image_lib"

# The unchecked upstream call must be gone and ours must be in place; otherwise
# the build could ship another black-screen ISO.
#
# Not written as `! grep -q ...`: POSIX ignores errexit for a pipeline starting
# with `!`, so that form would report nothing and let a failed substitution
# through. Same reason build-iso.sh has assert_absent().
if grep -q 'chroot \$1 /usr/bin/manjaro-live-setup' "$image_lib"; then
    echo "the unchecked manjaro-live-setup call is still in $image_lib" >&2
    exit 1
fi
grep -q 'mkiso_live_setup "\$1"' "$image_lib"
