"""Phase 7-A — état factuel de l'instrument AVANT tout ordre.

Lecture seule. Décrit l'état, pas la suite : aucune anticipation
directionnelle, aucun niveau graphique. Sortie : data/etat_actuel.txt.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from config import SYMBOL
from connect import connect, disconnect

PERIODE_ATR = 14


def atr_serie(tf, nb, cutoff):
    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, nb)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"copy_rates_from_pos : {mt5.last_error()}")
    df = pd.DataFrame({k: rates[k] for k in ("time", "high", "low", "close")})
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / PERIODE_ATR, adjust=False).mean()
    df = df.iloc[PERIODE_ATR * 3:]
    # dernière barre FERMÉE = avant-dernière ligne (la dernière se forme)
    atr_courant = float(df["atr"].iloc[-2])
    fen = df[df["time"] >= cutoff]["atr"]
    q1, q2 = fen.quantile([1 / 3, 2 / 3])
    tercile = "bas" if atr_courant <= q1 else \
              "haut" if atr_courant > q2 else "moyen"
    pct = float((fen <= atr_courant).mean() * 100)
    return atr_courant, tercile, pct, float(q1), float(q2)


def main():
    connect()
    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None:
        raise RuntimeError(f"tick/info None : {mt5.last_error()}")
    bid, ask = tick.bid, tick.ask
    spread = ask - bid
    t_srv = int(tick.time)
    dt_srv = datetime.fromtimestamp(t_srv, tz=timezone.utc).replace(tzinfo=None)
    heure = dt_srv.hour

    sp = pd.read_csv(RACINE / "data" / "spread_horaire.csv")
    ligne_h = sp[sp["heure_serveur"] == heure]
    med_h = float(ligne_h["mediane"].iloc[0]) if len(ligne_h) else float("nan")

    cutoff = t_srv - 60 * 86400
    lignes = []
    w = lignes.append
    w("=" * 68)
    w("PHASE 7-A — ÉTAT ACTUEL (factuel, aucune anticipation)")
    w("=" * 68)
    w("")
    w(f"heure serveur : {dt_srv:%Y-%m-%d %H:%M:%S} (UTC+3) | heure {heure}h")
    w(f"prix : bid {bid} / ask {ask} | spread instantané "
      f"{spread:.2f} $ | spread médian de l'heure {heure}h : {med_h:.2f} $")
    w("")

    for nom, tf, nb in (("M1", mt5.TIMEFRAME_M1, 99_000),
                        ("M5", mt5.TIMEFRAME_M5, 25_000),
                        ("M15", mt5.TIMEFRAME_M15, 10_000)):
        a, terc, pct, q1, q2 = atr_serie(tf, nb, cutoff)
        w(f"ATR14 {nom:<4}: {a:5.2f} $ → tercile {terc.upper()} sur 60 j "
          f"(percentile {pct:.0f} % ; bornes terciles {q1:.2f} / {q2:.2f})")
    w("")

    r5 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 25_000)
    df5 = pd.DataFrame({k: r5[k] for k in ("time", "high", "low", "close")})
    for jours in (5, 20, 30, 60):
        fen = df5[df5["time"] >= t_srv - jours * 86400]
        if jours == 30:
            pct_prix = float((fen["close"] <= bid).mean() * 100)
            w(f"position du prix dans la distribution 30 j : "
              f"percentile {pct_prix:.0f} % "
              f"(min {fen['low'].min():.2f}, max {fen['high'].max():.2f})")
        else:
            haut, bas = fen["high"].max(), fen["low"].min()
            w(f"extrêmes {jours:>2} j : haut {haut:8.2f} "
              f"({(haut - bid):+7.2f} $ / {(haut - bid) / bid * 100:+.2f} %) | "
              f"bas {bas:8.2f} ({(bas - bid):+7.2f} $ / "
              f"{(bas - bid) / bid * 100:+.2f} %)")
    w("")

    w("profil de spread médian attendu (mesure phase 2) jusqu'à 08h :")
    heures_avenir = [(heure + k) % 24 for k in range(0, 6)]
    for h in heures_avenir:
        lg = sp[sp["heure_serveur"] == h]
        if len(lg):
            w(f"  {h:02d}h : médiane {float(lg['mediane'].iloc[0]):.2f} $ | "
              f"P95 {float(lg['p95'].iloc[0]):.2f} $")
        else:
            w(f"  {h:02d}h : PAS DE COTATION (pause quotidienne)")
        if h == 8:
            break
    disconnect()

    texte = "\n".join(lignes) + "\n"
    (RACINE / "data" / "etat_actuel.txt").write_text(texte, encoding="utf-8")
    print(texte)


if __name__ == "__main__":
    main()
