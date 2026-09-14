# SPDX-License-Identifier: GPL-2.0-or-later
use Mojo::Base 'basetest';
use testapi;
use atspi;
use Digest::SHA qw(sha256_hex);
use JSON::PP qw(encode_json);
use guest_shell qw(shell_quote);

my @results;
my $root;
my $nonce;
my $pid;
my $current;


sub test_flags { return {fatal => 0}; }

sub command_ok {
    my ($command, $timeout) = @_;
    my $status = atspi->run_command($command, $timeout // 30);
    die 'independent guest condition did not succeed'
      unless defined $status && $status == 0;
}

sub condition_ok {
    my ($condition) = @_;
    my $status = atspi->run_command_until($condition, 20);
    die 'functional postcondition was not reached' unless defined $status && $status == 0;
}

sub reader {
    my ($operation, $phrase) = @_;
    my @args = ('python3', '/tmp/openqa-orca-probe.py', $operation,
        '--state', "$root/reader.json", '--timeout', '10');
    push @args, ('--phrase', $phrase) if defined $phrase;
    my $status = atspi->run_command(join(' ', map { shell_quote($_) } @args)
      . ' > ' . shell_quote("$root/reader-result.json"), 40);
    unless (defined $status && $status == 0) {
        # This is the small structured result, not the private transcript/token.
        eval { atspi->upload_guest_file("$root/reader-result.json", 'orca-probe-error.json') };
        die "Orca observation '$operation' failed or is unsupported";
    }
    $current->{screen_reader} = 'presenter-passed' if $current && $operation eq 'check';
}

sub focus_role {
    my ($roles) = @_;
    my %allowed = map { $_ => 1 } split /\|/, $roles;
    my $deadline = time + 20;
    my $last = 'no focus';
    while (time < $deadline) {
        my $focus = atspi->focused_widget($pid);
        die 'focus observation was incomplete'
          unless $focus->{complete};
        if (($focus->{status} // '') eq 'passed') {
            $last = $focus->{widget}{role};
            return $focus->{widget} if $allowed{$last};
        }
        sleep 1;
    }
    die "keyboard focus did not reach the expected control: $last";
}

sub replace_focused_text {
    my ($text) = @_;
    focus_role('text|entry');
    select_console 'sut';
    send_key 'ctrl-a';
    type_string $text;
}

sub kate {
    select_console 'sut';
    send_key 'ctrl-n';
    focus_role('text|entry|document text');
    select_console 'sut';
    type_string "BigLinux nonvisual proof $nonce";
    send_key 'ctrl-s';
    atspi->focus_widget('text|entry', ['Name', 'Nome', 'File name', 'Nome do arquivo'], 30);
    replace_focused_text("$root/proof.txt");
    select_console 'sut';
    send_key 'ret';
    condition_ok('test -f ' . shell_quote("$root/proof.txt")
      . ' && grep -Fxq -- ' . shell_quote("BigLinux nonvisual proof $nonce")
      . ' ' . shell_quote("$root/proof.txt"));
    select_console 'sut';
    send_key 'ctrl-o';
    atspi->focus_widget('text|entry', ['Name', 'Nome', 'File name', 'Nome do arquivo'], 30);
    replace_focused_text("$root/proof.txt");
    reader('mark');
    select_console 'sut';
    send_key 'ret';
    focus_role('text|entry|document text');
    select_console 'sut';
    send_key 'ctrl-home';
    send_key 'shift-end';
    $current->{functional} = 'passed';
    reader('check', "BigLinux nonvisual proof $nonce");
}

sub konsole {
    focus_role('terminal');
    # The command is typed in the actual terminal GUI, never executed through
    # the serial observation channel. Only its resulting file is checked there.
    select_console 'sut';
    type_string 'printf ' . shell_quote('terminal-result-' . $nonce . '\n')
      . ' | tee ' . shell_quote("$root/terminal.txt");
    reader('mark');
    select_console 'sut';
    send_key 'ret';
    condition_ok('grep -Fxq -- ' . shell_quote("terminal-result-$nonce")
      . ' ' . shell_quote("$root/terminal.txt"));
    $current->{functional} = 'passed';
    reader('check', "terminal-result-$nonce");
}

sub dolphin {
    select_console 'sut';
    send_key 'ctrl-l';
    replace_focused_text($root);
    select_console 'sut';
    send_key 'ret';
    type_string "source-$nonce";
    send_key 'f2';
    replace_focused_text("renamed-$nonce.txt");
    reader('mark');
    select_console 'sut';
    send_key 'ret';
    condition_ok('test -f ' . shell_quote("$root/renamed-$nonce.txt")
      . ' && test ! -e ' . shell_quote("$root/source-$nonce.txt"));
    $current->{functional} = 'passed';
    reader('check', "renamed-$nonce");
}

sub brave {
    reader('mark');
    atspi->activate_widget('push button|button', ['Confirm test'], 60);
    my $expected = "Operation completed $nonce";
    # A changed accessible live region is the page's functional postcondition.
    atspi->assert_widget('label|text|paragraph|static|status bar', [$expected], 20);
    $current->{functional} = 'passed';
    reader('check', $expected);
}

sub save_results {
    my $payload = {
        schema_version => 1,
        scope => 'four installed application tasks; not whole-desktop certification',
        input => 'keyboard', screenshots => 'diagnostic-only',
        screen_reader => 'Orca upstream speech presenter (instrumented)',
        audible_output => 'not-tested', native_reader_activation => 'not-tested',
        greeter_reader => 'not-tested', braille_device => 'not-tested',
        cases => \@results,
    };
    open my $file, '>:raw', 'testresults/nonvisual-contracts.json'
      or die "cannot write nonvisual evidence: $!";
    print {$file} encode_json($payload);
    close $file or die "cannot finish nonvisual evidence: $!";
}

sub run {
    $nonce = substr(sha256_hex(time . '-' . $$), 0, 16);
    $root = "/tmp/openqa-nonvisual-$nonce";
    command_ok('umask 077; mkdir -- ' . shell_quote($root));
    command_ok('curl --fail --silent --show-error --max-time 30 '
      . shell_quote(data_url('orca_probe.py')) . ' -o /tmp/openqa-orca-probe.py');
    command_ok('curl --fail --silent --show-error --max-time 30 '
      . shell_quote(data_url('nonvisual-fixture.html')) . ' -o ' . shell_quote("$root/fixture.html"));
    # Fixture preparation is not the action under test.
    command_ok('touch -- ' . shell_quote("$root/source-$nonce.txt"));
    atspi->reset_baseline;
    my @cases = (
        ['kate-save-reopen', 'kate --new', \&kate],
        ['konsole-execute', 'konsole --separate', \&konsole],
        ['dolphin-rename', 'dolphin --new-window ' . shell_quote($root), \&dolphin],
        ['brave-live-region', 'brave --no-first-run --no-default-browser-check '
          . '--user-data-dir=' . shell_quote("$root/browser") . ' '
          . shell_quote("file://$root/fixture.html#$nonce"), \&brave],
    );
    my $reader_started = 0;
    for my $case (@cases) {
        my ($name, $command, $exercise) = @$case;
        my $record = {name => $name, status => 'failed', functional => 'not-confirmed',
            accessibility => 'not-confirmed', screen_reader => 'not-confirmed'};
        push @results, $record;
        my ($binary) = split / /, $command;
        my $available = atspi->run_command('command -v ' . shell_quote($binary) . ' >/dev/null 2>&1', 5);
        die 'could not query application availability' unless defined $available;
        if ($available != 0) {
            $record->{status} = 'skipped';
            $record->{skip_reason} = 'not-installed';
            $record->{error} = 'Not installed in this ISO; not applicable';
            save_results();
            next;
        }
        unless ($reader_started) { reader('start'); $reader_started = 1; }
        $current = $record;
        my $ok = eval {
            my (undef, $opened, undef, undef, $path, $launch_pid) =
              atspi->launch_command($command, '', 90, 'process-tree');
            die 'application did not expose its own accessible window'
              unless ($opened->{status} // '') eq 'passed';
            $pid = $opened->{pid};
            $exercise->();
            $record->{functional} = 'passed';
            $record->{accessibility} = 'keyboard-path-passed';
            my $closed = atspi->terminate_window($pid, $path, $launch_pid, undef, 1);
            die 'application needed forced cleanup' unless $closed->{graceful_exit};
            die 'application crashed while closing' if $closed->{application_crashed};
            $record->{status} = 'passed';
            1;
        };
        $record->{error} = "$@" unless $ok;
        my $clean = eval { atspi->cleanup(15) };
        unless (ref $clean eq 'HASH' && ($clean->{status} // '') eq 'passed') {
            $record->{cleanup} = 'failed';
            $record->{status} = 'failed';
        }
        save_results();
        record_info $name, encode_json($record);
    }
    $current = undef;
    reader('stop') if $reader_started;
    die 'one or more nonvisual tasks failed; see nonvisual-contracts.json'
      if grep { $_->{status} eq 'failed' } @results;
}

sub post_fail_hook {
    eval { reader('stop') } if defined $root;
    eval { save_results() };
    eval { select_console 'sut'; save_screenshot; };
}

1;
