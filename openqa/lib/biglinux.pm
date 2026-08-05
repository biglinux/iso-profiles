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

sub activate_console ($self, $console, $mode = 'live') {
    return unless $console eq 'root-virtio-terminal';

    # Every wait must be checked: continuing to type after a missed prompt
    # would feed the credentials (including the installed secret) to whatever
    # owns the tty and echo them into the uploaded serial log.
    # Generous: after the installer reboots, this waits for the whole boot of
    # the freshly installed system, not just for a getty to respawn.
    defined testapi::wait_serial('login:', timeout => 180)
      or die 'serial console did not show a login prompt';
    my ($user, $password) = ('biglinux', 'biglinux');
    if ($mode eq 'installed') {
        $user = testapi::get_required_var('BIGLINUX_TEST_USER');
        $password = testapi::get_required_var('_SECRET_BIGLINUX_TEST_PASSWORD');
    }

    testapi::type_string $user;
    testapi::send_key 'ret';
    defined testapi::wait_serial('Password:', timeout => 30)
      or die 'serial console did not ask for a password';
    if ($mode eq 'installed') {
        testapi::type_password $password;
    }
    else {
        testapi::type_string $password;
    }
    testapi::send_key 'ret';

    # The image announces its shell integration once the decorated prompt is
    # up, which is a convenient hint that input will be read. Treat it as a
    # hint only: the installed system creates a fresh user whose shell may not
    # announce anything, and an image is free to change or drop that banner.
    testapi::wait_serial(qr/type=shell/, timeout => 30);

    # Replace the interactive shell with a plain Bash so command echo stays
    # deterministic. Retry: characters typed before the login shell starts
    # reading are simply lost, and only the prompt proves it took over.
    my $bash_ready;
    for (1 .. 10) {
        testapi::type_string "exec env TERM=dumb bash --noprofile --norc\n";
        $bash_ready = testapi::wait_serial(qr/bash-[0-9.]+\$ /, timeout => 15);
        last if defined $bash_ready;
    }
    defined $bash_ready
      or die 'plain bash did not take over the serial console';
    my $ready_marker = '__OA_SERIAL_READY__';
    testapi::type_string "export PS1='# '; printf '" . _marker_format($ready_marker) . "\\n'\n";
    defined testapi::wait_serial($ready_marker, timeout => 15)
      or die 'serial console shell did not confirm readiness';
    defined testapi::wait_serial('# ', no_regex => 1, timeout => 10)
      or die 'serial console prompt did not appear';
}

sub _marker_format ($marker) {
    return join '', map { sprintf '\\%03o', ord } split //, $marker;
}

1;
