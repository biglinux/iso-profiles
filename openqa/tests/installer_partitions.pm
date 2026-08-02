# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use calamares;

sub test_flags {
    return {fatal => 1};
}

sub run {
    calamares->advance('biglinux-installer-welcome', 'biglinux-installer-location');
    calamares->advance('biglinux-installer-location', 'biglinux-installer-keyboard');
    calamares->advance('biglinux-installer-keyboard', 'calamares-partitions-page');
    assert_screen 'calamares-partitions-page', 60;
}

1;
