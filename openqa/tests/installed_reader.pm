# SPDX-License-Identifier: GPL-2.0-or-later
use Mojo::Base 'basetest';
use testapi;
use atspi;
use biglinux;
use installed_system;
use orca;

# The installed system's own screens with Orca running: the lock screen and
# the authorization prompt each have to make Orca speak, and both are operated
# by keyboard. What Orca says is not judged.

sub test_flags {
    return {fatal => 0};
}

sub _session {
    my $user = get_required_var('BIGLINUX_TEST_USER');
    return "\$(loginctl show-user $user -p Display --value)";
}

# The oldest process of the test user whose command line matches $pattern; an
# AT-SPI search scoped to it covers its children too. BigLinux starts the
# lock screen through a /bin/sh wrapper that runs kscreenlocker_greet_orig.
# Write the pattern with a bracketed first letter, "[k]screenlocker_greet",
# so it never matches this lookup's own command line.
sub _pid_of {
    my ($pattern) = @_;
    my $user = get_required_var('BIGLINUX_TEST_USER');
    my $found = atspi->guest_json(['python3', '-c', <<'PYTHON', $user, $pattern], 20, "process '$pattern'");
import json, subprocess, sys, time
for _ in range(40):
    pids = subprocess.run(["pgrep", "-o", "-u", sys.argv[1], "-f", sys.argv[2]],
                          capture_output=True, text=True).stdout.split()
    if pids:
        break
    time.sleep(0.25)
print("__OPENQA_ATSPI__" + json.dumps({"pid": int(pids[0]) if pids else 0}).encode().hex())
PYTHON
    die "no process matches '$pattern'" unless ($found->{pid} // 0) > 1;
    return $found->{pid};
}

# The screen under test belongs to its own process; a showing window of that
# process with accessible content proves the screen is up, so Orca's speech
# since the mark is about it. (The lock screen's password field is published
# without SHOWING, so a widget search cannot be the proof.)
sub _assert_screen {
    my ($what, $pattern) = @_;
    my $screen = atspi->result('smoke-window', 30, '--pid', _pid_of($pattern));
    die "$what did not show an accessible window: " . ($screen->{error} // 'no answer')
      unless ($screen->{status} // '') eq 'passed'
      && ($screen->{coverage} // '') eq 'accessible-content-present';
}

sub _unlock_by_keyboard {
    my $session = _session;
    my $since = orca->mark;
    my $requested = atspi->run_command("loginctl lock-session $session", 15);
    die 'the session could not be asked to lock' unless defined $requested && $requested == 0;
    my $locked = atspi->run_command_until(
        "loginctl show-session $session -p LockedHint | grep -q =yes", 30);
    die 'the session did not lock' unless defined $locked && $locked == 0;
    my $checked = eval {
        _assert_screen('the lock screen', '[k]screenlocker_greet');
        orca->check($since, 'the lock screen');
        1;
    };
    my $error = $@;

    # Unlock whatever the checks found: every module after this one needs the
    # session.
    select_console 'sut';
    type_password(installed_system->test_password);
    send_key 'ret';
    my $unlocked = atspi->run_command_until(
        "loginctl show-session $session -p LockedHint | grep -q =no", 30);
    die 'the lock screen did not unlock with the password typed at it'
      unless defined $unlocked && $unlocked == 0;
    die $error unless $checked;
    record_info 'Lock screen', 'Orca spoke on the lock screen and the password typed there unlocked the session';
}

sub _authorization_prompt {
    # pkexec from the serial console belongs to another login session, whose
    # authentication agent does not exist. Ask polkit directly, on behalf of
    # the session's shell and with user interaction allowed: the session's
    # agent shows its dialog exactly as for a program the user started. A
    # unix-session subject would be simpler, but polkitd 127 aborts on it.
    # become_root types into the selected console; the lock screen left the
    # graphical one selected.
    select_console 'user-virtio-terminal';
    die 'the authorization prompt needs root to ask polkit on behalf of the session'
      unless biglinux->become_root;
    my $user = get_required_var('BIGLINUX_TEST_USER');
    my $since = orca->mark;
    my $asked = atspi->run_command(
        "shell=\$(pgrep -u $user -x plasmashell | head -n1)"
          . ' && started=$(awk \'{print $22}\' /proc/$shell/stat)'
          . " && uid=\$(id -u $user)"
          . ' && rm -f /tmp/openqa-polkit-answer'
          . ' && ( sudo -n gdbus call --system --timeout 60 --dest org.freedesktop.PolicyKit1'
          . ' --object-path /org/freedesktop/PolicyKit1/Authority'
          . ' --method org.freedesktop.PolicyKit1.Authority.CheckAuthorization'
          . ' "(\'unix-process\', {\'pid\': <uint32 $shell>, \'start-time\': <uint64 $started>, \'uid\': <int32 $uid>})"'
          . " org.freedesktop.policykit.exec '{}' 1 openqa-reader"
          . ' > /tmp/openqa-polkit-answer 2>&1 & )', 15);
    die 'polkit could not be asked for authorization' unless defined $asked && $asked == 0;
    my $checked = eval {
        _assert_screen('the authorization prompt', '[p]olkit-kde-authentication-agent-1');
        orca->check($since, 'the authorization prompt');
        1;
    };
    my $error = $@;

    select_console 'sut';
    send_key 'esc';
    # Answered "not authorized" and no challenge left: the user said no.
    my $dismissed = atspi->run_command_until(
        "grep -q '^((false, false' /tmp/openqa-polkit-answer", 30);
    die 'the authorization prompt did not close with Escape'
      unless defined $dismissed && $dismissed == 0;
    die $error unless $checked;
    record_info 'Authorization prompt', 'Orca spoke on the polkit prompt, and Escape dismissed it';
}

sub run {
    die 'Orca is not running for the installed session' unless orca->active;
    _unlock_by_keyboard;
    _authorization_prompt;
}

1;
