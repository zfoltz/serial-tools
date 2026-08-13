"""Interactive terminal to the VICI actuator via the COM7 adapter.

ONLY for use after rewiring the tap into a terminal: at the breakout, lift the
PLC-TX -> valve-RX conductor and connect the adapter's pin 3 (TXD) to the
valve's RX instead. Pin 2 (RXD) stays on the valve's TX line, pin 5 on ground.
While wired this way the PLC cannot talk to the valve - restore the conductor
afterward.

Usage:
    python vici_terminal.py                    # run the standard probe sequence
    python vici_terminal.py CP VR NP           # send specific commands
    python vici_terminal.py "GO04"             # test two-digit GO syntax

Each command is sent with CR (default). Use --crlf to append CR LF like the
PLC's PRTXT does. Responses are printed raw (hex + ascii) for 2s per command.
"""
import argparse
import sys
import time

import serial

PROBE = [
    # identity / config queries first (read-only for the actuator)
    "VR",    # firmware version
    "CP",    # current position
    "NP",    # number of ports/positions configured
    "ID",    # device id (if supported)
    "AM",    # actuator mode (if supported)
    "IFM",   # interface/response mode (if supported)
    "SM",    # stepping/serial mode variants (harmless query on most firmware)
    "LG",    # legacy/language mode (if supported)
    "?",     # help/command list on some firmware
]


def render(b: bytes) -> str:
    return "".join(chr(x) if 32 <= x < 127 else f"<{x:02X}>" for x in b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commands", nargs="*", default=None)
    ap.add_argument("--port", default="COM7")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--crlf", action="store_true",
                    help="terminate with CR LF (PLC-style) instead of CR")
    ap.add_argument("--wait", type=float, default=2.0, help="seconds to listen per command")
    args = ap.parse_args()

    cmds = args.commands or PROBE
    term = b"\r\n" if args.crlf else b"\r"

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    print(f"open {args.port} @ {args.baud} 8N1, terminator {term!r}\n")

    try:
        for cmd in cmds:
            ser.reset_input_buffer()
            ser.write(cmd.encode("ascii") + term)
            ser.flush()
            got = bytearray()
            end = time.time() + args.wait
            while time.time() < end:
                chunk = ser.read(256)
                if chunk:
                    got += chunk
                    end = time.time() + 0.4  # keep reading while data flows
            print(f">>> {cmd}")
            print(f"    {render(bytes(got)) if got else '(no response)'}\n")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
