# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use calamares;

sub test_flags {
    return {fatal => 1};
}

sub run {
    # The welcome page is proven by installer_launch, which is the module that
    # opens the installer; this one walks from there to the partitioning page.
    calamares->click_action(\@calamares::NEXT);
    calamares->assert_page('installer-location', 90);
    calamares->advance('installer-location', 'installer-keyboard');
    calamares->advance('installer-keyboard', 'partitions-page');
}

1;
