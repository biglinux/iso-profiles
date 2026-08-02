# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use calamares;

sub test_flags {
    return {fatal => 1};
}

sub run {
    assert_and_click 'calamares-summary-page', point_id => 'install',
      timeout => 60, mousehide => 1;
    assert_screen 'calamares-install-confirmation', 30;
    assert_and_click 'calamares-install-confirmation', point_id => 'confirm',
      timeout => 30, mousehide => 1;
    assert_screen 'calamares-install-progress', 120;

    # An error page is intentionally not treated as an alternative success
    # needle: it must time out as a fatal release-gate failure.
    assert_screen 'calamares-install-finished', 2400;

    calamares->upload_installation_log;
    assert_screen 'calamares-install-finished', 60;
    eject_cd;
    assert_and_click 'calamares-install-finished', point_id => 'restart',
      timeout => 60, mousehide => 1;
    assert_screen 'calamares-install-restart-selected', 30;
    assert_and_click 'calamares-install-restart-selected', point_id => 'finish',
      timeout => 60, mousehide => 1;
    reset_consoles;
}

sub post_fail_hook {
    eval {
        select_console 'root-virtio-terminal';
        upload_logs '/home/biglinux/installation.log', failok => 1,
          log_name => 'calamares-live-installation.log';
        upload_logs '/var/log/installation.log', failok => 1,
          log_name => 'calamares-installation.log';
    };
    eval { select_console 'sut' };
}

1;
