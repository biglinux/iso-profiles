use strict;
use warnings;
use Test::More;
use JSON::PP ();
use atspi;
no warnings 'redefine';

my (@keys, @operations, @active_responses, $active, $code, $wait, $wait_close);
($active, $code, $wait, $wait_close) = (1, 0, 0, 1);
local *atspi::result = sub {
    my ($class, $operation, @arguments) = @_;
    push @operations, [$operation, @arguments];
    return @active_responses ? shift @active_responses
      : {status => 'passed', active => $active, pid => 42}
      if $operation eq 'active-window';
    return $wait_close
      ? {status => 'passed', accessible_window => 1, process_gone => 0}
      : {status => 'failed', accessible_window => undef, error => 'window remains'}
      if $operation eq 'wait-close';
    die "unexpected operation $operation";
};
local *atspi::select_console = sub {};
local *atspi::send_key = sub { push @keys, $_[0]; };
local *atspi::run_command = sub { return $wait; };
local *atspi::_read_exit_code = sub { return $code; };
local *atspi::_kill_process_groups = sub { die 'unexpected forced close'; };
my $path = '/tmp/openqa-gui-status-1-2';

my $closed = atspi->close_with_shortcut(42, $path, 42, 15);
is_deeply(\@keys, ['alt-f4'], 'one standard close shortcut and no internal actions');
ok($closed->{graceful_exit}, 'normal process exit observed');
ok($closed->{window_closed}, 'process exit also closes the standard window');
is($closed->{raw_application_exit_code}, 0, 'returns supervisor exit status');

($wait, $code, $wait_close) = (0, 0, 1);
@keys = (); @operations = ();
my $indexed = atspi->close_with_shortcut(
    42, $path, 42, 15, 'alt-f4', 'process-exit',
    '/org/a11y/window/42', 0, 7);
my ($indexed_active) = grep { $_->[0] eq 'active-window' } @operations;
is_deeply([@{$indexed_active}[2 .. 5]],
    ['--pid', 42, '--application-index', 7],
    'active-window observation reuses the PID-verified application hint');
ok($indexed->{graceful_exit}, 'indexed close keeps the strict exit contract');

$code = 139;
ok(atspi->close_with_shortcut(42, $path, 42, 15)->{application_crashed}, 'segfault is diagnosed');
$wait = 1;
ok(!atspi->close_with_shortcut(42, $path, 42, 15)->{graceful_exit}, 'running process is not graceful exit');

($wait, $code, $wait_close) = (1, undef, 1);
@keys = (); @operations = ();
my $runner = atspi->close_with_shortcut(
    42, $path, 42, 15, 'esc', 'window-close', '/org/a11y/krunner');
is_deeply(\@keys, ['esc'], 'resident runner receives its documented Escape shortcut');
ok($runner->{window_closed}, 'Escape proves the scoped runner window disappeared');
is($runner->{close_action}, 'keyboard.esc', 'Escape evidence is reported canonically');

($wait, $code, $wait_close) = (1, undef, 1);
@keys = (); @operations = ();
my $resident = atspi->close_with_shortcut(
    42, $path, 42, 17, 'ctrl-q', 'window-close', '/org/a11y/window/42');
is_deeply(\@keys, ['ctrl-q'], 'resident window receives exactly one configured shortcut');
ok($resident->{window_closed}, 'resident window disappearance is observed');
ok(!$resident->{process_gone}, 'resident process may remain');
ok(!$resident->{graceful_exit}, 'process liveness is not mislabeled as exit');
is($operations[1][0], 'wait-close', 'window-close mode observes disappearance through AT-SPI');
is($operations[1][1], 17, 'window-close uses the configured bound');
is_deeply([@{$operations[1]}[2 .. 5]],
    ['--pid', 42, '--window-identity', '/org/a11y/window/42'],
    'window-close scopes disappearance to the opened accessible object');

($wait, $code, $wait_close) = (1, undef, 1);
@keys = (); @operations = ();
@active_responses = (
    {status => 'passed', active => 1, pid => 42, window_role => 'dialog',
        window_identity => '/org/a11y/welcome', application_window_count => 2},
    {status => 'passed', active => 1, pid => 42, window_role => 'frame',
        window_identity => '/org/a11y/main', application_window_count => 1},
);
my $welcomed = atspi->close_with_shortcut(
    42, $path, 42, 17, 'ctrl-q', 'window-close', '/org/a11y/welcome', 1);
is_deeply(\@keys, ['alt-f4', 'ctrl-q'],
    'one explicit first-run surface is dismissed before application Quit');
is($welcomed->{pre_close_action}, 'keyboard.alt-f4',
    'auxiliary dismissal is reported separately');
my ($scoped_wait) = grep { $_->[0] eq 'wait-close' } @operations;
is_deeply([@{$scoped_wait}[2 .. 5]],
    ['--pid', 42, '--window-identity', '/org/a11y/main'],
    'shared-window close follows the main window after the welcome surface');

($wait, $code, $wait_close) = (0, 0, 1);
@keys = (); @operations = (); @active_responses = (
    {status => 'passed', active => 1, pid => 42, window_role => 'dialog',
        window_identity => '/org/a11y/unconfigured', application_window_count => 2},
);
my $ordinary_ctrl_q = atspi->close_with_shortcut(
    42, $path, 42, 15, 'ctrl-q', 'process-exit', undef, 0);
is_deeply(\@keys, ['ctrl-q'],
    'unconfigured Ctrl+Q never receives a guessed preliminary close');
ok(!defined $ordinary_ctrl_q->{pre_close_action},
    'no auxiliary action is reported without the explicit contract');

($wait, $code, $wait_close) = (1, undef, 0);
ok(!atspi->close_with_shortcut(42, $path, 42, 15, 'alt-f4', 'window-close')->{window_closed},
    'resident contract does not invent window disappearance');
($wait, $code, $wait_close) = (0, 139, 1);
ok(atspi->close_with_shortcut(42, $path, 42, 15, 'alt-f4', 'window-close')->{application_crashed},
    'resident process crash remains visible');

($wait, $code, $wait_close) = (0, 0, 0);
my $exited = atspi->close_with_shortcut(
    42, $path, 42, 15, 'alt-f4', 'window-close', '/org/a11y/window/42');
ok($exited->{process_gone}, 'shared process exit is observed');
ok($exited->{window_closed}, 'process exit proves that its tested window is gone');

$active = 0; @keys = ();
eval { atspi->close_with_shortcut(42, $path, 42, 15) };
like($@, qr/inactive/, 'inactive application cannot be closed blindly');
is(scalar @keys, 0, 'no shortcut sent to an unrelated window');
eval { atspi->close_with_shortcut(42, $path, 42, 15, 'bad-key') };
like($@, qr/invalid close shortcut/, 'shortcut is validated');
eval { atspi->close_with_shortcut(42, $path, 42, 15, 'alt-f4', 'guess') };
like($@, qr/invalid close observation mode/, 'lifecycle observation mode is validated');
eval { atspi->close_with_shortcut(
    42, $path, 42, 15, 'alt-f4', 'process-exit', undef, 1) };
like($@, qr/requires Ctrl\+Q/,
    'auxiliary dismissal cannot be inferred for another close shortcut');
eval { atspi->close_with_shortcut(
    42, $path, 42, 15, 'ctrl-q', 'process-exit', undef, 2) };
like($@, qr/invalid auxiliary-window dismissal/,
    'auxiliary dismissal is a boolean contract');
done_testing;
