# Wiring a passive serial tap (RS232 and RS485)

## The one thing that decides everything

A serial port has **one** receive line. One USB-to-RS232 adapter can therefore
listen to **one direction only**. To capture both PLC output and PLC input at
the same time you need **two adapters**. Buy a second Oikwan (they're ~$10) —
there is no clever wiring that gets both directions onto one adapter without
losing the ability to tell who said what.

With the one adapter you have now you can still capture one direction at a
time, which is often enough to work out the protocol.

## DB9 pinout of your adapter

The Oikwan adapter is a DB9 **male**, wired as **DTE** (same as a PC serial
port). Only three pins matter:

| Pin | Signal | Direction on your adapter | Use in the tap |
|-----|--------|---------------------------|----------------|
| 2   | RXD    | **input**                 | connect to the line you want to watch |
| 3   | TXD    | output                    | **leave disconnected** |
| 5   | GND    | signal ground             | connect to the link's ground |

Pin 3 must stay unconnected. If your adapter's transmitter reaches the link it
will fight the real driver, and you'll corrupt the traffic you're trying to
observe. Pins 1, 4, 6, 7, 8, 9 stay unconnected too.

## Which wire carries which direction

The cable between the PLC and the device has two data conductors. One is
driven by the PLC, one is driven by the device. On a DB9 port, pin 3 is TXD
and pin 2 is RXD *by name* on both ends, but the direction reverses depending
on whether the port is DTE or DCE:

- **DTE port** (PLC programming ports, PCs): pin 3 = output, pin 2 = input
- **DCE port** (many modems, scales, printers, drives): pin 3 = input, pin 2 = output

So don't assume pin 3. Identify the driven conductor empirically:

1. Unplug the cable at the **device** end, leaving the PLC powered and running.
2. With a DMM, measure each data conductor against pin 5 (ground).
3. The conductor sitting at **−5 V to −12 V** is being driven by the PLC — that
   is the **PLC output** line. (Idle RS232 is the mark state, a negative voltage.)
4. The other conductor floats near **0 V** — that is the **PLC input** line,
   normally driven by the device.

Repeat at the PLC end if you want to confirm the device side the same way.

If you can't unplug anything, tap one line, watch the traffic, and infer it
from the pattern: in almost every PLC protocol the PLC is the master and sends
the short, regularly repeating query; the device replies with the longer,
variable frame.

## Making the tap without cutting the cable

Best option is an inline **DB9 male-to-female screw-terminal breakout board**
(~$8). Plug it into the existing link so the PLC↔device connection passes
through untouched, then run jumper wires from the terminals to your adapters.

**Do not use a plain DB9 Y-splitter.** It parallels *all* pins, including
pin 3, which puts your adapter's transmitter on the bus. If a Y-splitter is
all you have, physically remove or insulate pin 3 on the splitter leg going
to the adapter.

## Final connections

```
                 PLC output conductor
  PLC  ─────┬────────────────────────────────┬───── DEVICE
            │                                │
            │        PLC input conductor     │
       ─────┼────────────────────────────────┼─────
            │        signal ground (pin 5)   │
       ─────┼───────────────┬────────────────┼─────
            │               │
        pin 2│           pin 5               │pin 2 ... pin 5
      ┌──────┴──────┐   (both)         ┌─────┴───────┐
      │  ADAPTER A  │──────────────────│  ADAPTER B  │
      │  "PLC>DEV"  │                  │  "DEV>PLC"  │
      │  pin 3 n/c  │                  │  pin 3 n/c  │
      └─────────────┘                  └─────────────┘
```

**Adapter A — captures PLC output**
- A pin 2 ← PLC output conductor
- A pin 5 ← link signal ground
- A pin 3 → no connection

**Adapter B — captures PLC input**
- B pin 2 ← PLC input conductor (the device's output)
- B pin 5 ← same link signal ground
- B pin 3 → no connection

## Cautions

**Ground loops.** You are bonding your laptop's ground to the link's signal
ground. If the PLC and your laptop sit on different earth references, current
can flow through that wire. Run the laptop on battery, or use a USB isolator.
Connect ground at exactly one point — don't ground both adapters separately to
different places on the machine.

**Loading.** An RS232 receiver is 3–7 kΩ. Adding a second one in parallel
roughly halves the load, which is still inside what a compliant driver must
handle. It's safe at normal baud rates. If the link is long or already
marginal, keep the tap stubs short.

**Hardware flow control.** If the link uses RTS/CTS you're only tapping the
data lines, so you'll see the data but not the handshake. The script disables
flow control on the adapters so it never blocks waiting for CTS.

**Live equipment.** Wiring into a running control system can drop the link if
you short two conductors. Do it on a machine that's safe to stop.

## The tap dongle (build once, then tapping is plug-in)

When the link passes through DB9 connectors, skip the terminal work entirely.
Build this once from the inline M/F breakout board and two female breakouts:

1. **Inline board** (DB9 male one end, female the other, screw terminals in
   the middle): drops into the existing PLC-to-device connection; everything
   passes through, every conductor is now on a screw terminal.
2. **Monitor port A** (female breakout, plugs onto adapter #1): wire from the
   inline board's **pin 3** terminal to the monitor breakout's **pin 2**, and
   inline **pin 5** to monitor **pin 5**.
3. **Monitor port B** (female breakout, plugs onto adapter #2): inline
   **pin 2** to monitor **pin 2**, inline **pin 5** to monitor **pin 5**.
4. **Nothing lands on pin 3 of either monitor breakout — ever.** That is the
   adapter's transmitter; connecting it drives the live line. (This is also
   why an off-the-shelf DB9 Y-splitter can't be used: it parallels all pins,
   pin 3 included.)

Label the pigtails direction-neutrally (`LINE-PIN3`, `LINE-PIN2`): which side
is the PLC depends on whether the PLC port is DTE and whether the cable is
straight-through. Both monitor ports are receive-only, so a wrong guess just
swaps the labels — rename them in software, nothing is miswired.

## Tapping screw terminals without unlanding wires

Use the back-probe pins: slide a pin down alongside the conductor into the
terminal's clamp (or spear the exposed screw head) and connect the banana end
to the adapter pigtail. Mini-grabber hooks work on screw heads and breakout
pins; insulation-piercing clips are the last resort (they leave a pinhole).
Never unland a conductor on a live machine just to add a tap wire.

## Tapping RS485

**2-wire half-duplex (most common):** both directions share one A/B pair, so
**one** RS485 adapter sees everything. Wire adapter A(+/D+) to bus A, B(-/D-)
to bus B, GND to bus common if the link has one. Direction is inferred in
software:

```powershell
serialtools tap -p COM5 --wiring rs485-2w --decoder modbus_rtu
```

Do **not** enable the adapter's termination resistor (the bus is already
terminated at both ends) and keep the stub short. The tap never transmits, so
the adapter's driver stays off the bus automatically.

If A/B polarity is guessed wrong you get framing garbage, not damage — swap
the two wires. Modbus RTU frames want a tighter gap: `--gap 4` at 9600,
`--gap 2` at 19200+.

**4-wire full duplex (RS422-style):** two pairs, one driven by each side —
exactly like RS232. Two adapters, one listening across each pair (RX+ to the
pair's +, RX- to the pair's -), `--wiring rs485-4w`, labels per direction.

## Then run it

Just run it with no arguments. It finds the adapters and works out the baud
rate, data bits and parity by itself:

```powershell
serialtools tap        # or: python rs232_tap.py (same thing)
```

It sweeps 48 combinations (8 baud rates × 6 framings), listening 2 seconds at
each, and locks on when at least 95% of the bytes decode as printable ASCII.
If a full sweep finds nothing it starts over, because a PLC that polls every
few seconds can easily stay silent through an otherwise-correct candidate.
**Traffic has to be flowing while it detects** — trigger whatever makes the
PLC talk.

A full sweep takes about 90 seconds per port in the worst case, but common
settings are tried first so it usually locks within the first few tries.

Useful variations:

```powershell
serialtools list                                          # just show the ports
serialtools tap --detect-only                             # find the settings, don't capture
serialtools tap -p COM3 -p COM4                           # auto baud, but only these ports
serialtools tap -p COM3=PLC-OUT -p COM4=PLC-IN -b 9600    # skip detection entirely
serialtools tap --binary                                  # link isn't ASCII
serialtools tap --detect-seconds 5                        # slow poller
serialtools tap --profile vici --live                     # live decode + status header
```

Two notes. Detection assumes ASCII; if the link is a binary protocol like
Modbus RTU, pass `--binary` to switch to an entropy-based score. And avoid `>`
inside a label — PowerShell treats it as output redirection unless you quote
the whole argument.
