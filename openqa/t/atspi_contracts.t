use strict;
use warnings;
use Test::More;
use JSON::PP ();
use atspi;
no warnings 'redefine';

{
    my @args;
    local *atspi::result = sub { @args = @_; return {status => 'passed', complete => 1}; };
    atspi->set_widget_scope(42);
    atspi->wait_widget('button', ['Next'], 5, id => 'stable-next', checked => 1);
    is_deeply(\@args, ['atspi','wait-widget',5,'--role','button','--labels','Next',
        '--pid',42,'--accessible-id','stable-next','--checked','true'], 'selectors retain process scope and stable ID');
    atspi->wait_widget('button', ['Next'], 5, pid => undef);
    ok(!grep($_ eq '--pid', @args), 'explicit page discovery may be unscoped');
    atspi->wait_widget('button', ['Next'], 5, pid => 42, application_index => 7);
    is_deeply(\@args, ['atspi','wait-widget',5,'--role','button','--labels','Next',
        '--pid',42,'--application-index',7],
        'widget lookup forwards the PID-verified AT-SPI application hint');
    atspi->set_widget_scope(42, 41);
    atspi->wait_widget('button', ['Next'], 5, application_index => 7);
    is_deeply(\@args, ['atspi','wait-widget',5,'--role','button','--labels','Next',
        '--pid',42,'--root-pid',41,'--application-index',7],
        'explicit supervisor provenance enables process-group recovery');
    atspi->wait_widget('button', ['Next'], 5, pid => undef);
    ok(!grep($_ eq '--pid' || $_ eq '--root-pid', @args),
        'explicit unscoped discovery clears both PID and supervisor provenance');
    atspi->set_widget_scope(42);
    atspi->wait_widget('label', ['Welcome'], 90,
        positive_witness => 1, startup_timeout_ms => 5000);
    is_deeply(\@args, ['atspi','wait-widget',90,'--role','label','--labels','Welcome',
        '--pid',42,'--positive-witness','--startup-timeout-ms',5000],
        'positive witness and bounded startup grace are explicit opt-in arguments');
    eval { atspi->wait_widget('button', ['Next'], 5,
        checked => 1, positive_witness => 1) };
    like($@, qr/cannot assert checked/, 'positive witness cannot weaken a state assertion');
}
{
    local *atspi::wait_widget = sub { return {status => 'passed', complete => 0}; };
    eval { atspi->assert_widget('button', ['Next'], 5) };
    like($@, qr/incomplete/, 'required wait rejects incomplete evidence');
}
{
    local *atspi::activate_widget = sub { return {}; };
    for my $reply ({status=>'failed', complete=>1}, {status=>'passed',complete=>0,reason=>'absent'},
                   {status=>'inconclusive',complete=>0}) {
        local *atspi::_widget_operation = sub { return $reply; };
        eval { atspi->activate_widget_until_gone('button',['Confirm'],5) };
        like($@, qr/not confirmed/, 'failed or partial query never proves disappearance');
    }
    local *atspi::_widget_operation = sub { return {status=>'passed',complete=>1,reason=>'absent'}; };
    is(atspi->activate_widget_until_gone('button',['Confirm'],5), 1, 'complete absence satisfies postcondition');
}
{
    my @keys;
    my @focus = ({pid=>42, identity=>'/first', role=>'text'},
                 {pid=>42, identity=>'/target', role=>'button'});
    my @focus_args;
    local *atspi::assert_widget = sub {
        return {widget=>{pid=>42,identity=>'/target',name=>'Next',application_index=>7}};
    };
    local *atspi::focused_widget = sub {
        @focus_args = @_;
        return {status=>'passed',complete=>1,widget=>shift @focus};
    };
    local *atspi::select_console = sub {};
    local *atspi::send_key = sub { push @keys, $_[0]; };
    atspi->activate_widget('button', ['Next'], 5);
    is_deeply(\@keys, ['tab','ret'], 'activation follows observed keyboard focus, not direct action');
    is_deeply([@focus_args[1..3]], [42, '/target', 7],
        'focus traversal forwards the PID-verified AT-SPI application hint');
}
{
    my @focus_args;
    local *atspi::assert_widget = sub {
        return {widget=>{pid=>42,identity=>'/target',name=>'Next',application_index=>7}};
    };
    local *atspi::focused_widget = sub {
        @focus_args = @_;
        return {status=>'passed',complete=>1,widget=>{pid=>42,identity=>'/target'}};
    };
    local *atspi::select_console = sub {};
    local *atspi::send_key = sub {};
    atspi->focus_widget('button', ['Next'], 5, root_pid => 41);
    is($focus_args[4], 41,
        'focus traversal keeps the explicit supervisor root separate from the target PID');
}
{
    my @args;
    local *atspi::result = sub { @args = @_; return {status=>'passed',complete=>1}; };
    atspi->focused_widget(42, '/target', 7);
    is_deeply(\@args,
        ['atspi','focused-widget',5,'--pid',42,'--target-identity','/target',
         '--application-index',7],
        'focused-widget sends the application hint to the guest probe');
}
{
    my @result_calls;
    my @scope;
    local *atspi::result = sub {
        my ($class, $operation, $timeout, @args) = @_;
        push @result_calls, [$operation, @args];
        return {status=>'passed',complete=>1,window_count=>1,
                mem_available_mib=>1024,desktop=>'KDE'} if $operation eq 'baseline';
        return {status=>'passed',complete=>1,pid=>84,
                application_index=>3,window_identity=>'/window'} if $operation eq 'wait-open';
        die "unexpected probe operation $operation";
    };
    local *atspi::select_console = sub {};
    local *atspi::type_string = sub {};
    local *atspi::send_key = sub {};
    local *atspi::wait_serial = sub { return 1; };
    local *atspi::_read_child_pid = sub { return 73; };
    local *atspi::set_widget_scope = sub { @scope = @_[1,2]; };
    my @launch = atspi->_launch_argv(['/usr/bin/example'], 'Example', 5, 'process-tree', 0);
    is_deeply($result_calls[1],
        ['wait-open','--name','Example','--no-memory-sample','--pid',73,'--root-pid',73],
        'process-tree launch explicitly forwards the supervisor root to wait-open');
    is_deeply(\@scope, [84,73],
        'successful process-tree launch persists target PID and supervisor provenance');
}
{
    local *atspi::assert_widget = sub { return {widget=>{pid=>42,identity=>'/target',name=>'Next'}}; };
    local *atspi::focused_widget = sub { return {status=>'passed',complete=>1,widget=>{pid=>42,identity=>'/stuck'}}; };
    local *atspi::select_console = sub {};
    local *atspi::send_key = sub {};
    eval { atspi->focus_widget('button',['Next'],5) };
    like($@, qr/cycled/, 'focus trap fails instead of being bypassed');
}
{
    local *atspi::assert_widget = sub { return {widget=>{pid=>42,identity=>'/target',name=>'Next'}}; };
    local *atspi::focused_widget = sub { return {status=>'passed',complete=>1,widget=>{pid=>99,identity=>'/target'}}; };
    local *atspi::select_console = sub {};
    local *atspi::send_key = sub {};
    eval { atspi->focus_widget('button',['Next'],5) };
    like($@, qr/cycled/, 'same object path in another application cannot satisfy focus');
}
{
    local *atspi::select_console = sub {};
    local *atspi::type_string = sub {};
    local *atspi::send_key = sub {};
    local *atspi::wait_serial = sub {
        my ($pattern) = @_;
        my ($marker) = "$pattern" =~ /(__OA_APP_EXIT_DONE_[0-9]+_[0-9]+__)/;
        die 'status marker unavailable' unless defined $marker;
        return "0\n$marker\n";
    };
    my $code = atspi::_read_status_value('/tmp/openqa-gui-status-1-2', 'exit_code', 1);
    is(JSON::PP->new->canonical->encode({code => $code}), '{"code":0}',
        'supervisor exit status is serialized as a JSON number');
}
ok(atspi::is_crash_exit_code(133), 'SIGTRAP is not globally ignored');
ok(!atspi::is_crash_exit_code(0), 'normal exit is not a crash');
ok(atspi::_baseline_is_complete({
        status => 'passed', window_count => 5,
        mem_available_mib => 2048.0, desktop => 'KDE',
    }), 'compact baseline summary is complete');
ok(!atspi::_baseline_is_complete({
        windows => [], mem_available_mib => 2048.0, desktop => 'KDE',
    }), 'legacy full-window payload cannot bypass the compact baseline contract');
ok(!atspi::_baseline_is_complete({
        status => 'passed', window_count => 'many',
        mem_available_mib => 2048.0, desktop => 'KDE',
    }), 'baseline window count is typed and bounded to an integer');
done_testing;
