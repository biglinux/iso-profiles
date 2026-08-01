# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;

sub open_command_application {
    my ($command, $needle, $timeout) = @_;

    send_key 'alt-f2';
    sleep 1;
    type_string $command;
    sleep 1;
    assert_screen_change { send_key 'ret' };
    assert_screen $needle, $timeout;
    send_key 'alt-f4';
    sleep 2;
    send_key 'alt-f4';
    sleep 2;
}

sub open_command_smoke {
    my ($category, $command) = @_;

    record_info $category, "Run '$command' from the graphical command launcher";
    send_key 'alt-f2';
    sleep 1;
    type_string $command;
    assert_screen_change { send_key 'ret' };
    sleep 5;
    for (1 .. 4) {
        send_key 'alt-f4';
        sleep 2;
    }
    assert_screen 'biglinux-live-desktop', 30;
}

sub open_menu_application {
    my ($category, $search, $timeout) = @_;

    record_info $category, "Open the menu entry matching '$search'";
    send_key 'meta';
    sleep 1;
    type_string $search;
    sleep 1;
    assert_screen_change { send_key 'ret' };
    sleep 5;
    # A first-run dialog is closed by the first key; the remaining keys close
    # applications that open more than one top-level window.
    for (1 .. 4) {
        send_key 'alt-f4';
        sleep 2;
    }
    assert_screen 'biglinux-live-desktop', 30;
}

sub exercise_writer {
    record_info 'LibreOffice Writer', 'Type text, save an ODT document and close it';
    send_key 'meta';
    sleep 1;
    type_string 'LibreOffice Writer';
    sleep 1;
    assert_screen_change { send_key 'ret' } 60;
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
    send_key 'alt-f4';
    assert_screen 'biglinux-live-desktop', 30;
}

sub run {
    # Keep the existing focused smoke checks for the three original apps.
    open_command_application 'dolphin', 'biglinux-dolphin', 30;
    open_command_application 'konsole', 'biglinux-konsole', 30;
    open_command_application 'brave about:blank', 'biglinux-brave', 45;

    # Office and document viewers shown under Escritório.
    open_menu_application 'Escritório / LibreOffice Base', 'LibreOffice Base', 45;
    open_menu_application 'Escritório / LibreOffice Calc', 'LibreOffice Calc', 45;
    open_menu_application 'Escritório / LibreOffice Draw', 'LibreOffice Draw', 45;
    open_menu_application 'Escritório / LibreOffice Impress', 'LibreOffice Impress', 45;
    open_menu_application 'Escritório / LibreOffice Math', 'LibreOffice Math', 45;
    exercise_writer;
    open_menu_application 'Escritório / OCR PDF', 'Recognize text in scanned PDF', 45;
    open_menu_application 'Escritório / PDF viewer', 'Okular', 45;

    # Graphics applications.
    open_menu_application 'Gráficos / document scanner', 'Document Scanner', 45;
    open_menu_application 'Gráficos / image OCR', 'Extract text from image', 45;
    open_menu_application 'Gráficos / GIMP', 'GNU Image Manipulation Program', 60;
    open_menu_application 'Gráficos / Gwenview', 'Gwenview', 45;
    open_command_smoke 'Gráficos / XDvi', 'xdvi';

    # Internet applications.
    open_menu_application 'Internet / RustDesk', 'Remote Desktop RustDesk', 45;
    open_menu_application 'Internet / Chromium', 'Chromium', 45;
    open_menu_application 'Internet / Brave', 'Brave', 45;
    open_menu_application 'Internet / Firefox', 'Firefox', 60;

    # Games.
    open_menu_application 'Jogos / Mines', 'Mines', 45;
    open_menu_application 'Jogos / Lutris', 'Lutris', 60;
    open_menu_application 'Jogos / KPatience', 'KPatience', 45;
    open_menu_application 'Jogos / Steam', 'Steam', 60;

    # Multimedia applications.
    open_menu_application 'Multimídia / Big Audio Player', 'Big Audio Player', 45;
    open_menu_application 'Multimídia / Big Video Player', 'Big Video Player', 45;
    open_menu_application 'Multimídia / BigCam', 'BigCam', 45;
    open_menu_application 'Multimídia / audio converter', 'Audio Converter', 45;
    open_menu_application 'Multimídia / video converter', 'Video Converter', 45;
    open_menu_application 'Multimídia / noise filter', 'Filter noise', 45;
    open_menu_application 'Multimídia / GNOME Network Displays', 'GNOME Network Displays', 45;
    open_menu_application 'Multimídia / Kdenlive', 'Kdenlive', 60;
    open_menu_application 'Multimídia / Strawberry', 'Music Player Strawberry', 60;
    open_menu_application 'Multimídia / SMPlayer', 'Video Player SMPlayer', 45;
    open_menu_application 'Multimídia / UxPlay', 'UxPlay', 45;
    open_menu_application 'Multimídia / Guvcview', 'Webcam Guvc', 45;

    # System applications.
    open_menu_application 'Sistema / updates', 'Software Update', 60;
    open_menu_application 'Sistema / Big Store', 'Big Store', 60;
    open_menu_application 'Sistema / Big Terminal', 'Big Terminal', 45;
    open_menu_application 'Sistema / BigFiles', 'BigFiles', 45;
    open_menu_application 'Sistema / BigStyle', 'BigStyle', 45;
    open_menu_application 'Sistema / control center', 'Control Center', 60;
    open_menu_application 'Sistema / parental controls', 'Parental Controls', 45;
    open_menu_application 'Sistema / menu editor', 'Menu Editor', 45;
    open_menu_application 'Sistema / file manager', 'Dolphin', 45;
    open_menu_application 'Sistema / driver manager', 'Hardware Management', 60;
    open_menu_application 'Sistema / Htop', 'Htop', 30;
    open_menu_application 'Sistema / resources', 'Keep an eye on system resources', 45;
    open_menu_application 'Sistema / optimizer', 'BigLinux Optimizer', 45;
    open_menu_application 'Sistema / Pamac', 'Pamac', 60;
    open_menu_application 'Sistema / terminal', 'Konsole', 30;
    open_menu_application 'Sistema / Ashy Terminal', 'Ashy Terminal', 45;

    # Utility applications.
    open_menu_application 'Utilitários / notes', 'Kate', 45;
    open_menu_application 'Utilitários / BigEditor', 'BigEditor', 45;
    open_menu_application 'Utilitários / calculator', 'Calculator', 45;
    open_menu_application 'Utilitários / screenshot', 'Spectacle', 45;
    open_menu_application 'Utilitários / archive manager', 'Ark', 45;
    open_menu_application 'Utilitários / Run', 'Run', 30;
    open_menu_application 'Utilitários / image OCR', 'Extract text from image', 45;
    open_menu_application 'Utilitários / print queue', 'Print Queue', 45;
    open_menu_application 'Utilitários / driver manager', 'Hardware Management', 60;
    open_menu_application 'Utilitários / speech', 'Speech or stop selected text', 45;
    open_menu_application 'Utilitários / file search', 'KFind', 45;
    open_menu_application 'Utilitários / scrcpy', 'scrcpy', 45;
    open_menu_application 'Utilitários / scrcpy console', 'scrcpy (console)', 45;
    open_menu_application 'Utilitários / emoji selector', 'Emoji Selector', 45;

    # Webapps. The launch check intentionally does not depend on network content;
    # it verifies that each installed webapp entry opens its browser window.
    open_menu_application 'Webapps / manager', 'Add and Remove WebApps', 60;
    open_menu_application 'Webapps / BigLinux Forum', 'BigLinux Forum', 60;
    open_menu_application 'Webapps / Calendar', 'Calendar', 60;
    open_menu_application 'Webapps / Deezer', 'Deezer music', 60;
    open_menu_application 'Webapps / Discord', 'Discord', 60;
    open_menu_application 'Webapps / Drive', 'Drive', 60;
    open_menu_application 'Webapps / Jitsi Meet', 'Jitsi Meet', 60;
    open_menu_application 'Webapps / Snapdrop', 'Snapdrop', 60;
    open_menu_application 'Webapps / Spotify', 'Spotify', 60;
    open_menu_application 'Webapps / Telegram', 'Telegram', 60;
    open_menu_application 'Webapps / WhatsApp', 'WhatsApp', 60;
}

1;
