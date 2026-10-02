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

if command -v setsid >/dev/null 2>&1; then
	setsid -- "$@" >/tmp/openqa-gui-supervisor.log 2>&1 &
else
	"$@" >/tmp/openqa-gui-supervisor.log 2>&1 &
fi
child_pid=$!
printf 'child_pid=%s\nstate=running\n' "$child_pid" >"$status_file"

# Report the wait status verbatim: a process killed by a signal arrives as
# 128+signal, which is what lets the host tell a crash from any other exit.
set +e
wait "$child_pid"
exit_code=$?
set -e
printf 'exit_code=%s\nstate=exited\n' "$exit_code" >>"$status_file"
exit "$exit_code"
