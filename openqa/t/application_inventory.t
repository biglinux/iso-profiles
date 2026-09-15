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
my $policy = {
    excluded => {},
    aliases => {},
    contracts => {},
    critical => {'optional.desktop' => 'optional'},
};
my $entry = {path => '/usr/share/applications/editor.desktop', relative_path => 'editor.desktop', name => 'Editor 日本語'};
my $coverage = InventoryUnderTest::_build_application_context([$entry], $policy, 0, 4);
is_deeply($coverage->{not_installed_desktop_ids}, ['optional.desktop'], 'missing optional app is reported, not required');
is($coverage->{schema_version}, 5, 'contract schema distinguishes lifecycle-aware smoke from historical results');
is($coverage->{inventory}[0]{execution_contract}, 'standard', 'unconfigured entries use the strict standard contract');
is($coverage->{inventory_hash}, sha256_hex(JSON::PP->new->canonical->utf8->encode($coverage->{inventory})), 'inventory uses UTF-8 canonical bytes');
is(InventoryUnderTest::_shard_for('Aplicação/日本語.desktop', 4), 0, 'Unicode assignment agrees with Python SHA-256');
my %other = (%$entry, not_applicable_reason => 'OnlyShowIn=KDE on GNOME');
is(InventoryUnderTest::_build_application_context([\%other], $policy, 0, 4)->{excluded_total}, 1, 'entry for another desktop is excluded');
my %broken = (%$entry, skip_reason => 'neither Exec nor DBusActivatable');
is(InventoryUnderTest::_build_application_context([\%broken], $policy, 0, 4)->{invalid_total}, 1, 'broken installed entry is not disguised as missing');
is(InventoryUnderTest::_build_application_context([], $policy, 0, 4)->{launchable_total}, 0, 'empty complete inventory contains no invented tests');

my $classified_policy = {
    excluded => {'steam.desktop' => 'Steam bootstrap installer is not the installed client'},
    aliases => {'editor-alias.desktop' => 'editor.desktop'},
    contracts => {
        'camera.desktop' => {
            kind => 'standard', reason => 'camera required', close_key => undef,
            close_timeout => 20, content_timeout => 15,
            allowed_exit_codes => [0], requirements => ['video-device'],
        },
    },
    critical => {},
};
my @classified_entries = (
    {%$entry},
    {path => '/usr/share/applications/editor-alias.desktop', relative_path => 'editor-alias.desktop', name => 'Editor alias'},
    {path => '/usr/share/applications/steam.desktop', relative_path => 'steam.desktop', name => 'Install Steam'},
    {path => '/usr/share/applications/camera.desktop', relative_path => 'camera.desktop', name => 'Camera'},
);
my $classified = InventoryUnderTest::_build_application_context(\@classified_entries, $classified_policy, 0, 4);
my %by_id = map { $_->{desktop_id} => $_ } @{$classified->{inventory}};
is($by_id{'steam.desktop'}{classification}, 'excluded', 'Steam bootstrap remains visible as an audited exclusion');
like($by_id{'steam.desktop'}{exclusion_reason}, qr/bootstrap/i, 'Steam exclusion records its reason');
is($by_id{'editor-alias.desktop'}{classification}, 'duplicate-alias', 'duplicate desktop entry is not executed twice');
is($by_id{'editor-alias.desktop'}{canonical}, 'editor.desktop', 'alias records the canonical test');
is($by_id{'camera.desktop'}{execution_contract}, 'standard', 'capability-gated app keeps strict graphical contract');
is_deeply($by_id{'camera.desktop'}{contract_requirements}, ['video-device'], 'capability requirements are in coverage evidence');
is($by_id{'camera.desktop'}{contract_content_timeout}, 15, 'per-app content bound is persisted');

my $bad_alias_policy = {%$classified_policy, aliases => {'orphan.desktop' => 'missing.desktop'}};
my $alias_error = eval {
    InventoryUnderTest::_build_application_context(
        [{path => '/usr/share/applications/orphan.desktop', relative_path => 'orphan.desktop', name => 'Orphan'}],
        $bad_alias_policy, 0, 4);
    '';
};
like($@, qr/missing or untested canonical/, 'alias cannot silently remove all coverage');
done_testing;
