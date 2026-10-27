# SPDX-License-Identifier: MIT
"""A Dial `focus` keresenek PC-oldali vegrehajtasa: hozd elo a Warp tabot.

Ez a modul CSAK a gepen fut (Windows), a Dialra sosem kerul fel.

## Miert ilyen bonyolult

A terv 4.4 `{"t":"focus"}` uzenete eredetileg no-op maradt azzal az
indoklassal, hogy "minden claude.exe MainWindowHandle-je 0". Az indoklas
felig igaz: a *claude.exe*-nek tenyleg nincs ablaka, de a Warp ablakanak van.
A 2026-09-10-i meres a teljes kepet mutatta:

    WARP  PID=25588 HWND=198346 TITLE="✳ ShopKit"
    pwsh  PID=27152 HWND=131806 cls=PseudoConsoleWindow rect=0,0,0,0 root=onmaga

Vagyis: minden Warp-panelnek van egy `pwsh.exe`-je sajat ablak-handle-lel, de
az egy 0x0 meretu `PseudoConsoleWindow`, ami NEM gyereke a Warp ablakanak -
ConPTY-belsoseg, a Warp nem is tud rola. Rea adott `SetForegroundWindow` nem
valt tabot.

## A helyes ut: WARP_FOCUS_URL

A warpdotdev/warp#8611-et a **merge-elt PR #11130 lezarta (2026-05-22)**: azota
minden Warp-panel kornyezeteben ott van

    WARP_TERMINAL_SESSION_UUID  f96028319afc4f178bebc90a25841f1b
    WARP_FOCUS_URL              warp://session/f96028319afc4f178bebc90a25841f1b

Ezt a gepen igazoltuk (Warp v0.2026.09.02.08.27.stable_01). A hook - amely a
claude.exe gyereke, az meg a panel shellje - orokli, es beleirja az
allapotfajlba; az ugynok pedig egyszeruen megnyitja az URL-t. Se billentyu, se
ablak-handle. Ez a `focus_session` elso utja.

## A tartalek: cimfigyeleses tabkereses

Ha egy sessionnek nincs fokusz-URL-je (regebbi Warp, vagy nem Warpban indult),
marad az, amit a rokon warpdotdev/warp#8929 ("Deeplink to focus/switch to an
existing tab", meg mindig nyitva) bejelentoje is hasznal: **billentyu-szimulacio,
cimfigyeleses visszacsatolassal**. A meres adta hozza a hianyzo darabot: a
Warp `MainWindowTitle`-je koveti az AKTIV tabot (a meres kozben valtozott
"✳ ShopKit"-rol "? auth-gateway"-re). Tehat kuldunk egy Ctrl+PageDown-t,
elolvassuk a cimet, es tudjuk, hova jutottunk.

## Amit a biztonsagert teszunk

- A `Ctrl+PageDown` csak tabot valt - nem gepel szoveget egy elo sessionbe.
- Minden billentyukuldes elott ellenorizzuk, hogy tenyleg a Warp van elotérben;
  ha nem, azonnal megallunk (kulonben idegen ablakba mennenek a billentyuk).
- Ha egy teljes kor utan nincs talalat, a keresés a kiindulasi tabnal all meg,
  mert korbeert - nem hagyjuk a felhasznalot egy idegen tabon.

## Ismert korlatok

- Ket azonos cimu tab eseten a "korbeertunk" felismeres korabban megallhat.
- 16-nal tobb tab eseten (`MAX_TAB_STEPS`) feladjuk, es akkor nem biztos, hogy
  a kiindulasi tabon allunk meg.
- Ha a felhasznalo kozben maga is gepel/kattint, a verseny elronthatja a kort.
  Ezert a `focus` szandekosan a legritkabb gesztus (dupla kattintas).
"""

import os
import sys
import time

# Ennyi tabvaltast probalunk meg legfeljebb. A gyakorlatban a "korbeertunk"
# felismeres all meg elobb; ez csak a vegtelen ciklus elleni also korlat.
MAX_TAB_STEPS = 16

# A billentyu es a cim beolvasasa kozott a Warp-nak kell egy pillanat, hogy
# atrajzolja a fejlecet. Merve nem lett; ovatos, de meg gyors ertek.
SETTLE_S = 0.08

_ALLOWED_LEADING = "._-/\\~"

# A Warp terminal folyamatnevei. Szandekosan felsorolas es nem "warp*" minta:
# a Cloudflare VPN-kliense `warp-svc.exe` neven fut ugyanezen a gepen, es annak
# semmi koze a terminalhoz.
WARP_EXE_NAMES = ("warp.exe", "warpstable.exe", "warppreview.exe")

# A billentyus tartalek ag kapcsoloja. Alapbol kikapcsolva - lasd
# `fallback_enabled`.
FALLBACK_ENV = "M5DIAL_FOCUS_FALLBACK"


def warp_pids(table):
    """A Warp terminal folyamatai a `procs.process_table()` kimenetebol.

    `table`: pid -> (szulo pid, folyamatnev kisbetuvel).
    """
    pids = []
    for pid in table:
        name = table[pid][1]
        if name in WARP_EXE_NAMES:
            pids.append(pid)
    return pids


def normalize_title(title):
    """A Warp ablakcimebol a tab neve.

    A cim elejen egy allapotjelzo glifa all (pl. "✳", vagy ha a fontbol
    hianyzik, "?"), utana szokoz. Ezt vagjuk le, hogy a tab neve maradjon.
    """
    text = (title or "").strip()
    while text and not (text[0].isalnum() or text[0] in _ALLOWED_LEADING):
        text = text[1:].lstrip()
    return text


def title_matches(title, name):
    """Egyezik-e az ablakcim a keresett session nevevel.

    Szandekosan TELJES egyezes: reszlet-egyezessel egy "gateway" nevu session
    az "auth-gateway" tabra vinne.
    """
    if not name:
        return False
    return normalize_title(title) == normalize_title(name)


def active_session_id(fg_title, fg_is_warp, sessions):
    """Melyik session Warp-tabja van epp elol - a Dial kivalasztasa ezt koveti.

    `fg_title`: az elotérben levo ablak cime; `fg_is_warp`: Warp-folyamate-e.
    A Warp ablakcime elo, az aktiv tab nevet mutatja (elotte allapotjelzo
    glifaval); merve 2026-09-17-en. A `warp.sqlite` `active_tab_index`-e
    perceket kesik, a UI Automation semmit nem ad - ezert a cim a forras.

    Visszaad: a session azonositoja, ha PONTOSAN EGY session neve egyezik;
    kulonben None. Ket azonos nevu tabnal a cimbol nem derul ki, melyik az -
    ilyenkor inkabb semmi, mint egy rossz ugras a Dialon.
    """
    if not fg_is_warp or not sessions:
        return None
    if not normalize_title(fg_title):
        return None
    found = None
    for session in sessions:
        if title_matches(fg_title, session.get("n")):
            if found is not None:
                return None
            found = session.get("id")
    return found


def focus_tab(target, read_title, press_next, max_steps=MAX_TAB_STEPS):
    """Lepked a tabok kozott, amig a cim a `target`-et nem mutatja.

    A ket muveletet kivulrol kapja (`read_title`, `press_next`), hogy a teljes
    dontesi logika Warp es Windows nelkul is tesztelheto legyen.

    Visszaad: (eredmeny, lepesek) ahol az eredmeny
        "already"   - mar a keresett tabon alltunk, nem nyultunk semmihez
        "found"     - megtalaltuk, `lepesek` tabvaltas utan
        "not_found" - korbeertunk (vagy elfogyott a keret), nincs ilyen tab
        "error"     - a cimolvasas vagy a billentyukuldes elbukott
    """
    if not target:
        return ("not_found", 0)

    try:
        start = read_title()
    except Exception:
        return ("error", 0)

    if title_matches(start, target):
        return ("already", 0)

    start_key = normalize_title(start)

    for step in range(1, max_steps + 1):
        try:
            press_next()
            title = read_title()
        except Exception:
            return ("error", step - 1)

        if title_matches(title, target):
            return ("found", step)

        if normalize_title(title) == start_key:
            # Korbeertunk: minden tabot lattunk, es ismet a kiindulasin allunk.
            return ("not_found", step)

    return ("not_found", max_steps)


# --- Windows-specifikus reteg --------------------------------------------------
#
# Innentol minden mellekhatas. Ez a resz nem unit-tesztelheto (elo Warp-ablak
# kell hozza); a felette levo logika viszont teljesen az.


def _win32():
    """A szukseges user32/kernel32 fuggvenyek, vagy None nem-Windowson."""
    if not sys.platform.startswith("win"):
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.AttachThreadInput.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.BOOL,
    ]
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    return ctypes, wintypes, user32, kernel32


def pick_window_for(name, titled_windows):
    """Melyik Warp-ablakot hozzuk elore a fokusz-URL utan.

    `titled_windows`: [(hwnd, cim)] parok. Az URL atvaltotta a tabot abban az
    ablakban, amelyik a panelt tartalmazza - onnantol annak a cime EPPEN a cel
    session neve. Ez a jel mondja meg, melyik ablakot kell elorehozni.

    Ha nincs egyezes, de csak egyetlen ablak van, azt valasztjuk. Tobb ablaknal
    egyezes nelkul inkabb semmit: nem hozunk elore talalomra egy ablakot.
    """
    windows = [w for w in (titled_windows or []) if w and w[0]]
    if not windows:
        return None
    if name:
        for hwnd, title in windows:
            if title_matches(title, name):
                return hwnd
    if len(windows) == 1:
        return windows[0][0]
    return None


def find_warp_windows(pids):
    """A Warp osszes lathato, cimmel biro ablaka: [(hwnd, cim)]."""
    hwnds = _enum_warp_hwnds(pids)
    return [(hwnd, window_title(hwnd)) for hwnd in hwnds]


def find_warp_window(pids):
    """A Warp fo GUI-ablaka a megadott PID-ek kozul, vagy None.

    `pids`: a warp.exe folyamatok azonositoi. Tobb ablak eseten az elsot adja -
    aki valasztani akar, hasznalja a `find_warp_windows`-t.
    """
    hwnds = _enum_warp_hwnds(pids)
    return hwnds[0] if hwnds else None


def _enum_warp_hwnds(pids):
    """A Warp folyamatok lathato, cimmel biro ablakainak handle-jei."""
    win = _win32()
    if win is None or not pids:
        return []
    ctypes, wintypes, user32, _kernel32 = win

    wanted = set(int(p) for p in pids)
    found = []

    CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _visit(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in wanted and user32.IsWindowVisible(hwnd):
            if user32.GetWindowTextLengthW(hwnd) > 0:
                found.append(hwnd)
        return True

    user32.EnumWindows(CALLBACK(_visit), 0)
    return found


def window_title(hwnd):
    """Egy ablak cime, vagy "" ha nem olvashato."""
    win = _win32()
    if win is None or not hwnd:
        return ""
    ctypes, _wintypes, user32, _kernel32 = win
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def foreground_window():
    """Az elotérben levo ablak: (cim, Warp-folyamate-e). Csak olvas.

    Nem-Windowson vagy ablak nelkul ("", False). A hivo (az ugynok kore) a
    kiveteleket is elnyeli - egy elbukott olvasas nem allithatja meg a kort.
    """
    win = _win32()
    if win is None:
        return ("", False)
    ctypes, wintypes, user32, _kernel32 = win
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ("", False)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    from .procs import process_table

    entry = process_table().get(int(pid.value))
    is_warp = bool(entry) and entry[1] in WARP_EXE_NAMES
    return (window_title(hwnd), is_warp)


def bring_to_front(hwnd):
    """Elotérbe hozza az ablakot. Igaz, ha sikerult.

    A `SetForegroundWindow` onmagaban gyakran csendben elbukik, ha a hivo nem
    az aktiv folyamat (Windows fokusz-lopas elleni vedelme). A bevett megoldas:
    az input-sorunkat ideiglenesen hozzacsatoljuk az epp aktiv ablak szalahoz.
    """
    win = _win32()
    if win is None or not hwnd:
        return False
    ctypes, wintypes, user32, kernel32 = win

    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return True

    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    own_thread = kernel32.GetCurrentThreadId()

    attached = []
    for other in (fg_thread, target_thread):
        if other and other != own_thread:
            if user32.AttachThreadInput(own_thread, other, True):
                attached.append(other)
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        for other in attached:
            user32.AttachThreadInput(own_thread, other, False)

    time.sleep(SETTLE_S)
    return user32.GetForegroundWindow() == hwnd


def send_next_tab(hwnd):
    """Ctrl+PageDown a mar elotérben levo ablaknak.

    Ha nem a vart ablak van elotérben, NEM kuld semmit: a billentyuk kulonben
    egy idegen ablakba mennenek. Ez a vedelem a legfontosabb resz itt.
    """
    win = _win32()
    if win is None or not hwnd:
        return False
    _ctypes, _wintypes, user32, _kernel32 = win

    if user32.GetForegroundWindow() != hwnd:
        return False

    VK_CONTROL = 0x11
    VK_NEXT = 0x22  # PageDown
    KEYEVENTF_KEYUP = 0x0002

    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_NEXT, 0, 0, 0)
    user32.keybd_event(VK_NEXT, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(SETTLE_S)
    return True


def pid_from_session_id(session_id):
    """A `pid<szam>` alaku session-azonositobol a folyamat pid-je, vagy None.

    A `snapshot.build_snapshot` ezt az alakot adja annak az elo folyamatnak,
    amelyhez nem talalt allapotfajlt (`{"id": "pid%d"}`). Eppen ezek azok a
    sessionok, amelyeknek a hook-uton sosem lesz fokusz-URL-jük.
    """
    if not session_id or not isinstance(session_id, str):
        return None
    if not session_id.startswith("pid"):
        return None
    rest = session_id[3:]
    if not rest.isdigit():
        return None
    return int(rest)


def focus_url_for_pid(pid, parent_of=None, read_env=None, max_depth=4):
    """A folyamat (vagy egy ose) kornyezetebol a Warp fokusz-URL.

    Miert kell ez az allapotfajl melle: az allapotfajl arvakent 15 perc utan
    lejar es torlodik, egy uj session pedig az elso hook-esemenyig meg sem
    kap ilyet. Eppen a legvalószinubb celpont - egy regota pihenő session -
    maradt igy URL nelkul. A folyamat kornyezete viszont a folyamat teljes
    eleteben ott van.

    `parent_of` es `read_env` kivulrol johet, hogy a bejaras tesztelheto legyen.
    """
    if pid is None:
        return None
    if read_env is None:
        read_env = read_process_env
    if parent_of is None:
        parent_of = _parent_pid

    seen = set()
    current = pid
    for _ in range(max_depth):
        if current is None or current in seen:
            return None
        seen.add(current)
        env = read_env(current)
        if env:
            url = env.get(hookstate_focus_env())
            if url and url.strip().startswith("warp://"):
                return url.strip()
        current = parent_of(current)
    return None


def hookstate_focus_env():
    """A kornyezeti valtozo neve. Kulon fuggveny, hogy egy helyen legyen."""
    return "WARP_FOCUS_URL"


def _parent_pid(pid):
    from .procs import process_table

    entry = process_table().get(pid)
    return entry[0] if entry else None


def read_process_env(pid):
    """Egy MASIK folyamat kornyezeti valtozoi, vagy None.

    Csak olvas: `OpenProcess(QUERY_INFORMATION|VM_READ)`, majd a PEB-en at a
    `RTL_USER_PROCESS_PARAMETERS.Environment` blokk. Sajat felhasznaloju,
    64 bites folyamatra mukodik; barmi mas eseten csendben None.

    Nem modositunk semmit - ez a Windows szabvanyos, olvaso utja ahhoz, hogy
    megtudjuk, egy folyamat milyen kornyezetet orokolt.
    """
    if not sys.platform.startswith("win") or not pid:
        return None
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(pid)
    )
    if not handle:
        return None

    try:
        class _PBI(ctypes.Structure):
            _fields_ = [
                ("Reserved1", ctypes.c_void_p),
                ("PebBaseAddress", ctypes.c_void_p),
                ("Reserved2", ctypes.c_void_p * 2),
                ("UniqueProcessId", ctypes.c_void_p),
                ("Reserved3", ctypes.c_void_p),
            ]

        pbi = _PBI()
        length = wintypes.ULONG()
        status = ntdll.NtQueryInformationProcess(
            handle, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(length)
        )
        if status != 0 or not pbi.PebBaseAddress:
            return None

        def read(address, size):
            buf = ctypes.create_string_buffer(size)
            got = ctypes.c_size_t(0)
            ok = kernel32.ReadProcessMemory(
                handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)
            )
            if not ok or got.value != size:
                return None
            return buf.raw

        # x64 eltolasok: PEB.ProcessParameters, majd azon belul az Environment
        # mutato es a merete.
        raw = read(pbi.PebBaseAddress + 0x20, 8)
        if raw is None:
            return None
        params = int.from_bytes(raw, "little")
        if not params:
            return None

        raw = read(params + 0x80, 8)
        if raw is None:
            return None
        env_addr = int.from_bytes(raw, "little")

        raw = read(params + 0x3F0, 8)
        if raw is None:
            return None
        env_size = int.from_bytes(raw, "little")
        if not env_addr or not env_size or env_size > 1 << 20:
            return None

        block = read(env_addr, env_size)
        if block is None:
            return None
    finally:
        kernel32.CloseHandle(handle)

    return parse_env_block(block)


def parse_env_block(block):
    """A nyers, UTF-16LE kornyezeti blokk -> szotar. Sose dob kivetelt."""
    if not block:
        return {}
    try:
        text = block.decode("utf-16-le", "ignore")
    except Exception:
        return {}
    result = {}
    for item in text.split("\x00"):
        if not item or "=" not in item:
            continue
        key, _, value = item.partition("=")
        if key:
            result[key] = value
    return result


def fallback_enabled(environ):
    """Szabad-e a billentyus tartalek agat hasznalni. ALAPBOL NEM.

    Tobb Warp-ablak eseten a tartalek talalomra valasztott ablakban setal vegig
    a tabokon - ezt elesben lattuk, es rosszabb a semmittevesnel. A kod es a
    tesztjei megmaradnak, de csak kifejezett kerésre fut.
    """
    if not environ:
        return False
    value = environ.get(FALLBACK_ENV)
    if not value:
        return False
    return str(value).strip().lower() in ("1", "true", "igen", "yes")


def is_focus_url(url):
    """Elfogadhato-e ez az ertek a rendszer URL-kezelojenek.

    Az ertek egy allapotfajlbol jon, tehat ADAT - nem adhatjuk at vakon a
    ShellExecute-nak. Csak a `warp://session/<hex>` alak mehet at.
    """
    if not url or not isinstance(url, str):
        return False
    prefix = "warp://session/"
    if not url.startswith(prefix):
        return False
    ident = url[len(prefix):]
    if not ident or len(ident) > 64:
        return False
    for ch in ident:
        if ch not in "0123456789abcdefABCDEF-":
            return False
    return True


def open_focus_url(url):
    """A Warp fokusz-URL megnyitasa. Igaz, ha atadtuk a rendszernek.

    A Warp sajat URI-kezeloje veszi at (`WarpStable_URI_CHANNEL` named pipe),
    es o valt at a tabra - ehhez sem billentyu, sem ablak-handle nem kell.
    """
    if not is_focus_url(url) or not sys.platform.startswith("win"):
        return False
    try:
        os.startfile(url)  # noqa: S606 - a semat fent ellenoriztuk
    except Exception:
        return False
    return True


def focus_session(name, warp_pids, log=print, focus_url=None):
    """A teljes muvelet: hozd elore a session Warp-tabjat.

    Ket ut, ebben a sorrendben:

    1. **`focus_url`** - a session sajat `WARP_FOCUS_URL`-je, amit a hook irt az
       allapotfajlba. Ez a helyes ut: a Warp maga valt tabot.
    2. **cimfigyeleses kereses** - tartalek arra az esetre, ha a sessionnek
       nincs fokusz-URL-je (regi Warp, vagy a session nem Warpban indult).
       Billentyut szimulal, ezert csak masodik.

    Visszaad: "url" | "already" | "found" | "not_found" | "error" | "no_window".
    """
    if focus_url:
        if open_focus_url(focus_url):
            # Az URL atvaltja a tabot, de NEM hozza elore az ablakot: egy
            # hatterfolyamatbol inditott ShellExecute nem lophat fokuszt
            # (Windows elozar). Elesben pontosan igy latszott: mukodik, ha a
            # Warp mar elotérben van, kulonben "nem tortenik semmi".
            #
            # A valtas utan a cel PANELT tartalmazo ablak cime eppen a session
            # neve - ez mondja meg, melyik ablakot kell elorehozni.
            time.sleep(SETTLE_S)
            hwnd = pick_window_for(name, find_warp_windows(warp_pids))
            raised = bring_to_front(hwnd) if hwnd else False
            log("focus: {} -> a Warp fokusz-URL-jevel (ablak elore: {})".format(
                name, "igen" if raised else "nem"))
            return "url"
        log("focus: a fokusz-URL nem hasznalhato ({!r})".format(focus_url))

    if not fallback_enabled(os.environ):
        # ALAPERTELMEZES. Elesben megharapott: egy fokusz-URL nelkuli sessionre
        # a tartalek vegigsetalt egy TALALOMRA valasztott Warp ablak tabjain -
        # rosszabb, mint nem csinalni semmit.
        #
        # Fokusz-URL hianya ma mar nem azt jelenti, hogy regi a Warp (a
        # PR #11130 ota minden panel kap egyet), hanem hogy abban a sessionben
        # meg nem futott hook-esemeny a valtozas ota. Az elso esemeny orvosolja.
        log("focus: nincs hasznalhato fokusz-URL ({}) - nem tapogatozom".format(
            name))
        return "no_url"

    hwnd = find_warp_window(warp_pids)
    if not hwnd:
        log("focus: nincs Warp-ablak - nem csinalok semmit")
        return "no_window"

    if not bring_to_front(hwnd):
        log("focus: a Warp-ot nem sikerult elotérbe hozni")
        return "error"

    if not name:
        # Az ablak igy is elotérben van - ez a garantalt resz.
        log("focus: nincs sessionnev, csak az ablakot hoztam elore")
        return "not_found"

    def _read():
        return window_title(hwnd)

    def _press():
        if not send_next_tab(hwnd):
            raise OSError("a Warp nincs elotérben - megallok")

    result, steps = focus_tab(name, _read, _press)
    log("focus: {} -> {} ({} tabvaltas)".format(name, result, steps))
    return result
