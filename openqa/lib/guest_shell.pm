# SPDX-License-Identifier: GPL-2.0-or-later

# Typing commands into a guest console, safely.
#
# Both helpers exist because of the same property of a serial console: what is
# typed is echoed back on the very channel that is being read. Six modules had
# grown their own copy of each.
package guest_shell;

use Mojo::Base -strict, -signatures;
use Exporter 'import';

our @EXPORT_OK = qw(marker_format shell_quote);

# A marker written as octal escapes, for printf.
#
# A wait_serial for a literal marker is satisfied by the tty echo of the
# command line that contains it, so the test passes before the command runs -
# or when it fails. Typed as escapes, the marker itself only ever reaches the
# console from printf's output, which means the command reached its end.
sub marker_format ($marker) {
    return join '', map { sprintf '\\%03o', ord } split //, $marker;
}

# A single-quoted shell word, for values that are not under our control (page
# titles, application names, paths read from the guest).
sub shell_quote ($value) {
    $value =~ s/'/'"'"'/g;
    return "'$value'";
}

1;
