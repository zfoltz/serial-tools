# Serial Troubleshooting Kit — Plan

## Context

Zach does controls work and periodically has to troubleshoot PLC ↔ serial device links (RS232 and RS485) in plants. Today this is slow and painful: taps are improvised by unlanding screw terminals, TX/RX gets guessed wrong, and tooling is scattered. The goal is a grab-and-go kit (hardware in one organizer + software in this repo) so the next misbehaving serial device can be diagnosed in hours, not days.

Scope decisions (from Q&A):
- **Protocols:** proprietary ASCII is the main case; Modbus RTU/ASCII decoding included. Architecture extensible for future decoders (DF1, BACnet MS/TP) but not implemented now.
- **Budget:** minimize; ceiling ~$600. Already owned: 1× Oikwan FTDI USB-RS232 adapter, Saleae Logic 8, Windows laptop.
- **Not in scope:** electronics-level failure analysis. If the instrument or PLC is broken at the hardware level, it gets replaced — the kit only needs to *identify* that state, plus find wiring and PLC-code bugs.
- **Platform:** Windows laptop only, live sessions (hours). No leave-in-place logger.
- **AI layer:** both an MCP server (live: list ports, capture, decode, safety-gated transmit) and offline analysis scripts.

Existing assets in this repo to build on (not rewrite):
- `rs232_tap.py` — mature passive sniffer: auto port/baud/framing detection (ASCII + binary scoring), per-tap reader threads, idle-gap framing, timestamp-ordered dual-direction output, text/JSONL/raw logging, receive-only safety (RTS/DTR deasserted).
- `WIRING.md` — RS232 tap wiring guide (pin 2 + pin 5 only, direction identification by idle voltage, ground-loop cautions).
- `vici_terminal.py` — "impersonate the PLC" interactive terminal pattern.
- `testrs485.py` — throwaway; superseded.

## Field playbook (the procedure the kit supports)

When a serial link misbehaves, work down this ladder — each step needs specific hardware + software from the kit:

1. **Is anyone talking?** Tap the line passively, run capture with auto-detect. Silence from one side localizes the fault immediately (dead device / dead PLC port / broken conductor).
2. **Are the line settings right?** Auto-detection reveals actual baud/framing on the wire; compare against what the PLC and device are configured for. Mismatch = config bug, done.
3. **Are the frames well-formed?** Decode with the protocol decoder (Modbus CRC check, ASCII terminator/checksum validation). Garbage or checksum failures with correct settings → wiring/noise/duplicate-node problem.
4. **Is the conversation logically correct?** Request/response pairing, timing stats, retries, NAKs, wrong-node addressing, PLC sending malformed commands. This is where PLC-code bugs show up.
5. **Impersonate one side.** Disconnect the suspect device, talk to it directly from the laptop (terminal/MCP); or simulate the device and let the PLC talk to the laptop. Whichever side misbehaves in isolation is the culprit.
6. **Compare against known-good.** Capture the same link on a working line/machine and diff.

## Hardware kit (researched Aug 2026, prices approximate)

### Key findings
- **The #1 pain point (tapping screw terminals without unlanding wires) is solved by automotive back-probe pins** (~$15/22-pc kit): spring-steel pins (straight/45°/90°) with banana sockets that slide down alongside the conductor into a screw/cage-clamp terminal or land on the exposed screw head. Supplement with mini-grabber hooks and (last resort) insulation-piercing clips.
- **Brand test plugs (Phoenix PS-5, WAGO 210-136) are NOT universal** — they only fit their own brand's terminal blocks' test shafts. Buy only if plants standardize on those blocks.
- **The Saleae Logic 8 already covers electrical-level capture** (verified): digital inputs tolerate ±25 V, so it clips directly onto RS232 (use the Async Serial analyzer with "Inverted"); RS485 taps single-ended (A and/or B vs ground). No hardware protocol analyzer (EZ-Tap $140 / IO Ninja Tap $274) needed.
- **TX/RX-swap pain fix is procedural + hardware**: DB9 M+F screw-terminal breakouts make an inline pass-through tap point with every conductor exposed; the DMM idle-voltage test in WIRING.md identifies direction before landing anything; software auto-detect tolerates a swap (both taps are receive-only, labels are just names).
- **Two adapters per duplex tap, explicitly**: a serial port has one receive line, so reading both directions of an RS232 link (or a 4-wire RS485/422 link) takes **two** adapters. Kit inventory: 2× RS232 (1 owned Oikwan + 1 new) and 2× RS485/422. A 2-wire half-duplex RS485 bus needs only one adapter (direction inferred in software).

### Core kit (~$200)
| Item | ~Price | Purpose |
|---|---|---|
| MADDOX 22-pc back-probe kit (Harbor Freight 70614) | $15 | Tap screw terminals without unlanding |
| Generic minigrabber/IC-hook lead set | $12 | Grab screw heads, breakout pins |
| Insulation-piercing clip 2-pack | $10 | Last-resort tap, no exposed metal |
| 2× DSD TECH SH-U11 USB-RS485/422 (FTDI, screw terminals) | $34 | RS485 taps: 2-wire (1 adapter) and 4-wire (2 adapters) |
| 2nd OIKWAN FTDI USB-RS232 (match existing) | $15 | Second RS232 direction |
| DaFuRui DB9 screw-terminal breakout 4-pack (2M+2F) | $13 | Inline pass-through DB9 tap points |
| Null modem + gender changers + DB25↔DB9 adapters (5 pcs) | $25 | Legacy/odd connectors |
| HiLetgo ADUM3160 USB isolator | $15 | Break laptop↔panel ground loops (note: ~200–300 mA output — isolate the adapter in use, not a loaded hub) |
| Sabrent HB-UM43 4-port hub w/ per-port switches | $15 | Power-cycle wedged adapters; label ports for stable COM numbering |
| DuPont jumper assortment | $8 | Breakout-to-adapter wiring |
| Wiha 26025 2.5 mm terminal driver | $5 | Terminal screws |
| Removable-divider small-parts organizer (see sizing below) | $25–40 | The organizer — no foam-cutting labor |

### Full-kit upgrades (→ ~$425, ceiling $600)
Upgrade one SH-U11 → **SH-U11F galvanically isolated** (+$20); **Pomona 5523** minigrabber cord kit ($70) + 2× **Pomona 6248** ($28) for better clips; **WAGO 221 pocket pack** ($20) for instant temporary splice/tap points; **Erayco DIN-rail terminal kit** ($22) for a bench "fake panel" test fixture; iCrimp ferrule kit ($28); label maker/wire markers ($25); 2× USB extensions ($8); silicone banana lead kit ($18).

### Case sizing (removable dividers, no foam)
Contents to fit: Saleae Logic 8 (~4×2×1" + wire harness pouch), 2× RS232 dongle adapters (~1 ft cables), 2× RS485 adapters (small boxes), USB isolator, USB hub, the DB9 tap dongle assembly (below), 4× spare DB9 breakouts, 5× gender changers/adapters, back-probe pins (repacked from their blister into a bin), minigrabber leads, piercing clips, DuPont jumper bundle, 2.5 mm driver, 2× USB extensions, wire markers. That's roughly 12 compartment-groups; cables/leads need bins ≥ 4×4×2". A ~13–15" wide × ~10" deep × ≥4" tall organizer with removable bins/dividers fits without being comically large — a full 19–20" Packout organizer is oversized, and most flat 2"-deep parts organizers are too shallow for coiled leads.
- **Recommended: Milwaukee PACKOUT Compact Organizer 48-22-8435** (~13×10×4.6", removable bins, ~$35) — or the Low-Profile Compact 48-22-8436 as a second layer for flat items if needed.
- **Budget alternatives:** Husky 12" Connect/Build-Out organizer (~$15–25) or Hyper Tough interlocking organizer (~$10–20) — same removable-divider style; verify bin depth ≥ 2.5" for the adapter dongles.

### Pre-built tap assemblies (make once, keep in the case)
- **RS232 inline tap dongle (Zach's 3-way passthrough concept, refined):** a DB9 M→F pass-through you drop inline between PLC and device, with a monitor side teed off it. Built from the breakout boards: male breakout + female breakout jumpered pin-for-pin (the pass-through), and from the TX, RX, GND terminals, pigtails to **two** monitor DB9 ports — one per direction, since one adapter reads one direction. Each monitor port wires line-conductor → adapter pin 2 (RXD) and ground → pin 5 only; **adapter pin 3 (TXD) is left unconnected** so the adapters' transmitters can never fight the real drivers. (This is why an off-the-shelf DB9 Y-splitter can't be used: it parallels all pins including pin 3.) Result: plug in, connect two adapters, zero terminal work — the fastest tap when the link has DB9s in it.
- **Non-standard pinouts:** keep 2 spare breakouts (or a DB9 jumper/patch box, ~$10–15) to custom-map odd pinouts into the tap dongle's monitor side, exactly as Zach described.
- **RS485 tap pigtail:** SH-U11 screw terminals pre-loaded with short leads ending in back-probe pins (A, B, GND), labeled — for links with no connector, the back-probe pins onto screw terminals remain the tap method.
- Label every adapter with its FTDI serial number + a friendly name so software can auto-identify which physical adapter is which COM port.

## Software architecture

### Principles
- `rs232_tap.py` already has the hard parts right (detection scoring, idle-gap framing, receive-only safety via RTS/DTR deassert, hold-and-sort timestamp-ordered writer). **Refactor it into a package; don't rewrite.**
- Raw captures are evidence: never mutated. Decoding is an annotation layer regenerated on demand.
- One maintainer, Windows-first, everything runs from one PowerShell window.

### Packaging
Real pip package installed editable (`pyproject.toml`, `pip install -e .`) — the CLI, MCP server, analyzers, and terminal all import one capture core. `console_scripts` gives a `serialtools` command and a stable `python -m serialtools.mcp` target. Deps: `pyserial`; extras `[mcp]` → official `mcp` Python SDK (FastMCP decorator API, stdio — not the third-party fastmcp v2); `[view]` → `rich`. Device profiles are TOML read with stdlib `tomllib` (Python 3.11+).

### Package layout
```
serial-tools/
├── pyproject.toml
├── rs232_tap.py                   # 5-line shim → `serialtools tap` (muscle memory keeps working)
├── serialtools/
│   ├── cli.py                     # list, detect, tap, decode, analyze, diff, replay, sim, term, mcp
│   ├── core/
│   │   ├── ports.py               # open_port (RTS/DTR-deassert safety), discover/list   [from rs232_tap]
│   │   ├── detect.py              # sample, score, wait_for_activity, detect             [from rs232_tap]
│   │   ├── frames.py              # Frame, LinkConfig dataclasses; ascii_render          [from rs232_tap]
│   │   ├── capture.py             # CaptureSession: reader threads + ordered writer, pluggable sinks
│   │   ├── sources.py             # FrameSource abstraction: SerialSource, ReplaySource
│   │   └── direction.py           # 2-wire RS485 half-duplex direction inference
│   ├── decoders/                  # base.py (Decoder ABC), modbus_rtu, modbus_ascii, ascii_profile
│   ├── profiles/vici.toml         # first proprietary-ASCII device profile
│   ├── storage/                   # session dir + JSONL schema (session.py, schema.py)
│   ├── analyze/                   # summary.py, timing.py, errors.py, diff.py
│   ├── sim/                       # replay.py; device.py (request→response simulator, Phase 4)
│   ├── mcp/server.py              # FastMCP stdio server
│   └── viewer/live.py             # console sink formatting + optional rich Live header
├── captures/                      # session output (gitignored)
└── tests/                         # + tests/data/ fixtures from real captures
```
`CaptureSession` vs today's script: frames get a monotonic `seq`; output sinks are a list of callables (console printer, session writer, in-memory ring buffer for MCP, live decoder); a `wiring` mode — `rs232`, `rs485-4w` (two taps, same as RS232), `rs485-2w` (one tap, direction inference on).

### Capture session format
One directory per capture: `captures/20260814-1432-vici-line/` containing `session.json` (schema_version, wiring, taps with detected settings/scores, gap_ms, free-text notes, device/profile, tool version), `frames.jsonl` (raw, append-only), `decoded.jsonl` (regenerated by `decode`), `raw/<TAP>.bin`, `tap.log` (human text, unchanged format). `frames.jsonl` keeps today's fields (old captures stay readable) and adds `seq`, `src` (physical tap measured), `dir` (logical direction — equals `src` on RS232/4-wire, inferred on 2-wire) and `dir_conf`.

### Decoder plugin API
```python
@dataclass
class Decoded:
    proto: str; ok: bool          # parsed AND validated (CRC/checksum good)
    summary: str                  # one line: "req: read holding 40001 x2 @slave 3"
    role: str | None = None      # "request"|"response" → feeds direction inference
    fields: dict = ...; errors: list[str] = ...   # "crc_mismatch", "short_frame", ...

class Decoder(ABC):
    def resplit(self, data) -> list[bytes] | None: ...  # fix idle-gap mis-framing (Modbus length+CRC scan)
    def decode(self, data, prev: Decoded | None) -> Decoded | None: ...  # prev = pending request context
```
Registry is a plain dict — adding DF1/BACnet MS/TP later is one module + one entry. **Proprietary ASCII devices need no code**: one generic `AsciiProfileDecoder` driven by a ~20-line TOML profile (terminator/STX-ETX framing, checksum type, command table with regex patterns, response patterns). Which table matches classifies request vs response, which also feeds direction inference.

### 2-wire RS485 direction inference (`core/direction.py`)
Layered: (1) protocol-authoritative when a decoder is active (`Decoded.role`; Modbus addr/func echo + exception bit); (2) timing/shape heuristic fallback — cluster by preceding-gap/length/prefix, master polls are short and periodic after long idle, responses arrive within short turnaround; `dir_conf` = agreement over sliding window; (3) manual override (`--first-is master` or profile hint). `src` is always kept so wrong inference is recoverable via `decode --redirect`.

### MCP server (`serialtools mcp`, stdio; `claude mcp add serialtools -- python -m serialtools.mcp`)
Owns `CaptureSession` objects in-process (same class the CLI uses); each tap writes the normal session dir plus a ~10k-frame ring buffer for cursor reads. Tools: `list_ports`, `detect_settings`, `start_tap(ports, wiring, decoder/profile, notes)`, `tap_status`, `get_frames(session_id, since_seq, decoded=True)` (cursor pattern, reports drops), `stop_tap`, `list_captures`, `decode_capture`, `analyze_capture`, `send_bytes`.

**Transmit safety — three independent gates:** (1) `send_bytes` is not registered at all unless the server was started with `--allow-tx`; (2) per call, `confirm` must be the literal string `"SEND <port>"`; (3) target port must not belong to a running tap session (taps are wired receive-only), and every transmit is appended to `captures/tx-audit.jsonl`.

### Live viewer
`rich` only, no TUI framework or web page. Default `serialtools tap` output stays today's plain scrolling text (works redirected/remote). `--live` adds a pinned 3-line `rich.Live` header: per-tap byte rates, frame count, decode-error count, seconds-since-last-frame silence timer; decoder `summary` becomes an extra column. ~100 lines.

### Offline analyzers
`serialtools analyze <dir> [--json]`: **summary** (frames/bytes/rates per direction, size histogram); **timing** (request→response latency min/median/p95/max, poll-period stability, **unanswered requests with wall-clock timestamps** — the #1 "why is it misbehaving" answer, silence gaps); **errors** (CRC/checksum failure rate bucketed over time — rising rate = noise/termination, malformed frames, retry detection, NAK/ACK counts, baud-drift symptoms); **conformance** (unknown commands, unexpected responses — needs profile). `serialtools diff <good> <bad>` compares reports: latency shift, poll-rate change, new error types, response-omission rate.

### Testing without hardware
- Unit: pyserial `loop://` (open_port already uses `serial_for_url`); decoders/analyzers are pure functions over fixtures in `tests/data/` recorded from real captures.
- `ReplaySource` feeds a stored `frames.jsonl` straight into `CaptureSession` (original timing or `--speed 20`) — MCP, viewer, direction inference, and analyzers develop entirely off-plant.
- Integration: com0com virtual pair on Windows; `serialtools replay <capture> --port COM20` plays real bytes with original timing while the tap listens on COM21.
- **Device simulator (Phase 4)**: `serialtools sim <capture|profile> --port COMx` mines a request→response table from a decoded capture or profile and answers live — lets PLC code be exercised against a simulated valve/drive.

## Build phases

1. **Package refactor + session format** (foundation, no new behavior): `pyproject.toml`; move logic per the mapping (ports/detect/frames from rs232_tap.py; reader/writer → `CaptureSession` with sinks + `seq`); session-dir output; `--wiring` flag (rs485-2w accepted, `dir="BUS"` for now); shim. Exit test: identical console behavior vs today on a com0com replay.
2. **Decoders + direction inference + offline analysis** (the diagnostic payoff): Decoder ABC + registry; `modbus_rtu` (CRC16 + resplit), `modbus_ascii`, `ascii_profile` + `vici.toml`; `direction.py`; `decode`/`analyze`/`diff`; `ReplaySource` + `replay` + fixtures.
3. **MCP server + live view**: full tool set, ring buffer + `since_seq` cursor, TX triple-gating; `claude mcp add` setup docs; rich `--live` header.
4. **Simulation + terminal + docs**: `sim/device.py`; generalize `vici_terminal.py` into `serialtools term --profile X`; WIRING.md RS485 tap section; build the pre-made tap harnesses once hardware arrives.

Hardware purchasing happens in parallel with Phase 1 (nothing in Phases 1–2 needs new hardware — development runs on replay + com0com).

## Verification

- **Phase 1:** replay a real captured log through com0com; confirm `serialtools tap` output is byte-identical in behavior to `python rs232_tap.py` today; old JSONL files still load.
- **Phase 2:** unit tests on fixtures (known Modbus frames with good/bad CRC, VICI exchanges from existing logs); `analyze` on a real past capture produces sane latency/error numbers; deliberately corrupt a fixture and confirm error analytics flag it.
- **Phase 3:** `claude mcp add` the server, run a live conversation against a com0com replay: list ports → start_tap → get_frames cursor paging → analyze; verify `send_bytes` is absent without `--allow-tx` and refuses a wrong `confirm` string with it.
- **Phase 4:** run `serialtools sim` with the VICI profile on one com0com end and `serialtools term` on the other; full round-trip.
- **Hardware:** on arrival, bench-test with the DIN-rail "fake panel" fixture (full kit) or two adapters back-to-back before first field use; label adapters with FTDI serials.

## Critical files
- `rs232_tap.py` — source of all core logic being refactored (mapping table above)
- `serialtools/core/capture.py` — new `CaptureSession`, heart of everything
- `serialtools/decoders/base.py` — Decoder ABC + Decoded schema
- `serialtools/storage/session.py` — session dir + JSONL schema
- `serialtools/mcp/server.py` — MCP tools + TX gating
- `WIRING.md` — extend with RS485 tap section + back-probe technique
