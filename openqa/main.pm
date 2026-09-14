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
        'openqa/tests/nonvisual_tasks.pm',
        'openqa/tests/installed_health.pm',
        'openqa/tests/installed_security.pm',
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
        'openqa/tests/nonvisual_tasks.pm',
        'openqa/tests/installed_health.pm',
        'openqa/tests/installed_security.pm',
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
        'openqa/tests/nonvisual_tasks.pm',
        'openqa/tests/installed_health.pm',
        'openqa/tests/installed_security.pm',
        'openqa/tests/installed_critical_apps.pm',
        'openqa/tests/installed_brave.pm',
    ],
);

my $schedule = get_var('BIGLINUX_SCHEDULE', 'live');
die "Unknown openQA schedule '$schedule'" unless exists $schedules{$schedule};
my $deep = get_var('BIGLINUX_DEEP_APPLICATION_TESTS', '0');
die 'BIGLINUX_DEEP_APPLICATION_TESTS must be 0 or 1' unless $deep =~ /\A[01]\z/;
# The default application contract is open -> accessible content -> shortcut -> exit.
# Task-specific tests and Orca instrumentation are explicit opt-ins only.
for my $module (@{$schedules{$schedule}}) {
    next if !$deep && $module =~ m{/(?:nonvisual_tasks|installed_brave)\.pm\z};
    autotest::loadtest($module);
}

1;
