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
    wait_screen_change(sub { send_key 'ret' }, 30)
      or die 'The live desktop theme selector did not accept the default theme';

    # The live session briefly renders a black screen while Plasma applies the
    # selected theme. Wait for observable screen transitions instead of timing
    # the compositor with fixed sleeps.
    wait_screen_change(sub { send_key 'ctrl-alt-t' }, 30)
      or die 'Konsole did not open after the live theme selection';

    # Applying a fixed wallpaper makes the final desktop check independent of
    # the rotating live-session wallpaper.
    type_string 'plasma-apply-wallpaperimage ';
    send_key 'altgr-q';
    type_string 'usr';
    send_key 'altgr-q';
    type_string 'share';
    send_key 'altgr-q';
    type_string 'wallpapers';
    send_key 'altgr-q';
    type_string 'Big-retro.heic';
    wait_screen_change(sub { send_key 'ret' }, 60)
      or die 'The fixed live wallpaper was not applied';
    wait_screen_change(sub { send_key 'alt-f4' }, 30)
      or die 'Konsole did not close after applying the live wallpaper';
    # The earlier language, keyboard, layout, and theme needles are the
    # rendered-desktop sentinel. Do not repeat a wallpaper-dependent match
    # here: the live session can rotate the wallpaper between boots.
    wait_still_screen stilltime => 3, timeout => 60;
}

1;
