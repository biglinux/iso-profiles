# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

my %available_commands;
my %available_desktop_entries;

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
    record_info 'WebApp inventory', @missing ?
      'Skipping absent desktop entries: ' . join(', ', @missing) :
      'All catalogued WebApp desktop entries are present';
}

sub skip_missing_application {
    my ($category, $search, $command) = @_;
    record_info "$category / skipped", "Executable '$command' is not installed; '$search' is not tested";
}

sub close_exercised_application {
    my ($command) = @_;
    my $is_browser = defined($command) && (
        $command =~ /(?:^|\s)(?:brave|chromium|firefox|big-webapps-exec)(?:\s|$)/
          || $command =~ /(?:^|\s)gtk-launch\s+(?:brave|chromium|firefox)-/
    );

    # Close only while the desktop is not visible.  This handles browser
    # windows one at a time without cascading into unrelated applications.
    for (1 .. 3) {
        send_key 'alt-f4';
        sleep 2;
        return if check_screen 'biglinux-live-desktop', 0;
        # Brave asks for confirmation when several tabs are open.  Esc
        # cancels that dialog, so browsers must confirm it with Enter.
        send_key($is_browser ? 'ret' : 'esc');
        sleep 2;
        return if check_screen 'biglinux-live-desktop', 0;
    }

    if ($is_browser) {
        # Brave/Chromium can reuse one process for several desktop entries.
        # Use a process-wide quit only after ordinary window closure failed.
        send_key 'ctrl-q';
        sleep 3;
        return if check_screen 'biglinux-live-desktop', 0;
        send_key 'ret';
        sleep 3;
        return if check_screen 'biglinux-live-desktop', 0;
    }

    assert_screen 'biglinux-live-desktop', 15;
}

sub open_command_application {
    my ($command, $needle, $timeout) = @_;

    send_key 'alt-f2';
    sleep 3;
    type_string $command;
    sleep 3;
    assert_screen_change { send_key 'ret' };
    assert_screen $needle, $timeout;
    close_exercised_application $command;
}

sub open_command_application_if_available {
    my ($category, $command, $needle, $timeout) = @_;
    my ($executable) = split /\s+/, $command;
    unless (command_available($executable)) {
        skip_missing_application $category, $command, $executable;
        return;
    }
    open_command_application $command, $needle, $timeout;
}

sub open_command_smoke {
    my ($category, $command) = @_;

    record_info $category, "Run '$command' from the graphical command launcher";
    send_key 'alt-f2';
    sleep 3;
    type_string $command;
    sleep 3;
    assert_screen_change { send_key 'ret' };
    my $deadline = time + 30;
    while (check_screen('biglinux-live-desktop', 0)) {
        die "'$command' did not leave a visible application window within 30 seconds"
          if time >= $deadline;
        sleep 1;
    }
    close_exercised_application $command;
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
    my ($category, $entry) = @_;
    unless (command_available('gtk-launch') && command_available('big-webapps-exec')) {
        record_info "$category / skipped", 'The WebApp desktop launcher is not installed';
        return;
    }
    unless ($available_desktop_entries{$entry}) {
        record_info "$category / skipped", "Desktop entry '$entry.desktop' is not installed";
        return;
    }
    open_command_smoke $category, "gtk-launch $entry";
}

sub exercise_writer {
    record_info 'LibreOffice Writer', 'Type text, save an ODT document and close it';
    send_key 'alt-f2';
    sleep 3;
    type_string 'libreoffice --writer';
    sleep 3;
    assert_screen_change { send_key 'ret' };
    sleep 12;
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
    close_exercised_application;
}

sub run {
    # Inventory the guest once over the virtio serial console.  Missing
    # optional packages are recorded and skipped; a present package still
    # has to pass the graphical launch/close check below.
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
    open_command_application_if_available 'Sistema / Dolphin', 'dolphin', 'biglinux-dolphin', 30;
    open_command_application_if_available 'Sistema / Konsole', 'konsole', 'biglinux-konsole', 30;
    open_command_application_if_available 'Internet / Brave', 'brave about:blank', 'biglinux-brave', 45;

    # Office and document viewers shown under Escritório.
    open_command_smoke_if_available 'Escritório / LibreOffice Base', 'libreoffice --base';
    open_command_smoke_if_available 'Escritório / LibreOffice Calc', 'libreoffice --calc';
    open_command_smoke_if_available 'Escritório / LibreOffice Draw', 'libreoffice --draw';
    open_command_smoke_if_available 'Escritório / LibreOffice Impress', 'libreoffice --impress';
    open_command_smoke_if_available 'Escritório / LibreOffice Math', 'libreoffice --math';
    if (command_available('libreoffice')) {
        exercise_writer;
    }
    else {
        skip_missing_application 'Escritório', 'LibreOffice Writer', 'libreoffice';
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
    open_desktop_entry_if_available 'Webapps / BigLinux Forum', 'brave-forum.biglinux.com.br__-Default';
    open_desktop_entry_if_available 'Webapps / Calendar', 'brave-calendar.google.com__-Default';
    open_desktop_entry_if_available 'Webapps / Deezer', 'brave-www.deezer.com__-Default';
    open_desktop_entry_if_available 'Webapps / Discord', 'brave-discord.com__-Default';
    open_desktop_entry_if_available 'Webapps / Drive', 'brave-drive.google.com__-Default';
    open_desktop_entry_if_available 'Webapps / Jitsi Meet', 'brave-meet.jit.si__-Default';
    open_desktop_entry_if_available 'Webapps / Snapdrop', 'brave-snapdrop.net__-Default';
    open_desktop_entry_if_available 'Webapps / Spotify', 'brave-open.spotify.com__browse_featured-Default';
    open_desktop_entry_if_available 'Webapps / Telegram', 'brave-webz.telegram.org__-Default';
    open_desktop_entry_if_available 'Webapps / WhatsApp', 'brave-web.whatsapp.com__-Default';
}

1;
