"""Phase 8 — familles demandées par le propriétaire (Fibonacci, RSI),
testées HORS LIGNE avant toute promotion en live.

GRILLES CLOSES, déclarées avant simulation (compteur cumulatif : 44
après la config live v2 ; ici hypothèses n° 45-50) :

  J  Retracement de Fibonacci (M5) — niveaux DÉRIVÉS DES DONNÉES :
     jambe = [min, max] des W dernières barres (sens = extrême le plus
     récent) ; entrée quand le close touche le niveau de retracement
     (tolérance 0.2×ATR), direction = reprise de la jambe ;
     stop 0.5×ATR14, RR 2, heures Levier A.
     Grille : ratio ∈ {0.382, 0.618} × W ∈ {48, 96}          [4]
  K  RSI(14) M5 en retour à la moyenne : long si RSI < s, short si
     RSI > 100−s ; stop 0.5×ATR14, RR 2, heures Levier A.
     Grille : s ∈ {30, 20}                                    [2]

Protocole identique phase 5 : walk-forward 5 blocs (tests 2-5, purge
1 j), témoin par permutation de signes (20 graines) pour tout candidat
positif, correction du nombre d'essais (N = 50 → t > √(2·ln 50) =
2.80), stress P95, exécutabilité quart-Kelly. Cinq conditions, quatre
sur cinq = échec.

Aucun accès MT5 (relit data/barres_m5.csv, arrêtées au 19/08).
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

COMPTEUR_AVANT = 44
N_GRAINES = 20


def signaux_fibonacci(df, W, ratio):
    """Retracement d'une jambe détectée dans les W dernières barres.

    Jambe haussière (le max est plus récent que le min) : niveau =
    hh − ratio×(hh−ll) ; signal LONG quand le close revient toucher le
    niveau (± 0.2×ATR). Symétrique pour la jambe baissière.
    Tout est calculé sur les barres [i−W, i−1] : aucun lookahead.
    """
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    atr = df["atr"].to_numpy()
    n = len(df)
    sig = np.zeros(n, dtype=np.int8)
    hh = pd.Series(h).rolling(W).max().shift(1).to_numpy()
    ll = pd.Series(l).rolling(W).min().shift(1).to_numpy()
    i_hh = pd.Series(h).rolling(W).apply(np.argmax, raw=True).shift(1).to_numpy()
    i_ll = pd.Series(l).rolling(W).apply(np.argmin, raw=True).shift(1).to_numpy()
    for i in range(W + 1, n):
        if not (np.isfinite(hh[i]) and np.isfinite(ll[i])
                and np.isfinite(atr[i])):
            continue
        ampleur = hh[i] - ll[i]
        if ampleur <= 2 * atr[i]:          # jambe trop petite : bruit
            continue
        tol = 0.2 * atr[i]
        if i_hh[i] > i_ll[i]:              # jambe haussière, le max récent
            niveau = hh[i] - ratio * ampleur
            if abs(c[i] - niveau) <= tol:
                sig[i] = 1                 # reprise attendue vers le haut
        else:                              # jambe baissière
            niveau = ll[i] + ratio * ampleur
            if abs(c[i] - niveau) <= tol:
                sig[i] = -1
    return sig


def signaux_rsi(df, seuil):
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    perte = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / perte.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    sig = np.zeros(len(df), dtype=np.int8)
    sig[(rsi < seuil).to_numpy(na_value=False)] = 1
    sig[(rsi > 100 - seuil).to_numpy(na_value=False)] = -1
    return sig


def main():
    m2 = json.loads((RACINE / "data" / "mesure_phase2.json")
                    .read_text(encoding="utf-8"))
    v1usd = m2["valeur_1usd_volume_min"]
    la = json.loads((RACINE / "data" / "levier_a.json")
                    .read_text(encoding="utf-8"))
    heures_ok = set(la["heures_ok"])
    sp = pd.read_csv(RACINE / "data" / "spread_horaire.csv")
    cout_med = dict(zip(sp["heure_serveur"], sp["mediane"]))
    cout_p95 = dict(zip(sp["heure_serveur"], sp["p95"]))

    df5 = preparer(pd.read_csv(RACINE / "data" / "barres_m5.csv"), 300, "M5")
    blocs = blocs_temporels(df5)

    configs = []
    for W in (48, 96):
        for ratio in (0.382, 0.618):
            configs.append({"id": f"J-fibo-W{W}-r{ratio}",
                            "sig": signaux_fibonacci(df5, W, ratio)})
    for s in (30, 20):
        configs.append({"id": f"K-rsi-{s}", "sig": signaux_rsi(df5, s)})

    n_essais = COMPTEUR_AVANT + len(configs)
    seuil_bruit = math.sqrt(2 * math.log(n_essais))
    kw = {"mult_stop": 0.5, "rr": 2.0, "sortie": "tp", "heures_ok": heures_ok}

    lignes = []
    w = lignes.append
    w("=" * 72)
    w("PHASE 8 — FIBONACCI ET RSI, WALK-FORWARD HORS LIGNE")
    w("=" * 72)
    w(f"compteur cumulatif : {COMPTEUR_AVANT} + {len(configs)} = {n_essais} "
      f"→ t requis > {seuil_bruit:.2f}")
    w("stop 0.5×ATR14 M5, RR 2, heures Levier A ; données jusqu'au 19/08")
    w("")
    w(f"{'config':<20} {'n':>5} {'p̂':>6} {'esp/tr':>8} {'t':>6} {'blocs+':>7}")

    resultats = []
    for cfg in configs:
        trades = simuler5(df5, cfg["sig"], cout_heure=cout_med, ut="M5", **kw)
        oos, par_bloc = restreindre_test(trades, blocs)
        m = metriques(oos, v1usd, CAPITAL_REF_EUR)
        m["t"] = t_stat(oos, v1usd) if oos else float("nan")
        m["blocs_pos"] = sum(1 for b in par_bloc
                             if b and sum(tr["pnl_usd"] for tr in b) > 0)
        m["n_blocs"] = sum(1 for b in par_bloc if b)
        resultats.append({"cfg": cfg, "oos": oos, "m": m})
        if m["n"] == 0:
            w(f"{cfg['id']:<20}     0  — aucun trade OOS")
        else:
            w(f"{cfg['id']:<20} {m['n']:>5} {m['p_hat']:>6.3f} "
              f"{m['esperance_eur']:>+7.3f}€ {m['t']:>+6.2f} "
              f"{m['blocs_pos']}/{m['n_blocs']}")
    w("")

    w("--- VÉRIFICATION DES CANDIDATS (espérance OOS > 0, n ≥ 20) ---")
    candidats = [r for r in resultats
                 if r["m"]["n"] >= 20 and r["m"]["esperance_eur"] > 0]
    if not candidats:
        w("aucun candidat.")
    for r in candidats:
        cfg, m = r["cfg"], r["m"]
        w(f"[{cfg['id']}] espérance {m['esperance_eur']:+.3f} EUR/trade, "
          f"n={m['n']}, t={m['t']:+.2f}")
        esps = []
        for g in range(N_GRAINES):
            tr_t = temoin_permutation(df5, cfg["sig"], 8000 + g,
                                      cout_heure=cout_med, ut="M5", **kw)
            oos_t, _ = restreindre_test(tr_t, blocs)
            if oos_t:
                esps.append(metriques(oos_t, v1usd,
                                      CAPITAL_REF_EUR)["esperance_eur"])
        esps = np.array(esps)
        z = ((m["esperance_eur"] - esps.mean()) / esps.std()
             if esps.std() > 0 else float("nan"))
        c2 = z > 2.0
        w(f"    témoin : {esps.mean():+.3f} ± {esps.std():.3f} → "
          f"{z:+.1f} σ {'✓' if c2 else '✗'}")
        c3 = m["t"] > seuil_bruit
        w(f"    correction essais : t={m['t']:+.2f} vs {seuil_bruit:.2f} "
          f"{'✓' if c3 else '✗'}")
        tr_s = simuler5(df5, cfg["sig"], cout_heure=cout_p95, ut="M5", **kw)
        oos_s, _ = restreindre_test(tr_s, blocs)
        m_s = metriques(oos_s, v1usd, CAPITAL_REF_EUR)
        c4 = m_s["n"] > 0 and m_s["esperance_eur"] > 0
        w(f"    stress P95 : {m_s.get('esperance_eur', float('nan')):+.3f} "
          f"EUR/trade {'✓' if c4 else '✗'}")
        kq = kelly_quart(m, CAPITAL_REF_EUR, 0.01, 0.01)
        c5 = kq["verdict"].startswith("EXÉCUTABLE")
        w(f"    exécutabilité : {kq['verdict']} {'✓' if c5 else '✗'}")
        w(f"    VERDICT : {'POSITIF (5/5)' if all([c2, c3, c4, c5]) else 'ÉCHEC'}")
        w("")

    w(f"COMPTEUR CUMULATIF : {n_essais}")
    texte = "\n".join(lignes) + "\n"
    (RACINE / "data" / "phase8_resultats.txt").write_text(texte,
                                                          encoding="utf-8")
    print(texte)


if __name__ == "__main__":
    main()
