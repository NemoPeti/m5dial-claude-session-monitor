# SPDX-License-Identifier: MIT
"""A PC-oldali ugynok: osszefesul, kuld a Dialnak, es fogadja a valaszait.

Ez a modul koti ossze a tobbit (terv 3):

    procs  ->  snapshot  ->  protocol  ->  soros port  ->  Dial
                              protocol  <-  soros port  <-  Dial  ->  config

Amit szandekosan NEM csinal:

- **nem dont hangrol** - az a Dialon dol el (terv 4.5), hogy az ugynok
  ujrainditasa ne jarjon hamis riasztassal;
- **nem blokkolja a sessionoket** - a hookok fajlt irnak, az ugynok pedig
  onnan olvas (terv 3.1).

A `.release` jelzofajl a `push.ps1` fejlesztoi korenek szol (terv 3.2): ha
megjelenik, az ugynok elengedi a COM-portot, es varja, hogy eltunjon. Ha
beragad, 60 masodperc utan magatol visszacsatlakozik - egy elfelejtett
jelzofajl nem hagyhatja nemán holtan a rendszert.
"""

import json
import os
import time

from . import lockstate, protocol, warpfocus
from .config import DEFAULT_CONFIG, load_config, save_config
from .procs import (
    CLI_PATH_DEFAULT,
    SHELL_NAMES,
    list_claude_processes,
    process_table,
)
from .supervisor import IDLE_EXIT_S, acquire_lock, release_lock, should_exit_idle
from .snapshot import build_snapshot, is_session_process
from .weather import DEFAULT_LAT, DEFAULT_LON, get_weather

STATUS_DIR = os.environ.get("CLAUDE_SESSION_STATUS_DIR") or os.path.join(
    os.path.expanduser("~"), ".claude", "session-status"
)
CONFIG_PATH = os.path.join(STATUS_DIR, "config.json")
RELEASE_FLAG = os.path.join(STATUS_DIR, ".release")
WEATHER_CACHE = os.path.join(STATUS_DIR, "weather.json")

# A sajat segedfajljaink ugyanabban a mappaban ulnek, mint az allapotfajlok.
NOT_STATUS_FILES = ("config.json", "weather.json", "agent.pid")

# Az egypeldany-zar helye. A felhasznalo 5-10 sessiont indit egyszerre, es
# mindegyik `SessionStart`-ja inditana egy ugynokot - egy foghatja a COM-portot.
LOCK_PATH = os.path.join(STATUS_DIR, "agent.pid")

TICK_S = 1.0
RELEASE_MAX_S = 60.0
BAUD = 115200

# Ennyi EGYMAS UTANI hibas kor utan adjuk fel. Egy-egy elszallt kor (serult fajl,
# pillanatnyi CIM-hiba, kirantott kabel) nem dontheti meg a szolgaltatast, de egy
# tartosan hibas allapotban sem pörgunk a vegtelensegig: a kovetkezo session
# `SessionStart`-ja ugyis ujrainditja az ugynokot.
MAX_CONSECUTIVE_ERRORS = 60


class _IdleExit(Exception):
    """Belso jelzes: tetlenseg miatt kilepunk. Nem hiba."""


def local_now():
    """Helyi ido masodpercben.

    A Dialon nincs idozona: amit kuldunk, azt `time.localtime()`-mal ertelmezi.
    Ezert nem a nyers UTC-t kuldjuk, hanem a helyi eltolassal noveljuk - kulonben
    az ora nyaron ket orat tevedne.
    """
    lt = time.localtime()
    offset = -(time.altzone if lt.tm_isdst else time.timezone)
    return int(time.time()) + offset


def read_status_files(status_dir):
    """Az allapotfajlok beolvasasa. Egy serult fajl nem allithatja meg a kort."""
    result = {}
    try:
        names = os.listdir(status_dir)
    except OSError:
        return result

    for name in names:
        if not name.endswith(".json") or name in NOT_STATUS_FILES:
            continue
        path = os.path.join(status_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        # Nem eleg a nevre szurni: az allapotmappaban a sajat segedfajljaink is
        # ott vannak, es elesben a weather.json allapotfajlkent ertelmezve
        # KeyErrorral megallitotta az egesz kort. Az ismertetojel az "state" mezo.
        if isinstance(data, dict) and isinstance(data.get("state"), str):
            result[name[:-5]] = data
    return result


def delete_stale(status_dir, stale_ids):
    for session_id in stale_ids:
        try:
            os.remove(os.path.join(status_dir, session_id + ".json"))
        except OSError:
            pass


def collect(status_dir, now_ts):
    """Egy kor: folyamatok + allapotfajlok -> pillanatkep, az elavultak torolve."""
    raw = list_claude_processes()
    procs = [p for p in raw if is_session_process(p, CLI_PATH_DEFAULT, SHELL_NAMES)]
    status_files = read_status_files(status_dir)
    sessions, stale_ids = build_snapshot(procs, status_files, now_ts)
    delete_stale(status_dir, stale_ids)
    return sessions


class Agent:
    """A fo ciklus. A soros portot lazan kezeli: ha nincs, ujraprobalja."""

    def __init__(self, port, status_dir=STATUS_DIR, log=print,
                 lat=DEFAULT_LAT, lon=DEFAULT_LON, tick_s=TICK_S,
                 lock_probe=lockstate.current_lock_reason,
                 foreground_probe=warpfocus.foreground_window):
        self.port = port
        self.status_dir = status_dir
        self.log = log
        # A koridot csak a tesztek allitjak at - elesben mindig TICK_S.
        self.tick_s = tick_s
        self.lat = lat
        self.lon = lon
        # Zarolt-e a gep. Parameter, hogy a probakban kicserelheto legyen;
        # elesben mindig a Win32-probak eredmenye.
        self.lock_probe = lock_probe
        # Az elotérben levo ablak (cim, Warp-e). Szinten a probak miatt parameter.
        self.foreground_probe = foreground_probe
        self._active_error = None
        self._lock = None
        self.serial = None
        self.idle_since = None
        self.reader = protocol.LineReader()
        self.seq = 0
        self.cfg = dict(DEFAULT_CONFIG)
        self._cfg_mtime = None
        self._released_at = None
        # Az utolso kikuldott pillanatkep: a Dial `focus` kerese
        # csak session-azonositot hoz, a Warp-tab nevehez viszont
        # a session `--name`-je kell.
        self.last_sessions = []

    # --- soros port ------------------------------------------------------------

    def _open(self):
        if self.serial is not None:
            return True
        try:
            import serial  # pyserial, csak itt kell
        except ImportError:
            self.log("hianyzik a pyserial - pip install pyserial")
            return False
        try:
            self.serial = serial.Serial(self.port, BAUD, timeout=0)
        except Exception as exc:  # a pyserial sajat hibaosztalyai
            self.log("nem nyilik a {}: {}".format(self.port, exc))
            self.serial = None
            return False
        self.log("csatlakozva: {}".format(self.port))
        return True

    def _close(self):
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception:
                pass
            self.serial = None

    # --- port-elengedes (terv 3.2) --------------------------------------------

    def _handle_release_flag(self):
        """Igaz, ha ebben a korben el kell engedni a portot."""
        flagged = os.path.exists(RELEASE_FLAG)
        if flagged:
            if self._released_at is None:
                self._released_at = time.time()
                self._close()
                self.log("port elengedve a push.ps1-nek")
            elif time.time() - self._released_at > RELEASE_MAX_S:
                # Beragadt jelzofajl: nem varunk tovabb.
                self.log("a .release {}s-ig bent maradt - visszacsatlakozom".format(
                    int(RELEASE_MAX_S)))
                self._released_at = None
                return False
            return True
        if self._released_at is not None:
            self._released_at = None
            self.log("a .release eltunt - visszacsatlakozom")
        return False

    # --- konfig ----------------------------------------------------------------

    def _reload_config_if_changed(self):
        """A gepről allitott nema/hangero atvetele (terv 4.6)."""
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            mtime = None
        if mtime != self._cfg_mtime:
            self._cfg_mtime = mtime
            self.cfg = load_config(CONFIG_PATH)

    def _log_device_text(self, raw):
        """Az eszkoz emberi kimenete (print, traceback) - nem a protokoll resze."""
        try:
            text = raw.decode("utf-8", "ignore")
        except AttributeError:
            text = str(raw)
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("{"):
                self.log("Dial: {}".format(line))

    def _apply_event(self, msg):
        kind = msg.get("t")
        if kind == "vol":
            volume = msg.get("v")
            if isinstance(volume, int) and 0 <= volume <= 3:
                self.cfg = dict(self.cfg)
                self.cfg["volume"] = volume
                # Hianyzo "m" = nem nemitott (visszafele kompatibilis).
                self.cfg["mute"] = bool(msg.get("m"))
                save_config(CONFIG_PATH, self.cfg)
                self._cfg_mtime = os.path.getmtime(CONFIG_PATH)
                self.log("hangero a Dialrol: {}".format(volume))
        elif kind == "ack":
            self.log("nyugtazva: {}".format(msg.get("id")))
        elif kind == "dbg":
            self.log(
                "a Dial jelenti: nezet={} sessionok={} ora={} idojaras={!r}".format(
                    msg.get("view"), msg.get("n"), msg.get("clk"), msg.get("wx")
                )
            )
        elif kind == "focus":
            self._focus_session(msg.get("id"))

    def _focus_session(self, session_id):
        """A Dial dupla kattintasa: hozd elore a session Warp-tabjat.

        A claude.exe-nek nincs ablaka (MainWindowHandle=0), es a Warp-nak nincs
        tab-celzo API-ja (warpdotdev/warp#8929 nyitva) - ezert a Warp ablakat
        hozzuk elore, majd a tab nevet olvasva lepkedunk oda. Reszletek:
        `warpfocus`. Ha barmi elbukik, csak naplozunk: a `focus` kenyelmi
        funkcio, nem allithatja meg az ugynokot.
        """
        name = None
        for session in self.last_sessions:
            if session.get("id") == session_id:
                name = session.get("n")
                break
        if name is None:
            self.log("focus: ismeretlen session ({})".format(session_id))

        # A fokusz-URL ket forrasbol johet, ebben a sorrendben:
        #
        # 1. **a folyamat sajat kornyezete** - ez a friss igazsag. Merve: egy
        #    ujranyitott session mar mas panelen ul, mint amit a regi
        #    allapotfajl mondana, es az allapotfajl arvakent 15 perc utan
        #    torlodik is (a legvalószinubb celpont eppen egy pihenő session);
        # 2. az allapotfajl `focus_url` mezoje - tartalek, ha a folyamat
        #    kornyezete nem olvashato.
        #
        # A Dialra egyik sem megy ki: felesleges lenne minden masodpercben.
        record = read_status_files(self.status_dir).get(session_id)
        pid = None
        if isinstance(record, dict) and isinstance(record.get("pid"), int):
            pid = record["pid"]
        if pid is None:
            pid = warpfocus.pid_from_session_id(session_id)

        focus_url = warpfocus.focus_url_for_pid(pid)
        if not focus_url and isinstance(record, dict):
            focus_url = record.get("focus_url")

        try:
            warpfocus.focus_session(
                name,
                warpfocus.warp_pids(process_table()),
                log=self.log,
                focus_url=focus_url,
            )
        except Exception as exc:
            self.log("focus hiba: {}".format(exc))

    # --- zarolas ---------------------------------------------------------------

    def _read_lock(self):
        """A gep zarolasi allapota. Hiba eseten nincs zar, de naplozzuk.

        A valtozast naplozzuk (nem minden kort), kulonben masodpercenkent irna.
        """
        try:
            reason = self.lock_probe()
        except Exception as exc:
            self.log("zar-proba hiba: {}".format(exc))
            reason = None
        if reason != self._lock:
            self._lock = reason
            self.log(
                "zarolva ({})".format(reason) if reason else "feloldva"
            )
        return reason

    # --- aktiv Warp-tab ---------------------------------------------------------

    def _read_active(self, sessions):
        """Melyik session tabja van elol a Warp-ban, vagy None.

        Hiba eseten None: a kovetes kenyelmi funkcio, a kort nem allithatja meg.
        Ugyanazt a hibat csak egyszer naplozzuk, kulonben masodpercenkent irna.
        """
        try:
            title, is_warp = self.foreground_probe()
        except Exception as exc:
            message = "aktiv tab olvasasa: {}".format(exc)
            if message != self._active_error:
                self._active_error = message
                self.log(message)
            return None
        self._active_error = None
        return warpfocus.active_session_id(title, is_warp, sessions)

    # --- egy kor ---------------------------------------------------------------

    def tick(self):
        os.makedirs(self.status_dir, exist_ok=True)

        if self._handle_release_flag():
            return

        self._reload_config_if_changed()

        sessions = collect(self.status_dir, time.time())
        self.last_sessions = sessions

        # Tetlenseg-figyeles: ha egy ideje egyetlen Claude-session sincs, kilepunk.
        # Igy nem kell SessionEnd hook (amelynek a sajat, epp kilepo folyamatunkat
        # kellene kizarnia a szamolasbol), es nem marad arva folyamat sem. A
        # kovetkezo session SessionStart-ja ugyis ujrainditja.
        should_exit, self.idle_since = should_exit_idle(
            len(sessions), self.idle_since, time.time()
        )
        if should_exit:
            self.log("{} perce nincs Claude-session - kilepek".format(IDLE_EXIT_S // 60))
            raise _IdleExit()

        if not self._open():
            return

        # Az idojaras a sajat gyorsitotarabol jon; oranként egyszer megy ki
        # halozati keres, es ha az elbukik, a mezo egyszeruen kimarad.
        wx = get_weather(WEATHER_CACHE, self.lat, self.lon)

        # Zarolt gepen a Dial sem mutathat munka-informaciot (csak orat es
        # idojarast). A dontest a PC hozza, mert csak az latja a Windows
        # zarolasi allapotat; a Dial csak vegrehajtja.
        lock = self._read_lock()

        # A Dial kivalasztasa koveti az elol levo Warp-tabot. Zarolt gepen is
        # elkuldjuk; a Dial ott figyelmen kivul hagyja.
        active = self._read_active(sessions)

        self.seq += 1
        line = protocol.encode_snapshot(
            self.seq, self.cfg, sessions, now=local_now(), wx=wx, lock=lock,
            active=active,
        )
        try:
            self.serial.write(line.encode("utf-8"))
            waiting = self.serial.in_waiting
            if waiting:
                raw = self.serial.read(waiting)
                # A Dial `print()`-jei es tracebackjei ugyanezen a porton jonnek.
                # A LineReader ezeket eldobja (helyesen), de akkor egy eszkozon
                # tortent hiba nyomtalanul eltunik - ezert kulon naplozzuk oket.
                self._log_device_text(raw)
                for msg in self.reader.feed(raw):
                    self._apply_event(msg)
        except Exception as exc:
            self.log("soros hiba: {} - ujracsatlakozas".format(exc))
            self._close()

    def run(self, ticks=None, use_lock=True):
        """Vegtelen ciklus; `ticks` megadasaval veges (a probakhoz).

        `use_lock=False` csak a probakhoz kell - elesben mindig kell a zar.
        """
        pid = os.getpid()
        if use_lock:
            os.makedirs(self.status_dir, exist_ok=True)
            table = process_table()
            if not acquire_lock(LOCK_PATH, pid, lambda p: p in table):
                self.log("mar fut ugynok - kilepek")
                return

        count = 0
        errors = 0
        try:
            while ticks is None or count < ticks:
                started = time.time()
                try:
                    self.tick()
                    errors = 0
                except _IdleExit:
                    raise
                except Exception as exc:
                    # Egy elszallt kor NEM dontheti meg a szolgaltatast. A Dial
                    # ilyenkor csendben "nincs kapcsolat"-ra valtana, es a
                    # felhasznalo csak azt latna, hogy "megint nem megy".
                    errors += 1
                    self.log(
                        "hiba a korben ({}. egymas utan): {}".format(errors, exc)
                    )
                    self._close()
                    if errors >= MAX_CONSECUTIVE_ERRORS:
                        self.log("tartos hiba - feladom")
                        break
                count += 1
                sleep_for = self.tick_s - (time.time() - started)
                if sleep_for > 0:
                    time.sleep(sleep_for)
        except _IdleExit:
            pass
        finally:
            self._close()
            if use_lock:
                release_lock(LOCK_PATH, pid)
