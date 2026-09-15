# SPDX-License-Identifier: GPL-2.0-or-later
package application_smoke;

use Mojo::Base -strict;
use testapi;
use atspi;
use JSON::PP ();
use Time::HiRes qw(time sleep);

# The same contract is used by the live inventory and installed-app selection.
# It does not install packages, require Orca RPC, or perform app-specific tasks.
sub not_applicable_reason {
    my ($class, $entry) = @_;
    return 'not installed in this ISO' unless defined $entry;
    return $entry->{not_applicable_reason} if $entry->{not_applicable_reason};
    return 'terminal command is outside the graphical smoke test' if $entry->{terminal};
    my $binary = $entry->{launch_binary} // '';
    return 'session service has no standalone application window'
      if $binary eq 'orca' || $binary eq 'fcitx5';
    return;
}

# These applications document Ctrl+Q as application Quit. Alt+F4 may close
# only a document/tool window. Still send one ordinary shortcut, never a
# sequence of guessed actions or a signal. The job setting remains an override.
sub default_close_key {
    my ($class, $entry) = @_;
    my $id = $entry->{relative_path} // $entry->{path} // '';
    $id =~ s{.*/}{};
    return 'ctrl-q' if $id eq 'gimp.desktop'
      || $id =~ /\Alibreoffice-(?:base|calc|draw|impress|math|startcenter|writer|xsltfilter)\.desktop\z/;
    return 'alt-f4';
}

sub _contract {
    my ($class, $entry) = @_;
    my $coverage = ref $entry->{_coverage} eq 'HASH' ? $entry->{_coverage} : {};
    my $kind = $coverage->{execution_contract} // 'standard';
    die "unsupported application contract '$kind'"
      unless $kind =~ /\A(?:standard|shared-window|transient-dialog)\z/;
    my $codes = $coverage->{contract_allowed_exit_codes};
    $codes = $kind eq 'transient-dialog' ? [0, 1] : [0]
      unless ref $codes eq 'ARRAY' && @$codes;
    my %seen_code;
    for my $code (@$codes) {
        die 'invalid application contract exit code'
          unless defined $code && "$code" =~ /\A[0-9]+\z/ && $code <= 255;
        die 'duplicate application contract exit code' if $seen_code{$code}++;
    }
    my $requirements = ref $coverage->{contract_requirements} eq 'ARRAY'
      ? [@{$coverage->{contract_requirements}}] : [];
    my %allowed_requirement = map { $_ => 1 }
      qw(alsa-card native-x11 uefi-variables video-device);
    my %seen_requirement;
    for my $requirement (@$requirements) {
        die "invalid application contract requirement '$requirement'"
          unless defined $requirement && $allowed_requirement{$requirement};
        die "duplicate application contract requirement '$requirement'"
          if $seen_requirement{$requirement}++;
    }
    return {
        kind => $kind,
        reason => $coverage->{contract_reason}
          // 'Default strict graphical application contract',
        close_key => $coverage->{contract_close_key},
        close_timeout => $coverage->{contract_close_timeout},
        content_timeout => $coverage->{contract_content_timeout},
        allowed_exit_codes => [map { 0 + $_ } @$codes],
        requirements => $requirements,
    };
}

sub _requirement_not_applicable_reason {
    my ($class, $requirement) = @_;
    # Every command has three outcomes: 0 means available, 3 means a
    # confirmed absence, and any other code means the preflight itself failed.
    # A missing utility or an unreadable kernel interface must never be
    # converted into "not applicable".
    my %probe = (
        'alsa-card' => {
            command => q{capability_probe() { if [ ! -r /proc/asound/cards ]; then return 3; fi; grep -qE '^[[:space:]]*[0-9]+[[:space:]]+\[' /proc/asound/cards; code=$?; [ "$code" -eq 0 ] && return 0; [ "$code" -eq 1 ] && return 3; return 2; }; capability_probe},
            reason => 'no ALSA hardware card is available in this environment',
        },
        'native-x11' => {
            command => q{capability_probe() { [ "${XDG_SESSION_TYPE:-}" = x11 ] && return 0; return 3; }; capability_probe},
            reason => 'the current desktop session is not native X11',
        },
        'uefi-variables' => {
            command => q{capability_probe() { if [ ! -d /sys/firmware/efi/efivars ]; then return 3; fi; first=$(find /sys/firmware/efi/efivars -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null) || return 2; [ -n "$first" ] && return 0; return 3; }; capability_probe},
            reason => 'UEFI firmware variables are unavailable in this environment',
        },
        'video-device' => {
            command => q{capability_probe() { found=0; for device in /dev/video[0-9]*; do [ -c "$device" ] || continue; found=1; break; done; [ "$found" -eq 1 ] && return 0; return 3; }; capability_probe},
            reason => 'no V4L2 capture device is available in this environment',
        },
    );
    die "unsupported application capability '$requirement'" unless $probe{$requirement};
    my $status = atspi->run_command($probe{$requirement}{command}, 5);
    die "could not inspect application capability '$requirement'"
      unless defined $status;
    return undef if $status == 0;
    return $probe{$requirement}{reason} if $status == 3;
    die "application capability probe '$requirement' exited with status $status";
}

sub _dynamic_not_applicable_reason {
    my ($class, $contract) = @_;
    for my $requirement (@{$contract->{requirements}}) {
        my $reason = $class->_requirement_not_applicable_reason($requirement);
        return $reason if defined $reason;
    }
    return;
}

sub _exit_code_allowed {
    my ($class, $contract, $code) = @_;
    return scalar grep { $_ == $code } @{$contract->{allowed_exit_codes}};
}

sub check {
    my ($class, $entry, $timeout) = @_;
    if (my $reason = $class->not_applicable_reason($entry)) {
        return {status => 'skipped', skip_reason => $reason,
            functional_status => 'not-applicable', accessibility_status => 'not-applicable',
            screen_reader_status => 'not-tested'};
    }
    my $contract = $class->_contract($entry);
    my ($capability_reason, $capability_error);
    eval {
        $capability_reason = $class->_dynamic_not_applicable_reason($contract);
        1;
    } or $capability_error = $@ || 'application capability preflight failed';
    if ($capability_reason) {
        return {
            status => 'skipped',
            skip_reason => $capability_reason,
            validation_mode => 'capability-not-applicable',
            execution_contract => $contract->{kind},
            contract_reason => $contract->{reason},
            capability_requirements => $contract->{requirements},
            allowed_exit_codes => $contract->{allowed_exit_codes},
            functional_status => 'not-applicable',
            accessibility_status => 'not-applicable',
            screen_reader_status => 'not-tested',
            cleanup_status => 'not-needed',
        };
    }
    if ($capability_error) {
        return {
            status => 'failed',
            error => "$capability_error",
            validation_mode => 'capability-preflight',
            execution_contract => $contract->{kind},
            contract_reason => $contract->{reason},
            capability_requirements => $contract->{requirements},
            allowed_exit_codes => $contract->{allowed_exit_codes},
            functional_status => 'not-confirmed',
            accessibility_status => 'not-confirmed',
            screen_reader_status => 'not-tested',
            cleanup_status => 'not-needed',
        };
    }
    my $settle = get_var('BIGLINUX_APPLICATION_SETTLE_SECONDS', 2);
    my $content_timeout = $contract->{content_timeout}
      // get_var('BIGLINUX_APPLICATION_CONTENT_TIMEOUT', 10);
    my $close_timeout = $contract->{close_timeout}
      // get_var('BIGLINUX_APPLICATION_CLOSE_TIMEOUT', 15);
    my $default_close_key = $contract->{close_key} // $class->default_close_key($entry);
    my $close_key = get_var('BIGLINUX_APPLICATION_CLOSE_KEY', $default_close_key);
    die 'invalid application settle interval' unless $settle =~ /\A[0-9]+\z/ && $settle <= 10;
    die 'invalid application content timeout'
      unless $content_timeout =~ /\A[1-9][0-9]*\z/ && $content_timeout <= 120;
    die 'invalid application close timeout' unless $close_timeout =~ /\A[1-9][0-9]*\z/ && $close_timeout <= 120;
    die 'invalid application close shortcut' unless $close_key =~ /\A(?:alt-f4|ctrl-q)\z/;
    my $metric = {status => 'failed', validation_mode => 'atspi-smoke',
        functional_status => 'not-confirmed', accessibility_status => 'not-confirmed',
        screen_reader_status => 'not-tested', execution_contract => $contract->{kind},
        contract_reason => $contract->{reason},
        capability_requirements => $contract->{requirements},
        allowed_exit_codes => $contract->{allowed_exit_codes},
        action => $contract->{kind} eq 'shared-window'
          ? 'Open, accessible content, close shortcut, window disappears without crash'
          : 'Open, accessible content, close shortcut, allowed process exit'};
    my $started = time;
    my $failure;
    eval {
        die 'invalid installed desktop entry: ' . $entry->{skip_reason} if $entry->{skip_reason};
        # No recurring memory sampling: the window probe supplies one snapshot.
        my ($baseline, $opened, $method, $seconds, $path, $launch_pid) =
          atspi->launch_desktop_entry($entry, $timeout, 0);
        $metric->{launch_method} = $method;
        $metric->{launch_pid} = $launch_pid;
        $metric->{open_seconds} = 0 + sprintf('%.2f', $seconds);
        $metric->{mem_available_before_mib} = $baseline->{mem_available_mib};
        die 'application did not create an accessible window: ' . ($opened->{error} // '')
          unless ($opened->{status} // '') eq 'passed' && $opened->{accessible_window};
        my $pid = $opened->{pid};
        $metric->{window_pid} = $pid;
        $metric->{accessible_window} = JSON::PP::true;
        $metric->{accessible_application} = $opened->{application};
        $metric->{accessible_window_name} = $opened->{window};
        $metric->{accessible_children} = $opened->{accessible_children};
        $metric->{mem_available_after_open_mib} = $opened->{mem_available_mib};
        $metric->{memory_snapshot} = $opened->{memory};
        # A short settle catches applications which create a window then crash.
        # The next probe must still read content from that application.
        sleep $settle if $settle;
        my $content = atspi->result('smoke-window', $content_timeout, '--pid', $pid);
        die 'window did not expose accessible content: ' . ($content->{error} // '')
          unless ($content->{status} // '') eq 'passed'
          && ($content->{coverage} // '') eq 'accessible-content-present';
        $metric->{accessibility_status} = 'available';
        $metric->{accessible_content} = $content->{evidence};
        my $close_mode = $contract->{kind} eq 'shared-window' ? 'window-close' : 'process-exit';
        my $closed = atspi->close_with_shortcut(
            $pid, $path, $launch_pid, $close_timeout, $close_key, $close_mode
        );
        $metric->{close_action} = $closed->{close_action};
        $metric->{application_exit_code} = $closed->{raw_application_exit_code};
        $metric->{application_crashed} = $closed->{application_crashed} ? JSON::PP::true : JSON::PP::false;
        $metric->{graceful_exit} = $closed->{graceful_exit} ? JSON::PP::true : JSON::PP::false;
        $metric->{window_closed} = $closed->{window_closed} ? JSON::PP::true : JSON::PP::false;
        $metric->{process_gone} = $closed->{process_gone} ? JSON::PP::true : JSON::PP::false;
        if ($contract->{kind} eq 'shared-window') {
            die 'application window did not disappear after its close shortcut'
              unless $closed->{window_closed};
            die 'application crashed while closing its shared window'
              if $closed->{application_crashed};
            die 'application exited with a disallowed status (wait status '
              . $metric->{application_exit_code} . ')'
              if defined $metric->{application_exit_code}
              && !$class->_exit_code_allowed($contract, $metric->{application_exit_code});
            $metric->{functional_status} = 'window-closed';
        }
        else {
            die 'application did not exit after its close shortcut' unless $closed->{graceful_exit};
            die 'application exit status was not observed' unless defined $metric->{application_exit_code};
            die 'application exited with a disallowed status (wait status '
              . $metric->{application_exit_code} . ')'
              unless $class->_exit_code_allowed($contract, $metric->{application_exit_code});
            $metric->{functional_status} = $contract->{kind} eq 'transient-dialog'
              ? 'open-cancel' : 'open-close';
        }
        $metric->{status} = 'passed';
        1;
    } or $failure = $@ || 'application smoke failed';
    # Capture the actual failure before cleanup removes a welcome/save dialog.
    # Diagnostic pixels are never used as the test's oracle.
    eval { select_console 'sut'; save_screenshot; } if $failure;
    # Cleanup is isolation, never a replacement for the tested close operation.
    my $cleanup = eval { atspi->cleanup(5) };
    $metric->{cleanup_status} = ref $cleanup eq 'HASH' ? $cleanup->{status} : 'failed';
    if (($metric->{cleanup_status} // '') ne 'passed') {
        $failure ||= $@ || 'application cleanup failed';
    }
    if ($failure) {
        $metric->{status} = 'failed';
        $metric->{error} = "$failure";
    }
    $metric->{duration_seconds} = 0 + sprintf('%.2f', time - $started);
    return $metric;
}

1;
