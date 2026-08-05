# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use installed_system;

sub test_flags {
    return {fatal => 1};
}

sub run {
    # A fresh BigLinux SDDM session selects the created user and focuses its
    # password field. Matching the greeter is only a timing hint, never the
    # verdict: its theme and language are free to change. What proves the
    # graphical login worked is the desktop coming up afterwards.
    check_screen 'biglinux-sddm-login', 60;
    wait_still_screen stilltime => 3, timeout => 60;

    type_password(installed_system->test_password);
    send_key 'ret';
    installed_system->assert_desktop;
}

1;
