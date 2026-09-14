# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use JSON::PP qw(decode_json);
use testapi;
use atspi;
use application_policy;

sub test_flags {
    return {fatal => 1};
}

sub _desktop_id {
    my ($entry) = @_;
    return $entry->{relative_path} if defined $entry->{relative_path};
    my $path = $entry->{path} // '';
    $path =~ s{\A/usr/share/applications/}{};
    return $path;
}

sub _critical_policy {
    my $policy = application_policy->load;
    die 'the application policy has no critical section'
      unless ref $policy->{critical} eq 'ARRAY';
    return $policy->{critical};
}

sub _test_application {
    my ($entry, $functional_test) = @_;
    my $desktop_id = _desktop_id($entry);
    my ($status_path, $opened, $launch_method, $open_seconds, $launch_pid);
    my $failure;
    eval {
        my ($baseline, $window, $method, $seconds, $path, $child_pid) = atspi->launch_desktop_entry(
            $entry, 120
        );
        $opened = $window;
        $status_path = $path;
        $launch_method = $method;
        $open_seconds = $seconds;
        $launch_pid = $child_pid;
        my $validation_mode = 'atspi-open';
        die 'critical application has no PID-scoped accessible window: '
          . ($opened->{error} // 'incomplete observation')
          unless ($opened->{status} // '') eq 'passed';
        my $semantics = atspi->result('audit-window', 15, '--pid', $opened->{pid});
        die 'critical application has no usable accessible controls: ' . ($semantics->{error} // '')
          unless ($semantics->{status} // '') eq 'passed' && $semantics->{complete};

        my $termination = atspi->terminate_window(
            $opened->{pid}, $status_path, $launch_pid, $entry
        );
        die 'application did not exit after the close request'
          unless $termination->{graceful_exit};
        die "application crashed on exit (wait status $termination->{raw_application_exit_code})"
          if $termination->{application_crashed};

        atspi->record_guest_info("Critical application: $desktop_id", sprintf(
            'functional_test=%s; %s window "%s" opened in %.2f s via %s; exit status %s',
            $functional_test,
            $validation_mode,
            $opened->{window} // 'untitled',
            $open_seconds,
            $launch_method,
            $termination->{raw_application_exit_code} // 'unknown',
        ));
    };
    $failure = $@ if $@;

    my $cleanup;
    my $cleanup_error;
    eval { $cleanup = atspi->cleanup(20); 1 } or $cleanup_error = $@ || 'AT-SPI cleanup failed';
    if (!$cleanup_error && (!ref $cleanup || $cleanup->{status} ne 'passed')) {
        $cleanup_error = ref $cleanup && $cleanup->{error}
          ? $cleanup->{error} : 'AT-SPI cleanup failed';
    }
    $failure ||= $cleanup_error if $cleanup_error;
    if ($failure) {
        $failure =~ s/\s+\z//;
        die "Critical application $desktop_id failed: $failure";
    }
}

sub run {
    my %entries_by_id = map { _desktop_id($_) => $_ } @{atspi->inventory};
    my @failures;
    for my $item (@{_critical_policy()}) {
        die 'critical application policy entry is invalid'
          unless ref $item eq 'HASH'
          && defined $item->{desktop_id}
          && defined $item->{functional_test};
        my $desktop_id = $item->{desktop_id};
        my $entry = $entries_by_id{$desktop_id};
        if (!$entry) {
            push @failures, "$desktop_id is absent from the installed system";
            next;
        }
        eval { _test_application($entry, $item->{functional_test}); 1 }
          or push @failures, ($@ || "$desktop_id failed");
    }
    die 'Installed critical application failures: ' . join('; ', @failures)
      if @failures;
}

1;
