# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base -strict;
use autotest;

autotest::loadtest 'openqa/tests/boot_menu.pm';
autotest::loadtest 'openqa/tests/applications.pm';
autotest::loadtest 'openqa/tests/installer.pm';

1;
