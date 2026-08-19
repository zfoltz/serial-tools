#!/usr/bin/env python3
"""Compatibility shim: rs232_tap.py grew into the serialtools package.

`python rs232_tap.py <args>` now runs `serialtools tap <args>`. Output goes to
a capture directory under captures/ instead of logs/ (the old --log/--jsonl/
--raw-dir flags are accepted and ignored -- the capture dir contains all
three). Install with:  python -m pip install -e .
"""

import sys

try:
    from serialtools.cli import main
except ImportError:
    sys.exit("serialtools is not installed. Run:  python -m pip install -e . "
             "(from the serial-tools directory)")

argv = sys.argv[1:]
if "--list" in argv:
    sys.exit(main(["list"]))

for old_flag in ("--log", "--jsonl", "--raw-dir"):
    while old_flag in argv:
        i = argv.index(old_flag)
        dropped = argv[i:i + 2]
        del argv[i:i + 2]
        print(f"[!] {' '.join(dropped)} is obsolete: every capture now writes a "
              f"directory under captures/ with tap.log, frames.jsonl and raw/*.bin",
              file=sys.stderr)

sys.exit(main(["tap", *argv]))
