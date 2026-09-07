#!/usr/bin/env bash
#
# build-local.sh - build an ISO on your own machine
#
# Runs the engine (build-iso.sh) inside the official build container with
# podman or docker, so nothing is installed on your system. Your checkout is
# copied first and stays clean; the ISO lands in ./output.
#
#   ./build-iso/build-local.sh kde
#   ./build-iso/build-local.sh kde latest
#   ./build-iso/build-local.sh -m testing -b testing kde
#
# Usage: build-local.sh [options] <edition> [kernel]
#   kernel: oldlts | lts (default) | latest | xanmod | xanmod-lts
#   -m <branch>   Manjaro branch: stable (default) | testing | unstable
#   -b <branch>   BigLinux branch: stable (default) | testing
#   -c <branch>   BigCommunity branch: stable (default) | testing
#   -o <dir>      output directory (default: ./output)
#   -i <image>    container image (default depends on the distribution)
#
set -euo pipefail

scriptDir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
profilesRoot=$(cd "$scriptDir/.." && pwd)

die() { printf 'build-local.sh: error: %s\n' "$*" >&2; exit 1; }

# --help is the header comment above, uncommented. Read as "from line 2 to the
# first line that is not a comment", not as a hard-coded line range: editing
# the header would silently truncate the help text.
usage() {
    sed -n '2,/^[^#]/{ /^[^#]/d; s/^# \{0,1\}//p; }' "${BASH_SOURCE[0]}"
    exit "${1:-0}"
}

manjaroBranch=stable biglinuxBranch=stable communityBranch=stable
outputDir="$PWD/output" image=""
while getopts 'm:b:c:o:i:h' opt; do
    case "$opt" in
        m) manjaroBranch=$OPTARG ;;
        b) biglinuxBranch=$OPTARG ;;
        c) communityBranch=$OPTARG ;;
        o) outputDir=$OPTARG ;;
        i) image=$OPTARG ;;
        h) usage ;;
        *) usage 1 ;;
    esac
done
shift $((OPTIND - 1))
edition="${1:-}"
kernel="${2:-lts}"
[[ -n "$edition" ]] || usage 1

# Same detection the engine does, to pick the default container image.
#
# The registry is spelled out. A short name is resolved through podman's
# unqualified-search-registries, and a host without a containers-registries.conf
# has none: podman then refuses the name outright ("did not resolve to an alias")
# instead of trying Docker Hub. Docker would have assumed Docker Hub, so this
# failed on podman only.
if [[ -d "$profilesRoot/bigcommunity" ]]; then
    distroname=bigcommunity
    image="${image:-docker.io/talesam/community-build:latest}"
else
    distroname=biglinux
    image="${image:-docker.io/xivastudio/biglinux_build_package:latest}"
fi

if command -v podman &>/dev/null; then
    engine=podman
elif command -v docker &>/dev/null; then
    engine=docker
else
    die "neither podman nor docker found"
fi

mkdir -p "$outputDir"
outputDir=$(cd "$outputDir" && pwd)

# Work on a copy: the engine edits the profile files in place.
#
# The copy must land OUTSIDE the checkout. With the default output directory
# ($PWD/output, i.e. inside the checkout) a copy under it would be a copy of
# the checkout into itself, which cp refuses -- "cannot copy a directory into
# itself" -- aborting the documented `./build-iso/build-local.sh kde`.
#
# Next to the checkout rather than in /tmp: /tmp is RAM-backed on many systems
# and the profiles are large. If the parent is not writable (the checkout sits
# in a read-only mount), fall back to TMPDIR.
copyParent=$(cd "$profilesRoot/.." && pwd)
[[ -w "$copyParent" ]] || copyParent="${TMPDIR:-/tmp}"
tmpDir=$(mktemp -d "$copyParent/.build-iso-local.XXXXXX")
trap 'rm -rf "$tmpDir"' EXIT
echo "==> Copying the checkout to $tmpDir (your clone stays clean)"
cp -a "$profilesRoot" "$tmpDir/iso-profiles"

echo "==> Building $distroname/$edition (kernel=$kernel) with $engine using $image"
echo "==> The first build downloads a lot; expect 1-2 hours in total."
# --user 0:0 because both build images declare USER builduser, and the engine
# needs root: it patches manjaro-tools under /usr/lib and chroots into the
# images it builds. Without it the build stops at the engine's first check,
# after pulling the whole image. The GitHub workflow gets root from the
# container job, and gitrepo passes the same flag.
"$engine" run --rm --privileged --user 0:0 \
    -v "$tmpDir/iso-profiles:/build/iso-profiles" \
    -v "$outputDir:/build/output" \
    -e EDITION="$edition" \
    -e KERNEL="$kernel" \
    -e MANJARO_BRANCH="$manjaroBranch" \
    -e BIGLINUX_BRANCH="$biglinuxBranch" \
    -e BIGCOMMUNITY_BRANCH="$communityBranch" \
    -e WORK_PATH=/build/output \
    "$image" \
    bash /build/iso-profiles/build-iso/build-iso.sh

echo "==> Done. ISO in $outputDir:"
ls -lh "$outputDir"/*.iso
