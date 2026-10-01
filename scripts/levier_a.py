"""Phase 5, LEVIER A — le seuil recalculé sur les heures à faible spread.

Critère de restriction (défini sur les agrégats publiés en phase 2) :
heures serveur dont le spread MÉDIAN ≤ 0.28 $ (data/spread_horaire.csv).
On re-collecte les ticks pour calculer la médiane et le P95 POOLÉS sur
ce sous-ensemble (les agrégats horaires ne permettent pas de pooler),
puis on recalcule le croisement p_be / p_exec de la phase 3.

Sauvegardes :
- data/ticks.npz          (time, bid, ask — pour le levier B)
- data/levier_a.json      (heures retenues, coûts restreints)
- data/levier_a.txt       (rapport)
Lecture seule, aucun ordre.
"""

import json
import sys
import time as time_mod
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "scripts"))

import numpy as np
import pandas as pd

from connect import connect, disconnect
from mesure_cout import collecter_ticks
from seuil import seuils

SEUIL_SPREAD_MEDIAN = 0.28
RRS = (1.0, 2.0, 3.0)


def croisement(c, v1usd, capital):
    """S* minimisant p_requis = max(p_be, p_exec), par RR."""
    res = {}
    for RR in RRS:
        meilleur = None
        S = 0.40
        while S <= 40.0:
            r = seuils(S, RR, c, v1usd, capital)
            if r is not None:
                p_req = max(r[0], r[1])
                if meilleur is None or p_req < meilleur[1]:
                    meilleur = (S, p_req)
            S += 0.05
        if meilleur is None:
            raise RuntimeError(f"aucun stop viable pour RR={RR}, c={c}")
        res[RR] = {"S_opt": meilleur[0], "p_min": meilleur[1],
                   "edge_pts": (meilleur[1] - 1.0 / (1.0 + RR)) * 100}
    return res


def main():
    m2 = json.loads((RACINE / "data" / "mesure_phase2.json")
                    .read_text(encoding="utf-8"))
    v1usd = m2["valeur_1usd_volume_min"]
    capital = m2["capital_ref_eur"]
    c_med_global = m2["spread"]["mediane"]
    c_p95_global = m2["spread"]["p95"]

    sp = pd.read_csv(RACINE / "data" / "spread_horaire.csv")
    heures_ok = sorted(int(h) for h, m in
                       zip(sp["heure_serveur"], sp["mediane"])
                       if m <= SEUIL_SPREAD_MEDIAN)
    if not heures_ok:
        raise RuntimeError("Aucune heure ne satisfait le critère — "
                           "vérifier spread_horaire.csv")

    connect()
    utc_now = datetime.fromtimestamp(time_mod.time(), tz=timezone.utc)
    ticks_df, dt_srv, _ = collecter_ticks(utc_now)
    disconnect()

    np.savez_compressed(RACINE / "data" / "ticks.npz",
                        time=ticks_df["time"].to_numpy(np.int64),
                        bid=ticks_df["bid"].to_numpy(np.float64),
                        ask=ticks_df["ask"].to_numpy(np.float64))

    restreint = ticks_df[ticks_df["heure"].isin(heures_ok)]["spread"]
    if len(restreint) == 0:
        raise RuntimeError("Aucun tick dans les heures retenues")
    c_med = float(restreint.median())
    c_p95 = float(restreint.quantile(0.95))

    lignes = []

    def w(t=""):
        lignes.append(t)

    w("=" * 72)
    w("LEVIER A — SEUILS RECALCULÉS SUR LES HEURES À FAIBLE SPREAD")
    w("=" * 72)
    w()
    w(f"critère : spread médian horaire ≤ {SEUIL_SPREAD_MEDIAN:.2f} $ "
      "(agrégats phase 2)")
    w(f"heures serveur retenues : {heures_ok} "
      f"({len(heures_ok)} h/22, UTC+{m2['decalage_serveur_heures']})")
    w(f"ticks dans ces heures : {len(restreint)} / {len(ticks_df)} "
      f"({len(restreint) / len(ticks_df) * 100:.0f} %)")
    w()
    w(f"coût aller-retour   global (phase 3) : médiane {c_med_global:.2f} $ "
      f"| P95 {c_p95_global:.2f} $")
    w(f"coût aller-retour   heures retenues  : médiane {c_med:.2f} $ "
      f"| P95 {c_p95:.2f} $")
    w(f"réduction du coût médian : "
      f"{(1 - c_med / c_med_global) * 100:.0f} %")
    w()

    w("croisement p_be / p_exec (plancher de difficulté) :")
    w(f"{'':>6} {'— phase 3 (global) —':>34} {'— heures retenues —':>34}")
    w(f"{'RR':>4} {'S*':>8} {'p_requis':>9} {'edge':>9} "
      f"{'S*':>8} {'p_requis':>9} {'edge':>9} {'gain':>7}")
    avant = croisement(c_med_global, v1usd, capital)
    apres = croisement(c_med, v1usd, capital)
    apres_p95 = croisement(c_p95, v1usd, capital)
    for RR in RRS:
        a, b = avant[RR], apres[RR]
        w(f"{RR:>4.0f} {a['S_opt']:>7.2f}$ {a['p_min']:>9.3f} "
          f"{a['edge_pts']:>+8.1f}p {b['S_opt']:>7.2f}$ "
          f"{b['p_min']:>9.3f} {b['edge_pts']:>+8.1f}p "
          f"{a['edge_pts'] - b['edge_pts']:>6.1f}p")
    w()
    w("stress (P95 des heures retenues) :")
    for RR in RRS:
        b = apres_p95[RR]
        w(f"  RR {RR:.0f} : S* {b['S_opt']:.2f}$ → p_requis {b['p_min']:.3f} "
          f"(edge requis {b['edge_pts']:+.1f} pts)")
    w()
    w("NOUVEAU PLANCHER DE DIFFICULTÉ (coût médian, heures retenues) : "
      f"edge requis minimal {min(v['edge_pts'] for v in apres.values()):+.1f} "
      "points au-dessus du hasard.")

    (RACINE / "data" / "levier_a.json").write_text(json.dumps({
        "seuil_spread_median": SEUIL_SPREAD_MEDIAN,
        "heures_ok": heures_ok,
        "cout_median_restreint": c_med,
        "cout_p95_restreint": c_p95,
        "croisement_median": {str(k): v for k, v in apres.items()},
        "croisement_p95": {str(k): v for k, v in apres_p95.items()},
    }, indent=2), encoding="utf-8")
    (RACINE / "data" / "levier_a.txt").write_text("\n".join(lignes) + "\n",
                                                  encoding="utf-8")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
