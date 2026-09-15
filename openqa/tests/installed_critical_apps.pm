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
    die 'application policy version must be 2'
      unless $policy->{version} && $policy->{version} == 2;
    die 'invalid application selection' unless ref $policy->{critical} eq 'ARRAY';
    die 'invalid application contracts' unless ref($policy->{contracts} // []) eq 'ARRAY';
    my %contracts;
    for my $contract (@{$policy->{contracts} // []}) {
        die 'invalid selected application contract'
          unless ref $contract eq 'HASH'
          && defined $contract->{desktop_id}
          && $contract->{desktop_id} =~ /\A[^\r\n]+\.desktop\z/;
        die 'duplicate selected application contract'
          if exists $contracts{$contract->{desktop_id}};
        $contracts{$contract->{desktop_id}} = $contract;
    }
    my @results;
    for my $item (@{$policy->{critical}}) {
        my $id = $item->{desktop_id};
        die 'invalid selected desktop ID' unless defined $id && $id =~ /\A[^\r\n]+\.desktop\z/;
        my $entry = $entries{$id};
        if (defined $entry) {
            my $contract = $contracts{$id} // {};
            $entry->{_coverage} = {
                execution_contract => $contract->{kind} // 'standard',
                contract_reason => $contract->{reason} // 'Default strict graphical application contract',
                contract_close_key => $contract->{close_key},
                contract_close_timeout => $contract->{close_timeout},
                contract_content_timeout => $contract->{content_timeout},
                contract_allowed_exit_codes => $contract->{allowed_exit_codes}
                  // (($contract->{kind} // '') eq 'transient-dialog' ? [0, 1] : [0]),
                contract_requirements => $contract->{requires} // [],
            };
        }
        my $result = application_smoke->check($entry, 60);
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
