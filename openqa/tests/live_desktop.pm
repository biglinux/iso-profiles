# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub test_flags {
    return {fatal => 1};
}

sub run {
    # This is the first module: the budget covers the GRUB countdown, the
    # live boot, and the first-boot wizard appearing.
    assert_and_click 'biglinux-live-language', timeout => 360, mousehide => 1;
    assert_and_click 'biglinux-live-keyboard', timeout => 30, mousehide => 1;

    assert_screen 'biglinux-live-desktop-layout', 60;
    assert_and_click 'biglinux-live-desktop-layout', point_id => 'classic',
      timeout => 30, mousehide => 1;
    assert_screen 'biglinux-live-theme', 60;
    wait_screen_change(sub { send_key 'ret' }, 30)
      or die 'The live desktop theme selector did not accept the default theme';

    # The wizard pages above are the rendered-desktop evidence. Nothing applies
    # a wallpaper here any more: that opened a terminal and typed a path through
    # the keyboard layout only to stabilise a wallpaper-dependent needle which
    # no longer exists, and it failed on a perfectly good ISO. Let the session
    # settle instead; everything after this point works through accessibility
    # and the serial console.
    wait_still_screen stilltime => 5, timeout => 120;
}

1;
