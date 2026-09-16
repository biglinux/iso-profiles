# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 BigLinux

package atspi;

use Mojo::Base -strict;

use Encode qw(encode);
use JSON::PP qw(decode_json);
use MIME::Base64 qw(decode_base64);
use Text::ParseWords qw(shellwords);
use Time::HiRes 'time';
use testapi;
use guest_shell qw(marker_format shell_quote);

my $probe_path = '/tmp/openqa-atspi-probe.py';
my $supervisor_path = '/tmp/openqa-gui-supervisor.sh';
my $user_launcher_path = '/tmp/openqa-gui-user-launch.sh';
my $desktop_launcher_path = '/tmp/desktop_entry_launcher.py';
my $process_handoff_path = '/tmp/openqa-process-handoff.py';
my $state_path = '/tmp/openqa-atspi-baseline.json';
my $session_state_path = '/tmp/openqa-atspi-session-baseline.json';
my $kernel_version;
my %session_launch_pids;
my $widget_pid;
my $widget_root_pid;

# The guest supervisor reports the shell wait status, so a process killed by a
# signal arrives as 128+signal. Only a fatal crash disqualifies an application:
# a non-zero exit, or the SIGTERM/SIGKILL this framework itself sends during
# cleanup, says nothing about whether the program works.
my %crash_exit_code = map { $_ => 1 } (
    133,    # SIGTRAP: a teardown exception must be explicit, not global
    132,    # SIGILL
    134,    # SIGABRT
    135,    # SIGBUS
    136,    # SIGFPE
    139,    # SIGSEGV
);

our $WALK_HEADROOM = 30;

# isotovideo writes record_info through a byte-oriented channel, so a window
# title carrying something like an em dash aborts the run with "Wide character
# in syswrite". Guest text is never trustworthy ASCII: pass encoded octets.
sub record_guest_info {
    my ($class, $title, $output) = @_;
    return record_info encode('UTF-8', "$title"), encode('UTF-8', "$output");
}

sub is_crash_exit_code {
    my ($code) = @_;
    return 0 unless defined $code && $code =~ /\A[0-9]+\z/;
    return $crash_exit_code{$code} ? 1 : 0;
}

sub _baseline_is_complete {
    my ($baseline) = @_;
    return ref $baseline eq 'HASH'
      && ($baseline->{status} // '') eq 'passed'
      && defined $baseline->{window_count}
      && $baseline->{window_count} =~ /\A[0-9]+\z/
      && exists $baseline->{mem_available_mib}
      && defined $baseline->{desktop};
}

# Install the guest side of the probe. Once per boot, because the installed
# system reboots into a filesystem where /tmp is empty again.
#
# This used to also hunt for the accessibility bus, pin AT_SPI_BUS_ADDRESS in
# the user environment and start its own at-spi-bus-launcher when it could not
# find one. Every part of that was harmful. at-spi-bus-launcher unlinks
# $XDG_RUNTIME_DIR/at-spi/bus before binding it, with no collision check, so a
# second launcher steals the socket from the session's own - which keeps
# running and keeps answering GetAddress with a path that no longer exists.
# Pinning that dead path then aborted the probe with "Couldn't connect to
# accessibility bus", and the failure branch ended in `exit 1`, which closed
# the login shell: every module after it typed into a `login:` prompt. The
# session owns its accessibility bus; the harness never repairs it silently.
sub install {
    my ($class) = @_;
    my $ready_marker = '__OA_A11Y_READY__';
    my $probe_url = data_url('atspi_probe.py');
    my $supervisor_url = data_url('gui_supervisor.sh');
    my $user_launcher_url = data_url('gui_user_launch.sh');
    my $launcher_url = data_url('desktop_entry_launcher.py');
    my $process_handoff_url = data_url('process_handoff.py');

    select_console 'user-virtio-terminal';
    my $command = join ' ',
      'curl --fail --silent --show-error', shell_quote($probe_url), '--output', shell_quote($probe_path), '&&',
      'curl --fail --silent --show-error', shell_quote($supervisor_url), '--output', shell_quote($supervisor_path), '&&',
      'curl --fail --silent --show-error', shell_quote($user_launcher_url), '--output', shell_quote($user_launcher_path), '&&',
      'curl --fail --silent --show-error', shell_quote($launcher_url), '--output', shell_quote($desktop_launcher_path), '&&',
      'curl --fail --silent --show-error', shell_quote($process_handoff_url), '--output', shell_quote($process_handoff_path), '&&',
      'chmod 755', shell_quote($probe_path), shell_quote($supervisor_path), shell_quote($user_launcher_path), shell_quote($desktop_launcher_path), shell_quote($process_handoff_path), '&&',
      'printf ', shell_quote(marker_format($ready_marker) . '%s\\n'), ' "$(uname -r)"';
    type_string $command;
    send_key 'ret';
    my $ready = wait_serial qr/\Q$ready_marker\E([^\r\n]+)/, timeout => 120;
    die 'the AT-SPI probe could not be installed in the guest' unless defined $ready;

    ($kernel_version) = $ready =~ /\Q$ready_marker\E([^\r\n]+)/;
    $kernel_version =~ s/\s+\z// if defined $kernel_version;
    die 'the AT-SPI probe did not report the guest kernel'
      unless defined $kernel_version && $kernel_version =~ /^[[:alnum:]][[:alnum:].+_~-]*$/;
    select_console 'sut';
    return $kernel_version;
}

# Take the baseline for the graphical session that is running now.
#
# Called once per session, not once per job: the wizard, the live desktop and
# the installed desktop are three different sessions, and a baseline from one
# says nothing about the windows of the next.
sub reset_baseline {
    my ($class) = @_;
    %session_launch_pids = ();

    $widget_pid = undef;
    $widget_root_pid = undef;
    # The wizard's exit precedes the next desktop's readiness. Wait for the
    # delivered session and its actual endpoints, without restarting services.
    my $session_url = data_url('desktop_session.py');
    my $ready = $class->run_command(
        'curl --fail --silent --show-error --max-time 15 ' . shell_quote($session_url)
          . ' --output /tmp/openqa-desktop-session.py && '
          . 'session_environment=$(python3 /tmp/openqa-desktop-session.py --timeout 90) && '
          . 'eval "$session_environment"', 120);
    die 'the desktop session did not become ready; no accessibility repair was attempted'
      unless defined $ready && $ready == 0;

    my $baseline = $class->result('baseline', 10);
    if (!_baseline_is_complete($baseline)) {
        die 'the AT-SPI baseline has an unexpected shape: '
          . (ref $baseline ? JSON::PP->new->canonical->encode($baseline) : 'not a structure');
    }
    select_console 'user-virtio-terminal';
    my $saved = _run_guest_command("cp '$state_path' '$session_state_path'", 5);
    die 'the AT-SPI session baseline could not be saved' unless defined $saved && $saved == 0;
    select_console 'sut';
    return $baseline;
}


sub kernel_version {
    return $kernel_version;
}

sub result {
    my ($class, $operation, $timeout, @arguments) = @_;
    # dump-widgets is deliberately absent: a whole widget tree does not fit
    # through a serial marker, and no test needs one. It is an operator's tool,
    # run from a console inside the guest (see openqa/README.md).
    die "invalid AT-SPI operation '$operation'"
      unless $operation =~ /\A(?:baseline|wait-open|x11-wait-open|wait-close|wait-widget|wait-gone|focused-widget|audit-window|smoke-window|active-window|activate-widget|close|cleanup|memory|inventory|inventory-chunk)\z/;
    die 'invalid AT-SPI timeout' unless defined $timeout && $timeout =~ /\A[0-9]+(?:\.[0-9]+)?\z/;

    my @command = (
        'python3', $probe_path, $operation,
        '--state', $state_path,
        '--timeout', $timeout,
    );
    push @command, @arguments;
    my $probe_command = join ' ', map { shell_quote($_) } @command;
    # One accessibility tree walk can take many seconds on a guest busy
    # installing, and the probe only checks its own deadline between walks. Two
    # seconds of headroom got the probe killed mid-answer during the
    # installation wait, which reads exactly like a real failure.
    my $probe_timeout = $timeout + $WALK_HEADROOM;
    my $shell_command = join ' ',
      'if command -v timeout >/dev/null 2>&1; then timeout --kill-after=2',
      shell_quote($probe_timeout), $probe_command, '; else', $probe_command, '; fi; printf',
      shell_quote(marker_format('__OPENQA_ATSPI_DONE__') . '\\n');

    select_console 'user-virtio-terminal';
    type_string $shell_command;
    send_key 'ret';
    my $serial = wait_serial(
        qr/(?:__OPENQA_ATSPI__([0-9a-f]+)\r?\n)?__OPENQA_ATSPI_DONE__/,
        $timeout + $WALK_HEADROOM + 5
    );
    if (!defined $serial) {
        # A broken client can leave a libatspi call blocked.  Keep the serial
        # shell usable so the remaining inventory still gets a result.
        select_console 'user-virtio-terminal';
        type_string '', terminate_with => 'ETX';
        type_string 'printf ' . shell_quote(marker_format('__OPENQA_ATSPI_RECOVERED__') . '\\n');
        send_key 'ret';
        wait_serial '__OPENQA_ATSPI_RECOVERED__', no_regex => 1, timeout => 3;
    }
    select_console 'sut';
    die "AT-SPI operation '$operation' returned no result" unless defined $serial;

    my ($hex) = $serial =~ /__OPENQA_ATSPI__([0-9a-f]+)/;
    unless (defined $hex) {
        # Whatever the probe printed instead of an answer is the diagnosis: a
        # libatspi abort, a Python traceback, a dead bus socket. Reporting only
        # "returned no result" threw that away and cost two rounds of guessing.
        my $printed = $serial // '';
        $printed =~ s/\r//g;
        $printed = substr $printed, -600;
        die "AT-SPI operation '$operation' returned no result; the guest printed: $printed";
    }
    my $result = eval { decode_json(pack 'H*', $hex) };
    die "AT-SPI operation '$operation' returned invalid JSON: $@"
      unless ref $result eq 'HASH';
    return $result;
}

# Resolve a process that deliberately crossed a privilege boundary.  The
# executable, UID and one unique environment value all have to match, and the
# guest helper observes the same PID/start-time identity twice.  This is a
# provenance handoff, not a global process-name or window-title search.
sub wait_process_handoff {
    my ($class, $executable, $environment_name, $environment_value, $uid, $timeout) = @_;
    die 'handoff executable must be an absolute path'
      unless defined $executable && $executable =~ m{\A/[A-Za-z0-9_./+:-]+\z};
    die 'invalid handoff environment name'
      unless defined $environment_name && $environment_name =~ /\A[A-Z_][A-Z0-9_]{0,63}\z/;
    die 'invalid handoff environment value'
      unless defined $environment_value
      && $environment_value =~ /\A[A-Za-z0-9_.:@+-]{1,256}\z/;
    die 'invalid handoff UID'
      unless defined $uid && $uid =~ /\A[0-9]+\z/;
    die 'invalid handoff timeout'
      unless defined $timeout && $timeout =~ /\A[1-9][0-9]*(?:\.[0-9]+)?\z/
      && $timeout <= 180;

    my @command = (
        'sudo', '-n', '--', 'python3', $process_handoff_path,
        '--timeout', $timeout,
        '--executable', $executable,
        '--uid', $uid,
        '--environment-name', $environment_name,
        '--environment-value', $environment_value,
    );
    my $probe_command = join ' ', map { shell_quote($_) } @command;
    my $done = marker_format('__OPENQA_PROCESS_DONE__');
    my $shell_command = join ' ',
      'if command -v timeout >/dev/null 2>&1; then timeout --kill-after=2',
      shell_quote($timeout + $WALK_HEADROOM), $probe_command,
      '; else', $probe_command, '; fi; printf', shell_quote($done . '\\n');

    select_console 'user-virtio-terminal';
    type_string $shell_command;
    send_key 'ret';
    my $serial = wait_serial(
        qr/(?:__OPENQA_PROCESS__([0-9a-f]+)\r?\n)?__OPENQA_PROCESS_DONE__/,
        $timeout + $WALK_HEADROOM + 5,
    );
    select_console 'sut';
    die 'privileged process handoff returned no result' unless defined $serial;
    my ($hex) = $serial =~ /__OPENQA_PROCESS__([0-9a-f]+)/;
    die 'privileged process handoff returned no machine-readable record'
      unless defined $hex;
    my $result = eval { decode_json(pack 'H*', $hex) };
    die "privileged process handoff returned invalid JSON: $@"
      unless ref $result eq 'HASH';
    if (($result->{status} // '') eq 'passed') {
        die 'privileged process handoff returned an invalid PID'
          unless defined $result->{pid} && $result->{pid} =~ /\A[0-9]+\z/
          && $result->{pid} > 1;
        $session_launch_pids{$result->{pid}} = 1;
    }
    return $result;
}

sub inventory {
    my ($class) = @_;
    my $result = $class->result('inventory', 30);
    # Carry the probe's own reason: learning that one unreadable desktop file
    # aborted the scan took decoding the serial log by hand.
    die 'desktop entry inventory did not return chunk metadata: '
      . (ref $result eq 'HASH' && $result->{error} ? $result->{error} : 'no reason given')
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
    my ($class, $entry, $timeout, $sample_memory) = @_;
    die 'desktop entry is not a mapping' unless ref $entry eq 'HASH';
    my $path = $entry->{path};
    die 'desktop entry has no absolute path'
      unless defined $path
      && $path =~ m{\A/usr/share/applications/.+\.desktop\z}
      && $path !~ m{(?:\A|/)\.\.(?:/|\z)};
    my @argv = ('python3', $desktop_launcher_path, '--entry', $path);
    # Identity comes from provenance: the launcher execs the application, so its
    # window must belong to the launched process tree. Matching a window title
    # would only add toolkit- and release-specific brittleness.
    return $class->_launch_argv(\@argv, '', $timeout, 'process-tree', $sample_memory);
}

sub launch_smoke_desktop_entry {
    my ($class, $entry, $open_timeout, $settle, $content_timeout,
        $close_timeout, $close_key, $close_mode) = @_;
    die 'desktop entry is not a mapping' unless ref $entry eq 'HASH';
    my $path = $entry->{path};
    die 'desktop entry has no absolute path'
      unless defined $path
      && $path =~ m{\A/usr/share/applications/.+\.desktop\z}
      && $path !~ m{(?:\A|/)\.\.(?:/|\z)};
    die 'invalid smoke open timeout'
      unless defined $open_timeout && $open_timeout =~ /\A[1-9][0-9]*(?:\.[0-9]+)?\z/
      && $open_timeout <= 180;
    die 'invalid smoke settle interval'
      unless defined $settle && $settle =~ /\A[0-9]+(?:\.[0-9]+)?\z/ && $settle <= 10;
    die 'invalid smoke content timeout'
      unless defined $content_timeout && $content_timeout =~ /\A[1-9][0-9]*(?:\.[0-9]+)?\z/
      && $content_timeout <= 120;
    die 'invalid smoke close timeout'
      unless defined $close_timeout && $close_timeout =~ /\A[1-9][0-9]*(?:\.[0-9]+)?\z/
      && $close_timeout <= 120;
    die 'invalid smoke close shortcut'
      unless defined $close_key && $close_key =~ /\A(?:alt-f4|ctrl-q|esc)\z/;
    die 'invalid smoke close mode'
      unless defined $close_mode && $close_mode =~ /\A(?:process-exit|window-close)\z/;

    my @argv = ('python3', $desktop_launcher_path, '--entry', $path);
    my ($baseline, $status_path, $launch_pid, $launch_memory, $started) =
      $class->_start_argv(\@argv, '', 0);
    my @command = (
        'python3', $probe_path, 'smoke-session',
        '--state', $state_path,
        '--timeout', $open_timeout,
        '--pid', $launch_pid,
        '--root-pid', $launch_pid,
        '--settle', $settle,
        '--content-timeout', $content_timeout,
        '--close-timeout', $close_timeout,
        '--close-mode', $close_mode,
    );
    my $probe_command = join ' ', map { shell_quote($_) } @command;
    my $total_timeout = $open_timeout + $settle + $content_timeout
      + $close_timeout + $WALK_HEADROOM;
    my $shell_command = join ' ',
      'if command -v timeout >/dev/null 2>&1; then timeout --kill-after=2',
      shell_quote($total_timeout), $probe_command,
      '; else', $probe_command, '; fi; printf',
      shell_quote(marker_format('__OPENQA_ATSPI_DONE__') . '\\n');

    select_console 'user-virtio-terminal';
    type_string $shell_command;
    send_key 'ret';
    my $ready_budget = $open_timeout + $settle + $content_timeout + $WALK_HEADROOM + 5;
    my $serial = wait_serial(
        qr/(?:__OPENQA_ATSPI_READY__([0-9a-f]+)|__OPENQA_ATSPI__([0-9a-f]+)\r?\n__OPENQA_ATSPI_DONE__)/,
        $ready_budget,
    );
    unless (defined $serial) {
        select_console 'user-virtio-terminal';
        type_string '', terminate_with => 'ETX';
        type_string 'printf ' . shell_quote(marker_format('__OPENQA_ATSPI_SESSION_RECOVERED__') . '\\n');
        send_key 'ret';
        wait_serial '__OPENQA_ATSPI_SESSION_RECOVERED__', no_regex => 1, timeout => 5;
        select_console 'sut';
        die 'application smoke session returned no readiness or failure result';
    }

    my ($ready_hex, $early_hex) = $serial =~
      /(?:__OPENQA_ATSPI_READY__([0-9a-f]+)|__OPENQA_ATSPI__([0-9a-f]+)\r?\n__OPENQA_ATSPI_DONE__)/;
    if (defined $early_hex) {
        select_console 'sut';
        my $early = eval { decode_json(pack 'H*', $early_hex) };
        die "application smoke session returned invalid early JSON: $@"
          unless ref $early eq 'HASH';
        $early->{error} = ($early->{error} // 'application smoke failed before readiness')
          . ': ' . _read_launch_debug($status_path)
          if ($early->{phase} // '') eq 'open';
        return ($baseline, $early, 'serial-console-persistent-atspi-smoke',
            time - $started, $status_path, $launch_pid, $launch_memory);
    }

    my $ready = eval { decode_json(pack 'H*', $ready_hex // '') };
    die "application smoke session returned invalid readiness JSON: $@"
      unless ref $ready eq 'HASH';
    die 'application smoke session did not prove active accessible content'
      unless ($ready->{status} // '') eq 'passed'
      && ($ready->{phase} // '') eq 'ready'
      && ($ready->{coverage} // '') eq 'accessible-content-present'
      && $ready->{active}
      && defined $ready->{pid} && $ready->{pid} =~ /\A[0-9]+\z/ && $ready->{pid} > 1;
    $class->set_widget_scope($ready->{pid}, $launch_pid);

    # The target was observed active by the same probe that now waits for its
    # exact window/process outcome. Send exactly one documented keyboard
    # request; no AT action, coordinate input or signal can satisfy the test.
    select_console 'sut';
    send_key $close_key;
    my $final_serial = wait_serial(
        qr/__OPENQA_ATSPI__([0-9a-f]+)\r?\n__OPENQA_ATSPI_DONE__/,
        $close_timeout + $WALK_HEADROOM + 5,
    );
    unless (defined $final_serial) {
        select_console 'user-virtio-terminal';
        type_string '', terminate_with => 'ETX';
        type_string 'printf ' . shell_quote(marker_format('__OPENQA_ATSPI_SESSION_RECOVERED__') . '\\n');
        send_key 'ret';
        wait_serial '__OPENQA_ATSPI_SESSION_RECOVERED__', no_regex => 1, timeout => 5;
        select_console 'sut';
        die 'application smoke session returned no close result';
    }
    select_console 'sut';
    my ($final_hex) = $final_serial =~
      /__OPENQA_ATSPI__([0-9a-f]+)\r?\n__OPENQA_ATSPI_DONE__/;
    my $result = eval { decode_json(pack 'H*', $final_hex // '') };
    die "application smoke session returned invalid final JSON: $@"
      unless ref $result eq 'HASH';
    $result->{close_action} = 'keyboard.' . $close_key;
    my $code = _read_exit_code($status_path, $result->{process_gone} ? 3 : 1);
    $result->{raw_application_exit_code} = $code;
    $result->{application_exit_code} = $code;
    $result->{application_crashed} = is_crash_exit_code($code) ? 1 : 0;
    delete $session_launch_pids{$launch_pid} if $result->{process_gone};
    return ($baseline, $result, 'serial-console-persistent-atspi-smoke',
        time - $started, $status_path, $launch_pid, $launch_memory);
}

sub x11_wait_open {
    my ($class, $pid, $expected_name, $timeout) = @_;
    die "invalid X11 launch PID '$pid'"
      unless defined $pid && $pid =~ /\A[0-9]+\z/ && $pid > 1;
    return $class->result(
        'x11-wait-open', $timeout,
        '--pid', $pid, '--root-pid', $pid, '--name', $expected_name // '');
}

# Scope follows the application, never the translated title or screen position.
sub set_widget_scope {
    my ($class, $pid, $root_pid) = @_;
    die 'invalid widget PID' if defined $pid && ($pid !~ /\A[0-9]+\z/ || $pid <= 1);
    die 'invalid widget supervisor root PID'
      if defined $root_pid && ($root_pid !~ /\A[0-9]+\z/ || $root_pid <= 1);
    die 'widget supervisor root requires a widget PID'
      if defined $root_pid && !defined $pid;
    $widget_pid = $pid;
    $widget_root_pid = $root_pid;
}

sub _widget_operation {
    my ($class, $operation, $role, $labels, $timeout, %options) = @_;
    die 'AT-SPI widget role is required' unless defined $role && $role ne '';
    my $label_list = encode('UTF-8', join '|', @{$labels // []});
    die 'AT-SPI widget labels must not contain a newline' if $label_list =~ /[\r\n]/;
    my $pid = exists $options{pid} ? $options{pid} : $widget_pid;
    my $root_pid = exists $options{root_pid} ? $options{root_pid}
      : exists $options{pid} && !defined $options{pid} ? undef
      : $widget_root_pid;
    my @args = ('--role', $role, '--labels', $label_list);
    push @args, ('--pid', $pid) if defined $pid;
    if (defined $root_pid) {
        die 'invalid AT-SPI supervisor root PID'
          unless $root_pid =~ /\A[0-9]+\z/ && $root_pid > 1;
        push @args, ('--root-pid', $root_pid);
    }
    push @args, ('--accessible-id', $options{id}) if defined $options{id};
    push @args, ('--window', encode('UTF-8', $options{window})) if defined $options{window};
    if (defined $options{application_index}) {
        die 'invalid AT-SPI application index'
          unless $options{application_index} =~ /\A[0-9]+\z/;
        push @args, ('--application-index', $options{application_index});
    }
    if ($options{positive_witness}) {
        die 'positive AT-SPI witness is only valid for wait-widget'
          unless $operation eq 'wait-widget';
        die 'positive AT-SPI witness cannot assert checked state'
          if exists $options{checked};
        push @args, '--positive-witness';
    }
    if (defined $options{startup_timeout_ms}) {
        die 'invalid AT-SPI startup timeout'
          unless $options{startup_timeout_ms} =~ /\A(?:-1|[0-9]+)\z/
          && $options{startup_timeout_ms} <= 15000;
        push @args, ('--startup-timeout-ms', $options{startup_timeout_ms});
    }
    push @args, ('--checked', $options{checked} ? 'true' : 'false') if exists $options{checked};
    return $class->result($operation, $timeout, @args);
}

sub wait_widget {
    my ($class, $role, $labels, $timeout, %options) = @_;
    return $class->_widget_operation('wait-widget', $role, $labels, $timeout, %options);
}

sub assert_widget {
    my ($class, $role, $labels, $timeout, %options) = @_;
    my $found = $class->wait_widget($role, $labels, $timeout, %options);
    die 'required accessible control unavailable: ' . ($found->{error} // 'incomplete observation')
      unless ($found->{status} // '') eq 'passed' && $found->{complete};
    return $found;
}

sub wait_widget_until {
    my ($class, $role, $labels, $total_timeout, $slice) = @_;
    $slice //= 60;
    my $deadline = time + $total_timeout;
    my $found = {status => 'inconclusive', error => 'probe did not answer'};
    while (time < $deadline) {
        my $remaining = $deadline - time;
        my $budget = $remaining < $slice ? $remaining : $slice;
        my $result = eval { $class->wait_widget($role, $labels, $budget) };
        $found = ref $result eq 'HASH' ? $result : {status => 'inconclusive', error => "$@"};
        return $found if ($found->{status} // '') eq 'passed' && $found->{complete};
    }
    return $found;
}

sub focused_widget {
    my ($class, $pid, $target_identity, $application_index, $root_pid) = @_;
    $pid //= $widget_pid;
    $root_pid //= $widget_root_pid;
    my @args = defined $pid ? ('--pid', $pid) : ();
    if (defined $root_pid) {
        die 'invalid AT-SPI supervisor root PID'
          unless $root_pid =~ /\A[0-9]+\z/ && $root_pid > 1;
        push @args, ('--root-pid', $root_pid);
    }
    push @args, ('--target-identity', $target_identity)
      if defined $target_identity;
    if (defined $application_index) {
        die 'invalid AT-SPI application index'
          unless $application_index =~ /\A[0-9]+\z/;
        push @args, ('--application-index', $application_index);
    }
    return $class->result('focused-widget', 5, @args);
}

# Tab traversal is observed after every key. An ID locates a target but cannot
# teleport focus to it. Radio groups also need arrow navigation. Repeated focus
# is bounded; no coordinate click, grab_focus, or AT action rescues this test.
sub focus_widget {
    my ($class, $role, $labels, $timeout, %options) = @_;
    my $target = $class->assert_widget($role, $labels, $timeout, %options)->{widget};
    die 'target has no human-readable accessible name' unless $target->{name} =~ /\S/;
    my $pid = $target->{pid};
    my $identity = $target->{identity};
    my $application_index = $target->{application_index};
    die 'target has no runtime accessibility identity' unless defined $identity && $identity ne '';
    die 'target has an invalid AT-SPI application index'
      if defined $application_index && $application_index !~ /\A[0-9]+\z/;
    my %visits;
    my $deadline = time + $timeout;
    for (1 .. 80) {
        die 'keyboard traversal timed out' if time >= $deadline;
        my $focus = $class->focused_widget(
            $pid, $identity, $application_index, $options{root_pid});
        if (($focus->{status} // '') eq 'passed') {
            my $current = $focus->{widget};
            if (($current->{identity} // '') eq $identity && $current->{pid} == $pid) {
                return $current;
            }
            my $key = ($current->{pid} // '') . ':' . ($current->{identity} // '');
            die 'keyboard focus cycled before reaching the requested control' if ++$visits{$key} > 3;
            select_console 'sut';
            send_key(($role =~ /radio/ && ($current->{role} // '') =~ /radio/) ? 'right' : 'tab');
        }
        else {
            my $reason = $focus->{reason} // '';
            die 'keyboard focus could not be observed: ' . ($focus->{error} // '')
              unless ($reason eq 'not-found' || $reason eq 'target-not-focused')
              && $focus->{complete};
            select_console 'sut';
            send_key 'tab';
        }
    }
    die 'keyboard traversal exhausted its bound';
}

sub activate_widget {
    my ($class, $role, $labels, $timeout, %options) = @_;
    my $widget = $class->focus_widget($role, $labels, $timeout, %options);
    select_console 'sut';
    send_key($role =~ /check|radio|toggle/ ? 'spc' : 'ret');
    return {status => 'passed', widget => $widget, activation => 'keyboard'};
}

sub activate_widget_until_gone {
    my ($class, $role, $labels, $timeout) = @_;
    $class->activate_widget($role, $labels, $timeout);
    my $gone = $class->_widget_operation('wait-gone', $role, $labels, $timeout);
    die 'control disappearance was not confirmed: ' . ($gone->{error} // 'incomplete query')
      unless ($gone->{status} // '') eq 'passed' && $gone->{complete}
      && ($gone->{reason} // '') eq 'absent';
    return 1;
}

sub _start_argv {
    my ($class, $argv, $expected_name, $sample_memory) = @_;
    $sample_memory //= 1;
    my $started = time;
    my $baseline = $class->result('baseline', 3);
    die 'application baseline is incomplete' unless _baseline_is_complete($baseline);
    my $status_path = sprintf('/tmp/openqa-gui-status-%d-%d', $$, int(time * 1000) % 1_000_000);
    my $user_launcher_arguments = join ' ',
      shell_quote($user_launcher_path),
      shell_quote($status_path),
      (map { shell_quote($_) } @$argv);
    select_console 'user-virtio-terminal';
    my $launch_command = join ' ',
      $user_launcher_arguments,
      '< /dev/null > /tmp/openqa-gui-launch.log 2>&1 &',
      'printf', shell_quote(marker_format('__OA_GUI_LAUNCH_DONE__') . '\\n');
    type_string $launch_command;
    send_key 'ret';
    die 'GUI supervisor launch did not finish'
      unless wait_serial '__OA_GUI_LAUNCH_DONE__', timeout => 15;

    my $launch_pid = $class->_read_child_pid($status_path);
    die "GUI supervisor did not expose a child PID for '$expected_name'"
      . ': ' . _read_launch_debug($status_path)
      unless defined $launch_pid;
    $session_launch_pids{$launch_pid} = 1;
    my $launch_memory = $sample_memory
      ? eval { $class->result('memory', 1, '--pid', $launch_pid) } : undef;
    return ($baseline, $status_path, $launch_pid, $launch_memory, $started);
}

sub _launch_argv {
    my ($class, $argv, $expected_name, $timeout, $expected_pid, $sample_memory) = @_;
    $sample_memory //= 1;
    my ($baseline, $status_path, $launch_pid, $launch_memory, $started) =
      $class->_start_argv($argv, $expected_name, $sample_memory);
    # 'process-tree' scopes the window search to this launch. A privileged
    # launcher can re-parent the real application outside our tree, so those
    # call sites stay unscoped and prove identity through the flow that follows.
    my $window_pid =
        !defined $expected_pid            ? undef
      : $expected_pid eq 'process-tree'   ? $launch_pid
      : $expected_pid eq 'pending'        ? undef
      :                                     $expected_pid;
    my @wait_arguments = ('--name', $expected_name);
    push @wait_arguments, '--no-memory-sample' unless $sample_memory;
    if (defined $window_pid) {
        push @wait_arguments, ('--pid', $window_pid);
        push @wait_arguments, ('--root-pid', $launch_pid)
          if $expected_pid eq 'process-tree';
    }
    my $opened = $class->result('wait-open', $timeout, @wait_arguments);
    if (($opened->{status} // '') eq 'passed') {
        my $scope_root = defined $expected_pid && $expected_pid eq 'process-tree'
          ? $launch_pid : undef;
        $class->set_widget_scope($opened->{pid}, $scope_root);
    }
    if ($opened->{status} ne 'passed') {
        # Always attach the launcher's own output. A release gate that reports
        # "no window appeared" and nothing else sends whoever reads it back
        # into the guest to find out why, and this dump was already written --
        # it was just hidden behind a debug variable nobody sets.
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

sub cleanup {
    my ($class, $timeout, @owned_pids) = @_;
    die 'AT-SPI cleanup requires a positive timeout'
      unless defined $timeout && $timeout =~ /\A[1-9][0-9]*(?:\.[0-9]+)?\z/;
    my %owned = map { $_ => 1 }
      grep { defined $_ && $_ =~ /\A[0-9]+\z/ && $_ > 1 }
      (keys %session_launch_pids, @owned_pids);
    select_console 'user-virtio-terminal';
    _kill_process_groups(keys %owned) if %owned;
    %session_launch_pids = ();
    my $owned_gone = 1;
    if (%owned) {
        my $probe = join ' && ', map {
            "(test ! -d /proc/$_ || grep -q '^State:[[:space:]]*Z' /proc/$_/status 2>/dev/null)"
        } sort { $a <=> $b } keys %owned;
        my $status = _run_guest_command($probe, 4);
        $owned_gone = defined $status && $status == 0;
    }
    select_console 'sut';
    my ($result, $probe_error);
    eval { $result = $class->result('cleanup', $timeout); 1 }
      or $probe_error = $@ || 'cleanup probe failed';
    return {status => 'failed', error => 'owned application processes remained after cleanup'}
      unless $owned_gone;
    return $result if ref $result eq 'HASH' && ($result->{status} // '') eq 'passed';
    return $result if ref $result eq 'HASH' && ($result->{status} // '') eq 'failed';
    # The tested application has already proved its normal close contract, and
    # every process group owned by this launch is gone. A stale, unrelated
    # AT-SPI provider must not retroactively turn that application into a
    # failure. Preserve the infrastructure problem as an explicit warning.
    my $warning = ref $result eq 'HASH' ? ($result->{error} // 'cleanup observation incomplete')
      : ($probe_error // 'cleanup observation unavailable');
    return {
        status => 'passed',
        degraded => 1,
        isolation => 'owned-process-groups-gone',
        warning => $warning,
    };
}

# The generic smoke sends exactly one normal close shortcut. It never invokes
# an AT action, native quit command or kill to make the close test pass.
sub close_with_shortcut {
    my ($class, $pid, $status_path, $launch_pid, $timeout, $key, $mode,
        $window_identity, $dismiss_auxiliary, $application_index) = @_;
    $timeout //= 15;
    $key //= 'alt-f4';
    $mode //= 'process-exit';
    $dismiss_auxiliary //= 0;
    die 'invalid close timeout' unless $timeout =~ /\A[1-9][0-9]*\z/;
    die 'invalid close shortcut' unless $key =~ /\A(?:alt-f4|ctrl-q|esc)\z/;
    die 'invalid close observation mode'
      unless $mode =~ /\A(?:process-exit|window-close)\z/;
    die 'invalid auxiliary-window dismissal contract'
      unless $dismiss_auxiliary == 0 || $dismiss_auxiliary == 1;
    die 'auxiliary-window dismissal requires Ctrl+Q'
      if $dismiss_auxiliary && $key ne 'ctrl-q';
    die 'invalid application PID' unless defined $pid && $pid =~ /\A[0-9]+\z/ && $pid > 1;
    die 'invalid supervisor status file' unless defined $status_path
      && $status_path =~ m{\A/tmp/openqa-gui-status-[0-9]+-[0-9]+\z};
    die 'invalid accessible window identity'
      if defined $window_identity
      && ($window_identity !~ m{\A[A-Za-z0-9_./:-]+\z}
      || length($window_identity) > 4096);
    die 'invalid AT-SPI application index'
      if defined $application_index && $application_index !~ /\A[0-9]+\z/;
    my @active_scope = ('--pid', $pid);
    push @active_scope, ('--root-pid', $launch_pid)
      if defined $launch_pid;
    push @active_scope, ('--application-index', $application_index)
      if defined $application_index;
    push @active_scope, ('--window-identity', $window_identity)
      if defined $window_identity && !$dismiss_auxiliary;
    my $active = $class->result('active-window', 5, @active_scope);
    die 'cannot close an unobserved or inactive application: ' . ($active->{error} // '')
      unless ($active->{status} // '') eq 'passed' && $active->{active} && $active->{pid} == $pid;

    my @pre_close_actions;
    if ($dismiss_auxiliary) {
        # A reviewed first launch can expose more than one transient surface in
        # sequence (for example LibreOffice's template chooser followed by Tip
        # of the Day).  Dismiss only currently observed surfaces from the same
        # supervised launch, at most three times.  Re-observe after every key;
        # never guess a second key or accept a different application's window.
        my $settled = 0;
        for my $round (1 .. 3) {
            my $window_count = $active->{application_window_count} // 1;
            my $active_role = $active->{window_role} // '';
            my $separate_top_level = $active_role eq 'dialog' || $window_count > 1;
            my $previous_identity = $active->{window_identity} // '';
            my $pre_key = $separate_top_level ? 'alt-f4' : 'esc';
            select_console 'sut';
            send_key $pre_key;
            push @pre_close_actions, 'keyboard.' . $pre_key;

            my $deadline = time + 5;
            my $dismissed = 0;
            while (time < $deadline) {
                sleep 0.25;
                my $candidate = eval { $class->result('active-window', 1, @active_scope) };
                next unless ref $candidate eq 'HASH'
                  && ($candidate->{status} // '') eq 'passed'
                  && $candidate->{active}
                  && $candidate->{pid} == $pid;
                my $candidate_identity = $candidate->{window_identity} // '';
                my $candidate_count = $candidate->{application_window_count} // $window_count;
                if ($separate_top_level) {
                    next unless ($previous_identity ne '' && $candidate_identity ne $previous_identity)
                      || $candidate_count < $window_count
                      || ($candidate->{window_role} // '') ne 'dialog';
                }
                $window_identity = $candidate_identity if $candidate_identity ne '';
                if (defined $candidate->{application_index}
                    && $candidate->{application_index} =~ /\A[0-9]+\z/) {
                    $application_index = $candidate->{application_index};
                    @active_scope = ('--pid', $pid);
                    push @active_scope, ('--root-pid', $launch_pid)
                      if defined $launch_pid;
                    push @active_scope, ('--application-index', $application_index);
                }
                $active = $candidate;
                $dismissed = 1;
                last;
            }
            die 'auxiliary first-run surface did not return control to the application'
              unless $dismissed;

            # A second surface can be scheduled immediately after the first
            # closes.  Require a stable re-observation before the application
            # Quit shortcut; this remains a bounded semantic check, not a
            # screenshot comparison or an unobserved key sequence.
            sleep 0.5;
            my $stable = eval { $class->result('active-window', 1, @active_scope) };
            die 'application focus could not be re-observed after auxiliary dismissal'
              unless ref $stable eq 'HASH'
              && ($stable->{status} // '') eq 'passed'
              && $stable->{active}
              && $stable->{pid} == $pid;
            my $stable_identity = $stable->{window_identity} // '';
            $window_identity = $stable_identity if $stable_identity ne '';
            if (defined $stable->{application_index}
                && $stable->{application_index} =~ /\A[0-9]+\z/) {
                $application_index = $stable->{application_index};
                @active_scope = ('--pid', $pid);
                push @active_scope, ('--root-pid', $launch_pid)
                  if defined $launch_pid;
                push @active_scope, ('--application-index', $application_index);
            }
            $active = $stable;
            my $stable_count = $active->{application_window_count} // 1;
            my $stable_role = $active->{window_role} // '';
            if ($stable_role ne 'dialog' && $stable_count <= 1) {
                $settled = 1;
                last;
            }
        }
        die 'too many sequential auxiliary first-run surfaces'
          unless $settled;
    }
    my $pre_close_action = @pre_close_actions
      ? join(',', @pre_close_actions) : undef;
    select_console 'sut';
    send_key $key;
    my ($gone, $window_closed) = (0, 0);
    if ($mode eq 'window-close') {
        my @close_scope = ('--pid', $pid);
        push @close_scope, ('--root-pid', $launch_pid)
          if defined $launch_pid;
        push @close_scope, ('--window-identity', $window_identity)
          if defined $window_identity;
        my $closed = $class->result('wait-close', $timeout, @close_scope);
        $window_closed = ($closed->{status} // '') eq 'passed'
          && ($closed->{accessible_window} // 0) ? 1 : 0;
        # A shared service may outlive its window. Observe whether it exited,
        # but do not spend the whole close budget a second time.
        my $wait = $class->run_command(_wait_for_exit_command($pid, 1), 6);
        $gone = defined $wait && $wait == 0;
        $window_closed = 1 if $gone;
    }
    else {
        my $wait = $class->run_command(_wait_for_exit_command($pid, $timeout), $timeout + 5);
        $gone = defined $wait && $wait == 0;
        $window_closed = $gone;
    }
    my $code = _read_exit_code($status_path, $gone ? 3 : 1);
    delete $session_launch_pids{$launch_pid} if defined $launch_pid && $gone;
    return {close_action => 'keyboard.' . $key, pre_close_action => $pre_close_action,
        process_gone => $gone,
        window_closed => $window_closed, graceful_exit => $gone,
        raw_application_exit_code => $code,
        application_exit_code => $code, application_crashed => is_crash_exit_code($code)};
}

sub terminate_window {
    my ($class, $pid, $status_path, $launch_pid, $entry, $keyboard_only) = @_;
    die "AT-SPI returned invalid application PID '$pid'"
      unless defined $pid && $pid =~ /\A[0-9]+\z/ && $pid > 1;
    die "invalid GUI supervisor status path '$status_path'"
      unless defined $status_path && $status_path =~ m{\A/tmp/openqa-gui-status-[0-9]+-[0-9]+\z};

    my $keyboard_fallback = 0;
    my $close = $keyboard_only
      ? {status => 'failed', error => 'keyboard-only task'}
      : $class->result('close', 8, '--pid', $pid);
    if ($close->{status} ne 'passed') {
        # Some toolkit windows expose no Window/Action close entry even though
        # the focused window still supports the normal desktop close shortcut.
        # The process and crash checks below remain mandatory. This also
        # handles a toolkit close action that is accepted but leaves a dialog
        # or popup focused instead of terminating the application.
        my $native_close = $keyboard_only ? undef : _native_close_command($entry, $pid);
        if (defined $native_close) {
            select_console 'user-virtio-terminal';
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
        select_console 'user-virtio-terminal';
        $wait_exit = _run_guest_command(
            _wait_for_exit_command($pid, $keyboard_fallback ? 17 : 27),
            $keyboard_fallback ? 20 : 30,
        );
        $process_gone = defined $wait_exit && $wait_exit == 0;
    }
    if (!$process_gone) {
        my $graceful_quit = $keyboard_only ? undef : _graceful_quit_command($entry);
        if (defined $graceful_quit) {
            select_console 'user-virtio-terminal';
            my $quit_status = _run_guest_command($graceful_quit, 10);
            if (defined $quit_status && $quit_status == 0) {
                $wait_exit = _run_guest_command(
                    _wait_for_exit_command($pid, 17),
                    20,
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
        select_console 'user-virtio-terminal';
        $wait_exit = _run_guest_command(
            _wait_for_exit_command($pid, 17),
            20,
        );
        $process_gone = defined $wait_exit && $wait_exit == 0;
    }
    my $cleanup_signal_exit_code;
    if (!$process_gone) {
        # LibreOffice can keep Alt+F4 focused on a transient menu/dialog.
        # Its application-level quit shortcut is the next graceful path.
        select_console 'sut';
        send_key 'ctrl-q';
        select_console 'user-virtio-terminal';
        $wait_exit = _run_guest_command(
            _wait_for_exit_command($pid, 17),
            20,
        );
        $process_gone = defined $wait_exit && $wait_exit == 0;
    }
    if (!$process_gone) {
        select_console 'user-virtio-terminal';
        $cleanup_signal_exit_code = _kill_process_groups($launch_pid, $pid);
        $wait_exit = _run_guest_command(
            "test ! -d /proc/$pid || grep -q '^State:[[:space:]]*Z' /proc/$pid/status 2>/dev/null",
            5,
        );
        $process_gone = defined $wait_exit && $wait_exit == 0;
    }
    select_console 'sut';

    my @close_scope = ('--pid', $pid);
    push @close_scope, ('--root-pid', $launch_pid)
      if defined $launch_pid;
    my $closed = $class->result(
        'wait-close', $process_gone ? 8 : 2, @close_scope);
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
        close_action => $close->{action},
        close_action_error => $close->{error},
        process_exit_code => $wait_exit,
        process_gone => $process_gone,
        cleanup_signal_exit_code => $cleanup_signal_exit_code,
        graceful_exit => $process_gone && !defined $cleanup_signal_exit_code,
        raw_application_exit_code => $raw_application_exit_code,
        application_exit_code => $application_exit_code,
        application_crashed => is_crash_exit_code($raw_application_exit_code),
        closed => $closed,
    };
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
    my $wait_command = _wait_for_exit_command($launch_pid, 17);
    my $close_action = 'keyboard.alt-f4';
    select_console 'user-virtio-terminal';
    my $native_close = _native_close_command($entry, $launch_pid);
    $native_close //= _x11_window_close_command($window_pid);
    my $wait_exit;
    if (defined $native_close) {
        my $native_status = _run_guest_command($native_close, 5);
        $wait_exit = _run_guest_command($wait_command, 20)
          if defined $native_status && $native_status == 0;
        $close_action = 'x11.wmctrl-close'
          if defined $wait_exit && $wait_exit == 0;
    }
    if (!defined $wait_exit || $wait_exit != 0) {
        select_console 'sut';
        send_key 'alt-f4';
        select_console 'user-virtio-terminal';
        $wait_exit = _run_guest_command($wait_command, 20);
    }
    my $process_gone = defined $wait_exit && $wait_exit == 0;
    if (!$process_gone) {
        select_console 'sut';
        send_key 'ctrl-q';
        select_console 'user-virtio-terminal';
        $wait_exit = _run_guest_command($wait_command, 20);
        $process_gone = defined $wait_exit && $wait_exit == 0;
        $close_action = 'keyboard.ctrl-q' if $process_gone;
    }
    if (!$process_gone) {
        select_console 'user-virtio-terminal';
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
        close_action => $close_action,
        process_exit_code => $wait_exit,
        process_gone => $process_gone,
        raw_application_exit_code => $raw_application_exit_code,
        application_exit_code => $application_exit_code,
        application_crashed => is_crash_exit_code($raw_application_exit_code),
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
    select_console 'user-virtio-terminal';
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

# testapi's script_run and upload_logs speak their own protocol on the serial
# console and time out on this image, so guest commands and guest files travel
# the marker path the rest of this module already relies on.
sub run_command {
    my ($class, $command, $timeout) = @_;
    select_console 'user-virtio-terminal';
    my $exit_code = _run_guest_command($command, $timeout // 30);
    select_console 'sut';
    return $exit_code;
}

# Poll a guest condition until it holds. Deliberately without "exit": these
# commands run inside the interactive login shell, so an exit ends the session
# and the getty respawns a login prompt. That turned a display manager which
# was up, greeter and all, into "did not start its display manager".
sub run_command_until {
    my ($class, $probe, $seconds) = @_;
    return $class->run_command(
        "i=0; while [ \$i -lt $seconds ] && ! { $probe; }; do sleep 1; i=\$((i+1)); done; $probe",
        $seconds + $WALK_HEADROOM);
}

sub upload_guest_file {
    my ($class, $guest_path, $log_name) = @_;
    die "invalid guest path '$guest_path'"
      unless defined $guest_path && $guest_path =~ m{\A/[^\s'"]+\z};
    die "invalid uploaded log name '$log_name'"
      unless defined $log_name && $log_name =~ /\A[A-Za-z0-9][A-Za-z0-9._-]*\z/;
    my $command = join ' ',
      'test -s', shell_quote($guest_path), '&&',
      'curl --fail --silent --show-error --max-time 90',
      '--form', shell_quote('upload=@' . $guest_path),
      '--form', shell_quote('upname=' . $log_name),
      shell_quote(autoinst_url("/uploadlog/$log_name"));
    return $class->run_command($command, 120);
}

sub _wait_for_exit_command {
    my ($pid, $seconds) = @_;
    # The loop bounds itself in the guest. Without a deadline it keeps running
    # in the foreground after the host's serial wait expires, and every command
    # typed afterwards is read by the loop instead of the shell: one slow
    # application close cascaded into three failed modules on a GitHub runner,
    # where an application that closes in two seconds here took longer than
    # the 15 second budget. A non-zero status on the deadline is what the
    # callers already expect from "the process is still there".
    #
    # "break" and a status variable, never "exit": _run_guest_command wraps the
    # command in braces and runs it in the login shell, so an exit here closes
    # the serial console and every module after it dies on a dead console.
    return "deadline=\$((\$(date +%s) + $seconds)); timed_out=0; "
      . "while test -d /proc/$pid "
      . "&& ! grep -q '^State:[[:space:]]*Z' /proc/$pid/status 2>/dev/null; do "
      . "if test \"\$(date +%s)\" -ge \"\$deadline\"; then timed_out=1; break; fi; "
      . "sleep 1; done; test \"\$timed_out\" -eq 0";
}

sub _run_guest_command {
    my ($command, $timeout) = @_;
    my $marker = sprintf('__OA_COMMAND_DONE_%d_%d__', $$, int(time * 1000) % 1_000_000);
    my $status_marker = sprintf('__OA_COMMAND_STATUS_%d_%d__', $$, int(time * 1000) % 1_000_000);
    my $wrapped = '{ ' . $command . '; code=$?; printf '
      . shell_quote('%s\\n' . marker_format($status_marker) . '\\n')
      . ' "$code"; printf '
      . shell_quote(marker_format($marker) . '\\n') . '; }';
    type_string $wrapped;
    send_key 'ret';
    my $status_regex = qr/(?:^|\r?\n)([0-9]+)\r?\n\Q$status_marker\E\r?\n\Q$marker\E/;
    my $serial = wait_serial $status_regex, timeout => $timeout;
    unless (defined $serial) {
        # The command may still be running in the foreground after the
        # serial wait expires. Interrupt it before issuing the next command.
        my $recovery_marker = sprintf('__OA_COMMAND_RECOVERED_%d_%d__', $$, int(time * 1000) % 1_000_000);
        type_string '', terminate_with => 'ETX';
        type_string 'printf ' . shell_quote(marker_format($recovery_marker) . '\\n');
        send_key 'ret';
        # Generous on purpose: this only runs after a command already
        # overran, and failing to interrupt it leaves the console unusable
        # for every module that follows.
        wait_serial $recovery_marker, no_regex => 1, timeout => 15;
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
    $command .= shell_quote(marker_format('__OA_CHILD_PID_DONE__') . '\\n');
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
    my $display_awk = shell_quote('$1 == "DISPLAY" {print $2; exit}');
    my $xauthority_awk = shell_quote('$1 == "XAUTHORITY" {print $2; exit}');
    select_console 'user-virtio-terminal';
    my $command = 'printf '
      . shell_quote(marker_format($begin_marker))
      . '; cat '
      . shell_quote($status_path)
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
      . shell_quote(marker_format($end_marker));
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

sub _read_exit_code {
    my ($status_path, $timeout) = @_;
    return _read_status_value($status_path, 'exit_code', $timeout);
}

my $status_read_serial = 0;

sub _read_status_value {
    my ($status_path, $field, $timeout) = @_;
    $timeout //= 60;
    my $attempts = $timeout < 15 ? 5 : 45;
    # A unique marker per call plus a host wait that outlives the guest poll
    # loop; otherwise the next back-to-back read could match this call's
    # leftover "MISSING" output and return the wrong field's value.
    my $marker = sprintf('__OA_APP_EXIT_DONE_%d_%d__', $$, ++$status_read_serial);
    select_console 'user-virtio-terminal';
    my $command = "code=MISSING; for i in \$(seq 1 $attempts); do candidate=\$(awk -F= '/^$field=/{print \$2; exit}' "
      . shell_quote($status_path)
      . " 2>/dev/null || true); case \"\$candidate\" in '') sleep 1;; * ) code=\$candidate; break;; esac; done; printf "
      . shell_quote('%s\\n' . marker_format($marker) . '\\n')
      . q{ "$code"};
    type_string $command;
    send_key 'ret';
    my $serial = wait_serial qr/(?:MISSING\r?\n|\r?\n([0-9]+)\r?\n)\Q$marker\E/, $attempts + 5;
    unless (defined $serial) {
        # Interrupt the still-running poll loop so its late output cannot
        # desynchronize the next serial command.
        my $recovery_marker = sprintf('__OA_APP_EXIT_RECOVERED_%d_%d__', $$, $status_read_serial);
        type_string '', terminate_with => 'ETX';
        type_string 'printf ' . shell_quote(marker_format($recovery_marker) . '\\n');
        send_key 'ret';
        wait_serial $recovery_marker, no_regex => 1, timeout => 3;
    }
    select_console 'sut';
    return undef unless defined $serial && $serial !~ /(?:^|\r?\n)MISSING\r?\n\Q$marker\E/;
    my ($exit_code) = $serial =~ /(?:^|\r?\n)([0-9]+)\r?\n\Q$marker\E/;
    return defined $exit_code ? 0 + $exit_code : undef;
}



1;
