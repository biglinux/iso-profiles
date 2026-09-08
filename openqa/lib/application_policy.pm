# SPDX-License-Identifier: GPL-2.0-or-later

package application_policy;

use Mojo::Base -strict, -signatures;
use testapi ();

# The policy is read from the checkout rather than from a job setting.
#
# openQA indexes every job setting, and PostgreSQL refuses an index row over
# 2704 bytes: the canonical policy JSON had reached 2.7 KB, so a single new
# entry made every job in a release run fail to be created at all, with
# "index row size 2808 exceeds btree version 4 maximum 2704". A file has no
# such limit.
#
# No hash is checked here. Every job of a run reads the same checkout, and the
# commit it came from travels as BIGLINUX_OPENQA_TEST_GIT_REFSPEC and is
# compared across shards by the aggregator. Hashing the file as well only
# proved that a file at a commit matches itself, and it took three
# byte-identical canonical-JSON implementations to do it.
sub load ($class) {
    my $casedir = testapi::get_var('CASEDIR', '/workspace');
    my $policy_path = "$casedir/openqa/application-policy.yaml";
    die "the application policy is missing at $policy_path" unless -f $policy_path;

    require YAML::PP;
    my $policy = eval { YAML::PP->new(boolean => 'JSON::PP')->load_file($policy_path) };
    die "the application policy is not valid YAML: $@" unless ref $policy eq 'HASH';

    return $policy;
}

1;
