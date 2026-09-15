use strict;
use warnings;
use Test::More;
use atspi;
use calamares;
no warnings qw(redefine once);

for my $method (sub { calamares->assert_page('launcher-home', 5) },
                sub { calamares->click_action(['Continue'], 5) }) {
    eval { $method->() };
    like($@, qr/scope has not been established/, 'installer refuses an unscoped operation');
}
for my $pid (undef, 0, 1, '42; false') {
    eval { calamares->set_launch_scope($pid) };
    like($@, qr/valid launch-tree PID/, 'invalid launch scope is rejected');
}
{
    my @scopes;
    local *atspi::set_widget_scope = sub { push @scopes, $_[1]; };
    calamares->set_launch_scope(42);
    my @queries;
    my @children = (
        {pid => 101, application_index => 14},
        {pid => 202, application_index => 15},
    );
    local *atspi::assert_widget = sub {
        my ($class, $role, $labels, $timeout, %options) = @_;
        push @queries, [$options{pid}, $options{application_index}];
        return {status => 'passed', complete => 1, widget => shift @children};
    };
    calamares->assert_page('launcher-home', 5);
    calamares->assert_page('installer-welcome', 5);
    is_deeply(\@queries, [[42, undef], [42, 14]],
        'Qt page lookup reuses the GTK application slot as a bounded hint within the launch tree');
    is_deeply(\@scopes, [42], 'page discovery never switches to a transient child PID');
    local *atspi::activate_widget = sub {
        my ($class, $role, $labels, $timeout, %options) = @_;
        is($options{pid}, 42, 'installer actions retain explicit launch provenance');
        is($options{application_index}, 15, 'installer actions follow the newly discovered Qt application slot');
        return {status => 'passed', widget => {pid => 202, application_index => 15}};
    };
    calamares->click_action(['Continue'], 5);
}
{
    package installer_scope_fixture;
    require './openqa/tests/installer_launch.pm';
}
{
    my @queries;
    local *installer_scope_fixture::select_console = sub {};
    local *installer_scope_fixture::type_string = sub {};
    local *installer_scope_fixture::send_key = sub {};
    local *installer_scope_fixture::wait_serial = sub { '__OA_FIRMWARE_BIOS__' };
    local *atspi::reset_baseline = sub {};
    local *atspi::launch_command = sub {
        is($_[4], 'process-tree', 'first installer window must belong to launched process tree');
        return ({}, {status => 'passed', pid => 101}, '', 0, '/tmp/openqa-gui-status-1-1', 42);
    };
    local *atspi::set_widget_scope = sub { push @queries, $_[1]; };
    local *atspi::activate_widget = sub {};
    local *calamares::assert_page = sub {};
    installer_scope_fixture::run();
    is_deeply(\@queries, [42], 'installer registers the launcher PID, not first child window');
}
done_testing;
