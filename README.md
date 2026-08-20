# serial-tools

Field toolkit for troubleshooting PLC ↔ serial device links (RS232/RS485) in
industrial plants. Passive dual-direction taps, automatic baud/framing
detection, protocol decoding (Modbus RTU/ASCII + TOML-profile-driven
proprietary ASCII), offline analysis, device simulation, and an MCP server so
Claude Code can drive a live troubleshooting session.

See **PLAN.md** for the architecture, **WIRING.md** for how to physically tap
a link, and **SHOPPING.md** for the hardware kit.

## Install

```powershell
python -m pip install -e ".[mcp,view,dev]"
```

Python 3.11+. `pyserial` is the only hard dependency; `mcp` (MCP server),
`rich` (--live view) and `pytest` come with the extras.

## The troubleshooting ladder

1. **Is anyone talking?** `serialtools tap` — auto-detects ports and settings,
   captures both directions. Silence from one side localizes the fault.
2. **Are the line settings right?** `serialtools detect` — what's actually on
   the wire vs what the PLC and device are configured for.
3. **Are the frames well-formed?** `serialtools decode <capture> --decoder
   modbus_rtu` (or `--profile <device>`) — CRC/checksum/framing validation.
4. **Is the conversation logically right?** `serialtools analyze <capture>` —
   request/response latency, **unanswered requests with timestamps**, retries,
   error rate over time. `serialtools diff <good> <bad>` against a known-good
   capture.
5. **Impersonate one side.** `serialtools term --port COM7 --profile vici`
   (talk to the device as the PLC), or `serialtools sim <capture> --port COM7`
   (answer the PLC as the device). Whichever side misbehaves in isolation is
   the culprit.

## Commands

```
serialtools list                              show serial ports
serialtools detect [-p COM3] [--binary]       find baud/framing on the wire
serialtools tap [-p COM3=PLC-OUT ...]         passive capture (the main tool)
    --wiring rs485-2w                         one tap, both directions inferred
    --decoder modbus_rtu | --profile vici     live protocol decoding
    --live                                    pinned status header (rich)
serialtools decode <capture> --profile vici   annotate a capture; writes decoded.jsonl
serialtools analyze <capture> [--json]        summary / timing / errors report
serialtools diff <good> <bad>                 compare two captures
serialtools replay <capture> --port COM20     play a capture onto a port
serialtools sim <capture|profile> --port COMx answer requests like the device did
serialtools term --port COMx [--profile ...]  interactive terminal
serialtools mcp [--allow-tx]                  MCP server (stdio)
python serve_feed.py [--port 8686]            read-only web view of the live tap
```

`python rs232_tap.py` still works — it's a shim for `serialtools tap`.

Every capture becomes a directory under `captures/`: `session.json` (metadata,
notes), `frames.jsonl` (raw, never rewritten), `decoded.jsonl`, `raw/*.bin`,
`tap.log`. Old rs232_tap JSONL logs still load.

## Share the live feed (read-only)

To let a colleague watch the byte stream — say, while they edit the PLC program —
without giving them any access to your machine:

```powershell
serialtools tap -p COM4 -b 9600 --wiring rs485-2w --profile vici   # terminal 1
python serve_feed.py                                               # terminal 2
```

`serve_feed.py` prints your LAN IPs; the colleague opens `http://<your-ip>:8686`
in a browser and gets a live auto-scrolling view of the tap (ERR lines
highlighted). It follows the newest capture dir automatically, so restarting
the tap doesn't require a page refresh; `--capture <dir>` pins one capture
instead. Strictly one-way: the server only tails `tap.log` and ignores all
request input — no serial access, no file browsing. Allow the first-run
Windows Firewall prompt (private networks). Reachability is LAN/VPN; don't
expose the port to the internet.

## New device? Write a profile, not code

Copy `serialtools/profiles/vici.toml`, set the terminator/checksum and the
command/response patterns (~20 lines of TOML), drop it in `profiles/`. Then
`--profile <name>` works everywhere: tap, decode, analyze, sim, term.

## Claude Code (MCP)

```powershell
claude mcp add serialtools -- python -m serialtools.mcp
```

Tools: `list_ports`, `detect_settings`, `start_tap`, `tap_status`,
`get_frames` (cursor), `stop_tap`, `list_captures`, `decode_capture`,
`analyze_capture`. Transmit (`send_bytes`) does not exist unless the server is
started with `--allow-tx`, and then still requires a per-call
`confirm="SEND <port>"`, refuses ports held by running taps, and audit-logs to
`captures/tx-audit.jsonl`.

## Developing without hardware

- `pytest` — the suite runs entirely offline.
- [com0com](https://sourceforge.net/projects/com0com/) gives a virtual COM
  pair: `serialtools replay <capture> --port COM20` in one window,
  `serialtools tap -p COM21` in another, real bytes with original timing.
- `serialtools sim` on one end of the pair exercises PLC code (or `term`)
  against a simulated device.
