# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use Encode qw(encode);
use JSON::PP qw(encode_json);
use MIME::Base64 'encode_base64';
use Time::HiRes 'time';

my @application_metrics;
my $metrics_uploaded = 0;
my $kernel_version;

sub _record_info {
    my ($title, $output) = @_;
    # isotovideo writes record_info through a byte-oriented serial channel.
    # Keep the detailed UTF-8 values in application-metrics.json, but pass
    # encoded octets here so one localized desktop name cannot abort the run.
    record_info encode('UTF-8', "$title"), encode('UTF-8', "$output");
}

sub test_flags {
    return {fatal => 0};
}

sub _entry_value {
    my ($entry, $key, $fallback) = @_;
    return exists $entry->{$key} && defined $entry->{$key} ? $entry->{$key} : $fallback;
}

sub _record_skipped {
    my ($entry, $reason) = @_;
    my $name = _entry_value($entry, 'name', _entry_value($entry, 'relative_path', 'Unnamed desktop entry'));
    push @application_metrics, {
        name => $name,
        category => _entry_value($entry, 'relative_path', 'unknown'),
        desktop_entry => _entry_value($entry, 'path', undef),
        status => 'skipped',
        skip_reason => $reason,
        action => 'Not launchable in this desktop entry',
    };
    _record_info "$name / skipped", $reason;
}

sub _max_metric {
    my (@values) = @_;
    my @numbers = grep { _looks_like_number($_) } @values;
    return undef unless @numbers;
    my $maximum = $numbers[0];
    for my $number (@numbers[1 .. $#numbers]) {
        $maximum = $number if $number > $maximum;
    }
    return $maximum + 0;
}

sub _looks_like_number {
    my ($value) = @_;
    return defined $value && $value =~ /\A\d+(?:\.\d+)?\z/;
}

sub _merge_memory {
    my ($metric, @snapshots) = @_;
    for my $field (qw(rss_mib pss_mib process_count)) {
        my @values = map { ref $_ eq 'HASH' ? $_->{$field} : undef } @snapshots;
        $metric->{"${field}_peak"} = _max_metric(@values);
    }
}

sub _entry_metric {
    my ($entry) = @_;
    return {
        name => _entry_value($entry, 'name', _entry_value($entry, 'relative_path', 'Unnamed desktop entry')),
        category => _entry_value($entry, 'relative_path', 'unknown'),
        desktop_entry => _entry_value($entry, 'path', undef),
        launcher => _entry_value($entry, 'exec', undef),
        status => 'failed',
        action => _entry_value($entry, 'terminal', JSON::PP::false)
          ? 'Process start'
          : 'Application window open check',
        dbus_activatable => _entry_value($entry, 'dbus_activatable', JSON::PP::false),
        terminal => _entry_value($entry, 'terminal', JSON::PP::false),
    };
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
    return $heavy if $path =~ m{(?:gimp|libreoffice|soffice)[^/]*\.desktop\z};
    return $default;
}

sub _x11_fallback_open {
    my ($launch_pid, $timeout) = @_;
    return eval {
        atspi->x11_wait_open($launch_pid, '', $timeout);
    };
}

sub _uses_x11_fallback {
    my ($entry) = @_;
    return !_entry_value($entry, 'terminal', JSON::PP::false);
}

sub _uses_process_only {
    my ($entry) = @_;
    my $launch_binary = lc(_entry_value($entry, 'launch_binary', ''));
    my $path = lc(_entry_value($entry, 'path', ''));
    return $launch_binary eq 'fcitx5'
      || $path =~ m{/org\.fcitx\.fcitx5\.desktop\z};
}

sub _entry_matches_filter {
    my ($entry, $filter) = @_;
    return 1 unless defined $filter && $filter ne '';
    my $haystack = lc join "\n", map { _entry_value($entry, $_, '') }
      qw(name path relative_path exec launch_binary);
    return scalar grep { $_ ne '' && index($haystack, lc $_) >= 0 } split /,/, $filter;
}

sub _test_entry {
    my ($entry, $timeout) = @_;
    my $metric = _entry_metric($entry);
    my $name = $metric->{name};
    my ($status_path, $window_pid, $launch_pid);
    my $failure;
    my $process_started = 0;
    my $started = time;

    _record_info "$name / starting",
      'desktop_entry=' . _entry_value($entry, 'relative_path', _entry_value($entry, 'path', 'unknown'));
    eval {
        my ($baseline, $opened, $launch_method, $open_seconds, $path, $child_pid, $launch_memory) =
          atspi->launch_desktop_entry($entry, $timeout);
        $status_path = $path;
        $launch_pid = $child_pid;
        _record_info "$name / launched",
          sprintf('pid=%s; method=%s', $launch_pid // 'unknown', $launch_method // 'unknown');
        my $validation_mode = 'atspi-open';
        if ($opened->{status} ne 'passed' && _uses_x11_fallback($entry)) {
            my $x11_opened = _x11_fallback_open($launch_pid, $timeout);
            if (ref $x11_opened eq 'HASH' && $x11_opened->{status} eq 'passed') {
                $opened = $x11_opened;
                $validation_mode = 'x11-open';
                $metric->{fallback_reason} = 'AT-SPI did not expose a window; PID-scoped X11 window found';
            }
        }
        $metric->{launch_method} = $launch_method;
        $metric->{launch_pid} = $launch_pid;
        $metric->{launch_timeout_seconds} = $timeout + 0;
        $metric->{open_seconds} = sprintf('%.2f', $open_seconds) + 0;
        $metric->{mem_available_before_mib} = $baseline->{mem_available_mib};
        $metric->{mem_available_after_open_mib} = $opened->{mem_available_mib};
        $metric->{accessible_window} = $opened->{accessible_window} ? JSON::PP::true : JSON::PP::false;
        $metric->{accessible_application} = $opened->{application};
        $metric->{accessible_window_name} = $opened->{window};
        $metric->{accessible_children} = $opened->{accessible_children};
        $window_pid = $opened->{pid};
        $metric->{window_pid} = $window_pid;
        my $window_memory = $window_pid
          ? eval { atspi->result('memory', 1, '--pid', $window_pid) }
          : undef;
        _merge_memory(
            $metric,
            $launch_memory && $launch_memory->{memory},
            $opened->{memory},
            $window_memory && $window_memory->{memory},
        );
        $metric->{memory_sample_status} = defined $metric->{rss_mib_peak}
          || defined $metric->{pss_mib_peak}
          ? 'collected'
          : 'process exited before memory sampling';
        _record_info "$name / " . ($opened->{status} eq 'passed' ? 'opened' : 'started'),
          sprintf('%s; peak RSS=%s MiB; peak PSS=%s MiB',
            $opened->{status} eq 'passed' ? 'AT-SPI window detected' : 'process started without accessible window',
            $metric->{rss_mib_peak} // 'not collected',
            $metric->{pss_mib_peak} // 'not collected');

        if ($opened->{status} ne 'passed') {
            # Terminal and daemon-style entries have no window to observe. A
            # supervisor child is enough evidence that their command started.
            if ($metric->{terminal} || _uses_process_only($entry)) {
                $metric->{validation_mode} = 'process-start';
                $metric->{interaction} = 'process.started';
                $metric->{interaction_status} = 'passed';
                $metric->{interaction_result} = JSON::PP::true;
                $metric->{status} = 'passed';
                $process_started = 1;
            }
            die $opened->{error} || 'application did not expose an accessible window'
              unless $process_started;
        }

        if (!$process_started) {
            $metric->{validation_mode} = $validation_mode;
            $metric->{interaction} = 'application.opened';
            $metric->{interaction_status} = 'passed';
            $metric->{interaction_result} = JSON::PP::true;
            $metric->{status} = 'passed';
        }
    };
    $failure = $@ if $@;
    _record_info "$name / cleaning", 'terminating the application process tree';
    my $cleanup;
    my $cleanup_error;
    eval { $cleanup = atspi->cleanup; 1 } or $cleanup_error = $@ || 'application cleanup failed';
    if (!$cleanup_error && (!ref $cleanup || $cleanup->{status} ne 'passed')) {
        $cleanup_error = ref $cleanup && $cleanup->{error}
          ? $cleanup->{error} : 'application cleanup failed';
    }
    $metric->{cleanup_status} = ref $cleanup ? $cleanup->{status} : 'failed';
    $metric->{cleanup_closed} = $cleanup->{closed} if ref $cleanup;
    $metric->{cleanup_killed} = $cleanup->{killed} if ref $cleanup;
    _record_info "$name / cleanup",
      sprintf('status=%s; closed=%s; killed=%s',
        $metric->{cleanup_status},
        $metric->{cleanup_closed} // 'unknown',
        $metric->{cleanup_killed} // 'unknown');
    if (!$failure && $cleanup_error) {
        $failure = $cleanup_error;
    }
    if ($failure) {
        $failure =~ s/\s+\z//;
        $metric->{error} = $failure || 'application test failed';
        $metric->{cleanup_error} = $cleanup_error if $cleanup_error;
        $metric->{status} = 'failed';
    }
    $metric->{duration_seconds} = sprintf('%.2f', time - $started) + 0;
    push @application_metrics, $metric;

    if ($metric->{status} eq 'passed') {
        my $mode = $metric->{validation_mode} // 'unknown';
        _record_info "$name / passed",
          sprintf('%s action=%s; peak RSS=%s MiB; peak PSS=%s MiB',
            $mode,
            $metric->{interaction} // 'unknown',
            $metric->{rss_mib_peak} // 'not collected',
            $metric->{pss_mib_peak} // 'not collected');
    }
    else {
        _record_info "$name / failed", $metric->{error};
    }
}

sub _write_guest_metrics {
    my ($payload) = @_;
    my $encoded = encode_base64($payload, '');
    my @chunks = $encoded =~ /.{1,900}/g;
    my $start_marker = '__OA_METRICS_START__';
    my $ready_marker = '__OA_METRICS_READY__';
    select_console 'root-virtio-terminal';
    type_string "rm -f /tmp/application-metrics.json; : > /tmp/application-metrics.json; printf '%s\\n' "
      . _shell_quote($start_marker);
    send_key 'ret';
    die 'guest metrics file did not start' unless wait_serial $start_marker, no_regex => 1, timeout => 15;
    for my $index (0 .. $#chunks) {
        my $marker = sprintf('__OA_METRICS_CHUNK_%04d__', $index);
        type_string "printf '%s' '$chunks[$index]' | base64 --decode >> /tmp/application-metrics.json; printf '%s\\n' "
          . _shell_quote($marker);
        send_key 'ret';
        die "guest metrics chunk $index was not acknowledged"
          unless wait_serial $marker, no_regex => 1, timeout => 15;
    }
    type_string "test -s /tmp/application-metrics.json && printf '%s\\n' "
      . _shell_quote($ready_marker);
    send_key 'ret';
    die 'guest metrics file was not created' unless wait_serial $ready_marker, no_regex => 1, timeout => 15;
    my $compressed_marker = '__OA_METRICS_COMPRESSED__';
    type_string "gzip -c /tmp/application-metrics.json > /tmp/application-metrics.json.gz && printf '%s\\n' "
      . _shell_quote($compressed_marker);
    send_key 'ret';
    die 'guest metrics compression failed'
      unless wait_serial $compressed_marker, no_regex => 1, timeout => 15;
    select_console 'sut';
}

sub _upload_guest_metrics {
    my $basename = 'application-metrics.json.gz';
    my $marker = sprintf('__OA_METRICS_UPLOAD_%d_%d__', $$, int(time * 1000) % 1_000_000);
    my $upload_url = autoinst_url("/uploadlog/$basename");
    select_console 'root-virtio-terminal';
    type_string 'curl --fail --silent --show-error --form upload=\@/tmp/application-metrics.json.gz '
      . '--form upname=application-metrics.json.gz --max-time 90 '
      . _shell_quote($upload_url)
      . ' >/tmp/openqa-metrics-upload.log 2>&1; code=$?; printf '
      . _shell_quote(_marker_format($marker) . '%s\\n') . ' "$code"';
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
    return if $metrics_uploaded;
    my $failed = scalar grep { $_->{status} eq 'failed' } @application_metrics;
    my $tested = scalar grep { $_->{status} ne 'skipped' } @application_metrics;
    my $skipped = scalar grep { $_->{status} eq 'skipped' } @application_metrics;
    my $payload = encode_json({
        schema_version => 2,
        system => {
            kernel => $kernel_version,
            desktop => 'KDE Plasma',
            accessibility_bus => 'Active and validated with AT-SPI',
        },
        summary => {
            total => scalar @application_metrics,
            tested => $tested,
            passed => scalar(grep { $_->{status} eq 'passed' } @application_metrics),
            failed => $failed,
            skipped => $skipped,
        },
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
    }
    else {
        my $error = $@ || 'unknown metrics transfer error';
        $error =~ s/\s+\z//;
        _record_info 'Application metrics', "Could not transfer application-metrics.json: $error";
        eval { select_console 'sut' };
    }
    select_console 'sut';
    $metrics_uploaded = 1;
}

sub post_run_hook {
    upload_application_metrics;
}

sub post_fail_hook {
    upload_application_metrics;
}

sub _shell_quote {
    my ($value) = @_;
    $value =~ s/'/'"'"'/g;
    return "'$value'";
}

sub _marker_format {
    my ($marker) = @_;
    return join '', map { sprintf '\\%03o', ord } split //, $marker;
}

sub run {
    $kernel_version = atspi->prepare;
    _record_info 'Accessibility', 'AT-SPI is active and exposes the KDE live session';
    my $entries = atspi->inventory;
    die 'No desktop entries were discovered under /usr/share/applications'
      unless @$entries;

    my $timeout = get_var('BIGLINUX_APPLICATION_TIMEOUT', 8);
    my $heavy_timeout = get_var('BIGLINUX_APPLICATION_HEAVY_TIMEOUT', 20);
    my $filter = get_var('BIGLINUX_APPLICATION_FILTER', '');
    die 'BIGLINUX_APPLICATION_TIMEOUT must be a positive number'
      unless defined $timeout && $timeout =~ /\A[1-9][0-9]*(?:\.[0-9]+)?\z/;
    die 'BIGLINUX_APPLICATION_HEAVY_TIMEOUT must be a positive number'
      unless defined $heavy_timeout && $heavy_timeout =~ /\A[1-9][0-9]*(?:\.[0-9]+)?\z/;
    die 'BIGLINUX_APPLICATION_FILTER must not contain newlines'
      if defined $filter && $filter =~ /[\r\n]/;
    _record_info 'Application inventory', sprintf('%d desktop entries discovered recursively', scalar @$entries);
    _record_info 'Application filter', $filter if defined $filter && $filter ne '';

    my @ordered_entries = sort {
        _entry_priority($a) <=> _entry_priority($b)
          || $a->{path} cmp $b->{path}
    } @$entries;
    for my $entry (@ordered_entries) {
        my $reason = $entry->{skip_reason};
        if (defined $reason && $reason ne '') {
            _record_skipped($entry, $reason);
            next;
        }
        if (!_entry_matches_filter($entry, $filter)) {
            _record_skipped($entry, 'not selected by BIGLINUX_APPLICATION_FILTER');
            next;
        }
        _test_entry($entry, _entry_timeout($entry, $timeout, $heavy_timeout));
    }

    upload_application_metrics;
    my @failed = grep { $_->{status} eq 'failed' } @application_metrics;
    die sprintf('%d of %d desktop applications failed; see application-metrics.json',
        scalar @failed, scalar @application_metrics)
      if @failed;
}

1;
