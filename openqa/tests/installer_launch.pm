# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub test_flags {
    return {fatal => 1};
}

sub run {
    assert_screen 'biglinux-live-desktop', 60;

    # The UEFI build opens a firmware warning before the BigLinux launcher.
    # Detect the firmware through the live serial console so the graphical
    # path does not click blindly through a dialog that exists only in UEFI.
    select_console 'root-virtio-terminal';
    type_string 'if [ -d /sys/firmware/efi ]; then printf "__OA_FIRMWARE_UEFI__\\n"; else printf "__OA_FIRMWARE_BIOS__\\n"; fi';
    send_key 'ret';
    my $biglinux_firmware_mode = wait_serial qr/__OA_FIRMWARE_(?:BIOS|UEFI)__/, timeout => 30;
    select_console 'sut';
    die 'The live firmware mode could not be determined from the serial console'
      unless defined $biglinux_firmware_mode;

    send_key 'alt-f2';
    type_string 'calamares-biglinux_polkit --software-render';
    assert_screen_change(sub { send_key 'ret' }, 60)
      or die 'The BigLinux Calamares launcher did not open';

    if ($biglinux_firmware_mode =~ /UEFI/) {
        assert_screen_change(sub { send_key 'ret' }, 60)
          or die 'The UEFI installation confirmation was not accepted';
    }

    assert_and_click 'biglinux-installer-launcher', timeout => 90,
      point_id => 'install', mousehide => 1;
    assert_screen 'biglinux-installer-tips', 60;
    assert_and_click 'biglinux-installer-tips', timeout => 60,
      point_id => 'continue', mousehide => 1;
    assert_screen 'biglinux-installer-welcome', 90;
}

1;
