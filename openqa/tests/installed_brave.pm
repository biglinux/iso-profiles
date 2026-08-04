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
    my ($baseline, $opened, $launch_method, $open_seconds, $status_path) = atspi->launch_command(
        'env QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 brave --no-first-run --no-default-browser-check about:blank',
        'Brave',
        120
    );
    unless ($opened->{status} eq 'passed') {
        atspi->abort_launch($status_path);
        die 'Installed Brave did not expose an accessible window';
    }

    my $interaction = atspi->interact($opened->{pid});
    unless ($interaction->{status} eq 'passed'
        && $interaction->{action_result}
        && $interaction->{semantic_change}) {
        atspi->abort_launch($status_path);
        die "Installed Brave did not accept an AT-SPI interaction: $interaction->{error}";
    }
    my $termination = atspi->terminate_window($opened->{pid}, $status_path);
    die 'Installed Brave did not accept its AT-SPI close action'
      unless $termination->{close_action_ok};
    die "Installed Brave process $opened->{pid} did not exit after its AT-SPI close action"
      unless $termination->{process_gone};
    die "Installed Brave exited with unexpected code $termination->{application_exit_code}"
      unless $termination->{application_exit_ok};
    die 'Installed Brave left an accessible window open'
      unless $termination->{closed}{status} eq 'passed';

    record_info 'Installed Brave', sprintf(
        'CLI exit 0; AT-SPI action "%s"; window "%s" opened in %.2f s via %s and closed with exit 0; kernel %s',
        $interaction->{action},
        $opened->{window}, $open_seconds, $launch_method, $kernel
    );
}

1;
