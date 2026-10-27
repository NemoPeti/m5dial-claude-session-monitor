"""Hangszabaly a Dialon (terv 4.5, 4.6).

FONTOS: ez a modul a Dialra kerul at es MicroPythonon fut, NEM a PC-n. Ezert
csak a beepitett standard konyvtarat hasznalja, es csak azt, ami MicroPythonon
is letezik: nincs f-string (helyette "{}".format(...)), nincs tipusannotacio,
nincs typing/dataclasses/enum import, nincs semmi CPython-only.

Dontesek, ahol a terv hallgatott:
- Egy UJ session-azonosito, ami mar rogton "waiting" vagy "blocked" allapotban
  tunik fel (nem volt korabban a listaban), atmenetnek szamit, tehat szol.
  Indoklas: az elozo pillanatkepben nem volt "waiting", tehat az uj allapotba
  lepes ugyanugy igaz ra, mint egy mar ismert sessionre.
- A sessiononkenti nemitas ("muted_ids") ugy targolt, hogy csak akkor torlodik,
  amikor a session ELHAGYJA a waiting/blocked allapotot (azaz az elozo
  pillanatkepben waiting vagy blocked volt, es most mar nem az). Ez fedi a
  terv "a sessiononkenti nemitas az adott session kovetkezo
  allapotvaltasakor magatol megszunik" mondatat: a nemitast az a
  allapotvaltas oldja fel, amivel a felhasznalo mar reagalt/tovabblepett a
  nemitott riasztason, nem barmilyen mas allapotvaltas. A kovetkezo, UJABB
  waiting/blocked atmenet mar ujra szol.
"""


def _index_by_id(sessions):
    """Session-lista -> {id: st} szotar. Hianyzo mezok eseten kihagyja a bejegyzest."""
    result = {}
    for s in sessions:
        sid = s.get("id")
        if sid is None:
            continue
        result[sid] = s.get("st")
    return result


def should_alert(prev_sessions, new_sessions, muted_ids):
    """Terv 4.5: hang akkor kell, ha egy session waiting vagy blocked allapotba LEP.
    Visszaad (alert, muted_ids) part - a muted_ids frissitve."""
    muted_ids = set(muted_ids) if muted_ids else set()

    if prev_sessions is None:
        # Az elso pillanatkep csatlakozas utan mindig nema (terv 4.5).
        return False, muted_ids

    prev_by_id = _index_by_id(prev_sessions)
    new_by_id = _index_by_id(new_sessions)

    alert = False
    for sid, new_st in new_by_id.items():
        prev_st = prev_by_id.get(sid)  # None, ha uj session

        if prev_st == new_st:
            # Nincs allapotvaltas -> a nemitas (ha volt) ervenyben marad.
            continue

        # Allapotvaltas tortent. A nemitas csak akkor szunik meg, ha a
        # session ELHAGYTA a waiting/blocked allapotot - ez az "adott session
        # kovetkezo allapotvaltasa", amirol a terv 4.5-e beszel.
        if prev_st in ("waiting", "blocked"):
            muted_ids.discard(sid)

        if new_st in ("waiting", "blocked"):
            if sid in muted_ids:
                continue
            alert = True

    return alert, muted_ids


_VOLUME_MAP = {0: 0, 1: 48, 2: 128, 3: 255}


def volume_for(cfg):
    """Terv 4.6: a konfigbol M5.Speaker.setVolume() ertek. mute -> 0."""
    if cfg.get("mute"):
        return 0
    level = cfg.get("volume", 0)
    return _VOLUME_MAP.get(level, 0)


def next_volume(volume):
    """A negy fokozat korbe: 0 -> 1 -> 2 -> 3 -> 0."""
    return (volume + 1) % 4


# --- Kattintas-gesztus ---------------------------------------------------------
#
# EGY kattintas = ugras a session Warp-tabjara (ez a fo funkcio), KETTO =
# nemitas. A hosszu nyomas a launcheré (hardveres watchdog, az app nem tudja
# felulirni), ezert csak ez a ket gesztus all rendelkezesre.
#
# Az egyes kattintas hatasa szuksegkeppen KESIK a dupla-ablaknyit: amig az le
# nem jar, nem tudhato, hogy nem par elso fele-e. Forditva nem megy: ha az
# ugras azonnal megtortenne, egy dupla kattintas eloszor elugrana a tabra, es
# csak utana nemitana - a felhasznalo alol elveve az ablakot.

DOUBLE_CLICK_MS = 400


class ClickGesture:
    """Kattintasokbol "single" / "double" gesztus.

    Ketreszes, mert az egyes kattintas csak az ablak lejartakor derul ki:

        click()            - minden kattintasnal; "double"-t ad a par masodikara
        poll(elapsed_ms)   - minden korben; "single"-t ad, ha lejart az ablak

    Az eltelt idot a hivo szamolja (a Dialon `time.ticks_diff`, ami a szamlalo
    korbefordulasat is kezeli) - ez a modul csak dontest hoz.
    """

    def __init__(self, window_ms=DOUBLE_CLICK_MS):
        self.window_ms = window_ms
        self._pending = False

    def click(self):
        """Visszaad: "double" ha ez egy par masodik tagja, kulonben None."""
        if self._pending:
            self._pending = False
            return "double"
        self._pending = True
        return None

    def poll(self, elapsed_ms):
        """elapsed_ms: az utolso kattintas ota eltelt ido, vagy None.

        Visszaad: "single", ha a dupla-ablak lejart es nem jott masodik
        kattintas; kulonben None.
        """
        if not self._pending or elapsed_ms is None:
            return None
        if elapsed_ms > self.window_ms:
            self._pending = False
            return "single"
        return None


# --- Erintes-gesztus -----------------------------------------------------------
#
# ROVID erintes (felengedeskor) = hangero-lepes, HOSSZU (LONG_TOUCH_MS, tartva,
# felengedes nelkul) = nemitas. A firmware isHolding-jat nem hasznaljuk: a
# sajat idomeres kiszamithato.
LONG_TOUCH_MS = 800


class TouchGesture:
    """Erintesbol "short" / "long" gesztus.

        down()             - amikor az ujj leer
        poll(elapsed_ms)   - minden korben tartas kozben; "long"-ot ad EGYSZER
        up()               - amikor felemelik; "short"-ot ad, ha nem volt long
        cancel()           - eldobja a gesztust (pl. zarolaskor)

    Az eltelt idot a hivo szamolja (`time.ticks_diff`).
    """

    def __init__(self, long_ms=LONG_TOUCH_MS):
        self.long_ms = long_ms
        self._down = False
        self._fired = False

    def down(self):
        self._down = True
        self._fired = False

    def poll(self, elapsed_ms):
        if not self._down or self._fired or elapsed_ms is None or elapsed_ms < 0:
            return None
        if elapsed_ms >= self.long_ms:
            self._fired = True
            return "long"
        return None

    def up(self):
        if not self._down:
            return None
        self._down = False
        return None if self._fired else "short"

    def cancel(self):
        self._down = False
        self._fired = False


# --- Tartozkodas ---------------------------------------------------------------
#
# Forgatas utan, ha a kivalasztas DWELL_FOCUS_MS-ig nem mozdul, a gep a session
# Warp-tabjara ugrik - nyomas nelkul. Allvanyon a kijelzo megnyomasa felbillenti
# a Dialt, a forgatas nem. Csak FORGATAS elesit: bootkor vagy uj pillanatkepre
# nem ugrunk sehova, mert azt nem a felhasznalo kerte.

DWELL_FOCUS_MS = 2000


class DwellTrigger:
    """moved() minden forgataskor, poll(elapsed_ms) minden korben.

    poll() egyszer ad True-t, amikor a forgatas ota eltelt ido eleri a kuszobot;
    utana ujabb moved()-ig csendes. Az eltelt idot a hivo szamolja.
    """

    def __init__(self, dwell_ms=DWELL_FOCUS_MS):
        self.dwell_ms = dwell_ms
        self._armed = False

    def moved(self):
        self._armed = True

    def cancel(self):
        self._armed = False

    def poll(self, elapsed_ms):
        if not self._armed or elapsed_ms is None:
            return False
        if elapsed_ms >= self.dwell_ms:
            self._armed = False
            return True
        return False


# --- Aktiv tab kovetese ----------------------------------------------------------
#
# A PC minden pillanatkepben elkuldi (`act`), melyik session Warp-tabja van elol.
# A Dial kivalasztasa ezt koveti, de csak VALTOZASKOR (el-vezerelt): ha minden
# pillanatkepnel alkalmaznank, a felhasznalo forgatasat masodpercenkent
# visszaallitana, amig a Warp ugyanazon a taban all.
#
# Dontesek:
# - Hianyzo `act` (a Warp nincs elol, vagy nincs egyertelmu egyezes) NEM torli az
#   utolso ismert erteket. Igy egy Alt-Tab oda-vissza ugyanarra a tabra nem
#   szamit valtozasnak, es nem rantja el a kivalasztast onnan, ahova a
#   felhasznalo kozben forgatott.
# - Friss forgatas utan (FOLLOW_GRACE_MS-on belul) a valtozast ELDOBJUK, nem
#   halasztjuk: a felhasznalo epp valaszt, es a tartozkodas (DwellTrigger) ugyis
#   a Dial valasztasahoz igazitja majd a Warp-tabot.
# - A nem lathato (a MAX_SEGMENTS utani, vagy mar eltunt) session is elhasznalja
#   a valtozast: kesobb, ha megjelenik, nem ugrunk ra utolag.
# - Ez a modul csak dont: nem sipol, nem elesiti a tartozkodast, nem kuld
#   focus-t, es nem szamit bevitelnek - azt a hivo sem teheti.

FOLLOW_GRACE_MS = 3000


class ActiveFollower:
    """update(act, since_rotate_ms, shown_ids) minden pillanatkepnel.

    act: a PC szerint aktiv session azonositoja, vagy None.
    since_rotate_ms: az utolso forgatas ota eltelt ido, vagy None (nem volt).
    shown_ids: a gyurun latszo sessionok azonositoi, sorrendben.

    Visszaad: a kivalasztando index, vagy None (maradjon a mostani).
    """

    def __init__(self, grace_ms=FOLLOW_GRACE_MS):
        self.grace_ms = grace_ms
        self._last_act = None

    def update(self, act, since_rotate_ms, shown_ids):
        if not act or act == self._last_act:
            return None
        self._last_act = act
        if since_rotate_ms is not None and since_rotate_ms < self.grace_ms:
            return None
        for i, sid in enumerate(shown_ids):
            if sid == act:
                return i
        return None


# --- Hangero-feliratkep --------------------------------------------------------
#
# Erintesre a hangero leptet; hogy lassuk, mire allt, a kozepen ennyi ideig
# nagy felirat mutatja a fokozatot, aztan visszater a normal nezet.
VOLUME_OVERLAY_MS = 2000


def volume_overlay_lines(level, muted=False):
    """A felirat sorai: nemitva vagy 0 -> ["Nema"], 1..3 -> ["Hangero", "N/3"]."""
    if muted or level < 1:
        return ["Nema"]
    return ["Hangero", "%d/3" % min(level, 3)]


def volume_overlay_visible(elapsed_ms):
    """elapsed_ms: az utolso erintes ota eltelt ido, vagy None (nincs felirat).

    A negativ erteket (ticks korbefordulas) NEM tekintjuk frissnek.
    """
    return elapsed_ms is not None and 0 <= elapsed_ms < VOLUME_OVERLAY_MS


# A helyi hangero-leptetes utan a PC meg a REGI fokozatot tartalmazo
# pillanatkepet is kuldhet (a "vol" esemenyt csak a kovetkezo korben olvassa
# be). Ezeket nem fogadjuk el, kulonben a fokozat ide-oda villogna.
VOLUME_PENDING_MS = 5000


def snapshot_cfg_accepted(pending, elapsed_ms, snapshot_cfg):
    """Felulirhatja-e a pillanatkep cfg-je a helyi hangero-beallitast?

    pending: a helyben beallitott, a PC-nel meg nem visszaigazolt
    (fokozat, nemitva) par, vagy None. elapsed_ms: a beallitas ota eltelt ido
    (None/negativ = nem megbizhato, ticks korbefordulas -> elfogadjuk, nem
    ragadunk bele). A fokozatot ES a nemitast is osszevetjuk: egy elavult
    pillanatkep a nemitast sem vonhatja vissza.
    """
    if pending is None or elapsed_ms is None or elapsed_ms < 0:
        return True
    if elapsed_ms >= VOLUME_PENDING_MS:
        return True
    snapshot = (snapshot_cfg.get("volume"), bool(snapshot_cfg.get("mute")))
    return snapshot == tuple(pending)
