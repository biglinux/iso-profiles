#!/bin/bash
    
# Add some things from Packages-Desktop
# sed -n '/## Printing/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/xivastudio/Packages-Desktop
# sed -n '/## Xorg Server and Graphics/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/xivastudio/Packages-Desktop
# sed -n '/## Xorg Input Drivers/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/xivastudio/Packages-Desktop
# sed -n '/## Misc/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/xivastudio/Packages-Desktop
# sed -i 's|xf86-input-void||g'  biglinux/kde/Packages-Desktop

sed -i '/GRUB_DISTRIBUTOR=/s/GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="XIVAStudio"/' biglinux/xivastudio/root-overlay/etc/default/grub
sed -i '/User=/s/User=.*/User=xivastudio/' biglinux/xivastudio/root-overlay/etc/sddm.conf
sed -i '/User=/s/User=.*/User=xivastudio/' biglinux/xivastudio/live-overlay/etc/sddm.conf
sed -i '/autologin=/s/autologin=.*/autologin=xivastudio/' biglinux/xivastudio/live-overlay/etc/lxdm/lxdm.conf
sed -i 's/misolabel=biglinux/misolabel=xivastudio/g' biglinux/xivastudio/live-overlay/usr/share/grub/cfg/kernels.cfg
sed -i 's/misolabel=biglinux/misolabel=xivastudio/g' biglinux/xivastudio/live-overlay/boot/grub/kernels.cfg
sed -i 's/file = "biglinux-grub.png"/file = "xivastudio.png"/' biglinux/xivastudio/live-overlay/usr/share/grub/themes/manjaro-live/theme.txt
sed -i 's/file = "biglinux-grub.png"/file = "xivastudio.png"/' biglinux/xivastudio/live-overlay/usr/share/grub/themes/biglinux-live/theme.txt
sed -i '/ExecStart=/s/biglinux/xivastudio/' biglinux/xivastudio/live-overlay/usr/lib/systemd/system/getty@.service
sed -i '/hostname=/s/hostname=.*/hostname="xivastudio"/' biglinux/xivastudio/profile.conf
sed -i '/username=/s/username=.*/username="xivastudio"/' biglinux/xivastudio/profile.conf
sed -i '/password=/s/password=.*/password="xivastudio"/' biglinux/xivastudio/profile.conf
# sed -i '/Current=/s/Current=.*/Current=xivastudio/' biglinux/xivastudio/root-overlay/etc/sddm.conf

# sed -i '//s///' biglinux/xivastudio/

sed -i '/pipewire-biglinux-config/d' biglinux/xivastudio/Packages-Root

#add biglinux standed desktop to xivastudio desktop
cat biglinux/kde/Packages-Desktop  >>  biglinux/xivastudio/Packages-Desktop

#remove desktop
mv biglinux/xivastudio/Packages-Desktop biglinux/xivastudio/Packages-Desktop-prov
grep -vF -f sources/editions/xivastudio/Desktop-remove  biglinux/xivastudio/Packages-Desktop-prov  >  biglinux/xivastudio/Packages-Desktop
rm biglinux/xivastudio/Packages-Desktop-prov
