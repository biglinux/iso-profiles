# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use JSON::PP qw(decode_json);
use testapi;
use atspi;

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
    my $raw = get_var('BIGLINUX_APPLICATION_POLICY_JSON', '');
    die 'BIGLINUX_APPLICATION_POLICY_JSON is required for installed critical applications'
      unless defined $raw && $raw ne '';
    my $policy = eval { decode_json($raw) };
    die "BIGLINUX_APPLICATION_POLICY_JSON is invalid: $@"
      unless ref $policy eq 'HASH' && ref $policy->{critical} eq 'ARRAY';
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
        die "did not expose an AT-SPI window" unless $opened->{status} eq 'passed';

        my $interaction = atspi->interact($opened->{pid}, 10);
        die "AT-SPI interaction failed: $interaction->{error}"
          unless $interaction->{status} eq 'passed'
          && $interaction->{action_result}
          && $interaction->{semantic_change};

        my $termination = atspi->terminate_window(
            $opened->{pid}, $status_path, $launch_pid, $entry
        );
        die 'AT-SPI close action was not accepted' unless $termination->{close_action_ok};
        die 'application did not exit after AT-SPI close action'
          unless $termination->{process_gone};
        die "application exited with code $termination->{application_exit_code}"
          unless $termination->{application_exit_ok};
        die 'application window remained accessible'
          unless $termination->{closed}{status} eq 'passed';

        record_info "Critical application: $desktop_id", sprintf(
            'functional_test=%s; AT-SPI interaction=%s; opened in %.2f s via %s; exit=0',
            $functional_test,
            $interaction->{action},
            $open_seconds,
            $launch_method,
        );
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
