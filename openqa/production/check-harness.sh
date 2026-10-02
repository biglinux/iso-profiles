#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# The harness checks that need neither a guest nor a GUI. The pull-request
# workflow and the release gate both run this file, so the list exists once.
# Report regressions need openqa/report/requirements.txt installed first.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

git diff --check
for script in openqa/production/*.sh data/*.sh; do bash -n "$script"; done
shellcheck -x openqa/production/*.sh data/*.sh
ruby -e 'require "yaml"; ARGV.each { |path| YAML.safe_load_file(path, permitted_classes: [], aliases: false) }' \
    openqa/*.yaml

python3 -m unittest discover -s data -p 'test_*.py'
python3 -m unittest discover -s openqa/report -p 'test_*.py'
python3 -m py_compile data/*.py openqa/report/*.py openqa/production/*.py openqa/integration/*.py
# Pixel references and pointer automation cannot decide this gate.
python3 openqa/production/check-nonvisual.py
prove -Iopenqa/t/lib -Iopenqa/lib openqa/t/*.t

# The three mistakes below compile under perl -c and only fail minutes into a
# job, so they are refused here.
#
# "type_string calamares->test_user" is valid Perl that means
# "calamares->type_string(...)": the indirect object syntax silently calls the
# wrong method. Require the parentheses that settle the parse.
if grep -rnE '^\s*(type_string|type_password|assert_script_run|script_run|record_info|upload_logs)\s+[a-z_]+->' \
    openqa/tests/*.pm openqa/lib/*.pm; then
    echo 'Call the method first and pass its result in parentheses' >&2
    exit 1
fi
# A module whose literals are not ASCII needs "use utf8", or every accented
# label it declares reaches the guest as latin-1 and matches nothing.
for perl_module in openqa/lib/*.pm openqa/tests/*.pm openqa/main.pm; do
    if LC_ALL=C grep -q '[^ -~[:space:]]' "$perl_module" && ! grep -q '^use utf8;' "$perl_module"; then
        echo "$perl_module has non-ASCII literals but does not use utf8" >&2
        exit 1
    fi
done
# os-autoinst forwards a second select_console argument to
# distribution::console_selected, whose signature takes the console alone and
# dies on anything more.
if grep -rnE "select_console\s+'[a-z0-9-]+'\s*," openqa/tests/*.pm openqa/lib/*.pm; then
    echo 'select_console takes the console name alone' >&2
    exit 1
fi
