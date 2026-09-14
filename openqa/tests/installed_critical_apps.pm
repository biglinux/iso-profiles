# SPDX-License-Identifier: GPL-2.0-or-later
use Mojo::Base 'basetest';
use testapi;
use atspi;
use application_policy;
use application_smoke;
use JSON::PP qw(encode_json);

sub test_flags { return {fatal => 0}; }

sub run {
    atspi->reset_baseline;
    my %entries = map { $_->{relative_path} => $_ } @{atspi->inventory};
    my $policy = application_policy->load;
    die 'invalid application selection' unless ref $policy->{critical} eq 'ARRAY';
    my @results;
    for my $item (@{$policy->{critical}}) {
        my $id = $item->{desktop_id};
        die 'invalid selected desktop ID' unless defined $id && $id =~ /\A[^\r\n]+\.desktop\z/;
        my $result = application_smoke->check($entries{$id}, 60);
        $result->{desktop_id} = $id;
        push @results, $result;
        atspi->record_guest_info("Installed application: $id", encode_json($result));
    }
    open my $file, '>:raw', 'testresults/installed-application-smoke.json'
      or die "cannot create installed application report: $!";
    print {$file} encode_json({schema_version => 1, scope => 'application smoke', applications => \@results});
    close $file or die "cannot finish installed application report: $!";
    die 'installed application smoke failures; see installed-application-smoke.json'
      if grep { $_->{status} eq 'failed' } @results;
}

1;
