use strict;
use warnings;
use Test::More;
use application_smoke;
use atspi;
no warnings 'redefine';

my $entry = {name => 'App', path => '/usr/share/applications/app.desktop'};
my (@calls, $exit, $graceful, $window, $semantics, $cleanup,
    $window_closed, $process_gone, $crashed, $capability_status);
local *application_smoke::get_var = sub {
    return 0 if $_[0] eq 'BIGLINUX_APPLICATION_SETTLE_SECONDS';
    return $_[1];
};
local *application_smoke::select_console = sub {};
local *application_smoke::save_screenshot = sub {};
local *atspi::run_command = sub {
    push @calls, ['command', @_];
    return $capability_status;
};
local *atspi::launch_desktop_entry = sub {
    push @calls, ['launch', @_];
    return ({}, {status => $window, accessible_window => 1, pid => 42,
            application_index => 7,
            window_identity => '/org/a11y/window/42'}, 'test', 0.1,
            '/tmp/openqa-gui-status-1-2', 42);
};
local *atspi::result = sub {
    push @calls, [@_];
    return {status => $semantics, coverage => 'accessible-content-present', evidence => {text_interface => 1}};
};
local *atspi::close_with_shortcut = sub {
    push @calls, ['close', @_];
    return {
        graceful_exit => $graceful,
        process_gone => $process_gone,
        window_closed => $window_closed,
        application_crashed => $crashed,
        raw_application_exit_code => $exit,
        application_exit_code => $exit,
        close_action => 'keyboard.' . ($_[5] // 'alt-f4'),
    };
};
local *atspi::cleanup = sub { push @calls, ['cleanup']; return {status => $cleanup}; };

sub reset_state {
    @calls = ();
    ($exit, $graceful, $process_gone, $window_closed, $crashed,
        $window, $semantics, $cleanup, $capability_status)
      = (0, 1, 1, 1, 0, 'passed', 'passed', 'passed', 0);
}

reset_state();
my $ok = application_smoke->check($entry, 30);
is($ok->{status}, 'passed', 'simple window/content/shortcut/exit contract passes');
is($ok->{functional_status}, 'open-close', 'reports the actual smoke scope');
is($ok->{execution_contract}, 'standard', 'unconfigured application uses standard contract');
is($ok->{screen_reader_status}, 'not-tested', 'does not claim Orca speech testing');
is($ok->{window_identity}, '/org/a11y/window/42', 'records the exact opened accessible window');
is($ok->{application_index}, 7, 'records the PID-verified AT-SPI application hint');
is($calls[0][-1], 0, 'repeated memory sampling is disabled');
is(scalar grep($_->[0] eq 'close', @calls), 1, 'sends one close operation');
ok(!grep(($_->[1] // '') eq 'audit-window', @calls), 'does not request full semantics audit');

for my $code (1, 127, 133, 139) {
    reset_state();
    $exit = $code;
    $crashed = 1 if $code == 133 || $code == 139;
    is(application_smoke->check($entry, 30)->{status}, 'failed', "nonzero exit $code fails");
}
reset_state();
$exit = undef;
is(application_smoke->check($entry, 30)->{status}, 'failed', 'missing exit status never passes');
reset_state();
$graceful = 0;
$process_gone = 0;
is(application_smoke->check($entry, 30)->{status}, 'failed', 'forced cleanup cannot satisfy close');
reset_state();
$semantics = 'inconclusive';
is(application_smoke->check($entry, 30)->{status}, 'failed', 'unreadable accessibility content blocks');
reset_state();
$window = 'failed';
is(application_smoke->check($entry, 30)->{status}, 'failed', 'no window fails');
reset_state();
$cleanup = 'failed';
is(application_smoke->check($entry, 30)->{status}, 'failed', 'failed isolation cleanup fails');

reset_state();
my $transient = {
    %$entry,
    _coverage => {
        execution_contract => 'transient-dialog',
        contract_reason => 'cancel is expected',
        contract_allowed_exit_codes => [0, 1],
        contract_requirements => [],
    },
};
$exit = 1;
my $cancelled = application_smoke->check($transient, 30);
is($cancelled->{status}, 'passed', 'transient dialog accepts its declared cancel exit');
is($cancelled->{functional_status}, 'open-cancel', 'transient dialog scope is reported');
my ($transient_close) = grep { $_->[0] eq 'close' } @calls;
is($transient_close->[7], 'process-exit', 'transient dialog still requires the process to exit');

reset_state();
my $shared = {
    %$entry,
    _coverage => {
        execution_contract => 'shared-window',
        contract_reason => 'resident service',
        contract_allowed_exit_codes => [0],
        contract_requirements => [],
    },
};
($exit, $graceful, $process_gone, $window_closed) = (undef, 0, 0, 1);
my $resident = application_smoke->check($shared, 30);
is($resident->{status}, 'passed', 'resident contract passes when the tested window closes');
is($resident->{functional_status}, 'window-closed', 'resident scope reports the window boundary');
my ($shared_close) = grep { $_->[0] eq 'close' } @calls;
is($shared_close->[7], 'window-close', 'resident contract observes the window rather than forcing process exit');
is($shared_close->[8], '/org/a11y/window/42', 'resident close tracks the exact opened window');

for my $changes (
    {window_closed => 0},
    {crashed => 1, exit => 139},
    {exit => 1},
) {
    reset_state();
    ($exit, $graceful, $process_gone, $window_closed) = (undef, 0, 0, 1);
    $window_closed = $changes->{window_closed} if exists $changes->{window_closed};
    $crashed = $changes->{crashed} if exists $changes->{crashed};
    $exit = $changes->{exit} if exists $changes->{exit};
    is(application_smoke->check($shared, 30)->{status}, 'failed',
        'resident contract still rejects missing close, crash, or disallowed observed exit');
}

reset_state();
my $capability = {
    %$entry,
    _coverage => {
        execution_contract => 'standard',
        contract_reason => 'camera required',
        contract_allowed_exit_codes => [0],
        contract_requirements => ['video-device'],
    },
};
$capability_status = 3;
my $not_applicable = application_smoke->check($capability, 30);
is($not_applicable->{status}, 'skipped', 'missing declared capability is not applicable');
is($not_applicable->{validation_mode}, 'capability-not-applicable', 'capability skip is explicit');
is(scalar grep($_->[0] eq 'launch', @calls), 0, 'missing capability never launches the application');
my ($capability_call) = grep { $_->[0] eq 'command' } @calls;
unlike($capability_call->[2], qr/\bexit\b/, 'capability probe cannot terminate the interactive login shell');

reset_state();
$capability_status = 2;
my $preflight_failed = application_smoke->check($capability, 30);
is($preflight_failed->{status}, 'failed', 'capability probe error is not disguised as absence');
is($preflight_failed->{validation_mode}, 'capability-preflight', 'probe failure is attributable');
is(scalar grep($_->[0] eq 'launch', @calls), 0, 'failed capability probe never launches the application');

reset_state();
my $custom = {
    %$entry,
    _coverage => {
        execution_contract => 'standard',
        contract_reason => 'custom bounded timings',
        contract_close_key => 'ctrl-q',
        contract_dismiss_auxiliary => JSON::PP::true,
        contract_close_timeout => 31,
        contract_content_timeout => 22,
        contract_allowed_exit_codes => [0],
        contract_requirements => [],
    },
};
is(application_smoke->check($custom, 30)->{status}, 'passed', 'valid per-application bounds pass');
my ($content_call) = grep { ($_->[1] // '') eq 'smoke-window' } @calls;
my ($custom_close) = grep { $_->[0] eq 'close' } @calls;
is($content_call->[2], 22, 'content timeout is forwarded');
is_deeply([@{$content_call}[3 .. 6]],
    ['--pid', 42, '--application-index', 7],
    'content observation reuses the PID-verified application hint');
is($custom_close->[5], 31, 'close timeout is forwarded');
is($custom_close->[6], 'ctrl-q', 'close shortcut is forwarded');
is($custom_close->[7], 'process-exit', 'standard custom contract keeps process-exit mode');
is($custom_close->[8], '/org/a11y/window/42', 'opened window identity is forwarded');
is($custom_close->[10], 7, 'close observation reuses the application hint');

reset_state();
my $bad_auxiliary = {
    %$entry,
    _coverage => {
        execution_contract => 'standard',
        contract_reason => 'invalid auxiliary flag',
        contract_dismiss_auxiliary => 'yes',
        contract_allowed_exit_codes => [0],
        contract_requirements => [],
    },
};
eval { application_smoke->check($bad_auxiliary, 30) };
like($@, qr/invalid application auxiliary-window contract/,
    'auxiliary dismissal is a typed lifecycle contract');

reset_state();
is(application_smoke->check(undef, 30)->{status}, 'skipped', 'absent optional application is not applicable');
is(scalar @calls, 0, 'absence does not launch, inspect, or kill anything');
is(application_smoke->check({terminal => 1}, 30)->{status}, 'skipped', 'CLI outside graphical smoke');
is(application_smoke->check({not_applicable_reason => 'different desktop'}, 30)->{status}, 'skipped', 'other desktop entry is not applicable');

for my $id (qw(gimp.desktop libreoffice-calc.desktop libreoffice-writer.desktop)) {
    is(application_smoke->default_close_key({path => "/usr/share/applications/$id"}),
        'ctrl-q', "$id uses its documented application Quit shortcut");
}
is(application_smoke->default_close_key({relative_path => 'org.gnome.TextEditor.desktop'}),
    'alt-f4', 'other applications keep the desktop close shortcut');
is(application_smoke->default_close_key({relative_path => 'not-libreoffice-calc.desktop'}),
    'alt-f4', 'shortcut exception does not match an unrelated desktop ID');
done_testing;
