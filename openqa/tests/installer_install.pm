# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use calamares;

sub test_flags {
    return {fatal => 1};
}

our @RESTART = ('Restart system', 'Reiniciar o sistema');
# Only the confirmation dialog offers this, so it cannot be confused with the
# summary page's own Install button behind the modal.
our @CONFIRM = ('Install Now', 'Instalar agora');

sub run {
    calamares->click_action(\@calamares::INSTALL);

    # Only a profile with prompt-install: true asks again before it writes the
    # disk; BigLinux and BigCommunity start installing at once. The finish
    # page below is what proves the installation started.
    calamares->click_action(\@CONFIRM)
      if atspi->run_command(q{grep -Eq '^prompt-install:[[:space:]]*true' /etc/calamares/settings.conf}) == 0;

    # The finish page shows its restart button only when the installation
    # succeeded, so waiting for it proves the installation completed. A failed
    # installation shows an error instead and runs out of budget here.
    my $restart = atspi->wait_widget_until($calamares::BUTTON_ROLES, \@RESTART, 2400, calamares->scope);
    die 'The installation did not finish: ' . ($restart->{error} // 'unknown reason')
      unless $restart->{status} eq 'passed';

    calamares->upload_session_log;

    # Focus the restart button before ejecting: the live root is served from
    # the medium, and once it is gone any program that pages in code from it
    # can die, the accessibility bus included. Only the key press is left.
    atspi->focus_widget($calamares::BUTTON_ROLES, \@RESTART, 60, calamares->scope);
    eject_cd;
    select_console 'sut';
    send_key 'spc';

    # The installer must perform its own restart. Resetting here would hide a
    # broken user action. installed_boot waits for a new authenticated console.
    reset_consoles;
}

sub post_fail_hook {
    eval { calamares->upload_session_log };
    eval { select_console 'sut' };
}

1;
