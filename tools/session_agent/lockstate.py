# SPDX-License-Identifier: MIT
"""Zarolt-e a gep: tiszta dontes + vekony Win32-probak.

Ez a modul CSAK a PC-n fut (nem kerul at a Dialra), tehat nyugodtan hasznal
f-string nelkuli, de CPython-specifikus dolgokat is - a `ctypes`-t.

A ketteosztas ugyanaz, mint a tobbi modulban: a `lock_reason` tiszta fuggveny,
minden bemenete parameter, es teljesen tesztelt; a `probe_*` fuggvenyek egy
vekony, tesztelhetetlen reteg a Win32 fole, amelyek hiba eseten `None`-t adnak.

Melyik jelet mibol olvassuk:

- **Win+L / felhasznalovaltas / RDP-lecsatlakozas**: a sajat session WTS-flagje,
  `WTSQuerySessionInformationW(WTSSessionInfoEx)` ->
  `WTSINFOEX_LEVEL1.SessionFlags`. `WTS_SESSIONSTATE_LOCK` = 0,
  `WTS_SESSIONSTATE_UNLOCK` = 1.
- **Kepernyovedo**: `SystemParametersInfo(SPI_GETSCREENSAVERRUNNING)`.
- **Monitor kikapcsolva / alvas**: erre valodi esemeny csak ablakos
  energia-ertesitessel (`RegisterPowerSettingNotification` +
  `GUID_CONSOLE_DISPLAY_STATE`) jonne, az ugynoknek viszont nincs
  uzenethurka. Ezert KOZELITES: `GetLastInputInfo` szerinti tetlenseg egy
  kuszob felett. Nem pontos - ha a kepernyo-idokorlat mas, allitsd a
  `M5DIAL_LOCK_IDLE_S` kornyezeti valtozoval.

**NEM az `OpenInputDesktop`-ot hasznaljuk, es ez meres eredmenye.** Az elso
valtozat azzal dolgozott (zarolt allomason a hivas `ERROR_ACCESS_DENIED`-del
bukik), es elesben a Dial fel masodpercre valtott zarolt nezetre, majd meg
zarolt gep mellett visszaallt. A 2026-09-11-i meres (Windows 11 Pro 26200,
Win+L -> ujjlenyomatos feloldas) megmutatta, miert:

    10:15:14  desktop_open=False  desktop=err5     flags=0  LogonUI=1
    10:15:15  desktop_open=True   desktop=Default  flags=0  LogonUI=1   <-- itt bukik
    10:15:19  desktop_open=False  desktop=err5     flags=0  LogonUI=1
    10:15:21  desktop_open=True   desktop=Default  flags=1  LogonUI=0   <-- feloldas

Az `OpenInputDesktop` **pattog**: a Win10/11 zarkepernyot a `LockApp` a
**Default** asztalon rajzolja, a Winlogon biztonsagos asztal csak a valtas
pillanataban (es jelszo-beirasnal) van elol - utana a hivas ujra sikerul. A
`SessionFlags` ugyanebben a korben vegig 0 volt, pattogas nelkul.
"""

import ctypes
import ctypes.wintypes
import os

#: Ennyi masodperc tetlenseg utan tekintjuk ugy, hogy a kepernyo elaludt.
#: A Windows alapertelmezett kepernyo-idokorlatja halozati aramon 10 perc.
DEFAULT_IDLE_THRESHOLD_S = 600

#: A `lock_reason` lehetseges valaszai a `None` mellett. A Dial mindharmat
#: ugyanugy kezeli; a megkulonboztetes a naplonak es a hibakeresesnek szol.
LOCK_REASONS = ("lock", "saver", "idle")

IDLE_THRESHOLD_ENV = "M5DIAL_LOCK_IDLE_S"

#: A WTS session-flagek. A `WTS_SESSIONSTATE_UNKNOWN` akkor jon, ha a rendszer
#: nem tudja megmondani - azt nem ertelmezzuk zarnak.
WTS_SESSIONSTATE_LOCK = 0
WTS_SESSIONSTATE_UNLOCK = 1
WTS_SESSIONSTATE_UNKNOWN = 0xFFFFFFFF


def idle_threshold_from_env(environ=None, default=DEFAULT_IDLE_THRESHOLD_S):
    """A tetlensegi kuszob a kornyezetbol. Ertelmetlen ertekre az alapertek.

    `0` szandekosan ervenyes: azzal a tetlenseg-figyeles kikapcsolhato, ugy
    csak a valodi zar es a kepernyovedo szamit.
    """
    env = os.environ if environ is None else environ
    raw = env.get(IDLE_THRESHOLD_ENV)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def session_locked_from_flags(flags):
    """A nyers WTS `SessionFlags` -> True (zarolt) / False / None (ismeretlen).

    Kulon fuggveny, mert ez az EGYETLEN hely, ahol a Win32-konstansokat
    ertelmezzuk - es igy tesztelheto a ctypes-rétegtől függetlenul.
    """
    if flags is None:
        return None
    try:
        value = int(flags) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None
    if value == WTS_SESSIONSTATE_LOCK:
        return True
    if value == WTS_SESSIONSTATE_UNLOCK:
        return False
    return None


def lock_reason(
    session_locked, screensaver_running, idle_s, idle_threshold_s=DEFAULT_IDLE_THRESHOLD_S
):
    """Miert tekintjuk zartnak a gepet - vagy `None`, ha nem az.

    session_locked: zarolt-e a sajat Windows-sessionunk. `True` = zarolva.
        `None` = a proba elbukott vagy ismeretlen allapotot adott; ilyenkor NEM
        zarunk. Egy nema, orokre zarolt Dial rosszabb es nehezebben
        diagnosztizalhato, mint egy elmarado zar - a tobbi jel meg ilyenkor is
        szamit.
    screensaver_running: fut-e a kepernyovedo.
    idle_s: hany masodperce nem nyult a felhasznalo a gephez.
    idle_threshold_s: ennyi felett tekintjuk alvonak a kepernyot.
        `0` vagy `None` kikapcsolja ezt a jelet.
    """
    if session_locked is True:
        return "lock"
    if screensaver_running:
        return "saver"
    if not idle_threshold_s:
        return None
    try:
        if float(idle_s) >= float(idle_threshold_s):
            return "idle"
    except (TypeError, ValueError):
        return None
    return None


# --- Win32-probak: innentol nincs teszt, csak vedett hivasok -------------------

_SPI_GETSCREENSAVERRUNNING = 0x0072
_WTS_CURRENT_SERVER_HANDLE = 0
_WTS_CURRENT_SESSION = 0xFFFFFFFF
_WTS_SESSION_INFO_EX = 25


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class _WtsInfoExHead(ctypes.Structure):
    """A `WTSINFOEXW` eleje - csak ameddig a `SessionFlags` tart.

    A teljes szerkezet ~232 bajt, de a vege (nevek, `LARGE_INTEGER` idobelyegek)
    nem kell. A `Level` utan 4 bajt toltelek van: a rakovetkezo union 8 bajtra
    igazodik a `LARGE_INTEGER` mezoi miatt.
    """

    _fields_ = [
        ("Level", ctypes.c_ulong),
        ("_pad", ctypes.c_ulong),
        ("SessionId", ctypes.c_ulong),
        ("SessionState", ctypes.c_int),
        ("SessionFlags", ctypes.c_long),
    ]


def probe_session_locked():
    """Zarolt-e a sajat Windows-sessionunk. True/False, hiba eseten None."""
    try:
        wts = ctypes.windll.wtsapi32  # type: ignore[attr-defined]
    except AttributeError:
        return None
    buffer = ctypes.c_void_p()
    size = ctypes.wintypes.DWORD()
    try:
        ok = wts.WTSQuerySessionInformationW(
            _WTS_CURRENT_SERVER_HANDLE,
            _WTS_CURRENT_SESSION,
            _WTS_SESSION_INFO_EX,
            ctypes.byref(buffer),
            ctypes.byref(size),
        )
    except OSError:
        return None
    if not ok or not buffer:
        return None
    try:
        head = ctypes.cast(buffer, ctypes.POINTER(_WtsInfoExHead)).contents
        if head.Level != 1:
            return None
        return session_locked_from_flags(head.SessionFlags)
    except (ValueError, OSError):
        return None
    finally:
        try:
            wts.WTSFreeMemory(buffer)
        except OSError:
            pass


def probe_screensaver_running():
    """Fut-e a kepernyovedo. Hiba eseten False (nem tudunk rola)."""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        running = ctypes.c_int(0)
        ok = user32.SystemParametersInfoW(
            _SPI_GETSCREENSAVERRUNNING, 0, ctypes.byref(running), 0
        )
    except (AttributeError, OSError):
        return False
    return bool(ok) and bool(running.value)


def probe_idle_s():
    """Hany masodperce tetlen a felhasznalo. Hiba eseten None.

    A `dwTime` es a `GetTickCount` egyarant 32 bites, es ~49,7 naponta korbefordul;
    a kulonbseget ezert 32 biten szamoljuk, kulonben egy fordulas utan negativ
    (majd abszurd) tetlenseget latnank.
    """
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(_LastInputInfo)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        now = kernel32.GetTickCount() & 0xFFFFFFFF
    except (AttributeError, OSError):
        return None
    return ((now - (info.dwTime & 0xFFFFFFFF)) & 0xFFFFFFFF) / 1000.0


def current_lock_reason(idle_threshold_s=None):
    """A harom proba + a tiszta dontes egyben. Elesben ezt hivja az ugynok."""
    if idle_threshold_s is None:
        idle_threshold_s = idle_threshold_from_env()
    return lock_reason(
        probe_session_locked(),
        probe_screensaver_running(),
        probe_idle_s(),
        idle_threshold_s=idle_threshold_s,
    )
