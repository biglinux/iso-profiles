# SPDX-License-Identifier: GPL-2.0-or-later

package installed_system;

use Mojo::Base -strict;
use testapi;

sub test_password {
    return get_required_var('_SECRET_BIGLINUX_TEST_PASSWORD');
}

sub assert_desktop {
    assert_screen ['biglinux-installed-desktop', 'biglinux-installed-welcome'], 300;
    if (match_has_tag 'biglinux-installed-welcome') {
        assert_screen_change(sub { send_key 'alt-f4' }, 30)
          or die 'The installed BigLinux welcome screen did not close';
    }
    assert_screen 'biglinux-installed-desktop', 60;
    wait_still_screen stilltime => 3, timeout => 60;
}

1;
