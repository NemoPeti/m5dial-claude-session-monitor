# SPDX-License-Identifier: MIT
"""M5Dial app-launcher.

A /flash/apps/ mappa .py fajljait listazza. Forgatva valasztasz, kattintasra
elindul, hosszan nyomva visszajossz ide.

Ket dolgot csinal maskepp, mint a kezenfekvo megoldas - mindketto meresbol:

1. Az appot NEM helyben (execfile-lal) inditja a listabol, hanem felir egy jelzot
   es soft resetel. Az app igy TELJESEN tiszta gepallapotot kap. A helyben inditas
   elesben megbukott: az app szamlaloja fixen 0-t mutatott, mert a launcher altal
   mar hasznalt hardver (enkoder-megszakitasok, M5 allapot) belezavart. Onallo
   futtataskor ugyanaz az app hibatlanul mukodott.

2. A "vissza" gesztust nem az M5 gombkezelojere bizza, hanem egy idozito olvassa
   kozvetlenul a GPIO42-t. Indok: az app sajat M5.begin()-t hiv, ami torli a
   korabbi callbackeket. Az idozitot MODUL-SZINTU valtozoban kell tartani,
   kulonben a MicroPython begyujti es nemán leall.
"""

import os
import sys
import time

import machine
import micropython
import M5
from machine import Pin, Timer
from M5 import *  # noqa: F403
from hardware import Rotary

from applist import APPS_DIR, display_name, list_app_files, move_selection, visible_window

BG = 0x101418
FG = 0xFFFFFF
DIM = 0x6C7A89
SEL = 0xFFA000

CENTER_X = 120
ROWS = 5
ROW_H = 30
TOP_Y = 120 - (ROWS * ROW_H) // 2

LONG_PRESS_MS = 1500
MARKER = "/flash/.launch"

apps = []
selection = 0
rotary = None
row_labels = []
title = None
_press_started = None
_pending_launch = None  # a fociklus inditja el; callbackbol nem lehet resetelni

# --- Globalis "vissza" gesztus -------------------------------------------------
#
# Merve: a GPIO42 a gomb, aktiv alacsony (nyomva = 0), es pontosan egyutt mozog a
# BtnA.isPressed()-del.

_BTN_PIN = 42
_WATCH_MS = 50
_btn_pin = None
_held_ms = 0
_watch_timer = None  # FONTOS: modul-szintu hivatkozas, kulonben a GC leallitja


def _watchdog(_timer):
    global _held_ms
    if _btn_pin.value() == 0:
        _held_ms += _WATCH_MS
        if _held_ms >= LONG_PRESS_MS:
            _held_ms = 0
            # Hardveres reset, NEM soft_reset: az utobbi SystemExit-et dob, amit a
            # timer-callback kerete elnyel (ugyanaz a hiba, mint a gomb-callbacknel).
            # A jelzot nem kell torolni - a boot elso dolga ugyis torli.
            machine.reset()
    else:
        _held_ms = 0


def _start_watchdog():
    global _btn_pin, _watch_timer
    _btn_pin = Pin(_BTN_PIN, Pin.IN)
    _watch_timer = Timer(0)
    _watch_timer.init(period=_WATCH_MS, mode=Timer.PERIODIC, callback=_watchdog)


# --- Inditasi jelzo ------------------------------------------------------------


def _read_marker():
    try:
        with open(MARKER) as f:
            return f.read().strip()
    except OSError:
        return None


def _write_marker(name):
    with open(MARKER, "w") as f:
        f.write(name)


def _clear_marker():
    try:
        os.remove(MARKER)
    except OSError:
        pass


# --- Lista ---------------------------------------------------------------------


def _read_apps():
    try:
        return list_app_files(os.listdir(APPS_DIR))
    except OSError:
        return []


def _draw():
    start, end = visible_window(selection, len(apps), ROWS)
    window = apps[start:end]

    for i, label in enumerate(row_labels):
        if i < len(window):
            name = display_name(window[i])
            is_sel = (start + i) == selection
            label.setText(("> " + name) if is_sel else ("  " + name))
            label.setColor(SEL if is_sel else DIM, BG)
        else:
            label.setText("")
            label.setColor(BG, BG)


def btnA_wasPressed_event(state):  # noqa: N802
    global _press_started
    _press_started = time.ticks_ms()


def btnA_wasReleased_event(state):  # noqa: N802
    """Rovid kattintas: feljegyzi a valasztast es ujraindul, hogy az app tiszta
    gepallapotot kapjon."""
    global _press_started
    if _press_started is None:
        return
    held = time.ticks_diff(time.ticks_ms(), _press_started)
    _press_started = None
    if held < LONG_PRESS_MS and apps:
        global _pending_launch
        M5.Speaker.tone(5000, 40)
        # A resetet NEM itt vegezzuk: a soft_reset() SystemExit-et dob, es azt az
        # M5 callback-kerete elnyeli (elesben merve: "SystemExit" traceback minden
        # kattintasra, az app el sem indult). A fociklus vegzi el, callbacken kivul.
        _pending_launch = apps[selection]


def show_list():
    global apps, rotary, row_labels, title

    M5.begin()
    M5.Speaker.setVolume(64)
    Widgets.fillScreen(BG)  # noqa: F405

    apps = _read_apps()

    title = Widgets.Label(  # noqa: F405
        "apps", CENTER_X - 26, 26, 1.0, FG, BG, Widgets.FONTS.DejaVu18  # noqa: F405
    )
    row_labels = [
        Widgets.Label(  # noqa: F405
            "", 40, TOP_Y + i * ROW_H, 1.0, DIM, BG, Widgets.FONTS.DejaVu18  # noqa: F405
        )
        for i in range(ROWS)
    ]
    if not apps:
        title.setText("nincs app")

    BtnA.setCallback(type=BtnA.CB_TYPE.WAS_PRESSED, cb=btnA_wasPressed_event)  # noqa: F405
    BtnA.setCallback(type=BtnA.CB_TYPE.WAS_RELEASED, cb=btnA_wasReleased_event)  # noqa: F405

    rotary = Rotary()
    _draw()
    print("launcher: lista,", len(apps), "app")

    while True:
        M5.update()
        if _pending_launch:
            time.sleep_ms(120)
            _write_marker(_pending_launch)
            machine.soft_reset()
        if rotary.get_rotary_status():
            delta = rotary.get_rotary_increments()
            if delta:
                _set_selection(move_selection(selection, delta, len(apps)))
        # A sleep NEM elhagyhato: alvas nelkuli szoros ciklus kieheztet a
        # USB-CDC REPL-t, es az mpremote nem tud betorni az eszkozre - a gyari
        # keretrendszer is ezert hasznal await asyncio.sleep_ms(10)-et.
        time.sleep_ms(10)


def _set_selection(value):
    global selection
    selection = value
    M5.Speaker.tone(6500, 12)
    _draw()


def run_app(name):
    """Az app a lehető legtisztabb allapotot kapja: ez a boot utani elso dolog,
    a launcher listaja el sem indult."""
    path = APPS_DIR + "/" + name
    print("launcher: indul", path)
    _execfile = getattr(__import__("builtins"), "execfile")
    try:
        _execfile(path, {"__name__": "__main__"})
    except Exception as e:
        # **SOHA ne legyen ebbol `BaseException`.** A `machine.soft_reset()` ebben
        # a firmware-ben `SystemExit`-tel dolgozik, es a soft reset pontosan attol
        # tortenik meg, hogy ez a kivetel ELMEGY a legfelso szintig. Egy
        # `except BaseException` elnyeli, es akkor a reset elmarad: elesben ettol
        # bukott vegig az egesz lanc a REPL-ig, piros hibakeppel.
        print("launcher: az app hibaval allt le:", e)
        sys.print_exception(e)
        try:
            from utility import print_error_msg

            print_error_msg(e)
        except ImportError:
            pass
        time.sleep(3)
    finally:
        # Ha az app letiltotta a Ctrl-C-t (kbd_intr(-1)), a launcher visszaallitja,
        # kulonben az eszkoz sukétan maradna a lista mellett is.
        micropython.kbd_intr(3)
    # Ha az app magatol visszatert vagy elszallt, a listaval folytatjuk.
    machine.soft_reset()


def main():
    # A jelzot MINDIG toroljuk, mielott barmit inditanank: ha az app induláskor
    # elszall, a kovetkezo boot a listat hozza, nem vegtelen ujrainditast.
    wanted = _read_marker()
    _clear_marker()

    _start_watchdog()

    if wanted and wanted in _read_apps():
        run_app(wanted)
    else:
        show_list()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Az `mpremote` Ctrl-C-vel tor be a futo programba: ez a fejlesztoi kor
        # NORMALIS lepese, nem hiba. A korabbi valtozat piros hibakepet rajzolt
        # ilyenkor, es a felhasznalo joggal hitte osszeomlasnak - minden egyes
        # telepites utan ott maradt a kepernyon.
        micropython.kbd_intr(3)
        Widgets.fillScreen(0x000000)  # noqa: F405
        print("launcher: megszakitva - a REPL vette at")
    except Exception as e:
        # Itt sem `BaseException`: a `SystemExit`-nek at kell mennie, kulonben a
        # soft reset nem tortenik meg (lasd a `run_app` megjegyzeset).
        # Ide mar csak akkor jutunk, ha maga a launcher szallt el. A soros
        # naplo azert kell, mert a piros hibakep az elso ujraindulassal eltunik.
        print("launcher: MAGA A LAUNCHER ALLT LE HIBAVAL")
        sys.print_exception(e)
        micropython.kbd_intr(3)
        try:
            from utility import print_error_msg

            print_error_msg(e)
        except ImportError:
            print("please update to latest firmware")
