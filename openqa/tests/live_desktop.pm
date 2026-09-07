# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
# The comments below name translated labels; the pragma keeps the file valid
# under the workflow's non-ASCII check.
use utf8;
use testapi;
use atspi;

sub test_flags {
    return {fatal => 1};
}

# The only module in the gate that still looks at pixels, and only to know
# which page of the first-boot wizard is on screen. Nothing here is chosen by
# coordinate any more; every choice is made with the keyboard, from the
# wizard's own default selection.
#
# Why not accessibility, like every other module: the wizard is
# GTK4/libadwaita and labels its controls for screen readers (18 uses of
# Gtk.AccessibleProperty.LABEL in /usr/share/biglinux/livecd/ui), but the live
# session starts with a broken accessibility bus - /run/user/1000/at-spi is
# empty and toolkit-accessibility is false - and GTK only registers on the bus
# while starting up. atspi->prepare repairs the bus, but the wizard has been
# running for a while by then and never reconnects. Measured on
# biglinux_2026-08-19_k618: with the bus repaired and a six-minute budget, the
# probe reported "all roles observed: none". That is a defect in the ISO, not
# merely an inconvenience here - Orca is in the autostart of this same session
# and would be just as blind.
#
# Why no clicks: the language page orders its tiles by the boot-time locale
# suggestion (suggested_locale.language_sort_key, first the suggested locale,
# then en_US, pt_BR, es_ES), so the same ISO on the same machine puts
# "Português, Brazil" first on one boot and second on the next. Job 14 and job
# 15 differed exactly that way. A needle with a click point on a tile is
# therefore a coin toss between installing Portuguese and installing English,
# and a green run proves nothing about which one happened. Two needles had
# already been recorded over the wrong tile before this was understood.
sub run {
    # This is the first module: the budget covers the GRUB countdown, the live
    # boot, and the wizard appearing. The needle deliberately matches only the
    # header icons and the search box - the parts of the page that do not move.
    assert_screen 'biglinux-live-wizard', 360;

    # The wizard routes any printable key to its search box from anywhere in
    # the window (LanguageView.handle_global_key_press), filters as it types,
    # selects the first match, and activates it on Return. "Brazil" matches one
    # entry, "Portuguese - Brazil", so the selection cannot depend on where the
    # tile happens to be. Typed in ASCII on purpose: the accented name would
    # have to survive the VNC keymap.
    wait_screen_change(sub { type_string 'Brazil' }, 15)
      or die 'the wizard did not filter its language list while typing';

    # Wait for the filter to settle before activating anything. It runs on a
    # 50 ms debounce and moves the selection to the first match from an idle
    # callback (LanguageView._trigger_filter_update), so a Return sent right
    # after the last keystroke activates the *unfiltered* first tile - the
    # boot-time locale suggestion. Job 16 selected English exactly that way,
    # and the next page's assertion caught it: with English there is only the
    # "US" layout, the keyboard page has nothing to ask, and the run arrived at
    # the desktop layout page still in English.
    wait_still_screen stilltime => 2, timeout => 15;
    wait_screen_change(sub { send_key 'ret' }, 30)
      or die 'the wizard did not accept the language chosen by search';

    # Every remaining page selects its first item when it appears
    # (BaseItemView._select_first_item, KeyboardView._select_first_and_announce)
    # and activates the selection on Return, so the default is what a plain
    # Return picks:
    #   - keyboard: the layout derived from the language, ahead of "US";
    #   - desktop layout: "classic", the first line of list-desktops.sh on KDE,
    #     which is the same layout this module used to click by coordinate;
    #   - theme: the first theme of list-themes.sh.
    for my $page ('biglinux-live-keyboard', 'biglinux-live-desktop-layout',
        'biglinux-live-theme') {
        assert_screen $page, 60;
        wait_screen_change(sub { send_key 'ret' }, 30)
          or die "the wizard did not accept the default on $page";
    }

    # Let the session settle; everything after this point works through
    # accessibility and the serial console.
    wait_still_screen stilltime => 5, timeout => 120;
}

1;
