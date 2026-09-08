# SPDX-License-Identifier: GPL-2.0-or-later

use Mojo::Base 'basetest';
use testapi;
use atspi;
use biglinux;
use installed_system;
use guest_shell qw(marker_format);

# Measures the security posture of the freshly installed system.
#
# Every item below came out of a manual audit of a released ISO, where each one
# was true. They are reported as soft failures on purpose: the point today is
# to make the posture visible on every build, and to notice the day it gets
# worse - not to block a release on defects that already shipped. Promoting one
# to a hard failure is a single line here once it is fixed.
sub test_flags {
    # Never fatal: the modules after this one still have to run.
    return {fatal => 0};
}


sub run {
    select_console 'user-virtio-terminal';

    # Everything below reads files and tables that are root-only. Measuring
    # them as the desktop user does not fail - it returns nothing, which reads
    # as a clean system. Refuse to report anything rather than report that.
    unless (biglinux->become_root) {
        record_soft_failure 'security: the posture probe could not obtain root, so nothing was measured';
        return;
    }

    my $probe = <<'SHELL';
uid=$(id -u)
# Only lines that are in effect: the stock /etc/sudoers ships a commented
# "%wheel ALL=(ALL:ALL) NOPASSWD: ALL" example, and counting it reported three
# grants where the system has two.
nopasswd_lines=$(grep -rhs NOPASSWD /etc/sudoers /etc/sudoers.d/ 2>/dev/null | grep -vE '^[[:space:]]*#' || true)
nopasswd=$(printf '%s\n' "$nopasswd_lines" | grep -c . || true)
nopasswd_names=$(grep -rlsE '^[[:space:]]*[^#].*NOPASSWD' /etc/sudoers.d/ 2>/dev/null | xargs -r -n1 basename | paste -sd, || true)
listening=$(ss -tulpnH 2>/dev/null | awk '{print $5}' | grep -vcE '^(127\.0\.0\.[0-9]+|\[::1\]):' || true)
listening_ports=$(ss -tulpnH 2>/dev/null | awk '{print $5}' | grep -vE '^(127\.0\.0\.[0-9]+|\[::1\]):' | sort -u | paste -sd, || true)
firewall=$(systemctl is-enabled ufw firewalld nftables iptables 2>/dev/null | grep -c '^enabled' || true)
firewall_units=$(for u in ufw firewalld nftables iptables; do
    [ "$(systemctl is-enabled "$u" 2>/dev/null)" = enabled ] && printf '%s ' "$u"
done)
# An enabled unit is not a filtered machine: ufw ships enabled here and still
# leaves the policy at ACCEPT until "ufw enable" is run once.
ufwstate=$(ufw status 2>/dev/null | awk 'NR == 1 {print $2}')
ufwstate=${ufwstate:-absent}
inpolicy=$(iptables -S INPUT 2>/dev/null | awk '/^-P INPUT/ {print $3; exit}')
inpolicy=${inpolicy:-unknown}
nftrules=$(nft list ruleset 2>/dev/null | grep -cE '^[[:space:]]*(drop|reject|accept|jump)' || true)
filtering=0
if [ "$ufwstate" = active ] || [ "$inpolicy" = DROP ] || [ "$inpolicy" = REJECT ] || [ "$nftrules" -gt 0 ]; then
    filtering=1
fi
dbnever=$(grep -cE '^[[:space:]]*SigLevel.*DatabaseNever' /etc/pacman.conf 2>/dev/null || true)
httpmirror=$(grep -rhE '^[[:space:]]*Server[[:space:]]*=[[:space:]]*http:' /etc/pacman.d/ 2>/dev/null | grep -c . || true)
kptr=$(sysctl -n kernel.kptr_restrict 2>/dev/null || echo unknown)
dmesgr=$(sysctl -n kernel.dmesg_restrict 2>/dev/null || echo unknown)
# "|| echo unset" on a pipeline never fires: the status is head's, not grep's,
# so a kernel command line without an audit= setting used to report an empty
# value that read like a measurement rather than an absence.
audit=$(grep -oE 'audit=[01]' /proc/cmdline 2>/dev/null | head -1)
audit=${audit:-unset}
apparmor=$(grep -c 'security=apparmor' /proc/cmdline 2>/dev/null || true)
luks=none
if lsblk -no FSTYPE 2>/dev/null | grep -q crypto_LUKS; then
    luks=$(lsblk -no PATH,FSTYPE 2>/dev/null | awk '$2 == "crypto_LUKS" {print $1; exit}' \
        | xargs -r cryptsetup luksDump 2>/dev/null | awk '/^Version:/ {print $2; exit}')
    luks=${luks:-unknown}
fi
updates=$(pacman -Qu 2>/dev/null | grep -c . || true)
suid=$(find / -xdev -perm -4000 -type f 2>/dev/null | grep -c . || true)
{
    printf 'probe uid: %s\n' "$uid"
    printf 'sudoers NOPASSWD lines: %s (%s)\n' "$nopasswd" "$nopasswd_names"
    printf '%s\n' "$nopasswd_lines"
    printf '\nlistening beyond loopback: %s\n' "$listening_ports"
    ss -tulpn 2>/dev/null || true
    printf '\nfirewall units enabled: %s (%s)\n' "$firewall" "$firewall_units"
    printf 'firewall filtering: %s (ufw %s, INPUT policy %s, nft rules %s)\n' \
        "$filtering" "$ufwstate" "$inpolicy" "$nftrules"
    ufw status verbose 2>/dev/null || true
    iptables -S 2>/dev/null || true
    nft list ruleset 2>/dev/null || true
    printf 'pacman SigLevel:\n'
    grep -E '^[[:space:]]*SigLevel' /etc/pacman.conf 2>/dev/null || true
    printf '\nplain HTTP mirrors: %s\n' "$httpmirror"
    printf 'kernel.kptr_restrict=%s kernel.dmesg_restrict=%s\n' "$kptr" "$dmesgr"
    printf 'cmdline audit: %s apparmor: %s\n' "$audit" "$apparmor"
    printf 'LUKS version: %s\n' "$luks"
    printf 'pending updates: %s\n' "$updates"
    printf 'setuid binaries: %s\n' "$suid"
    find / -xdev -perm -4000 -type f 2>/dev/null || true
} >/tmp/openqa-installed-security.log
printf '__OA_SECURITY_MARKER_FORMAT__uid=%s;nopasswd=%s;listening=%s;firewall=%s;filtering=%s;ufw=%s;inpolicy=%s;dbnever=%s;httpmirror=%s;kptr=%s;dmesgr=%s;audit=%s;apparmor=%s;luks=%s;updates=%s;suid=%s__\n' \
    "$uid" "$nopasswd" "$listening" "$firewall" "$filtering" "$ufwstate" "$inpolicy" "$dbnever" "$httpmirror" "$kptr" "$dmesgr" "$audit" "$apparmor" "$luks" "$updates" "$suid"
SHELL
    $probe =~ s/__OA_SECURITY_MARKER_FORMAT__/marker_format('__OA_INSTALLED_SECURITY__')/e;
    # One sudo for the whole script: the cached timestamp would otherwise have
    # to outlive every command in it, and "pacman -Qu" alone can take a minute.
    type_string "sudo -n bash -s <<'OA_SECURITY_PROBE'\n$probe" . "OA_SECURITY_PROBE\n";

    my $pattern = qr/__OA_INSTALLED_SECURITY__uid=(\d+);nopasswd=(\d+);listening=(\d+);firewall=(\d+);filtering=(\d+);ufw=(\S*?);inpolicy=(\S*?);dbnever=(\d+);httpmirror=(\d+);kptr=(\S*?);dmesgr=(\S*?);audit=(\S*?);apparmor=(\d+);luks=(\S*?);updates=(\d+);suid=(\d+)__/;
    my $result = wait_serial $pattern, timeout => 180;
    select_console 'sut';
    atspi->upload_guest_file('/tmp/openqa-installed-security.log', 'installed-security.log');

    unless (defined $result) {
        record_soft_failure 'security: the posture probe returned no result';
        return;
    }

    my ($uid, $nopasswd, $listening, $firewall, $filtering, $ufwstate, $inpolicy,
        $dbnever, $httpmirror, $kptr, $dmesgr, $audit, $apparmor, $luks,
        $updates, $suid) = $result =~ $pattern;

    # Each entry: what was measured, whether it is acceptable, and why it
    # matters when it is not. The wording is what a maintainer reads in the
    # report, so it names the consequence rather than the setting.
    unless ($uid eq '0') {
        record_soft_failure "security: the posture probe ran as uid $uid, so every root-only item below is unmeasured";
        return;
    }

    my @findings;
    my $note = sub {
        my ($ok, $message) = @_;
        return if $ok;
        push @findings, $message;
        record_soft_failure "security: $message";
    };

    $note->($nopasswd == 0,
        "sudoers grants NOPASSWD on $nopasswd line(s); a command that forwards its arguments to a root process is a local escalation");
    $note->($listening == 0,
        "$listening service(s) listen beyond loopback, reachable on any network this machine joins");
    # Deliberately not "is a firewall unit enabled": ufw is in enable_systemd
    # and reports enabled on every install, while its policy stays ACCEPT until
    # someone runs "ufw enable" once. The question is whether packets are
    # actually filtered.
    $note->($filtering,
        "nothing filters incoming traffic (ufw $ufwstate, INPUT policy $inpolicy, $firewall unit(s) enabled), so those services are reachable as they are");
    $note->($dbnever == 0,
        'pacman accepts unsigned repository databases (SigLevel DatabaseNever)');
    $note->($httpmirror == 0,
        "$httpmirror mirror(s) are configured over plain HTTP");
    $note->(!($kptr eq '0' && $dmesgr eq '0'),
        "kernel.kptr_restrict=$kptr and kernel.dmesg_restrict=$dmesgr expose kernel addresses and the kernel log to unprivileged users");
    $note->(!($audit eq 'audit=0' && $apparmor > 0),
        'AppArmor is enforcing but audit=0 discards its denials, so violations are never recorded');
    $note->($luks ne '1',
        'the encrypted volume uses LUKS1 (PBKDF2), the Calamares fallback when luksGeneration is unset');
    $note->($updates <= 50,
        "$updates package update(s) are already pending on a freshly installed system");

    record_info 'Security posture', sprintf(
        "probe_uid=%s nopasswd=%s listening=%s firewall_units=%s filtering=%s ufw=%s input_policy=%s\n"
          . "dbnever=%s http_mirrors=%s kptr_restrict=%s dmesg_restrict=%s audit=%s apparmor=%s\n"
          . "luks=%s updates=%s setuid=%s\n"
          . '%s',
        $uid, $nopasswd, $listening, $firewall, $filtering, $ufwstate, $inpolicy,
        $dbnever, $httpmirror, $kptr, $dmesgr, $audit, $apparmor,
        $luks, $updates, $suid,
        @findings
        ? 'Reported as warnings: ' . scalar(@findings) . ' item(s) below expectation'
        : 'Every measured item is within expectations'
    );
}

1;
