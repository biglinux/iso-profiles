# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub run {
    assert_screen 'biglinux-boot-menu', 120;
}

1;
