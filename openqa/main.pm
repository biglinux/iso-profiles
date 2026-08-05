# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base -strict;
use autotest;
use File::Basename 'dirname';
use lib dirname(__FILE__) . '/lib';
use biglinux;
use testapi;

testapi::set_distribution(biglinux->new);

# GRUB is intentionally not validated: if the boot loader is broken nothing
# boots and the first module below fails with an obvious timeout.
my %schedules = (
    live => [
        'openqa/tests/live_desktop.pm',
    ],
    applications => [
        'openqa/tests/live_desktop.pm',
        'openqa/tests/applications.pm',
    ],
    installer => [
        'openqa/tests/live_desktop.pm',
        'openqa/tests/installer_launch.pm',
        'openqa/tests/installer_partitions.pm',
        'openqa/tests/installer_user.pm',
        'openqa/tests/installer_install.pm',
        'openqa/tests/installed_boot.pm',
        'openqa/tests/installed_login.pm',
        'openqa/tests/installed_health.pm',
        'openqa/tests/installed_critical_apps.pm',
        'openqa/tests/installed_brave.pm',
    ],
    release => [
        'openqa/tests/live_desktop.pm',
        'openqa/tests/applications.pm',
        'openqa/tests/installer_launch.pm',
        'openqa/tests/installer_partitions.pm',
        'openqa/tests/installer_user.pm',
        'openqa/tests/installer_install.pm',
        'openqa/tests/installed_boot.pm',
        'openqa/tests/installed_login.pm',
        'openqa/tests/installed_health.pm',
        'openqa/tests/installed_critical_apps.pm',
        'openqa/tests/installed_brave.pm',
    ],
    release_uefi => [
        'openqa/tests/live_desktop.pm',
        'openqa/tests/installer_launch.pm',
        'openqa/tests/installer_partitions.pm',
        'openqa/tests/installer_user.pm',
        'openqa/tests/installer_install.pm',
        'openqa/tests/installed_boot.pm',
        'openqa/tests/installed_login.pm',
        'openqa/tests/installed_health.pm',
        'openqa/tests/installed_critical_apps.pm',
        'openqa/tests/installed_brave.pm',
    ],
);

my $schedule = get_var('BIGLINUX_SCHEDULE', 'live');
die "Unknown openQA schedule '$schedule'" unless exists $schedules{$schedule};
autotest::loadtest($_) for @{$schedules{$schedule}};

1;
