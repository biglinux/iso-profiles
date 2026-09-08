# SPDX-License-Identifier: GPL-2.0-or-later

package calamares;

use Mojo::Base -strict;
# The button labels below are not ASCII. Without this pragma Perl reads the
# file as latin-1, "Próximo" becomes two characters, and the probe is asked for
# a button whose name no installer will ever have.
use utf8;
use testapi;
use biglinux;
use atspi;

# Buttons are located by their accessibility label, so the lists below are the
# only place a renamed or newly translated control has to be taught. A failure
# reports every button the installer exposed, which names the replacement.
our @NEXT = ('Next', 'Próximo', 'Continue', 'Continuar', 'Avançar');
our @INSTALL = ('Install', 'Instalar', 'Install now', 'Instalar agora');
# "Concluído" is what this build actually names the button; the probe folds
# accents and case, but it cannot guess a different word.
our @DONE = ('Done', 'Concluir', 'Concluído', 'Finish', 'Finalizar');

# Qt Widgets publishes a "push button" while Qt Quick publishes a "button";
# accept both so the toolkit Calamares happens to use is not a variable.
our $BUTTON_ROLES = 'push button|button';

sub click_action {
    my ($class, $labels, $timeout) = @_;
    return atspi->activate_widget($BUTTON_ROLES, $labels, $timeout // 60);
}

# Each installer page is identified by a control only that page publishes,
# rather than by a picture of it. A needle records one build's pixels: a new
# theme, a moved column or a translated string turns it red, and a needle that
# still matches after the layout moved is worse - the 2026-08-04 language
# needle had its click point over what later builds render as another entry.
#
# Every anchor below is [role, [labels]]. Labels are compared with markup,
# case, punctuation and accents folded away (see data/atspi_probe.py), so both
# the English and the translated name can be listed.
our %PAGE_ANCHORS = (
    # The BigLinux launcher, before Calamares itself: its first screen offers
    # maintenance, installation and a "minimal" mode, and its second screen is
    # the partitioning advice. Both publish a "Continue" button, so each screen
    # has to be confirmed before its button is pressed - otherwise the run ends
    # up in the software-removal page, which is what happens when the two are
    # treated as one step.
    'launcher-home' => [$BUTTON_ROLES, ['Install', 'Instalar']],
    'launcher-tips' => ['label|heading|static',
        ['Manual Partitioning Recommendations', 'Recomendações de Particionamento Manual']],
    'installer-welcome' => ['label|heading|static',
        ['Welcome to the Calamares installer', 'Bem-vindo ao instalador Calamares']],
    'installer-location' => ['label|combo box', ['Region', 'Região']],
    'installer-keyboard' => ['label|combo box', ['Keyboard Model', 'Modelo de teclado']],
    'partitions-page' => ['radio button', ['Erase disk', 'Apagar disco']],
    'users-page' => ['label|entry', ['What is your name', 'Qual é o seu nome']],
    'summary-page' => [$BUTTON_ROLES, ['Install', 'Instalar']],
);

sub page_anchor {
    my ($class, $page) = @_;
    my $anchor = $PAGE_ANCHORS{$page}
      or die "no accessibility anchor is defined for installer page '$page'";
    return @{$anchor};
}

# Wait until a page is the one on screen. Returns the matching record so a
# caller can inspect the control it found.
sub assert_page {
    my ($class, $page, $timeout) = @_;
    my ($role, $labels) = $class->page_anchor($page);
    my $found = atspi->wait_widget($role, $labels, $timeout // 60);
    die "the installer did not show the '$page' page: "
      . ($found->{error} // 'unknown reason')
      unless ref $found eq 'HASH' && $found->{status} eq 'passed';
    return $found;
}

sub advance {
    my ($class, $current_page, $next_page, $timeout) = @_;
    $timeout //= 90;
    $class->assert_page($current_page, 60);
    $class->click_action(\@NEXT);
    $class->assert_page($next_page, $timeout);
}

sub test_user {
    return get_var('BIGLINUX_TEST_USER', 'openqa');
}

sub test_password {
    return biglinux->test_password;
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
