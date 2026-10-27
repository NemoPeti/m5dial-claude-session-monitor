# SPDX-License-Identifier: MIT
"""Claude session-ertesito a Dialon (terv: docs/superpowers/specs/...-design.md).

A kerek kijelzo szelen egy szegmens minden sessionhoz, allapotszinnel. Kozepen
harom nezet valtakozik (a dontest a `panel.view_for` hozza):

- **sessions** - valaki rad var, vagy epp most nyultal az eszkozhoz
- **panel**    - senki nem var: ora, datum, idojaras, session-osszesito
- **offline**  - nincs ugynok: ugyanaz a panel, de gyuru nelkul
- **locked**   - a gep zarolt: CSAK ora, datum es idojaras, gyuru es osszesito
                 nelkul, tompitott fenyerovel, a bevitel tiltva

Ket dolog, ami merésbol jott, es amit nem szabad visszaalakitani:

- **A rajzolas M5GFX (`M5.Lcd.fillArc`), nem `m5ui`/LVGL.** Ugyanez a gyuru
  LVGL-bol 7782 ms alatt epult fel es 690 ms volt egy atszinezes; M5GFX-bol
  25 ms es 26 ms. A masodpercenkenti frissites csak igy fer bele (terv 4.8).
- **`micropython.kbd_intr(-1)` es nem blokkolo `uselect.poll`.** Enelkul egy
  0x03 bajt az adatfolyamban KeyboardInterrupttal megolne a programot, a
  blokkolo olvasas pedig megallitana a rajzolast es a gombkezelest (terv 4.7).
  Ara: az `mpremote` sem tud betorni, amig ez az app fut - a kiut a launcher
  hosszu nyomasa.

A launcher-szerzodes (lasd a m5dial skillt) miatt: a hosszu nyomas NEM a miénk,
az a launcher "vissza" gesztusa; a Timer(0) es a GPIO42 sem hasznalhato.
"""

import math
import sys
import time

import machine
import micropython
import uselect

import M5
from M5 import *  # noqa: F403
from hardware import Rotary

from alerts import (
    FOLLOW_GRACE_MS,
    ActiveFollower,
    ClickGesture,
    DwellTrigger,
    TouchGesture,
    next_volume,
    should_alert,
    volume_for,
    volume_overlay_lines,
    volume_overlay_visible,
    snapshot_cfg_accepted,
)
from panel import (
    format_clock,
    format_date,
    format_weather,
    center_name,
    short_labels,
    should_sync_clock,
    summary_lines,
    to_device_epoch,
    view_for,
)
from protocol import LineReader, encode_event

# --- Geometria (a spike_gyuru2.py-bol, elesben megmerve) -----------------------
CX = 120
CY = 120
R_OUT = 118
R_IN = 102
R_IN_SEL = 90
GAP_DEG = 6

# A gyuru-feliratok sugara. A gyuru belso szele 102 (kivalasztva 90), tehat a
# 78 mar biztosan a gyuru ALATT van, es nem log ra a szegmensre.
LABEL_R = 78

# A fillArc szogeinek nullpontja. Ha a feliratok elcsusznanak a szegmenseikhez
# kepest, EZT az egy szamot kell allitani (fokban), semmi mast.
LABEL_ANGLE_OFFSET = 0

C_BG = 0x101418
C_FG = 0xFFFFFF
C_DIM = 0x6C7A89
C_ACCENT = 0xFFA000

# Allapotszinek. A logika kozlekedesi lampa, a FELHASZNALO szemszogebol - nem a
# gepebol: **zold = nincs veled dolga**, sarga = rad var, piros = elakadt.
#
# Az elso valtozat a busy-t festette zoldre ("dolgozik, tehat jo"), de az
# felrevezeto: a zold onkentelenul azt jelenti, hogy keszen van. A dolgozo
# session ezert kek (folyamatban), a befejezett zold.
#
# Az `agents` (a kor vege, de alugynokok futnak meg) lila: a kek mar a `busy`-e,
# es a ket "nincs veled dolga" allapotnak ranezesre kulonboznie kell.
C_AGENTS = 0x8E24AA
STATE_COLORS = {
    "blocked": 0xE53935,  # piros - engedelyre var vagy elakadt
    "waiting": 0xFFA000,  # borostyan - RAD var
    "busy": 0x1E88E5,     # kek - dolgozik, nincs veled dolga
    "agents": C_AGENTS,   # lila - az alugynokeire var, nem rad
    "idle": 0x43A047,     # zold - befejezte a kort, nyugalomban
    "unknown": 0x37474F,  # sotetszurke - meg nem szolt hook
}

LINK_TIMEOUT_MS = 5000
MAX_SEGMENTS = 12

# Fenyero zarolt allapotban es azon kivul. A 0..255 tartomanyt az M5GFX
# `setBrightness` varja; a tenyleges fuggvenynevet indulaskor deritjuk ki
# (`_resolve_brightness`), mert a firmware nevei eltertek a typings-belitol.
BRIGHTNESS_NORMAL = 255
BRIGHTNESS_LOCKED = 40

# Egy koron belul ennyi bajtot szivunk fel a stdin-rol. Egy pillanatkep ~500
# bajt; a felso korlat azert kell, hogy egy folyamatos adatfolyam se tudja
# kiehezteni a rajzolast es a gombkezelest.
MAX_READ_PER_LOOP = 1024

# Minden ennyiedik pillanatkepnel kuldunk allapotjelentest a gepnek.
REPORT_EVERY = 5

# Becsult karakterszelesseg fontonkent, a kozepre igazitashoz. A firmware
# Label-szignaturaja eltér a typings-belitol, ezert nem tamaszkodunk a
# font_align parameterre.
CHAR_W_BIG = 22
CHAR_W_MID = 10
CHAR_W_SMALL = 7

# A panel sorainak fuggoleges helye. A kerek kijelzon a gyuru belso sugara 90 px,
# tehat a hasznalhato szelesseg a kozepponttol tavolodva fogy:
#
#     y=70  -> ~149 px      y=128 -> ~179 px
#     y=106 -> ~177 px      y=152 -> ~168 px      y=170 -> ~146 px
#
# Ezert kerult az ora feljebb, es ezert ket soros az osszesito.
Y_CLOCK = 70
Y_DATE = 108
Y_WX = 130
Y_INFO1 = 152
Y_INFO2 = 170

# A hangero-felirat: egy sor (Nema) kozepen, ketto (kis "Hangero" + nagy N/3)
# egymas alatt. A "Hangero" NEM nagy betuvel: 7 * 22 = 154 px-es teglalapja
# elesben belelogott a kijelolt szegmensbe (R_IN_SEL = 90).
Y_VOL_ONE = 100
Y_VOLW = 80
Y_VOL_NUM = 104

sessions = []
prev_sessions = None
cfg = {"mute": False, "volume": 2}
weather = None
muted_ids = set()
selection = 0
last_rx_ms = 0
last_input_ms = 0
link_up = False
# A gep zarolasi oka az ugynoktol ("lock" | "saver" | "idle"), vagy None.
locked = None
clock_set = False
_last_clock_sync_ms = None
reader = None
rotary = None
poller = None
_ring_key_drawn = None
_view = None
_center_key = None
_touch_was_down = False
_set_brightness = None
_brightness_applied = None
# EGY kattintas = ugras a session Warp-tabjara, KETTO = nemitas. A hosszu
# nyomas a launcheré (hardveres watchdog), azt nem tudjuk hasznalni.
_clicks = ClickGesture()
_last_click_ms = None
# Forgatas utan 2 mp nyugalom = ugyanaz az ugras, nyomas nelkul (allvanyon a
# kijelzo megnyomasa felbillenti a Dialt).
_dwell = DwellTrigger()
_last_move_ms = None
# A kivalasztas koveti a gepen aktiv Warp-tabot (`act`), de csak valtozaskor, es
# friss forgatas utan nem (lasd `alerts.ActiveFollower`). A `_last_move_ms`-t
# nem hasznalhatjuk erre: azt a tartozkodas elsulese torli.
_follow = ActiveFollower()
_last_rotate_ms = None
# Az utolso hangero-erintes ideje (ticks_ms), vagy None: amig a
# `VOLUME_OVERLAY_MS` le nem jar, a kozepen a fokozat felirata latszik.
_volume_touch_ms = None
# A helyben beallitott, a PC-nel meg nem visszaigazolt (fokozat, nemitva) par (lasd
# `alerts.snapshot_cfg_accepted`), es a beallitas ideje.
_volume_pending = None
_volume_pending_ms = None
# Erintes: rovid = hangero-lepes, hosszu = nemitas (lasd `alerts.TouchGesture`).
_touch = TouchGesture()
_touch_down_ms = None
_reported = 0

labels = {}
# A gyuru-feliratok kulon listaban: fix darabszam, a helyuket a szegmens
# kozepszoge adja, ezert nem illenek a nev szerinti `labels` szotarba.
ring_labels = []


def _send(line):
    sys.stdout.write(line)


# --- Gyuru ---------------------------------------------------------------------


def _color_for(session):
    return STATE_COLORS.get(session.get("st"), STATE_COLORS["unknown"])


def _segment_angles(i, count):
    span = 360.0 / count
    return int(i * span + GAP_DEG / 2), int((i + 1) * span - GAP_DEG / 2)


def _draw_segment(i, count, color, selected):
    start, end = _segment_angles(i, count)
    r_in = R_IN_SEL if selected else R_IN
    # Eloszor a teljes savot toroljuk, kulonben a vastagbol vekonyra valtas
    # otthagyja a regi belso szelet.
    M5.Lcd.fillArc(CX, CY, R_IN_SEL, R_OUT, start, end, C_BG)
    M5.Lcd.fillArc(CX, CY, r_in, R_OUT, start, end, color)


def _clear_ring():
    M5.Lcd.fillArc(CX, CY, R_IN_SEL, R_OUT, 0, 359, C_BG)
    _clear_ring_labels()


def _clear_ring_labels():
    for label in ring_labels:
        label.setText("")


def _label_xy(i, count):
    """A szegmens kozepenek kepernyo-koordinatai a felirat sugaran.

    A fillArc nullpontja a 3 ora iranyaban van, es az oramutato jarasaval
    egyezoen no; a kijelzon az y lefele no, ezert a sin elojele +.
    """
    start, end = _segment_angles(i, count)
    mid = math.radians((start + end) / 2.0 + LABEL_ANGLE_OFFSET)
    return CX + int(LABEL_R * math.cos(mid)), CY + int(LABEL_R * math.sin(mid))


def _draw_ring_labels(shown):
    """Rovid nev minden szegmenshez, hogy forgatas nelkul is lathato legyen,
    melyik szin melyik sessionhoz tartozik.

    A sorrend fontos: eloszor TOROLJUK a szoveget a REGI helyen, es csak utana
    mozgatjuk a Labelt. A Label ugyanis csak a sajat, aktualis helyet takaritja
    - athelyezes utan a regi helyen ott maradnanak a pixelek. Elesben pontosan
    ez latszott a fotokon: szemetes maradek a bal also sarokban.
    """
    if not ring_labels:
        return
    texts = short_labels([s.get("n") or s.get("id") or "" for s in shown])
    count = len(shown)
    for i, label in enumerate(ring_labels):
        label.setText("")
        if i >= count:
            continue
        text = texts[i]
        x, y = _label_xy(i, count)
        # A firmware neve `setColor` - az eszkoztol kerdeztuk meg
        # (`dir(Widgets.Label)`), a typings `set_text_color`-t mond.
        label.setColor(C_FG if i == selection else _color_for(shown[i]), C_BG)
        label.setCursor(x - (len(text) * CHAR_W_SMALL) // 2, y - 6)
        label.setText(text)


def _draw_ring():
    """Csak akkor rajzol, ha valtozott a kep - a kor 1 mp, ne pazaroljunk."""
    global _ring_key_drawn
    shown = sessions[:MAX_SEGMENTS]
    # A `_view` is a kulcs resze: nezetvaltaskor a feliratok megjelennek vagy
    # eltunnek, tehat ujra kell rajzolni.
    key = (_view, selection, tuple((s.get("id"), s.get("st")) for s in shown))
    if key == _ring_key_drawn:
        return
    _ring_key_drawn = key

    if not shown:
        _clear_ring()
        return
    for i, session in enumerate(shown):
        _draw_segment(i, len(shown), _color_for(session), i == selection)

    # A feliratok CSAK a session-nezetben. A panelen az ora, a datum es az
    # osszesito ugyanezen a sugaron ul - elesben egymasra ertek (`api` felul,
    # `cur`/`entr` az ora mellett, `m5st`/`Shop` a szovegen).
    if _view == "panel":
        _clear_ring_labels()
    else:
        _draw_ring_labels(shown)


# --- Fenyero -------------------------------------------------------------------


def _resolve_brightness():
    """A fenyero-allito fuggveny megkeresese - NEM talalgatas, hanem proba.

    A firmware nevei mar egyszer eltertek a `typings/`-belitol (`setColor` vs
    `set_text_color`), es a fenyero-allitas egyik valtozatban sincs benne a
    vendorozott konyvtarban. Ezert nem irunk be egy nevet talalomra: vegigmegyunk
    a szoba johetokon, es az elsot hasznaljuk, amelyik letezik. Ha egyik sem, a
    zarolas a fenyero nelkul is mukodik - csak nem tompit.
    """
    for owner_name in ("Lcd", "Display"):
        owner = getattr(M5, owner_name, None)
        if owner is None:
            continue
        for fn_name in ("setBrightness", "set_brightness", "setBrightnessLevel"):
            fn = getattr(owner, fn_name, None)
            if callable(fn):
                print("session_monitor: fenyero = M5.{}.{}".format(owner_name, fn_name))
                return fn
    print("session_monitor: nincs fenyero-allitas ezen a firmware-en")
    return None


def _apply_brightness(level):
    """Csak valtozaskor allit - a fociklus masodpercenkent tobbszor is idefut."""
    global _brightness_applied
    if _set_brightness is None or level == _brightness_applied:
        return
    try:
        _set_brightness(level)
        _brightness_applied = level
    except Exception as exc:
        print("session_monitor: a fenyero allitasa nem sikerult:", exc)


# --- Kozepso resz --------------------------------------------------------------


def _set(name, text, char_w, y):
    """Kozepre igazitott szoveg egy elore letrehozott Labelbe."""
    label = labels[name]
    label.setText(text)
    label.setCursor(CX - (len(text) * char_w) // 2, y)


def _clear_center():
    for name in labels:
        labels[name].setText("")


def _draw_sessions_view():
    global _center_key
    if not sessions:
        key = ("sessions", None)
        if key != _center_key:
            _center_key = key
            _clear_center()
            _set("name", "nincs session", CHAR_W_MID, 112)
        return

    session = sessions[min(selection, len(sessions) - 1)]
    name = center_name(session.get("n") or session.get("id") or "?")
    state = (session.get("st") or "?")
    if session.get("id") in muted_ids:
        state += " *"

    key = ("sessions", name, state)
    if key == _center_key:
        return
    _center_key = key
    _clear_center()
    _set("name", name, CHAR_W_MID, 104)
    _set("state", state, CHAR_W_MID, 128)


def _draw_panel_view(offline):
    """Ora + datum + idojaras + osszesito. Percenkent valtozik, nem masodpercenkent.

    Az elrendezes a kerek kijelzohoz igazodik: a gyuru belso sugara 90 px, tehat
    a hasznalhato szelesseg a kozepponttol tavolodva gyorsan fogy. Az ora ezert
    feljebb kerult, az osszesito pedig ket sorba - egy sorban belelogott a
    gyuruTbe (~182 px kellett volna a ~146 px helyen).
    """
    global _center_key
    now = time.localtime()
    clock = format_clock(now)
    date = format_date(now)
    wx = format_weather(weather)
    info = ["nincs kapcsolat"] if offline else summary_lines(sessions)

    key = ("panel", clock, date, wx, tuple(info))
    if key == _center_key:
        return
    _center_key = key
    _clear_center()
    _set("clock", clock, CHAR_W_BIG, Y_CLOCK)
    _set("date", date, CHAR_W_MID, Y_DATE)
    if wx:
        _set("wx", wx, CHAR_W_MID, Y_WX)
    _set("info", info[0], CHAR_W_SMALL, Y_INFO1)
    if len(info) > 1:
        _set("info2", info[1], CHAR_W_SMALL, Y_INFO2)


def _draw_locked_view():
    """Zarolt gep: ora, datum, idojaras - semmi mas.

    Se gyuru, se session-nev, se osszesito: a lezart gep kijelzojerol senki ne
    olvashassa le, min dolgozol, es hany session var rad.
    """
    global _center_key
    now = time.localtime()
    clock = format_clock(now)
    date = format_date(now)
    wx = format_weather(weather)

    key = ("locked", clock, date, wx)
    if key == _center_key:
        return
    _center_key = key
    _clear_center()
    _set("clock", clock, CHAR_W_BIG, Y_CLOCK)
    _set("date", date, CHAR_W_MID, Y_DATE)
    if wx:
        _set("wx", wx, CHAR_W_MID, Y_WX)


def _draw_volume_overlay():
    """A hangero-fokozat nagy felirata a kozepen, amig a `_volume_touch_ms` friss.

    Visszaadja, hogy a felirat van-e kint (ilyenkor a normal kozep nem rajzol).
    A kulcs a `_center_key`-ben van, ezert amikor a felirat lejar, a normal
    nezet kulcsa mar nem egyezik, es a kozep teljesen ujrarajzolodik.
    """
    global _center_key, _volume_touch_ms
    if _volume_touch_ms is None:
        return False
    elapsed = time.ticks_diff(time.ticks_ms(), _volume_touch_ms)
    if not volume_overlay_visible(elapsed):
        # Lejart: elfelejtjuk, kulonben a ticks korbefordulasakor (napok
        # mulva) a felirat ujra felvillanna.
        _volume_touch_ms = None
        return False

    lines = volume_overlay_lines(cfg.get("volume", 0), bool(cfg.get("mute")))
    key = ("volume", tuple(lines))
    if key != _center_key:
        _center_key = key
        _clear_center()
        if len(lines) == 1:
            _set("vol1", lines[0], CHAR_W_BIG, Y_VOL_ONE)
        else:
            _set("volw", lines[0], CHAR_W_MID, Y_VOLW)
            _set("vol1", lines[1], CHAR_W_BIG, Y_VOL_NUM)
    return True


def _apply_view():
    """A nezetvaltas az egyetlen hely, ahol teljes kepernyot torlunk."""
    global _view, _center_key, _ring_key_drawn, _volume_touch_ms

    wanted = view_for(
        sessions, time.ticks_ms(), last_input_ms, link_up, locked=bool(locked)
    )
    if wanted != _view:
        _view = wanted
        _center_key = None
        _ring_key_drawn = None
        Widgets.fillScreen(C_BG)  # noqa: F405

    _apply_brightness(BRIGHTNESS_LOCKED if wanted == "locked" else BRIGHTNESS_NORMAL)

    if wanted == "locked":
        # Zarolt gepen nincs bevitel: a felirat nem maradhat kint.
        _volume_touch_ms = None
        _draw_locked_view()
        return
    if wanted == "offline":
        if not _draw_volume_overlay():
            _draw_panel_view(True)
        return
    center_before = _center_key
    if not _draw_volume_overlay():
        if wanted == "panel":
            _draw_panel_view(False)
        else:
            _draw_sessions_view()
    # A Label torlese a teljes befoglalo teglalapjat hatterszinnel festi at, es
    # az belelog a gyurube (elesben a hangero-felirat lejarta utan a kijelolt
    # szegmensbol hianyzott egy darab). Ezert a gyuru a kozep UTAN rajzol, es
    # ha a kozep valtozott, akkor is, ha a sajat kulcsa nem.
    if _center_key != center_before:
        _ring_key_drawn = None
    _draw_ring()


# --- Bejovo pillanatkep --------------------------------------------------------


def _set_clock(now):
    """Az ugynok idejebol beallitjuk az RTC-t, hogy kapcsolat nelkul is jarjon."""
    global clock_set
    device_ts = to_device_epoch(now)
    if device_ts is None:
        return
    try:
        t = time.localtime(device_ts)
        machine.RTC().datetime((t[0], t[1], t[2], t[6] + 1, t[3], t[4], t[5], 0))
        clock_set = True
        print("session_monitor: ora beallitva", format_clock(time.localtime()))
    except Exception as exc:
        print("session_monitor: az ora beallitasa nem sikerult:", exc)


def _sync_clock_if_needed(now):
    """A gep ideje minden pillanatkepben megjon - idonkent allitsuk be belole.

    Eddig csak az ELSO kapcsolatfelvetelkor allitottuk az orat, es elesben 16
    perccel jart rosszul: egy rossz elso beallitast semmi nem hozott helyre.
    Halozati idoforras nem kell hozza, a gep ideje eleg.
    """
    global _last_clock_sync_ms
    if not now:
        return
    elapsed = None
    if _last_clock_sync_ms is not None:
        elapsed = time.ticks_diff(time.ticks_ms(), _last_clock_sync_ms)
    if should_sync_clock(clock_set, elapsed):
        _set_clock(now)
        _last_clock_sync_ms = time.ticks_ms()


def _apply_snapshot(msg):
    global sessions, prev_sessions, cfg, muted_ids, selection, weather, _reported
    global locked, _volume_pending, _volume_pending_ms

    new_sessions = msg.get("sessions") or []
    alert, muted_ids = should_alert(prev_sessions, new_sessions, muted_ids)

    prev_sessions = new_sessions
    sessions = new_sessions
    snap_cfg = msg.get("cfg")
    if snap_cfg:
        pending_elapsed = None
        if _volume_pending_ms is not None:
            pending_elapsed = time.ticks_diff(time.ticks_ms(), _volume_pending_ms)
        if snapshot_cfg_accepted(_volume_pending, pending_elapsed, snap_cfg):
            cfg = snap_cfg
            _volume_pending = None
            _volume_pending_ms = None
    weather = msg.get("wx") or weather
    # A zar-jelzes hianya ERVENYES ertek (= feloldva), ezert itt nincs `or`:
    # a `weather`-rel ellentetben nem az utolso ismert erteket tartjuk meg.
    locked = msg.get("lk")

    if msg.get("now"):
        # NEM `_set_clock` kozvetlenul: az minden pillanatkepnel ujraallitana az
        # orat (elesben masodpercenkent irta a naplot). A `_sync_clock_if_needed`
        # idozit - lasd `panel.should_sync_clock`.
        _sync_clock_if_needed(msg["now"])

    if selection >= len(sessions):
        selection = max(0, len(sessions) - 1)

    # Zarolt gepen az `act`-ot figyelmen kivul hagyjuk (a kovetot sem leptetjuk).
    if not locked:
        _follow_active(msg.get("act"))

    volume = volume_for(cfg)
    M5.Speaker.setVolume(volume)
    if alert and volume:
        M5.Speaker.tone(3200, 120)

    # A Dial kijelzojet a gepről nem latjuk, a soros portot pedig az ugynok fogja
    # - ez az egyetlen gepi bizonyitek arrol, hogy mi epult fel. Minden REPORT_EVERY.
    # pillanatkepnel jelentunk, nem csak egyszer: egy egyszeri jelentest egy korabbi
    # futas mar "elhasznalhat", es akkor a kovetkezo probanal nemanak latszik.
    _reported += 1
    if _reported % REPORT_EVERY == 1:
        _send(
            encode_event(
                "dbg",
                view=_view,
                n=len(sessions),
                clk=format_clock(time.localtime()),
                wx=format_weather(weather),
            )
        )


def _follow_active(act):
    """Az aktiv Warp-tab kovetese: csak a `selection` valtozik.

    Szandekosan NINCS hang, tartozkodas-elesites, focus-kuldes, `last_input_ms`
    es nezetvaltas - ez nem a felhasznalo bevitele. A gyuru a `_draw_ring`
    kulcsaban levo `selection` miatt magatol ujrarajzolodik.
    """
    global selection, _last_rotate_ms
    since = None
    if _last_rotate_ms is not None:
        since = time.ticks_diff(time.ticks_ms(), _last_rotate_ms)
        # A turelmi ido lejart: elfelejtjuk, kulonben napok mulva a ticks
        # korbefordulasa negativ (= "friss") kulonbseget adna.
        if since >= FOLLOW_GRACE_MS:
            _last_rotate_ms = None
    shown_ids = [s.get("id") for s in sessions[:MAX_SEGMENTS]]
    index = _follow.update(act, since, shown_ids)
    if index is not None:
        selection = index


# --- Bevitel -------------------------------------------------------------------


def _selected_id():
    if not sessions:
        return None
    return sessions[min(selection, len(sessions) - 1)].get("id")


def _toggle_mute():
    """Ketto kattintas: a kivalasztott session nemitasa/visszakapcsolasa."""
    sid = _selected_id()
    if not sid:
        return
    if sid in muted_ids:
        muted_ids.discard(sid)
        _send(encode_event("ack", id=sid, m=0))
        M5.Speaker.tone(4000, 25)
    else:
        muted_ids.add(sid)
        _send(encode_event("ack", id=sid, m=1))
        M5.Speaker.tone(5200, 25)


def _focus_selected():
    """Egy kattintas vagy 2 mp tartozkodas: ugras a session Warp-tabjara (terv 4.4)."""
    sid = _selected_id()
    if not sid:
        return
    # Kattintasra is: ne ugorjon meg egyszer, amikor a tartozkodas lejar.
    _dwell.cancel()
    _send(encode_event("focus", id=sid))
    M5.Speaker.tone(7000, 40)


def _drain_input():
    """Zarolt allapotban: a bemenetet elolvassuk, de eldobjuk.

    Olvasni KELL: az enkoder kulonben felhalmozza a lepteket, es feloldaskor a
    kivalasztas egy nagyot ugrana. A `_touch_was_down` ugyanezert kovetjuk
    tovabb - kulonben a feloldas utani elso kor hamis erintes-eleként latna a
    meg le nem engedett ujjat.
    """
    global _touch_was_down, _last_click_ms, _touch_down_ms
    if rotary.get_rotary_status():
        rotary.get_rotary_increments()
    BtnA.wasClicked()  # noqa: F405
    # A fuggoben levo egy-kattintas es tartozkodas is elvesz: zarolt gepen nem
    # ugrunk sehova.
    _last_click_ms = None
    _dwell.cancel()
    # A gesztus is elvesz: a feloldaskor nem sulhat el rovid/hosszu erintes.
    _touch.cancel()
    _touch_down_ms = None
    _touch_was_down = M5.Touch.getCount() > 0


def _volume_changed():
    """Hangero/nemitas valtozas utan: felirat, fuggo cfg es jelentes a gepnek."""
    global last_input_ms, _volume_touch_ms, _volume_pending, _volume_pending_ms
    last_input_ms = time.ticks_ms()
    # Ujabb valtozas ujrainditja a felirat visszaszamlalasat.
    _volume_touch_ms = last_input_ms
    _volume_pending = (cfg["volume"], bool(cfg["mute"]))
    _volume_pending_ms = last_input_ms
    _send(encode_event("vol", v=cfg["volume"], m=1 if cfg["mute"] else 0))


def _handle_input():
    global selection, muted_ids, cfg, last_input_ms, _touch_was_down
    global _last_click_ms, _last_move_ms, _last_rotate_ms, _touch_down_ms

    if locked:
        _drain_input()
        return

    if rotary.get_rotary_status():
        delta = rotary.get_rotary_increments()
        if delta and sessions:
            selection = (selection + delta) % min(len(sessions), MAX_SEGMENTS)
            last_input_ms = time.ticks_ms()
            _last_move_ms = last_input_ms
            _last_rotate_ms = last_input_ms
            _dwell.moved()
            M5.Speaker.tone(6500, 12)

    # Tartozkodas: ha a kivalasztas DWELL_FOCUS_MS-ig all, ugras a Warp-tabra.
    if _last_move_ms is not None:
        if _dwell.poll(time.ticks_diff(time.ticks_ms(), _last_move_ms)):
            _last_move_ms = None
            _focus_selected()

    # EGY kattintas: ugras a session Warp-tabjara. KETTO: nemitas.
    # A HOSSZU nyomas a launcheré - azt nem tudjuk elvenni tole.
    if BtnA.wasClicked() and sessions:  # noqa: F405
        _last_click_ms = time.ticks_ms()
        last_input_ms = _last_click_ms
        if _clicks.click() == "double":
            _toggle_mute()

    # Az egyes kattintas csak akkor derul ki, amikor a dupla-ablak lejart.
    if _last_click_ms is not None:
        elapsed = time.ticks_diff(time.ticks_ms(), _last_click_ms)
        if _clicks.poll(elapsed) == "single":
            _focus_selected()

    # Erintes: rovid (felengedeskor) = hangero-fokozat leptetese (terv 4.6),
    # hosszu (tartva) = nemitas a fokozat megtartasaval.
    touch_down = M5.Touch.getCount() > 0
    gesture = None
    if touch_down and not _touch_was_down:
        _touch.down()
        _touch_down_ms = time.ticks_ms()
    elif touch_down and _touch_down_ms is not None:
        gesture = _touch.poll(time.ticks_diff(time.ticks_ms(), _touch_down_ms))
    elif _touch_was_down and not touch_down:
        gesture = _touch.up()
        _touch_down_ms = None
    _touch_was_down = touch_down

    if gesture == "short":
        cfg["volume"] = next_volume(cfg.get("volume", 0))
        cfg["mute"] = False
        M5.Speaker.setVolume(volume_for(cfg))
        M5.Speaker.tone(4200, 40)
        _volume_changed()
    elif gesture == "long":
        cfg["mute"] = not cfg.get("mute")
        if cfg["mute"]:
            # Nemitaskor ELSO a hang, utana a nema (kulonben nem hallanank).
            M5.Speaker.tone(2500, 70)
            M5.Speaker.setVolume(volume_for(cfg))
        else:
            M5.Speaker.setVolume(volume_for(cfg))
            M5.Speaker.tone(3300, 70)
        _volume_changed()


# --- Fociklus ------------------------------------------------------------------


def setup():
    global reader, rotary, poller, last_rx_ms, last_input_ms, _set_brightness

    # Enelkul egy 0x03 bajt az adatfolyamban megolne a programot (terv 4.7).
    micropython.kbd_intr(-1)

    M5.begin()
    Widgets.fillScreen(C_BG)  # noqa: F405

    # Minden feliratot egyszer hozunk letre, es szoveg-cserevel hasznalunk
    # ujra - a Label letrehozasa dragabb, mint a setText.
    labels["clock"] = Widgets.Label(  # noqa: F405
        "", 60, Y_CLOCK, 1.0, C_FG, C_BG, Widgets.FONTS.DejaVu40  # noqa: F405
    )
    labels["date"] = Widgets.Label(  # noqa: F405
        "", 60, Y_DATE, 1.0, C_DIM, C_BG, Widgets.FONTS.DejaVu18  # noqa: F405
    )
    labels["wx"] = Widgets.Label(  # noqa: F405
        "", 60, Y_WX, 1.0, C_ACCENT, C_BG, Widgets.FONTS.DejaVu18  # noqa: F405
    )
    labels["info"] = Widgets.Label(  # noqa: F405
        "", 60, Y_INFO1, 1.0, C_DIM, C_BG, Widgets.FONTS.DejaVu12  # noqa: F405
    )
    labels["info2"] = Widgets.Label(  # noqa: F405
        "", 60, Y_INFO2, 1.0, C_DIM, C_BG, Widgets.FONTS.DejaVu12  # noqa: F405
    )
    labels["name"] = Widgets.Label(  # noqa: F405
        "", 60, 104, 1.0, C_FG, C_BG, Widgets.FONTS.DejaVu18  # noqa: F405
    )
    labels["state"] = Widgets.Label(  # noqa: F405
        "", 60, 128, 1.0, C_DIM, C_BG, Widgets.FONTS.DejaVu18  # noqa: F405
    )
    # A hangero-felirat ket sora (nagy betu). A `labels`-ben vannak, hogy a
    # `_clear_center` torolje oket, amikor a normal nezet visszajon.
    labels["volw"] = Widgets.Label(  # noqa: F405
        "", 60, Y_VOLW, 1.0, C_DIM, C_BG, Widgets.FONTS.DejaVu18  # noqa: F405
    )
    labels["vol1"] = Widgets.Label(  # noqa: F405
        "", 60, Y_VOL_NUM, 1.0, C_ACCENT, C_BG, Widgets.FONTS.DejaVu40  # noqa: F405
    )

    # A gyuru-feliratok: annyi, ahany szegmens lehet. Egyszer jonnek letre, es
    # a helyuk minden ujrarajzolaskor valtozhat (a szegmensek szama fugg attol,
    # hany session van).
    for _ in range(MAX_SEGMENTS):
        ring_labels.append(
            Widgets.Label(  # noqa: F405
                "", 0, 0, 1.0, C_DIM, C_BG, Widgets.FONTS.DejaVu12  # noqa: F405
            )
        )

    _set_brightness = _resolve_brightness()

    reader = LineReader()
    rotary = Rotary()

    poller = uselect.poll()
    poller.register(sys.stdin, uselect.POLLIN)

    last_rx_ms = time.ticks_ms()
    last_input_ms = time.ticks_ms()
    print("session_monitor: elindult")


def loop():
    global last_rx_ms, link_up

    M5.update()

    # Nem blokkolo olvasas. A stdin bajtonkent adja magat, ezert egy koron belul
    # kiszivattyuzzuk, ami keszen all - kulonben egy ~500 bajtos pillanatkep
    # 10 ms-os koridovel masodpercekig csepegne be.
    pending = 0
    while pending < MAX_READ_PER_LOOP and poller.poll(0):
        chunk = sys.stdin.read(1)
        pending += 1
        if not chunk:
            break
        for msg in reader.feed(chunk):
            kind = msg.get("t")
            if kind == "s":
                _apply_snapshot(msg)
                link_up = True
                last_rx_ms = time.ticks_ms()
            elif kind == "quit":
                # Fejlesztoi kiut. A `kbd_intr(-1)` miatt az mpremote nem tud
                # betorni, amig ez az app fut, tehat minden ujratelepites elott
                # kezzel, hosszu nyomassal kellene kilepni. Ez a parancs ugyanazt
                # teszi, tavolról. A resetet a FOCIKLUSBOL hivjuk (itt vagyunk),
                # nem callbackbol - lasd a launcher-szerzodest.
                print("session_monitor: quit - visszaadom a vezerlest")
                micropython.kbd_intr(3)
                machine.soft_reset()

    if time.ticks_diff(time.ticks_ms(), last_rx_ms) > LINK_TIMEOUT_MS:
        link_up = False

    _handle_input()
    _apply_view()
    time.sleep_ms(10)  # NEM elhagyhato - lasd a launcher-szerzodest


if __name__ == "__main__":
    try:
        setup()
        while True:
            loop()
    except Exception as exc:
        # **Nem `BaseException`.** A `machine.soft_reset()` `SystemExit`-tel
        # dolgozik, es a resetet epp az valtja ki, hogy ez a kivetel felmegy a
        # legfelso szintig - elkapva a reset elmarad, es az egesz lanc a REPL-be
        # bukik. Elesben pontosan ez tortent.
        # A kepernyore kiirt piros hibakep eltunik a kovetkezo indulassal, es a
        # felhasznalo nem feltetlenul olvassa el - a soros naplo viszont megmarad.
        print("session_monitor: HIBAVAL ALLT LE")
        sys.print_exception(exc)
        raise
    finally:
        # Enelkul egy elszallt app sukétan hagyja az eszkozt: a Ctrl-C tiltva
        # marad, es az mpremote nem tud betorni, amig valaki fizikailag nem
        # nyul hozza. Elesben ketszer kellett hosszu nyomassal kimenteni.
        micropython.kbd_intr(3)
