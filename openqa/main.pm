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
    ],
    applications => [
        'openqa/tests/boot_menu.pm',
        'openqa/tests/applications.pm',
    ],
    installer => [
        'openqa/tests/boot_menu.pm',
        'openqa/tests/installer.pm',
    ],
);

my $schedule = get_var('BIGLINUX_SCHEDULE', 'boot_menu');
die "Unknown openQA schedule '$schedule'" unless exists $schedules{$schedule};
autotest::loadtest($_) for @{$schedules{$schedule}};

1;
