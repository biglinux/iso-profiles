use strict;
use warnings;
use Test::More;
use atspi;
no warnings 'redefine';

my (@keys, @operations, $active, $code, $wait, $wait_close);
($active, $code, $wait, $wait_close) = (1, 0, 0, 1);
local *atspi::result = sub {
    my ($class, $operation, @arguments) = @_;
    push @operations, [$operation, @arguments];
    return {status => 'passed', active => $active, pid => 42}
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

$code = 139;
ok(atspi->close_with_shortcut(42, $path, 42, 15)->{application_crashed}, 'segfault is diagnosed');
$wait = 1;
ok(!atspi->close_with_shortcut(42, $path, 42, 15)->{graceful_exit}, 'running process is not graceful exit');

($wait, $code, $wait_close) = (1, undef, 1);
@keys = (); @operations = ();
my $resident = atspi->close_with_shortcut(42, $path, 42, 17, 'ctrl-q', 'window-close');
is_deeply(\@keys, ['ctrl-q'], 'resident window receives exactly one configured shortcut');
ok($resident->{window_closed}, 'resident window disappearance is observed');
ok(!$resident->{process_gone}, 'resident process may remain');
ok(!$resident->{graceful_exit}, 'process liveness is not mislabeled as exit');
is($operations[1][0], 'wait-close', 'window-close mode observes disappearance through AT-SPI');
is($operations[1][1], 17, 'window-close uses the configured bound');

$wait_close = 0;
ok(!atspi->close_with_shortcut(42, $path, 42, 15, 'alt-f4', 'window-close')->{window_closed},
    'resident contract does not invent window disappearance');
($wait, $code, $wait_close) = (0, 139, 1);
ok(atspi->close_with_shortcut(42, $path, 42, 15, 'alt-f4', 'window-close')->{application_crashed},
    'resident process crash remains visible');

$active = 0; @keys = ();
eval { atspi->close_with_shortcut(42, $path, 42, 15) };
like($@, qr/inactive/, 'inactive application cannot be closed blindly');
is(scalar @keys, 0, 'no shortcut sent to an unrelated window');
eval { atspi->close_with_shortcut(42, $path, 42, 15, 'bad-key') };
like($@, qr/invalid close shortcut/, 'shortcut is validated');
eval { atspi->close_with_shortcut(42, $path, 42, 15, 'alt-f4', 'guess') };
like($@, qr/invalid close observation mode/, 'lifecycle observation mode is validated');
done_testing;
