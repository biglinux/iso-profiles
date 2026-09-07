# SPDX-License-Identifier: GPL-2.0-or-later

package application_policy;

use Mojo::Base -strict, -signatures;
use testapi ();
use JSON::PP ();
use Encode ();

# The policy is read from the checkout rather than from a job setting.
#
# openQA indexes every job setting, and PostgreSQL refuses an index row over
# 2704 bytes: the canonical policy JSON had reached 2.7 KB, so a single new
# entry made every job in a release run fail to be created at all, with
# "index row size 2808 exceeds btree version 4 maximum 2704". A file has no
# such limit, and the checkout is already pinned by TEST_GIT_REFSPEC.
#
# Provenance is kept by the hash the scheduler computed over the canonical
# JSON form of the policy, which the aggregator recomputes. Three
# implementations of that form now exist - Ruby in the scheduler, Python in the
# aggregator, Perl here - and openqa/production/test_policy_canonical_form.py
# proves they agree byte for byte.
sub load ($class) {
    my $casedir = testapi::get_var('CASEDIR', '/workspace');
    my $policy_path = "$casedir/openqa/application-policy.yaml";
    die "the application policy is missing at $policy_path" unless -f $policy_path;

    require YAML::PP;
    require Digest::SHA;
    my $policy = eval { YAML::PP->new(boolean => 'JSON::PP')->load_file($policy_path) };
    die "the application policy is not valid YAML: $@" unless ref $policy eq 'HASH';

    # The same canonical form the scheduler hashes and the aggregator
    # recomputes: keys sorted, no spaces. Parsed in Perl rather than shelled
    # out to Python, because the worker image ships YAML::PP and no PyYAML.
    my $canonical = JSON::PP->new->canonical(1)->utf8(0)->encode($policy);

    my $expected = testapi::get_var('BIGLINUX_APPLICATION_POLICY_HASH', '');
    die 'BIGLINUX_APPLICATION_POLICY_HASH is required to verify the policy'
      if $expected eq '';
    my $actual = Digest::SHA::sha256_hex(Encode::encode('UTF-8', $canonical));
    die "the application policy in $casedir does not match the scheduled hash: "
      . "expected $expected, read $actual"
      unless $actual eq $expected;

    return $policy;
}

1;
