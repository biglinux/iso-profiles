use strict;
use warnings;
use Test::More;
use JSON::PP qw(encode_json);
use atspi;
no warnings 'redefine';

{
    my $typed;
    local *atspi::select_console = sub {};
    local *atspi::type_string = sub { $typed = $_[0]; };
    local *atspi::send_key = sub {};
    local *atspi::wait_serial = sub {
        my $hex = unpack 'H*', encode_json({
            status => 'passed', pid => 4321, uid => 0,
            executable => '/usr/bin/calamares', start_time => 99,
        });
        return "__OPENQA_PROCESS__${hex}\n__OPENQA_PROCESS_DONE__\n";
    };
    my $result = atspi->wait_process_handoff(
        '/usr/bin/calamares', 'DESKTOP_STARTUP_ID',
        'openqa-calamares-test-1', 0, 90,
    );
    is($result->{pid}, 4321, 'exact privileged process PID is returned');
    like($typed, qr/sudo/, 'handoff observer runs with the privilege needed for root proc metadata');
    like($typed, qr/openqa-process-handoff\.py/, 'reviewed handoff helper is used');
    like($typed, qr/DESKTOP_STARTUP_ID/, 'environment identity is part of the query');
    like($typed, qr/openqa-calamares-test-1/, 'unique launch token is part of the query');
}
{
    local *atspi::select_console = sub {};
    local *atspi::type_string = sub {};
    local *atspi::send_key = sub {};
    local *atspi::wait_serial = sub {
        my $hex = unpack 'H*', encode_json({
            status => 'failed', reason => 'not-found', error => 'no exact process',
        });
        return "__OPENQA_PROCESS__${hex}\n__OPENQA_PROCESS_DONE__\n";
    };
    my $result = atspi->wait_process_handoff(
        '/usr/bin/calamares', 'DESKTOP_STARTUP_ID',
        'openqa-calamares-test-2', 0, 30,
    );
    is($result->{status}, 'failed', 'semantic absence is returned rather than fabricated success');
}
for my $case (
    ['/relative', 'BAD-NAME', 'openqa-calamares-good', 0, 30],
    ['/usr/bin/calamares', 'DESKTOP_STARTUP_ID', 'bad token', 0, 30],
    ['/usr/bin/calamares', 'DESKTOP_STARTUP_ID', 'openqa-calamares-good', -1, 30],
    ['/usr/bin/calamares', 'DESKTOP_STARTUP_ID', 'openqa-calamares-good', 0, 0],
) {
    my ($path, $name, $value, $uid, $timeout) = @$case;
    eval { atspi->wait_process_handoff($path, $name, $value, $uid, $timeout) };
    ok($@, 'invalid handoff selector is rejected before reaching the guest');
}
{
    local *atspi::select_console = sub {};
    local *atspi::type_string = sub {};
    local *atspi::send_key = sub {};
    local *atspi::wait_serial = sub { '__OPENQA_PROCESS_DONE__' };
    eval {
        atspi->wait_process_handoff(
            '/usr/bin/calamares', 'DESKTOP_STARTUP_ID',
            'openqa-calamares-test-3', 0, 30,
        );
    };
    like($@, qr/no machine-readable record/, 'sudo/helper failure cannot pass without a record');
}
done_testing;
