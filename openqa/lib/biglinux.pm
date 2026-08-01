# SPDX-License-Identifier: GPL-2.0-or-later

package biglinux;

use Mojo::Base 'distribution', -signatures;
use testapi;

sub init ($self) {
    $self->SUPER::init;
    # The ISO starts agetty on hvc0.  A named virtio console lets tests run
    # deterministic shell probes without typing shell syntax through VNC.
    $self->add_console('root-virtio-terminal', 'virtio-terminal');
}

sub activate_console ($self, $console) {
    return unless $console eq 'root-virtio-terminal';

    testapi::wait_serial 'login:', timeout => 60;
    testapi::type_string 'root';
    testapi::send_key 'ret';
    testapi::wait_serial qr/[#\$] /, timeout => 30;
    testapi::type_string "export PS1='# '\n";
    testapi::wait_serial '# ', no_regex => 1, timeout => 10;
}

1;
