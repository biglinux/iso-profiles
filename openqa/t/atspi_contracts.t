use strict;
use warnings;
use Test::More;
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
    local *atspi::assert_widget = sub { return {widget=>{pid=>42,identity=>'/target',name=>'Next'}}; };
    local *atspi::focused_widget = sub { return {status=>'passed',complete=>1,widget=>shift @focus}; };
    local *atspi::select_console = sub {};
    local *atspi::send_key = sub { push @keys, $_[0]; };
    atspi->activate_widget('button', ['Next'], 5);
    is_deeply(\@keys, ['tab','ret'], 'activation follows observed keyboard focus, not direct action');
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
ok(atspi::is_crash_exit_code(133), 'SIGTRAP is not globally ignored');
ok(!atspi::is_crash_exit_code(0), 'normal exit is not a crash');
done_testing;
