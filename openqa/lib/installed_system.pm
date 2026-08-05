# SPDX-License-Identifier: GPL-2.0-or-later

package installed_system;

use Mojo::Base -strict;
use testapi;
use atspi;

sub test_password {
    return get_required_var('_SECRET_BIGLINUX_TEST_PASSWORD');
}

sub assert_filesystem {
    # assert_desktop (installed_login, fatal) already activated the serial
    # console with the installed credentials; the login session owns hvc0 and
    # a reset would wait for a login prompt that never reappears.
    select_console 'root-virtio-terminal';

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
efi_present=0
test -d /sys/firmware/efi && efi_present=1
efi_mount=0
test -n "$(findmnt -no SOURCE /boot/efi 2>/dev/null || true)" && efi_mount=1
efi_boot=0
if command -v efibootmgr >/dev/null 2>&1 && efibootmgr -v 2>/dev/null | grep -q '^Boot'; then
    efi_boot=1
fi
{
    printf 'findmnt /:\n'
    findmnt / 2>&1
    printf 'firmware EFI directory: %s\n' "$efi_present"
    printf 'findmnt /boot/efi:\n'
    findmnt /boot/efi 2>&1 || true
    printf 'efibootmgr -v:\n'
    efibootmgr -v 2>&1 || true
    printf 'systemctl --failed --no-legend:\n'
    printf '%s\n' "$failed_unit_list"
    printf 'big-release: %s\n' "$release_present"
    printf 'failed units: %s\n' "$failed_units"
    printf 'brave executable: %s\n' "$brave_present"
    printf 'overlay root: %s\n' "$overlay_root"
    printf 'EFI mount: %s\n' "$efi_mount"
    printf 'EFI boot entries: %s\n' "$efi_boot"
    printf 'memory after installed boot:\n'
    free -h
    printf 'disk after installed boot:\n'
    df -h /
} >/tmp/openqa-installed-health.log
printf '__OA_HEALTH_MARKER_FORMAT__root=%s;type=%s;release=%s;failed=%s;overlay=%s;brave=%s;efi=%s;efi_mount=%s;efi_boot=%s__\n' "$root_source" "$root_fstype" "$release_present" "$failed_units" "$overlay_root" "$brave_present" "$efi_present" "$efi_mount" "$efi_boot"
SHELL
    $health_check =~ s/__OA_HEALTH_MARKER_FORMAT__/_marker_format('__OA_INSTALLED_HEALTH__')/e;
    type_string $health_check;
    my $result = wait_serial qr/__OA_INSTALLED_HEALTH__root=([^;]*);type=([^;]*);release=(\d+);failed=(\d+);overlay=(\d+);brave=(\d+);efi=(\d+);efi_mount=(\d+);efi_boot=(\d+)__/, timeout => 90;
    select_console 'sut';
    atspi->upload_guest_file('/tmp/openqa-installed-health.log', 'installed-health.log');

    die 'The installed-system health probe did not return a result' unless defined $result;
    my ($root_source, $root_fstype, $release_present, $failed_units, $overlay_root, $brave_present, $efi_present, $efi_mount, $efi_boot) = $result =~ /__OA_INSTALLED_HEALTH__root=([^;]*);type=([^;]*);release=(\d+);failed=(\d+);overlay=(\d+);brave=(\d+);efi=(\d+);efi_mount=(\d+);efi_boot=(\d+)__/;
    die 'The installed root filesystem is missing or still uses overlayfs'
      unless $root_source =~ m{^/dev/} && $root_fstype ne 'overlay' && !$overlay_root;
    die 'The installed system is missing /etc/big-release' unless $release_present;
    die "The installed system has $failed_units failed systemd units" unless !$failed_units;
    die 'The installed system is missing an executable Brave binary' unless $brave_present;
    my $uefi_expected = get_var('UEFI', '0') eq '1';
    die 'UEFI job did not expose /sys/firmware/efi' if $uefi_expected && !$efi_present;
    die 'UEFI job did not mount /boot/efi' if $uefi_expected && !$efi_mount;
    die 'UEFI job did not expose an efibootmgr entry' if $uefi_expected && !$efi_boot;
    die 'BIOS job unexpectedly exposed /sys/firmware/efi' if !$uefi_expected && $efi_present;
    record_info 'Installed firmware', sprintf(
        'expected=%s; /sys/firmware/efi=%s; /boot/efi=%s; efibootmgr=%s',
        $uefi_expected ? 'UEFI' : 'BIOS', $efi_present, $efi_mount, $efi_boot
    );
}

sub assert_brave_cli {
    my $exit_code = atspi->run_command(
        'brave --version >/tmp/openqa-brave-version.log 2>&1', 60);
    atspi->upload_guest_file('/tmp/openqa-brave-version.log', 'brave-version.log');
    die 'Brave CLI did not exit successfully (exit code '
      . (defined $exit_code ? $exit_code : 'timeout') . ')'
      unless defined $exit_code && $exit_code == 0;
}

sub assert_desktop {
    # First serial use after the reboot: activate the console with the
    # installed credentials before atspi->prepare selects it without a mode
    # (which would try the live biglinux/biglinux login that no longer exists).
    reset_consoles;
    select_console 'root-virtio-terminal', 'installed';
    select_console 'sut';
    atspi->prepare;
    my $desktop_exit_code = atspi->run_command(
        'for i in $(seq 1 30); do pgrep -u 1000 -x plasmashell >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1',
        45);
    die 'The installed KDE Plasma shell did not start'
      unless defined $desktop_exit_code && $desktop_exit_code == 0;
    record_info 'Installed desktop', 'AT-SPI is active and plasmashell is running for the logged-in user';
}

sub _marker_format {
    my ($marker) = @_;
    return join '', map { sprintf '\\%03o', ord } split //, $marker;
}

1;
