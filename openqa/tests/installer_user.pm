# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use calamares;

sub test_flags {
    return {fatal => 1};
}

sub run {
    assert_and_click 'calamares-erase-disk-option', point_id => 'erase-disk',
      timeout => 60, mousehide => 1;
    assert_screen 'calamares-erase-disk-selected', 30;
    assert_and_click 'calamares-erase-disk-selected', point_id => 'next',
      timeout => 60, mousehide => 1;
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
    assert_screen 'calamares-users-valid', 30;

    assert_and_click 'calamares-users-page', point_id => 'next', timeout => 60,
      mousehide => 1;
    assert_screen 'calamares-summary-page', 90;
    assert_screen 'calamares-summary-expected', 30;
}

1;
