# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use calamares;
use guest_shell qw(marker_format);
use Time::HiRes 'time';

sub test_flags {
    return {fatal => 1};
}

sub run {
    # The UEFI build opens a firmware warning before the BigLinux launcher.
    # Detect the firmware through the live serial console so the graphical
    # path does not click blindly through a dialog that exists only in UEFI.
    # The preceding live_desktop module already owns the non-black screenshot
    # checkpoints; launching Calamares below validates this state semantically.
    select_console 'user-virtio-terminal';
    my $uefi_marker = marker_format('__OA_FIRMWARE_UEFI__');
    my $bios_marker = marker_format('__OA_FIRMWARE_BIOS__');
    type_string "if [ -d /sys/firmware/efi ]; then printf '$uefi_marker\\n'; else printf '$bios_marker\\n'; fi";
    send_key 'ret';
    my $biglinux_firmware_mode = wait_serial qr/__OA_FIRMWARE_(?:BIOS|UEFI)__/, timeout => 30;
    select_console 'sut';
    die 'The live firmware mode could not be determined from the serial console'
      unless defined $biglinux_firmware_mode;

    my $is_uefi = $biglinux_firmware_mode =~ /UEFI/;

    # Follow the GTK launcher by its supervised process group. A unique desktop
    # startup identity is forwarded by the product's privilege wrapper and is
    # later used with the exact /usr/bin/calamares executable and root UID to
    # prove the Qt handoff. No title or globally new window establishes ownership.
    atspi->reset_baseline;
    my $handoff_token = sprintf('openqa-calamares-%d-%d', $$, int(time * 1_000_000));
    my (undef, $opened, undef, undef, $status_path, $launch_pid) = atspi->launch_command(
        "env DESKTOP_STARTUP_ID=$handoff_token calamares-biglinux_polkit --software-render",
        '',
        120,
        'process-tree'
    );
    unless ($opened->{status} eq 'passed') {
        atspi->abort_launch($status_path);
        die 'The BigLinux Calamares launcher did not expose its first AT-SPI window';
    }

    calamares->set_launch_scope($launch_pid, $handoff_token);

    if ($is_uefi) {
        # The EFI warning is one of the launcher's GTK4 dialogs, so its button
        # can be activated by name instead of by pressing return at a screen
        # that may not have focus yet.
        atspi->activate_widget($calamares::BUTTON_ROLES,
            ['Continue', 'Continuar'], 60);
    }

    # The launcher and its tips page are GTK4 (/usr/share/biglinux/calamares),
    # not the WebKit interface an older comment here described, so both are
    # driven by accessible name. Nothing in this module depends on the theme.
    calamares->assert_page('launcher-home', 90);
    atspi->activate_widget($calamares::BUTTON_ROLES, ['Install', 'Instalar'], 90);
    calamares->assert_page('launcher-tips', 60);
    atspi->activate_widget($calamares::BUTTON_ROLES, ['Continue', 'Continuar'], 60);
    # This action ends the GTK frontend and starts privileged Qt Calamares.
    # Resolve that deliberate boundary before querying the installer page.
    calamares->begin_application_transition(90);
    calamares->assert_page('installer-welcome', 90);
}


1;
