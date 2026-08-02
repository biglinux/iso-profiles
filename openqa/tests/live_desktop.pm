# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub test_flags {
    return {fatal => 1};
}

sub run {
    assert_and_click 'biglinux-live-language', timeout => 300, mousehide => 1;
    assert_and_click 'biglinux-live-keyboard', timeout => 30, mousehide => 1;

    assert_screen 'biglinux-live-desktop-layout', 60;
    assert_and_click 'biglinux-live-desktop-layout', point_id => 'classic',
      timeout => 30, mousehide => 1;
    assert_screen 'biglinux-live-theme', 60;
    wait_screen_change(sub { send_key 'spc' }, 30)
      or die 'The live desktop theme selector did not accept the default theme';

    assert_screen 'biglinux-live-desktop', 120;
    wait_still_screen stilltime => 3, timeout => 60;

    # A terminal is a basic live-session capability and gives the release gate
    # an observable confirmation beyond the desktop wallpaper/taskbar.
    wait_screen_change(sub { send_key 'ctrl-alt-t' }, 30)
      or die 'The live session did not open a terminal';
    assert_screen 'biglinux-konsole', 60;
    wait_screen_change(sub { send_key 'alt-f4' }, 30)
      or die 'The live terminal did not close cleanly';
    assert_screen 'biglinux-live-desktop', 30;
}

1;
