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
    # selected theme.  The previously proven flow lets the session settle by
    # opening Konsole before asserting the wallpaper-dependent desktop state.
    sleep 5;
    send_key 'ctrl-alt-t';
    sleep 8;

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
    send_key 'ret';
    sleep 8;
    send_key 'alt-f4';
    sleep 5;
    assert_screen 'biglinux-live-desktop', 120;
    wait_still_screen stilltime => 3, timeout => 60;
}

1;
