# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base -strict;
use autotest;
use File::Basename 'dirname';
use lib dirname(__FILE__) . '/lib';
use biglinux;
use testapi;

testapi::set_distribution(biglinux->new);

my %schedules = (
    boot_menu => [
        'openqa/tests/boot_menu.pm',
        'openqa/tests/live_desktop.pm',
    ],
    applications => [
        'openqa/tests/boot_menu.pm',
        'openqa/tests/live_desktop.pm',
        'openqa/tests/applications.pm',
    ],
    installer => [
        'openqa/tests/boot_menu.pm',
        'openqa/tests/live_desktop.pm',
        'openqa/tests/installer_launch.pm',
        'openqa/tests/installer_partitions.pm',
        'openqa/tests/installer_user.pm',
        'openqa/tests/installer_install.pm',
        'openqa/tests/installed_boot.pm',
        'openqa/tests/installed_login.pm',
        'openqa/tests/installed_health.pm',
        'openqa/tests/installed_brave.pm',
    ],
    release => [
        'openqa/tests/boot_menu.pm',
        'openqa/tests/live_desktop.pm',
        'openqa/tests/applications.pm',
        'openqa/tests/installer_launch.pm',
        'openqa/tests/installer_partitions.pm',
        'openqa/tests/installer_user.pm',
        'openqa/tests/installer_install.pm',
        'openqa/tests/installed_boot.pm',
        'openqa/tests/installed_login.pm',
        'openqa/tests/installed_health.pm',
        'openqa/tests/installed_brave.pm',
    ],
    release_uefi => [
        'openqa/tests/boot_menu.pm',
        'openqa/tests/live_desktop.pm',
        'openqa/tests/installer_launch.pm',
        'openqa/tests/installer_partitions.pm',
        'openqa/tests/installer_user.pm',
        'openqa/tests/installer_install.pm',
        'openqa/tests/installed_boot.pm',
        'openqa/tests/installed_login.pm',
        'openqa/tests/installed_health.pm',
        'openqa/tests/installed_brave.pm',
    ],
);

my $schedule = get_var('BIGLINUX_SCHEDULE', 'boot_menu');
die "Unknown openQA schedule '$schedule'" unless exists $schedules{$schedule};
autotest::loadtest($_) for @{$schedules{$schedule}};

1;
