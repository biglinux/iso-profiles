# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use application_smoke;
use application_policy;
use Digest::SHA qw(sha256_hex);
use Encode qw(encode);
use JSON::PP qw(encode_json);
use Math::BigInt;
use MIME::Base64 'encode_base64';
use Time::HiRes 'time';
use guest_shell qw(marker_format shell_quote);

my @application_metrics;
my $metrics_uploaded = 0;
my $metrics_upload_ok = 0;
my $kernel_version;
my $application_context;
my $desktop;

sub _record_info {
    my ($title, $output) = @_;
    # The detailed UTF-8 values stay in application-metrics.json; what reaches
    # the job log goes through the shared encoder.
    atspi->record_guest_info($title, $output);
}

sub test_flags {
    return {fatal => 0};
}

sub _entry_value {
    my ($entry, $key, $fallback) = @_;
    return exists $entry->{$key} && defined $entry->{$key} ? $entry->{$key} : $fallback;
}

sub _entry_priority {
    my ($entry) = @_;
    my $path = lc(_entry_value($entry, 'path', _entry_value($entry, 'relative_path', '')));
    return 0 if $path =~ m{(?:dolphin|libreoffice|gimp|brave)};
    return 1;
}

sub _entry_timeout {
    my ($entry, $default, $heavy) = @_;
    my $path = lc(_entry_value($entry, 'path', _entry_value($entry, 'relative_path', '')));
    return $heavy
      if $path =~ m{(?:gimp|libreoffice|soffice|lstopo|big-themes-gui|snapshotrestore|cups)[^/]*\.desktop\z};
    return $default;
}

sub _entry_matches_filter {
    my ($entry, $filter) = @_;
    return 1 unless defined $filter && $filter ne '';
    my $haystack = lc join "\n", map { _entry_value($entry, $_, '') }
      qw(name path relative_path exec launch_binary);
    return scalar grep { $_ ne '' && index($haystack, lc $_) >= 0 } split /,/, $filter;
}

sub _desktop_id {
    my ($entry) = @_;
    my $relative_path = _entry_value($entry, 'relative_path', '');
    return $relative_path if $relative_path ne '';
    my $path = _entry_value($entry, 'path', '');
    $path =~ s{\A/usr/share/applications/}{};
    return $path;
}

sub _application_policy {
    my $policy = application_policy->load;
    die 'application policy version must be 1'
      unless $policy->{version} && $policy->{version} == 1;
    for my $section (qw(exclude aliases critical)) {
        die "application policy section '$section' is invalid"
          if exists $policy->{$section} && ref $policy->{$section} ne 'ARRAY';
    }

    my %excluded;
    for my $item (@{$policy->{exclude} // []}) {
        die 'application policy exclusion is invalid'
          unless ref $item eq 'HASH'
          && defined $item->{desktop_id}
          && defined $item->{reason}
          && $item->{desktop_id} =~ /\A[^\r\n]+\.desktop\z/
          && $item->{reason} ne '';
        die 'application policy exclusion is duplicated'
          if exists $excluded{$item->{desktop_id}};
        $excluded{$item->{desktop_id}} = $item->{reason};
    }
    my %aliases;
    for my $item (@{$policy->{aliases} // []}) {
        die 'application policy alias is invalid'
          unless ref $item eq 'HASH'
          && defined $item->{desktop_id}
          && defined $item->{canonical}
          && $item->{desktop_id} =~ /\A[^\r\n]+\.desktop\z/
          && $item->{canonical} =~ /\A[^\r\n]+\.desktop\z/;
        die 'application policy alias is duplicated'
          if exists $aliases{$item->{desktop_id}};
        $aliases{$item->{desktop_id}} = $item->{canonical};
    }
    my %critical;
    for my $item (@{$policy->{critical} // []}) {
        die 'application policy critical entry is invalid'
          unless ref $item eq 'HASH'
          && defined $item->{desktop_id}
          && defined $item->{functional_test}
          && $item->{desktop_id} =~ /\A[^\r\n]+\.desktop\z/
          && $item->{functional_test} =~ /\A[A-Za-z0-9_.-]+\z/;
        die 'application policy critical entry is duplicated'
          if exists $critical{$item->{desktop_id}};
        $critical{$item->{desktop_id}} = $item->{functional_test};
    }
    return {excluded => \%excluded, aliases => \%aliases, critical => \%critical};
}

sub _shard_for {
    my ($desktop_id, $shard_count) = @_;
    my $digest = sha256_hex(encode('UTF-8', $desktop_id));
    my $number = Math::BigInt->new('0x' . $digest);
    return ($number % $shard_count)->numify;
}

sub _build_application_context {
    my ($entries, $policy, $shard_index, $shard_count) = @_;
    my @inventory;
    for my $entry (@$entries) {
        my $desktop_id = _desktop_id($entry);
        die 'desktop entry inventory contains an invalid desktop ID'
          unless $desktop_id =~ /\A[^\r\n\/]+(?:\/[^\r\n\/]+)*\.desktop\z/;
        die 'desktop entry inventory contains a duplicate desktop ID'
          if grep { $_->{desktop_id} eq $desktop_id } @inventory;
        my $not_applicable = $policy->{excluded}{$desktop_id}
          // application_smoke->not_applicable_reason($entry);
        my $classification = defined $not_applicable
          ? 'excluded'
          : exists $policy->{aliases}{$desktop_id}
          ? 'duplicate-alias'
          : defined _entry_value($entry, 'skip_reason', undef)
          && _entry_value($entry, 'skip_reason', '') ne ''
          ? 'invalid'
          : 'launchable';
        push @inventory, {
            desktop_id => $desktop_id,
            path => _entry_value($entry, 'path', undef),
            name => _entry_value($entry, 'name', $desktop_id),
            classification => $classification,
            classification_reason => $classification eq 'invalid'
              ? _entry_value($entry, 'skip_reason', 'invalid desktop entry')
              : undef,
            canonical => $policy->{aliases}{$desktop_id},
            exclusion_reason => $not_applicable,
            critical_functional_test => $policy->{critical}{$desktop_id},
            execution_contract => 'graphical',
            assigned_shard => _shard_for($desktop_id, $shard_count),
        };
    }
    @inventory = sort { $a->{desktop_id} cmp $b->{desktop_id} } @inventory;
    my $inventory_json = JSON::PP->new->canonical(1)->utf8(1)->encode(\@inventory);
    my %totals;
    for my $classification (qw(launchable excluded duplicate-alias invalid)) {
        $totals{$classification} = scalar grep {
            $_->{classification} eq $classification
        } @inventory;
    }
    my @critical = sort keys %{$policy->{critical}};
    my %known = map { $_->{desktop_id} => 1 } @inventory;
    my @not_installed = grep { !$known{$_} } @critical;
    # An alias drops its desktop entry from testing, so its canonical target
    # must itself exist and be tested; otherwise both silently lose coverage.
    my %classification_by_id = map { $_->{desktop_id} => $_->{classification} } @inventory;
    for my $entry (@inventory) {
        next unless $entry->{classification} eq 'duplicate-alias';
        die "alias $entry->{desktop_id} points to a missing or untested canonical"
          . " entry $entry->{canonical}"
          unless ($classification_by_id{$entry->{canonical}} // '') eq 'launchable';
    }
    my $context = {
        schema_version => 4,
        iso_filename => get_var('BIGLINUX_ISO_FILENAME', ''),
        iso_sha256 => get_var('BIGLINUX_ISO_SHA256', ''),
        build_id => get_var('BIGLINUX_OPENQA_BUILD', ''),
        commit_sha => get_var('BIGLINUX_OPENQA_COMMIT', ''),
        policy_version => 1,
        shard_index => $shard_index + 0,
        shard_count => $shard_count + 0,
        inventory_hash => sha256_hex($inventory_json),
        inventory => \@inventory,
        inventory_total => scalar @inventory,
        launchable_total => $totals{launchable},
        excluded_total => $totals{excluded},
        duplicate_total => $totals{'duplicate-alias'},
        invalid_total => $totals{invalid},
        critical_desktop_ids => \@critical,
        not_installed_desktop_ids => \@not_installed,
    };
    return $context;
}

sub _test_entry {
    my ($entry, $timeout) = @_;
    my $id = _desktop_id($entry);
    _record_info "$id / starting", $entry->{name} // $id;
    my $metric = application_smoke->check($entry, $timeout);
    $metric->{desktop_id} = $id;
    $metric->{name} = $entry->{name} // $id;
    $metric->{desktop_entry} = $entry->{path};
    $metric->{category} = $id;
    $metric->{classification} = $entry->{_coverage}{classification};
    $metric->{assigned_shard} = $entry->{_coverage}{assigned_shard};
    push @application_metrics, $metric;
    _record_info "$id / $metric->{status}",
      $metric->{error} // $metric->{skip_reason} // 'Accessible window opened; close shortcut completed with exit 0';
}

sub _write_guest_metrics {
    my ($payload) = @_;
    my $encoded = encode_base64($payload, '');
    my @chunks = $encoded =~ /.{1,900}/g;
    my $start_marker = '__OA_METRICS_START__';
    my $ready_marker = '__OA_METRICS_READY__';
    # Every marker below is typed as octal escapes (marker_format) so the
    # tty echo of the command line can never satisfy its own wait_serial; the
    # literal marker only appears once the command actually succeeded. This
    # also paces the chunk stream to the guest shell's real progress.
    select_console 'user-virtio-terminal';
    type_string "rm -f /tmp/application-metrics.json && : > /tmp/application-metrics.json && printf "
      . shell_quote(marker_format($start_marker) . '\\n');
    send_key 'ret';
    die 'guest metrics file did not start' unless wait_serial $start_marker, no_regex => 1, timeout => 15;
    for my $index (0 .. $#chunks) {
        my $marker = sprintf('__OA_METRICS_CHUNK_%04d__', $index);
        type_string "printf '%s' '$chunks[$index]' | base64 --decode >> /tmp/application-metrics.json && printf "
          . shell_quote(marker_format($marker) . '\\n');
        send_key 'ret';
        die "guest metrics chunk $index was not acknowledged"
          unless wait_serial $marker, no_regex => 1, timeout => 15;
    }
    type_string "test -s /tmp/application-metrics.json && printf "
      . shell_quote(marker_format($ready_marker) . '\\n');
    send_key 'ret';
    die 'guest metrics file was not created' unless wait_serial $ready_marker, no_regex => 1, timeout => 15;
    my $compressed_marker = '__OA_METRICS_COMPRESSED__';
    type_string "gzip -c /tmp/application-metrics.json > /tmp/application-metrics.json.gz && printf "
      . shell_quote(marker_format($compressed_marker) . '\\n');
    send_key 'ret';
    die 'guest metrics compression failed'
      unless wait_serial $compressed_marker, no_regex => 1, timeout => 15;
    select_console 'sut';
}

sub _upload_guest_metrics {
    my $basename = 'application-metrics.json.gz';
    my $marker = sprintf('__OA_METRICS_UPLOAD_%d_%d__', $$, int(time * 1000) % 1_000_000);
    my $upload_url = autoinst_url("/uploadlog/$basename");
    select_console 'user-virtio-terminal';
    type_string 'curl --fail --silent --show-error --form upload=\@/tmp/application-metrics.json.gz '
      . '--form upname=application-metrics.json.gz --max-time 90 '
      . shell_quote($upload_url)
      . ' >/tmp/openqa-metrics-upload.log 2>&1; code=$?; printf '
      . shell_quote(marker_format($marker) . '%s\\n') . ' "$code"';
    send_key 'ret';
    my $serial = wait_serial qr/\Q$marker\E(\d+)/, timeout => 100;
    select_console 'sut';
    die 'guest metrics upload did not return an exit code' unless defined $serial;
    my ($exit_code) = $serial =~ /\Q$marker\E(\d+)/;
    die 'guest metrics upload returned an invalid exit code'
      unless defined $exit_code && $exit_code =~ /\A\d+\z/;
    return $exit_code + 0;
}

sub upload_application_metrics {
    return $metrics_upload_ok if $metrics_uploaded;
    my $failed = scalar grep { $_->{status} eq 'failed' } @application_metrics;
    my $tested = scalar grep { $_->{status} ne 'skipped' } @application_metrics;
    my $skipped = scalar grep { $_->{status} eq 'skipped' } @application_metrics;
    my $payload = encode_json({
        schema_version => 2,
        system => {
            kernel => $kernel_version,
            desktop => $desktop // 'unknown',
            accessibility_bus => 'Active and validated with AT-SPI',
        },
        summary => {
            total => scalar @application_metrics,
            tested => $tested,
            passed => scalar(grep { $_->{status} eq 'passed' } @application_metrics),
            failed => $failed,
            skipped => $skipped,
        },
        coverage => $application_context,
        applications => \@application_metrics,
    });
    my $written = eval { _write_guest_metrics($payload); 1 };
    if ($written) {
        my $upload_exit_code = eval { _upload_guest_metrics };
        if (!defined $upload_exit_code || $upload_exit_code != 0) {
            _record_info 'Application metrics',
              'Guest metrics file was created but upload returned exit code '
              . (defined $upload_exit_code ? $upload_exit_code : 'unknown');
        }
        else {
            $metrics_upload_ok = 1;
        }
    }
    else {
        my $error = $@ || 'unknown metrics transfer error';
        $error =~ s/\s+\z//;
        _record_info 'Application metrics', "Could not transfer application-metrics.json: $error";
        eval { select_console 'sut' };
    }
    select_console 'sut';
    $metrics_uploaded = 1;
    return $metrics_upload_ok;
}

sub post_run_hook {
    die 'Application metrics upload failed' unless upload_application_metrics;
}

sub post_fail_hook {
    upload_application_metrics;
}



sub run {
    $kernel_version = atspi->kernel_version;
    my $baseline = atspi->reset_baseline;
    $desktop = $baseline->{desktop} // 'unknown';
    _record_info 'Accessibility', 'AT-SPI session: ' . $desktop;
    my $entries = atspi->inventory;
    _record_info 'Applications / not applicable', 'No installed desktop applications were discovered'
      unless @$entries;

    my $timeout = get_var('BIGLINUX_APPLICATION_TIMEOUT', 30);
    # Generous on purpose: an application that works returns as soon as its
    # window appears, so a long budget is only ever spent on one that is
    # struggling. Package managers refresh their metadata on first start and
    # a browser cold start is slow, and both were being called broken for it.
    my $heavy_timeout = get_var('BIGLINUX_APPLICATION_HEAVY_TIMEOUT', 60);
    my $filter = get_var('BIGLINUX_APPLICATION_FILTER', '');
    my $shard_count = get_var('BIGLINUX_APPLICATION_SHARD_COUNT', 1);
    my $shard_index = get_var('BIGLINUX_APPLICATION_SHARD_INDEX', 0);
    die 'BIGLINUX_APPLICATION_TIMEOUT must be a positive number'
      unless defined $timeout && $timeout =~ /\A[1-9][0-9]*(?:\.[0-9]+)?\z/;
    die 'BIGLINUX_APPLICATION_HEAVY_TIMEOUT must be a positive number'
      unless defined $heavy_timeout && $heavy_timeout =~ /\A[1-9][0-9]*(?:\.[0-9]+)?\z/;
    die 'BIGLINUX_APPLICATION_FILTER must not contain newlines'
      if defined $filter && $filter =~ /[\r\n]/;
    die 'BIGLINUX_APPLICATION_SHARD_COUNT must be a positive integer'
      unless defined $shard_count && $shard_count =~ /\A[1-9][0-9]*\z/;
    die 'BIGLINUX_APPLICATION_SHARD_INDEX must be a valid shard index'
      unless defined $shard_index && $shard_index =~ /\A[0-9]+\z/ && $shard_index < $shard_count;
    my $policy = _application_policy;
    $application_context = _build_application_context(
        $entries, $policy, $shard_index, $shard_count
    );
    my %coverage_by_id = map { $_->{desktop_id} => $_ } @{$application_context->{inventory}};
    for my $entry (@$entries) {
        $entry->{_coverage} = $coverage_by_id{_desktop_id($entry)};
    }
    my @selected_entries = grep {
        my $coverage = $_->{_coverage};
        $coverage->{classification} eq 'launchable'
          && $coverage->{assigned_shard} == $shard_index
          && ($filter eq '' || _entry_matches_filter($_, $filter));
    } @$entries;
    _record_info 'Applications / not applicable', 'No installed application matches the filter'
      if $filter ne '' && !@selected_entries;
    _record_info 'Application inventory', sprintf(
        '%d desktop entries discovered recursively; shard %d/%d selected %d',
        scalar @$entries,
        $shard_index,
        $shard_count,
        scalar @selected_entries,
    );
    _record_info 'Application filter', $filter if defined $filter && $filter ne '';

    my @ordered_entries = sort {
        _entry_priority($a) <=> _entry_priority($b)
          || $a->{path} cmp $b->{path}
    } @selected_entries;
    for my $entry (@ordered_entries) {
        _test_entry($entry, _entry_timeout($entry, $timeout, $heavy_timeout));
    }

    upload_application_metrics;
    my @failed = grep { $_->{status} eq 'failed' } @application_metrics;
    die 'Application coverage contains invalid desktop entries: '
      . $application_context->{invalid_total}
      if $application_context->{invalid_total};
    for my $id (@{$application_context->{not_installed_desktop_ids}}) {
        _record_info "$id / skipped", 'Not installed in this ISO; not applicable';
    }
    die sprintf('%d of %d desktop applications failed; see application-metrics.json',
        scalar @failed, scalar @application_metrics)
      if @failed;
}

1;
