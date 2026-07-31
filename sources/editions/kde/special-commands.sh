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
# `sed -n '/## Section/,/^$/p'` prints from the section header down to the first
# blank line, which is how upstream separates its sections.
upstreamDesktop=manjaro-iso-profiles/manjaro/kde/Packages-Desktop
generatedDesktop=biglinux/kde/Packages-Desktop

{
    sed -n '/## Printing/,/^$/p' "$upstreamDesktop"
    sed -n '/## Xorg Server and Graphics/,/^$/p' "$upstreamDesktop"
    sed -n '/## Xorg Input Drivers/,/^$/p' "$upstreamDesktop"
    sed -n '/## Misc/,/^$/p' "$upstreamDesktop"
} >> "$generatedDesktop"

# Came in with "## Xorg Input Drivers" above and is not wanted: the void driver
# claims input devices and nothing uses it. Anchored so it cannot match a
# longer package name.
sed -i '/^xf86-input-void$/d' "$generatedDesktop"
