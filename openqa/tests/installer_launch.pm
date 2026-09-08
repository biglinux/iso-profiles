# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use calamares;
use guest_shell qw(marker_format);

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

    # No expected window title: the launcher renames its windows between
    # releases and localizes them. That a window appeared is enough here; the
    # installer pages asserted below prove it is really Calamares.
    # The installer runs in the live desktop session, which live_desktop
    # already installed the probe into; only the baseline is per session.
    atspi->reset_baseline;
    my (undef, $opened, undef, undef, $status_path) = atspi->launch_command(
        'calamares-biglinux_polkit --software-render',
        '',
        120
    );
    unless ($opened->{status} eq 'passed') {
        atspi->abort_launch($status_path);
        die 'The BigLinux Calamares launcher did not expose its first AT-SPI window';
    }

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
    calamares->assert_page('installer-welcome', 90);
}


1;
