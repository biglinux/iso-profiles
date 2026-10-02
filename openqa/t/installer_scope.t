# SPDX-License-Identifier: GPL-2.0-or-later
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
{
    my ($role, $labels) = calamares->page_anchor('installer-welcome');
    is($role, 'label|heading|static',
        'installer welcome remains a semantic text anchor');
    ok((grep { $_ eq 'Welcome to the BigLinux installer' } @{$labels}),
        'BigLinux branded welcome heading is accepted');
    ok((grep { $_ eq 'Welcome to the BigCommunity installer' } @{$labels}),
        'BigCommunity branded welcome heading is accepted');
    ok((grep { $_ eq 'Welcome to the XivaStudio installer' } @{$labels}),
        'XivaStudio branded welcome heading is accepted');
    ok(!(grep { $_ eq 'Welcome to the Calamares installer' } @{$labels}),
        'obsolete unbranded heading is not the sole assumed page identity');
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
        push @queries, [
            $options{pid}, $options{root_pid}, $options{application_index},
            $options{positive_witness} // 0,
            $options{startup_timeout_ms},
        ];
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
        [[42, 42, undef, 0, undef], [303, undef, undef, 1, 5000]],
        'Qt page uses an exact positive witness and bounded startup grace on the adopted PID');
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

{
    my (@commands, @uploads, @records);
    local *atspi::set_widget_scope = sub {};
    calamares->set_launch_scope(42, 'openqa-calamares-diagnostics-1');
    local *atspi::wait_process_handoff = sub {
        return {status => 'passed', pid => 303};
    };
    calamares->begin_application_transition(5);
    local *atspi::run_command = sub {
        push @commands, $_[1];
        return 0;
    };
    local *atspi::upload_guest_file = sub {
        push @uploads, [$_[1], $_[2]];
        return 0;
    };
    local *calamares::record_info = sub {
        push @records, [$_[0], $_[1]];
    };
    local *calamares::select_console = sub {};
    ok(calamares->collect_launch_failure_evidence,
        'Calamares failure evidence collection is best effort');
    is(scalar @commands, 3, 'process, privileged session and runtime state diagnostics are attempted');
    like($commands[1], qr{^\(umask 077; tmp=\$\(mktemp /tmp/openqa-calamares-session\.XXXXXX\)},
        'live-user shell creates a private unique temporary log');
    like($commands[1], qr{exec head -c 33554432 -- "\$src"; else exit 1; fi' >"\$tmp"},
        'privileged reader writes only to stdout, with a hard size cap');
    unlike($commands[1], qr{chown|dst=},
        'privileged reader never opens or changes ownership of a temporary destination');
    like($commands[1], qr{&& mv -fT -- "\$tmp" /tmp/openqa-calamares-session\.log\)$},
        'live user installs the diagnostic only after successful reading');
    unlike(join("\n", @commands), qr{/proc/[0-9]+/environ|ps .*args},
        'diagnostics do not dump process arguments or full environments');
    is_deeply(
        [map { $_->[1] } @uploads],
        [qw(calamares-processes.txt calamares-gui-launch.log calamares-session.log calamares-runtime-state.txt)],
        'bounded installer diagnostics use stable upload names');
    like($records[0][1], qr/"launch_pid":42/, 'diagnostic scope records the launcher PID');
    like($records[0][1], qr/"application_pid":303/, 'diagnostic scope records the adopted Qt PID');
    like($records[0][1], qr/"handoff_token_present":true/, 'diagnostics record token presence without leaking the token');
}
{
    my (@commands, @uploads);
    local *calamares::record_info = sub {};
    local *calamares::select_console = sub {};
    local *atspi::run_command = sub {
        push @commands, $_[1];
        return @commands == 2 ? 1 : 0;
    };
    local *atspi::upload_guest_file = sub { push @uploads, $_[2]; return 0; };
    ok(calamares->collect_launch_failure_evidence,
        'an unavailable privileged log cannot replace the original failure');
    ok(!(grep { $_ eq 'calamares-session.log' } @uploads),
        'failed copying never uploads a stale privileged log');
    is(scalar @commands, 3, 'remaining diagnostics continue after a failed log copy');
}

{
    my ($collected, $screenshots, $sut);
    local *calamares::collect_launch_failure_evidence = sub { $collected++; return 1; };
    local *installer_scope_fixture::select_console = sub { $sut++ if $_[0] eq 'sut'; };
    local *installer_scope_fixture::save_screenshot = sub { $screenshots++; };
    installer_scope_fixture::post_fail_hook();
    is($collected, 1, 'installer failure hook collects semantic diagnostics once');
    is($screenshots, 1, 'installer failure hook keeps one diagnostic screenshot');
    is($sut, 1, 'installer failure hook restores the graphical console');
}
done_testing;
