#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later

set -eu
umask 022

if [ "$#" -lt 2 ]; then
	exit 64
fi

status_file=$1
shift
case "$status_file" in
/tmp/openqa-gui-status-[0-9]*-[0-9]*) ;;
*) exit 64 ;;
esac
printf 'state=starting\n' >"$status_file"
printf 'uid=%s\ndisplay=%s\nxauthority=%s\nxdg_runtime_dir=%s\n' \
	"$(id -u)" "${DISPLAY:-}" "${XAUTHORITY:-}" "${XDG_RUNTIME_DIR:-}" >>"$status_file"

if command -v setsid >/dev/null 2>&1; then
	setsid -- "$@" >/tmp/openqa-gui-supervisor.log 2>&1 &
else
	"$@" >/tmp/openqa-gui-supervisor.log 2>&1 &
fi
child_pid=$!
printf 'child_pid=%s\nprocess_group=%s\nstate=running\n' "$child_pid" "$child_pid" >"$status_file"

# Report the wait status verbatim: a process killed by a signal arrives as
# 128+signal, which is what lets the host tell a crash from any other exit.
set +e
wait "$child_pid"
exit_code=$?
set -e
printf 'raw_exit_code=%s\n' "$exit_code" >>"$status_file"
printf 'exit_code=%s\nstate=exited\n' "$exit_code" >>"$status_file"
exit "$exit_code"
