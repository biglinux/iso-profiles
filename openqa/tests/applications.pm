# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use JSON::PP qw(decode_json encode_json);
use MIME::Base64 'encode_base64';
use Time::HiRes 'time';

my %available_commands;
my %available_desktop_entries;
my @application_metrics;
my $metrics_uploaded = 0;
my $kernel_version;
my $atspi_probe = '/tmp/openqa-atspi-probe.py';
my $atspi_state = '/tmp/openqa-atspi-baseline.json';

sub discover_commands {
    my (@commands) = @_;

    select_console 'root-virtio-terminal';
    my $probe_id = 0;
    for my $command (@commands) {
        ++$probe_id;
        # Do not use script_run here: its shell-echo marker is sensitive to
        # bracketed/ANSI prompt output on the live console.  An explicit
        # per-command marker gives us a deterministic protocol without
        # matching a marker left in the serial buffer by a previous probe.
        my $present_marker = "__OA_${probe_id}_PRESENT__";
        my $absent_marker = "__OA_${probe_id}_ABSENT__";
        type_string "if command -v '$command' >/dev/null 2>&1; then printf '${present_marker}\\n'; else printf '${absent_marker}\\n'; fi\\n";
        my $result = wait_serial qr/\Q$present_marker\E|\Q$absent_marker\E/, timeout => 15;
        die "command availability probe timed out for '$command'" unless defined $result;
        $available_commands{$command} = $result =~ /\Q$present_marker\E/;
    }
    select_console 'sut';

    my @missing = grep { !$available_commands{$_} } @commands;
    record_info 'Application inventory', @missing ?
      'Skipping absent executables: ' . join(', ', @missing) :
      'All catalogued application executables are present';
}

sub command_available {
    my ($command) = @_;
    die "command '$command' was not included in the availability inventory"
      unless exists $available_commands{$command};
    return $available_commands{$command};
}

sub discover_desktop_entries {
    my (@entries) = @_;

    select_console 'root-virtio-terminal';
    my $probe_id = 0;
    for my $entry (@entries) {
        ++$probe_id;
        my $present_marker = "__OA_DESKTOP_${probe_id}_PRESENT__";
        my $absent_marker = "__OA_DESKTOP_${probe_id}_ABSENT__";
        type_string 'home=$(getent passwd 1000 | cut -d: -f6); if [ -r "$home/.local/share/applications/'
          . $entry . '.desktop" ] || [ -r "/usr/share/applications/' . $entry . '.desktop" ]; then printf "'
          . $present_marker . '\n"; else printf "' . $absent_marker . '\n"; fi\n';
        my $result = wait_serial qr/\Q$present_marker\E|\Q$absent_marker\E/, timeout => 15;
        die "desktop entry availability probe timed out for '$entry'" unless defined $result;
        $available_desktop_entries{$entry} = $result =~ /\Q$present_marker\E/;
    }
    select_console 'sut';

    my @missing = grep { !$available_desktop_entries{$_} } @entries;
    record_info 'Desktop entry inventory', @missing ?
      'Skipping absent desktop entries: ' . join(', ', @missing) :
      'All catalogued desktop entries are present';
}

sub skip_missing_application {
    my ($category, $search, $command) = @_;
    record_info "$category / skipped", "Executable '$command' is not installed; '$search' is not tested";
    push @application_metrics, {
        category => $category,
        name => $search,
        launcher => $command,
        status => 'skipped',
        action => 'Executable absent from this ISO',
    };
}

sub atspi_result {
    my ($operation, $timeout) = @_;
    $timeout //= 30;
    select_console 'root-virtio-terminal';
    type_string "python3 '$atspi_probe' '$operation' --state '$atspi_state' --timeout '$timeout'\n";
    my $serial = wait_serial qr/__OPENQA_ATSPI__([0-9a-f]+)/, timeout => $timeout + 10;
    select_console 'sut';
    die "AT-SPI probe '$operation' did not return a result" unless defined $serial;
    $serial =~ /__OPENQA_ATSPI__([0-9a-f]+)/ or die "AT-SPI probe '$operation' returned malformed data";
    return decode_json(pack 'H*', $1);
}

sub prepare_accessibility {
    my $probe_url = data_url('atspi_probe.py');
    select_console 'root-virtio-terminal';
    type_string 'export XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus '
      . "SAL_ACCESSIBILITY_ENABLED=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1; "
      . 'gsettings set org.gnome.desktop.interface toolkit-accessibility true; '
      . 'systemctl --user restart at-spi-dbus-bus.service; '
      . 'systemctl --user set-environment SAL_ACCESSIBILITY_ENABLED=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1; '
      . 'dbus-update-activation-environment --systemd SAL_ACCESSIBILITY_ENABLED QT_LINUX_ACCESSIBILITY_ALWAYS_ON; '
      . "curl --fail --silent --show-error '$probe_url' --output '$atspi_probe'; "
      . "chmod 700 '$atspi_probe'; "
      . 'kquitapp6 krunner >/dev/null 2>&1 || true; '
      . 'printf "__OA_A11Y_READY__%s\\n" "$(uname -r)"\n';
    my $result = wait_serial qr/__OA_A11Y_READY__([^\r\n]+)/, timeout => 30;
    die 'Unable to activate the AT-SPI accessibility stack' unless defined $result;
    $result =~ /__OA_A11Y_READY__([^\r\n]+)/;
    $kernel_version = $1;
    select_console 'sut';

    my $baseline = atspi_result 'baseline', 10;
    die "AT-SPI is active but exposes no graphical applications"
      unless ref($baseline->{windows}) eq 'ARRAY' && @{$baseline->{windows}};
    record_info 'Accessibility', 'AT-SPI is active and exposes the KDE live session';
}

sub begin_application {
    my ($category, $command, $timeout, $action) = @_;
    my $baseline = atspi_result 'baseline', 10;
    my $started = time;
    my $launch_command = "env QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 $command";
    if ($command =~ /(?:^|\s)(?:libreoffice|gtk-launch\s+libreoffice-)/) {
        $launch_command = "env SAL_USE_VCLPLUGIN=gtk3 SAL_ACCESSIBILITY_ENABLED=1 $launch_command";
    }

    record_info $category, "Run '$command' and require an accessible application window";
    send_key 'alt-f2';
    sleep 2;
    type_string $launch_command;
    sleep 1;
    send_key 'ret';

    my $opened = atspi_result 'wait-open', $timeout;
    my $open_seconds = time - $started;
    my $metric = {
        category => (split m{\s*/\s*}, $category, 2)[0],
        name => (split m{\s*/\s*}, $category, 2)[1] // $category,
        launcher => $command,
        status => $opened->{status},
        action => $action // 'Open and close',
        open_seconds => sprintf('%.2f', $open_seconds) + 0,
        mem_available_before_mib => $baseline->{mem_available_mib},
        mem_available_after_open_mib => $opened->{mem_available_mib},
        settled_pss_mib => $opened->{settled_pss_mib},
        accessible_window => $opened->{accessible_window} ? JSON::PP::true : JSON::PP::false,
        accessible_application => $opened->{application},
        accessible_window_name => $opened->{window},
        accessible_children => $opened->{accessible_children},
    };
    if ($opened->{status} ne 'passed') {
        $metric->{error} = $opened->{error};
        push @application_metrics, $metric;
        die "'$command' did not expose an accessible application window within $timeout seconds";
    }
    return $metric;
}

sub close_exercised_application {
    my ($metric) = @_;
    my $command = $metric->{launcher};
    my $is_browser = defined($command) && (
        $command =~ /(?:^|\s)(?:brave|chromium|firefox|big-webapps-exec)(?:\s|$)/
          || $command =~ /(?:^|\s)gtk-launch\s+(?:brave|chromium|firefox)-/
    );

    my $started = time;
    send_key 'alt-f4';
    my $closed = atspi_result 'wait-close', 8;
    if ($closed->{status} ne 'passed' && $is_browser) {
        send_key 'ctrl-q';
        sleep 1;
        send_key 'ret';
        $closed = atspi_result 'wait-close', 12;
    }
    $metric->{close_seconds} = sprintf('%.2f', time - $started) + 0;
    $metric->{mem_available_after_close_mib} = $closed->{mem_available_mib};
    if ($closed->{status} ne 'passed') {
        $metric->{status} = 'failed';
        $metric->{error} = $closed->{error};
        push @application_metrics, $metric;
        die "'$command' left an accessible application window open";
    }
    push @application_metrics, $metric;
    record_info "$metric->{name} / metrics",
      sprintf('Opened in %.2f s, closed in %.2f s, PSS after opening: %s MiB',
        $metric->{open_seconds}, $metric->{close_seconds}, $metric->{settled_pss_mib} // 'not available');
}

sub open_command_application {
    my ($category, $command, $timeout) = @_;
    my $metric = begin_application $category, $command, $timeout;
    close_exercised_application $metric;
}

sub open_command_application_if_available {
    my ($category, $command, $timeout) = @_;
    my ($executable) = split /\s+/, $command;
    unless (command_available($executable)) {
        skip_missing_application $category, $command, $executable;
        return;
    }
    open_command_application $category, $command, $timeout;
}

sub open_command_smoke {
    my ($category, $command) = @_;
    open_command_application $category, $command, 30;
}

sub open_command_smoke_if_available {
    my ($category, $command) = @_;
    my ($executable) = split /\s+/, $command;
    unless (command_available($executable)) {
        skip_missing_application $category, $command, $executable;
        return;
    }
    open_command_smoke $category, $command;
}

sub open_desktop_entry_if_available {
    my ($category, $entry, $required_command) = @_;
    unless (command_available('gtk-launch')) {
        record_info "$category / skipped", 'gtk-launch is not installed';
        push @application_metrics, {category => $category, name => $entry, launcher => "gtk-launch $entry", status => 'skipped', action => 'gtk-launch absent'};
        return;
    }
    if (defined($required_command) && !command_available($required_command)) {
        record_info "$category / skipped", "Executable '$required_command' is not installed";
        push @application_metrics, {category => $category, name => $entry, launcher => "gtk-launch $entry", status => 'skipped', action => "Executable '$required_command' absent"};
        return;
    }
    unless ($available_desktop_entries{$entry}) {
        record_info "$category / skipped", "Desktop entry '$entry.desktop' is not installed";
        push @application_metrics, {category => $category, name => $entry, launcher => "gtk-launch $entry", status => 'skipped', action => 'Desktop entry absent'};
        return;
    }
    open_command_smoke $category, "gtk-launch $entry";
}

sub exercise_writer {
    my $metric = begin_application 'Escritório / LibreOffice Writer',
      'gtk-launch libreoffice-writer', 30, 'Type text, save an ODT document and close it';
    # LibreOffice shows a first-run welcome window on a fresh live session.
    send_key 'esc';
    sleep 2;
    assert_screen_change { type_string 'Teste de escrita do openQA BigLinux' };
    assert_screen_change { send_key 'ctrl-shift-s' };
    sleep 3;
    # The save dialog starts with the filename selected and the Documents folder.
    send_key 'ctrl-a';
    type_string 'openqa-writer-smoke';
    assert_screen_change { send_key 'ret' };
    sleep 3;
    # If saving failed, Alt+F4 leaves a confirmation dialog and the desktop
    # assertion below fails instead of silently discarding the document.
    close_exercised_application $metric;
}

sub upload_application_metrics {
    return if $metrics_uploaded;
    my $payload = encode_json({
        schema_version => 1,
        system => {
            kernel => $kernel_version,
            desktop => 'KDE Plasma',
            accessibility_bus => 'Active and validated with AT-SPI',
        },
        applications => \@application_metrics,
    });
    my $encoded = encode_base64($payload, '');

    select_console 'root-virtio-terminal';
    type_string "printf '%s' '$encoded' | base64 --decode > /tmp/application-metrics.json && printf '__OA_METRICS_READY__\\n'\n";
    wait_serial '__OA_METRICS_READY__', timeout => 15;
    upload_logs '/tmp/application-metrics.json', log_name => 'application-metrics.json';
    $metrics_uploaded = 1;
    select_console 'sut';
}

sub post_run_hook {
    upload_application_metrics;
}

sub post_fail_hook {
    upload_application_metrics;
}

sub run {
    # Inventory the guest once over the virtio serial console.  Missing
    # optional packages are recorded and skipped; a present package still
    # has to pass the graphical launch/close check below.
    prepare_accessibility;
    discover_commands qw(
      dolphin konsole brave chromium libreoffice bigocrpdf okular simple-scan
      bigocrimage gimp gwenview xdvi rustdesk firefox kmines lutris kpat steam
      bigaudio bigvideo bigcam big-audio-converter-gui big-video-converter-gui
      bigaudioimprove gnome-network-displays kdenlive strawberry smplayer uxplay
      guvcview pamac-manager big-store bigterminal bigfiles bigstyle-gui
      bigcontrolcenter big-parental-controls kmenuedit big-driver-manager htop
      resources big-optimizer-gui ashyterm kate bigeditor gnome-calculator spectacle ark
      krunner plasma-print-queue tts-selected-text kfind scrcpy
      plasma-emojier gtk-launch big-webapps-gui big-webapps-exec
    );
    discover_desktop_entries qw(
      libreoffice-base
      libreoffice-calc
      libreoffice-draw
      libreoffice-impress
      libreoffice-math
      libreoffice-writer
      brave-forum.biglinux.com.br__-Default
      brave-calendar.google.com__-Default
      brave-www.deezer.com__-Default
      brave-discord.com__-Default
      brave-drive.google.com__-Default
      brave-meet.jit.si__-Default
      brave-snapdrop.net__-Default
      brave-open.spotify.com__browse_featured-Default
      brave-webz.telegram.org__-Default
      brave-web.whatsapp.com__-Default
    );

    # Keep the existing focused smoke checks for the three original apps.
    open_command_application_if_available 'Sistema / Dolphin', 'dolphin', 30;
    open_command_application_if_available 'Sistema / Konsole', 'konsole', 30;
    open_command_application_if_available 'Internet / Brave', 'brave about:blank', 45;

    # Office and document viewers shown under Escritório.
    open_desktop_entry_if_available 'Escritório / LibreOffice Base', 'libreoffice-base';
    open_desktop_entry_if_available 'Escritório / LibreOffice Calc', 'libreoffice-calc';
    open_desktop_entry_if_available 'Escritório / LibreOffice Draw', 'libreoffice-draw';
    open_desktop_entry_if_available 'Escritório / LibreOffice Impress', 'libreoffice-impress';
    open_desktop_entry_if_available 'Escritório / LibreOffice Math', 'libreoffice-math';
    if ($available_desktop_entries{'libreoffice-writer'}) {
        exercise_writer;
    }
    else {
        record_info 'Escritório / LibreOffice Writer / skipped',
          "Desktop entry 'libreoffice-writer.desktop' is not installed";
        push @application_metrics, {
            category => 'Escritório',
            name => 'LibreOffice Writer',
            launcher => 'gtk-launch libreoffice-writer',
            status => 'skipped',
            action => 'Desktop entry absent',
        };
    }
    open_command_smoke_if_available 'Escritório / OCR PDF', 'bigocrpdf';
    open_command_smoke_if_available 'Escritório / PDF viewer', 'okular';

    # Graphics applications.
    open_command_smoke_if_available 'Gráficos / document scanner', 'simple-scan';
    open_command_smoke_if_available 'Gráficos / image OCR', 'bigocrimage';
    open_command_smoke_if_available 'Gráficos / GIMP', 'gimp';
    open_command_smoke_if_available 'Gráficos / Gwenview', 'gwenview';
    open_command_smoke_if_available 'Gráficos / XDvi', 'xdvi';

    # Internet applications.
    open_command_smoke_if_available 'Internet / RustDesk', 'rustdesk';
    open_command_smoke_if_available 'Internet / Chromium', 'chromium';
    open_command_smoke_if_available 'Internet / Brave', 'brave about:blank';
    open_command_smoke_if_available 'Internet / Firefox', 'firefox about:blank';

    # Games.
    open_command_smoke_if_available 'Jogos / Mines', 'kmines';
    open_command_smoke_if_available 'Jogos / Lutris', 'lutris';
    open_command_smoke_if_available 'Jogos / KPatience', 'kpat';
    open_command_smoke_if_available 'Jogos / Steam', 'steam';

    # Multimedia applications.
    open_command_smoke_if_available 'Multimídia / Big Audio Player', 'bigaudio';
    open_command_smoke_if_available 'Multimídia / Big Video Player', 'bigvideo';
    open_command_smoke_if_available 'Multimídia / BigCam', 'bigcam';
    open_command_smoke_if_available 'Multimídia / audio converter', 'big-audio-converter-gui';
    open_command_smoke_if_available 'Multimídia / video converter', 'big-video-converter-gui';
    open_command_smoke_if_available 'Multimídia / noise filter', 'bigaudioimprove';
    open_command_smoke_if_available 'Multimídia / GNOME Network Displays', 'gnome-network-displays';
    open_command_smoke_if_available 'Multimídia / Kdenlive', 'kdenlive';
    open_command_smoke_if_available 'Multimídia / Strawberry', 'strawberry';
    open_command_smoke_if_available 'Multimídia / SMPlayer', 'smplayer';
    open_command_smoke_if_available 'Multimídia / UxPlay', 'uxplay';
    open_command_smoke_if_available 'Multimídia / Guvcview', 'guvcview';

    # System applications.
    open_command_smoke_if_available 'Sistema / updates', 'pamac-manager --updates';
    open_command_smoke_if_available 'Sistema / Big Store', 'big-store';
    open_command_smoke_if_available 'Sistema / Big Terminal', 'bigterminal';
    open_command_smoke_if_available 'Sistema / BigFiles', 'bigfiles';
    open_command_smoke_if_available 'Sistema / BigStyle', 'bigstyle-gui';
    open_command_smoke_if_available 'Sistema / control center', 'bigcontrolcenter';
    open_command_smoke_if_available 'Sistema / parental controls', 'big-parental-controls';
    open_command_smoke_if_available 'Sistema / menu editor', 'kmenuedit';
    open_command_smoke_if_available 'Sistema / file manager', 'dolphin';
    open_command_smoke_if_available 'Sistema / driver manager', 'big-driver-manager';
    open_command_smoke_if_available 'Sistema / Htop', 'htop';
    open_command_smoke_if_available 'Sistema / resources', 'resources';
    open_command_smoke_if_available 'Sistema / optimizer', 'big-optimizer-gui';
    open_command_smoke_if_available 'Sistema / Pamac', 'pamac-manager';
    open_command_smoke_if_available 'Sistema / terminal', 'konsole';
    open_command_smoke_if_available 'Sistema / Ashy Terminal', 'ashyterm';

    # Utility applications.
    open_command_smoke_if_available 'Utilitários / notes', 'kate';
    open_command_smoke_if_available 'Utilitários / BigEditor', 'bigeditor';
    open_command_smoke_if_available 'Utilitários / calculator', 'gnome-calculator';
    open_command_smoke_if_available 'Utilitários / screenshot', 'spectacle';
    open_command_smoke_if_available 'Utilitários / archive manager', 'ark';
    open_command_smoke_if_available 'Utilitários / Run', 'krunner';
    open_command_smoke_if_available 'Utilitários / image OCR', 'bigocrimage';
    open_command_smoke_if_available 'Utilitários / print queue', 'plasma-print-queue';
    open_command_smoke_if_available 'Utilitários / driver manager', 'big-driver-manager';
    open_command_smoke_if_available 'Utilitários / speech', 'tts-selected-text';
    open_command_smoke_if_available 'Utilitários / file search', 'kfind';
    open_command_smoke_if_available 'Utilitários / scrcpy', 'scrcpy';
    open_command_smoke_if_available 'Utilitários / emoji selector', 'plasma-emojier';

    # WebApps use exact desktop IDs because their launcher requires the full
    # Exec line generated in each desktop entry.
    open_command_smoke_if_available 'Webapps / manager', 'big-webapps-gui';
    open_desktop_entry_if_available 'Webapps / BigLinux Forum', 'brave-forum.biglinux.com.br__-Default', 'big-webapps-exec';
    open_desktop_entry_if_available 'Webapps / Calendar', 'brave-calendar.google.com__-Default', 'big-webapps-exec';
    open_desktop_entry_if_available 'Webapps / Deezer', 'brave-www.deezer.com__-Default', 'big-webapps-exec';
    open_desktop_entry_if_available 'Webapps / Discord', 'brave-discord.com__-Default', 'big-webapps-exec';
    open_desktop_entry_if_available 'Webapps / Drive', 'brave-drive.google.com__-Default', 'big-webapps-exec';
    open_desktop_entry_if_available 'Webapps / Jitsi Meet', 'brave-meet.jit.si__-Default', 'big-webapps-exec';
    open_desktop_entry_if_available 'Webapps / Snapdrop', 'brave-snapdrop.net__-Default', 'big-webapps-exec';
    open_desktop_entry_if_available 'Webapps / Spotify', 'brave-open.spotify.com__browse_featured-Default', 'big-webapps-exec';
    open_desktop_entry_if_available 'Webapps / Telegram', 'brave-webz.telegram.org__-Default', 'big-webapps-exec';
    open_desktop_entry_if_available 'Webapps / WhatsApp', 'brave-web.whatsapp.com__-Default', 'big-webapps-exec';
}

1;
