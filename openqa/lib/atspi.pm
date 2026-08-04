# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BigLinux

package atspi;

use Mojo::Base -strict;

use JSON::PP qw(decode_json);
use MIME::Base64 qw(decode_base64);
use Text::ParseWords qw(shellwords);
use testapi;

my $probe_path = '/tmp/openqa-atspi-probe.py';
my $supervisor_path = '/tmp/openqa-gui-supervisor.sh';
my $user_launcher_path = '/tmp/openqa-gui-user-launch.sh';
my $desktop_launcher_path = '/tmp/desktop_entry_launcher.py';
my $state_path = '/tmp/openqa-atspi-baseline.json';
my $session_state_path = '/tmp/openqa-atspi-session-baseline.json';
my $kernel_version;
my %session_launch_pids;

sub prepare {
    my ($class) = @_;
    %session_launch_pids = ();
    my $ready_marker = '__OA_A11Y_READY__';
    my $kernel_marker = '__OA_KERNEL__';
    my $probe_url = data_url('atspi_probe.py');
    my $supervisor_url = data_url('gui_supervisor.sh');
    my $user_launcher_url = data_url('gui_user_launch.sh');
    my $launcher_url = data_url('desktop_entry_launcher.py');

    select_console 'root-virtio-terminal';
    my $command = join ' ',
      'export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus',
      'SAL_ACCESSIBILITY_ENABLED=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 GTK_A11Y=atspi NO_AT_BRIDGE=0;',
      'session_xauthority=$(systemctl --user show-environment 2>/dev/null | awk -F= \'$1 == "XAUTHORITY" {print substr($0, index($0, "=") + 1); exit}\');',
      '[ -n "$session_xauthority" ] && export XAUTHORITY="$session_xauthority";',
      'gsettings set org.gnome.desktop.interface toolkit-accessibility true 2>/dev/null || true;',
      'systemctl --user set-environment DISPLAY="$DISPLAY" XAUTHORITY="${XAUTHORITY:-}" XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" 2>/dev/null || true;',
      'dbus-update-activation-environment --systemd DISPLAY XAUTHORITY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true;',
      'systemctl --user --no-block restart at-spi-dbus-bus.service 2>/dev/null || systemctl --user --no-block start at-spi-dbus-bus.service 2>/dev/null || true;',
      'at_spi_bus_address=$(systemctl --user show-environment 2>/dev/null | awk -F= \'$1 == "AT_SPI_BUS_ADDRESS" {print substr($0, index($0, "=") + 1); exit}\');',
      'for i in $(seq 1 50); do published_at_spi_address=$(gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus --method org.a11y.Bus.GetAddress 2>/dev/null | sed -E "s/.*\x27([^\x27]+)\x27.*/\\1/"); at_spi_socket=$(find /run/user/1000/at-spi -maxdepth 1 -type s -print -quit 2>/dev/null || true); for candidate in "$at_spi_bus_address" "$published_at_spi_address" "${at_spi_socket:+unix:path=$at_spi_socket}"; do candidate_path=${candidate#unix:path=}; if [ -n "$candidate" ] && { timeout 2 gdbus call --address "$candidate" --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.ListNames >/dev/null 2>&1 || test -S "$candidate_path"; }; then at_spi_bus_address="$candidate"; break 2; fi; done; if [ "$i" = 1 ] && test -x /usr/lib/at-spi-bus-launcher; then if [ "$(id -u)" = 0 ] && command -v runuser >/dev/null 2>&1; then runuser -u 1000 -- env DISPLAY="$DISPLAY" XAUTHORITY="${XAUTHORITY:-}" XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus /usr/lib/at-spi-bus-launcher --launch-immediately --a11y=1 >/tmp/openqa-atspi-bus.log 2>&1 & else env DISPLAY="$DISPLAY" XAUTHORITY="${XAUTHORITY:-}" XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus /usr/lib/at-spi-bus-launcher --launch-immediately --a11y=1 >/tmp/openqa-atspi-bus.log 2>&1 & fi; fi; at_spi_bus_address=; sleep 0.2; done;',
      'test -n "$at_spi_bus_address" || { systemctl --user status at-spi-dbus-bus.service --no-pager 2>/dev/null || true; printf "AT_SPI_BUS_ADDRESS from user environment: "; systemctl --user show-environment 2>/dev/null | sed -n \'/^AT_SPI_BUS_ADDRESS=/p\'; command -v gdbus || true; find /run/user/1000/at-spi -maxdepth 1 -type s -ls 2>/dev/null || true; cat /tmp/openqa-atspi-bus.log 2>/dev/null || true; exit 1; }; export AT_SPI_BUS_ADDRESS="$at_spi_bus_address";',
      'if test -x /usr/lib/at-spi2-registryd && ! pgrep -u 1000 -x at-spi2-registryd >/dev/null 2>&1; then /usr/lib/at-spi2-registryd --use-gnome-session >/tmp/openqa-atspi-registry.log 2>&1 & fi;',
      'for i in $(seq 1 50); do if timeout 2 gdbus call --address "$AT_SPI_BUS_ADDRESS" --dest org.a11y.atspi.Registry --object-path /org/a11y/atspi/accessible/root --method org.a11y.atspi.Accessible.GetRoleName >/dev/null 2>&1; then break; fi; sleep 0.2; done;',
      'systemctl --user set-environment SAL_ACCESSIBILITY_ENABLED=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 GTK_A11Y=atspi NO_AT_BRIDGE=0 AT_SPI_BUS_ADDRESS="$AT_SPI_BUS_ADDRESS" 2>/dev/null || true;',
      'dbus-update-activation-environment --systemd SAL_ACCESSIBILITY_ENABLED QT_LINUX_ACCESSIBILITY_ALWAYS_ON GTK_A11Y NO_AT_BRIDGE AT_SPI_BUS_ADDRESS 2>/dev/null || true;',
      'curl --fail --silent --show-error', _shell_quote($probe_url), '--output', _shell_quote($probe_path), '&&',
      'curl --fail --silent --show-error', _shell_quote($supervisor_url), '--output', _shell_quote($supervisor_path), '&&',
      'curl --fail --silent --show-error', _shell_quote($user_launcher_url), '--output', _shell_quote($user_launcher_path), '&&',
      'curl --fail --silent --show-error', _shell_quote($launcher_url), '--output', _shell_quote($desktop_launcher_path), '&&',
      'chmod 755', _shell_quote($probe_path), _shell_quote($supervisor_path), _shell_quote($user_launcher_path), _shell_quote($desktop_launcher_path), '&&',
      'kquitapp6 krunner >/dev/null 2>&1 || true;',
      'printf ', _shell_quote(_marker_format($ready_marker) . '%s\\n'), ' "$(uname -r)"';
    type_string $command;
    send_key 'ret';
    my $ready = wait_serial $ready_marker, no_regex => 1, timeout => 60;
    die 'AT-SPI preparation did not finish' unless defined $ready;

    type_string join ' ', 'printf', _shell_quote(_marker_format($kernel_marker) . '%s\\n'), '"$(uname -r)"';
    send_key 'ret';
    my $kernel_output = wait_serial qr/\Q$kernel_marker\E([^\r\n]+)/, timeout => 30;
    ($kernel_version) = $kernel_output =~ /\Q$kernel_marker\E([^\r\n]+)/ if defined $kernel_output;
    $kernel_version =~ s/\s+\z// if defined $kernel_version;
    die 'AT-SPI preparation did not report the guest kernel'
      unless defined $kernel_version && $kernel_version =~ /^[[:alnum:]][[:alnum:].+_~-]*$/;

    select_console 'sut';
    my $baseline = $class->result('baseline', 3);
    if (ref $baseline ne 'HASH'
        || !exists $baseline->{mem_available_mib}
        || ref $baseline->{windows} ne 'ARRAY') {
        my $registry_log = _read_registry_log();
        die 'AT-SPI baseline is unavailable'
          . ($registry_log ? ": $registry_log" : '');
    }
    select_console 'root-virtio-terminal';
    my $session_baseline_saved = _run_guest_command(
        "cp '$state_path' '$session_state_path'",
        5,
    );
    die 'AT-SPI session baseline could not be saved'
      unless defined $session_baseline_saved;
    select_console 'sut';
    return $kernel_version;
}

sub kernel_version {
    return $kernel_version;
}

sub result {
    my ($class, $operation, $timeout, @arguments) = @_;
    die "invalid AT-SPI operation '$operation'"
      unless $operation =~ /\A(?:baseline|wait-open|x11-wait-open|wait-close|interact|close|cleanup|memory|inventory|inventory-chunk)\z/;
    die 'invalid AT-SPI timeout' unless defined $timeout && $timeout =~ /\A[0-9]+(?:\.[0-9]+)?\z/;

    my @command = (
        'python3', $probe_path, $operation,
        '--state', $state_path,
        '--timeout', $timeout,
    );
    push @command, @arguments;
    my $probe_command = join ' ', map { _shell_quote($_) } @command;
    my $probe_timeout = $timeout + 2;
    my $shell_command = join ' ',
      'if command -v timeout >/dev/null 2>&1; then timeout --kill-after=2',
      _shell_quote($probe_timeout), $probe_command, '; else', $probe_command, '; fi; printf',
      _shell_quote(_marker_format('__OPENQA_ATSPI_DONE__') . '\\n');

    select_console 'root-virtio-terminal';
    type_string $shell_command;
    send_key 'ret';
    my $serial = wait_serial(
        qr/(?:__OPENQA_ATSPI__([0-9a-f]+)\r?\n)?__OPENQA_ATSPI_DONE__/,
        $timeout + 3
    );
    if (!defined $serial) {
        # A broken client can leave a libatspi call blocked.  Keep the serial
        # shell usable so the remaining inventory still gets a result.
        select_console 'root-virtio-terminal';
        type_string '', terminate_with => 'ETX';
        type_string 'printf ' . _shell_quote(_marker_format('__OPENQA_ATSPI_RECOVERED__') . '\\n');
        send_key 'ret';
        wait_serial '__OPENQA_ATSPI_RECOVERED__', no_regex => 1, timeout => 3;
    }
    select_console 'sut';
    die "AT-SPI operation '$operation' returned no result" unless defined $serial;

    my ($hex) = $serial =~ /__OPENQA_ATSPI__([0-9a-f]+)/;
    die "AT-SPI operation '$operation' returned no result" unless defined $hex;
    my $result = eval { decode_json(pack 'H*', $hex) };
    die "AT-SPI operation '$operation' returned invalid JSON: $@"
      unless ref $result eq 'HASH';
    return $result;
}

sub inventory {
    my ($class) = @_;
    my $result = $class->result('inventory', 30);
    die 'desktop entry inventory did not return chunk metadata'
      unless ref $result eq 'HASH'
      && $result->{status} eq 'passed'
      && defined $result->{chunks}
      && $result->{chunks} =~ /\A[1-9][0-9]*\z/;

    my $encoded_payload = '';
    for my $index (0 .. $result->{chunks} - 1) {
        my $chunk = $class->result('inventory-chunk', 30, '--index', $index);
        die "desktop entry inventory chunk $index is invalid"
          unless ref $chunk eq 'HASH'
          && $chunk->{status} eq 'passed'
          && defined $chunk->{data};
        $encoded_payload .= decode_base64($chunk->{data});
    }
    my $entries = eval { decode_json($encoded_payload) };
    die "desktop entry inventory JSON is invalid: $@"
      unless ref $entries eq 'ARRAY';
    return $entries;
}

sub launch_command {
    my ($class, $command, $expected_name, $timeout, $expected_pid) = @_;
    my @argv = shellwords($command);
    die 'empty graphical command' unless @argv;
    $expected_pid //= 'pending';
    return $class->_launch_argv(\@argv, $expected_name, $timeout, $expected_pid);
}

sub launch_desktop_entry {
    my ($class, $entry, $timeout) = @_;
    die 'desktop entry is not a mapping' unless ref $entry eq 'HASH';
    my $path = $entry->{path};
    die 'desktop entry has no absolute path'
      unless defined $path
      && $path =~ m{\A/usr/share/applications/.+\.desktop\z}
      && $path !~ m{(?:\A|/)\.\.(?:/|\z)};
    my @argv = ('python3', $desktop_launcher_path, '--entry', $path);
    # The baseline isolates the window created by this launch, so matching by
    # title only adds toolkit-specific brittleness.
    return $class->_launch_argv(
        \@argv,
        '',
        $timeout,
        undef,
        _allows_graceful_sigterm($entry),
    );
}

sub x11_wait_open {
    my ($class, $pid, $expected_name, $timeout) = @_;
    die "invalid X11 launch PID '$pid'"
      unless defined $pid && $pid =~ /\A[0-9]+\z/ && $pid > 1;
    return $class->result('x11-wait-open', $timeout, '--pid', $pid, '--name', $expected_name // '');
}

sub _launch_argv {
    my ($class, $argv, $expected_name, $timeout, $expected_pid, $allow_graceful_sigterm) = @_;
    my $started = time;
    my $baseline = $class->result('baseline', 3);
    my $status_path = sprintf('/tmp/openqa-gui-status-%d-%d', $$, int(time * 1000) % 1_000_000);
    my $graceful_signal_prefix = $allow_graceful_sigterm
      ? 'OPENQA_EXPECTED_GRACEFUL_SIGTERM=1 '
      : '';
    my $user_launcher_arguments = $graceful_signal_prefix . join ' ',
      _shell_quote($user_launcher_path),
      _shell_quote($status_path),
      (map { _shell_quote($_) } @$argv);
    select_console 'root-virtio-terminal';
    my $launch_command = join ' ',
      $user_launcher_arguments,
      '< /dev/null > /tmp/openqa-gui-launch.log 2>&1 &',
      'printf', _shell_quote(_marker_format('__OA_GUI_LAUNCH_DONE__') . '\\n');
    type_string $launch_command;
    send_key 'ret';
    die 'GUI supervisor launch did not finish'
      unless wait_serial '__OA_GUI_LAUNCH_DONE__', timeout => 15;

    my $launch_pid = $class->_read_child_pid($status_path);
    $session_launch_pids{$launch_pid} = 1;
    die "GUI supervisor did not expose a child PID for '$expected_name'"
      . ': ' . $class->_read_launch_debug($status_path)
      unless defined $launch_pid;
    my $window_pid = $expected_pid && $expected_pid eq 'pending' ? undef : $expected_pid;
    my $launch_memory = eval { $class->result('memory', 1, '--pid', $launch_pid) };
    my @wait_arguments = ('--name', $expected_name);
    push @wait_arguments, ('--pid', $window_pid) if defined $window_pid;
    my $opened = $class->result('wait-open', $timeout, @wait_arguments);
    if ($opened->{status} ne 'passed' && get_var('BIGLINUX_DEBUG_GUI_LAUNCH', 0)) {
        $opened->{error} = ($opened->{error} // 'accessible application window did not open')
          . ': ' . _read_launch_debug($status_path);
    }
    return (
        $baseline,
        $opened,
        'serial-console-gui-supervisor',
        time - $started,
        $status_path,
        $launch_pid,
        $launch_memory,
    );
}

sub interact {
    my ($class, $pid, $timeout) = @_;
    die "invalid AT-SPI application PID '$pid'" unless defined $pid && $pid =~ /\A[0-9]+\z/ && $pid > 1;
    $timeout //= 8;
    return $class->result('interact', $timeout, '--pid', $pid);
}

sub cleanup {
    my ($class, $timeout) = @_;
    die 'AT-SPI cleanup requires a positive timeout'
      unless defined $timeout && $timeout =~ /\A[1-9][0-9]*(?:\.[0-9]+)?\z/;
    select_console 'root-virtio-terminal';
    _kill_process_groups(keys %session_launch_pids);
    %session_launch_pids = ();
    select_console 'sut';
    return $class->result('cleanup', $timeout);
}

sub terminate_window {
    my ($class, $pid, $status_path, $launch_pid, $entry) = @_;
    die "AT-SPI returned invalid application PID '$pid'"
      unless defined $pid && $pid =~ /\A[0-9]+\z/ && $pid > 1;
    die "invalid GUI supervisor status path '$status_path'"
      unless defined $status_path && $status_path =~ m{\A/tmp/openqa-gui-status-[0-9]+-[0-9]+\z};

    my $keyboard_fallback = 0;
    my $close = $class->result('close', 8, '--pid', $pid);
    if ($close->{status} ne 'passed') {
        # Some toolkit windows expose no Window/Action close entry even though
        # the focused window still supports the normal desktop close shortcut.
        # Use that keyboard path only after AT-SPI interaction succeeded; the
        # process and exit-code checks below remain mandatory. This also
        # handles a toolkit close action that is accepted but leaves a dialog
        # or popup focused instead of terminating the application.
        my $native_close = _native_close_command($entry, $pid);
        if (defined $native_close) {
            select_console 'root-virtio-terminal';
            my $native_status = _run_guest_command($native_close, 5);
            if (defined $native_status && $native_status == 0) {
                $close = {
                    status => 'passed',
                    action => 'x11.wmctrl-close',
                    action_result => 1,
                };
            }
        }
        if ($close->{status} ne 'passed') {
            select_console 'sut';
            my $preferred_key = _preferred_close_key($entry) // 'alt-f4';
            send_key $preferred_key;
            $keyboard_fallback = 1;
            $close = {
                status => 'passed',
                action => 'keyboard.' . $preferred_key,
                action_result => 1,
            };
        }
    }
    my $wait_exit;
    my $process_gone = 0;
    if ($close->{status} eq 'passed') {
        select_console 'root-virtio-terminal';
        $wait_exit = _run_guest_command(
            "while test -d /proc/$pid && ! grep -q '^State:[[:space:]]*Z' /proc/$pid/status 2>/dev/null; do sleep 1; done",
            $keyboard_fallback ? 10 : 15,
        );
        $process_gone = defined $wait_exit && $wait_exit == 0;
    }
    if (!$process_gone) {
        my $graceful_quit = _graceful_quit_command($entry);
        if (defined $graceful_quit) {
            select_console 'root-virtio-terminal';
            my $quit_status = _run_guest_command($graceful_quit, 10);
            if (defined $quit_status && $quit_status == 0) {
                $wait_exit = _run_guest_command(
                    "while test -d /proc/$pid && ! grep -q '^State:[[:space:]]*Z' /proc/$pid/status 2>/dev/null; do sleep 1; done",
                    10,
                );
                $process_gone = defined $wait_exit && $wait_exit == 0;
                $close->{action} = 'graceful.' . $graceful_quit
                  if $process_gone;
            }
        }
    }
    if (!$process_gone) {
        # A successful AT-SPI close action can close a popup or reveal a save
        # dialog without terminating the application. Give the normal desktop
        # close path one chance before process cleanup.
        select_console 'sut';
        send_key 'alt-f4';
        select_console 'root-virtio-terminal';
        $wait_exit = _run_guest_command(
            "while test -d /proc/$pid && ! grep -q '^State:[[:space:]]*Z' /proc/$pid/status 2>/dev/null; do sleep 1; done",
            10,
        );
        $process_gone = defined $wait_exit && $wait_exit == 0;
    }
    my $cleanup_signal_exit_code;
    if (!$process_gone) {
        # LibreOffice can keep Alt+F4 focused on a transient menu/dialog.
        # Its application-level quit shortcut is the next graceful path.
        select_console 'sut';
        send_key 'ctrl-q';
        select_console 'root-virtio-terminal';
        $wait_exit = _run_guest_command(
            "while test -d /proc/$pid && ! grep -q '^State:[[:space:]]*Z' /proc/$pid/status 2>/dev/null; do sleep 1; done",
            10,
        );
        $process_gone = defined $wait_exit && $wait_exit == 0;
    }
    if (!$process_gone) {
        select_console 'root-virtio-terminal';
        $cleanup_signal_exit_code = _kill_process_groups($launch_pid, $pid);
        $wait_exit = _run_guest_command(
            "test ! -d /proc/$pid || grep -q '^State:[[:space:]]*Z' /proc/$pid/status 2>/dev/null",
            5,
        );
        $process_gone = defined $wait_exit && $wait_exit == 0;
    }
    select_console 'sut';

    my $closed = $class->result('wait-close', $process_gone ? 8 : 2, '--pid', $pid);
    my $raw_application_exit_code = _read_status_value(
        $status_path,
        'raw_exit_code',
        $process_gone ? 5 : 3,
    );
    my $application_exit_code = _read_exit_code(
        $status_path,
        $process_gone ? 5 : 3,
    );
    delete $session_launch_pids{$launch_pid}
      if defined $launch_pid && $process_gone;
    return {
        close_action_ok => $close->{status} eq 'passed',
        close_action => $close->{action},
        close_action_error => $close->{error},
        process_exit_code => $wait_exit,
        process_gone => $process_gone,
        cleanup_signal_exit_code => $cleanup_signal_exit_code,
        raw_application_exit_code => $raw_application_exit_code,
        application_exit_code => $application_exit_code,
        application_exit_ok => defined $application_exit_code && $application_exit_code == 0,
        closed => $closed,
    };
}

sub _allows_graceful_sigterm {
    my ($entry) = @_;
    return unless ref $entry eq 'HASH';
    my $binary = lc($entry->{launch_binary} // '');
    my %graceful_sigterm_application = map { $_ => 1 } qw(
      big-driver-manager
      biglinux-config
      big-kernel-manager
      big-store
      gufw
      jamesdsp
    );
    return 1 if $graceful_sigterm_application{$binary};
    return lc($entry->{path} // '') =~ m{/gufw\.desktop\z} ? 1 : 0;
}

sub _preferred_close_key {
    my ($entry) = @_;
    return unless ref $entry eq 'HASH';
    my $binary = lc($entry->{launch_binary} // '');
    my %bigbashview_application = map { $_ => 1 } qw(
      big-driver-manager
      biglinux-config
      big-kernel-manager
      big-store
      gufw
    );
    return 'ctrl-q' if $bigbashview_application{$binary}
      || lc($entry->{path} // '') =~ m{/gufw\.desktop\z};
    return;
}

sub _native_close_command {
    my ($entry, $pid) = @_;
    return unless ref $entry eq 'HASH';
    return unless defined $pid && $pid =~ /\A[0-9]+\z/;
    my $binary = lc($entry->{launch_binary} // '');
    my %bigbashview_application = map { $_ => 1 } qw(
      big-driver-manager
      biglinux-config
      big-kernel-manager
      big-store
      gufw
    );
    return unless $bigbashview_application{$binary}
      || lc($entry->{path} // '') =~ m{/gufw\.desktop\z};
    return 'window_id=$(wmctrl -l -p | awk -v pid=' . $pid
      . ' \'$3 == pid {print $1; exit}\'); test -n "$window_id"'
      . ' && wmctrl -i -c "$window_id"';
}

sub _graceful_quit_command {
    my ($entry) = @_;
    return unless ref $entry eq 'HASH';
    my $binary = lc($entry->{launch_binary} // '');
    my %kde_application_quit = map { $_ => 1 } qw(
      krunner
      big-driver-manager
      big-kernel-manager
      big-store
    );
    return "kquitapp6 $binary" if $kde_application_quit{$binary};
    return;
}

sub terminate_x11_window {
    my ($class, $status_path, $launch_pid, $entry, $window_pid) = @_;
    die "invalid X11 launch PID '$launch_pid'"
      unless defined $launch_pid && $launch_pid =~ /\A[0-9]+\z/ && $launch_pid > 1;
    my $wait_command = "while test -d /proc/$launch_pid && ! grep -q '^State:[[:space:]]*Z' /proc/$launch_pid/status 2>/dev/null; do sleep 1; done";
    my $close_action = 'keyboard.alt-f4';
    select_console 'root-virtio-terminal';
    my $native_close = _native_close_command($entry, $launch_pid);
    $native_close //= _x11_window_close_command($window_pid);
    my $wait_exit;
    if (defined $native_close) {
        my $native_status = _run_guest_command($native_close, 5);
        $wait_exit = _run_guest_command($wait_command, 10)
          if defined $native_status && $native_status == 0;
        $close_action = 'x11.wmctrl-close'
          if defined $wait_exit && $wait_exit == 0;
    }
    if (!defined $wait_exit || $wait_exit != 0) {
        select_console 'sut';
        send_key 'alt-f4';
        select_console 'root-virtio-terminal';
        $wait_exit = _run_guest_command($wait_command, 10);
    }
    my $process_gone = defined $wait_exit && $wait_exit == 0;
    if (!$process_gone) {
        select_console 'sut';
        send_key 'ctrl-q';
        select_console 'root-virtio-terminal';
        $wait_exit = _run_guest_command($wait_command, 10);
        $process_gone = defined $wait_exit && $wait_exit == 0;
        $close_action = 'keyboard.ctrl-q' if $process_gone;
    }
    if (!$process_gone) {
        select_console 'root-virtio-terminal';
        _kill_process_groups($launch_pid, $window_pid);
        $wait_exit = _run_guest_command($wait_command, 5);
        $process_gone = defined $wait_exit && $wait_exit == 0;
        $close_action = 'process-group.sigterm' if $process_gone;
    }
    select_console 'sut';
    my $application_exit_code = _read_exit_code($status_path, $process_gone ? 5 : 2);
    my $raw_application_exit_code = _read_status_value(
        $status_path,
        'raw_exit_code',
        $process_gone ? 5 : 2,
    );
    return {
        close_action_ok => $process_gone,
        close_action => $close_action,
        process_exit_code => $wait_exit,
        process_gone => $process_gone,
        raw_application_exit_code => $raw_application_exit_code,
        application_exit_code => $application_exit_code,
        application_exit_ok => defined $application_exit_code && $application_exit_code == 0,
    };
}

sub _x11_window_close_command {
    my ($pid) = @_;
    return unless defined $pid && $pid =~ /\A[0-9]+\z/ && $pid > 1;
    return 'window_id=$(wmctrl -l -p | awk -v pid=' . $pid
      . ' \'$3 == pid {print $1; exit}\'); test -n "$window_id"'
      . ' && wmctrl -i -c "$window_id"';
}

sub launch_exit_code {
    my ($class, $status_path, $timeout) = @_;
    die 'invalid GUI supervisor status path'
      unless defined $status_path
      && $status_path =~ m{\A/tmp/openqa-gui-status-[0-9]+-[0-9]+\z};
    return _read_exit_code($status_path, $timeout // 3);
}

sub abort_launch {
    my ($class, $status_path, @known_pids) = @_;
    return unless defined $status_path && $status_path =~ m{\A/tmp/openqa-gui-status-[0-9]+-[0-9]+\z};
    select_console 'root-virtio-terminal';
    my @pids = grep { defined $_ && $_ =~ /\A[0-9]+\z/ && $_ > 1 } @known_pids;
    my $pid = @pids ? undef : $class->_read_child_pid($status_path, 2);
    push @pids, $pid if defined $pid;
    my $cleanup_status = 1;
    if (@pids) {
        $cleanup_status = _kill_process_groups(@pids);
    }
    delete @session_launch_pids{@pids};
    select_console 'sut';
    return $cleanup_status;
}

sub _kill_process_groups {
    my @pids = grep { defined $_ && $_ =~ /\A[0-9]+\z/ && $_ > 1 } @_;
    return 1 unless @pids;
    my $pid_list = join ' ', @pids;
    return _run_guest_command(
        "kill_tree() { for child in \$(pgrep -P \"\$1\" 2>/dev/null || true); do kill_tree \"\$child\"; done; kill -- -\"\$1\" 2>/dev/null || true; kill -TERM \"\$1\" 2>/dev/null || true; }; for pid in $pid_list; do kill_tree \"\$pid\"; done; sleep 1; kill_tree_hard() { for child in \$(pgrep -P \"\$1\" 2>/dev/null || true); do kill_tree_hard \"\$child\"; done; kill -- -\"\$1\" 2>/dev/null || true; kill -KILL \"\$1\" 2>/dev/null || true; }; for pid in $pid_list; do kill_tree_hard \"\$pid\"; done",
        3,
    );
}

sub _run_guest_command {
    my ($command, $timeout) = @_;
    my $marker = sprintf('__OA_COMMAND_DONE_%d_%d__', $$, int(time * 1000) % 1_000_000);
    my $status_marker = sprintf('__OA_COMMAND_STATUS_%d_%d__', $$, int(time * 1000) % 1_000_000);
    my $wrapped = '{ ' . $command . '; code=$?; printf '
      . _shell_quote('%s\\n' . _marker_format($status_marker) . '\\n')
      . ' "$code"; printf '
      . _shell_quote(_marker_format($marker) . '\\n') . '; }';
    type_string $wrapped;
    send_key 'ret';
    my $status_regex = qr/(?:^|\r?\n)([0-9]+)\r?\n\Q$status_marker\E\r?\n\Q$marker\E/;
    my $serial = wait_serial $status_regex, timeout => $timeout;
    unless (defined $serial) {
        # The command may still be running in the foreground after the
        # serial wait expires. Interrupt it before issuing the next command.
        my $recovery_marker = sprintf('__OA_COMMAND_RECOVERED_%d_%d__', $$, int(time * 1000) % 1_000_000);
        type_string '', terminate_with => 'ETX';
        type_string 'printf ' . _shell_quote(_marker_format($recovery_marker) . '\\n');
        send_key 'ret';
        wait_serial $recovery_marker, no_regex => 1, timeout => 3;
        return undef;
    }
    my ($status) = $serial =~ $status_regex;
    return undef unless defined $status;
    return $status + 0;
}

sub _read_child_pid {
    my ($class, $status_path, $timeout) = @_;
    $timeout //= 15;
    my $attempts = $timeout < 5 ? 2 : 15;
    my $command = "pid=; for i in \$(seq 1 $attempts); do if [ -r '$status_path' ]; then pid=\$(awk -F= '/^child_pid=/{print \$2; exit}' '$status_path' 2>/dev/null || true); test -n \"\$pid\" && break; fi; sleep 1; done; printf '%s\\n' \"\${pid:-0}\"; printf ";
    $command .= _shell_quote(_marker_format('__OA_CHILD_PID_DONE__') . '\\n');
    type_string $command;
    send_key 'ret';
    my $serial = wait_serial qr/(?:^|\r?\n)([0-9]+)\r?\n__OA_CHILD_PID_DONE__/, $timeout;
    return undef unless defined $serial;
    my ($pid) = $serial =~ /(?:^|\r?\n)([0-9]+)\r?\n__OA_CHILD_PID_DONE__/;
    return undef unless defined $pid && $pid > 1;
    return $pid;
}

sub _read_launch_debug {
    my ($status_path) = @_;
    my $begin_marker = '__OA_GUI_DEBUG_BEGIN__';
    my $end_marker = '__OA_GUI_DEBUG_END__';
    my $display_awk = _shell_quote('$1 == "DISPLAY" {print $2; exit}');
    my $xauthority_awk = _shell_quote('$1 == "XAUTHORITY" {print $2; exit}');
    select_console 'root-virtio-terminal';
    my $command = 'printf '
      . _shell_quote(_marker_format($begin_marker))
      . '; cat '
      . _shell_quote($status_path)
      . ' 2>/dev/null; cat /tmp/openqa-gui-launch.log 2>/dev/null; cat /tmp/openqa-gui-supervisor.log 2>/dev/null; '
      . 'if command -v xprop >/dev/null 2>&1; then printf "x11-client-list="; '
      . 'xprop -root _NET_CLIENT_LIST_STACKING 2>/dev/null || true; '
      . 'for window_id in $(xprop -root _NET_CLIENT_LIST_STACKING 2>/dev/null | grep -oE "0x[0-9a-fA-F]+"); do '
      . 'xprop -id "$window_id" _NET_WM_PID _NET_WM_NAME WM_NAME 2>/dev/null || true; done; fi; '
      . 'id; printf "display=%s xauth=%s xdg=%s\\n" "$DISPLAY" "$XAUTHORITY" "$XDG_RUNTIME_DIR"; '
      . 'printf "session-display="; systemctl --user show-environment 2>/dev/null | awk -F= '
      . $display_awk . '; '
      . 'printf "session-xauth="; systemctl --user show-environment 2>/dev/null | awk -F= '
      . $xauthority_awk . '; '
      . 'getent passwd 1000 2>/dev/null || true; '
      . 'find /home /run/user -maxdepth 3 -name .Xauthority -ls 2>/dev/null || true; printf '
      . _shell_quote(_marker_format($end_marker));
    type_string $command;
    send_key 'ret';
    my $serial = wait_serial qr/\Q$begin_marker\E(.*?)\Q$end_marker\E/s, 10;
    select_console 'sut';
    return 'debug-unavailable' unless defined $serial;
    my ($debug) = $serial =~ /\Q$begin_marker\E(.*?)\Q$end_marker\E/s;
    $debug =~ s/\s+/ /g if defined $debug;
    $debug =~ s/\A\s+|\s+\z//g if defined $debug;
    $debug = substr($debug, 0, 800) if defined $debug;
    return defined $debug && length $debug ? $debug : 'empty-debug';
}

sub _read_registry_log {
    my $begin_marker = '__OA_ATSPI_REGISTRY_BEGIN__';
    my $end_marker = '__OA_ATSPI_REGISTRY_END__';
    select_console 'root-virtio-terminal';
    type_string 'printf ' . _shell_quote(_marker_format($begin_marker))
      . '; cat /tmp/openqa-atspi-registry.log 2>/dev/null; printf '
      . _shell_quote(_marker_format($end_marker));
    send_key 'ret';
    my $serial = wait_serial qr/\Q${begin_marker}\E(.*?)\Q${end_marker}\E/s, timeout => 5;
    select_console 'sut';
    return '' unless defined $serial;
    my ($log) = $serial =~ /\Q${begin_marker}\E(.*?)\Q${end_marker}\E/s;
    $log //= '';
    $log =~ s/\s+/ /g;
    $log =~ s/\A\s+|\s+\z//g;
    return substr($log, 0, 1200);
}

sub _read_exit_code {
    my ($status_path, $timeout) = @_;
    return _read_status_value($status_path, 'exit_code', $timeout);
}

sub _read_status_value {
    my ($status_path, $field, $timeout) = @_;
    $timeout //= 60;
    my $attempts = $timeout < 15 ? 5 : 45;
    select_console 'root-virtio-terminal';
    my $command = "code=MISSING; for i in \$(seq 1 $attempts); do candidate=\$(awk -F= '/^$field=/{print \$2; exit}' "
      . _shell_quote($status_path)
      . " 2>/dev/null || true); case \"\$candidate\" in '') sleep 1;; * ) code=\$candidate; break;; esac; done; printf "
      . _shell_quote('%s\\n' . _marker_format('__OA_APP_EXIT_DONE__') . '\\n')
      . q{ "$code"};
    type_string $command;
    send_key 'ret';
    my $serial = wait_serial qr/(?:MISSING\r?\n|\r?\n([0-9]+)\r?\n)__OA_APP_EXIT_DONE__/, $timeout;
    select_console 'sut';
    return undef unless defined $serial && $serial !~ /(?:^|\r?\n)MISSING\r?\n__OA_APP_EXIT_DONE__/;
    my ($exit_code) = $serial =~ /(?:^|\r?\n)([0-9]+)\r?\n__OA_APP_EXIT_DONE__/;
    return $exit_code;
}

sub _shell_quote {
    my ($value) = @_;
    $value =~ s/'/'"'"'/g;
    return "'$value'";
}

sub _marker_format {
    my ($marker) = @_;
    return join '', map { sprintf '\\%03o', ord } split //, $marker;
}

1;
