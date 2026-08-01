# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub run {
    assert_screen 'biglinux-boot-menu', 120;
    send_key 'ret';
    assert_and_click 'biglinux-live-language', timeout => 300, mousehide => 1;
    assert_and_click 'biglinux-live-keyboard', timeout => 30, mousehide => 1;
    assert_and_click 'biglinux-live-desktop-layout', timeout => 30, mousehide => 1;
    assert_screen 'biglinux-live-theme', 30;
    send_key 'ret';
    # Make the desktop reference independent of the rotating live-session wallpaper.
    sleep 5;
    send_key 'ctrl-alt-t';
    sleep 8;
    # type_string follows the guest keyboard layout; use the ABNT2 AltGr path
    # separator because a literal slash is mapped to the wrong physical key.
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
    save_screenshot;
    send_key 'alt-f4';
    sleep 5;
    assert_screen 'biglinux-live-desktop', 60;
}

1;
