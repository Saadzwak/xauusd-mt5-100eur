"""Phase 5, LEVIER B — features minute depuis les ticks + analyses micro.

Construit data/minutes.csv (une ligne par minute cotée) :
    minute (epoch serveur), n_ticks, n_up, n_down, bid_first, bid_last,
    ret ($), spread_moy, spread_max, heure, contigue_suivante
et produit data/micro_analyse.txt : relations DESCRIPTIVES (pas de
stratégie ici — les grilles des familles D/E/F sont déclarées dans
phase5_backtest.py avant toute simulation) :
  1. intensité de ticks → amplitude et continuation de la minute suivante
  2. déséquilibre de flux (ticks up vs down) → rendement minute suivante
  3. élargissement du spread → amplitude / continuation suivantes
  4. asymétrie de la distribution des rendements minute

Aucun accès MT5 (relit data/ticks.npz).
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import numpy as np
import pandas as pd

FENETRE_ROULANTE = 60      # minutes, pour les bases mobiles (intensité, spread)


def construire_minutes():
    z = np.load(RACINE / "data" / "ticks.npz")
    t, bid, ask = z["time"], z["bid"], z["ask"]
    ordre = np.argsort(t, kind="stable")
    t, bid, ask = t[ordre], bid[ordre], ask[ordre]

    dbid = np.diff(bid, prepend=bid[0])
    dt = np.diff(t, prepend=t[0])
    dbid[dt > 120] = 0.0            # pas de signe à travers les coupures

    df = pd.DataFrame({
        "minute": (t // 60) * 60,
        "bid": bid,
        "spread": ask - bid,
        "up": (dbid > 0).astype(np.int32),
        "down": (dbid < 0).astype(np.int32),
    })
    g = df.groupby("minute")
    m = pd.DataFrame({
        "n_ticks": g["bid"].count(),
        "n_up": g["up"].sum(),
        "n_down": g["down"].sum(),
        "bid_first": g["bid"].first(),
        "bid_last": g["bid"].last(),
        "spread_moy": g["spread"].mean(),
        "spread_max": g["spread"].max(),
    }).reset_index()
    m["ret"] = m["bid_last"] - m["bid_first"]
    m["heure"] = pd.to_datetime(m["minute"], unit="s").dt.hour
    m["contigue_suivante"] = m["minute"].shift(-1) == m["minute"] + 60
    m.to_csv(RACINE / "data" / "minutes.csv", index=False)
    return m


def main():
    m = construire_minutes()
    lignes = []

    def w(t=""):
        lignes.append(t)

    w("=" * 72)
    w("ANALYSES MICROSTRUCTURE (descriptives, minute par minute)")
    w("=" * 72)
    w()
    w(f"minutes cotées : {len(m)} | ticks : {int(m['n_ticks'].sum())} | "
      f"période : {pd.to_datetime(int(m['minute'].min()), unit='s'):%Y-%m-%d} "
      f"→ {pd.to_datetime(int(m['minute'].max()), unit='s'):%Y-%m-%d} "
      "(heure serveur)")
    w()

    # cible : minute suivante (uniquement si contiguë)
    valide = m["contigue_suivante"].to_numpy()
    ret_suiv = m["ret"].shift(-1).to_numpy()
    ret = m["ret"].to_numpy()
    n_ticks = m["n_ticks"].to_numpy()

    # ---------- 1. intensité ----------
    w("--- 1. INTENSITÉ DE TICKS (n_ticks/min vs minute suivante) ---")
    base = m["n_ticks"].rolling(FENETRE_ROULANTE, min_periods=30).mean() \
        .shift(1).to_numpy()
    ratio = np.where(base > 0, n_ticks / base, np.nan)
    ok = valide & np.isfinite(ratio) & np.isfinite(ret_suiv)
    quintiles = pd.qcut(pd.Series(ratio[ok]), 5, labels=False)
    tbl = pd.DataFrame({"q": quintiles,
                        "abs_suiv": np.abs(ret_suiv[ok]),
                        "cont": np.sign(ret[ok]) * ret_suiv[ok]})
    agg = tbl.groupby("q").agg(n=("abs_suiv", "count"),
                               ampl_suiv=("abs_suiv", "mean"),
                               continuation=("cont", "mean"))
    w("quintile d'intensité relative | n | amplitude moyenne minute "
      "suivante ($) | continuation moyenne ($, >0 = poursuite)")
    for q, r in agg.iterrows():
        w(f"  Q{int(q) + 1} : {int(r['n']):>6} | {r['ampl_suiv']:.4f} | "
          f"{r['continuation']:+.5f}")
    corr = np.corrcoef(ratio[ok], np.abs(ret_suiv[ok]))[0, 1]
    w(f"corrélation intensité relative ↔ amplitude suivante : {corr:+.3f}")
    w()

    # ---------- 2. déséquilibre de flux ----------
    w("--- 2. DÉSÉQUILIBRE DE FLUX (up-down)/(up+down), minute t → t+1 ---")
    tot = (m["n_up"] + m["n_down"]).to_numpy()
    imb = np.where(tot >= 10, (m["n_up"] - m["n_down"]) / np.maximum(tot, 1),
                   np.nan)
    ok = valide & np.isfinite(imb) & np.isfinite(ret_suiv)
    deciles = pd.qcut(pd.Series(imb[ok]), 10, labels=False, duplicates="drop")
    tbl = pd.DataFrame({"d": deciles, "suiv": ret_suiv[ok]})
    agg = tbl.groupby("d").agg(n=("suiv", "count"), moy=("suiv", "mean"),
                               sd=("suiv", "std"))
    agg["t"] = agg["moy"] / (agg["sd"] / np.sqrt(agg["n"]))
    w("décile d'imbalance | n | rendement moyen minute suivante ($) | t")
    for d, r in agg.iterrows():
        w(f"  D{int(d) + 1:>2} : {int(r['n']):>6} | {r['moy']:+.5f} | "
          f"t={r['t']:+.2f}")
    corr = np.corrcoef(imb[ok], ret_suiv[ok])[0, 1]
    w(f"corrélation imbalance ↔ rendement suivant : {corr:+.4f}")
    w()

    # ---------- 3. dynamique du spread ----------
    w("--- 3. ÉLARGISSEMENT DU SPREAD (z du spread moyen minute) ---")
    smoy = m["spread_moy"]
    mu = smoy.rolling(FENETRE_ROULANTE, min_periods=30).mean().shift(1)
    sd = smoy.rolling(FENETRE_ROULANTE, min_periods=30).std().shift(1)
    sz = ((smoy - mu) / sd).to_numpy()
    ok = valide & np.isfinite(sz) & np.isfinite(ret_suiv)
    seaux = pd.cut(pd.Series(sz[ok]),
                   [-np.inf, -1, 0, 1, 2, 3, np.inf],
                   labels=["<-1", "-1..0", "0..1", "1..2", "2..3", ">3"])
    tbl = pd.DataFrame({"s": seaux, "abs_suiv": np.abs(ret_suiv[ok]),
                        "cont": np.sign(ret[ok]) * ret_suiv[ok],
                        "suiv": ret_suiv[ok]})
    agg = tbl.groupby("s", observed=True).agg(
        n=("suiv", "count"), ampl=("abs_suiv", "mean"),
        continuation=("cont", "mean"), signe=("suiv", "mean"))
    w("z-spread | n | amplitude suivante ($) | continuation ($) | "
      "rendement signé ($)")
    for s, r in agg.iterrows():
        w(f"  {s:>6} : {int(r['n']):>6} | {r['ampl']:.4f} | "
          f"{r['continuation']:+.5f} | {r['signe']:+.5f}")
    w()

    # ---------- 4. asymétrie ----------
    w("--- 4. ASYMÉTRIE DES RENDEMENTS MINUTE ---")
    s = pd.Series(ret[np.isfinite(ret)])
    w(f"global : n={len(s)}, moyenne {s.mean():+.5f} $, σ {s.std():.4f} $, "
      f"skew {s.skew():+.3f}, kurtosis excédentaire {s.kurt():+.2f}")
    par_h = m.groupby("heure")["ret"].agg(["count", "mean", "std",
                                           "skew"])
    pires = par_h.reindex(par_h["skew"].abs().sort_values().index[-3:])
    w("heures au skew le plus marqué :")
    for h, r in pires.iterrows():
        w(f"  {h:02d}h : skew {r['skew']:+.3f} (n={int(r['count'])})")
    w()

    (RACINE / "data" / "micro_analyse.txt").write_text(
        "\n".join(lignes) + "\n", encoding="utf-8")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
