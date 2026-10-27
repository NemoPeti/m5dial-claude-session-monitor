# SPDX-License-Identifier: MIT
"""M5Stack Dial (v1.1) - MicroPython/UIFlow2 indulo demo.

Mit mutat be:
  - forgo enkoder (hardware.Rotary, GPIO41/40) olvasasa,
  - BtnA (a keszulek elulso gombja, GPIO42) callback-kel,
  - erintokijelzo (M5.Touch) lekerdezese,
  - hangjelzes (M5.Speaker) es rajzolas a 240x240-es kerek kijelzore.
"""

import M5
from M5 import *
from hardware import Rotary

BG = 0x101418
FG = 0xFFA000
CENTER = 120  # a 240x240-es kerek kijelzo kozepe

label_value = None
label_hint = None
rotary = None


def btnA_wasClicked_event(state):  # noqa: N802
    """A Dial elulso gombja: nullazza a szamlalot."""
    rotary.reset_rotary_value()
    label_value.setText("0")
    M5.Speaker.tone(4000, 60)


def setup():
    global label_value, label_hint, rotary

    M5.begin()
    M5.Speaker.setVolume(64)
    Widgets.fillScreen(BG)

    # A kerek kijelzon a sarkok nem latszanak - mindent kozepre igazitunk.
    label_value = Widgets.Label(
        "0", CENTER - 40, CENTER - 36, 1.0, FG, BG, Widgets.FONTS.DejaVu72
    )
    label_hint = Widgets.Label(
        "forgasd / erintsd", CENTER - 62, CENTER + 50, 1.0, 0x8899AA, BG, Widgets.FONTS.DejaVu18
    )

    BtnA.setCallback(type=BtnA.CB_TYPE.WAS_CLICKED, cb=btnA_wasClicked_event)

    # A hardware.Rotary fixen RANGE_UNBOUNDED modot hasznal, ezert a min_val/max_val
    # parameterek tetlenek - az ertek mindig szabadon szamol mindket iranyba.
    rotary = Rotary()

    print("M5Dial demo elindult")


def loop():
    M5.update()

    if rotary.get_rotary_status():
        value = rotary.get_rotary_value()
        label_value.setText(str(value))
        M5.Speaker.tone(6500, 15)
        print("rotary =", value)

    if M5.Touch.getCount() > 0:
        detail = M5.Touch.getDetail(0)
        if not detail[9]:  # index 9 = isHolding
            label_hint.setText("x=%d y=%d" % (M5.Touch.getX(), M5.Touch.getY()))


if __name__ == "__main__":
    try:
        setup()
        while True:
            loop()
    except (Exception, KeyboardInterrupt) as e:
        try:
            from utility import print_error_msg

            print_error_msg(e)
        except ImportError:
            print("please update to latest firmware")
