"""Contrôle de rigueur phase 4 — témoin à entrées ALÉATOIRES.

Pour chacune des 3 configurations sélectionnées en IS, on rejoue la même
machinerie (stop, RR, coût horaire, sessions, règle conservatrice) avec
des signaux tirés au hasard, à la même densité que les signaux réels,
sur 20 graines. Deux lectures :
- si la stratégie réelle ≈ témoin aléatoire, le signal n'a aucun pouvoir
  directionnel : seule la structure de coût explique le résultat ;
- l'espérance du témoin doit être voisine de −(coût par trade), ce qui
  valide le simulateur.

Aucun accès MT5 : relit les barres sauvegardées par backtest.py.
Sortie : data/temoin_aleatoire.txt.
"""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "scripts"))

import numpy as np
import pandas as pd

from config import CAPITAL_REF_EUR
from backtest import (PART_IS, metriques, preparer, signaux_donchian,
                      signaux_zscore, simuler)

# Les 3 sélections IS du run backtest.py (déterministe, voir
# data/backtest_resultats.txt). Toute divergence = re-vérifier.
SELECTIONNEES = [
    {"id": "A-don-M5-N12-RR3", "ut": "M5", "type": "donchian", "N": 12,
     "rr": 3.0, "mult_stop": 0.5},
    {"id": "B-zscore-M5-z2.5-RR2", "ut": "M5", "type": "zscore", "N": 48,
     "z": 2.5, "rr": 2.0, "mult_stop": 0.5},
    {"id": "C-don-M1-N60-RR3", "ut": "M1", "type": "donchian", "N": 60,
     "rr": 3.0, "mult_stop": 1.0},
]
N_GRAINES = 20


def main():
    m2 = json.loads((RACINE / "data" / "mesure_phase2.json")
                    .read_text(encoding="utf-8"))
    v1usd = m2["valeur_1usd_volume_min"]
    sp = pd.read_csv(RACINE / "data" / "spread_horaire.csv")
    cout_med = dict(zip(sp["heure_serveur"], sp["mediane"]))

    barres = {}
    tf_secondes = {"M1": 60, "M5": 300}
    for ut in ("M1", "M5"):
        chemin = RACINE / "data" / f"barres_{ut.lower()}.csv"
        if not chemin.exists():
            raise FileNotFoundError(f"{chemin} absent — exécuter backtest.py "
                                    "d'abord.")
        barres[ut] = preparer(pd.read_csv(chemin), tf_secondes[ut], ut)

    lignes = []

    def w(t=""):
        lignes.append(t)

    w("=" * 72)
    w("TÉMOIN ALÉATOIRE — mêmes stops/RR/coûts/sessions, entrées au hasard")
    w(f"{N_GRAINES} graines par configuration ; segment OOS uniquement")
    w("=" * 72)
    w()

    for cfg in SELECTIONNEES:
        df = barres[cfg["ut"]]
        if cfg["type"] == "donchian":
            sig_reel = signaux_donchian(df, cfg["N"])
        else:
            sig_reel = signaux_zscore(df, cfg["N"], cfg["z"])
        densite = float(np.mean(sig_reel != 0))

        trades_reel, _, _ = simuler(df, sig_reel, cfg["mult_stop"],
                                    cfg["rr"], cout_med, cfg["ut"])
        i_split = int(len(df) * PART_IS)
        m_reel = metriques([t for t in trades_reel
                            if t["i_entree"] >= i_split],
                           v1usd, CAPITAL_REF_EUR)

        esps, phats, couts = [], [], []
        for graine in range(N_GRAINES):
            rng = np.random.default_rng(1000 + graine)
            sig_alea = rng.choice(
                np.array([-1, 0, 1], dtype=np.int8), size=len(df),
                p=[densite / 2, 1 - densite, densite / 2])
            trades_a, _, _ = simuler(df, sig_alea, cfg["mult_stop"],
                                     cfg["rr"], cout_med, cfg["ut"])
            m_a = metriques([t for t in trades_a
                             if t["i_entree"] >= i_split],
                            v1usd, CAPITAL_REF_EUR)
            if m_a["n"] == 0:
                raise RuntimeError(f"témoin sans trade OOS ({cfg['id']}, "
                                   f"graine {graine})")
            esps.append(m_a["esperance_eur"])
            phats.append(m_a["p_hat"])
            couts.append(m_a["cout_total_eur"] / m_a["n"])

        esps, phats = np.array(esps), np.array(phats)
        w(f"{cfg['id']} (densité de signal {densite:.4f})")
        w(f"  réel    OOS : p̂ {m_reel['p_hat']:.3f} | espérance "
          f"{m_reel['esperance_eur']:+.3f} EUR/trade | "
          f"coût/trade {m_reel['cout_total_eur'] / m_reel['n']:.3f} EUR")
        w(f"  témoin  OOS : p̂ {phats.mean():.3f} ± {phats.std():.3f} | "
          f"espérance {esps.mean():+.3f} ± {esps.std():.3f} EUR/trade | "
          f"coût/trade {np.mean(couts):.3f} EUR")
        ecart = (m_reel["esperance_eur"] - esps.mean()) / esps.std() \
            if esps.std() > 0 else float("nan")
        w(f"  écart réel − témoin : "
          f"{m_reel['esperance_eur'] - esps.mean():+.3f} EUR/trade "
          f"({ecart:+.1f} écarts-types du témoin)")
        w()

    (RACINE / "data" / "temoin_aleatoire.txt").write_text(
        "\n".join(lignes) + "\n", encoding="utf-8")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
