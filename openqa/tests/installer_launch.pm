# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;

sub test_flags {
    return {fatal => 1};
}

sub run {
    # The UEFI build opens a firmware warning before the BigLinux launcher.
    # Detect the firmware through the live serial console so the graphical
    # path does not click blindly through a dialog that exists only in UEFI.
    # The preceding live_desktop module already owns the non-black screenshot
    # checkpoints; launching Calamares below validates this state semantically.
    select_console 'root-virtio-terminal';
    my $uefi_marker = _marker_format('__OA_FIRMWARE_UEFI__');
    my $bios_marker = _marker_format('__OA_FIRMWARE_BIOS__');
    type_string "if [ -d /sys/firmware/efi ]; then printf '$uefi_marker\\n'; else printf '$bios_marker\\n'; fi";
    send_key 'ret';
    my $biglinux_firmware_mode = wait_serial qr/__OA_FIRMWARE_(?:BIOS|UEFI)__/, timeout => 30;
    select_console 'sut';
    die 'The live firmware mode could not be determined from the serial console'
      unless defined $biglinux_firmware_mode;

    my $is_uefi = $biglinux_firmware_mode =~ /UEFI/;
    my $first_window = $is_uefi ? 'Install the system' : 'BigLinux Installation';

    atspi->prepare;
    my (undef, $opened, undef, undef, $status_path) = atspi->launch_command(
        'calamares-biglinux_polkit --software-render',
        $first_window,
        120
    );
    unless ($opened->{status} eq 'passed') {
        atspi->abort_launch($status_path);
        die 'The BigLinux Calamares launcher did not expose its first AT-SPI window';
    }

    if ($is_uefi) {
        wait_screen_change(sub { send_key 'ret' }, 60)
          or die 'The UEFI installation confirmation was not accepted';
        my $main_window = atspi->result(
            'wait-open', 120, '--name', 'BigLinux Installation'
        );
        unless ($main_window->{status} eq 'passed') {
            atspi->abort_launch($status_path);
            die 'The BigLinux installer did not open after the UEFI confirmation';
        }
    }

    assert_and_click 'biglinux-installer-launcher', timeout => 90,
      point_id => 'install', mousehide => 1;
    assert_screen 'biglinux-installer-tips', 60;
    assert_and_click 'biglinux-installer-tips', timeout => 60,
      point_id => 'continue', mousehide => 1;
    assert_screen 'biglinux-installer-welcome', 90;
}

sub _marker_format {
    my ($marker) = @_;
    return join '', map { sprintf '\\%03o', ord } split //, $marker;
}

1;
