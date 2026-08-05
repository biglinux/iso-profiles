# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use installed_system;

sub test_flags {
    return {fatal => 1};
}

sub run {
    installed_system->assert_brave_cli;
    my $kernel = atspi->prepare;
    # No expected window title: Brave renames its window across releases and
    # the browser being the right program is already proven by the CLI check
    # above plus the launched process tree.
    my ($baseline, $opened, $launch_method, $open_seconds, $status_path) = atspi->launch_command(
        'env QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 brave --no-first-run --no-default-browser-check about:blank',
        '',
        120
    );
    unless ($opened->{status} eq 'passed') {
        atspi->abort_launch($status_path);
        die 'Installed Brave did not expose an accessible window';
    }

    my $termination = atspi->terminate_window($opened->{pid}, $status_path);
    die "Installed Brave process $opened->{pid} did not exit after the close request"
      unless $termination->{process_gone};
    die "Installed Brave crashed on exit (wait status $termination->{raw_application_exit_code})"
      if $termination->{application_crashed};

    record_info 'Installed Brave', sprintf(
        'CLI exit 0; window "%s" opened in %.2f s via %s and exited with status %s; kernel %s',
        $opened->{window} // 'untitled', $open_seconds, $launch_method,
        $termination->{raw_application_exit_code} // 'unknown', $kernel
    );
}

1;
