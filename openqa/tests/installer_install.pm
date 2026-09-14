# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use calamares;

sub test_flags {
    return {fatal => 1};
}

our @RESTART = ('Restart now', 'Reiniciar agora');
# Only the confirmation dialog offers this, so it cannot be confused with the
# summary page's own Install button behind the modal.
our @CONFIRM = ('Install Now', 'Instalar agora');

sub run {
    calamares->click_action(\@calamares::INSTALL);

    # The dialog is proven by its own button. A needle would add the dialog's
    # position on screen as a variable, and it does move between runs.
    #
    # Let the dialog settle before confirming and require it to disappear: one
    # run pressed Install Now while the dialog was still fading in, the action
    # reported success, and the installer sat on the summary page until the
    # whole budget ran out.
    atspi->activate_widget_until_gone($calamares::BUTTON_ROLES, \@CONFIRM, 60);

    # The finish page is the only one offering to restart, so waiting for that
    # control proves the installation completed and hands us the control to
    # act on. An error page never exposes it, which is exactly why a failed
    # installation must run out of budget here instead of matching something.
    my $restart = atspi->wait_widget_until('check box|checkbox', \@RESTART, 2400);
    die 'The installation did not finish: ' . ($restart->{error} // 'unknown reason')
      unless $restart->{status} eq 'passed';

    calamares->upload_installation_log;
    atspi->activate_widget('check box|checkbox', \@RESTART, 60)
      unless $restart->{widget}{checked};
    my $selected = atspi->wait_widget('check box|checkbox', \@RESTART, 30);
    die 'The installer did not accept restarting after the installation'
      unless $selected->{status} eq 'passed' && $selected->{widget}{checked};

    # Eject as late as possible: the live root can still be served from the
    # medium, so every rendering step after this point is a risk. Only the
    # final click remains, and it reboots the machine.
    eject_cd;
    calamares->click_action(\@calamares::DONE);

    # The installer must perform its own restart. Resetting here would hide a
    # broken user action. installed_boot waits for a new authenticated console.
    reset_consoles;
}

sub post_fail_hook {
    eval { calamares->upload_installation_log };
    eval { select_console 'sut' };
}

1;
