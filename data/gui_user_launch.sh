#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later

set -eu

if [ "$#" -lt 2 ]; then
	exit 64
fi

status_file=$1
shift
case "$status_file" in
/tmp/openqa-gui-status-[0-9]*-[0-9]*) ;;
*) exit 64 ;;
esac

printf 'state=starting\nlauncher_uid=%s\n' "$(id -u)" >"$status_file"

launcher_uid=$(id -u)
if [ "$launcher_uid" != 0 ]; then
	gui_uid=$launcher_uid
	gui_home=$(getent passwd "$gui_uid" | cut -d: -f6 || true)
else
	gui_uid=1000
	gui_home=$(getent passwd "$gui_uid" | cut -d: -f6 || true)
fi
if [ -z "$gui_home" ]; then
	printf 'state=failed\nreason=gui-user-not-found\nexit_code=1\n' >>"$status_file"
	exit 1
fi
export HOME="$gui_home"
export DISPLAY=:0
export XDG_RUNTIME_DIR="/run/user/$gui_uid"
if [ -z "${XAUTHORITY:-}" ] || [ ! -r "$XAUTHORITY" ]; then
	if [ -r "$gui_home/.Xauthority" ]; then
		export XAUTHORITY="$gui_home/.Xauthority"
	else
		for candidate in \
			"$XDG_RUNTIME_DIR/.Xauthority" \
			"/run/user/$gui_uid/.Xauthority" \
			/var/lib/sddm/.Xauthority \
			/var/run/sddm/.Xauthority; do
			if [ -r "$candidate" ]; then
				export XAUTHORITY="$candidate"
				break
			fi
		done
	fi
fi
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
session_environment=$(systemctl --user show-environment 2>/dev/null || true)
session_display=$(printf '%s\n' "$session_environment" | awk -F= '$1 == "DISPLAY" {print substr($0, index($0, "=") + 1); exit}')
session_xauthority=$(printf '%s\n' "$session_environment" | awk -F= '$1 == "XAUTHORITY" {print substr($0, index($0, "=") + 1); exit}')
session_wayland_display=$(printf '%s\n' "$session_environment" | awk -F= '$1 == "WAYLAND_DISPLAY" {print substr($0, index($0, "=") + 1); exit}')
[ -n "$session_display" ] && export DISPLAY="$session_display"
[ -n "$session_xauthority" ] && export XAUTHORITY="$session_xauthority"
[ -n "$session_wayland_display" ] && export WAYLAND_DISPLAY="$session_wayland_display"
for session_variable in QT_QPA_PLATFORM GDK_BACKEND XDG_SESSION_TYPE KDE_FULL_SESSION KDE_SESSION_VERSION; do
	session_value=$(printf '%s\n' "$session_environment" | awk -F= -v key="$session_variable" '$1 == key {print substr($0, index($0, "=") + 1); exit}')
	[ -n "$session_value" ] && export "$session_variable=$session_value"
done
export QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1
export SAL_ACCESSIBILITY_ENABLED=1
export GTK_A11Y=atspi
export NO_AT_BRIDGE=0

supervisor=/tmp/openqa-gui-supervisor.sh

run_candidate() {
	printf 'candidate=%s\n' "$1" >>"$status_file"
	set +e
	"$@"
	set -e
	for _ in 1 2 3 4 5 6 7 8 9 10; do
		if grep -q '^child_pid=' "$status_file" 2>/dev/null; then
			return 0
		fi
		sleep 0.1
	done
	return 125
}

# These functions are passed to run_candidate as commands.
# shellcheck disable=SC2329
run_with_setpriv() {
	setpriv --reuid="$gui_uid" --regid="$gui_uid" --init-groups -- "$supervisor" "$status_file" "$@"
}

# shellcheck disable=SC2329
run_with_runuser() {
	runuser -u "$gui_uid" -- "$supervisor" "$status_file" "$@"
}

# shellcheck disable=SC2329
run_with_su() {
	su -s /bin/sh "$gui_uid" -c 'exec "$@"' openqa-gui-user "$supervisor" "$status_file" "$@"
}

# shellcheck disable=SC2329
run_with_current_user() {
	"$supervisor" "$status_file" "$@"
}

# shellcheck disable=SC2329
run_with_user_systemd() {
	systemd-run --user --scope --quiet -- "$supervisor" "$status_file" "$@"
}

if [ "$launcher_uid" != 0 ]; then
	if command -v systemd-run >/dev/null 2>&1 && run_candidate run_with_user_systemd "$@"; then
		exit 0
	fi
	if run_candidate run_with_current_user "$@"; then
		exit 0
	fi
fi

if command -v setpriv >/dev/null 2>&1; then
	if run_candidate run_with_setpriv "$@"; then
		exit 0
	fi
fi
if command -v runuser >/dev/null 2>&1; then
	if run_candidate run_with_runuser "$@"; then
		exit 0
	fi
fi
if run_candidate run_with_su "$@"; then
	exit 0
fi
printf 'state=failed\nexit_code=125\n' >>"$status_file"
exit 125
