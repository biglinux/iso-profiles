# Test double only. Real os-autoinst behavior is not simulated here.
package testapi;
use Exporter 'import';
our @EXPORT = qw(select_console send_key type_string type_password wait_serial
    record_info record_soft_failure data_url get_var get_required_var autoinst_url reset_consoles
    save_screenshot eject_cd power assert_script_run script_run upload_logs);
for my $name (@EXPORT) {
    no strict 'refs';
    *{$name} = sub { die "unmocked testapi call: $name" };
}
1;
