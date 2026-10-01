"""Phase 6, étape 2 — analyse HORS CONNEXION du compte réel.

N'importe PAS MetaTrader5. Travaille uniquement sur
data/historique_reel.csv, data/deals_bruts_reel.csv, data/compte_reel.json.

1. décomposition de la perte (commission, swap, spread implicite estimé,
   direction pure) ;
2. espérance NORMALISÉE à volume constant 0.01 lot (la question centrale) ;
3. témoin aléatoire : mêmes trades, directions au hasard, coûts conservés,
   20 graines ;
4. sizing : volumes, risque par trade en % du solde du moment, stop-outs,
   réel vs normalisé ;
5. structure : espérance normalisée par heure / durée / jour / sens /
   symbole — chaque découpage compte dans le compteur cumulatif
   (37 + 1 test central = 38 ; +5 découpages = 43) avec correction du
   nombre d'essais.

Sortie : data/analyse_reel.txt + verdict A/B/C explicite.
"""

import json
import math
import statistics
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import numpy as np
import pandas as pd

COMPTEUR_AVANT = 37
N_GRAINES = 20
NORM = statistics.NormalDist()
VOLUME_REF = 0.01


def t_stat(x):
    x = np.asarray(x, dtype=float)
    if len(x) < 2 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x))))


def main():
    pos = pd.read_csv(RACINE / "data" / "historique_reel.csv")
    meta = json.loads((RACINE / "data" / "compte_reel.json")
                      .read_text(encoding="utf-8"))
    devise = meta["compte"]["devise"]

    lignes = []

    def w(t=""):
        lignes.append(t)

    w("=" * 72)
    w("PHASE 6 — ANALYSE DU COMPTE RÉEL (hors connexion)")
    w("=" * 72)
    w()
    w(f"broker {meta['compte']['broker']} ({meta['compte']['serveur']}), "
      f"devise {devise}, levier 1:{meta['compte']['levier']}, "
      f"stop-out {meta['compte']['stop_out']} %")
    w(f"période couverte : {meta['premier_deal']} → {meta['dernier_deal']} "
      "(heure serveur broker, fuseau non identifié)")
    w(f"positions fermées : {len(pos)} | dépôts/retraits : "
      f"{meta['depots_retraits']['n']} pour "
      f"{meta['depots_retraits']['total']:+.2f} {devise}")
    if abs(meta["solde_initial_implicite"]) > 0.01:
        w(f"TRONCATURE PROBABLE : {meta['solde_initial_implicite']:+.2f} "
          f"{devise} de flux antérieurs à la fenêtre manquent (dépôt "
          "initial hors historique synchronisé).")
    w(f"solde actuel : {meta['compte']['solde']:.2f} {devise} "
      f"(equity {meta['compte']['equity']:.2f} : position encore ouverte, "
      "exclue de l'analyse)")
    w()

    d = np.where(pos["sens"] == "long", 1.0, -1.0)
    move = (pos["prix_sortie"] - pos["prix_entree"]) * d

    # conversion devise-de-cotation → EUR, dérivée des deals eux-mêmes
    conv = {}
    for s, g in pos.groupby("symbole"):
        cs = meta["symboles"][s].get("contract_size")
        gd = np.where(g["sens"] == "long", 1.0, -1.0)
        m = (g["prix_sortie"] - g["prix_entree"]) * gd * cs * g["volume"]
        ok = np.abs(m) > 1e-9
        if ok.sum() >= 3:
            conv[s] = float(np.median(g["profit_brut"][ok] / m[ok]))
        else:
            conv[s] = None

    # ---------------- 1. décomposition de la perte ----------------
    w("--- 1. DÉCOMPOSITION DU RÉSULTAT RÉALISÉ ---")
    net_tot = pos["net"].sum()
    comm_tot = pos["commission"].sum() + pos["fee"].sum()
    swap_tot = pos["swap"].sum()
    brut_tot = pos["profit_brut"].sum()
    spread_est = np.zeros(len(pos))
    spread_dispo = np.zeros(len(pos), dtype=bool)
    for s, g in pos.groupby("symbole"):
        info = meta["symboles"][s]
        sc = info.get("spread_courant") or 0.0
        if sc > 0 and conv.get(s):
            spread_est[g.index] = sc * info["contract_size"] * \
                g["volume"].to_numpy() * conv[s]
            spread_dispo[g.index] = True
    dir_pure = brut_tot + spread_est.sum()
    w(f"résultat net réalisé        : {net_tot:+10.2f} {devise} "
      f"({len(pos)} trades)")
    w(f"  commissions + frais       : {comm_tot:+10.2f} {devise} "
      f"({abs(comm_tot) / abs(net_tot) * 100:5.1f} % de la perte)")
    w(f"  swap                      : {swap_tot:+10.2f} {devise} "
      f"({abs(swap_tot) / abs(net_tot) * 100:5.1f} %)")
    w(f"  spread implicite (ESTIMÉ au spread courant, "
      f"{int(spread_dispo.sum())}/{len(pos)} trades estimables) : "
      f"{-spread_est.sum():+10.2f} {devise} "
      f"({spread_est.sum() / abs(net_tot) * 100:5.1f} %)")
    w(f"  direction pure (mid-à-mid, résiduel) : {dir_pure:+10.2f} {devise} "
      f"({abs(dir_pure) / abs(net_tot) * 100:5.1f} %)")
    w()
    par_sym = pos.groupby("symbole").agg(
        n=("net", "count"), net=("net", "sum"), vol_median=("volume", "median"))
    w("par symbole :")
    for s, r in par_sym.iterrows():
        w(f"  {s:<10} n={int(r['n']):>4}  net {r['net']:>+9.2f} {devise}  "
          f"volume médian {r['vol_median']:.2f} lot")
    w()
    # coût par aller-retour normalisé 0.01 lot (XAUUSD, comparaison démo)
    for s in par_sym.index:
        info = meta["symboles"][s]
        if s.startswith("XAU") and info.get("spread_courant") and conv.get(s):
            cout_rt = (info["spread_courant"] * info["contract_size"]
                       * VOLUME_REF * conv[s])
            g = pos[pos["symbole"] == s]
            comm_01 = -(g["commission"] + g["fee"]).sum() / \
                g["volume"].sum() * VOLUME_REF
            w(f"COÛT RÉEL PAR ALLER-RETOUR ({s}, 0.01 lot) : spread "
              f"{cout_rt:.2f} {devise} (courant {info['spread_courant']:.2f} $)"
              f" + commission {comm_01:.2f} {devise} = "
              f"{cout_rt + comm_01:.2f} {devise} — démo MetaQuotes : 0.26 EUR")
    w()

    # ---------------- 2. espérance normalisée 0.01 lot ----------------
    w("--- 2. QUESTION CENTRALE : ESPÉRANCE À VOLUME CONSTANT 0.01 LOT ---")
    w("(hypothèse n° 38 du compteur cumulatif)")
    echelle = VOLUME_REF / pos["volume"]
    brut_n = pos["profit_brut"] * echelle
    couts_n = (pos["commission"] + pos["fee"] + pos["swap"]) * echelle
    net_n = (brut_n + couts_n).to_numpy()
    gains = net_n[net_n > 0]
    pertes = net_n[net_n < 0]
    p_hat = len(gains) / len(net_n)
    t_n = t_stat(net_n)
    w(f"n = {len(net_n)} | espérance {net_n.mean():+.4f} {devise}/trade | "
      f"total normalisé {net_n.sum():+.2f} {devise}")
    w(f"taux de réussite {p_hat:.3f} | gain moyen {gains.mean():+.4f} | "
      f"perte moyenne {pertes.mean():+.4f} | ratio G/P "
      f"{abs(gains.mean() / pertes.mean()):.2f}")
    w(f"t de Student : {t_n:+.2f} (approximation normale, n={len(net_n)})")
    w()

    # ---------------- 3. témoin aléatoire ----------------
    w("--- 3. TÉMOIN ALÉATOIRE (mêmes trades, directions au hasard, "
      f"{N_GRAINES} graines) ---")
    # « mêmes coûts » : le témoin retourne le mouvement MID-à-MID et paie
    # le spread dans tous les cas. mid_norm = brut_norm + spread_norm ;
    # témoin = ±mid_norm − spread_norm + (commission+swap) normalisés.
    spread_n = pd.Series(spread_est, index=pos.index) * echelle
    n_sans_spread = int((~spread_dispo).sum())
    if n_sans_spread:
        w(f"(spread non estimable sur {n_sans_spread} trades : leur témoin "
          "retombe sur la permutation du brut)")
    mid_n = (brut_n + spread_n).to_numpy()
    esps = []
    for g in range(N_GRAINES):
        rng = np.random.default_rng(6000 + g)
        signes = rng.choice([-1.0, 1.0], size=len(net_n))
        esps.append(float((mid_n * signes - spread_n.to_numpy()
                           + couts_n).mean()))
    esps = np.array(esps)
    z_tem = ((net_n.mean() - esps.mean()) / esps.std()
             if esps.std() > 0 else float("nan"))
    w(f"témoin : {esps.mean():+.4f} ± {esps.std():.4f} {devise}/trade")
    w(f"réel − témoin : {net_n.mean() - esps.mean():+.4f} {devise}/trade "
      f"= {z_tem:+.1f} σ")
    w()

    # ---------------- 4. sizing ----------------
    w("--- 4. SIZING ---")
    w(f"volume médian {pos['volume'].median():.2f} lot | maximum "
      f"{pos['volume'].max():.2f} lot")
    fiable = pos["solde_avant"] >= 5.0
    n_exclus = int((~fiable).sum())
    perdants_f = pos[fiable & (pos["net"] < 0)]
    risque_f = (-perdants_f["net"]) / perdants_f["solde_avant"] * 100
    w(f"perte réalisée en % du solde du moment (perdants au solde "
      f"reconstruit ≥ 5 EUR, n={len(perdants_f)} ; {n_exclus} trades exclus "
      "car solde reconstruit < 5 EUR autour des stop-outs/troncature) :")
    w(f"  médiane {risque_f.median():.1f} % | P90 "
      f"{risque_f.quantile(0.9):.1f} % | max {risque_f.max():.1f} %")
    so = pos["raison_sortie"].str.contains("_SO", na=False)
    w(f"sorties par stop-out (DEAL_REASON_SO) : {int(so.sum())}")
    w(f"dépôts pendant la période : {meta['depots_retraits']['n']} "
      f"(recharges après pertes)")
    esp_reelle = pos["net"].mean()
    w(f"espérance réelle {esp_reelle:+.3f} {devise}/trade vs normalisée "
      f"{net_n.mean():+.4f} {devise}/trade")
    ratio_ampl = (esp_reelle / net_n.mean()
                  if abs(net_n.mean()) > 1e-9 else float("nan"))
    w(f"facteur d'amplification du sizing : ×{ratio_ampl:.1f} "
      f"(volume moyen pondéré {pos['volume'].mean() / VOLUME_REF:.0f}× le "
      "lot minimum)")
    corr_vs = float(np.corrcoef(pos["volume"], np.sign(net_n))[0, 1])
    w(f"corrélation volume ↔ signe du résultat normalisé : {corr_vs:+.3f} "
      "(négatif = les plus grosses positions perdent plus souvent)")
    w()

    # ---------------- 5. structure ----------------
    w("--- 5. STRUCTURE (espérance normalisée ; hypothèses n° 39-43) ---")
    n_essais = COMPTEUR_AVANT + 1 + 5
    seuil_global = math.sqrt(2 * math.log(n_essais))
    w(f"compteur cumulatif : {COMPTEUR_AVANT} + 1 (test central) + 5 "
      f"(découpages) = {n_essais} → t requis > {seuil_global:.2f} "
      "+ Bonferroni intra-découpage")
    pos["_net_n"] = net_n
    duree_min = pos["duree_s"] / 60
    pos["_duree_cl"] = pd.cut(duree_min, [0, 1, 5, 30, 120, np.inf],
                              labels=["<1min", "1-5min", "5-30min",
                                      "30min-2h", ">2h"])
    noms_j = {0: "lun", 1: "mar", 2: "mer", 3: "jeu", 4: "ven",
              5: "sam", 6: "dim"}
    pos["_jour"] = pos["jour_semaine"].map(noms_j)
    decoupages = [("heure d'entrée (serveur broker)", "heure_entree"),
                  ("durée de détention", "_duree_cl"),
                  ("jour de semaine", "_jour"),
                  ("sens", "sens"),
                  ("symbole", "symbole")]
    for titre, col in decoupages:
        w(f"  par {titre} :")
        grp = pos.groupby(col, observed=True)["_net_n"]
        n_cellules = sum(1 for _, v in grp if len(v) >= 10)
        bonf = NORM.inv_cdf(1 - 0.025 / max(n_cellules, 1))
        for cle, v in grp:
            if len(v) < 10:
                w(f"    {cle!s:<10} n={len(v):>3}  (effectif < 10, "
                  "non testé)")
                continue
            t = t_stat(v)
            signif = (abs(t) > max(bonf, seuil_global))
            w(f"    {cle!s:<10} n={len(v):>3}  {v.mean():+.4f} {devise}/tr  "
              f"t={t:+.2f}{'  ← significatif' if signif else ''}")
        w()

    # motifs comportementaux (descriptif, pour le verdict C)
    w("--- MOTIFS (descriptif) ---")
    dur_g = duree_min[net_n > 0]
    dur_p = duree_min[net_n < 0]
    w(f"durée médiane gagnants {dur_g.median():.1f} min vs perdants "
      f"{dur_p.median():.1f} min")
    w(f"part de longs : {(pos['sens'] == 'long').mean() * 100:.0f} %")
    par_h = pos.groupby("heure_entree")["_net_n"].count()
    w(f"heures les plus tradées : "
      f"{', '.join(f'{h}h ({n})' for h, n in par_h.nlargest(3).items())}")
    w(f"trades par jour calendaire : {len(pos) / 5:.0f}")
    w()

    # ---------------- verdict ----------------
    w("=" * 72)
    w("VERDICT")
    w("=" * 72)
    if net_n.mean() > 0 and z_tem > 2:
        w("A) Espérance normalisée POSITIVE et > 2 σ au-dessus du témoin : "
          "edge discrétionnaire réel, le problème était le sizing.")
        b = abs(gains.mean() / pertes.mean())
        f_plein = p_hat - (1 - p_hat) / b
        f4 = f_plein / 4
        risque_min = abs(pertes.mean())
        capital_nec = risque_min / f4 if f4 > 0 else float("inf")
        w(f"   Kelly plein {f_plein:+.4f}, quart {f4:+.4f} → capital "
          f"nécessaire pour 0.01 lot : {capital_nec:.0f} {devise} ; gain "
          f"attendu {net_n.mean():+.4f} {devise}/trade à ce capital.")
    elif z_tem > -2:
        w("B) Espérance normalisée DANS LE BRUIT du témoin aléatoire : pas "
          "d'edge directionnel décelable ; la perte réelle est le coût "
          "cumulé (spread + commission + swap), amplifié par le sizing.")
    else:
        w("C) Espérance normalisée SOUS le témoin aléatoire : les décisions "
          "font pire que le hasard — voir les motifs ci-dessus (asymétrie "
          "des durées gagnants/perdants, biais de sens, heures de "
          "sur-trading).")
    w()
    w(f"COMPTEUR CUMULATIF FINAL : {n_essais}")

    (RACINE / "data" / "analyse_reel.txt").write_text(
        "\n".join(lignes) + "\n", encoding="utf-8")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
