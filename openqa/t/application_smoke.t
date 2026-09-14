use strict;
use warnings;
use Test::More;
use application_smoke;
use atspi;
no warnings 'redefine';

my $entry = {name => 'App', path => '/usr/share/applications/app.desktop'};
my (@calls, $exit, $graceful, $window, $semantics, $cleanup);
local *application_smoke::get_var = sub { return $_[0] eq 'BIGLINUX_APPLICATION_SETTLE_SECONDS' ? 0 : $_[1]; };
local *application_smoke::select_console = sub {};
local *application_smoke::save_screenshot = sub {};
local *atspi::launch_desktop_entry = sub {
    push @calls, ['launch', @_];
    return ({}, {status => $window, accessible_window => 1, pid => 42}, 'test', 0.1,
            '/tmp/openqa-gui-status-1-2', 42);
};
local *atspi::result = sub {
    push @calls, [@_];
    return {status => $semantics, coverage => 'accessible-content-present', evidence => {text_interface => 1}};
};
local *atspi::close_with_shortcut = sub {
    push @calls, ['close', @_];
    return {graceful_exit => $graceful, raw_application_exit_code => $exit, close_action => 'keyboard.alt-f4'};
};
local *atspi::cleanup = sub { push @calls, ['cleanup']; return {status => $cleanup}; };

($exit, $graceful, $window, $semantics, $cleanup) = (0, 1, 'passed', 'passed', 'passed');
my $ok = application_smoke->check($entry, 30);
is($ok->{status}, 'passed', 'simple window/content/shortcut/exit contract passes');
is($ok->{functional_status}, 'open-close', 'reports the actual smoke scope');
is($ok->{screen_reader_status}, 'not-tested', 'does not claim Orca speech testing');
is($calls[0][-1], 0, 'repeated memory sampling is disabled');
is(scalar grep($_->[0] eq 'close', @calls), 1, 'sends one close operation');
ok(!grep(($_->[1] // '') eq 'audit-window', @calls), 'does not request full semantics audit');
for my $code (1, 127, 133, 139) {
    $exit = $code;
    is(application_smoke->check($entry, 30)->{status}, 'failed', "nonzero exit $code fails");
}
$exit = undef;
is(application_smoke->check($entry, 30)->{status}, 'failed', 'missing exit status never passes');
$exit = 0; $graceful = 0;
is(application_smoke->check($entry, 30)->{status}, 'failed', 'forced cleanup cannot satisfy close');
$graceful = 1; $semantics = 'inconclusive';
is(application_smoke->check($entry, 30)->{status}, 'failed', 'unreadable accessibility content blocks');
$semantics = 'passed'; $window = 'failed';
is(application_smoke->check($entry, 30)->{status}, 'failed', 'no window fails');
$window = 'passed'; $cleanup = 'failed';
is(application_smoke->check($entry, 30)->{status}, 'failed', 'failed isolation cleanup fails');
@calls = ();
is(application_smoke->check(undef, 30)->{status}, 'skipped', 'absent optional application is not applicable');
is(scalar @calls, 0, 'absence does not launch, inspect, or kill anything');
is(application_smoke->check({terminal => 1}, 30)->{status}, 'skipped', 'CLI outside graphical smoke');
is(application_smoke->check({not_applicable_reason => 'different desktop'}, 30)->{status}, 'skipped', 'other desktop entry is not applicable');

done_testing;
