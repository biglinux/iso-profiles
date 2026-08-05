# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use calamares;

sub test_flags {
    return {fatal => 1};
}

sub run {
    calamares->click_action(\@calamares::INSTALL);
    assert_screen 'calamares-install-confirmation', 30;
    calamares->click_action(\@calamares::INSTALL, 30);
    assert_screen 'calamares-install-progress', 120;

    # An error page is intentionally not treated as an alternative success
    # needle: it must time out as a fatal release-gate failure.
    assert_screen 'calamares-install-finished', 2400;

    calamares->upload_installation_log;
    atspi->activate_widget('check box|checkbox', ['Restart now', 'Reiniciar agora'], 60);
    assert_screen 'calamares-install-restart-selected', 30;
    # Eject as late as possible: the live root can still be served from the
    # medium, so every rendering step after this point is a risk. Only the
    # final click remains, and it reboots the machine.
    eject_cd;
    calamares->click_action(\@calamares::DONE);
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
