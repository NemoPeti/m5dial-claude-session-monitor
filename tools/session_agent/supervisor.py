# SPDX-License-Identifier: MIT
"""Az ugynok onfelugyelete (terv 3): egypeldanyos zar es tetlensegi kilepes.

Ket problemara valasz, amit az inditja fel, hogy az ugynokot mostantol egy
Claude Code `SessionStart` hook indithatja:

1. **Egyszerre inditott sessionok** - a felhasznalo tobb Claude sessiont indit
   masodperceken belul, mindegyik lefuttatja a hookot, tehat tobb ugynok
   probalna egyszerre fogni az egyetlen COM-portot. Az `acquire_lock` /
   `release_lock` / `read_lock` harmas biztositja, hogy csak egy peldany
   fusson: a zarfajl letrehozasa atomi (`os.O_CREAT | os.O_EXCL`), igy ket
   egyszerre inditott folyamat kozul csak az egyik nyerheti meg a versenyt.
   Egy korabbi, osszeomlott ugynok ott maradt zarfajlja nem ragaszthatja be
   a rendszert: ha a bejegyzett pid mar nem el, az uj peldany atveszi a
   zarat. Egy serult/olvashatatlan zarfajl ugyanigy atveheto - soha nem
   szabad emiatt elszallni.

2. **Semmi nem allitja le az ugynokot, amikor az utolso session is bezarul.**
   Egy `SessionEnd` hook bonyolult lenne (ki kellene zarnia a sajat, eppen
   kilepo folyamatat a szamlalasbol), ezert az ugynok inkabb magat figyeli:
   ha mar egy ideje (`IDLE_EXIT_S`) nincs egyetlen Claude session sem, kilep.
   Egy kesobbi session `SessionStart` hookja ujra elinditja.
"""

import os

IDLE_EXIT_S = 900  # 15 perc


def should_exit_idle(session_count, idle_since, now_ts, idle_exit_s=IDLE_EXIT_S):
    """Kell-e kilepni tetlenseg miatt. Visszaad (exit, idle_since) part.

    `session_count` None/hianyzo vagy <= 0 erteke tetlenkent szamit.
    `idle_since` ervenytelen (nem szam) erteke ugy kezelendo, mintha a
    tetlenseg most kezdodne - soha nem szabad emiatt elszallni.
    """
    active = isinstance(session_count, (int, float)) and session_count > 0

    if active:
        return False, None

    if not isinstance(idle_since, (int, float)):
        idle_since = now_ts

    if now_ts - idle_since >= idle_exit_s:
        return True, idle_since

    return False, idle_since


def read_lock(path):
    """A zarfajlban levo pid, vagy None (hianyzo, ures vagy serult fajl eseten)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except OSError:
        return None

    try:
        return int(raw)
    except ValueError:
        return None


def acquire_lock(path, pid, is_alive):
    """Igaz, ha mienk a zar. `is_alive(pid)` mondja meg, el-e egy folyamat.

    Uj zarfajlt atomian hoz letre (`O_CREAT | O_EXCL`), igy ket egyszerre
    versenyzo folyamat kozul csak az egyik nyerhet. Ha a fajl mar letezik,
    a bejegyzett tulajdonos elettartanak fuggvenyeben vagy visszalep, vagy
    atveszi (feluliraja) a zarat.
    """
    if _try_create(path, pid):
        return True

    owner_pid = read_lock(path)
    if owner_pid is not None and is_alive(owner_pid):
        return False

    # A tulajdonos holt (vagy a fajl serult/olvashatatlan) - atvesszuk.
    _write_pid(path, pid)
    return True


def release_lock(path, pid):
    """Csak akkor torli a zarfajlt, ha tenyleg a mienk."""
    if read_lock(path) != pid:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _try_create(path, pid):
    """Igaz, ha atomian sikerult letrehozni a zarfajlt a mi pidunkkel."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    try:
        os.write(fd, str(pid).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _write_pid(path, pid):
    """A zarfajl felulirasa a mi pidunkkel (mar letezo, atvett zar eseten)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(pid))
