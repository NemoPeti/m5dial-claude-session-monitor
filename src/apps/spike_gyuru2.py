# SPDX-License-Identifier: MIT
"""Spike 2: ugyanaz a szegmentalt gyuru, de M5GFX-bol (M5.Lcd.fillArc), LVGL nelkul.

Osszehasonlitasi alap a spike_gyuru.py m5ui/LVGL meresehez. Ugyanazokat a
szamokat irja ki, hogy a ket ut egymas melle tehetó legyen:

  - N szegmens felrajzolasanak ideje
  - egy szegmens ujraszinezesenek ideje (ez fut elesben masodpercenkent)
  - a kivalasztas leptetesenek ideje (vastagabb szegmens)

Kezzel ellenorzendo a kijelzon: latszik-e N kulon szegmens, van-e kozottuk res,
es lathatoan vastagabb-e a kivalasztott.
"""

import gc
import time

import M5
from M5 import *  # noqa: F403
from hardware import Rotary

CX = 120
CY = 120
R_OUT = 118
R_IN = 102
R_IN_SEL = 90  # a kivalasztott szegmens befele vastagszik
GAP_DEG = 6

C_BLOCKED = 0xE53935  # piros
C_WAITING = 0xFFA000  # borostyan
C_BUSY = 0x43A047     # zold
C_IDLE = 0x546E7A     # szurke
C_BG = 0x101418

STATES = (C_BUSY, C_WAITING, C_BLOCKED, C_IDLE)

N = 8
colors = []
rotary = None
selection = 0
label = None


def _segment_angles(i, count):
    """M5GFX-szog: 0 fok a 3 oranal, oramutato jarasa szerint no."""
    span = 360.0 / count
    return int(i * span + GAP_DEG / 2), int((i + 1) * span - GAP_DEG / 2)


def _draw_segment(i, count, color, selected=False):
    start, end = _segment_angles(i, count)
    r_in = R_IN_SEL if selected else R_IN
    # Eloszor a teljes savot letoroljuk, kulonben a vastagbol vekonyra valtas
    # otthagyja a regi belso szelet.
    M5.Lcd.fillArc(CX, CY, R_IN_SEL, R_OUT, start, end, C_BG)
    M5.Lcd.fillArc(CX, CY, r_in, R_OUT, start, end, color)


def _draw_ring(count):
    t0 = time.ticks_ms()
    for i in range(count):
        _draw_segment(i, count, colors[i], selected=(i == selection))
    return time.ticks_diff(time.ticks_ms(), t0)


def _select(index):
    global selection
    index %= N
    if index == selection:
        return 0
    t0 = time.ticks_ms()
    old = selection
    selection = index
    _draw_segment(old, N, colors[old], selected=False)
    _draw_segment(index, N, colors[index], selected=True)
    label.setText("session {}".format(index + 1))
    return time.ticks_diff(time.ticks_ms(), t0)


def setup():
    global colors, rotary, label

    M5.begin()
    Widgets.fillScreen(C_BG)  # noqa: F405
    colors = [STATES[i % len(STATES)] for i in range(N)]

    label = Widgets.Label(  # noqa: F405
        "spike2", 70, 110, 1.0, 0xFFFFFF, C_BG, Widgets.FONTS.DejaVu18  # noqa: F405
    )

    gc.collect()
    free_before = gc.mem_free()

    for count in (8, 16):
        colors = [STATES[i % len(STATES)] for i in range(count)]
        ms = _draw_ring(count)
        print("spike2: N={} rajzolas {} ms".format(count, ms))

    colors = [STATES[i % len(STATES)] for i in range(N)]
    Widgets.fillScreen(C_BG)  # noqa: F405
    label = Widgets.Label(  # noqa: F405
        "spike2", 70, 110, 1.0, 0xFFFFFF, C_BG, Widgets.FONTS.DejaVu18  # noqa: F405
    )
    ms = _draw_ring(N)
    print("spike2: vissza N=8, rajzolas {} ms".format(ms))

    gc.collect()
    print("spike2: a gyuru {} bajtot hasznal, szabad: {}".format(
        free_before - gc.mem_free(), gc.mem_free()))

    # Egy szegmens ujraszinezese - ez a muvelet fut elesben masodpercenkent.
    t0 = time.ticks_ms()
    _draw_segment(0, N, C_BLOCKED, selected=(selection == 0))
    print("spike2: EGY szegmens ujraszinezese {} ms".format(
        time.ticks_diff(time.ticks_ms(), t0)))

    t0 = time.ticks_ms()
    for i in range(N):
        _draw_segment(i, N, STATES[(i + 1) % len(STATES)], selected=(i == selection))
    print("spike2: mind a 8 szegmens ujraszinezese {} ms".format(
        time.ticks_diff(time.ticks_ms(), t0)))

    print("spike2: kivalasztas leptetese {} ms".format(_select(1)))

    rotary = Rotary()
    print("spike2: kesz, forgasd - a kivalasztott szegmens vastagabb")


def loop():
    M5.update()
    if rotary.get_rotary_status():
        delta = rotary.get_rotary_increments()
        if delta:
            ms = _select(selection + delta)
            print("spike2: leptetes -> {} ms".format(ms))
    time.sleep_ms(10)


if __name__ == "__main__":
    setup()
    while True:
        loop()
