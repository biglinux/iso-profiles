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
    assert_screen 'biglinux-live-desktop', 60;
}

1;
