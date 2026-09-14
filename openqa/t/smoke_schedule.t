use strict;
use warnings;
use Test::More;
use testapi;
BEGIN { $INC{'autotest.pm'} = 1; $INC{'biglinux.pm'} = 1; }
no warnings qw(redefine once);
my @loaded;
local *autotest::loadtest = sub { push @loaded, $_[0]; };
local *biglinux::new = sub { return bless {}, 'biglinux'; };
local *testapi::set_distribution = sub {};
for my $schedule (qw(installer release release_uefi)) {
    for my $deep (0, 1) {
        @loaded = ();
        local *testapi::get_var = sub {
            return $schedule if $_[0] eq 'BIGLINUX_SCHEDULE';
            return $deep if $_[0] eq 'BIGLINUX_DEEP_APPLICATION_TESTS';
            return $_[1];
        };
        my $ok = do './openqa/main.pm';
        die $@ || $! unless $ok;
        is(scalar grep(/nonvisual_tasks/, @loaded), $deep, "$schedule deep tasks require explicit opt-in=$deep");
        is(scalar grep(/installed_brave/, @loaded), $deep, "$schedule extra Brave test is optional=$deep");
        ok(scalar(grep(/installed_critical_apps/, @loaded)), 'default installed application smoke remains scheduled');
    }
}
done_testing;
