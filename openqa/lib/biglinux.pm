# SPDX-License-Identifier: GPL-2.0-or-later

package biglinux;

use Mojo::Base 'distribution', -signatures;
use feature 'state';
# Import no symbols: importing testapi::script_run into this class would
# shadow distribution::script_run and recurse when the console probes run.
use testapi ();
use guest_shell qw(marker_format);

sub init ($self) {
    $self->SUPER::init;
    # The ISO starts agetty on hvc0. A named virtio console lets tests run
    # deterministic shell probes without typing shell syntax through VNC.
    #
    # It logs in as the desktop user, not as root, because the session it has
    # to reach is the user's: the application audit, every AT-SPI probe and the
    # accessibility bus all belong to that session. The name says so - an
    # earlier "root-" prefix cost a full security report, which measured
    # nothing and reported it as clean.
    $self->add_console('user-virtio-terminal', 'virtio-terminal');
}

# Which credentials the next activation should use. An extra argument to
# select_console cannot carry this: os-autoinst forwards it to
# distribution::console_selected, whose signature takes the console alone and
# dies on anything more.
my $credentials = 'live';

sub use_installed_credentials {
    $credentials = 'installed';
}

sub activate_console ($self, $console, @) {
    return unless $console eq 'user-virtio-terminal';
    my $mode = $credentials;

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
        $password = biglinux->test_password;
    }

    testapi::type_string $user;
    testapi::send_key 'ret';
    # login(1) asks in the system language: the installed system is configured
    # in Portuguese and prompts "Senha:", so matching only "Password:" waited
    # out its timeout on a perfectly good installation. Add the prompt of any
    # further language the gate installs in.
    defined testapi::wait_serial(qr/(?:Password|Senha)\s*:/i, timeout => 30)
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
    testapi::type_string "export PS1='# '; printf '" . marker_format($ready_marker) . "\\n'\n";
    defined testapi::wait_serial($ready_marker, timeout => 15)
      or die 'serial console shell did not confirm readiness';
    defined testapi::wait_serial('# ', no_regex => 1, timeout => 10)
      or die 'serial console prompt did not appear';
}

# The test user's password, read from the file the runner mounts.
#
# Never a job setting: isotovideo writes vars.json before the tests start and
# does not redact it, and that directory is uploaded as an artifact. A password
# that is never a variable cannot leak through one.
sub test_password {
    state $password;
    return $password if defined $password;
    my $path = testapi::get_required_var('BIGLINUX_TEST_PASSWORD_FILE');
    open my $handle, '<', $path
      or die "cannot read the test password from $path: $!";
    $password = do { local $/; <$handle> };
    close $handle;
    $password =~ s/\s+\z//;
    die "the test password file is empty: $path" if $password eq '';
    return $password;
}


# Raises the serial console to root for the probes that need it, and answers
# whether it worked. Callers must check: a probe that keeps going unprivileged
# reads a system it cannot see and reports it as clean. "grep -s NOPASSWD
# /etc/sudoers" returning nothing is exactly that failure - the file is 0440
# root, and -s hides the permission error.
#
# Root stays opt-in and per-probe. Making the shared console root would run the
# desktop applications as root, which is neither what ships nor what the
# accessibility probes can talk to.
sub become_root {
    my $uid_marker = '__OA_ROOT_UID__';
    my $uid_format = marker_format($uid_marker);
    my $check = "printf '$uid_format%s$uid_format\\n' \"\$(sudo -n id -u 2>/dev/null)\"\n";
    my $is_root = sub {
        testapi::type_string $check;
        my $answer = testapi::wait_serial(qr/${uid_marker}(\d*)${uid_marker}/, timeout => 60);
        return defined $answer && $answer =~ /${uid_marker}0${uid_marker}/;
    };

    # The live session grants the desktop user passwordless sudo, so ask before
    # typing anything.
    return 1 if $is_root->();

    my $password = $credentials eq 'installed'
      ? biglinux->test_password
      : 'biglinux';
    my $prompt_marker = '__OA_SUDO_PASSWORD__';
    my $prompt_format = marker_format($prompt_marker);
    my $done_marker = '__OA_SUDO_DONE__';
    my $done_format = marker_format($done_marker);

    for (1 .. 2) {
        # Never type the password without seeing sudo ask for it. Typing it
        # blind is not just a race: the bytes arrive before sudo starts reading
        # the tty, so the line discipline echoes the secret into the serial log
        # that the job uploads, and sudo then reads the *next* typed line as
        # the password. That is what happened on job 17, which leaked the local
        # test password and failed with "2 incorrect password attempts".
        #
        # The prompt is built by printf so the echo of the command itself
        # carries the octal escapes rather than the marker: only sudo's own
        # prompt matches.
        testapi::type_string "sudo -k; sudo -S -p \"\$(printf '$prompt_format')\" -v"
          . "; printf '$done_format\\n'\n";
        next unless defined testapi::wait_serial($prompt_marker, timeout => 30);
        testapi::type_password $password;
        testapi::send_key 'ret';
        # Wait for sudo to exit before typing anything else. It prints nothing
        # on success, so without this marker the next command is typed while
        # sudo is still reading stdin and becomes another password attempt: on
        # a GitHub runner that swallowed the uid check twice and turned a
        # non-blocking module into a failed one. The marker is printed whether
        # sudo succeeded or not, so the check below always gets to run.
        next unless defined testapi::wait_serial($done_marker, timeout => 60);
        return 1 if $is_root->();
    }

    # Leave the console usable for the modules that follow. A sudo that read a
    # wrong password keeps asking, and every command typed after it becomes
    # another attempt: on job 17 the next module found the shell eating its
    # input and died on an unrelated AT-SPI timeout.
    # A control character, not send_key: the virtio terminal backend dies with
    # "Virtio terminal and svirt serial terminal do not support send_key" for
    # anything it cannot map, and that turned a failed escalation into a dead
    # backend and an incomplete job on a GitHub runner.
    testapi::type_string "\003\n";
    testapi::wait_serial('# ', no_regex => 1, timeout => 15);
    return 0;
}

1;
