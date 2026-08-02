# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use installed_system;

sub test_flags {
    return {fatal => 1};
}

sub run {
    installed_system->assert_desktop;

    # The installed user and password are intentionally different from the
    # live-session account, so a post-reboot serial probe could block while
    # waiting for the wrong getty credentials.  The independent graphical
    # launch below proves that the executable is installed and usable.
    send_key 'alt-f2';
    type_string 'brave --no-first-run --no-default-browser-check about:blank';
    assert_screen_change(sub { send_key 'ret' }, 60)
      or die 'The Brave launcher did not change the installed desktop';
    assert_screen 'biglinux-installed-brave-window', 120;

    assert_screen_change(sub {
        send_key 'ctrl-l';
        type_string 'about:version';
        send_key 'ret';
    }, 60) or die 'The installed Brave window did not respond to navigation';
    assert_screen 'biglinux-installed-brave-version', 60;

    assert_screen_change(sub { send_key 'alt-f4' }, 30)
      or die 'The installed Brave window did not close';
    assert_screen 'biglinux-installed-desktop', 60;
}

1;
