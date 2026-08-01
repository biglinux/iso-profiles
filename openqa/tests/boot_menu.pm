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
    send_key 'alt-f2';
    sleep 1;
    # type_string follows the guest keyboard layout; send the path separators
    # explicitly because '/' is otherwise produced as ';' in the live session.
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
    sleep 2;
    send_key 'esc';
    sleep 6;
    # Keep one terminal capture while authoring the keyboard path so a failed
    # command is visible instead of being mistaken for a wallpaper assertion.
    send_key 'ctrl-alt-t';
    sleep 3;
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
    sleep 4;
    save_screenshot;
    send_key 'alt-f4';
    sleep 3;
    assert_screen 'biglinux-live-desktop', 60;
}

1;
