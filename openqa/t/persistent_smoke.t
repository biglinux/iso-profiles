use strict;
use warnings;
use Test::More;
use JSON::PP qw(encode_json);
use atspi;
no warnings 'redefine';

my $entry = {path => '/usr/share/applications/app.desktop'};
my (@keys, @typed, @serial, @scopes);
local *atspi::_start_argv = sub {
    return (
        {status => 'passed', window_count => 1, mem_available_mib => 100, desktop => 'KDE'},
        '/tmp/openqa-gui-status-1-2', 42, undef, 100,
    );
};
local *atspi::select_console = sub {};
local *atspi::type_string = sub { push @typed, $_[0]; };
local *atspi::send_key = sub { push @keys, $_[0]; };
local *atspi::wait_serial = sub { return shift @serial; };
local *atspi::_read_exit_code = sub { return 0; };
local *atspi::set_widget_scope = sub { push @scopes, [@_]; };

sub encoded {
    return unpack 'H*', encode_json($_[0]);
}

my $ready = encoded({
    status => 'passed', phase => 'ready', pid => 77,
    application => 'App', window => 'App', role => 'frame',
    accessible_children => 1, application_index => 9,
    window_identity => '/org/a11y/window/77', active => 1,
    coverage => 'accessible-content-present', evidence => {text_interface => 1},
    open_seconds => 1.2, mem_available_mib => 90,
    memory => {process_count => 1},
});
my $closed = encoded({
    status => 'passed', phase => 'closed', pid => 77,
    application => 'App', window => 'App', role => 'frame',
    accessible_children => 1, application_index => 9,
    window_identity => '/org/a11y/window/77', active => 1,
    coverage => 'accessible-content-present', evidence => {text_interface => 1},
    open_seconds => 1.2, mem_available_mib => 90,
    memory => {process_count => 1}, process_gone => 1,
    window_closed => 1, graceful_exit => 1,
});
@serial = (
    "__OPENQA_ATSPI_READY__${ready}\n",
    "__OPENQA_ATSPI__${closed}\n__OPENQA_ATSPI_DONE__\n",
);
my (undef, $result, $method, undef, undef, $launch_pid) =
  atspi->launch_smoke_desktop_entry(
      $entry, 30, 2, 10, 15, 'alt-f4', 'process-exit');
is($result->{status}, 'passed', 'persistent session returns the observed close result');
is($result->{application_exit_code}, 0, 'supervisor exit status is attached');
is($result->{close_action}, 'keyboard.alt-f4', 'normal keyboard request is recorded');
is($method, 'serial-console-persistent-atspi-smoke', 'persistent validation mode is explicit');
is($launch_pid, 42, 'supervised root PID is retained');
is_deeply(\@keys, ['ret', 'alt-f4'], 'one shell return and exactly one close shortcut are sent');
like($typed[0], qr/smoke-session/, 'guest runs the persistent smoke operation');
like($typed[0], qr/'--root-pid'\s+'42'/, 'supervisor ownership is passed to the probe');
like($typed[0], qr/'--content-timeout'\s+'10'/, 'content budget is passed separately');
like($typed[0], qr/'--close-mode'\s+'process-exit'/, 'lifecycle expectation is passed separately');
is_deeply($scopes[0], ['atspi', 77, 42], 'readiness narrows later widget scope to the proven PID');

@keys = (); @typed = (); @scopes = ();
my $early = encoded({
    status => 'failed', phase => 'content', pid => 77,
    error => 'no content witness',
});
@serial = ("__OPENQA_ATSPI__${early}\n__OPENQA_ATSPI_DONE__\n");
my (undef, $failed) = atspi->launch_smoke_desktop_entry(
    $entry, 30, 2, 10, 15, 'alt-f4', 'process-exit');
is($failed->{status}, 'failed', 'failure before readiness is returned');
is_deeply(\@keys, ['ret'], 'no SUT keyboard input is sent without active accessible content');

for my $bad (
    [0, 2, 10, 15, 'alt-f4', 'process-exit'],
    [30, 11, 10, 15, 'alt-f4', 'process-exit'],
    [30, 2, 0, 15, 'alt-f4', 'process-exit'],
    [30, 2, 10, 0, 'alt-f4', 'process-exit'],
    [30, 2, 10, 15, 'bad', 'process-exit'],
    [30, 2, 10, 15, 'alt-f4', 'guess'],
) {
    eval { atspi->launch_smoke_desktop_entry($entry, @$bad) };
    ok($@, 'invalid persistent smoke contract is rejected before guest input');
}

done_testing;
