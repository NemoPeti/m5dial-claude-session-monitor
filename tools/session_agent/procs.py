# SPDX-License-Identifier: MIT
"""A Windows-oldali folyamat-begyujtes: melyik `claude.exe` valodi session.

Ez a modul csak a NYERS adatot allitja elo; hogy melyik folyamat szamit
sessionnek, azt a `snapshot.is_session_process` donti el (spec 4.3).

A szetvalasztas szandekos: a szures tiszta logika, asztali Pythonon tesztelheto,
az itteni resz viszont Win32-t kerdez, tehat nem unit-tesztelheto. Ami itt megis
tesztelheto - a parancssor ertelmezese -, az kulon fuggveny.

Merve 2026-09-10-en (spec 4.3): a "nevtelen" claude.exe folyamatok NEM sessionok,
hanem a Claude Desktop Electron-alkalmazasa, egy masik binarisbol. Ezert szurunk
eleresi utra es szulo-folyamatra, nem a --name meglétére.

## Miert ket retegu a begyujtes?

Az elso valtozat minden korben egy `Get-CimInstance` hivast inditott PowerShellben.
Elesben megmerve ez **1990 ms** volt - az ugynok viszont masodpercenkent kuld
pillanatkepet (spec 3), tehat ez onmagaban tullepte a teljes koridot.

Ezert a begyujtes ketretegu:

- **minden korben** egy `ctypes` Toolhelp-pillanatkep fut. Ez adja a pid-eket, a
  szulo pid-eket es a folyamatneveket, ezredmasodpercek alatt. Ennyi kell ahhoz,
  hogy tudjuk, ELETBEN van-e meg a session, es ki a szuloje.
- **csak akkor**, ha uj `claude.exe` pid jelent meg, fut egy CIM-lekerdezes, ami a
  teljes eleresi utat es a parancssort (`--name`) hozza. Ezek egy folyamat eleteben
  nem valtoznak, tehat pid-enkent egyszer kell megkerdezni.

A gyorsitotar a halott pid-eket kitakaritja, kulonben egy hosszan futo ugynokben
korlatlanul nőne.
"""

import ctypes
import json
import os
import time
import subprocess
from ctypes import wintypes

# A CLI binaris; a Claude Desktop ugyanilyen nevu exe-je mas utvonalon el.
CLI_PATH_DEFAULT = os.path.expanduser(r"~\.local\bin\claude.exe")

# Ezek gyerekekent indul egy valodi, felhasznaloi session.
SHELL_NAMES = {
    "pwsh.exe",
    "powershell.exe",
    "cmd.exe",
    "bash.exe",
    "windowsterminal.exe",
    "wt.exe",
    "conhost.exe",
}

TARGET_EXE = "claude.exe"

# pid -> {"exe_path": ..., "name": ...}; csak uj pid eseten toltjuk fel.
_detail_cache = {}

# pid -> hanyszor probaltuk mar lekerdezni. Ennyi sikertelen probalkozas utan
# feladjuk, es nem inditunk ujabb PowerShellt miatta.
_attempts = {}
#: Ennyi masodperc utan ujraprobalunk egy korabban feladott pid-et. Rovid,
#: mert a feladas lehet egy atmeneti CIM-hiba is, es addig a session
#: lathatatlan a gyurun.
DETAIL_RETRY_S = 60

MAX_DETAIL_ATTEMPTS = 3


def parse_name(cmdline):
    """A `--name <ertek>` erteke a parancssorbol, vagy None.

    Tamogatja a `--name X` es a `--name=X` alakot is, es kezeli az idezojelbe
    tett, szokozos erteket.
    """
    if not cmdline:
        return None
    tokens = _tokenize(cmdline)
    for i, token in enumerate(tokens):
        if token == "--name":
            if i + 1 < len(tokens):
                value = tokens[i + 1]
                # A kovetkezo token nem lehet maga is kapcsolo.
                return None if value.startswith("--") else value
            return None
        if token.startswith("--name="):
            value = token[len("--name="):]
            return value or None
    return None


def _tokenize(cmdline):
    """Parancssor szetszedese, az idezojeleket tiszteletben tartva."""
    tokens = []
    current = []
    in_quotes = False
    for ch in cmdline:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch.isspace() and not in_quotes:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


class _PROCESSENTRY32(ctypes.Structure):
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


def process_table():
    """pid -> (szulo pid, folyamatnev kisbetuvel). Ezredmasodperces muvelet."""
    TH32CS_SNAPPROCESS = 0x00000002
    invalid = ctypes.c_void_p(-1).value

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == invalid:
        return {}

    table = {}
    try:
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            table[int(entry.th32ProcessID)] = (
                int(entry.th32ParentProcessID),
                entry.szExeFile.decode("ascii", "ignore").lower(),
            )
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return table


_PS_DETAILS = r"""
Get-CimInstance Win32_Process -Filter "Name='claude.exe'" | ForEach-Object {
    [pscustomobject]@{
        pid      = [int]$_.ProcessId
        exe_path = $_.ExecutablePath
        cmdline  = $_.CommandLine
    }
} | ConvertTo-Json -AsArray -Compress
"""


def _load_details(powershell="pwsh"):
    """Eleresi ut es parancssor minden claude.exe-re. Draga: csak uj pid-re hivjuk."""
    # CREATE_NO_WINDOW: enelkul minden hivasnal felvillan egy konzolablak. Elesben
    # ez zavaro volt - a felhasznalo "villogo pwsh ablakokat" latott, mert egy
    # gyorsitotar-hezag miatt ez masodpercenkent lefutott.
    creationflags = 0x08000000 if os.name == "nt" else 0

    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", _PS_DETAILS],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    if result.returncode != 0 or not result.stdout.strip():
        return {}

    try:
        rows = json.loads(result.stdout)
    except ValueError:
        return {}

    if isinstance(rows, dict):
        rows = [rows]

    details = {}
    for row in rows:
        pid = row.get("pid")
        if pid is None:
            continue
        details[int(pid)] = {
            "exe_path": row.get("exe_path") or "",
            "name": parse_name(row.get("cmdline")),
        }
    return details


def list_claude_processes(powershell="pwsh"):
    """Minden futo claude.exe, a `snapshot.build_snapshot` altal vart alakban.

    A `cwd` mezot a Win32 NEM adja meg egy masik folyamatra, ezert mindig None -
    a session munkakonyvtarat es a pid-jet az allapotfajlbol tudjuk meg, amit a
    hook ir (spec 4.2). A pid-alapu parositas eppen ezert kellett.
    """
    table = process_table()
    pids = [pid for pid, (_parent, name) in table.items() if name == TARGET_EXE]

    # A korabban FELADOTT pid-eket egy ido utan ujra megprobaljuk. Enelkul egy
    # par masodperces CIM-kiesés VEGLEGESEN megmergezi az osszes epp futo
    # sessiont: a lekerdezes egyszerre hozza mindegyiket, tehat harom hibas kor
    # utan mind ures bejegyzest kap, es a gyuru orokre ures marad.
    #
    # Elesben merve 2026-09-10: az ugynok 15 percen at NULLA sessiont latott,
    # majd tetlenseg miatt kilepett - kozben nyolc session futott. Ujrainditas
    # utan azonnal mind a nyolcat latta.
    now = time.time()
    for pid in list(_detail_cache):
        failed_at = _detail_cache[pid].get("failed_at")
        if failed_at is not None and now - failed_at > DETAIL_RETRY_S:
            del _detail_cache[pid]
            _attempts.pop(pid, None)

    # Csak akkor kerdezzuk meg a dragabb reszleteket, ha van ismeretlen pid.
    unknown = [pid for pid in pids if pid not in _detail_cache]
    if unknown and any(_attempts.get(pid, 0) < MAX_DETAIL_ATTEMPTS for pid in unknown):
        for pid in unknown:
            _attempts[pid] = _attempts.get(pid, 0) + 1
        _detail_cache.update(_load_details(powershell))
        # Ha a CIM valamelyik pid-et tobbszor sem hozta vissza, feladjuk es
        # ures bejegyzest teszunk be. Enelkul az a pid orokre ismeretlen marad,
        # es a dragа lekerdezes MINDEN korben ujrafut - elesben ettol villogott
        # masodpercenkent egy pwsh ablak a felhasznalo kepernyojen.
        for pid in unknown:
            if pid not in _detail_cache and _attempts[pid] >= MAX_DETAIL_ATTEMPTS:
                # `failed_at`: ez feladas, nem tudas. `DETAIL_RETRY_S` mulva
                # ujraprobaljuk (lasd fent).
                _detail_cache[pid] = {
                    "exe_path": "", "name": None, "failed_at": now
                }

    # A halott pid-ek takaritasa, hogy a gyorsitotar ne nojon korlatlanul.
    for pid in list(_detail_cache):
        if pid not in table:
            del _detail_cache[pid]
    for pid in list(_attempts):
        if pid not in table:
            del _attempts[pid]

    processes = []
    for pid in pids:
        parent_pid, _name = table[pid]
        parent_name = table.get(parent_pid, (0, ""))[1]
        detail = _detail_cache.get(pid) or {"exe_path": "", "name": None}
        processes.append(
            {
                "pid": pid,
                "exe_path": detail["exe_path"],
                "parent_name": parent_name,
                "name": detail["name"],
                "cwd": None,
            }
        )
    return processes
