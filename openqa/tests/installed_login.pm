# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use installed_system;

sub test_flags {
    return {fatal => 1};
}

sub run {
    assert_screen 'biglinux-sddm-login', 60;

    # A fresh BigLinux SDDM session selects the created user and focuses its
    # password field.  The login needle proves which user was selected before
    # the secret is entered.
    type_password(installed_system->test_password);
    send_key 'ret';
    installed_system->assert_desktop;
}

1;
