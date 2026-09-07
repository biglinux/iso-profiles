# SPDX-License-Identifier: GPL-2.0-or-later

package application_policy;

use Mojo::Base -strict, -signatures;
use testapi ();
use JSON::PP ();

# The policy is read from the checkout rather than from a job setting.
#
# openQA indexes every job setting, and PostgreSQL refuses an index row over
# 2704 bytes: the canonical policy JSON had reached 2.7 KB, so a single new
# entry made every job in a release run fail to be created at all, with
# "index row size 2808 exceeds btree version 4 maximum 2704". A file has no
# such limit, and the checkout is already pinned by TEST_GIT_REFSPEC.
#
# Provenance is kept by the hash the scheduler computed: the same canonical
# JSON the aggregator recomputes. The canonicalisation lives in exactly one
# place - openqa/production/aggregate_policy.py - so the scheduler, this
# reader and the aggregator cannot drift apart.
sub load ($class) {
    my $casedir = testapi::get_var('CASEDIR', '/workspace');
    my $policy_path = "$casedir/openqa/application-policy.yaml";
    my $reader_path = "$casedir/openqa/production/aggregate_policy.py";
    die "the application policy is missing at $policy_path" unless -f $policy_path;
    die "the policy reader is missing at $reader_path" unless -f $reader_path;

    my @command = ('python3', $reader_path, $policy_path);
    open my $stream, '-|', @command
      or die "could not run the policy reader: $!";
    my $canonical = do { local $/; <$stream> };
    close $stream;
    die 'the policy reader failed' if $? != 0 || !defined $canonical || $canonical eq '';
    chomp $canonical;

    my $expected = testapi::get_var('BIGLINUX_APPLICATION_POLICY_HASH', '');
    die 'BIGLINUX_APPLICATION_POLICY_HASH is required to verify the policy'
      if $expected eq '';
    require Digest::SHA;
    my $actual = Digest::SHA::sha256_hex($canonical);
    die "the application policy in $casedir does not match the scheduled hash: "
      . "expected $expected, read $actual"
      unless $actual eq $expected;

    my $policy = eval { JSON::PP::decode_json($canonical) };
    die "the application policy is not valid JSON: $@" unless ref $policy eq 'HASH';
    return $policy;
}

1;
