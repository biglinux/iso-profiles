use strict;
use warnings;
use Test::More;
use atspi;
use calamares;
no warnings qw(redefine once);

for my $method (sub { calamares->assert_page('launcher-home', 5) },
                sub { calamares->click_action(['Continue'], 5) },
                sub { calamares->begin_application_transition }) {
    eval { $method->() };
    like($@, qr/scope has not been established/, 'installer refuses an unscoped operation');
}
for my $pid (undef, 0, 1, '42; false') {
    eval { calamares->set_launch_scope($pid, 'openqa-calamares-valid') };
    like($@, qr/valid launch-tree PID/, 'invalid launch scope is rejected');
}
for my $token (undef, '', 'bad token', 'other-prefix-1') {
    eval { calamares->set_launch_scope(42, $token) };
    like($@, qr/valid privilege-handoff token/, 'invalid handoff token is rejected');
}
{
    my @scopes;
    local *atspi::set_widget_scope = sub { push @scopes, [$_[1], $_[2]]; };
    calamares->set_launch_scope(42, 'openqa-calamares-test-1');
    my @queries;
    my @children = (
        {pid => 101, application_index => 14},
        {pid => 303, application_index => 15},
    );
    local *atspi::assert_widget = sub {
        my ($class, $role, $labels, $timeout, %options) = @_;
        push @queries, [$options{pid}, $options{root_pid}, $options{application_index}];
        return {status => 'passed', complete => 1, widget => shift @children};
    };
    calamares->assert_page('launcher-home', 5);
    local *atspi::wait_process_handoff = sub {
        my ($class, $executable, $name, $value, $uid, $timeout) = @_;
        is($executable, '/usr/bin/calamares', 'handoff requires exact Calamares executable');
        is($name, 'DESKTOP_STARTUP_ID', 'handoff uses the forwarded startup identity');
        is($value, 'openqa-calamares-test-1', 'handoff uses the unique launch token');
        is($uid, 0, 'handoff requires the privileged installer UID');
        return {status => 'passed', pid => 303};
    };
    calamares->begin_application_transition(30);
    calamares->assert_page('installer-welcome', 5);
    is_deeply(\@queries,
        [[42, 42, undef], [303, undef, undef]],
        'Qt page uses the exact adopted PID without claiming it is a supervisor root');
    is_deeply(\@scopes, [[42, 42], [303, undef]],
        'widget scope narrows from the GTK launch group to the exact privileged Qt PID');
    local *atspi::activate_widget = sub {
        my ($class, $role, $labels, $timeout, %options) = @_;
        is($options{pid}, 303, 'installer actions use the adopted Qt PID');
        ok(!defined $options{root_pid}, 'installer actions do not widen the adopted Qt PID by group');
        is($options{application_index}, 15, 'installer actions follow the discovered Qt application slot');
        return {status => 'passed', widget => {pid => 303, application_index => 15}};
    };
    calamares->click_action(['Continue'], 5);
}
{
    package installer_scope_fixture;
    require './openqa/tests/installer_launch.pm';
}
{
    my @scopes;
    my $command;
    local *installer_scope_fixture::select_console = sub {};
    local *installer_scope_fixture::type_string = sub {};
    local *installer_scope_fixture::send_key = sub {};
    local *installer_scope_fixture::wait_serial = sub { '__OA_FIRMWARE_BIOS__' };
    local *atspi::reset_baseline = sub {};
    local *atspi::launch_command = sub {
        $command = $_[1];
        is($_[4], 'process-tree', 'first installer window must belong to launched process tree');
        return ({}, {status => 'passed', pid => 101}, '', 0, '/tmp/openqa-gui-status-1-1', 42);
    };
    local *calamares::set_launch_scope = sub { push @scopes, [$_[1], $_[2]]; };
    local *atspi::activate_widget = sub {};
    local *calamares::assert_page = sub {};
    my $transitions = 0;
    local *calamares::begin_application_transition = sub {
        is($_[1], 90, 'installer gives the privileged handoff a bounded wait');
        $transitions++;
    };
    installer_scope_fixture::run();
    like($command, qr/^env DESKTOP_STARTUP_ID=openqa-calamares-[0-9]+-[0-9]+ /,
        'installer marks the complete launch with a unique forwarded environment token');
    is($scopes[0][0], 42, 'installer registers the launcher PID');
    like($scopes[0][1], qr/^openqa-calamares-[0-9]+-[0-9]+$/,
        'installer records the same safe token used by the command');
    is($transitions, 1, 'installer performs one explicit GTK-to-Qt privilege handoff');
}
done_testing;
