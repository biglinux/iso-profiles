# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
# The page titles below are the accessible names the wizard publishes, and two
# of them are translated.
use utf8;
use testapi;
use atspi;
use guest_shell qw(marker_format shell_quote);

sub test_flags {
    return {fatal => 1};
}

# Every page of the wizard publishes a table whose accessible name is the page
# title, so each page is recognised by what it is rather than by a picture of
# it. Both the English and the translated name are listed: the wizard switches
# language the moment one is chosen, and the probe folds case and accents.
my %PAGE = (
    language => ['Search for a language', 'Pesquise um idioma'],
    keyboard => ['Choose Your Keyboard Layout', 'Escolha o layout do teclado'],
    layout => ['Choose a Desktop Layout', 'Escolha um layout da área de trabalho'],
    theme => ['Choose a System Theme', 'Escolha um tema do sistema'],
);

# The first-boot wizard, driven through accessibility and the keyboard.
#
# Nothing here is chosen by coordinate. The language page orders its tiles by
# the boot-time locale suggestion (suggested_locale.language_sort_key: the
# suggested locale first, then en_US, pt_BR, es_ES), so the same ISO on the
# same machine puts "Português, Brazil" first on one boot and second on the
# next. A recorded click point on a tile is therefore a coin toss between
# installing Portuguese and installing English, and a green run proves nothing
# about which one happened - two needles had been recorded over the wrong tile
# before that was understood.
#
# The tiles cannot be activated through accessibility either: GTK4 exposes them
# as table cells with no action and no focus. What the wizard does offer is
# type-to-search from anywhere in the window
# (LanguageView.handle_global_key_press), which filters, selects the first
# match and activates it on Return. Filtering by text cannot select the wrong
# language, whatever the order.
sub run {
    # The first module: this covers the GRUB countdown, the live boot and the
    # session coming up, and it is the accessibility bus that answers - not a
    # picture of a wizard whose icons change between builds.
    atspi->install;
    atspi->reset_baseline;
    atspi->wait_widget('table', $PAGE{language}, 300);

    # Two things have to be true before Return is pressed, and each one cost a
    # failed run to learn. The filter has to have been typed correctly: at the
    # default speed a runner dropped a keystroke and the box read "Bazil", so
    # nothing matched and Return activated nothing. And the filter has to have
    # been applied: it runs on a 50 ms debounce and moves the selection from an
    # idle callback, so a Return sent immediately activates the *unfiltered*
    # first tile, which is the boot-time suggestion.
    #
    # The retry is what makes this self-correcting, and the next page appearing
    # is what says it worked. Not a changed frame buffer: a repaint is not a
    # navigation, and the wizard animates.
    my $chosen = 0;
    for (1 .. 3) {
        # BackSpace reaches the search box from anywhere in the window.
        send_key 'backspace' for 1 .. 12;
        type_string 'Brazil', max_interval => 20;
        send_key 'ret';
        my $next = eval { atspi->wait_widget('table', $PAGE{keyboard}, 20) };
        next unless ref $next eq 'HASH' && ($next->{status} // '') eq 'passed';
        $chosen = 1;
        last;
    }
    $chosen or die 'the wizard did not accept the language chosen by search';

    # Every remaining page selects its first item when it appears
    # (BaseItemView._select_first_item, KeyboardView._select_first_and_announce)
    # and activates the selection on Return, so a plain Return takes the
    # default: the keyboard layout derived from the language, ahead of "US";
    # "classic", the first line of list-desktops.sh on KDE; and the first theme
    # of list-themes.sh.
    # The language page has already been left, so the keyboard page is where we
    # are. Each Return takes the default and the next page's own table is the
    # proof it was taken.
    my @remaining = (['keyboard', 'layout'], ['layout', 'theme'], ['theme', undef]);
    for my $step (@remaining) {
        my ($current, $next) = @$step;
        atspi->wait_widget('table', $PAGE{$current}, 60);
        send_key 'ret';
        next unless defined $next;
        atspi->wait_widget('table', $PAGE{$next}, 60);
    }

    # Choosing the theme ends the wizard, and the desktop session takes its
    # place.
    #
    # The accessibility bus cannot answer whether that happened. It belongs to
    # the graphical session (at-spi-dbus-bus.service is
    # PartOf=graphical-session.target), so the wizard's session takes it down
    # on the way out, and a probe during the transition fails identically
    # whether the wizard has gone or is still on screen - this loop used to
    # read that failure as success, and did. The process table has no such
    # ambiguity, and the console is not part of the graphical session.
    select_console 'user-virtio-terminal';
    my $closed = '__OA_WIZARD_CLOSED__';
    my $wizard = shell_quote('/usr/share/biglinux/livecd/main.py');
    type_string "for attempt in \$(seq 120); do pgrep -f $wizard >/dev/null || break; sleep 1; done; "
      . "pgrep -f $wizard >/dev/null || printf " . shell_quote(marker_format($closed) . '\\n');
    send_key 'ret';
    die 'the wizard did not close after the theme was chosen'
      unless defined wait_serial($closed, no_regex => 1, timeout => 150);
    select_console 'sut';
}

1;
