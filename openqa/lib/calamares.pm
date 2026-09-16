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

my $launch_pid;
my $application_pid;
my $handoff_token;
my $application_index;

sub set_launch_scope {
    my ($class, $pid, $token) = @_;
    die 'Calamares requires a valid launch-tree PID'
      unless defined $pid && $pid =~ /\A[0-9]+\z/ && $pid > 1;
    die 'Calamares requires a valid privilege-handoff token'
      unless defined $token && $token =~ /\Aopenqa-calamares-[A-Za-z0-9-]{1,192}\z/;
    $launch_pid = $pid;
    $application_pid = undef;
    $handoff_token = $token;
    $application_index = undef;
    atspi->set_widget_scope($launch_pid, $launch_pid);
}

sub _require_launch_scope {
    die 'Calamares launch scope has not been established' unless defined $launch_pid;
    return $launch_pid;
}

# The BigLinux GTK launcher starts Qt Calamares through sudo and dbus-launch.
# That deliberate privilege boundary can move the Qt process outside the user
# supervisor's process group.  Resolve the handoff by an exact executable,
# root UID and the unique DESKTOP_STARTUP_ID that the product wrapper explicitly
# forwards.  A title, process name or globally new accessibility window is not
# sufficient provenance.
sub begin_application_transition {
    my ($class, $timeout) = @_;
    $class->_require_launch_scope;
    die 'Calamares handoff token has not been established'
      unless defined $handoff_token;
    my $resolved = atspi->wait_process_handoff(
        '/usr/bin/calamares', 'DESKTOP_STARTUP_ID', $handoff_token, 0,
        $timeout // 90,
    );
    die 'the privileged Qt Calamares process could not be identified: '
      . ($resolved->{error} // 'incomplete process observation')
      unless ref $resolved eq 'HASH' && ($resolved->{status} // '') eq 'passed';
    $application_pid = $resolved->{pid};
    $application_index = undef;
    # The exact Qt PID is now the authority.  Do not claim it is a setsid
    # supervisor root: ordinary descendant scoping is sufficient from here.
    atspi->set_widget_scope($application_pid, undef);
    return $resolved;
}

sub _scope_options {
    my ($class) = @_;
    my $root_pid = $class->_require_launch_scope;
    my %options;
    if (defined $application_pid) {
        %options = (pid => $application_pid, root_pid => undef);
    }
    else {
        %options = (pid => $root_pid, root_pid => $root_pid);
    }
    $options{application_index} = $application_index
      if defined $application_index;
    return %options;
}

sub _remember_application {
    my ($class, $result) = @_;
    return $result unless ref $result eq 'HASH' && ref $result->{widget} eq 'HASH';
    my $index = $result->{widget}{application_index};
    if (defined $index) {
        die 'installer control exposed an invalid AT-SPI application index'
          unless $index =~ /\A[0-9]+\z/;
        $application_index = 0 + $index;
    }
    return $result;
}

sub click_action {
    my ($class, $labels, $timeout) = @_;
    my %options = $class->_scope_options;
    return $class->_remember_application(
        atspi->activate_widget($BUTTON_ROLES, $labels, $timeout // 60, %options));
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
    # Do not rediscover globally or narrow to a transient GTK child: Calamares
    # replaces that child with a Qt process, still owned by the same launch.
    my %options = $class->_scope_options;
    if (defined $application_pid) {
        # The privileged Qt application is newly registered and can expose a
        # large, slow tree.  A page anchor needs one exact positive witness,
        # not a full census of unrelated descendants.  Absence and actions keep
        # their strict complete-tree contracts.
        $options{positive_witness} = 1;
        $options{startup_timeout_ms} = 5000;
    }
    my $found = $class->_remember_application(
        atspi->assert_widget($role, $labels, $timeout // 60, %options));
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
