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

    # The dialog is proven by its own button. A needle would add the dialog's
    # position on screen as a variable, and it does move between runs. The
    # finish page below is what proves the press started the installation.
    atspi->activate_widget($calamares::BUTTON_ROLES, \@CONFIRM, 60, calamares->scope);

    # The finish page shows its restart button only when the installation
    # succeeded, so waiting for it proves the installation completed. A failed
    # installation shows an error instead and runs out of budget here.
    my $restart = atspi->wait_widget_until($calamares::BUTTON_ROLES, \@RESTART, 2400, calamares->scope);
    die 'The installation did not finish: ' . ($restart->{error} // 'unknown reason')
      unless $restart->{status} eq 'passed';

    calamares->upload_installation_log;

    # Eject as late as possible: the live root can still be served from the
    # medium, so every rendering step after this point is a risk. Only the
    # final key press remains, and it reboots the machine.
    eject_cd;
    calamares->click_action(\@RESTART);

    # The installer must perform its own restart. Resetting here would hide a
    # broken user action. installed_boot waits for a new authenticated console.
    reset_consoles;
}

sub post_fail_hook {
    eval { calamares->upload_installation_log };
    eval { select_console 'sut' };
}

1;
