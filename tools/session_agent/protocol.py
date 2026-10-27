"""Soronkenti JSON vezetekprotokoll a PC-oldali ugynok es a Dial kozott.

EZ A FAJL MINDKET OLDALON FUT: a PC-n CPython 3.12 alatt, es *valtoztatas
nelkul* felmasolva a M5Stack Dialra, ahol MicroPython futtatja. Ezert:

- KIZAROLAG szabvany konyvtar, es abbol is csak amit a MicroPython ismer:
  `json` -- semmi mas. Tilos: `typing`, `dataclasses`, `enum`, `re`, `logging`.
- Nincs f-string; mindenhol `"{}".format(...)`.
- Nincs tipusannotacio a fuggvenyfejlecekben.
- A memoriafoglalas maradjon szereny -- ez egy 8 MB flash-es, PSRAM nelkuli
  mikrokontrolleren fut le masodpercenkent.

Ne "modernizald" ezt a fajlt f-stringgel vagy annotacioval -- attol a Dialon
elszall a program.

Vezetekformak (2026-09-09-dial-session-monitor-design.md 4.4. szakasz):

    PC -> Dial:  {"t":"s","seq":41,"cfg":{"mute":false,"volume":2},
                  "sessions":[{"id":"2cd028e8","n":"...","st":"waiting"}],
                  "act":"2cd028e8"}
    Dial -> PC:  {"t":"ack","id":"2cd028e8"}
                 {"t":"focus","id":"2cd028e8"}
                 {"t":"vol","v":2,"m":1}   (m = nemitva; hianyzo m = nem)

Minden sor `\n`-nel zarul es UTF-8 kodolasu.
"""

import json

_MAX_BUFFER = 4096


def encode_snapshot(seq, cfg, sessions, now=None, wx=None, lock=None,
                    active=None):
    """PC -> Dial: egy sor, \n-nel lezarva.

    seq: novekvo sorszam (szivveres/eldobott sorok eszlelesehez).
    cfg: {"mute": bool, "volume": 0..3} -- a globalis nemitas/hangero.
    sessions: lista {"id", "n", "st"} szotarakbol.
    now: helyi ido masodpercben (a Dial ebbol allitja be az RTC-jet, hogy
         kapcsolat nelkul is jarjon az oraja).
    wx: {"t": fok, "c": rovid felirat} vagy None -- ha nincs, a mezo kimarad,
        es a Dial egyszeruen elhagyja az idojaras-sort.
    lock: "lock" | "saver" | "idle" | None -- miert zarolt a gep. Ha nincs zar,
        a mezo kimarad, es egy regebbi Dial-program valtozatlanul mukodik.
    active: annak a sessionnek az azonositoja, amelyiknek a Warp-tabja epp
        elol van a gepen, vagy None. Csak az azonosito megy at (a nev mar ott
        van a `sessions`-ben), hogy a sor rovid maradjon; ha nincs, kimarad.

    A `now` es a `wx` szandekosan csak akkor kerul bele, ha van ertelmes ertek:
    igy a sor rovidebb marad, es egy regebbi Dial-program is elolvassa.
    """
    obj = {"t": "s", "seq": seq, "cfg": cfg, "sessions": sessions}
    if now is not None:
        obj["now"] = now
    if wx:
        obj["wx"] = wx
    if lock:
        obj["lk"] = lock
    if active:
        obj["act"] = active
    return json.dumps(obj) + "\n"


def encode_event(kind, **fields):
    """Dial -> PC: egy sor, \n-nel lezarva. kind: "ack" | "focus" | "vol"."""
    obj = {"t": kind}
    for key in fields:
        obj[key] = fields[key]
    return json.dumps(obj) + "\n"


def decode_line(line):
    """Egy beerkezett sor -> dict, vagy None ha ertelmezhetetlen.

    Sose dob kivetelt: ez a fuggveny a fo vedelem az ellen, hogy egy
    megserult bajt a soros vonalon megolje a Dial programjat.
    """
    if line is None:
        return None
    stripped = line.strip()
    if not stripped:
        return None
    try:
        obj = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    if "t" not in obj:
        return None
    return obj


class LineReader:
    """Bajtfolyamot sorokra bont. A soros porton a sorok tordelve erkeznek.

    A `feed` minden hivasnal a chunkban levo osszes ujonnan lezart, ervenyes
    sort dekodolt uzenetkent adja vissza (a None-okat -- azaz a szemet
    sorokat -- eldobva). A felbevagott vegzodes a kovetkezo hivasig
    pufferben marad.
    """

    def __init__(self):
        self._buffer = ""

    def feed(self, chunk):
        """chunk: bytes vagy str. Visszaad: dekodolt uzenetek listaja."""
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8", "ignore")
        self._buffer += chunk

        messages = []
        while True:
            idx = self._buffer.find("\n")
            if idx == -1:
                break
            line = self._buffer[:idx]
            self._buffer = self._buffer[idx + 1:]
            decoded = decode_line(line)
            if decoded is not None:
                messages.append(decoded)

        if len(self._buffer) > _MAX_BUFFER:
            # nincs ujsor a hatarido/meretkoron belul -- eldobjuk, nehogy
            # a puffer vegtelenul nojon egy soha le nem zaruló soron
            self._buffer = ""

        return messages
