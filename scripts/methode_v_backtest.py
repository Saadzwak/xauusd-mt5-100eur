"""Méthode V (spec du propriétaire, 2026-09-11) — backtest hors ligne.

Hypothèse n° 51 du compteur cumulatif. Config UNIQUE, déclarée par le
propriétaire, aucune grille, aucune variante :
- EMA9/EMA21 sur close M5 ; signal à la clôture de la barre n-1 :
    dPrev = EMA9[n-2] − EMA21[n-2] ; dLast = EMA9[n-1] − EMA21[n-1]
    BUY si dPrev ≤ 0 et dLast > 0 ; SELL si dPrev ≥ 0 et dLast < 0
- filtre volume : tick_volume(barre signal) ≥ moyenne des 20 barres
  closes précédentes ET ≥ 200 (NB : sur ce feed, 100 % des barres
  dépassent 200 — seule la moyenne mobile filtre réellement) ;
- permanence : un croisement invalidé ne se re-signale jamais (chaque
  barre n'est évaluée qu'une fois, ce qui l'implémente exactement) ;
- entrée au marché à l'open de la barre suivante ;
- SL fixe 10 $ ; TP fixe 7 $ (RR 0.7) — jamais modulés.

Implémentation : simulateur phase 5 avec colonne atr forcée à 10.0 et
rr = 0.7 (S = 10 $ fixe, TP = 7 $). Coût = spread médian de l'heure
d'entrée (phase 2). Walk-forward 5 blocs, tests 2-5. Témoin par
permutation de signes si candidat positif. Exécutabilité quart-Kelly
(capital de référence 100 EUR, CLAUDE.md).

Seuil à battre analytique (à coût médian c ≈ 0.30) :
    p_be = (10 + c) / (10 + 7) ≈ 0.606
"""

import json
import math
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "scripts"))

import numpy as np
import pandas as pd

from config import CAPITAL_REF_EUR
from backtest import kelly_quart, metriques, preparer
from phase5_backtest import (blocs_temporels, restreindre_test, simuler5,
                             t_stat, temoin_permutation)

COMPTEUR_AVANT = 50
SL_USD = 10.0
TP_USD = 7.0
VOL_SEUIL_ABS = 200
VOL_FENETRE = 20
N_GRAINES = 20


def signaux_methode_v(df):
    close = df["close"]
    vol = df["tick_volume"]
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    d = (ema9 - ema21).to_numpy()
    vol_ma20 = vol.rolling(VOL_FENETRE).mean().shift(1).to_numpy()
    v = vol.to_numpy()
    sig = np.zeros(len(df), dtype=np.int8)
    n_croisements, n_invalides_volume = 0, 0
    for i in range(VOL_FENETRE + 21, len(df)):
        dprev, dlast = d[i - 1], d[i]
        if not (np.isfinite(dprev) and np.isfinite(dlast)
                and np.isfinite(vol_ma20[i])):
            continue
        haussier = dprev <= 0 and dlast > 0
        baissier = dprev >= 0 and dlast < 0
        if not (haussier or baissier):
            continue
        n_croisements += 1
        if v[i] >= vol_ma20[i] and v[i] >= VOL_SEUIL_ABS:
            sig[i] = 1 if haussier else -1
        else:
            n_invalides_volume += 1
    return sig, n_croisements, n_invalides_volume


def main():
    m2 = json.loads((RACINE / "data" / "mesure_phase2.json")
                    .read_text(encoding="utf-8"))
    v1usd = m2["valeur_1usd_volume_min"]
    c_med = m2["spread"]["mediane"]
    sp = pd.read_csv(RACINE / "data" / "spread_horaire.csv")
    cout_med = dict(zip(sp["heure_serveur"], sp["mediane"]))
    cout_p95 = dict(zip(sp["heure_serveur"], sp["p95"]))

    brut = pd.read_csv(RACINE / "data" / "barres_m5_vol.csv")
    df = preparer(brut, 300, "M5")
    df["atr"] = 10.0          # S fixe = 10 $ via le simulateur (mult 1.0)
    rr = TP_USD / SL_USD

    sig, n_crois, n_inval = signaux_methode_v(df)
    blocs = blocs_temporels(df)
    kw = {"mult_stop": 1.0, "rr": rr, "sortie": "tp", "heures_ok": None}

    trades = simuler5(df, sig, cout_heure=cout_med, ut="M5", **kw)
    oos, par_bloc = restreindre_test(trades, blocs)
    m = metriques(oos, v1usd, CAPITAL_REF_EUR)
    m["t"] = t_stat(oos, v1usd) if oos else float("nan")
    blocs_pos = sum(1 for b in par_bloc if b and sum(t["pnl_usd"] for t in b) > 0)

    n_essais = COMPTEUR_AVANT + 1
    seuil_bruit = math.sqrt(2 * math.log(n_essais))
    p_be = (SL_USD + c_med) / (SL_USD + TP_USD)

    lignes = []
    w = lignes.append
    w("=" * 72)
    w("MÉTHODE V — BACKTEST (EMA9/EMA21 M5 + filtre volume, SL 10 / TP 7)")
    w("=" * 72)
    d0 = pd.to_datetime(int(df['time'].iloc[0]), unit='s')
    d1 = pd.to_datetime(int(df['time'].iloc[-1]), unit='s')
    w(f"données : {len(df)} barres M5, {d0:%Y-%m-%d} → {d1:%Y-%m-%d} "
      "(heure serveur)")
    w(f"compteur cumulatif : {COMPTEUR_AVANT} + 1 = {n_essais} → t requis "
      f"> {seuil_bruit:.2f}")
    w(f"croisements EMA détectés : {n_crois} | invalidés par le filtre "
      f"volume : {n_inval} ({n_inval / max(n_crois, 1) * 100:.0f} %)")
    w(f"seuil d'équilibre analytique : p_be = (10+{c_med:.2f})/(10+7) = "
      f"{p_be:.3f} — il faut {p_be * 100:.1f} % de réussite pour ne pas "
      "perdre (RR 0.7 : on risque 10 pour gagner 7)")
    w("")
    if m["n"] == 0:
        w("AUCUN trade OOS — rien à évaluer.")
    else:
        w(f"WALK-FORWARD OOS (blocs 2-5) : n = {m['n']} | p̂ = "
          f"{m['p_hat']:.3f} | espérance {m['esperance_eur']:+.3f} EUR/trade "
          f"| t = {m['t']:+.2f} | blocs positifs {blocs_pos}/4 | "
          f"DD {m['dd_max_pct']:.1f} % | coût total "
          f"{m['cout_total_eur']:.2f} EUR")
        w(f"gain moyen {m['gain_moyen_eur']:+.2f} EUR | perte moyenne "
          f"{-m['perte_moyenne_eur']:.2f} EUR | forcées {m['n_forcees']}")
        w("")
        if m["esperance_eur"] > 0 and m["n"] >= 20:
            esps = []
            for g in range(N_GRAINES):
                tr_t = temoin_permutation(df, sig, 9000 + g,
                                          cout_heure=cout_med, ut="M5", **kw)
                oos_t, _ = restreindre_test(tr_t, blocs)
                if oos_t:
                    esps.append(metriques(oos_t, v1usd,
                                          CAPITAL_REF_EUR)["esperance_eur"])
            esps = np.array(esps)
            z = ((m["esperance_eur"] - esps.mean()) / esps.std()
                 if esps.std() > 0 else float("nan"))
            w(f"témoin ({N_GRAINES} graines) : {esps.mean():+.3f} ± "
              f"{esps.std():.3f} → écart {z:+.1f} σ "
              f"{'✓' if z > 2 else '✗'}")
            c3 = m["t"] > seuil_bruit
            w(f"correction essais : t={m['t']:+.2f} vs {seuil_bruit:.2f} "
              f"{'✓' if c3 else '✗'}")
            tr_s = simuler5(df, sig, cout_heure=cout_p95, ut="M5", **kw)
            oos_s, _ = restreindre_test(tr_s, blocs)
            m_s = metriques(oos_s, v1usd, CAPITAL_REF_EUR)
            w(f"stress P95 : {m_s.get('esperance_eur', float('nan')):+.3f} "
              f"EUR/trade {'✓' if m_s['n'] and m_s['esperance_eur'] > 0 else '✗'}")
            kq = kelly_quart(m, CAPITAL_REF_EUR, 0.01, 0.01)
            w(f"exécutabilité (réf. 100 EUR) : {kq['verdict']}")
        else:
            w("espérance OOS ≤ 0 (ou n < 20) : pas de phase de vérification "
              "— le témoin/stress/Kelly ne s'appliquent qu'aux candidats "
              "positifs.")
            kq = kelly_quart(m, CAPITAL_REF_EUR, 0.01, 0.01)
            w(f"exécutabilité (pour information) : {kq['verdict']}")
    w("")
    w(f"COMPTEUR CUMULATIF : {n_essais}")
    texte = "\n".join(lignes) + "\n"
    (RACINE / "data" / "methode_v_backtest.txt").write_text(texte,
                                                            encoding="utf-8")
    print(texte)


if __name__ == "__main__":
    main()
