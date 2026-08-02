# SPDX-License-Identifier: GPL-2.0-or-later

package biglinux;

use Mojo::Base 'distribution', -signatures;
# Import no symbols: importing testapi::script_run into this class would
# shadow distribution::script_run and recurse when the console probes run.
use testapi ();

sub init ($self) {
    $self->SUPER::init;
    # The ISO starts agetty on hvc0. A named virtio console lets tests run
    # deterministic shell probes without typing shell syntax through VNC.
    $self->add_console('root-virtio-terminal', 'virtio-terminal');
}

sub activate_console ($self, $console) {
    return unless $console eq 'root-virtio-terminal';

    testapi::wait_serial 'login:', timeout => 60;
    # The live image exposes the unprivileged live-session account on hvc0.
    testapi::type_string 'biglinux';
    testapi::send_key 'ret';
    testapi::wait_serial 'Password:', timeout => 30;
    testapi::type_string 'biglinux';
    testapi::send_key 'ret';

    # Wait for the shell integration marker instead of matching the decorated
    # ble.sh prompt. Then replace the interactive shell with a plain Bash so
    # command echo and upload_logs remain deterministic on the serial console.
    testapi::wait_serial qr/type=shell/, timeout => 60;
    testapi::type_string "exec env TERM=dumb bash --noprofile --norc\n";
    testapi::wait_serial qr/bash-[0-9.]+\$ /, timeout => 30;
    testapi::type_string "export PS1='# '; printf '__OA_SERIAL_READY__\\n'\n";
    testapi::wait_serial '__OA_SERIAL_READY__', timeout => 15;
    testapi::wait_serial '# ', no_regex => 1, timeout => 10;
}

1;
