# SPDX-License-Identifier: GPL-2.0-or-later

package calamares;

use Mojo::Base -strict;
use testapi;

sub advance {
    my ($class, $current_tag, $next_tag, $timeout) = @_;
    $timeout //= 90;
    assert_and_click $current_tag, point_id => 'next', timeout => 60,
      mousehide => 1;
    assert_screen $next_tag, $timeout;
}

sub test_user {
    return get_var('BIGLINUX_TEST_USER', 'openqa');
}

sub test_password {
    return get_required_var('_SECRET_BIGLINUX_TEST_PASSWORD');
}

sub test_hostname {
    return get_var('BIGLINUX_TEST_HOSTNAME', 'biglinux-openqa');
}

sub upload_installation_log {
    select_console 'root-virtio-terminal';
    assert_script_run 'test -s /home/biglinux/installation.log || test -s /var/log/installation.log';
    upload_logs '/home/biglinux/installation.log', failok => 1,
      log_name => 'calamares-live-installation.log';
    upload_logs '/var/log/installation.log', failok => 1,
      log_name => 'calamares-installation.log';
    select_console 'sut';
}

1;
