#!/usr/bin/env bash
#
# build-iso.sh - ISO build engine for BigLinux and BigCommunity
#
# Lives inside iso-profiles so the profiles and the code that interprets them
# (KERNEL placeholders, labels, overlays) always change together. It builds
# from the checkout it is part of: clone iso-profiles, run this script inside
# the build container, take the ISO from the output directory. The profile
# files are edited in place, so build from a disposable clone.
#
# Quickstart (as root, inside the build container):
#
#   bash build-iso/build-iso.sh kde
#
# Everything else has a sane default, declared in the inputs section below.
# Outside the container, use build-iso/build-local.sh instead. The variable
# table, the stage walkthrough and the troubleshooting notes are in
# build-iso/README.md; main() at the bottom is the order things happen in.
#
# bigcommunity support follows the previous generators (talesam/build-iso and
# gitrepo) but still needs a real community build to be validated.
#
# Single quotes are load-bearing here: a `$arch` in a pacman.conf Server line and
# a `$1` in a generated sed program are read by pacman and manjaro-tools, not by
# this shell, so shellcheck's "did you mean double quotes?" is wrong throughout.
# shellcheck disable=SC2016
set -euo pipefail

scriptDir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Written by one stage and read by a later one. Declared here because bash gives
# no other signal that main()'s stage order is load-bearing: move collect_output
# above run_build and the failure is an empty file name, not an error.
KERNEL_NAME=""    # set by resolve_kernel; read by configure_profile, run_build, collect_output
ISO_BASENAME=""   # set by collect_output; read by main's closing message

msg() { printf '\n==> %s\n' "$*"; }
die() { printf 'build-iso.sh: error: %s\n' "$*" >&2; exit 1; }

# Assert that a pattern is NOT in a set of files.
#
# `! grep -q ...` cannot do this: POSIX says errexit is ignored for a pipeline
# starting with `!`, so a failed negative assertion is silently skipped and the
# build carries on. Written as an if/die, the failure actually stops the build.
assert_absent() {
    local pattern="$1"
    shift
    if grep -q "$pattern" "$@"; then
        die "unexpected '$pattern' still present in: $*"
    fi
}

# Assert that a pattern IS in a file, right after the sed that should have put
# it there. A bare `grep -q` does stop the build under errexit, but it stops it
# with exit code 1 and no message, an hour in; this names the pattern and the
# file that disagree.
assert_present() {
    local pattern="$1"
    shift
    grep -q "$pattern" "$@" || die "expected '$pattern' in: $*"
}

# `$arch` is pacman's variable, not ours: the format string stays single-quoted and
# the caller passes the URL without it.
repo_section() {
    local config_file="$1" name="$2" url_base="$3"
    printf '[%s]\nSigLevel = PackageRequired\nServer = %s/$arch\n\n' \
        "$name" "$url_base" >>"$config_file"
}

# The container reads this file; mkchroot replaces it in the chroots with the
# single BUILD_MIRROR Server. Writing BUILD_MIRROR here too gives the whole
# build one package source. `$repo` and `$arch` are pacman's variables.
write_build_mirrorlist() {
    local mirrorlist="${1:-/etc/pacman.d/mirrorlist}"
    install -dm755 "$(dirname "$mirrorlist")"
    printf '## Written by build-iso.sh: the build mirror, so that the container\n## and the ISO chroots resolve packages from the same source.\nServer = %s/%s/$repo/$arch\n' \
        "$BUILD_MIRROR" "$MANJARO_BRANCH" >"$mirrorlist"
}

#--- inputs -------------------------------------------------------------------

# Every input, with its default. Reading these into globals is a function rather
# than top-level code so that `source build-iso.sh` has no effect and the tests
# can call the stages instead of matching this file's text.
read_inputs() {
    # First, as before, so that an unreadable checkout is reported ahead of a
    # missing edition.
    #
    # The profiles are this checkout unless PROFILES_ROOT points elsewhere -- the
    # engine still runs from here. That split exists for gitrepo, which builds
    # bigcommunity profiles before big-comm ships this directory of its own.
    PROFILES_ROOT="${PROFILES_ROOT:-$(cd "$scriptDir/.." && pwd)}"

    EDITION="${EDITION:-${1:-}}"
    [[ -n "$EDITION" ]] || die "no edition given (e.g.: bash build-iso/build-iso.sh kde)"

    # A selector; resolve_kernel turns it into linux612 or linux-xanmod.
    KERNEL="${KERNEL:-lts}"
    MANJARO_BRANCH="${MANJARO_BRANCH:-stable}"
    # testing is inserted above stable, not instead of it.
    BIGLINUX_BRANCH="${BIGLINUX_BRANCH:-stable}"
    BIGCOMMUNITY_BRANCH="${BIGCOMMUNITY_BRANCH:-stable}"
    RELEASE_TAG="${RELEASE_TAG:-$(date +%Y-%m-%d)}"
    WORK_PATH="${WORK_PATH:-$PROFILES_ROOT/output}"

    # mkchroot replaces the mirrorlist Include with this one Server, so it decides the
    # whole Manjaro package set. Unset, manjaro-tools picks mirror.easyname.at, which
    # lags behind stable.
    #
    # manjaro-tools appends `/$branch/$repo/$arch` to this value, so a trailing
    # slash produces `repo//stable/core/...`. Behind a CDN that empty path segment
    # is a cache key of its own, holding a copy of core.db nothing refreshes: the
    # build resolves package versions that were current weeks ago and then 404s
    # fetching them, an hour in. Normalised here so no caller can reintroduce it.
    BUILD_MIRROR="${BUILD_MIRROR:-http://mirrors.manjaro.org/repo}"
    while [[ "$BUILD_MIRROR" == */ ]]; do
        BUILD_MIRROR="${BUILD_MIRROR%/}"
    done

    # Overridable so a fork builds from its own repositories.
    BIGLINUX_REPO_HOST="${BIGLINUX_REPO_HOST:-repo.biglinux.com.br}"
    COMMUNITY_REPO_HOST="${COMMUNITY_REPO_HOST:-repo.communitybig.org}"

    # Days since the epoch, not seconds, despite the name.
    UNIX_TIMESTAMP="${UNIX_TIMESTAMP:-$(($(date +%s) / 86400))}"

    # Which distribution these profiles describe, detected from the layout.
    if [[ -z "${DISTRONAME:-}" ]]; then
        if [[ -d "$PROFILES_ROOT/bigcommunity" ]]; then
            DISTRONAME="bigcommunity"
        elif [[ -d "$PROFILES_ROOT/biglinux" ]]; then
            DISTRONAME="biglinux"
        else
            die "no biglinux/ or bigcommunity/ profile directory in $PROFILES_ROOT"
        fi
    fi

    PROFILE_PATH_EDITION="$PROFILES_ROOT/$DISTRONAME/$EDITION"
    # Live volume id; profile.conf label, kernels.cfg misolabel and manjaro-tools
    # iso_label must all carry this same value or the live medium will not mount.
    VOL_ID="${DISTRONAME^^}_LIVE_${EDITION^^}"

    # The branch as asked for. collect_output is its only reader: it is what
    # separates a DEVELOPMENT ISO from a TESTING one in the published name.
    case "$DISTRONAME" in
        biglinux) REQUESTED_BRANCH="$BIGLINUX_BRANCH" ;;
        bigcommunity) REQUESTED_BRANCH="$BIGCOMMUNITY_BRANCH" ;;
        *) die "unknown DISTRONAME: $DISTRONAME (biglinux or bigcommunity)" ;;
    esac

    # `development` is a name, not a repository set: BigLinux publishes no
    # development repository, so such a build installs from testing. Normalising
    # here means the repositories, the helper scripts, the compression level and
    # /etc/big-release all keep seeing the two branches they already handle.
    DISTRO_BRANCH="$REQUESTED_BRANCH"
    if [[ "$DISTRO_BRANCH" == "development" ]]; then
        DISTRO_BRANCH="testing"
    fi
    case "$DISTRONAME" in
        biglinux) BIGLINUX_BRANCH="$DISTRO_BRANCH" ;;
        bigcommunity) BIGCOMMUNITY_BRANCH="$DISTRO_BRANCH" ;;
    esac

    # The helper scripts read these. BIGLINUX_REPO_HOST is among them so that the
    # repositories the ISO ships follow the repositories it was built from.
    export MANJARO_BRANCH BIGLINUX_BRANCH BIGLINUX_REPO_HOST PROFILE_PATH_EDITION
}

# Everything that can be rejected before a single package is downloaded. The
# order is the order the failures were reported in before this was a function.
validate_inputs() {
    local mirror_url_pattern='^https?://[A-Za-z0-9._~-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~-]+)*/?$'

    [[ $EUID -eq 0 ]] || die "must run as root (inside the build container)"

    [[ $BUILD_MIRROR =~ $mirror_url_pattern ]] \
        || die "BUILD_MIRROR must be an http(s) URL without shell syntax: $BUILD_MIRROR"
    case "$MANJARO_BRANCH" in
        stable | testing | unstable) ;;
        *) die "unknown Manjaro branch: $MANJARO_BRANCH" ;;
    esac
    # The distribution's own branch reaches here already normalised, so only a
    # value read_inputs did not recognise can still be `development` -- and an
    # unknown one is unchanged either way, which is what these reject. Both are
    # checked, including the branch this build does not use: a typo in it is a
    # mistake worth reporting rather than ignoring.
    case "$BIGLINUX_BRANCH" in
        stable | testing | development) ;;
        *) die "unknown BigLinux branch: $BIGLINUX_BRANCH" ;;
    esac
    case "$BIGCOMMUNITY_BRANCH" in
        stable | testing | development) ;;
        *) die "unknown BigCommunity branch: $BIGCOMMUNITY_BRANCH" ;;
    esac
    [[ -d "$PROFILE_PATH_EDITION" ]] || die "profile not found: $PROFILE_PATH_EDITION"

    # Here rather than at move time: fail in a second, not after the build.
    mkdir -p "$WORK_PATH" || die "cannot create WORK_PATH: $WORK_PATH"
}

#--- kernel -------------------------------------------------------------------

# kernel.org lists longterm series newest first; $1 picks which one.
# Prints the version digits without the dot (6.12 -> 612).
kernel_org_longterm() {
    curl -fsS https://www.kernel.org/feeds/kdist.xml \
        | grep ": longterm" \
        | sed -n 's/.*<title>\(.*\): longterm<\/title>.*/\1/p' \
        | rev | cut -d "." -f2,3 | rev \
        | sed 's/\.//g' | sed -n "${1}p"
}

resolve_kernel() {
    msg "Resolving kernel selector: $KERNEL"
    case "$KERNEL" in
        oldlts) KERNEL_NAME=$(kernel_org_longterm 2) ;;
        lts) KERNEL_NAME=$(kernel_org_longterm 1) ;;
        latest)
            # linux-latest is a meta package; its kernelver names the real
            # Manjaro kernel package (kernelver=71 -> linux71).
            KERNEL_NAME=$(curl -fsS https://raw.githubusercontent.com/biglinux/linux-latest/stable/PKGBUILD \
                | awk -F= '/^kernelver=/{print $2}')
            ;;
        xanmod | xanmod-lts)
            # BigLinux packages these as linux-xanmod / linux-xanmod-lts, with
            # the same module set the placeholders expand to. The version is
            # only known after the build, from the .pkgs list.
            KERNEL_NAME="-${KERNEL}"
            ;;
        *) die "unsupported kernel selector: $KERNEL (use oldlts, lts, latest, xanmod or xanmod-lts)" ;;
    esac
    [[ "$KERNEL_NAME" =~ ^[0-9][0-9][0-9]?$ || "$KERNEL_NAME" == -xanmod* ]] \
        || die "could not resolve '$KERNEL' to a kernel version (got: '$KERNEL_NAME')"
    msg "Kernel package: linux${KERNEL_NAME}"
}

#--- container preparation ----------------------------------------------------

prepare_host() {
    # Before the first download. This used to be `pacman-mirrors --fasttrack 5`,
    # which ranked five mirrors for the container while the chroots installed
    # from BUILD_MIRROR: two package sources in one build, so a database synced
    # from a mirror the CDN has not caught up with resolves versions the build
    # then fails to fetch. One source answers both.
    msg "Building from the mirror: $BUILD_MIRROR"
    write_build_mirrorlist

    msg "Updating the container and installing build tools"
    if [[ "$DISTRONAME" == "bigcommunity" ]] \
        && ! grep -q '^\[community-extra\]' /etc/pacman.conf; then
        # Community build tools live in this repository, and the container needs
        # them before the chroots exist -- hence /etc/pacman.conf, not the
        # manjaro-tools configuration the chroots use.
        repo_section /etc/pacman.conf community-extra "https://$COMMUNITY_REPO_HOST/extra"
    fi
    pacman -Syu --noconfirm
    pacman -S --quiet --needed --noconfirm \
        archiso btrfs-progs calamares calamares-tools cdrkit \
        manjaro-tools-base-git manjaro-tools-iso-git \
        manjaro-tools-pkg-git manjaro-tools-yaml-git \
        mkinitcpio mktorrent squashfs-tools

    msg "Installing the pacman keyrings"
    rm -rf /tmp/biglinux-key
    git clone --depth 1 https://github.com/biglinux/biglinux-key.git /tmp/biglinux-key
    install -dm755 /etc/pacman.d/gnupg/
    install -m0644 /tmp/biglinux-key/usr/share/pacman/keyrings/* /etc/pacman.d/gnupg/
    rm -rf /tmp/biglinux-key
    if [[ "$DISTRONAME" == "bigcommunity" ]]; then
        rm -rf /tmp/community-keyring
        git clone --depth 1 https://github.com/big-comm/community-keyring.git /tmp/community-keyring
        install -m0644 /tmp/community-keyring/community.gpg /usr/share/pacman/keyrings/
        install -m0644 /tmp/community-keyring/community-trusted /usr/share/pacman/keyrings/
        install -m0644 /tmp/community-keyring/community-revoked /usr/share/pacman/keyrings/
        rm -rf /tmp/community-keyring
    fi
    pacman-key --init
    pacman-key --populate
    pacman -Sy --quiet --noconfirm

    # Old-style alpm hook triggers break current pacman inside the chroot.
    sed -i -e 's/File/Path/' /usr/share/libalpm/hooks/*hook* 2>/dev/null || true

    # Loop and optical device nodes needed by mksquashfs/xorriso. A container
    # image ships no device nodes, and every one of these may already exist
    # when the runner passes the host's /dev through -- hence `|| true`.
    mknod -m 660 /dev/sr0 b 11 0 2>/dev/null || true
    for i in $(seq 0 7); do
        mknod -m 660 "/dev/loop$i" b 7 "$i" 2>/dev/null || true
    done
    mknod -m 660 /dev/loop-control c 10 237 2>/dev/null || true

    # manjaro-tools reads this file before applying its own defaults, so the
    # branding, mirror and compression need no patching of /usr/lib. Runtime
    # state of this disposable container, rewritten on every build.
    msg "Writing the manjaro-tools configuration"
    mkdir -p "$HOME/.config/manjaro-tools"
    cat >"$HOME/.config/manjaro-tools/manjaro-tools.conf" <<EOF
dist_name=$DISTRONAME
iso_name=$DISTRONAME
dist_branding=$DISTRONAME
build_mirror=$BUILD_MIRROR
iso_compression=zstd
EOF
    cat "$HOME/.config/manjaro-tools/manjaro-tools.conf"
    # Point buildiso at the profiles checkout.
    printf 'run_dir=%s\n' "$PROFILES_ROOT" >"$HOME/.config/manjaro-tools/iso-profiles.conf"

    # Git may reject a checkout mounted into this root-owned container when the
    # host runner owns it. Trust only the profile directory passed to this build;
    # buildiso uses Git there to validate the profiles.
    git config --global --add safe.directory "$PROFILES_ROOT"

    msg "Cleaning previous build state"
    rm -rf /var/lib/manjaro-tools/buildiso/* /var/cache/manjaro-tools/iso/* 2>/dev/null || true
    mkdir -p /var/cache/manjaro-tools/iso
    chmod 1777 /var/cache/manjaro-tools/iso
}

#--- build repositories -------------------------------------------------------

# Also written into the profile's own pacman.conf, so the order lives here only.
append_community_repos() {
    local config_file="$1"
    if [[ "$BIGCOMMUNITY_BRANCH" == "testing" ]]; then
        repo_section "$config_file" community-testing "https://$COMMUNITY_REPO_HOST/testing"
    fi
    repo_section "$config_file" community-stable "https://$COMMUNITY_REPO_HOST/stable"
    repo_section "$config_file" community-extra "https://$COMMUNITY_REPO_HOST/extra"
}

# A BigCommunity system installs BigLinux packages, so the installed system
# needs these as much as the build does -- see configure_profile. Testing is
# conditional; stable always answers, and comes last because everything above
# it falls back to it.
append_biglinux_repos() {
    local config_file="$1"
    if [[ "$BIGLINUX_BRANCH" == "testing" ]]; then
        repo_section "$config_file" biglinux-testing "https://$BIGLINUX_REPO_HOST/testing"
    fi
    repo_section "$config_file" biglinux-stable "https://$BIGLINUX_REPO_HOST/stable"
}

# The repositories the *installed* system resolves packages from, in the same
# order the build uses. Separate from append_build_repos because the build also
# needs the development mirror and update-stable, which the profile's own
# pacman.conf already ships.
append_installed_repos() {
    local config_file="$1"
    append_community_repos "$config_file"
    append_biglinux_repos "$config_file"
}

# Appended highest priority first: pacman prefers the earliest section that has
# the package, so this order is why testing wins and stable still answers.
append_build_repos() {
    local config_file="$1"
    # Set only by development pipelines. First, so it outranks everything below.
    if [[ -n "${UNSTABLE_REPO_MIRROR:-}" ]]; then
        repo_section "$config_file" "bigiborg-${UNSTABLE_REPO_NAME:-}" \
            "https://$UNSTABLE_REPO_MIRROR"
    fi
    # The handful of packages held back from stable. Both distributions build
    # with it; until it was here, biglinux got it from the profile's
    # user-repos.conf instead -- see configure_build_repos for why that had to
    # stop.
    repo_section "$config_file" biglinux-update-stable \
        "https://$BIGLINUX_REPO_HOST/update-stable"
    if [[ "$DISTRONAME" == "bigcommunity" ]]; then
        append_community_repos "$config_file"
    fi
    append_biglinux_repos "$config_file"
}

configure_build_repos() {
    msg "Adding $DISTRONAME repositories to the build pacman configuration"
    local conf
    for conf in /usr/share/manjaro-tools/pacman-default.conf \
        /usr/share/manjaro-tools/pacman-multilib.conf; do
        append_build_repos "$conf"
        assert_present '^\[biglinux-stable\]' "$conf"
        # manjaro-tools ships this commented out; a chroot pulls hundreds of packages.
        sed -i -e '/ParallelDownloads/s/#//' \
            -e '/ParallelDownloads/s/ParallelDownloads =.*/ParallelDownloads = 10/' "$conf"
    done

    # manjaro-tools hands pacman `cat pacman-<arch>.conf user-repos.conf`, so a
    # repository the profile names as well as this function does is registered
    # twice: `could not register 'biglinux-stable' database`, mid-build, with the
    # profile's copy silently dropped. append_build_repos is the one owner of the
    # build's repository list, and the profiles are a disposable clone, so the
    # file goes rather than the two being kept in step forever.
    rm -f "$PROFILE_PATH_EDITION/user-repos.conf"

    # Development builds trade compression for speed; releases keep the
    # manjaro-tools default (level 20). Block size 1024K for both.
    if [[ "$DISTRO_BRANCH" != "stable" ]]; then
        sed -i 's/-Xcompression-level [0-9]\+/-Xcompression-level 7/g' /usr/lib/manjaro-tools/util-iso.sh
        assert_present 'Xcompression-level 7' /usr/lib/manjaro-tools/util-iso.sh
    fi
    sed -i 's/256K/1024K/g' /usr/lib/manjaro-tools/util-iso.sh
}

#--- manjaro-tools patches ----------------------------------------------------

# Image cleanups run on rootfs, desktopfs and livefs. Unlike upstream's
# cleanups, /usr/share/man is kept: BigLinux ships man pages.
add_image_cleanups() {
    local image="$1" iso="$2"

    assert_present '^configure_live_image(){' "$image"
    sed -i '/^configure_live_image(){$/a\    mkiso_build_iso_cleanups "$1"' "$image"

    cat >>"$image" <<'CLEANUPS'

# Added by BigLinux build-iso.sh
mkiso_build_iso_cleanups() {
    local cpath="$1"

    # Post-install removal, the other half of what a *-remove file means.
    #
    # Filtering the package lists only stops a package that the profile asks
    # for by name. Most of what these files name arrives as a dependency:
    # Packages-Root lists `vi`, the only provider is ex-vi-compat, and it
    # depends on vim -- so gnome and cinnamon shipped vim no matter what their
    # Desktop-remove said. pacman -Rdd is what removes it, after the install,
    # ignoring the dependency that pulled it in. Same as the previous
    # generator (talesam/build-iso), which is where this was lost.
    #
    # A missing package is normal, not an error: each list is applied to every
    # image, and a package removed from the rootfs is already gone in the
    # desktopfs built on top of it.
    local remove_dir="$cpath/var/lib/packages-remove"
    if [[ -d "$remove_dir" ]]; then
        local remove_file package
        for remove_file in "$remove_dir"/*-remove; do
            [[ -f "$remove_file" ]] || continue
            echo "[CLEANUP] applying $(basename "$remove_file")"
            while read -r package _; do
                [[ -n "$package" && "$package" != \#* ]] || continue
                if chroot "$cpath" pacman -Qi "$package" &> /dev/null; then
                    echo "[CLEANUP] removing $package"
                    chroot "$cpath" pacman -Rdd --noconfirm "$package" &> /dev/null ||
                        echo "[CLEANUP] could not remove $package"
                fi
            done < "$remove_file"
        done
        # The lists are build instructions; they must not reach the ISO.
        rm -rf "$remove_dir"
    fi

    rm -rf "$cpath/usr/share/doc"/* 2> /dev/null

    local libreoffice_path="$cpath/usr/lib/libreoffice/share/config"
    if [[ -d "$libreoffice_path" ]]; then
        rm -f "$libreoffice_path"/images_{karasa_jaga,elementary,sukapura}* 2> /dev/null
        rm -f "$libreoffice_path"/images_{colibre,sifr_dark,sifr,breeze_dark,breeze}_svg.zip 2> /dev/null
    fi

    local wallpapers_path="$cpath/usr/share/wallpapers"
    if [[ -d "$wallpapers_path" ]]; then
        rm -rf "$wallpapers_path"/{Altai,BytheWater,Cascade,ColdRipple,DarkestHour,EveningGlow,Flow,FlyingKonqui,IceCold,Kokkini,Next,Opal,Patak,SafeLanding,summer_1am,Autumn,Canopee,Cluster,ColorfulCups,Elarun,FallenLeaf,Fluent,Grey,Kite,MilkyWay,OneStandsOut,PastelHills,Path,Shell,Volna}
    fi
    return 0
}
CLEANUPS

    # Also run on rootfs and desktopfs, not only on the live image.
    sed -i '/^make_image_root()/,/^}$/{/reset_pac_conf.*\${path}/i\        mkiso_build_iso_cleanups "${path}"
}' "$iso"
    sed -i '/^make_image_desktop()/,/^}$/{/reset_pac_conf.*\${path}/i\        mkiso_build_iso_cleanups "${path}"
}' "$iso"
    assert_present 'mkiso_build_iso_cleanups "$1"' "$image"
    assert_present 'mkiso_build_iso_cleanups' "$iso"
}

patch_manjaro_tools() {
    local iso=/usr/lib/manjaro-tools/util-iso.sh
    local image=/usr/lib/manjaro-tools/util-iso-image.sh

    msg "Pointing buildiso at the $EDITION profile"
    # Candidates for removal: with run_dir set, `buildiso -p` should resolve
    # the profile by itself. Kept until a validation build confirms it.
    sed -i "s|profile=.*|profile=\"$EDITION\"|" "$iso"
    sed -i "s|profile_dir=.*|profile_dir=\"$PROFILE_PATH_EDITION\"|" "$iso"

    # The profile decides the kernel; manjaro-tools' own check reads a digit
    # out of the package name and would reject linux-xanmod.
    sed -i '/\${iso_kernel}/s/^/#/' "$iso"

    # Live volume label; must match the misolabel set in configure_profile.
    # manjaro-tools computes its own label from branding+profile, so this one
    # line is replaced rather than configured.
    sed -i "s/iso_label=.*/iso_label=${VOL_ID}/" "$iso"
    assert_present "iso_label=${VOL_ID}" "$iso"

    # Enable plymouth and kms in the live initrd.
    sed -i 's/keyboard keymap/keyboard keymap kms plymouth/g' /usr/share/manjaro-tools/mkinitcpio.conf
    assert_present 'kms plymouth' /usr/share/manjaro-tools/mkinitcpio.conf

    add_image_cleanups "$image" "$iso"

    # manjaro-live-setup must produce a usable live home (see the script).
    bash "$scriptDir/patch-live-setup.sh"
}

#--- profile configuration ----------------------------------------------------

# Drop the packages an edition opts out of.
#
# A profile may ship Root-remove, Live-remove, Mhwd-remove or Desktop-remove:
# one package name per line. This is how an edition drops a package from a list
# it does not own -- the bigcommunity editions share Packages-{Root,Live,Mhwd}
# through symlinks into shared/, and Packages-Desktop can be assembled from
# another edition's.
#
# Two steps, because a package can arrive two ways:
#
#   1. Here, out of the matching Packages-* file, so it is never asked for.
#   2. In the chroot, after the install, by mkiso_build_iso_cleanups -- which
#      is the step that catches a package pulled in as a dependency, and the
#      only reason `vim` ever leaves the image.
#
# The lists travel to step 2 inside root-overlay, the way the previous
# generator (talesam/build-iso) carried them. Both halves were lost when the
# build moved into this engine; only the first one is visible in a profile, so
# restoring it alone still shipped vim.
apply_profile_removals() {
    local remove_file target list
    local staging="$PROFILE_PATH_EDITION/root-overlay/var/lib/packages-remove"

    for remove_file in Root-remove Live-remove Mhwd-remove Desktop-remove; do
        list="$PROFILE_PATH_EDITION/$remove_file"
        [[ -f "$list" ]] || continue

        # Every list is staged, including one whose Packages-* file does not
        # exist: what it names may still be installed as a dependency.
        msg "Staging $remove_file for post-install removal"
        install -Dm644 "$list" "$staging/$remove_file"

        target="$PROFILE_PATH_EDITION/Packages-${remove_file%-remove}"
        if [[ ! -f "$target" ]]; then
            msg "$remove_file: no $(basename "$target") to edit, skipping"
            continue
        fi

        # The shared lists are symlinks into shared/. Editing through the link
        # would remove the package from every edition that shares the file, so
        # the edition gets its own copy first.
        if [[ -L "$target" ]]; then
            cp --remove-destination "$(readlink -f "$target")" "$target"
        fi

        msg "Applying $remove_file to $(basename "$target")"
        # Matching the first field, not the whole line, so that a package
        # carrying a manjaro-tools modifier (`vim >extra`) goes too. Comments
        # and blank lines in the removal list are ignored, and the comparison
        # is between strings, so a `+` in a package name is a `+`.
        #
        # awk also reports what it did. A package the list does not carry is
        # the normal case, not an error: it is either a dependency, which only
        # the post-install step can remove, or a line nobody needs any more.
        # -v, not a trailing assignment: BEGIN runs before argument
        # assignments, and an empty `out` there is a fatal awk error.
        awk -v out="$target.new" 'BEGIN { printf "" > out }
             NR==FNR {
                 sub(/#.*/, "")
                 gsub(/^[ \t]+|[ \t]+$/, "")
                 if ($0 != "") drop[$0] = 1
                 next
             }
             ($1 in drop) { hit[$1] = 1; next }
             { print > out }
             END {
                 for (package in drop)
                     if (!(package in hit))
                         printf "    %s: not in the list, left to the post-install removal\n", package > "/dev/stderr"
             }' "$list" "$target"
        mv "$target.new" "$target"
    done
}

configure_profile() {
    # The installed system of a community ISO gets its repositories from the
    # shared pacman.conf, when the profile layout ships one.
    #
    # Both families belong here. The profile stopped shipping [biglinux-stable]
    # on the understanding that this engine wrote it, but only the build
    # configuration ever got it -- so every community ISO since then installed
    # without the repository its BigLinux packages are updated from. The
    # assertions below are why that cannot happen again quietly.
    #
    # This runs before set-biglinux-branch.sh, which inserts [biglinux-testing]
    # immediately above [biglinux-stable] and fails when that section is absent.
    # Writing the repositories first gives that script the anchor it looks for;
    # on a testing build it then finds its own section already in place and says
    # so instead of inserting a second copy.
    if [[ "$DISTRONAME" == "bigcommunity" && -f "$PROFILES_ROOT/shared/pacman.conf" ]]; then
        msg "Adding community and BigLinux repositories to shared/pacman.conf"
        append_installed_repos "$PROFILES_ROOT/shared/pacman.conf"
        assert_present '^\[community-stable\]' "$PROFILES_ROOT/shared/pacman.conf"
        assert_present '^\[community-extra\]' "$PROFILES_ROOT/shared/pacman.conf"
        assert_present '^\[biglinux-stable\]' "$PROFILES_ROOT/shared/pacman.conf"
    fi

    # Ship the branch actually being built (see each script's header).
    if [[ "$DISTRONAME" == "biglinux" ]]; then
        bash "$scriptDir/set-manjaro-branch.sh"
    fi
    bash "$scriptDir/set-biglinux-branch.sh"

    # Off by default; the TKG mesa swap of the old latest/xanmod ISOs. The local
    # generator (gitrepo / Build ISO GUI) never does this, so it stays behind a
    # flag that only a pipeline sets. Only the bleeding-edge kernels ever
    # shipped it, and which those are is decided here rather than by each caller.
    #
    # TKG mesa replaces the stock one: adding the packages is not enough, the
    # stock mesa consumers have to go or pacman hits a file conflict in the chroot.
    if [[ "${MESA_TKG:-false}" == "true" ]]; then
        case "$KERNEL" in
            latest | xanmod | xanmod-lts)
                msg "Swapping mesa for the TKG builds"
                printf '\nmesa-tkg-stable\nlib32-mesa-tkg-stable\n' >>"$PROFILE_PATH_EDITION/Packages-Root"
                sed -i '/libva-mesa/d' "$PROFILE_PATH_EDITION/Packages-Desktop" \
                    "$PROFILE_PATH_EDITION/Packages-Mhwd"
                sed -i '/vulkan-swrast/d' "$PROFILE_PATH_EDITION/Packages-Desktop"
                ;;
            *) msg "MESA_TKG ignored: no TKG mesa build for kernel selector $KERNEL" ;;
        esac
    fi

    # After the package lists have been assembled (MESA_TKG above appends to
    # Packages-Root) and before the kernel placeholders are filled.
    apply_profile_removals

    msg "Setting live media ids (misobasedir=$DISTRONAME misolabel=$VOL_ID)"
    find "$PROFILES_ROOT/$DISTRONAME" -name "kernels.cfg" -exec sed -i \
        -e "s/misobasedir=[^ ]*/misobasedir=${DISTRONAME}/g" \
        -e "s/misolabel=[^ ]*/misolabel=${VOL_ID}/g" {} +
    # No biglinux profile ships a grub-fix.sh, so this pass currently matches
    # nothing. It stays for the bigcommunity profiles, which are not in this
    # checkout and are still awaiting a validation build; drop it once one has
    # confirmed they carry no such file either. The pattern requires the two
    # settings adjacent, which is how grub-fix.sh wrote them and why this is a
    # separate expression rather than the two above.
    find "$PROFILES_ROOT/$DISTRONAME" -name "grub-fix.sh" -exec sed -i \
        "s|misobasedir=[^ ]* misolabel=[^ ]*|misobasedir=${DISTRONAME} misolabel=${VOL_ID}|g" {} +

    find "$PROFILES_ROOT/$DISTRONAME" -name "variable.cfg" -exec sed -i \
        "s#grub_theme=/boot/grub/themes/[^/]*/theme.txt#grub_theme=/boot/grub/themes/${DISTRONAME}-live/theme.txt#g" {} +
    find "$PROFILES_ROOT/$DISTRONAME" -name "grub.cfg" -exec sed -i \
        "s#theme=(\$root)/boot/grub/themes/[^/]*/theme.txt#theme=(\$root)/boot/grub/themes/${DISTRONAME}-live/theme.txt#g" {} +

    sed -i "s/label=.*/label=${VOL_ID}/" "$PROFILE_PATH_EDITION/profile.conf"
    assert_present "label=${VOL_ID}" "$PROFILE_PATH_EDITION/profile.conf"

    msg "Selecting kernel linux${KERNEL_NAME} in the package lists"
    local pkg_file
    for pkg_file in "$PROFILE_PATH_EDITION"/Packages-*; do
        # Drop any kernel the profile hardcodes, then fill the KERNEL
        # placeholders (KERNEL, KERNEL-headers, KERNEL-nvidia, ...).
        sed -i '/^linux[0-9]/d; /^linux-latest/d' "$pkg_file"
        sed -i "s/^KERNEL\b/linux${KERNEL_NAME}/" "$pkg_file"
    done
    # Every placeholder must be gone: a leftover literal "KERNEL" line makes
    # pacman fail deep inside the chroot, an hour into the build.
    assert_absent '^KERNEL' "$PROFILE_PATH_EDITION"/Packages-*

    msg "Writing /etc/big-release"
    local release_file="$PROFILE_PATH_EDITION/root-overlay/etc/big-release"
    mkdir -p "$(dirname "$release_file")"
    {
        echo "BUILD_RELEASE=$RELEASE_TAG"
        echo "BUILD_BRANCH=$DISTRO_BRANCH"
        echo "EDITION=$EDITION"
        echo "UNIX_TIMESTAMP=$UNIX_TIMESTAMP"
    } >>"$release_file"
}

#--- build and output ---------------------------------------------------------

run_build() {
    command -v buildiso &>/dev/null || die "buildiso not found (manjaro-tools-iso)"
    msg "buildiso -p $EDITION -b $MANJARO_BRANCH -k linux${KERNEL_NAME}"
    # No -f: with it manjaro-tools sets extra=true and installs every
    # `>extra` line of the profile's Packages-* files.
    LC_ALL=C buildiso -p "$EDITION" -b "$MANJARO_BRANCH" -k "linux${KERNEL_NAME}"
}

collect_output() {
    local product flavour tier iso_path pkgs_path kernel_suffix
    # This is the published name, and this is the only place that decides it:
    # every publisher -- the GitLab pipeline, the GitHub workflow, the Build ISO
    # GUI -- ships the file under the name written here. A second opinion
    # downstream is how an ISO built from Manjaro unstable once got published,
    # with a torrent, under the release name.
    #
    # kde carries no flavour segment because it is the default edition, and
    # xivastudio is its own product rather than a BigLinux flavour. Anything
    # else has its edition inserted as a segment.
    case "$EDITION" in
        kde) product="$DISTRONAME"; flavour="" ;;
        xivastudio) product="xivastudio"; flavour="" ;;
        *) product="$DISTRONAME"; flavour="_${EDITION}" ;;
    esac

    # Both branches vote, and Manjaro's is asked first: a non-stable Manjaro
    # makes the build a development one whatever our own branch says.
    case "$MANJARO_BRANCH/$REQUESTED_BRANCH" in
        unstable/*) tier="_DEVELOPMENT${flavour}_ManUnstable" ;;
        testing/*) tier="_DEVELOPMENT${flavour}_ManTesting" ;;
        stable/development) tier="_DEVELOPMENT${flavour}" ;;
        stable/testing) tier="_TESTING${flavour}" ;;
        stable/stable) tier="${flavour}" ;;
        # Unreachable: the branch values are validated above. Kept so a new
        # branch name cannot silently produce a nameless tier.
        *) die "no ISO tier for $MANJARO_BRANCH/$REQUESTED_BRANCH" ;;
    esac

    iso_path=$(find /var/cache/manjaro-tools/iso -type f -name '*.iso' | head -n1)
    pkgs_path=$(find /var/cache/manjaro-tools/iso -type f -name '*-pkgs.txt' | head -n1)
    [[ -n "$iso_path" ]] || die "buildiso finished but produced no ISO"

    # The kernel id is always the last _-separated token of the ISO name:
    # k612, k71, xanmod71, xanmodlts71 (the version read from the .pkgs list).
    if [[ "$KERNEL_NAME" == -xanmod* ]]; then
        local xan_ver
        [[ -n "$pkgs_path" ]] || die "no .pkgs list to read the ${KERNEL} version from"
        xan_ver=$(awk -v pkg="linux${KERNEL_NAME}" \
            '$1 == pkg {split($2, a, "."); print a[1] a[2]; exit}' "$pkgs_path")
        [[ -n "$xan_ver" ]] || die "linux${KERNEL_NAME} not found in $pkgs_path"
        kernel_suffix="${KERNEL//-/}${xan_ver}"
    else
        kernel_suffix="k${KERNEL_NAME}"
    fi
    # RELEASE_TAG may carry a time (the GUI sends %Y-%m-%d_%H-%M); the name
    # keeps the date alone, while /etc/big-release records it in full.
    ISO_BASENAME="${product}${tier}_${RELEASE_TAG%%_*}_${kernel_suffix}.iso"

    msg "Moving ISO to $WORK_PATH/$ISO_BASENAME"
    mv -f "$iso_path" "$WORK_PATH/$ISO_BASENAME"
    if [[ -n "$pkgs_path" ]]; then
        mv -f "$pkgs_path" "$WORK_PATH/$ISO_BASENAME.pkgs"
    fi
}

#--- main ---------------------------------------------------------------------

main() {
    read_inputs "$@"
    validate_inputs

    local start=$SECONDS
    msg "Building $DISTRONAME/$EDITION (kernel=$KERNEL manjaro=$MANJARO_BRANCH ${DISTRONAME}=$DISTRO_BRANCH)"
    resolve_kernel
    prepare_host
    configure_build_repos
    patch_manjaro_tools
    configure_profile
    run_build
    collect_output
    msg "Finished in $(((SECONDS - start) / 60)) min: $WORK_PATH/$ISO_BASENAME"
}

# Only when run, not when sourced, so the tests can source this file and call a
# single stage with fixtures instead of matching the source text.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
