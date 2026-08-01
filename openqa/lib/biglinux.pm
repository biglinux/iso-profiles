# SPDX-License-Identifier: GPL-2.0-or-later

package biglinux;

use Mojo::Base 'distribution', -signatures;
# Import no symbols: importing testapi::script_run into this class would
# shadow distribution::script_run and recurse when the console probes run.
use testapi ();

sub init ($self) {
    $self->SUPER::init;
    # The ISO starts agetty on hvc0.  A named virtio console lets tests run
    # deterministic shell probes without typing shell syntax through VNC.
    $self->add_console('root-virtio-terminal', 'virtio-terminal');
}

sub activate_console ($self, $console) {
    return unless $console eq 'root-virtio-terminal';

    testapi::wait_serial 'login:', timeout => 60;
    # The live image exposes the unprivileged live-session account on hvc0.
    # Keep the console user aligned with the profile instead of assuming a
    # root login that is deliberately disabled by the live setup.
    testapi::type_string 'biglinux';
    testapi::send_key 'ret';
    testapi::wait_serial 'Password:', timeout => 30;
    testapi::type_string 'biglinux';
    testapi::send_key 'ret';
    # The Plasma shell prompt contains ANSI colour sequences between the
    # closing bracket, '$' and the following space.  Wait for the stable
    # account marker instead of matching that decorated prompt.
    testapi::wait_serial qr/\@/, timeout => 15;
    testapi::type_string "export PS1='# '\n";
    testapi::wait_serial '# ', no_regex => 1, timeout => 10;
}

1;
