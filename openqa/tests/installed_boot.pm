# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub test_flags {
    return {fatal => 1};
}

sub run {
    select_console 'sut';
    # The installed image boots its default entry without a visible GRUB
    # menu.  Reaching the installed SDDM is the positive proof that the
    # ejected live medium was not booted again.
    assert_screen 'biglinux-sddm-login', 300;
}

1;
