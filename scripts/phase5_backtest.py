"""Phase 5, LEVIER B — familles nouvelles, protocole walk-forward.

GRILLES CLOSES, déclarées ici avant toute simulation (compteur cumulatif
14 → 37 ; les témoins, stress et analyses descriptives ne comptent pas) :

  D  imbalance de flux (M1, période ticks) : W ∈ {5,15} min ×
     seuil ∈ {0.65,0.75}, direction = signe de l'imbalance, RR 2,
     stop 1.0×ATR14(M1), heures Levier A.                       [4]
  E  burst d'intensité (M1) : k ∈ {2,3} × ratio n_ticks/moyenne 60 min,
     direction = signe du rendement de la minute du burst, RR 2,
     stop 1.0×ATR, heures Levier A.                             [2]
  F  élargissement du spread, CONTINUATION (M1) : z ∈ {1.5,2.5},
     direction = signe du rendement minute, RR 2, stop 1.0×ATR,
     heures Levier A.                                           [2]
  F2 élargissement du spread, RENVERSEMENT (M1) : z ∈ {2.5,3.0},
     direction opposée au rendement minute. DATA-SUGGESTED : famille
     née de l'inspection descriptive des mêmes 15 jours — tout
     résultat positif est non probant et devra être revalidé sur des
     ticks futurs.                                              [2]
  G  saisonnalité horaire (M5, toutes heures — coût facturé à l'heure
     réelle, ce qui rend la restriction Levier A superflue ici) :
     seuil |t| train ∈ {2.0,2.5}, direction = signe du biais train,
     stop 0.5×ATR(M5), sortie à la fin de l'heure.              [2]
  H  conditionnement au régime ATR (M5) : règles phase 4
     {Donchian N12 RR3, z-score 48/2.5 RR2} × terciles {bas,moyen,haut}
     de l'ATR14 courant vs distribution train, stop 0.5×ATR,
     heures Levier A.                                           [6]
  I  structure de sortie (M5, heures Levier A, stop 0.5×ATR) :
     Donchian N12 × {temps 6, temps 24, suiveur 0.5×ATR} +
     z-score 48/2.5 × {temps 6, temps 24}.                      [5]

Walk-forward : 5 blocs temporels égaux, tests sur les blocs 2..5
(4 fenêtres), purge de 1 jour entre fin de train et début de test pour
toute quantité estimée (biais horaires de G, terciles de H).

Cinq conditions simultanées pour déclarer un positif : (1) espérance
walk-forward OOS > 0 ; (2) > 2 σ au-dessus du témoin (20 graines,
permutation des signes à timing identique) ; (3) survie à la correction
du nombre d'essais (t > √(2·ln N), N = 37, + Deflated Sharpe Ratio si
n ≥ 50) ; (4) espérance > 0 au coût P95 horaire ; (5) quart de Kelly
≥ 0.01 lot sur 100 EUR. Quatre sur cinq = échec.

Aucun accès MT5 (relit les données sauvegardées). Aucun ordre.
"""

import json
import math
import statistics
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "scripts"))

import numpy as np
import pandas as pd

from config import CAPITAL_REF_EUR
from backtest import (kelly_quart, metriques, preparer, signaux_donchian,
                      signaux_zscore)
from backtest import simuler as simuler_phase4

COMPTEUR_PRECEDENT = 14
N_BLOCS = 5
PURGE_S = 86_400
N_GRAINES = 20
MIN_TICKS_IMB = 5          # par minute de fenêtre, pour un imbalance valide
NORMALE = statistics.NormalDist()


# ----------------------------------------------------------------------
# Simulateur phase 5 : étend la sémantique phase 4 (mêmes conventions de
# coût : long payé à l'entrée, short à la sortie ; stop prioritaire).
# ----------------------------------------------------------------------
def simuler5(df, sig, mult_stop, cout_heure, ut, rr=None, heures_ok=None,
             sortie="tp", n_hold=None):
    from backtest import MIN_BARRES_RESTANTES
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
            i = k
            continue
        if heures_ok is not None and int(heure[k]) not in heures_ok:
            i = k
            continue
        cout = cout_heure.get(int(heure[k]))
        if cout is None:
            raise RuntimeError(f"Pas de coût pour l'heure {heure[k]}")
        S = mult_stop * atr[i]
        if not np.isfinite(S) or S <= 0 or S < 3 * cout:
            i = k
            continue

        if sortie == "heure":
            j_fin = k
            while j_fin < fin_s[k] and heure[j_fin + 1] == heure[k]:
                j_fin += 1
        elif sortie == "temps":
            j_fin = min(k + n_hold, fin_s[k])
        else:
            j_fin = fin_s[k]

        entree = o[k] + cout if d == 1 else o[k]
        issue = None

        if sortie == "tp":
            if d == 1:
                stop_l, tgt_l = entree - S, entree + rr * S
                t_stop = l[k:j_fin + 1] <= stop_l
                t_tgt = h[k:j_fin + 1] >= tgt_l
            else:
                stop_l, tgt_l = entree + S, entree - rr * S
                t_stop = h[k:j_fin + 1] >= stop_l - cout
                t_tgt = l[k:j_fin + 1] <= tgt_l - cout
            js = int(np.argmax(t_stop)) if t_stop.any() else -1
            jt = int(np.argmax(t_tgt)) if t_tgt.any() else -1
            if js >= 0 and (jt < 0 or js <= jt):
                issue, pnl, j_exit = "perte", -S, k + js
            elif jt >= 0:
                issue, pnl, j_exit = "gain", rr * S, k + jt
        elif sortie in ("temps", "heure"):
            if d == 1:
                t_stop = l[k:j_fin + 1] <= entree - S
            else:
                t_stop = h[k:j_fin + 1] >= entree + S - cout
            js = int(np.argmax(t_stop)) if t_stop.any() else -1
            if js >= 0:
                issue, pnl, j_exit = "perte", -S, k + js
        elif sortie == "trail":
            if d == 1:
                stop_l = entree - S
                for j in range(k, j_fin + 1):
                    if l[j] <= stop_l:
                        pnl, j_exit = stop_l - entree, j
                        issue = "gain" if pnl > 0 else "perte"
                        break
                    stop_l = max(stop_l, h[j] - S)
            else:
                stop_l = entree + S
                for j in range(k, j_fin + 1):
                    if h[j] >= stop_l - cout:
                        pnl, j_exit = entree - stop_l, j
                        issue = "gain" if pnl > 0 else "perte"
                        break
                    stop_l = min(stop_l, l[j] + S)
        else:
            raise ValueError(f"sortie inconnue : {sortie}")

        if issue is None:              # sortie au temps / fin de fenêtre
            j_exit = j_fin
            pnl = (c[j_exit] - entree) if d == 1 else (entree - c[j_exit] - cout)
            issue = "gain" if pnl > 0 else "perte"
            if j_fin == fin_s[k] and sortie in ("tp", "trail"):
                issue = "forcee"
        trades.append({"i_entree": k, "t_entree": int(t[k]), "dir": d,
                       "stop_usd": S, "cout_usd": cout, "issue": issue,
                       "pnl_usd": pnl})
        i = j_exit + 1
    return trades


# ----------------------------------------------------------------------
def charger_minutes():
    m = pd.read_csv(RACINE / "data" / "minutes.csv")
    m = m.sort_values("minute").reset_index(drop=True)
    base_int = m["n_ticks"].rolling(60, min_periods=30).mean().shift(1)
    m["ratio_int"] = m["n_ticks"] / base_int
    mu = m["spread_moy"].rolling(60, min_periods=30).mean().shift(1)
    sd = m["spread_moy"].rolling(60, min_periods=30).std().shift(1)
    m["z_spread"] = (m["spread_moy"] - mu) / sd
    for w in (5, 15):
        u = m["n_up"].rolling(w).sum()
        dn = m["n_down"].rolling(w).sum()
        tot = u + dn
        imb = np.where(tot >= MIN_TICKS_IMB * w, (u - dn) / tot, np.nan)
        m[f"imb_{w}"] = imb
    return m


def sig_depuis_minutes(df_m1, minutes, colonne, condition, direction):
    """Aligne un signal minute sur les barres M1 (bar i ← minute time[i])."""
    idx = minutes.set_index("minute")
    aligne = idx.reindex(df_m1["time"].to_numpy())
    sig = np.zeros(len(df_m1), dtype=np.int8)
    val = aligne[colonne].to_numpy()
    ret = aligne["ret"].to_numpy()
    ok = np.isfinite(val) & condition(val)
    if direction == "signe_valeur":
        sig[ok & (val > 0)] = 1
        sig[ok & (val < 0)] = -1
    elif direction == "signe_ret":
        ok = ok & np.isfinite(ret) & (ret != 0)
        sig[ok] = np.sign(ret[ok]).astype(np.int8)
    elif direction == "contre_ret":
        ok = ok & np.isfinite(ret) & (ret != 0)
        sig[ok] = (-np.sign(ret[ok])).astype(np.int8)
    else:
        raise ValueError(direction)
    return sig


def blocs_temporels(df):
    t0, t1 = int(df["time"].iloc[0]), int(df["time"].iloc[-1])
    bornes = [t0 + (t1 - t0) * k // N_BLOCS for k in range(N_BLOCS + 1)]
    return [(bornes[k], bornes[k + 1]) for k in range(N_BLOCS)]


def restreindre_test(trades, blocs):
    """Ne garde que les trades entrés dans les blocs de test (2..5)."""
    tests = blocs[1:]
    garde, par_bloc = [], [[] for _ in tests]
    for tr in trades:
        for b, (a, z) in enumerate(tests):
            if a <= tr["t_entree"] < z:
                garde.append(tr)
                par_bloc[b].append(tr)
                break
    return garde, par_bloc


def t_stat(trades, v1usd):
    pnl = np.array([tr["pnl_usd"] for tr in trades]) * v1usd
    if len(pnl) < 2 or pnl.std(ddof=1) == 0:
        return float("nan")
    return float(pnl.mean() / (pnl.std(ddof=1) / math.sqrt(len(pnl))))


def dsr(trades, v1usd, var_sr_essais, n_essais):
    """Deflated Sharpe Ratio (Bailey & López de Prado), par trade."""
    pnl = np.array([tr["pnl_usd"] for tr in trades]) * v1usd
    n = len(pnl)
    if n < 50 or pnl.std(ddof=1) == 0:
        return None
    sr = pnl.mean() / pnl.std(ddof=1)
    g3 = float(pd.Series(pnl).skew())
    g4 = float(pd.Series(pnl).kurt()) + 3.0
    gamma = 0.5772156649
    z1 = NORMALE.inv_cdf(1 - 1 / n_essais)
    z2 = NORMALE.inv_cdf(1 - 1 / (n_essais * math.e))
    sr0 = math.sqrt(max(var_sr_essais, 1e-12)) * ((1 - gamma) * z1 + gamma * z2)
    denom = math.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2, 1e-9))
    return NORMALE.cdf((sr - sr0) * math.sqrt(n - 1) / denom)


def temoin_permutation(df, sig, graine, **kw):
    rng = np.random.default_rng(graine)
    sig2 = sig.copy()
    nz = sig2 != 0
    sig2[nz] = rng.choice(np.array([-1, 1], dtype=np.int8), size=int(nz.sum()))
    return simuler5(df, sig2, **kw)


# ----------------------------------------------------------------------
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

    barres = {}
    for ut, tf_s in (("M1", 60), ("M5", 300)):
        barres[ut] = preparer(
            pd.read_csv(RACINE / "data" / f"barres_{ut.lower()}.csv"),
            tf_s, ut)
    minutes = charger_minutes()

    # --- contrôle de non-régression du simulateur ---
    df5 = barres["M5"]
    sig_ref = signaux_donchian(df5, 12)
    ref4 = simuler_phase4(df5, sig_ref, 0.5, 3.0, cout_med, "M5")[0]
    ref5 = simuler5(df5, sig_ref, 0.5, cout_med, "M5", rr=3.0, sortie="tp")
    p4 = sum(tr["pnl_usd"] for tr in ref4)
    p5 = sum(tr["pnl_usd"] for tr in ref5)
    if abs(p4 - p5) > 1e-9 or len(ref4) != len(ref5):
        raise RuntimeError(f"simuler5 diverge de la phase 4 : "
                           f"{len(ref4)}/{p4} vs {len(ref5)}/{p5}")

    lignes = []

    def w(t=""):
        lignes.append(t)

    w("=" * 72)
    w("PHASE 5 — RÉSULTATS WALK-FORWARD (voir en-tête du script pour les "
      "grilles closes)")
    w("=" * 72)
    w()
    w("contrôle de non-régression simulateur : OK (phase 4 reproduite à "
      "l'identique)")
    w(f"heures Levier A : {sorted(heures_ok)}")
    w()

    # ---------- saisonnalité descriptive (analyse, pas une hypothèse) ----
    w("--- ANALYSE SAISONNALITÉ (M5, plein échantillon, Bonferroni ×22) ---")
    df5 = barres["M5"]
    dt5 = pd.to_datetime(df5["time"], unit="s")
    aux = pd.DataFrame({"date": dt5.dt.date, "heure": df5["heure"],
                        "jour": dt5.dt.dayofweek,
                        "o": df5["open"], "c": df5["close"]})
    gh = aux.groupby(["date", "heure"])
    ret_h = (gh["c"].last() - gh["o"].first()).reset_index(name="ret")
    stats_h = ret_h.groupby("heure")["ret"].agg(["count", "mean", "std"])
    stats_h["t"] = stats_h["mean"] / (stats_h["std"] /
                                      np.sqrt(stats_h["count"]))
    seuil_bonf = NORMALE.inv_cdf(1 - 0.025 / 22)
    w(f"seuil de signification Bonferroni (α=5 %, 22 heures) : "
      f"|t| > {seuil_bonf:.2f}")
    signif = stats_h[np.abs(stats_h["t"]) > seuil_bonf]
    for h, r in stats_h.iterrows():
        marque = "  ← significatif" if abs(r["t"]) > seuil_bonf else ""
        w(f"  {h:02d}h : n={int(r['count']):>3}, moyenne {r['mean']:+.3f} $, "
          f"t={r['t']:+.2f}{marque}")
    if signif.empty:
        w("  → AUCUNE heure au biais significatif après Bonferroni.")
    gj = ret_h.merge(aux[["date", "jour"]].drop_duplicates(), on="date")
    par_jour = gj.groupby(["date", "jour"])["ret"].sum().reset_index()
    sj = par_jour.groupby("jour")["ret"].agg(["count", "mean", "std"])
    sj["t"] = sj["mean"] / (sj["std"] / np.sqrt(sj["count"]))
    noms = ["lun", "mar", "mer", "jeu", "ven"]
    w("  jour de semaine (rendement moyen par jour, $) :")
    for j, r in sj.iterrows():
        w(f"    {noms[int(j)]} : n={int(r['count'])}, {r['mean']:+.2f} $, "
          f"t={r['t']:+.2f}")
    w()

    # ---------- construction des 23 configurations ----------
    # M1 restreint à la période des ticks : découpe AVANT preparer(), car
    # fin_session/session indexent les positions du DataFrame préparé.
    configs = []
    m1_brut = pd.read_csv(RACINE / "data" / "barres_m1.csv")
    t_ticks_min = int(minutes["minute"].min())
    m1_ticks = preparer(
        m1_brut[m1_brut["time"] >= t_ticks_min].reset_index(drop=True),
        60, "M1")

    for W in (5, 15):
        for s in (0.65, 0.75):
            sig = sig_depuis_minutes(
                m1_ticks, minutes, f"imb_{W}",
                lambda v, s=s: np.abs(v) >= s, "signe_valeur")
            configs.append({"id": f"D-imb-W{W}-s{s}", "fam": "D",
                            "df": m1_ticks, "sig": sig, "ut": "M1",
                            "kw": {"mult_stop": 1.0, "rr": 2.0,
                                   "sortie": "tp", "heures_ok": heures_ok}})
    for kf in (2.0, 3.0):
        sig = sig_depuis_minutes(m1_ticks, minutes, "ratio_int",
                                 lambda v, kf=kf: v >= kf, "signe_ret")
        configs.append({"id": f"E-burst-k{kf:.0f}", "fam": "E",
                        "df": m1_ticks, "sig": sig, "ut": "M1",
                        "kw": {"mult_stop": 1.0, "rr": 2.0, "sortie": "tp",
                               "heures_ok": heures_ok}})
    for zf in (1.5, 2.5):
        sig = sig_depuis_minutes(m1_ticks, minutes, "z_spread",
                                 lambda v, zf=zf: v >= zf, "signe_ret")
        configs.append({"id": f"F-sprcont-z{zf}", "fam": "F",
                        "df": m1_ticks, "sig": sig, "ut": "M1",
                        "kw": {"mult_stop": 1.0, "rr": 2.0, "sortie": "tp",
                               "heures_ok": heures_ok}})
    for zf in (2.5, 3.0):
        sig = sig_depuis_minutes(m1_ticks, minutes, "z_spread",
                                 lambda v, zf=zf: v >= zf, "contre_ret")
        configs.append({"id": f"F2-sprrev-z{zf}", "fam": "F2",
                        "df": m1_ticks, "sig": sig, "ut": "M1",
                        "kw": {"mult_stop": 1.0, "rr": 2.0, "sortie": "tp",
                               "heures_ok": heures_ok}})

    # G : biais horaire, flags estimés par bloc (train < début bloc − purge)
    blocs5 = blocs_temporels(df5)
    for seuil_t in (2.0, 2.5):
        sig = np.zeros(len(df5), dtype=np.int8)
        heure_arr = df5["heure"].to_numpy()
        for (a, z) in blocs5[1:]:
            train = ret_h[ret_h.apply(
                lambda r: pd.Timestamp(r["date"]).timestamp() < a - PURGE_S,
                axis=1)]
            st = train.groupby("heure")["ret"].agg(["count", "mean", "std"])
            st = st[st["count"] >= 15]
            st["t"] = st["mean"] / (st["std"] / np.sqrt(st["count"]))
            flags = {int(h): int(np.sign(r["mean"]))
                     for h, r in st.iterrows() if abs(r["t"]) >= seuil_t}
            tarr = df5["time"].to_numpy()
            for i in range(1, len(df5) - 1):
                if not (a <= tarr[i + 1] < z):
                    continue
                hk = int(heure_arr[i + 1])
                if hk in flags and heure_arr[i] != hk:
                    sig[i] = flags[hk]
        configs.append({"id": f"G-heure-t{seuil_t}", "fam": "G",
                        "df": df5, "sig": sig, "ut": "M5",
                        "kw": {"mult_stop": 0.5, "sortie": "heure",
                               "heures_ok": None}})

    # H : régimes ATR (classification par trade, bornes train par bloc)
    regles_h = [("don12rr3", signaux_donchian(df5, 12),
                 {"mult_stop": 0.5, "rr": 3.0, "sortie": "tp",
                  "heures_ok": heures_ok}),
                ("z25rr2", signaux_zscore(df5, 48, 2.5),
                 {"mult_stop": 0.5, "rr": 2.0, "sortie": "tp",
                  "heures_ok": heures_ok})]
    for nom_r, sig_r, kw_r in regles_h:
        for regime in ("bas", "moyen", "haut"):
            configs.append({"id": f"H-{nom_r}-{regime}", "fam": "H",
                            "df": df5, "sig": sig_r, "ut": "M5",
                            "kw": kw_r, "regime": regime})

    # I : structure de sortie
    sig_don = signaux_donchian(df5, 12)
    sig_z = signaux_zscore(df5, 48, 2.5)
    for nh in (6, 24):
        configs.append({"id": f"I-don12-temps{nh}", "fam": "I", "df": df5,
                        "sig": sig_don, "ut": "M5",
                        "kw": {"mult_stop": 0.5, "sortie": "temps",
                               "n_hold": nh, "heures_ok": heures_ok}})
    configs.append({"id": "I-don12-trail", "fam": "I", "df": df5,
                    "sig": sig_don, "ut": "M5",
                    "kw": {"mult_stop": 0.5, "sortie": "trail",
                           "heures_ok": heures_ok}})
    for nh in (6, 24):
        configs.append({"id": f"I-z25-temps{nh}", "fam": "I", "df": df5,
                        "sig": sig_z, "ut": "M5",
                        "kw": {"mult_stop": 0.5, "sortie": "temps",
                               "n_hold": nh, "heures_ok": heures_ok}})

    n_essais_total = COMPTEUR_PRECEDENT + len(configs)
    seuil_bruit = math.sqrt(2 * math.log(n_essais_total))
    w(f"COMPTEUR CUMULATIF : {COMPTEUR_PRECEDENT} (phases 1-4) + "
      f"{len(configs)} (phase 5) = {n_essais_total}")
    w(f"correction du nombre d'essais : max attendu du bruit ≈ "
      f"√(2·ln {n_essais_total}) = {seuil_bruit:.2f} σ → t requis > "
      f"{seuil_bruit:.2f}")
    w()

    # ---------- simulation + classification régimes ----------
    def classer_regime(trades, df, blocs):
        atr = df["atr"].to_numpy()
        tarr = df["time"].to_numpy()
        for tr in trades:
            i_sig = tr["i_entree"] - 1
            a_bloc = None
            for (a, z) in blocs[1:]:
                if a <= tr["t_entree"] < z:
                    a_bloc = a
                    break
            if a_bloc is None:
                tr["regime"] = None
                continue
            hist = atr[(tarr < a_bloc - PURGE_S) & np.isfinite(atr)]
            q1, q2 = np.quantile(hist, [1 / 3, 2 / 3])
            v = atr[i_sig]
            tr["regime"] = ("bas" if v <= q1 else
                            "haut" if v > q2 else "moyen")

    resultats = []
    for cfg in configs:
        blocs = blocs_temporels(cfg["df"])
        trades = simuler5(cfg["df"], cfg["sig"], cout_heure=cout_med,
                          ut=cfg["ut"], **cfg["kw"])
        if "regime" in cfg:
            classer_regime(trades, cfg["df"], blocs)
            trades = [tr for tr in trades if tr.get("regime") == cfg["regime"]]
        oos, par_bloc = restreindre_test(trades, blocs)
        m = metriques(oos, v1usd, CAPITAL_REF_EUR)
        m["t"] = t_stat(oos, v1usd) if oos else float("nan")
        m["blocs_pos"] = sum(
            1 for b in par_bloc
            if b and sum(tr["pnl_usd"] for tr in b) > 0)
        m["n_blocs"] = sum(1 for b in par_bloc if b)
        resultats.append({"cfg": cfg, "oos": oos, "m": m, "blocs": blocs})

    # variance des Sharpe entre essais (pour le DSR)
    srs = []
    for r in resultats:
        if r["m"]["n"] >= 2:
            pnl = np.array([tr["pnl_usd"] for tr in r["oos"]]) * v1usd
            if pnl.std(ddof=1) > 0:
                srs.append(pnl.mean() / pnl.std(ddof=1))
    var_sr = float(np.var(srs, ddof=1)) if len(srs) > 2 else 0.0

    w("--- RÉSULTATS WALK-FORWARD OOS (blocs 2-5, purge 1 j) ---")
    w(f"{'config':<22} {'n':>5} {'p̂':>6} {'esp/tr':>8} {'t':>6} "
      f"{'blocs+':>7} {'DD%':>6}")
    for r in sorted(resultats, key=lambda r: -(r["m"].get(
            "esperance_eur", -9e9) if r["m"]["n"] else -9e9)):
        m = r["m"]
        if m["n"] == 0:
            w(f"{r['cfg']['id']:<22}     0  — aucun trade OOS")
            continue
        w(f"{r['cfg']['id']:<22} {m['n']:>5} {m['p_hat']:>6.3f} "
          f"{m['esperance_eur']:>+7.3f}€ {m['t']:>+6.2f} "
          f"{m['blocs_pos']}/{m['n_blocs']:>4} {m['dd_max_pct']:>5.1f}%")
    w()

    # ---------- vérification des candidats positifs ----------
    w("--- VÉRIFICATION DES CANDIDATS (espérance OOS > 0) ---")
    candidats = [r for r in resultats
                 if r["m"]["n"] >= 20 and r["m"]["esperance_eur"] > 0]
    if not candidats:
        w("aucun candidat : aucune configuration n'a d'espérance "
          "walk-forward OOS positive avec ≥ 20 trades.")
    verdicts = []
    for r in candidats:
        cfg, m = r["cfg"], r["m"]
        w(f"[{cfg['id']}] espérance OOS {m['esperance_eur']:+.3f} EUR/trade, "
          f"n={m['n']}, t={m['t']:+.2f}")
        # condition 2 : témoin
        esps = []
        for g in range(N_GRAINES):
            tr_t = temoin_permutation(cfg["df"], cfg["sig"], 3000 + g,
                                      cout_heure=cout_med, ut=cfg["ut"],
                                      **cfg["kw"])
            if "regime" in cfg:
                classer_regime(tr_t, cfg["df"], r["blocs"])
                tr_t = [x for x in tr_t if x.get("regime") == cfg["regime"]]
            oos_t, _ = restreindre_test(tr_t, r["blocs"])
            if oos_t:
                esps.append(metriques(oos_t, v1usd,
                                      CAPITAL_REF_EUR)["esperance_eur"])
        esps = np.array(esps)
        z_tem = ((m["esperance_eur"] - esps.mean()) / esps.std()
                 if esps.std() > 0 else float("nan"))
        c2 = z_tem > 2.0
        w(f"    témoin ({len(esps)} graines) : {esps.mean():+.3f} ± "
          f"{esps.std():.3f} → écart {z_tem:+.1f} σ "
          f"{'✓' if c2 else '✗ (< 2 σ)'}")
        # condition 3 : correction essais + DSR
        c3 = m["t"] > seuil_bruit
        d = dsr(r["oos"], v1usd, var_sr, n_essais_total)
        txt_dsr = f", DSR={d:.3f}" if d is not None else ", DSR n/a (n<50)"
        if d is not None:
            c3 = c3 and d >= 0.95
        w(f"    correction essais : t={m['t']:+.2f} vs {seuil_bruit:.2f} "
          f"requis{txt_dsr} {'✓' if c3 else '✗'}")
        # condition 4 : stress P95
        tr_s = simuler5(cfg["df"], cfg["sig"], cout_heure=cout_p95,
                        ut=cfg["ut"], **cfg["kw"])
        if "regime" in cfg:
            classer_regime(tr_s, cfg["df"], r["blocs"])
            tr_s = [x for x in tr_s if x.get("regime") == cfg["regime"]]
        oos_s, _ = restreindre_test(tr_s, r["blocs"])
        m_s = metriques(oos_s, v1usd, CAPITAL_REF_EUR)
        c4 = m_s["n"] > 0 and m_s["esperance_eur"] > 0
        w(f"    stress P95 : espérance {m_s.get('esperance_eur', float('nan')):+.3f} "
          f"EUR/trade {'✓' if c4 else '✗'}")
        # condition 5 : exécutabilité
        kq = kelly_quart(m, CAPITAL_REF_EUR, 0.01, 0.01)
        c5 = kq["verdict"].startswith("EXÉCUTABLE")
        w(f"    exécutabilité : {kq['verdict']} {'✓' if c5 else '✗'}")
        ok = all([True, c2, c3, c4, c5])
        note = ""
        if cfg["fam"] == "F2":
            note = (" [famille DATA-SUGGESTED : même en cas de succès, "
                    "résultat non probant sans revalidation hors "
                    "échantillon]")
            ok = False
        w(f"    VERDICT : {'POSITIF (5/5)' if ok else 'ÉCHEC'}{note}")
        w()
        verdicts.append((cfg["id"], ok))

    w()
    w(f"COMPTEUR FINAL : {n_essais_total} hypothèses cumulées.")
    n_pos = sum(1 for _, ok in verdicts if ok)
    w(f"stratégies satisfaisant les 5 conditions : {n_pos}")

    (RACINE / "data" / "phase5_resultats.txt").write_text(
        "\n".join(lignes) + "\n", encoding="utf-8")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
