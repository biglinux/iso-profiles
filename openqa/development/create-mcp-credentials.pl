#!/usr/bin/env perl

use strict;
use warnings;

use lib '/usr/share/openqa/lib';

use OpenQA::Schema;
use OpenQA::Utils qw(random_hex);

my $nickname = $ENV{OPENQA_MCP_USER} // die "OPENQA_MCP_USER is required\n";
die "invalid OPENQA_MCP_USER\n" unless $nickname =~ /^[A-Za-z0-9_.-]+$/;

my $schema = OpenQA::Schema::connect_db(deploy => 0, silent => 1, from_script => 1);
my $user = $schema->resultset('Users')->create_user(
    $nickname,
    email => "$nickname\@example.invalid",
    fullname => 'BigLinux openQA development agent',
    is_admin => 0,
    is_operator => 0,
);
my $key = random_hex();
my $secret = random_hex();
$user->api_keys->create({key => $key, secret => $secret});

print "Key: $key\nSecret: $secret\n";
