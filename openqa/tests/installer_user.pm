# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use calamares;

sub test_flags {
    return {fatal => 1};
}

sub run {
    calamares->assert_page('partitions-page', 60);
    atspi->activate_widget('radio button', ['Erase disk', 'Apagar disco'], 60);
    # The radio reports its own state, which is what "selected" means here.
    my $erase = atspi->wait_widget('radio button', ['Erase disk', 'Apagar disco'], 30);
    die 'the installer did not select the erase-disk option'
      unless ref $erase eq 'HASH' && $erase->{status} eq 'passed';
    calamares->click_action(\@calamares::NEXT);
    calamares->assert_page('users-page', 90);

    # Calamares focuses the first field when the users page opens.  Keeping the
    # path keyboard-only avoids brittle per-field coordinates and exercises the
    # same focus order used by the graphical test backend.
    type_string 'BigLinux openQA';
    send_key 'tab';
    type_string(calamares->test_user);
    send_key 'tab';
    type_string(calamares->test_hostname);
    send_key 'tab';
    type_password(calamares->test_password);
    send_key 'tab';
    type_password(calamares->test_password);
    # Calamares only enables "Next" once every field validates, so the button
    # becoming sensitive is the accessible equivalent of the green marks - and
    # unlike them it cannot be faked by a theme that draws a green icon.
    my $ready = atspi->wait_widget($calamares::BUTTON_ROLES, \@calamares::NEXT, 30);
    die 'Calamares did not accept the account details'
      unless ref $ready eq 'HASH' && $ready->{status} eq 'passed';

    calamares->click_action(\@calamares::NEXT);
    calamares->assert_page('summary-page', 90);
}

1;
