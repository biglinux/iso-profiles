# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub open_application {
    my ($command, $needle, $timeout) = @_;

    send_key 'alt-f2';
    sleep 1;
    type_string $command;
    sleep 1;
    send_key 'ret';
    assert_screen $needle, $timeout;
    send_key 'alt-f4';
    sleep 2;
}

sub run {
    open_application 'dolphin', 'biglinux-dolphin', 30;
    open_application 'konsole', 'biglinux-konsole', 30;
    open_application 'brave about:blank', 'biglinux-brave', 45;
}

1;
