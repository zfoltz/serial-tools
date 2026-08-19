# Serial troubleshooting kit — shopping list

Researched Aug 2026. Prices approximate. Already owned: 1× Oikwan FTDI USB-RS232,
Saleae Logic 8, Windows laptop. See PLAN.md for how each item is used.

## Core kit (~$200)

- [ ] **MADDOX 22-pc back-probe kit** — Harbor Freight item 70614, $15
      <https://www.harborfreight.com/back-probe-kit-22-piece-70614.html>
      (Amazon equivalent: HORUSDY 22-pc, ~$18, B096TS8PC1)
      *The screw-terminal tap solution: spring pins slide in alongside the conductor.*
- [ ] **Minigrabber/IC-hook lead set** (generic) — ~$12, Amazon
- [ ] **Insulation-piercing clips, 2-pack** — ~$10
      <https://www.amazon.com/Bei-Qian-Insulation-Multimeter-Automotive/dp/B083JJGVCV>
      *Last resort when no metal is exposed; leaves a pinhole.*
- [ ] **2× DSD TECH SH-U11 USB-RS485/422** (FTDI FT232R, screw terminals) — $17 ea
      <https://www.amazon.com/DSD-TECH-Converter-Compatible-Windows/dp/B07B416CPK>
      *Does both 2-wire RS485 and 4-wire RS422 — two needed for full-duplex both-direction taps.*
- [ ] **2nd OIKWAN FTDI USB-RS232** (match existing) — ~$15
      <https://www.amazon.com/gp/product/B0759HSLP1>
      *Two adapters required to read both directions of an RS232 link.*
      (Alternative with TX/RX activity LEDs: Gearmo FTDI, B004WLA4P4, ~$19)
- [ ] **Inline DB9 male-to-female breakout board, 2-pack** — ~$12
      <https://www.amazon.com/dp/B0B714YHDD>
      *Male one end, female the other, screw terminals in the middle — a
      one-piece pass-through tap point. Preferred core of the tap dongle
      (Zach's pick); one spare.*
- [ ] **DaFuRui DB9 solderless screw-terminal breakouts, 4-pack (2M+2F)** — ~$13
      <https://www.amazon.com/DaFuRui-Solderless-Terminal-Connector-Breakout/dp/B087B9TJC9>
      *The 2 female ones become the dongle's monitor ports (they plug onto the
      DB9-male adapters); males are spares for odd pinouts.*
- [ ] **DB9 adapter set** (~$25 total): null modem F-F slim (B008JG7PF0),
      M-M + F-F gender changers, DB25M→DB9F and DB25F→DB9M (~$6 ea)
- [ ] **HiLetgo ADUM3160 USB isolator** — ~$15
      <https://www.amazon.com/HiLetgo-ADUM3160-Voltage-Isolator-Support/dp/B07235PR4V>
      *Ground-loop protection. ~200–300 mA output: isolate the adapter in use, not a loaded hub.*
- [ ] **Sabrent HB-UM43 4-port hub, per-port switches** — ~$15
      <https://www.amazon.com/Sabrent-4-Port-Individual-Switches-HB-UM43/dp/B00JX1ZS5O>
- [ ] **DuPont jumper assortment** (Elegoo/Edgelec 120-pc) — ~$8
- [ ] **Wiha 26025 2.5 mm slotted terminal driver** — $5
      <https://www.wihatools.com/products/precision-slotted-2-5-3-32-x-50mm>
- [ ] **Organizer, removable dividers** (~13–15" × ~10" × ≥4", bins ≥2.5" deep):
      **Milwaukee PACKOUT Compact Organizer 48-22-8435**, ~$35
      <https://www.homedepot.com/p/305821962> — or Husky 12" Build-Out (~$20) /
      Hyper Tough interlocking organizer (~$15) as budget options.

## Full-kit upgrades (→ ~$425; ceiling $600)

- [ ] Swap one SH-U11 → **DSD TECH SH-U11F isolated RS485/422** (+$20)
      <https://www.amazon.com/DSD-TECH-SH-U11F-Industrial-Application/dp/B083XSG1RG>
- [ ] **Pomona 5523 Minigrabber patch cord kit** — ~$70 (Transcat/TestEquipmentDepot)
- [ ] 2× **Pomona 6248-12** minigrabber-to-DMM-jack — ~$14 ea
- [ ] **WAGO 221 Lever-Nut 28-pc pocket pack** — ~$20 (B01N0LRTXZ)
      *Instant temporary tap/splice points.*
- [ ] **Erayco UK2.5B DIN-rail terminal kit** — ~$22 (B07KRDJCYB)
      *Bench-top "fake panel" tap-practice / test fixture.*
- [ ] **iCrimp/IWISS HSC8 ferrule crimper + ferrule kit** — ~$28 (B07LCF39W9)
- [ ] Label maker (NIIMBOT D11 ~$25) or write-on wire marker book (~$8)
- [ ] 2× 3-ft USB-A extension cables — ~$8
- [ ] Silicone banana test lead kit w/ alligators — ~$18

## Deliberately skipped

- **Hardware line monitors** (Stratus EZ-Tap $140, Tibbo IO Ninja Tap $274) —
  redundant with the Logic 8 + two-adapter tap + this repo's software.
- **Phoenix PS-5 / WAGO 210-136 test plugs** — brand-specific: they only fit
  their own terminal blocks' test shafts, not generic screw terminals. Revisit
  only if plants standardize on Phoenix CLIPLINE or WAGO TOPJOB blocks.
- **Pocket DMM** — already owned.

## Saleae Logic 8 notes (verified against Saleae docs)

- Digital inputs tolerate ±25 V continuous → clips directly onto RS232 (±12 V).
  Set the Async Serial analyzer to **Inverted** for RS232.
- RS485: tap **single-ended** (A and/or B vs ground); no true differential.
  A-line usually non-inverted, B inverted.
- Analog channels are low-voltage only — use digital channels for serial.

## Build-once tap assemblies (after parts arrive)

1. **RS232 inline tap dongle**: the one-piece inline M/F board drops into the
   link (pass-through); from its pin 3, pin 2, and pin 5 terminals, pigtail to
   two female monitor breakouts — line conductor → monitor pin 2, ground →
   monitor pin 5, **monitor pin 3 left unconnected** on both. Label the
   monitor ports direction-neutrally (LINE-PIN3 / LINE-PIN2). Full recipe in
   WIRING.md.
2. **RS485 tap pigtail**: SH-U11 terminals pre-loaded with leads ending in
   back-probe pins (A, B, GND), labeled.
3. Label every adapter with its FTDI serial number + friendly name.
