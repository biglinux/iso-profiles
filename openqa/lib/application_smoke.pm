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

sub check {
    my ($class, $entry, $timeout) = @_;
    if (my $reason = $class->not_applicable_reason($entry)) {
        return {status => 'skipped', skip_reason => $reason,
            functional_status => 'not-applicable', accessibility_status => 'not-applicable',
            screen_reader_status => 'not-tested'};
    }
    my $settle = get_var('BIGLINUX_APPLICATION_SETTLE_SECONDS', 2);
    my $close_timeout = get_var('BIGLINUX_APPLICATION_CLOSE_TIMEOUT', 15);
    my $close_key = get_var('BIGLINUX_APPLICATION_CLOSE_KEY', $class->default_close_key($entry));
    die 'invalid application settle interval' unless $settle =~ /\A[0-9]+\z/ && $settle <= 10;
    die 'invalid application close timeout' unless $close_timeout =~ /\A[1-9][0-9]*\z/ && $close_timeout <= 120;
    die 'invalid application close shortcut' unless $close_key =~ /\A(?:alt-f4|ctrl-q)\z/;
    my $metric = {status => 'failed', validation_mode => 'atspi-smoke',
        functional_status => 'not-confirmed', accessibility_status => 'not-confirmed',
        screen_reader_status => 'not-tested', action => 'Open, accessible content, close shortcut, exit'};
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
        my $content = atspi->result('smoke-window', 10, '--pid', $pid);
        die 'window did not expose accessible content: ' . ($content->{error} // '')
          unless ($content->{status} // '') eq 'passed'
          && ($content->{coverage} // '') eq 'accessible-content-present';
        $metric->{accessibility_status} = 'available';
        $metric->{accessible_content} = $content->{evidence};
        my $closed = atspi->close_with_shortcut($pid, $path, $launch_pid, $close_timeout, $close_key);
        $metric->{close_action} = $closed->{close_action};
        $metric->{application_exit_code} = $closed->{raw_application_exit_code};
        $metric->{application_crashed} = $closed->{application_crashed} ? JSON::PP::true : JSON::PP::false;
        $metric->{graceful_exit} = $closed->{graceful_exit} ? JSON::PP::true : JSON::PP::false;
        die 'application did not exit after its close shortcut' unless $closed->{graceful_exit};
        die 'application exit status was not observed' unless defined $metric->{application_exit_code};
        die 'application exited with an error (wait status ' . $metric->{application_exit_code} . ')'
          unless $metric->{application_exit_code} == 0;
        $metric->{functional_status} = 'open-close';
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
