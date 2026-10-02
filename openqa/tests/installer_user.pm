# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use calamares;

sub test_flags {
    return {fatal => 1};
}

sub run {
    calamares->assert_page('partitions-page', 60);
    atspi->activate_widget('radio button', ['Erase disk', 'Apagar disco'], 60, calamares->scope);
    # The radio reports its own state, which is what "selected" means here.
    my $erase = atspi->wait_widget('radio button', ['Erase disk', 'Apagar disco'], 60, calamares->scope);
    die 'the installer did not select the erase-disk option'
      unless ref $erase eq 'HASH' && $erase->{status} eq 'passed' && $erase->{widget}{checked};
    calamares->click_action(\@calamares::NEXT);
    calamares->assert_page('users-page', 90);

    # Reach the first field by Tab and fill the form in its focus order. The
    # full name pre-fills the login and computer names, so each field is
    # selected before it is typed over. Calamares publishes every page at
    # once, too much to walk completely, so presence is proven by the first
    # exact match; Tab must then land on that very object.
    atspi->focus_widget('text|entry', ['Full name', 'Nome completo'], 60,
        calamares->scope, positive_witness => 1);
    for my $value ('BigLinux openQA', calamares->test_user, calamares->test_hostname) {
        send_key 'ctrl-a';
        type_string $value;
        send_key 'tab';
    }
    type_password(calamares->test_password);
    send_key 'tab';
    type_password(calamares->test_password);
    # Calamares only enables "Next" once every field validates, so the button
    # becoming sensitive is the accessible equivalent of the green marks - and
    # unlike them it cannot be faked by a theme that draws a green icon.
    my $ready = atspi->wait_widget($calamares::BUTTON_ROLES, \@calamares::NEXT, 60,
        calamares->scope, positive_witness => 1);
    die 'Calamares did not accept the account details'
      unless ref $ready eq 'HASH' && $ready->{status} eq 'passed';

    calamares->click_action(\@calamares::NEXT);
    calamares->assert_page('summary-page', 90);
}

# Observation only: the failure is already recorded.
sub post_fail_hook {
    eval { calamares->collect_launch_failure_evidence };
    eval { select_console 'sut'; save_screenshot; };
}

1;
