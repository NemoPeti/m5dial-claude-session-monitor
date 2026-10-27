# SPDX-License-Identifier: MIT
"""Claude Code `SessionStart` hook: elinditja a session-ugynokot, ha meg nem fut.

Miert csak `SessionStart`, es miert nincs `SessionEnd` par ja?

Mert a leallitast az ugynok maga vegzi: ha egy ideig egyetlen Claude-session sincs,
kilep (lasd `session_agent/supervisor.py`). Igy nem kell a `SessionEnd` pillanataban
kizarni a szamolasbol a sajat, epp kilepo folyamatunkat, nem kell jelzofajl, es nem
kell folyamatot leallitani. A kovetkezo session `SessionStart`-ja ugyis ujrainditja.

A tobbszoros indulas nem itt van megoldva, hanem az ugynokben: a felhasznalo
5-10 sessiont indit egyszerre, mindegyik lefuttatja ezt a hookot, es mindegyik
inditana egy ugynokot. Egyetlen peldany szerzi meg a zarat, a tobbi azonnal es
csendben kilep. Igy nincs olyan ablak, amiben ket ugynok verekszik a COM-porton.

Mint minden hook: **soha nem bukik el hangosan es soha nem varakozik**. A session
sebessege mulik rajta (spec 3.1), ezert leválasztott folyamatot indit, es azonnal
visszater.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

STATUS_DIR = os.environ.get("CLAUDE_SESSION_STATUS_DIR") or os.path.join(
    os.path.expanduser("~"), ".claude", "session-status"
)
LOCK_PATH = os.path.join(STATUS_DIR, "agent.pid")


def _lock_holder_alive():
    """Fut-e mar ugynok. Olcso ellenorzes, hogy ne inditsunk feleslegesen."""
    try:
        with open(LOCK_PATH, "r", encoding="utf-8") as handle:
            pid = int(handle.read().strip())
    except (OSError, ValueError):
        return False

    sys.path.insert(0, REPO)
    try:
        from session_agent.procs import process_table
    except ImportError:
        return False
    return pid in process_table()


def start_agent():
    """Leválasztott ugynok-folyamat inditasa. Nem varunk ra."""
    launcher = os.path.join(REPO, "session_agent", "__main__.py")
    if not os.path.exists(launcher):
        return False

    creationflags = 0
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: az ugynok tulelje a
        # sessiont, es ne kapja meg annak Ctrl-C-jet.
        # CREATE_NO_WINDOW: ne villanjon fel konzolablak. Elesben ez zavaro volt:
        # a `python.exe` konzolos alkalmazas, es minden hook-futasnal felvillant
        # egy ablak - minden promptnal, minden sessionben.
        creationflags = 0x00000008 | 0x00000200 | 0x08000000

    try:
        subprocess.Popen(
            [sys.executable, "-m", "session_agent"],
            cwd=REPO,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except (OSError, ValueError):
        return False
    return True


def main():
    # A payloadot beolvassuk, hogy a hook ne akadjon meg a stdin-en, de nem
    # hasznaljuk: ez a hook nem a sessionrol szol, hanem az ugynokrol.
    # `pythonw.exe` alatt a `sys.stdin` lehet None - ilyenkor nincs mit olvasni.
    if sys.stdin is not None:
        try:
            json.load(sys.stdin)
        except (ValueError, OSError):
            pass

    if _lock_holder_alive():
        return 0

    os.makedirs(STATUS_DIR, exist_ok=True)
    start_agent()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Egy ertesito-kiegeszito soha nem allithatja meg a felhasznalo munkajat.
        sys.exit(0)
