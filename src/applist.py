# SPDX-License-Identifier: MIT
"""A launcher tiszta logikaja - se M5, se hardver, ezert asztali Pythonon is fut
es tesztelheto. A launcher.py ezt importalja."""

APPS_DIR = "/flash/apps"


def move_selection(selection, delta, count):
    """Lepteti a kivalasztast, korbeerve mindket iranyban.

    Ures listanal 0-t ad vissza ahelyett, hogy nullaval osztana."""
    if count <= 0:
        return 0
    return (selection + delta) % count


def visible_window(selection, count, rows):
    """A kirajzolando szelet (start, end) felzart indexekkel.

    A kivalasztott elem mindig a szeleten belul van, es a szelet sosem log tul
    a lista veget."""
    if count <= 0 or rows <= 0:
        return (0, 0)
    if count <= rows:
        return (0, count)

    # A kivalasztottat lehetoleg kozepre tesszuk, aztan a listahatarokhoz zarjuk.
    start = selection - rows // 2
    if start < 0:
        start = 0
    elif start + rows > count:
        start = count - rows
    return (start, start + rows)


def list_app_files(names):
    """A .py fajlok abc-rendben, a nem-python fajlokat kihagyva."""
    return sorted(n for n in names if n.endswith(".py"))


def display_name(filename):
    """A listaban mutatott nev: kiterjesztes nelkul."""
    return filename[:-3] if filename.endswith(".py") else filename
