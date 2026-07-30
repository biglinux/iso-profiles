#!/bin/bash
    
# Add some things from Packages-Desktop
sed -n '/## Printing/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/kde/Packages-Desktop
sed -n '/## Xorg Server and Graphics/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/kde/Packages-Desktop
sed -n '/## Xorg Input Drivers/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/kde/Packages-Desktop
sed -n '/## Misc/,/^$/p'  manjaro-iso-profiles/manjaro/kde/Packages-Desktop  >>  biglinux/kde/Packages-Desktop
sed -i 's|xf86-input-void||g'  biglinux/kde/Packages-Desktop
