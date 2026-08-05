# SPDX-License-Identifier: GPL-2.0-or-later

package calamares;

use Mojo::Base -strict;
use testapi;
use atspi;

# Buttons are located by their accessibility label, so the lists below are the
# only place a renamed or newly translated control has to be taught. A failure
# reports every button the installer exposed, which names the replacement.
our @NEXT = ('Next', 'Próximo', 'Continue', 'Continuar', 'Avançar');
our @INSTALL = ('Install', 'Instalar', 'Install now', 'Instalar agora');
our @DONE = ('Done', 'Concluir', 'Finish', 'Finalizar');

# Qt Widgets publishes a "push button" while Qt Quick publishes a "button";
# accept both so the toolkit Calamares happens to use is not a variable.
our $BUTTON_ROLES = 'push button|button';

sub click_action {
    my ($class, $labels, $timeout) = @_;
    return atspi->activate_widget($BUTTON_ROLES, $labels, $timeout // 60);
}

sub advance {
    my ($class, $current_tag, $next_tag, $timeout) = @_;
    $timeout //= 90;
    assert_screen $current_tag, 60;
    $class->click_action(\@NEXT);
    assert_screen $next_tag, $timeout;
}

sub test_user {
    return get_var('BIGLINUX_TEST_USER', 'openqa');
}

sub test_password {
    return get_required_var('_SECRET_BIGLINUX_TEST_PASSWORD');
}

sub test_hostname {
    return get_var('BIGLINUX_TEST_HOSTNAME', 'biglinux-openqa');
}

# Evidence, never a verdict: an installation that succeeded must not fail the
# release gate because its log could not be collected.
sub upload_installation_log {
    atspi->upload_guest_file('/var/log/installation.log', 'calamares-installation.log');
    atspi->upload_guest_file('/home/biglinux/installation.log',
        'calamares-live-installation.log');
}

1;
