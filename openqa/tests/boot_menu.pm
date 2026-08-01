# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub run {
    assert_screen 'biglinux-boot-menu', 120;
    send_key 'ret';
    assert_and_click 'biglinux-live-language', timeout => 300, mousehide => 1;
    assert_and_click 'biglinux-live-keyboard', timeout => 30, mousehide => 1;
    assert_and_click 'biglinux-live-desktop-layout', timeout => 30, mousehide => 1;

    sleep 2;
    record_info 'Theme selector', 'Reference image captured during test authoring';
    save_screenshot;
    send_key 'ret';
    sleep 20;
    record_info 'Live desktop', 'Reference image captured during test authoring';
    save_screenshot;

    send_key 'alt-f2';
    type_string 'dolphin';
    sleep 1;
    send_key 'ret';
    sleep 5;
    record_info 'Dolphin', 'Reference image captured during test authoring';
    save_screenshot;
    send_key 'alt-f4';

    send_key 'alt-f2';
    type_string 'konsole';
    sleep 1;
    send_key 'ret';
    sleep 5;
    record_info 'Konsole', 'Reference image captured during test authoring';
    save_screenshot;
    send_key 'alt-f4';

    send_key 'alt-f2';
    type_string 'brave about:blank';
    sleep 1;
    send_key 'ret';
    sleep 8;
    record_info 'Brave', 'Reference image captured during test authoring';
    save_screenshot;
    send_key 'alt-f4';

    send_key 'alt-f2';
    type_string 'calamares-biglinux_polkit --software-render';
    sleep 1;
    send_key 'ret';
    sleep 10;
    record_info 'Installer launcher', 'Reference image captured during test authoring';
    save_screenshot;
    send_key 'alt-f4';
    sleep 2;

    assert_screen 'biglinux-live-desktop', 30;
}

1;
