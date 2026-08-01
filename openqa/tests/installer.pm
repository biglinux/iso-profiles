# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub click_at {
    my ($x, $y) = @_;

    mouse_set $x, $y;
    mouse_click 'left';
}

sub capture_reference {
    my ($title) = @_;

    record_info $title, 'Reference image captured during test authoring';
    save_screenshot;
}

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
    capture_reference 'Calamares location';
    click_at 855, 706;

    sleep 5;
    capture_reference 'Calamares keyboard';
    click_at 855, 706;

    sleep 5;
    capture_reference 'Calamares partitions';
    assert_screen 'biglinux-installer-partitions', 30;
}

1;
