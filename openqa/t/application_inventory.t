use strict;
use warnings;
use utf8;
use Test::More;
use JSON::PP;
use Encode qw(encode);
use Digest::SHA qw(sha256_hex);
{
    package InventoryUnderTest;
    my $loaded = do './openqa/tests/applications.pm';
    die $@ || $! unless $loaded;
}
no warnings qw(redefine once);
local *InventoryUnderTest::get_var = sub { return $_[1]; };
my $policy = {excluded => {}, aliases => {}, critical => {'optional.desktop' => 'optional'}};
my $entry = {path => '/usr/share/applications/editor.desktop', relative_path => 'editor.desktop', name => 'Editor 日本語'};
my $coverage = InventoryUnderTest::_build_application_context([$entry], $policy, 0, 4);
is_deeply($coverage->{not_installed_desktop_ids}, ['optional.desktop'], 'missing optional app is reported, not required');
is($coverage->{schema_version}, 4, 'new schema distinguishes complete smoke from historical launch-only');
is($coverage->{inventory_hash}, sha256_hex(JSON::PP->new->canonical->utf8->encode($coverage->{inventory})), 'inventory uses UTF-8 canonical bytes');
is(InventoryUnderTest::_shard_for('Aplicação/日本語.desktop', 4), 0, 'Unicode assignment agrees with Python SHA-256');
my %other = (%$entry, not_applicable_reason => 'OnlyShowIn=KDE on GNOME');
is(InventoryUnderTest::_build_application_context([\%other], $policy, 0, 4)->{excluded_total}, 1, 'entry for another desktop is excluded');
my %broken = (%$entry, skip_reason => 'neither Exec nor DBusActivatable');
is(InventoryUnderTest::_build_application_context([\%broken], $policy, 0, 4)->{invalid_total}, 1, 'broken installed entry is not disguised as missing');
is(InventoryUnderTest::_build_application_context([], $policy, 0, 4)->{launchable_total}, 0, 'empty complete inventory contains no invented tests');
done_testing;
