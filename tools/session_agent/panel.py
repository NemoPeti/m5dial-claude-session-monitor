# SPDX-License-Identifier: MIT
"""Az ora/idojaras panel tiszta logikaja (nezetvalasztas es formazas).

FONTOS: ez a modul a Dialra kerul at es MicroPythonon fut, NEM a PC-n. Ezert
csak azt hasznalja, ami MicroPythonon is letezik: nincs f-string (helyette
"{}".format(...)), nincs tipusannotacio, nincs typing/dataclasses/enum import.

**Minden kiirt szoveg ASCII.** A kijelzo betukeszlete (`Widgets.FONTS.DejaVu18`)
ekezetes betuit nem probaltuk ki, es egy hianyzo glif nemán rossz kepet ad -
ezert a napnevek es az idojaras-feliratok ekezet nelkuliek ("csutortok",
"felhos"). Van ra teszt, hogy ez igy is maradjon.

A modul semmit nem rajzol: a `session_monitor.py` kérdezi meg tole, MIT kell
mutatni, es az rajzolja. Igy a dontes asztali Pythonon tesztelheto.
"""

# A MicroPython idotuplijeben (localtime) a hetfo = 0.
DAY_NAMES = ("hetfo", "kedd", "szerda", "csutortok", "pentek", "szombat", "vasarnap")

# Ezek az allapotok jelentik, hogy a session a felhasznalora var.
WAITING_STATES = ("waiting", "blocked")

# Forgatas/kattintas utan ennyi ideig meg a session-nezet marad, hogy legyen ido
# megnezni, mire kattintottal. Utana magatol visszaall a panel.
GRACE_MS = 5000

# MEGMERVE 2026-09-10-en ezen a firmware-en (UIFlow2 v2.5.2):
#
#     >>> time.localtime(0)
#     (1970, 1, 1, 0, 0, 0, 3, 1)
#
# tehat az idoszamitas kezdete **1970-01-01**, ugyanaz, mint a Unix-ido, es nem
# kell atszamolni. Ez nem magatol ertetodo: a MicroPython ESP32-portja
# hagyomanyosan 2000-01-01-tol szamol, es en is arra szamitottam - a merés
# cafolta. Az atszamito fuggveny azert marad meg, mert egy masik firmware-en
# vagy masik boardon megvaltozhat: ott eleg ezt az egy szamot atallitani.
MPY_EPOCH_OFFSET = 0


def to_device_epoch(unix_ts, offset=MPY_EPOCH_OFFSET):
    """Unix-ido -> az eszkoz sajat idoszamitasa. Hibas bemenetre None."""
    try:
        return int(unix_ts) - offset
    except (TypeError, ValueError):
        return None


def anyone_waiting(sessions):
    """Igaz, ha barmelyik session a felhasznalora var."""
    if not sessions:
        return False
    for session in sessions:
        if session.get("st") in WAITING_STATES:
            return True
    return False


def summarize(sessions):
    """Allapot-szamlalok a panel osszesito sorahoz.

    Az `agents` (a session az alugynokeire var) a "dolgozik" koze szamit: a
    felhasznalonak nincs vele dolga, a munka folyik.
    """
    counts = {"total": 0, "busy": 0, "waiting": 0, "blocked": 0}
    if not sessions:
        return counts
    for session in sessions:
        counts["total"] += 1
        state = session.get("st")
        if state == "agents":
            counts["busy"] += 1
        elif state in counts and state != "total":
            counts[state] += 1
    return counts


def format_summary(sessions):
    """Egy sor a gyuru tartalmarol szamokban: "7 session, 3 dolgozik, 0 var"."""
    counts = summarize(sessions)
    if counts["total"] == 0:
        return "nincs session"
    return "{} session, {} dolgozik, {} var".format(
        counts["total"], counts["busy"], counts["waiting"] + counts["blocked"]
    )


def summary_lines(sessions):
    """Ugyanaz ket sorban, hogy ne erjen bele a gyuruTbe.

    A kerek kijelzon a hasznalhato szelesseg lefele egyre kisebb: a gyuru belso
    sugara 90 px, tehat a kozepponttol 52 px-re mar csak ~146 px marad. Az
    egysoros valtozat ("8 session, 3 dolgozik, 0 var") ennel szelesebb, es
    elesben lathatoan belelogott a gyuruTbe - ezert tordeljuk.
    """
    counts = summarize(sessions)
    if counts["total"] == 0:
        return ["nincs session"]
    return [
        "{} session".format(counts["total"]),
        "{} dolgozik, {} var".format(
            counts["busy"], counts["waiting"] + counts["blocked"]
        ),
    ]


def format_clock(t):
    """"OO:PP" a `time.localtime()` tuplijebol. Hibas bemenetre "--:--"."""
    try:
        return "{:02d}:{:02d}".format(t[3], t[4])
    except (TypeError, IndexError, ValueError):
        return "--:--"


def format_date(t):
    """"HH-NN napnev". Ismeretlen napindex eseten csak a datum."""
    try:
        date = "{:02d}-{:02d}".format(t[1], t[2])
    except (TypeError, IndexError, ValueError):
        return ""
    try:
        return date + " " + DAY_NAMES[t[6]]
    except (TypeError, IndexError):
        return date


def format_weather(wx):
    """"12C felhos". Hianyzo adatra ures sor - a panel ilyenkor elhagyja."""
    if not wx:
        return ""
    temp = wx.get("t")
    if temp is None:
        return ""
    label = wx.get("c")
    text = "{}C".format(temp)
    return text + " " + label if label else text


def view_for(
    sessions, now_ms, last_input_ms, link_up, grace_ms=GRACE_MS, locked=False
):
    """Melyik nezet legyen: "offline", "locked", "sessions" vagy "panel".

    A sorrend szandekos: kapcsolat nelkul nincs mit mutatni a sessionokrol; ha a
    gep zarolt, semmilyen munka-informacio nem lathato (meg akkor sem, ha valaki
    var); ha valaki var, az minden mas ele megy; es a friss bevitel megtartja a
    session-nezetet, hogy legyen ido megnezni, mire kattintottal.

    A zar-jelzes az ugynoktol erkezik minden pillanatkeppel. Kapcsolat nelkul
    ezert elavult, es nem bizunk benne - az "offline" nezet ugyis csak orat es
    idojarast mutat, tehat nem szivarog ki semmi.
    """
    if not link_up:
        return "offline"
    if locked:
        return "locked"
    if anyone_waiting(sessions):
        return "sessions"
    if now_ms - last_input_ms < grace_ms:
        return "sessions"
    return "panel"


# --- Gyuru-feliratok -----------------------------------------------------------
#
# A gyuru szegmensei szinnel mutatjak az allapotot, de nem mondjak meg, MELYIK
# session melyik. Forgatas nelkul is lathato legyen - ehhez kell egy nagyon
# rovid, egyertelmu rovidites.
#
# A `cc-` a felhasznalo sajat rovidítese a "claude code"-ra, minden projektjen
# rajta van - semmit nem kulonboztet meg, ezert fixen levagjuk.

LABEL_PREFIX = "cc-"
LABEL_MAX = 4
_LABEL_SEPARATORS = "-_. "


def _label_tokens(name):
    tokens = []
    current = ""
    for ch in name:
        if ch in _LABEL_SEPARATORS:
            if current:
                tokens.append(current)
                current = ""
        else:
            current += ch
    if current:
        tokens.append(current)
    return tokens


def short_label(name, max_len=LABEL_MAX):
    """Egy session nevebol max `max_len` karakteres gyuru-felirat."""
    if not name:
        return ""
    text = name.strip()
    if text[:len(LABEL_PREFIX)].lower() == LABEL_PREFIX:
        text = text[len(LABEL_PREFIX):]
    tokens = _label_tokens(text)
    if not tokens:
        return text[:max_len]
    return tokens[0][:max_len]


def _second_initial(name):
    """A masodik nevtag kezdobetuje - ez kulonbozteti meg az utkozo neveket."""
    text = name.strip() if name else ""
    if text[:len(LABEL_PREFIX)].lower() == LABEL_PREFIX:
        text = text[len(LABEL_PREFIX):]
    tokens = _label_tokens(text)
    return tokens[1][0] if len(tokens) > 1 else ""


def short_labels(names, max_len=LABEL_MAX):
    """Feliratok egy session-listahoz, garantaltan kulonbozoek.

    Utkozesnel eloszor a masodik nevtag kezdobetuje kerul a vegere
    (`supp` -> `supm`), ha az sem eleg, egy sorszam. A sorrend determinisztikus:
    ugyanaz a lista mindig ugyanazt adja.
    """
    result = []
    taken = set()
    for name in names or []:
        label = short_label(name, max_len)
        if not label:
            label = "?"
        if label in taken:
            extra = _second_initial(name)
            if extra and (label[:max_len - 1] + extra) not in taken:
                label = label[:max_len - 1] + extra
        counter = 2
        while label in taken and counter < 10:
            label = label[:max_len - 1] + str(counter)
            counter += 1
        taken.add(label)
        result.append(label)
    return result


#: Ennyi ezredmasodpercenkent allitjuk ujra az eszkoz orajat a gep idejere.
CLOCK_SYNC_INTERVAL_MS = 10 * 60 * 1000


def should_sync_clock(clock_set, elapsed_ms, interval_ms=CLOCK_SYNC_INTERVAL_MS):
    """Kell-e (ujra) beallitani az eszkoz orajat.

    Ket dolog vezetett ide:

    1. Az RTC-t eddig CSAK az elso kapcsolatfelvetelkor allitottuk be, es
       elesben 16 percet kesett - egy rossz elso beallitast semmi nem hozott
       helyre.
    2. Az elso javitas a ket idot HASONLITOTTA ossze (`should_set_clock`), es
       elesben MINDEN korben ujraallitotta az orat: az eszkoz `time.time()`-ja
       es az altalunk kuldott ertek nem ugyanabban a viszonyitasi rendszerben
       van. A kulonbseget nem mertuk meg, ezert nem is epitunk ra.

    Ez a valtozat nem hasonlit, csak idozit: ha meg sosem allitottuk be, vagy
    letelt az intervallum, szinkronizalunk. A gep ideje minden pillanatkepben
    megerkezik, tehat halozati idoforras nem kell.
    """
    if not clock_set:
        return True
    if elapsed_ms is None:
        return False
    try:
        return elapsed_ms >= interval_ms
    except TypeError:
        return False


#: A kozepen mutatott session-nev legfeljebb ennyi karakter.
#:
#: Merve a fotokon: a gyuru-feliratok a vizszintes tengelyen a kepernyo szelso
#: ~28 pixeles savjaiban ulnek, a kozepso nev pedig kozepre igazitva ~10 px /
#: karakter. 12 karakter az, ami meg elfér kettejuk kozott - a hosszabb nev
#: levagta a bal es jobb oldali feliratot (`LL`, `er`).
CENTER_NAME_MAX = 12


def center_name(name, max_len=CENTER_NAME_MAX):
    """A kozepen mutatott nev: `cc-` elotag nelkul, hosszban korlatozva.

    A `cc-` levagasa ugyanaz, mint a gyuru-feliratoknál (`short_label`): a
    felhasznalo sajat rovidítese a "claude code"-ra, minden projektjen rajta van,
    tehat semmit nem kulonboztet meg - viszont harom ertekes karaktert elvesz.
    """
    if not name:
        return ""
    text = name.strip()
    if text[:len(LABEL_PREFIX)].lower() == LABEL_PREFIX:
        text = text[len(LABEL_PREFIX):]
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "."
