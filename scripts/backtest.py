"""Phase 4 — backtest, pandas pur. LECTURE SEULE côté MT5 (données).

Protocole (voir aussi CLAUDE.md) :
- 14 hypothèses déclarées A PRIORI, comptées, jamais étendues en cours
  de route :
    A. cassure Donchian M5, N ∈ {12,24,48} × RR ∈ {2,3}, stop 0.5×ATR14
    B. retour à la moyenne z-score M5 (SMA/σ 48), z ∈ {2.0,2.5} ×
       RR ∈ {1,2}, stop 0.5×ATR14
    C. cassure Donchian M1, N ∈ {30,60} × RR ∈ {2,3}, stop 1.0×ATR14
  Les multiplicateurs de stop viennent de la phase 3 (zone exécutable
  quart-Kelly ≈ 1.7–3 $) et ne sont PAS optimisés.
- Découpage temporel : 60 % in-sample / 40 % out-of-sample. La sélection
  (meilleure espérance IS par famille) ne regarde que l'IS ; l'OOS n'est
  rapporté que pour les sélectionnés.
- Coût : spread MÉDIAN de l'heure serveur d'entrée (mesure phase 2),
  payé une fois par aller-retour ; stress au P95 horaire pour les
  sélectionnés.
- Exécution : barres bid ; long exécuté à open+spread, short à open ;
  stop/objectif relatifs au prix d'exécution ; si stop ET objectif
  touchés dans la même barre → PERTE (conservateur).
- Intraday strict : clôture forcée au dernier bar avant la pause
  quotidienne (23h serveur) → aucun swap ; entrée bloquée s'il reste
  moins de MIN_BARRES_RESTANTES dans la session.
- Sizing : AUCUNE taille a priori. Quart de Kelly sur le taux de
  réussite OOS ; si la taille < volume_min = 0.01 lot, la stratégie est
  NON EXÉCUTABLE — jamais d'arrondi vers le haut. Les espérances par
  trade sont rapportées au volume_min (plancher physique).

Sorties : data/backtest_resultats.txt, data/backtest_is.csv.
"""

import json
import math
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from config import CAPITAL_REF_EUR, SYMBOL
from connect import connect, disconnect

PART_IS = 0.60
PERIODE_ATR = 14
MIN_BARRES_RESTANTES = {"M1": 30, "M5": 6}   # ~30 min avant fin de session
FRACTION_KELLY = 0.25

HYPOTHESES = []
for n in (12, 24, 48):
    for rr in (2.0, 3.0):
        HYPOTHESES.append({"id": f"A-don-M5-N{n}-RR{rr:.0f}", "famille": "A",
                           "ut": "M5", "type": "donchian", "N": n,
                           "rr": rr, "mult_stop": 0.5})
for z in (2.0, 2.5):
    for rr in (1.0, 2.0):
        HYPOTHESES.append({"id": f"B-zscore-M5-z{z}-RR{rr:.0f}", "famille": "B",
                           "ut": "M5", "type": "zscore", "N": 48, "z": z,
                           "rr": rr, "mult_stop": 0.5})
for n in (30, 60):
    for rr in (2.0, 3.0):
        HYPOTHESES.append({"id": f"C-don-M1-N{n}-RR{rr:.0f}", "famille": "C",
                           "ut": "M1", "type": "donchian", "N": n,
                           "rr": rr, "mult_stop": 1.0})


def champ(obj, nom):
    d = obj._asdict()
    if nom not in d:
        raise AttributeError(f"Champ '{nom}' absent de {type(obj).__name__}. "
                             f"Champs réels : {sorted(d.keys())}")
    return d[nom]


def charger_donnees():
    """Barres M1/M5 fraîches + garde-fous, sauvegardées dans data/."""
    connect()
    terminal = mt5.terminal_info()
    if terminal is None:
        raise RuntimeError(f"terminal_info() None : {mt5.last_error()}")
    maxbars = champ(terminal, "maxbars")
    barres = {}
    for ut, tf, nb in (("M1", mt5.TIMEFRAME_M1, 99_000),
                       ("M5", mt5.TIMEFRAME_M5, 25_000)):
        nb_eff = min(nb, maxbars - 1000)
        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, nb_eff)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"copy_rates_from_pos({ut}) : "
                               f"{mt5.last_error()}")
        df = pd.DataFrame({k: rates[k] for k in
                           ("time", "open", "high", "low", "close")})
        df.to_csv(RACINE / "data" / f"barres_{ut.lower()}.csv", index=False)
        barres[ut] = df
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        raise RuntimeError(f"symbol_info : {mt5.last_error()}")
    volume_min = champ(info, "volume_min")
    volume_step = champ(info, "volume_step")
    disconnect()
    return barres, volume_min, volume_step


def preparer(df, tf_s, ut):
    """ATR14 Wilder, heure serveur, sessions (pause quotidienne/week-end)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1.0 / PERIODE_ATR, adjust=False).mean()
    df.loc[df.index[:PERIODE_ATR * 3], "atr"] = np.nan   # warm-up purgé
    dt = pd.to_datetime(df["time"], unit="s")
    df["heure"] = dt.dt.hour.to_numpy()
    saut = df["time"].diff().fillna(tf_s) > 3 * tf_s
    df["session"] = saut.cumsum().to_numpy()
    # fin_session[i] = dernier indice de la session de i (parcours inversé)
    sess = df["session"].to_numpy()
    fin = np.zeros(len(df), dtype=np.int64)
    dernier = len(df) - 1
    for i in range(len(df) - 1, -1, -1):
        fin[i] = dernier
        if i > 0 and sess[i - 1] != sess[i]:
            dernier = i - 1
    df["fin_session"] = fin
    return df


def signaux_donchian(df, N):
    haut = df["high"].rolling(N).max().shift(1)
    bas = df["low"].rolling(N).min().shift(1)
    sig = np.zeros(len(df), dtype=np.int8)
    sig[(df["close"] > haut).to_numpy()] = 1
    sig[(df["close"] < bas).to_numpy()] = -1
    return sig


def signaux_zscore(df, N, seuil):
    ma = df["close"].rolling(N).mean()
    sd = df["close"].rolling(N).std()
    z = (df["close"] - ma) / sd
    sig = np.zeros(len(df), dtype=np.int8)
    sig[(z < -seuil).to_numpy()] = 1      # sur-vendu → long (retour)
    sig[(z > seuil).to_numpy()] = -1
    return sig


def simuler(df, sig, mult_stop, rr, cout_heure, ut):
    """Simulation séquentielle, une position à la fois. Retourne les trades."""
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    atr = df["atr"].to_numpy()
    heure = df["heure"].to_numpy()
    sess = df["session"].to_numpy()
    fin_s = df["fin_session"].to_numpy()
    t = df["time"].to_numpy()
    min_rest = MIN_BARRES_RESTANTES[ut]

    trades = []
    n_skip_stop, n_skip_fin = 0, 0
    n = len(df)
    i = 1
    while i < n - 1:
        d = int(sig[i])
        if d == 0:
            i += 1
            continue
        k = i + 1
        if sess[k] != sess[i]:
            i = k
            continue
        if fin_s[k] - k < min_rest:
            n_skip_fin += 1
            i = k
            continue
        cout = cout_heure.get(int(heure[k]))
        if cout is None:
            raise RuntimeError(f"Pas de coût mesuré pour l'heure {heure[k]}")
        S = mult_stop * atr[i]
        if not np.isfinite(S) or S <= 0:
            i = k
            continue
        if S < 3 * cout:
            n_skip_stop += 1
            i = k
            continue

        if d == 1:
            entree = o[k] + cout            # achat au ask
            niv_stop, niv_tgt = entree - S, entree + rr * S
            fen_l, fen_h = l[k:fin_s[k] + 1], h[k:fin_s[k] + 1]
            touche_stop = fen_l <= niv_stop
            touche_tgt = fen_h >= niv_tgt
        else:
            entree = o[k]                    # vente au bid
            niv_stop, niv_tgt = entree + S, entree - rr * S
            fen_l, fen_h = l[k:fin_s[k] + 1], h[k:fin_s[k] + 1]
            touche_stop = fen_h >= niv_stop - cout   # rachat au ask
            touche_tgt = fen_l <= niv_tgt - cout

        j_stop = int(np.argmax(touche_stop)) if touche_stop.any() else -1
        j_tgt = int(np.argmax(touche_tgt)) if touche_tgt.any() else -1

        if j_stop >= 0 and (j_tgt < 0 or j_stop <= j_tgt):
            issue, pnl_usd, j_exit = "perte", -S, k + j_stop
        elif j_tgt >= 0:
            issue, pnl_usd, j_exit = "gain", rr * S, k + j_tgt
        else:
            j_exit = fin_s[k]                # clôture forcée fin de session
            if d == 1:
                pnl_usd = c[j_exit] - entree
            else:
                pnl_usd = entree - (c[j_exit] + cout)
            issue = "forcee"
        trades.append({"i_entree": k, "t_entree": int(t[k]), "dir": d,
                       "stop_usd": S, "cout_usd": cout, "issue": issue,
                       "pnl_usd": pnl_usd})
        i = j_exit + 1
    return trades, n_skip_stop, n_skip_fin


def metriques(trades, v1usd, capital):
    if not trades:
        return {"n": 0}
    pnl_eur = np.array([tr["pnl_usd"] for tr in trades]) * v1usd
    couts_eur = np.array([tr["cout_usd"] for tr in trades]) * v1usd
    issues = [tr["issue"] for tr in trades]
    n_g = issues.count("gain")
    n_p = issues.count("perte")
    n_f = issues.count("forcee")
    equite = np.cumsum(pnl_eur)
    pic = np.maximum.accumulate(np.concatenate([[0.0], equite]))[1:]
    dd_max = float(np.max(pic - equite)) if len(equite) else 0.0
    gains = pnl_eur[[i for i, s in enumerate(issues) if s == "gain"]]
    pertes = pnl_eur[[i for i, s in enumerate(issues) if s == "perte"]]
    return {
        "n": len(trades), "n_gains": n_g, "n_pertes": n_p, "n_forcees": n_f,
        "p_hat": n_g / (n_g + n_p) if (n_g + n_p) else float("nan"),
        "esperance_eur": float(pnl_eur.mean()),
        "pnl_total_eur": float(pnl_eur.sum()),
        "cout_total_eur": float(couts_eur.sum()),
        "gain_moyen_eur": float(gains.mean()) if len(gains) else float("nan"),
        "perte_moyenne_eur": float(-pertes.mean()) if len(pertes) else float("nan"),
        "dd_max_eur": dd_max,
        "dd_max_pct": dd_max / capital * 100,
    }


def kelly_quart(m, capital, volume_min, volume_step):
    """Taille quart-Kelly depuis les métriques OOS. Jamais arrondi vers le haut."""
    if m["n"] == 0 or math.isnan(m["p_hat"]):
        return {"verdict": "NON ÉVALUABLE (aucun trade résolu)"}
    if math.isnan(m["gain_moyen_eur"]) or math.isnan(m["perte_moyenne_eur"]) \
            or m["perte_moyenne_eur"] <= 0:
        return {"verdict": "NON ÉVALUABLE (distribution dégénérée)"}
    b = m["gain_moyen_eur"] / m["perte_moyenne_eur"]
    p = m["p_hat"]
    f_plein = p - (1 - p) / b
    if f_plein <= 0:
        return {"verdict": "NON EXÉCUTABLE (Kelly ≤ 0 : espérance binaire "
                           "nulle ou négative)", "f_plein": f_plein}
    f = f_plein * FRACTION_KELLY
    budget_risque = f * capital
    # perte_moyenne_eur est mesurée au volume_min : risque par lot min.
    volume_brut = budget_risque / m["perte_moyenne_eur"] * volume_min
    volume = math.floor(volume_brut / volume_step) * volume_step
    if volume < volume_min:
        return {"verdict": f"NON EXÉCUTABLE (quart-Kelly = {volume_brut:.4f} "
                           f"lot < volume_min {volume_min})",
                "f_plein": f_plein, "volume_brut": volume_brut}
    return {"verdict": f"EXÉCUTABLE à {volume:.2f} lot",
            "f_plein": f_plein, "volume_brut": volume_brut, "volume": volume}


def main():
    m2 = json.loads((RACINE / "data" / "mesure_phase2.json")
                    .read_text(encoding="utf-8"))
    v1usd = m2["valeur_1usd_volume_min"]
    sp = pd.read_csv(RACINE / "data" / "spread_horaire.csv")
    cout_med = dict(zip(sp["heure_serveur"], sp["mediane"]))
    cout_p95 = dict(zip(sp["heure_serveur"], sp["p95"]))

    barres, volume_min, volume_step = charger_donnees()
    tf_secondes = {"M1": 60, "M5": 300}
    for ut in barres:
        barres[ut] = preparer(barres[ut], tf_secondes[ut], ut)

    lignes = []

    def w(t=""):
        lignes.append(t)

    w("=" * 72)
    w("PHASE 4 — BACKTEST (in-sample 60 % / out-of-sample 40 %)")
    w("=" * 72)
    w()
    w(f"NOMBRE D'HYPOTHÈSES TESTÉES : {len(HYPOTHESES)} "
      "(déclarées avant toute simulation, grille close)")
    w("sélection : meilleure espérance IS par famille ; l'OOS n'est lu que "
      "pour les 3 sélectionnées ; stress de coût (P95 horaire) sur les "
      "sélectionnées uniquement")
    w(f"coût par trade : spread médian de l'heure serveur d'entrée ; "
      f"conversion {v1usd:.4f} EUR par $ (volume_min {volume_min})")
    w("intraday strict (clôture forcée avant la pause 23h serveur) → swap nul")
    w()
    for ut, df in barres.items():
        d0 = pd.to_datetime(int(df['time'].iloc[0]), unit='s')
        d1 = pd.to_datetime(int(df['time'].iloc[-1]), unit='s')
        i_split = int(len(df) * PART_IS)
        t_split = pd.to_datetime(int(df['time'].iloc[i_split]), unit='s')
        w(f"{ut} : {len(df)} barres, {d0:%Y-%m-%d} → {d1:%Y-%m-%d} "
          f"(heure serveur), frontière IS/OOS : {t_split:%Y-%m-%d %H:%M}")
    w()

    # ---------- Simulation des 14 hypothèses ----------
    resultats = []
    for hyp in HYPOTHESES:
        df = barres[hyp["ut"]]
        if hyp["type"] == "donchian":
            sig = signaux_donchian(df, hyp["N"])
        else:
            sig = signaux_zscore(df, hyp["N"], hyp["z"])
        trades, n_skip_stop, n_skip_fin = simuler(
            df, sig, hyp["mult_stop"], hyp["rr"], cout_med, hyp["ut"])
        i_split = int(len(df) * PART_IS)
        t_is = [tr for tr in trades if tr["i_entree"] < i_split]
        t_oos = [tr for tr in trades if tr["i_entree"] >= i_split]
        resultats.append({
            "hyp": hyp, "trades_is": t_is, "trades_oos": t_oos,
            "m_is": metriques(t_is, v1usd, CAPITAL_REF_EUR),
            "m_oos": metriques(t_oos, v1usd, CAPITAL_REF_EUR),
            "n_skip_stop": n_skip_stop, "n_skip_fin": n_skip_fin,
        })

    w("--- IN-SAMPLE : les 14 hypothèses ---")
    w(f"{'hypothèse':<22} {'n':>5} {'p̂':>6} {'esp/tr':>8} {'coût tot':>9} "
      f"{'DD max':>7} {'forcées':>7}")
    lignes_csv = []
    for r in resultats:
        m = r["m_is"]
        if m["n"] == 0:
            w(f"{r['hyp']['id']:<22} {'0':>5}  — aucun trade IS")
            continue
        w(f"{r['hyp']['id']:<22} {m['n']:>5} {m['p_hat']:>6.3f} "
          f"{m['esperance_eur']:>+7.3f}€ {m['cout_total_eur']:>8.2f}€ "
          f"{m['dd_max_pct']:>6.1f}% {m['n_forcees']:>7}")
        lignes_csv.append({"id": r["hyp"]["id"], "segment": "IS", **m})
    w()

    # ---------- Sélection par famille (IS uniquement) ----------
    selection = {}
    for fam in ("A", "B", "C"):
        cands = [r for r in resultats
                 if r["hyp"]["famille"] == fam and r["m_is"]["n"] >= 30]
        if not cands:
            w(f"famille {fam} : aucune hypothèse avec ≥ 30 trades IS — "
              "famille écartée.")
            continue
        selection[fam] = max(cands, key=lambda r: r["m_is"]["esperance_eur"])
    w()

    # ---------- OOS des sélectionnées + Kelly + stress ----------
    w("--- OUT-OF-SAMPLE : sélectionnées uniquement ---")
    for fam, r in selection.items():
        hyp = r["hyp"]
        mi, mo = r["m_is"], r["m_oos"]
        w(f"[{fam}] {hyp['id']}")
        w(f"    IS  : {mi['n']:>4} trades | p̂ {mi['p_hat']:.3f} | "
          f"espérance {mi['esperance_eur']:+.3f} EUR/trade | "
          f"coût {mi['cout_total_eur']:.2f} EUR | DD {mi['dd_max_pct']:.1f} %")
        if mo["n"] == 0:
            w("    OOS : aucun trade")
            continue
        w(f"    OOS : {mo['n']:>4} trades | p̂ {mo['p_hat']:.3f} | "
          f"espérance {mo['esperance_eur']:+.3f} EUR/trade | "
          f"coût {mo['cout_total_eur']:.2f} EUR | DD {mo['dd_max_pct']:.1f} % "
          f"| forcées {mo['n_forcees']}")
        lignes_csv.append({"id": hyp["id"], "segment": "OOS", **mo})
        k = kelly_quart(mo, CAPITAL_REF_EUR, volume_min, volume_step)
        w(f"    quart-Kelly OOS : {k['verdict']}")
        if "f_plein" in k and not math.isnan(k.get("f_plein", float("nan"))):
            w(f"      (Kelly plein f* = {k['f_plein']:+.4f} ; quart = "
              f"{k['f_plein'] * FRACTION_KELLY:+.4f} du capital)")

        # stress : coût P95 horaire
        df = barres[hyp["ut"]]
        if hyp["type"] == "donchian":
            sig = signaux_donchian(df, hyp["N"])
        else:
            sig = signaux_zscore(df, hyp["N"], hyp["z"])
        trades_s, _, _ = simuler(df, sig, hyp["mult_stop"], hyp["rr"],
                                 cout_p95, hyp["ut"])
        i_split = int(len(df) * PART_IS)
        mo_s = metriques([t for t in trades_s if t["i_entree"] >= i_split],
                         v1usd, CAPITAL_REF_EUR)
        if mo_s["n"]:
            w(f"    stress coût P95 : espérance OOS "
              f"{mo_s['esperance_eur']:+.3f} EUR/trade "
              f"(p̂ {mo_s['p_hat']:.3f}, {mo_s['n']} trades)")
        w()

    pd.DataFrame(lignes_csv).to_csv(RACINE / "data" / "backtest_is.csv",
                                    index=False)
    (RACINE / "data" / "backtest_resultats.txt").write_text(
        "\n".join(lignes) + "\n", encoding="utf-8")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
