# SPDX-License-Identifier: GPL-2.0-or-later
package orca;

# Orca runs through the whole desktop part of a plan, and each tested window or
# screen has to make it speak. data/orca_probe.py records what Orca sends to
# speech-dispatcher; what it says is not judged, only that it said something
# and speech-dispatcher accepted it.

use Mojo::Base -strict;
use testapi;
use atspi;

my $active = 0;

sub _probe {
    my ($operation, $timeout, @arguments) = @_;
    return atspi->guest_json(
        ['python3', $atspi::orca_probe_path, $operation, '--timeout', $timeout, @arguments],
        $timeout, "Orca observation '$operation'");
}

# After atspi->install, in the session the tests use. Replaces any Orca already
# running, so the one observed is the one speaking.
sub start {
    my $started = _probe('start', 30);
    die 'Orca could not be started for the session: ' . ($started->{error} // 'no answer')
      unless ($started->{status} // '') eq 'passed';
    $active = 1;
    record_info 'Orca', 'Orca runs for the session; every tested window has to make it speak';
}

sub active {
    return $active;
}

# The speech-log position before an action; check() looks only after it.
sub mark {
    my $offset = _probe('offset', 10)->{offset};
    die 'Orca observation returned no speech offset'
      unless defined $offset && $offset =~ /\A[0-9]+\z/;
    return $offset;
}

sub check {
    my ($class, $since, $what, %options) = @_;
    my @arguments = ('--since', $since);
    push @arguments, ('--phrase', $options{phrase}) if defined $options{phrase};
    my $spoke = _probe('check', $options{timeout} // 15, @arguments);
    die "Orca did not speak for $what: " . ($spoke->{error} // 'no answer')
      unless ($spoke->{status} // '') eq 'passed';
    return $spoke;
}

1;
