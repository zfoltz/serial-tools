"""`python -m serialtools.mcp [--allow-tx]` -- the target for `claude mcp add`."""

import argparse

from .server import run

ap = argparse.ArgumentParser(prog="python -m serialtools.mcp")
ap.add_argument("--allow-tx", action="store_true",
                help="register the send_bytes tool (transmitting!). Off by default.")
args = ap.parse_args()
raise SystemExit(run(allow_tx=args.allow_tx))
