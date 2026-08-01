# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base -strict;
use autotest;
use File::Basename 'dirname';
use lib dirname(__FILE__) . '/lib';
use biglinux;
use testapi;

testapi::set_distribution(biglinux->new);

autotest::loadtest 'openqa/tests/boot_menu.pm';
autotest::loadtest 'openqa/tests/applications.pm';
autotest::loadtest 'openqa/tests/installer.pm';

1;
