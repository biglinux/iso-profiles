# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub run {
    assert_screen 'biglinux-boot-menu', 120;
    send_key 'ret';
    assert_and_click 'biglinux-live-language', timeout => 300, mousehide => 1;
    assert_screen 'biglinux-live-desktop', 120;
}

1;
