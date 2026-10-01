"""Phase 3 — le seuil à battre, avant tout backtest.

Deux seuils par couple (stop S, objectif RR·S), coût c mesuré en phase 2 :

1. Seuil de coût (formule du brief) :
       p_be = (S + c) / (S + RR·S)
   C'est le taux de réussite qui annule l'espérance après spread.

2. Seuil d'exécutabilité (contrainte quart-de-Kelly, CLAUDE.md) :
   le quart de Kelly doit allouer AU MOINS volume_min = 0.01 lot sur
   100 EUR, sans jamais arrondir vers le haut.
       b_net    = (RR·S − c) / (S + c)          (cote nette après coût)
       f*(p)    = (p·(b_net+1) − 1) / b_net      (Kelly plein)
       r_min    = (S + c) · v1usd / capital      (risque du lot minimum,
                                                  coût inclus)
       exécutable ⟺ f*(p)/4 ≥ r_min
       ⟺ p ≥ p_exec = (4·r_min·b_net + 1) / (b_net + 1)

Le seuil réel est p_requis = max(p_be, p_exec) : en dessous de p_be la
stratégie perd, en dessous de p_exec elle n'est pas exécutable sur
100 EUR. p_be décroît avec S, p_exec croît avec S : leur croisement
donne le stop S* qui minimise l'exigence — c'est le plancher de
difficulté du projet, toutes unités de temps confondues.

Entrées : data/mesure_phase2.json. Sorties : data/seuil.txt,
data/seuil_grille.csv. Aucun accès MT5 nécessaire (pur calcul).
"""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import pandas as pd

MULTIPLES_STOP = (0.5, 1.0, 1.5)
RRS = (1.0, 2.0, 3.0)


def charger():
    chemin = RACINE / "data" / "mesure_phase2.json"
    if not chemin.exists():
        raise FileNotFoundError(f"{chemin} absent — exécuter la phase 2 d'abord.")
    return json.loads(chemin.read_text(encoding="utf-8"))


def seuils(S, RR, c, v1usd, capital):
    """Retourne (p_be, p_exec, b_net, r_min) pour un couple stop/objectif."""
    if RR * S <= c:
        return None  # l'objectif ne couvre même pas le coût
    p_be = (S + c) / (S + RR * S)
    b_net = (RR * S - c) / (S + c)
    r_min = (S + c) * v1usd / capital
    p_exec = (4.0 * r_min * b_net + 1.0) / (b_net + 1.0)
    return p_be, p_exec, b_net, r_min


def main():
    m = charger()
    c_med = m["spread"]["mediane"]
    c_p95 = m["spread"]["p95"]
    v1usd = m["valeur_1usd_volume_min"]
    capital = m["capital_ref_eur"]
    devise = m["devise"]

    lignes = []

    def w(t=""):
        lignes.append(t)

    w("=" * 72)
    w("PHASE 3 — LE SEUIL À BATTRE")
    w("=" * 72)
    w()
    w(f"coût aller-retour retenu : spread médian c = {c_med:.2f} $ "
      f"(stress : P95 = {c_p95:.2f} $)")
    w(f"conversion : 1 $ de mouvement sur volume_min = {v1usd:.4f} {devise}")
    w(f"capital de référence : {capital:.0f} EUR ; quart de Kelly ; "
      "volume_min = 0.01 lot jamais arrondi vers le haut")
    w()
    w("p_be    = taux de réussite d'équilibre après coût")
    w("p_exec  = taux de réussite minimal pour que le quart de Kelly")
    w("          alloue au moins 0.01 lot sur 100 EUR")
    w("p_requis = max des deux ; edge = p_requis − p_hasard où")
    w("p_hasard = 1/(1+RR), le taux d'équilibre d'une pièce sans coût")
    w()

    # ---------- Grille par UT ----------
    grille = []
    for ut, atr in m["atr"].items():
        A = atr["atr_median"]
        for mult in MULTIPLES_STOP:
            S = mult * A
            for RR in RRS:
                res = seuils(S, RR, c_med, v1usd, capital)
                if res is None:
                    continue
                p_be, p_exec, b_net, r_min = res
                p_req = max(p_be, p_exec)
                p_hasard = 1.0 / (1.0 + RR)
                grille.append({
                    "ut": ut, "mult_atr": mult, "stop_usd": round(S, 2),
                    "rr": RR,
                    "risque_lot_min_pct": round(r_min * 100, 2),
                    "p_be": round(p_be, 4), "p_exec": round(p_exec, 4),
                    "p_requis": round(p_req, 4),
                    "edge_requis_pts": round((p_req - p_hasard) * 100, 2),
                    "contrainte": "coût" if p_be >= p_exec else "exécutabilité",
                })
    df = pd.DataFrame(grille)
    df.to_csv(RACINE / "data" / "seuil_grille.csv", index=False)

    for ut in m["atr"]:
        A = m["atr"][ut]["atr_median"]
        ratio = m["atr"][ut]["ratio_spread_atr_pct"]
        w(f"--- {ut} (ATR14 médian {A:.2f} $, spread/ATR {ratio:.1f} %) ---")
        w(f"{'stop':>10} {'RR':>4} {'risque min':>11} {'p_be':>7} "
          f"{'p_exec':>7} {'p_requis':>8} {'edge requis':>12} {'limite':>14}")
        for r in [g for g in grille if g["ut"] == ut]:
            w(f"{r['mult_atr']:>4.1f}×ATR "
              f"{r['stop_usd']:>5.2f}$ {r['rr']:>3.0f} "
              f"{r['risque_lot_min_pct']:>10.2f}% "
              f"{r['p_be']:>7.3f} {r['p_exec']:>7.3f} {r['p_requis']:>8.3f} "
              f"{r['edge_requis_pts']:>+10.1f}pts {r['contrainte']:>14}")
        w()

    # ---------- Croisement : le plancher de difficulté ----------
    w("--- PLANCHER DE DIFFICULTÉ (stop S* minimisant p_requis) ---")
    w("balayage S de 0.40 $ à 40.00 $ par pas de 0.05 $ :")
    resume_croisement = {}
    for etiquette, c in (("médian", c_med), ("P95 (stress)", c_p95)):
        w(f"  coût {etiquette} c = {c:.2f} $ :")
        for RR in RRS:
            meilleur = None
            S = 0.40
            while S <= 40.0:
                res = seuils(S, RR, c, v1usd, capital)
                if res is not None:
                    p_req = max(res[0], res[1])
                    if meilleur is None or p_req < meilleur[1]:
                        meilleur = (S, p_req, res[0], res[1])
                S += 0.05
            if meilleur is None:
                raise RuntimeError(f"aucun stop viable pour RR={RR}, c={c}")
            S_opt, p_min, p_be_o, p_exec_o = meilleur
            p_hasard = 1.0 / (1.0 + RR)
            edge = (p_min - p_hasard) * 100
            w(f"    RR {RR:.0f} : S* ≈ {S_opt:5.2f} $ → p_requis minimal "
              f"{p_min:.3f} (hasard {p_hasard:.3f}, edge requis "
              f"{edge:+.1f} pts)")
            if etiquette == "médian":
                resume_croisement[RR] = {"S_opt": S_opt, "p_min": p_min,
                                         "edge_pts": edge}
        w()

    # ---------- Verdicts par UT ----------
    w("--- VERDICTS ---")
    verdicts = {}
    for ut, atr in m["atr"].items():
        A = atr["atr_median"]
        sous = [g for g in grille if g["ut"] == ut]
        meilleur = min(sous, key=lambda g: g["edge_requis_pts"])
        verdicts[ut] = meilleur
        w(f"{ut:>4} : meilleur cas {meilleur['mult_atr']}×ATR = "
          f"{meilleur['stop_usd']}$, RR {meilleur['rr']:.0f} → "
          f"p_requis {meilleur['p_requis']:.3f}, edge requis "
          f"{meilleur['edge_requis_pts']:+.1f} pts "
          f"(contrainte : {meilleur['contrainte']})")
    w()

    (RACINE / "data" / "seuil.txt").write_text("\n".join(lignes) + "\n",
                                               encoding="utf-8")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
