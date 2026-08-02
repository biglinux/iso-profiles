# SPDX-License-Identifier: GPL-2.0-or-later

package installed_system;

use Mojo::Base -strict;
use testapi;

sub test_password {
    return get_required_var('_SECRET_BIGLINUX_TEST_PASSWORD');
}

sub assert_filesystem {
    reset_consoles;
    select_console 'root-virtio-terminal', 'installed';

    my $health_check = <<'SHELL';
root_source=$(findmnt -no SOURCE / 2>/dev/null || true)
root_fstype=$(findmnt -no FSTYPE / 2>/dev/null || true)
release_present=0
test -f /etc/big-release && release_present=1
failed_unit_list=$(systemctl --failed --no-legend --plain)
failed_units=$(printf '%s\n' "$failed_unit_list" | awk 'NF {count++} END {print count+0}')
brave_present=0
test -x /usr/bin/brave && brave_present=1
overlay_root=0
test "$(findmnt -no SOURCE / 2>/dev/null || true)" = overlay && overlay_root=1
{
    printf 'findmnt /:\n'
    findmnt / 2>&1
    printf 'systemctl --failed --no-legend:\n'
    printf '%s\n' "$failed_unit_list"
    printf 'big-release: %s\n' "$release_present"
    printf 'failed units: %s\n' "$failed_units"
    printf 'brave executable: %s\n' "$brave_present"
    printf 'overlay root: %s\n' "$overlay_root"
} >/tmp/openqa-installed-health.log
printf '__OA_INSTALLED_HEALTH__root=%s;type=%s;release=%s;failed=%s;overlay=%s;brave=%s__\n' "$root_source" "$root_fstype" "$release_present" "$failed_units" "$overlay_root" "$brave_present"
SHELL
    type_string $health_check;
    my $result = wait_serial qr/__OA_INSTALLED_HEALTH__root=([^;]*);type=([^;]*);release=(\d+);failed=(\d+);overlay=(\d+);brave=(\d+)__/, timeout => 90;
    upload_logs '/tmp/openqa-installed-health.log', log_name => 'installed-health.log', failok => 1;
    select_console 'sut';

    die 'The installed-system health probe did not return a result' unless defined $result;
    my ($root_source, $root_fstype, $release_present, $failed_units, $overlay_root, $brave_present) = $result =~ /__OA_INSTALLED_HEALTH__root=([^;]*);type=([^;]*);release=(\d+);failed=(\d+);overlay=(\d+);brave=(\d+)__/;
    die 'The installed root filesystem is missing or still uses overlayfs'
      unless $root_source =~ m{^/dev/} && $root_fstype ne 'overlay' && !$overlay_root;
    die 'The installed system is missing /etc/big-release' unless $release_present;
    die "The installed system has $failed_units failed systemd units" unless !$failed_units;
    die 'The installed system is missing an executable Brave binary' unless $brave_present;
}

sub assert_desktop {
    assert_screen ['biglinux-installed-desktop', 'biglinux-installed-welcome'], 300;
    if (match_has_tag 'biglinux-installed-welcome') {
        wait_screen_change(sub { send_key 'alt-f4' }, 30)
          or die 'The installed BigLinux welcome screen did not close';
    }
    assert_screen 'biglinux-installed-desktop', 60;
    wait_still_screen stilltime => 3, timeout => 60;
}

1;
