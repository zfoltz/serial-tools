"""Serial port opening and discovery.

open_port() is the single place a port is ever opened, and it always deasserts
RTS/DTR and disables flow control so a tap adapter never drives the line.
"""

from __future__ import annotations

import serial
from serial.tools import list_ports

PARITY = {
    "N": serial.PARITY_NONE,
    "E": serial.PARITY_EVEN,
    "O": serial.PARITY_ODD,
    "M": serial.PARITY_MARK,
    "S": serial.PARITY_SPACE,
}
BYTESIZE = {5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS, 8: serial.EIGHTBITS}
STOPBITS = {"1": serial.STOPBITS_ONE, "1.5": serial.STOPBITS_ONE_POINT_FIVE, "2": serial.STOPBITS_TWO}


def open_port(port: str, baud: int, bytesize: int, parity: str, stopbits: str, timeout: float):
    """serial_for_url passes plain names like COM3 straight through, and also
    accepts rfc2217://host:port for a networked serial server."""
    ser = serial.serial_for_url(
        port,
        baudrate=baud,
        bytesize=BYTESIZE[bytesize],
        parity=PARITY[parity],
        stopbits=STOPBITS[stopbits],
        timeout=timeout,
        rtscts=False,
        dsrdtr=False,
        xonxoff=False,
    )
    # Never drive the line. Adapters assert these on open by default.
    for attr in ("rts", "dtr"):
        try:
            setattr(ser, attr, False)
        except (OSError, serial.SerialException, NotImplementedError):
            pass
    return ser


def discover_ports() -> list[str]:
    return [p.device for p in list_ports.comports()]


def port_details() -> list[dict]:
    return [
        {"device": p.device, "description": p.description, "hwid": p.hwid or ""}
        for p in list_ports.comports()
    ]


def show_ports():
    ports = port_details()
    if not ports:
        print("No serial ports found. Plug in the USB adapter and try again.")
        return
    for p in ports:
        print(f"{p['device']:<8} {p['description']}")
        if p["hwid"] and p["hwid"] != "n/a":
            print(f"{'':<8} {p['hwid']}")
