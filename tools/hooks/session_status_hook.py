# SPDX-License-Identifier: MIT
"""Claude Code hook: egyetlen allapotfajlt ir a session-ertesitonek (spec 4.2).

Ez a szkript **minden hook-esemenynel lefut, minden sessionben**, tehat a
sebessege kozvetlenul a felhasznalo sessionjeinek sebessege (spec 3.1: a hook
szinkron fut, ezert soha nem beszelhet a Dialhoz kozvetlenul). Ket dolog kovetkezik
ebbol, es mindketto szandekos dontes:

1. **Nincs CIM/WMI es nincs PowerShell.** A szulolanc bejarasa `ctypes`-szal, a
   Toolhelp pillanatkeppel tortenik - ez ezredmasodperces, mig egy `pwsh` inditas
   ~300 ms lenne, esemenyenkent.
2. **A feloldott PID-et gyorsitotarazzuk** a mar meglevo allapotfajlbol: egy
   sessionben csak az elso esemeny jar a szulolanc bejarasaval.

A szkript **soha nem bukik el hangosan**: ha barmi nem sikerul, csendben kilep 0-val.
Egy ertesito-kiegeszito nem allithatja meg a felhasznalo munkajat.
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from session_agent.hookstate import (  # noqa: E402
    DELETE,
    SUBAGENT_START,
    SUBAGENT_STOP,
    focus_url_from_env,
    next_record,
    session_id_of,
    state_for,
)

# A teszteles miatt felulirhato - kulonben a probak a valodi allapotmappaba irnanak.
STATUS_DIR = os.environ.get("CLAUDE_SESSION_STATUS_DIR") or os.path.join(
    os.path.expanduser("~"), ".claude", "session-status"
)
CLI_EXE = "claude.exe"
MAX_DEPTH = 12


def _process_table():
    """pid -> (szulo pid, folyamatnev) a Toolhelp pillanatkepbol."""
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE:
        return {}

    table = {}
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.decode("ascii", "ignore").lower()
            table[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), name)
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return table


def resolve_session_pid():
    """A sajat `claude.exe` osunk pid-je, vagy None.

    Merve 2026-09-10-en: egy hook-szeru unokafolyamattol negy szintre volt a
    session `claude.exe`-je. A `MAX_DEPTH` bosegesen fedi ezt.
    """
    try:
        table = _process_table()
    except Exception:
        return None
    if not table:
        return None

    current = os.getpid()
    for _ in range(MAX_DEPTH):
        entry = table.get(current)
        if entry is None:
            return None
        parent, _name = entry
        parent_entry = table.get(parent)
        if parent_entry is None:
            return None
        if parent_entry[1] == CLI_EXE:
            return parent
        current = parent
    return None


def _read_record(path):
    """A korabban kiirt allapotfajl (pid, focus_url, alugynokok), vagy {}.

    A korabban feloldott pid innen jon - igy csak az elso esemeny dolgozik.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_atomic(path, record):
    """Ideiglenes fajlba irunk, majd atnevezunk: az ugynok soha nem lat csonkot."""
    directory = os.path.dirname(path)
    handle, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(record, out)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def main():
    # `pythonw.exe` alatt a `sys.stdin` lehet None. A hook a payload nelkul
    # ertelmetlen, de nem szabad hangosan elbuknia.
    if sys.stdin is None:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    session_id = session_id_of(payload)
    if session_id is None:
        return 0

    event = payload.get("hook_event_name")
    if state_for(payload) is None and event not in (SUBAGENT_START, SUBAGENT_STOP):
        return 0

    os.makedirs(STATUS_DIR, exist_ok=True)
    path = os.path.join(STATUS_DIR, session_id + ".json")
    previous = _read_record(path)

    # A pid feloldasa a draga resz, ezert csak akkor, ha nincs meg a fajlban.
    pid = previous.get("pid") if isinstance(previous.get("pid"), int) else None
    record = next_record(previous, payload, pid, time.time())
    if record is None:
        return 0

    if record == DELETE:
        try:
            os.remove(path)
        except OSError:
            pass
        return 0

    if record.get("pid") is None:
        record["pid"] = resolve_session_pid()

    # A Warp-fokusz URL a kornyezetbol jon. Ha egy kesobbi hook-hivas mar nem
    # latna (mas indito lanc), a korabban kiirt erteket tartjuk meg - egy
    # egyszer megszerzett tab-azonositot nem dobunk el.
    focus_url = focus_url_from_env(os.environ) or previous.get("focus_url")

    if focus_url:
        record["focus_url"] = focus_url

    _write_atomic(path, record)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Egy ertesito-kiegeszito soha nem allithatja meg a sessiont.
        sys.exit(0)
