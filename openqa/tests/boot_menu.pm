# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub test_flags {
    return {fatal => 1};
}

sub run {
    assert_screen 'biglinux-boot-menu', 120;
    assert_screen_change(sub { send_key 'ret' }, 30)
      or die 'The BigLinux live boot menu did not start the live session';
}

1;
