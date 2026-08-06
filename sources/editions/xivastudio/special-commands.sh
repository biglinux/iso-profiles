#!/bin/bash
#
# Runs from the repository root. The workflow invokes this with bash, so it
# does not inherit the step's -e: without this line a failed sed is invisible
# and a half-built profile gets committed.
set -euo pipefail
    
# Add some things from Packages-Desktop
# sed -n '/## Printing/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/xivastudio/Packages-Desktop
# sed -n '/## Xorg Server and Graphics/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/xivastudio/Packages-Desktop
# sed -n '/## Xorg Input Drivers/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/xivastudio/Packages-Desktop
# sed -n '/## Misc/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/xivastudio/Packages-Desktop
# sed -i 's|xf86-input-void||g'  biglinux/kde/Packages-Desktop

sed -i '/GRUB_DISTRIBUTOR=/s/GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="XIVAStudio"/' biglinux/xivastudio/root-overlay/etc/default/grub
# Anchored: an unanchored /User=/ also matches RememberLastUser=, turning a
# boolean into a username.
sed -i '/^User=/s/.*/User=xivastudio/' biglinux/xivastudio/live-overlay/etc/sddm.conf
sed -i '/autologin=/s/autologin=.*/autologin=xivastudio/' biglinux/xivastudio/live-overlay/etc/lxdm/lxdm.conf
# misolabel and misobasedir are not set here on purpose: build-iso.sh rewrites
# them in every kernels.cfg from the edition it is building, so whatever the
# profile carries is overwritten. The two seds that used to sit here targeted
# 'misolabel=biglinux' (the file says BIGLINUXLIVE) and a boot/grub/kernels.cfg
# that does not exist, so both were silent no-ops.
find biglinux/xivastudio/live-overlay/usr/share/grub/themes/manjaro-live \
  -maxdepth 1 -name 'theme*.txt' -exec \
  sed -i 's/file = "biglinux-grub.png"/file = "xivastudio.png"/' {} +
# build-iso.sh repoints variable.cfg at <distro>-live/theme.txt, so the live
# menu loads biglinux-live even for this edition. The image has to be there
# before the theme references it.
cp biglinux/xivastudio/live-overlay/usr/share/grub/themes/manjaro-live/xivastudio.png \
  biglinux/xivastudio/live-overlay/usr/share/grub/themes/biglinux-live/xivastudio.png
find biglinux/xivastudio/live-overlay/usr/share/grub/themes/biglinux-live \
  -maxdepth 1 -name 'theme*.txt' -exec \
  sed -i 's/file = "biglinux-grub.png"/file = "xivastudio.png"/' {} +
sed -i '/ExecStart=/s/biglinux/xivastudio/' biglinux/xivastudio/live-overlay/usr/lib/systemd/system/getty@.service
sed -i '/hostname=/s/hostname=.*/hostname="xivastudio"/' biglinux/xivastudio/profile.conf
sed -i '/username=/s/username=.*/username="xivastudio"/' biglinux/xivastudio/profile.conf
sed -i '/password=/s/password=.*/password="xivastudio"/' biglinux/xivastudio/profile.conf
# sed -i '/Current=/s/Current=.*/Current=xivastudio/' biglinux/xivastudio/root-overlay/etc/sddm.conf

# sed -i '//s///' biglinux/xivastudio/


#add biglinux standed desktop to xivastudio desktop
cat biglinux/kde/Packages-Desktop  >>  biglinux/xivastudio/Packages-Desktop

#remove desktop
# Write to a temporary file and move it into place only once grep succeeded.
# Moving the original away first and truncating the target meant a missing
# Desktop-remove left a zero-byte package list and deleted the only copy.
test -e sources/editions/xivastudio/Desktop-remove
grep -vF -f sources/editions/xivastudio/Desktop-remove \
  biglinux/xivastudio/Packages-Desktop > biglinux/xivastudio/Packages-Desktop.new
test -s biglinux/xivastudio/Packages-Desktop.new
mv biglinux/xivastudio/Packages-Desktop.new biglinux/xivastudio/Packages-Desktop
