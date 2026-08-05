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
    atspi->activate_widget($calamares::BUTTON_ROLES, \@CONFIRM, 60);

    # A progress bar proves the installation really started rather than
    # returning to the summary or opening an error dialog.
    my $progress = atspi->wait_widget('progress bar', [], 120);
    die 'The installation did not start: ' . ($progress->{error} // 'unknown reason')
      unless $progress->{status} eq 'passed';

    # The finish page is the only one offering to restart, so waiting for that
    # control proves the installation completed and hands us the control to
    # act on. An error page never exposes it, which is exactly why a failed
    # installation must run out of budget here instead of matching something.
    my $restart = atspi->wait_widget_until('check box|checkbox', \@RESTART, 2400);
    die 'The installation did not finish: ' . ($restart->{error} // 'unknown reason')
      unless $restart->{status} eq 'passed';

    calamares->upload_installation_log;
    atspi->activate_widget('check box|checkbox', \@RESTART, 60);
    my $selected = atspi->wait_widget('check box|checkbox', \@RESTART, 30);
    die 'The installer did not accept restarting after the installation'
      unless $selected->{status} eq 'passed' && $selected->{widget}{checked};

    # Eject as late as possible: the live root can still be served from the
    # medium, so every rendering step after this point is a risk. Only the
    # final click remains, and it reboots the machine.
    eject_cd;
    calamares->click_action(\@calamares::DONE);

    # No reboot fallback here on purpose. Calamares reboots through a
    # privileged helper and takes its time: a previous run saw the machine
    # still answering 30 seconds after Done and the broadcast arrive later.
    # Rebooting from this console cannot work anyway, because the live user is
    # unprivileged, and the next module already proves the outcome -- it waits
    # for the installed system's own login prompt and fails clearly if the
    # machine never came back.
    reset_consoles;
}

sub post_fail_hook {
    eval { calamares->upload_installation_log };
    eval { select_console 'sut' };
}

1;
