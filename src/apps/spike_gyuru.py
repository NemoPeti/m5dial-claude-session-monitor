# SPDX-License-Identifier: MIT
"""Spike: kirajzolhato-e a szegmentalt session-gyuru m5ui.M5Arc-bol?

A terv (docs/superpowers/specs/2026-09-09-dial-session-monitor-design.md, 4.8)
ezt megmeretlen kockazatkent tartja nyilvan: "hogy N szegmens rajzolhato-e
elfogadhatoan m5ui.M5Arc peldanyokbol, az nincs megmerve".

Ez az app megmeri, es a szamokat a soros portra irja:

  - N szegmens felepitesenek ideje es memoriaigenye (N = 8, majd 16)
  - egy szegmens atszinezesenek ideje (ez fut masodpercenkent elesben)
  - a kivalasztas leptetesenek ideje (vastagabb szegmens)

Kezzel ellenorzendo a kijelzon: latszik-e N kulon szegmens, van-e kozottuk res,
es lathatoan vastagabb-e a kivalasztott.
"""

import gc
import time

import lvgl as lv
import m5ui
import M5
from hardware import Rotary

# A gyuru geometriaja. A kijelzo kerek 240x240, a kozeppont (120,120).
SIZE = 236
RING_W = 16
RING_W_SEL = 28
GAP_DEG = 6

# Allapotszinek a terv 4.8 pontjabol.
C_BLOCKED = 0xE53935  # piros
C_WAITING = 0xFFA000  # borostyan
C_BUSY = 0x43A047     # zold
C_IDLE = 0x546E7A     # szurke
C_BG = 0x101418

STATES = (C_BUSY, C_WAITING, C_BLOCKED, C_IDLE)

page = None
segments = []
label = None
rotary = None
selection = 0


def _segment_angles(i, count):
    """LVGL-szog: 0 fok a 3 oranal, oramutato jarasa szerint no."""
    span = 360.0 / count
    start = i * span + GAP_DEG / 2
    end = (i + 1) * span - GAP_DEG / 2
    return int(start), int(end)


def _make_segment(parent, start, end, color, width):
    arc = m5ui.M5Arc(
        x=(240 - SIZE) // 2,
        y=(240 - SIZE) // 2,
        w=SIZE,
        h=SIZE,
        value=100,
        min_value=0,
        max_value=100,
        rotation=0,
        bg_c=color,
        bg_c_indicator=color,
        bg_c_knob=color,
        parent=parent,
    )
    # A szegmens = az ivnek csak egy darabja. A hatter- es a mutato-iv ugyanazt
    # a szoget kapja, igy egyetlen tomor szinfoltnak latszik.
    arc.set_bg_angles(start, end)
    arc.set_angles(start, end)
    # A gomb (knob) es a kattinthatosag itt csak zavarna.
    arc.remove_style(None, lv.PART.KNOB)
    arc.remove_flag(lv.obj.FLAG.CLICKABLE)
    _set_width(arc, width)
    return arc


def _set_width(arc, width):
    arc.set_style_arc_width(width, lv.PART.MAIN)
    arc.set_style_arc_width(width, lv.PART.INDICATOR)


def _set_color(arc, color):
    c = lv.color_hex(color)
    arc.set_style_arc_color(c, lv.PART.MAIN)
    arc.set_style_arc_color(c, lv.PART.INDICATOR)


def _build_ring(count):
    """Felepiti a gyurut, es visszaadja (epitesi ms, felhasznalt bajt)."""
    global segments
    for arc in segments:
        arc.delete()
    segments = []
    gc.collect()

    free_before = gc.mem_free()
    t0 = time.ticks_ms()
    for i in range(count):
        start, end = _segment_angles(i, count)
        segments.append(
            _make_segment(page, start, end, STATES[i % len(STATES)], RING_W)
        )
    build_ms = time.ticks_diff(time.ticks_ms(), t0)
    gc.collect()
    used = free_before - gc.mem_free()
    return build_ms, used


def _select(index):
    global selection
    if not segments:
        return 0
    index %= len(segments)
    t0 = time.ticks_ms()
    _set_width(segments[selection], RING_W)
    _set_width(segments[index], RING_W_SEL)
    label.set_text("session {}".format(index + 1))
    selection = index
    return time.ticks_diff(time.ticks_ms(), t0)


def setup():
    global page, label, rotary

    M5.begin()
    m5ui.init()
    page = m5ui.M5Page(bg_c=C_BG)

    label = m5ui.M5Label(
        "spike",
        x=70,
        y=110,
        text_c=0xFFFFFF,
        bg_c=C_BG,
        bg_opa=0,
        font=lv.font_montserrat_24,
        parent=page,
    )
    page.screen_load()

    for count in (8, 16):
        build_ms, used = _build_ring(count)
        print("spike: N={} epites {} ms, {} bajt".format(count, build_ms, used))

    # A merest a 8 szegmenses valtozattal folytatjuk, az a realis eset.
    build_ms, used = _build_ring(8)
    print("spike: vissza N=8, epites {} ms, {} bajt".format(build_ms, used))
    print("spike: szabad memoria a gyuruvel: {} bajt".format(gc.mem_free()))

    # Egy szegmens atszinezese - ez a muvelet fut elesben masodpercenkent.
    t0 = time.ticks_ms()
    for i, arc in enumerate(segments):
        _set_color(arc, STATES[(i + 1) % len(STATES)])
    recolor_ms = time.ticks_diff(time.ticks_ms(), t0)
    print("spike: mind a 8 szegmens atszinezese {} ms".format(recolor_ms))

    print("spike: kivalasztas leptetese {} ms".format(_select(0)))

    rotary = Rotary()
    print("spike: kesz, forgasd - a kivalasztott szegmens vastagabb")


def loop():
    M5.update()
    if rotary.get_rotary_status():
        delta = rotary.get_rotary_increments()
        if delta:
            ms = _select(selection + delta)
            print("spike: leptetes {} -> {} ms".format(selection, ms))
    time.sleep_ms(10)


if __name__ == "__main__":
    setup()
    while True:
        loop()
