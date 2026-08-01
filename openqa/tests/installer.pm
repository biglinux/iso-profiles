# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub run {
    send_key 'alt-f2';
    type_string 'calamares-biglinux_polkit --software-render';
    sleep 1;
    send_key 'ret';
    assert_and_click 'biglinux-installer-launcher', timeout => 60, mousehide => 1;

    sleep 5;
    assert_and_click 'biglinux-installer-tips', timeout => 30, mousehide => 1;

    sleep 30;
    assert_and_click 'biglinux-installer-welcome', timeout => 60, mousehide => 1;

    sleep 5;
    assert_and_click 'biglinux-installer-location', timeout => 30, mousehide => 1;

    sleep 5;
    assert_screen 'biglinux-installer-keyboard', 30, mousehide => 1;
    mouse_set 855, 706;
    mouse_click 'left';

    sleep 5;
    assert_screen 'biglinux-installer-partitions', 30, mousehide => 1;
}

1;
