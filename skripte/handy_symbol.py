#!/usr/bin/env python3
"""Zeichnet das Symbol der Handy-App "WoazeWeather": eine Sonne mit einem WW darin.

Die Bilddateien liegen fertig im Repo (docs/handy/). Dieses Skript wird nur
gebraucht, wenn das Symbol geaendert werden soll. Es braucht Pillow
(``pip install pillow``) und wird NICHT vom Daten-Workflow ausgefuehrt.

    python3 skripte/handy_symbol.py

Erzeugt in docs/handy/:
  symbol-192.png            normales Symbol (abgerundetes Quadrat)
  symbol-512.png            dasselbe gross
  symbol-maskable-512.png   randlos, damit Android es beliebig zuschneiden kann
                            (alles Wichtige liegt im mittleren Kreis, 80 %)
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

ZIEL = Path(__file__).resolve().parent.parent / "docs" / "handy"

HIMMEL = (18, 50, 74)        # dunkles Blau (Hintergrund)
SONNE = (245, 185, 33)       # warmes Gelb (Scheibe und Strahlen)
SCHRIFT = (18, 50, 74)       # WW in der Hintergrundfarbe
GROSS = 1024                 # gezeichnet wird gross und dann verkleinert (glatte Kanten)


def _strich(zeichner, p, q, dicke, farbe):
    """Ein gerader Strich mit runden Enden (Rechteck plus zwei Kreise): Kanten bleiben
    gleich dick, auch schraeg gezeichnet."""
    (x1, y1), (x2, y2) = p, q
    laenge = math.hypot(x2 - x1, y2 - y1) or 1
    nx, ny = -(y2 - y1) / laenge * dicke / 2, (x2 - x1) / laenge * dicke / 2
    zeichner.polygon([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)], fill=farbe)
    r = dicke / 2
    for x, y in (p, q):
        zeichner.ellipse((x - r, y - r, x + r, y + r), fill=farbe)


def _w(zeichner, x0, y0, breite, hoehe, dicke, farbe):
    """Ein W aus vier Strichen mit runden Ecken."""
    punkte = [(x0, y0), (x0 + breite * 0.25, y0 + hoehe), (x0 + breite * 0.5, y0 + hoehe * 0.32),
              (x0 + breite * 0.75, y0 + hoehe), (x0 + breite, y0)]
    for a, b in zip(punkte, punkte[1:]):
        _strich(zeichner, a, b, dicke, farbe)


def sonne_zeichnen(mit_rand):
    """Liefert das grosse Bild. mit_rand=True: abgerundetes Quadrat, Ecken durchsichtig."""
    bild = Image.new("RGBA", (GROSS, GROSS), (0, 0, 0, 0))
    z = ImageDraw.Draw(bild)
    if mit_rand:
        z.rounded_rectangle((0, 0, GROSS - 1, GROSS - 1), radius=int(GROSS * 0.22), fill=HIMMEL)
    else:
        z.rectangle((0, 0, GROSS, GROSS), fill=HIMMEL)
    m = GROSS / 2
    k = GROSS / 512                                # alle Masse unten sind fuer 512 px gedacht
    # Strahlen: zwoelf kurze, dicke Striche mit runden Enden
    for i in range(12):
        a = i * math.pi / 6
        r1, r2 = 148 * k, 190 * k
        _strich(z, (m + math.cos(a) * r1, m + math.sin(a) * r1), (m + math.cos(a) * r2, m + math.sin(a) * r2),
                24 * k, SONNE)
    # Scheibe
    r = 118 * k
    z.ellipse((m - r, m - r, m + r, m + r), fill=SONNE)
    # WW: zwei W nebeneinander, mittig in der Scheibe
    b, h, d, luecke = 88 * k, 84 * k, 18 * k, 6 * k
    gesamt = 2 * b + luecke
    x0, y0 = m - gesamt / 2, m - h / 2
    _w(z, x0, y0, b, h, d, SCHRIFT)
    _w(z, x0 + b + luecke, y0, b, h, d, SCHRIFT)
    return bild


def main():
    ZIEL.mkdir(parents=True, exist_ok=True)
    normal, randlos = sonne_zeichnen(True), sonne_zeichnen(False)
    for name, bild, seite in (("symbol-192.png", normal, 192), ("symbol-512.png", normal, 512),
                              ("symbol-maskable-512.png", randlos, 512)):
        bild.resize((seite, seite), Image.LANCZOS).save(ZIEL / name, optimize=True)
        print("geschrieben:", ZIEL / name)


if __name__ == "__main__":
    main()
