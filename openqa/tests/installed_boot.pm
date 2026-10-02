# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use installed_system;

sub test_flags {
    return {fatal => 1};
}

sub run {
    select_console 'sut';
    # The installed image boots its default entry without a visible GRUB menu.
    # Reaching a login prompt on the installed system's own console, with the
    # account the installer created, is the positive proof that the ejected
    # live medium was not booted again, and it does not make the gate depend on
    # the greeter's theme, wallpaper or language.
    installed_system->assert_display_manager;
}

1;
