# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use installed_system;

sub test_flags {
    return {fatal => 1};
}

sub run {
    # The greeter is ready when its process is up, which the serial console can
    # answer without knowing what the theme looks like. The screenshot is kept
    # only as evidence in the job, never as the condition: SDDM's theme and
    # language are free to change between builds.
    installed_system->assert_greeter;
    check_screen 'biglinux-sddm-login', 5;
    # A greeter that just appeared may still be animating its password field in.
    wait_still_screen stilltime => 3, timeout => 60;

    type_password(installed_system->test_password);
    send_key 'ret';
    installed_system->assert_desktop;
}

1;
