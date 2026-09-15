use strict;
use warnings;
use Test::More;
use atspi;
no warnings 'redefine';

my (@killed, @commands, $probe_result, $probe_die, $owned_status);
local *atspi::select_console = sub {};
local *atspi::_kill_process_groups = sub { @killed = @_; return 0; };
local *atspi::_run_guest_command = sub { push @commands, [@_]; return $owned_status; };
local *atspi::result = sub {
    die $probe_die if $probe_die;
    return $probe_result;
};

sub reset_state {
    @killed = ();
    @commands = ();
    $probe_result = {status => 'passed'};
    $probe_die = '';
    $owned_status = 0;
}

reset_state();
my $clean = atspi->cleanup(5, 42, 43, 42);
is($clean->{status}, 'passed', 'complete global cleanup passes');
is_deeply([sort {$a <=> $b} @killed], [42, 43], 'owned process IDs are de-duplicated');
like($commands[0][0], qr{/proc/42}, 'owned process termination is verified');
like($commands[0][0], qr{/proc/43}, 'every owned process is verified');

reset_state();
$probe_result = {status => 'inconclusive', complete => 0, error => 'stale unrelated provider'};
my $degraded = atspi->cleanup(5, 42);
is($degraded->{status}, 'passed', 'unrelated incomplete global scan does not revoke proven isolation');
ok($degraded->{degraded}, 'degraded isolation is explicit');
is($degraded->{warning}, 'stale unrelated provider', 'infrastructure warning is preserved');

reset_state();
$probe_result = {status => 'failed', error => 'new window remained'};
is(atspi->cleanup(5, 42)->{status}, 'failed', 'actual remaining windows still fail cleanup');

reset_state();
$owned_status = 1;
$probe_result = {status => 'inconclusive', error => 'registry unavailable'};
my $owned_failed = atspi->cleanup(5, 42);
is($owned_failed->{status}, 'failed', 'unverified owned-process cleanup cannot pass');
like($owned_failed->{error}, qr/owned application processes remained/, 'owned isolation failure is attributable');

reset_state();
$probe_die = 'probe transport failed';
my $transport = atspi->cleanup(5, 42);
is($transport->{status}, 'passed', 'owned-process proof survives unrelated probe transport failure');
ok($transport->{degraded}, 'transport fallback is marked degraded');
like($transport->{warning}, qr/probe transport failed/, 'transport error is retained');

done_testing;
