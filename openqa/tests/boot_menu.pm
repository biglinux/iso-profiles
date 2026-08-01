# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub run {
    assert_screen 'biglinux-boot-menu', 120;
    send_key 'ret';
    assert_and_click 'biglinux-live-language', timeout => 300, mousehide => 1;
    assert_and_click 'biglinux-live-keyboard', timeout => 30, mousehide => 1;
    # Match the stable title only; the cards are intentionally theme/layout
    # artwork and are not a reliable oracle.  The first card keeps a stable
    # position in this setup, so click its center after the semantic match.
    assert_screen 'biglinux-live-desktop-layout', 30;
    mouse_set 209, 349;
    mouse_click;
    assert_screen 'biglinux-live-theme', 30;
    send_key 'ret';
    # Dismiss a possible file/location dialog opened by the selected theme;
    # on images without one Esc is harmless and keeps the path deterministic.
    send_key 'esc';
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
    send_key 'alt-f4';
    sleep 5;
    assert_screen 'biglinux-live-desktop', 60;
}

1;
