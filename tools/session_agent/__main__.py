# SPDX-License-Identifier: MIT
"""Az ugynok indithato modulkent is: `python -m session_agent`.

Ezt hivja a `SessionStart` hook (tools/hooks/agent_supervisor.py), es ezt hasznalja
a `tools/session-agent.ps1` is. A portot magatol megkeresi: a UIFlow2 firmware
USB-azonositoja `303a:81dd`, ez kulonbozteti meg minden mastol a gepen.

Ha nincs bedugva eszkoz, **nem hiba**: az ugynok elindul, es a szokasos modon
ujraprobalja - a Dial barmikor bedughato menet kozben.
"""

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from session_agent.agent import Agent
else:
    from .agent import Agent

VID_PID = "303a:81dd"

# Ennyit varunk a bedugasra, mielott feladjuk. Ugyanaz a nagysagrend, mint a
# tetlensegi kilepes: egy eszkoz nelkul varakozo ugynok ugyanolyan arva folyamat.
WAIT_FOR_DEVICE_S = 900


def find_port():
    """Az elso M5Dial soros portja, vagy None."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for port in list_ports.comports():
        hwid = (port.hwid or "").lower()
        if "303a" in hwid and "81dd" in hwid:
            return port.device
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port = argv[0] if argv else os.environ.get("M5DIAL_PORT")

    if not port:
        # Portszamot SEHOVA nem egetunk be: firmware-iras utan az eszkoz
        # ujra-enumeralodik es mas COM-szamot kap (nalunk COM3 -> COM4). Ha most
        # nincs bedugva, varunk ra - az ugynok igy is fogja a zarat, tehat nem
        # indul kozben egy masodik peldany.
        import time

        deadline = time.time() + WAIT_FOR_DEVICE_S
        while True:
            port = find_port()
            if port:
                break
            if time.time() > deadline:
                # Nem varunk orokke: ha nincs eszkoz, egy futo ugynok csak egy
                # arva folyamat lenne. A kovetkezo session SessionStart-ja ugyis
                # ujraprobalja.
                print("nincs M5Dial ({}), kilepek".format(VID_PID))
                return 0
            time.sleep(5)

    Agent(port).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
