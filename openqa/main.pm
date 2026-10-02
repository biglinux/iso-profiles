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

# Install, first boot and the installed system, shared by both firmware plans.
my @install = map { "openqa/tests/$_.pm" } qw(
    installer_launch installer_partitions installer_user installer_install
    installed_boot installed_login nonvisual_tasks installed_health
    installed_security installed_critical_apps installed_brave
);
my $live = 'openqa/tests/live_desktop.pm';
my $applications = 'openqa/tests/applications.pm';

my %schedules = (
    live => [$live],
    applications => [$live, $applications],
    release => [$live, $applications, @install],
    release_uefi => [$live, @install],
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
