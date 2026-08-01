# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

my %available_commands;

sub discover_commands {
    my (@commands) = @_;

    select_console 'root-virtio-terminal';
    for my $command (@commands) {
        # Do not use script_run here: its shell-echo marker is sensitive to
        # bracketed/ANSI prompt output on the live console.  An explicit
        # marker gives us a small, deterministic protocol for both outcomes.
        type_string "if command -v '$command' >/dev/null 2>&1; then printf '__OA_PRESENT__\\n'; else printf '__OA_ABSENT__\\n'; fi\\n";
        my $result = wait_serial qr/__OA_(?:PRESENT|ABSENT)__/, timeout => 15;
        die "command availability probe timed out for '$command'" unless defined $result;
        wait_serial '# ', no_regex => 1, timeout => 15;
        $available_commands{$command} = $result =~ /__OA_PRESENT__/;
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

sub skip_missing_application {
    my ($category, $search, $command) = @_;
    record_info "$category / skipped", "Executable '$command' is not installed; '$search' is not tested";
}

sub close_exercised_application {
    my ($command) = @_;
    my $is_browser = defined($command) && $command =~ /(?:^|\s)(?:brave|chromium|firefox|big-webapps-exec)(?:\s|$)/;

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
    sleep 5;
    close_exercised_application $command;
}

sub open_command_smoke_if_available {
    my ($category, $command) = @_;
    unless (command_available($command)) {
        skip_missing_application $category, $command, $command;
        return;
    }
    open_command_smoke $category, $command;
}

sub open_menu_application {
    my ($category, $search, $timeout, $command) = @_;

    record_info $category, "Open the menu entry matching '$search'";
    send_key 'meta';
    sleep 1;
    type_string $search;
    sleep 1;
    assert_screen_change { send_key 'ret' };
    sleep 5;
    close_exercised_application $command;
}

sub open_menu_application_if_available {
    my ($category, $search, $command, $timeout) = @_;
    unless (command_available($command)) {
        skip_missing_application $category, $search, $command;
        return;
    }
    open_menu_application $category, $search, $timeout, $command;
}

sub exercise_writer {
    record_info 'LibreOffice Writer', 'Type text, save an ODT document and close it';
    send_key 'meta';
    sleep 1;
    type_string 'LibreOffice Writer';
    sleep 1;
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
      plasma-emojier big-webapps-exec
    );

    # Keep the existing focused smoke checks for the three original apps.
    open_command_application_if_available 'Sistema / Dolphin', 'dolphin', 'biglinux-dolphin', 30;
    open_command_application_if_available 'Sistema / Konsole', 'konsole', 'biglinux-konsole', 30;
    open_command_application_if_available 'Internet / Brave', 'brave about:blank', 'biglinux-brave', 45;

    # Office and document viewers shown under Escritório.
    open_menu_application_if_available 'Escritório / LibreOffice Base', 'LibreOffice Base', 'libreoffice', 45;
    open_menu_application_if_available 'Escritório / LibreOffice Calc', 'LibreOffice Calc', 'libreoffice', 45;
    open_menu_application_if_available 'Escritório / LibreOffice Draw', 'LibreOffice Draw', 'libreoffice', 45;
    open_menu_application_if_available 'Escritório / LibreOffice Impress', 'LibreOffice Impress', 'libreoffice', 45;
    open_menu_application_if_available 'Escritório / LibreOffice Math', 'LibreOffice Math', 'libreoffice', 45;
    if (command_available('libreoffice')) {
        exercise_writer;
    }
    else {
        skip_missing_application 'Escritório', 'LibreOffice Writer', 'libreoffice';
    }
    open_menu_application_if_available 'Escritório / OCR PDF', 'Recognize text in scanned PDF', 'bigocrpdf', 45;
    open_menu_application_if_available 'Escritório / PDF viewer', 'Okular', 'okular', 45;

    # Graphics applications.
    open_menu_application_if_available 'Gráficos / document scanner', 'Document Scanner', 'simple-scan', 45;
    open_menu_application_if_available 'Gráficos / image OCR', 'Extract text from image', 'bigocrimage', 45;
    open_menu_application_if_available 'Gráficos / GIMP', 'GNU Image Manipulation Program', 'gimp', 60;
    open_menu_application_if_available 'Gráficos / Gwenview', 'Gwenview', 'gwenview', 45;
    open_command_smoke_if_available 'Gráficos / XDvi', 'xdvi';

    # Internet applications.
    open_menu_application_if_available 'Internet / RustDesk', 'Remote Desktop RustDesk', 'rustdesk', 45;
    open_menu_application_if_available 'Internet / Chromium', 'Chromium', 'chromium', 45;
    open_menu_application_if_available 'Internet / Brave', 'Brave', 'brave', 45;
    open_menu_application_if_available 'Internet / Firefox', 'Firefox', 'firefox', 60;

    # Games.
    open_menu_application_if_available 'Jogos / Mines', 'Mines', 'kmines', 45;
    open_menu_application_if_available 'Jogos / Lutris', 'Lutris', 'lutris', 60;
    open_menu_application_if_available 'Jogos / KPatience', 'KPatience', 'kpat', 45;
    open_menu_application_if_available 'Jogos / Steam', 'Steam', 'steam', 60;

    # Multimedia applications.
    open_menu_application_if_available 'Multimídia / Big Audio Player', 'Big Audio Player', 'bigaudio', 45;
    # Launch the executable directly: free-text menu search can select a web
    # result instead of the BigLinux desktop entry when both names overlap.
    open_command_smoke_if_available 'Multimídia / Big Video Player', 'bigvideo';
    open_command_smoke_if_available 'Multimídia / BigCam', 'bigcam';
    open_menu_application_if_available 'Multimídia / audio converter', 'Audio Converter', 'big-audio-converter-gui', 45;
    open_menu_application_if_available 'Multimídia / video converter', 'Video Converter', 'big-video-converter-gui', 45;
    open_menu_application_if_available 'Multimídia / noise filter', 'Filter noise', 'bigaudioimprove', 45;
    open_menu_application_if_available 'Multimídia / GNOME Network Displays', 'GNOME Network Displays', 'gnome-network-displays', 45;
    open_menu_application_if_available 'Multimídia / Kdenlive', 'Kdenlive', 'kdenlive', 60;
    open_menu_application_if_available 'Multimídia / Strawberry', 'Music Player Strawberry', 'strawberry', 60;
    open_menu_application_if_available 'Multimídia / SMPlayer', 'Video Player SMPlayer', 'smplayer', 45;
    open_menu_application_if_available 'Multimídia / UxPlay', 'UxPlay', 'uxplay', 45;
    open_menu_application_if_available 'Multimídia / Guvcview', 'Webcam Guvc', 'guvcview', 45;

    # System applications.
    open_menu_application_if_available 'Sistema / updates', 'Software Update', 'pamac-manager', 60;
    open_menu_application_if_available 'Sistema / Big Store', 'Big Store', 'big-store', 60;
    open_menu_application_if_available 'Sistema / Big Terminal', 'Big Terminal', 'bigterminal', 45;
    open_menu_application_if_available 'Sistema / BigFiles', 'BigFiles', 'bigfiles', 45;
    open_menu_application_if_available 'Sistema / BigStyle', 'BigStyle', 'bigstyle-gui', 45;
    open_menu_application_if_available 'Sistema / control center', 'Control Center', 'bigcontrolcenter', 60;
    open_menu_application_if_available 'Sistema / parental controls', 'Parental Controls', 'big-parental-controls', 45;
    open_menu_application_if_available 'Sistema / menu editor', 'Menu Editor', 'kmenuedit', 45;
    open_menu_application_if_available 'Sistema / file manager', 'Dolphin', 'dolphin', 45;
    open_menu_application_if_available 'Sistema / driver manager', 'Hardware Management', 'big-driver-manager', 60;
    open_menu_application_if_available 'Sistema / Htop', 'Htop', 'htop', 30;
    open_menu_application_if_available 'Sistema / resources', 'Keep an eye on system resources', 'resources', 45;
    open_menu_application_if_available 'Sistema / optimizer', 'BigLinux Optimizer', 'big-optimizer-gui', 45;
    open_menu_application_if_available 'Sistema / Pamac', 'Pamac', 'pamac-manager', 60;
    open_menu_application_if_available 'Sistema / terminal', 'Konsole', 'konsole', 30;
    open_menu_application_if_available 'Sistema / Ashy Terminal', 'Ashy Terminal', 'ashyterm', 45;

    # Utility applications.
    open_menu_application_if_available 'Utilitários / notes', 'Kate', 'kate', 45;
    open_menu_application_if_available 'Utilitários / BigEditor', 'BigEditor', 'bigeditor', 45;
    open_menu_application_if_available 'Utilitários / calculator', 'Calculator', 'gnome-calculator', 45;
    open_menu_application_if_available 'Utilitários / screenshot', 'Spectacle', 'spectacle', 45;
    open_menu_application_if_available 'Utilitários / archive manager', 'Ark', 'ark', 45;
    open_menu_application_if_available 'Utilitários / Run', 'Run', 'krunner', 30;
    open_menu_application_if_available 'Utilitários / image OCR', 'Extract text from image', 'bigocrimage', 45;
    open_menu_application_if_available 'Utilitários / print queue', 'Print Queue', 'plasma-print-queue', 45;
    open_menu_application_if_available 'Utilitários / driver manager', 'Hardware Management', 'big-driver-manager', 45;
    open_menu_application_if_available 'Utilitários / speech', 'Speech or stop selected text', 'tts-selected-text', 45;
    open_menu_application_if_available 'Utilitários / file search', 'KFind', 'kfind', 45;
    open_menu_application_if_available 'Utilitários / scrcpy', 'scrcpy', 'scrcpy', 45;
    open_menu_application_if_available 'Utilitários / scrcpy console', 'scrcpy (console)', 'scrcpy', 45;
    open_menu_application_if_available 'Utilitários / emoji selector', 'Emoji Selector', 'plasma-emojier', 45;

    # Webapps. The launch check intentionally does not depend on network content;
    # it verifies that each installed webapp entry opens its browser window.
    open_menu_application_if_available 'Webapps / manager', 'Add and Remove WebApps', 'big-webapps-exec', 60;
    open_menu_application_if_available 'Webapps / BigLinux Forum', 'BigLinux Forum', 'big-webapps-exec', 60;
    open_menu_application_if_available 'Webapps / Calendar', 'Calendar', 'big-webapps-exec', 60;
    open_menu_application_if_available 'Webapps / Deezer', 'Deezer music', 'big-webapps-exec', 60;
    open_menu_application_if_available 'Webapps / Discord', 'Discord', 'big-webapps-exec', 60;
    open_menu_application_if_available 'Webapps / Drive', 'Drive', 'big-webapps-exec', 60;
    open_menu_application_if_available 'Webapps / Jitsi Meet', 'Jitsi Meet', 'big-webapps-exec', 60;
    open_menu_application_if_available 'Webapps / Snapdrop', 'Snapdrop', 'big-webapps-exec', 60;
    open_menu_application_if_available 'Webapps / Spotify', 'Spotify', 'big-webapps-exec', 60;
    open_menu_application_if_available 'Webapps / Telegram', 'Telegram', 'big-webapps-exec', 60;
    open_menu_application_if_available 'Webapps / WhatsApp', 'WhatsApp', 'big-webapps-exec', 60;
}

1;
