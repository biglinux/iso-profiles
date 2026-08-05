# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use calamares;

sub test_flags {
    return {fatal => 1};
}

sub run {
    assert_screen 'calamares-partitions-page', 60;
    atspi->click_widget('radio button', ['Erase disk', 'Apagar disco'], 60);
    assert_screen 'calamares-erase-disk-selected', 30;
    calamares->click_action(\@calamares::NEXT);
    assert_screen 'calamares-users-page', 90;

    # Calamares focuses the first field when the users page opens.  Keeping the
    # path keyboard-only avoids brittle per-field coordinates and exercises the
    # same focus order used by the graphical test backend.
    type_string 'BigLinux openQA';
    send_key 'tab';
    type_string calamares->test_user;
    send_key 'tab';
    type_string calamares->test_hostname;
    send_key 'tab';
    type_password calamares->test_password;
    send_key 'tab';
    type_password calamares->test_password;
    # The green validation marks are the meaningful proof that Calamares
    # accepted the account, so this needle stays. The button that follows is
    # located through AT-SPI because it only becomes enabled at this point.
    assert_screen 'calamares-users-valid', 30;

    calamares->click_action(\@calamares::NEXT);
    assert_screen 'calamares-summary-page', 90;
}

1;
