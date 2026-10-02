# SPDX-License-Identifier: GPL-2.0-or-later
# Test double only. Never add openqa/t/lib to an isotovideo invocation.
package Mojo::Base;
sub import {
    strict->import;
    warnings->import;
    require feature;
    feature->import('signatures', 'state');
}
1;
