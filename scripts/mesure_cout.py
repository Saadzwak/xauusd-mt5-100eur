"""Phase 2 — mesure du coût réel, en LECTURE SEULE.

Mesures :
- distribution du spread par tranche horaire (heure serveur + UTC),
  à partir de l'historique de ticks réels (copy_ticks_range),
  fermetures week-end et pauses quotidiennes marquées comme telles ;
- ATR(14) Wilder sur M1, M5, M15, H1, H4 (60 derniers jours,
  copy_rates_from_pos), en dollars ;
- ratio spread_médian / ATR par unité de temps, en % ;
- amplitude médiane et P90 des bougies (high - low) par UT ;
- swap_long, swap_short, swap_mode, swap_rollover3days ;
- champs de commission disponibles (ou signalement de leur absence) ;
- horodatage UTC et heure serveur, avec le décalage inféré des données.

Décalage serveur : l'horloge serveur n'est observable que via le dernier
tick. Pendant une pause de cotation, ce tick est en retard sur l'horloge,
donc décalage >= (t_dernier_tick - t_utc). On prend le plafond horaire
(ceil) et on VALIDE contre l'historique : l'heure serveur courante doit
tomber dans une tranche horaire historiquement sans ticks. Échec bruyant
sinon.

Sorties : data/mesure_cout.txt (rapport), data/spread_horaire.csv,
data/atr_ut.csv, data/mesure_phase2.json (entrées de la phase 3).
Aucun ordre. trade_tick_value banni (voir CLAUDE.md) :
order_calc_profit() fait foi.
"""

import json
import math
import sys
import time as time_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import MetaTrader5 as mt5
import pandas as pd

from config import CAPITAL_REF_EUR, SYMBOL
from connect import connect, disconnect

JOURS_TICKS = 15    # profondeur de l'historique de ticks pour le spread
JOURS_ATR = 60      # profondeur demandée pour l'ATR
PERIODE_ATR = 14

BARRES_DEMANDEES = {
    "M1": (mt5.TIMEFRAME_M1, 100_000),
    "M5": (mt5.TIMEFRAME_M5, 25_000),
    "M15": (mt5.TIMEFRAME_M15, 10_000),
    "H1": (mt5.TIMEFRAME_H1, 3_000),
    "H4": (mt5.TIMEFRAME_H4, 1_000),
}


def champ(obj, nom):
    """Rule 6 : jamais d'attribut inventé — échec bruyant avec la liste réelle."""
    d = obj._asdict()
    if nom not in d:
        raise AttributeError(
            f"Champ '{nom}' absent de {type(obj).__name__}. "
            f"Champs réels : {sorted(d.keys())}"
        )
    return d[nom]


def dt_naive_utc(epoch):
    """Epoch → datetime naïf ; l'axe (UTC ou serveur) est celui de l'epoch."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)


def collecter_ticks(utc_now):
    """Historique de ticks bid/ask par tranches d'un jour. Échec bruyant."""
    debut = utc_now - timedelta(days=JOURS_TICKS)
    morceaux = []
    n_spread_negatif = 0
    for k in range(JOURS_TICKS + 1):
        a = debut + timedelta(days=k)
        b = min(a + timedelta(days=1), utc_now + timedelta(hours=14))
        if a >= b:
            break
        ticks = mt5.copy_ticks_range(SYMBOL, a, b, mt5.COPY_TICKS_INFO)
        if ticks is None:
            raise RuntimeError(
                f"copy_ticks_range({a:%Y-%m-%d}) a échoué : {mt5.last_error()}"
            )
        if len(ticks) == 0:
            continue
        noms = ticks.dtype.names
        for requis in ("time", "bid", "ask"):
            if requis not in noms:
                raise AttributeError(
                    f"Champ tick '{requis}' absent. Champs réels : {noms}"
                )
        df = pd.DataFrame({"time": ticks["time"],
                           "bid": ticks["bid"], "ask": ticks["ask"]})
        df = df[(df["bid"] > 0) & (df["ask"] > 0)]
        n_spread_negatif += int((df["ask"] < df["bid"]).sum())
        df = df[df["ask"] >= df["bid"]]
        df["spread"] = df["ask"] - df["bid"]
        morceaux.append(df[["time", "bid", "ask", "spread"]])
    if not morceaux:
        raise RuntimeError(
            "Aucun tick renvoyé sur toute la période — historique de ticks "
            "indisponible sur ce terminal ?"
        )
    ticks_df = pd.concat(morceaux, ignore_index=True)
    ticks_df = ticks_df.drop_duplicates(subset="time", keep="first")
    dt_srv = pd.to_datetime(ticks_df["time"], unit="s")   # horloge serveur
    ticks_df["date"] = dt_srv.dt.date
    ticks_df["heure"] = dt_srv.dt.hour
    ticks_df["jour_sem"] = dt_srv.dt.dayofweek            # 0=lun … 6=dim
    return ticks_df, dt_srv, n_spread_negatif


def inferer_decalage(ticks_df, epoch_dernier_tick, epoch_utc):
    """Décalage horaire serveur-UTC, validé contre les heures creuses.

    L'horloge serveur est >= son dernier tick, donc
    decalage >= (epoch_dernier_tick - epoch_utc). On prend le plafond
    horaire. Si le dernier tick date de plus de 5 min (pause de cotation),
    l'heure serveur courante doit être une tranche historiquement vide
    (jours de semaine) ; sinon on refuse de conclure.
    """
    brut = epoch_dernier_tick - epoch_utc
    semaine = ticks_df[ticks_df["jour_sem"] < 5]
    comptes = semaine.groupby("heure")["spread"].count()
    mediane_comptes = comptes[comptes > 0].median()

    if abs(brut - round(brut / 3600.0) * 3600) <= 300:
        # marché en cotation : le décalage se lit directement
        return int(round(brut / 3600.0)), brut

    decalage_h = math.ceil(brut / 3600.0)
    anciennete = decalage_h * 3600 - brut
    if anciennete > 3 * 3600:
        raise RuntimeError(
            f"Dernier tick vieux de {anciennete:.0f} s sous l'hypothèse "
            f"UTC{decalage_h:+d} — trop pour une pause quotidienne. "
            "Week-end ou terminal déconnecté ? Relancer marché ouvert."
        )
    heure_serveur_courante = dt_naive_utc(epoch_utc + decalage_h * 3600).hour
    n_cette_heure = int(comptes.get(heure_serveur_courante, 0))
    if n_cette_heure > 0.05 * mediane_comptes:
        raise RuntimeError(
            f"Hypothèse UTC{decalage_h:+d} incohérente : l'heure serveur "
            f"courante ({heure_serveur_courante}h) compte {n_cette_heure} "
            f"ticks dans l'historique (médiane horaire "
            f"{mediane_comptes:.0f}), donc le marché devrait coter et il ne "
            "cote pas. Décalage indéterminable — relancer marché ouvert."
        )
    return decalage_h, brut


def main():
    compte = connect()
    devise = champ(compte, "currency")

    # ---------- Références symbole et conversion ----------
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        raise RuntimeError(f"symbol_info({SYMBOL}) None : {mt5.last_error()}")
    d_sym = info._asdict()
    d_cpt = compte._asdict()

    point = champ(info, "point")
    volume_min = champ(info, "volume_min")
    digits = champ(info, "digits")
    ask = champ(info, "ask")

    valeur_1usd = mt5.order_calc_profit(
        mt5.ORDER_TYPE_BUY, SYMBOL, volume_min, ask, ask + 1.0
    )
    if valeur_1usd is None or valeur_1usd <= 0:
        raise RuntimeError(f"order_calc_profit invalide : {valeur_1usd}, "
                           f"{mt5.last_error()}")

    # ---------- Ticks puis horodatage ----------
    epoch_utc = time_mod.time()
    utc_now = datetime.fromtimestamp(epoch_utc, tz=timezone.utc)
    ticks_df, dt_srv, n_spread_negatif = collecter_ticks(utc_now)

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        raise RuntimeError(f"symbol_info_tick({SYMBOL}) None : {mt5.last_error()}")
    epoch_dernier = champ(tick, "time")
    decalage_h, brut = inferer_decalage(ticks_df, epoch_dernier, epoch_utc)
    serveur_now = dt_naive_utc(epoch_utc + decalage_h * 3600)
    epoch_serveur = epoch_utc + decalage_h * 3600

    lignes = []

    def w(t=""):
        lignes.append(t)

    w("=" * 64)
    w("PHASE 2 — MESURE DU COÛT RÉEL (lecture seule)")
    w("=" * 64)
    w()
    w(f"généré (UTC)         : {utc_now:%Y-%m-%d %H:%M:%S} UTC")
    w(f"heure serveur        : {serveur_now:%Y-%m-%d %H:%M:%S} "
      f"(UTC{decalage_h:+d}, inféré et validé sur les heures creuses)")
    w(f"dernier tick serveur : {dt_naive_utc(epoch_dernier):%Y-%m-%d %H:%M:%S} "
      f"(écart brut {brut:+.0f} s : cotation en pause si non multiple d'1 h)")
    w()

    # ---------- Swaps ----------
    swap_long = champ(info, "swap_long")
    swap_short = champ(info, "swap_short")
    swap_mode = champ(info, "swap_mode")
    swap_3j = champ(info, "swap_rollover3days")
    noms_modes = {getattr(mt5, n): n for n in dir(mt5)
                  if n.startswith("SYMBOL_SWAP_MODE")}
    nom_mode = noms_modes.get(swap_mode, f"mode {swap_mode} "
                              f"(constantes exposées : {sorted(noms_modes.values())})")

    w("--- SWAP ---")
    w(f"swap_mode  : {swap_mode} ({nom_mode})")
    w(f"swap_long  : {swap_long}")
    w(f"swap_short : {swap_short}")
    w(f"swap_rollover3days : {swap_3j} (0=lun … 4=ven ; jour du swap triple)")
    swap_eur_long = swap_eur_short = None
    if nom_mode == "SYMBOL_SWAP_MODE_POINTS":
        # Swap exprimé en points de prix : équivalent prix = swap × point ($).
        # valeur_1usd (order_calc_profit) convertit 1 $ de prix en EUR pour
        # volume_min ; donc EUR/nuit = swap × point × valeur_1usd.
        swap_eur_long = swap_long * point * valeur_1usd
        swap_eur_short = swap_short * point * valeur_1usd
        w(f"→ mode points : pour {volume_min} lot, "
          f"long {swap_eur_long:+.3f} {devise}/nuit, "
          f"short {swap_eur_short:+.3f} {devise}/nuit "
          f"(triple le jour {swap_3j})")
    else:
        w(f"→ mode {nom_mode} : conversion en {devise}/nuit non automatisée "
          "pour ce mode ; valeurs brutes ci-dessus font foi et devront être "
          "converties explicitement en phase 4 si une UT à position "
          "overnight survit à la phase 3.")
    w()

    # ---------- Commission ----------
    w("--- COMMISSION ---")
    cles_comm = sorted(k for k in list(d_sym) + list(d_cpt)
                       if "commission" in k.lower() or "fee" in k.lower())
    if cles_comm:
        for k in cles_comm:
            src = "symbol" if k in d_sym else "compte"
            val = d_sym.get(k, d_cpt.get(k))
            w(f"{k} ({src}) : {val}")
        w("NB : aucun de ces champs n'est un taux de commission par lot.")
    w("L'API MetaTrader5 n'expose PAS de taux de commission par lot dans "
      "symbol_info() ni account_info(). Sur ce compte MetaQuotes-Demo le "
      "coût mesurable se limite à spread + swap ; toute commission broker "
      "réelle devra être ajoutée à la main le jour où le broker réel est "
      "connu.")
    w()

    # ---------- Spread ----------
    n_ticks = len(ticks_df)
    w("--- SPREAD : HISTORIQUE DE TICKS ---")
    w(f"ticks bid/ask analysés : {n_ticks} "
      f"du {dt_srv.min():%Y-%m-%d %H:%M} au {dt_srv.max():%Y-%m-%d %H:%M} "
      f"(heure serveur, UTC{decalage_h:+d})")
    if n_spread_negatif:
        w(f"ticks à spread négatif écartés : {n_spread_negatif}")

    sp = ticks_df["spread"]
    med = float(sp.median())
    w()
    w(f"spread global   : médiane {med:.{digits}f} $ | moyenne "
      f"{sp.mean():.{digits}f} $ | P95 {sp.quantile(0.95):.{digits}f} $ | "
      f"max {sp.max():.{digits}f} $")
    w(f"coût aller-retour médian ({volume_min} lot) : "
      f"{med * valeur_1usd:.2f} {devise} = "
      f"{med * valeur_1usd / CAPITAL_REF_EUR * 100:.2f} % du capital de "
      f"référence ({CAPITAL_REF_EUR:.0f} EUR)")
    w()

    grp = ticks_df.groupby("heure")["spread"]
    table = pd.DataFrame({
        "heure_serveur": grp.median().index,
        "mediane": grp.median().values,
        "moyenne": grp.mean().values,
        "p95": grp.quantile(0.95).values,
        "max": grp.max().values,
        "n_ticks": grp.count().values,
    })
    table["heure_utc"] = (table["heure_serveur"] - decalage_h) % 24
    table = table[["heure_serveur", "heure_utc", "n_ticks",
                   "mediane", "moyenne", "p95", "max"]]
    dossier = RACINE / "data"
    dossier.mkdir(exist_ok=True)
    table.to_csv(dossier / "spread_horaire.csv", index=False)

    w("spread par tranche horaire (heure serveur | équivalent UTC) :")
    w(f"{'srv':>4} {'utc':>4} {'n_ticks':>9} {'médiane':>9} {'moyenne':>9} "
      f"{'P95':>9} {'max':>9}")
    for _, r in table.iterrows():
        w(f"{int(r['heure_serveur']):>4} {int(r['heure_utc']):>4} "
          f"{int(r['n_ticks']):>9} {r['mediane']:>9.2f} {r['moyenne']:>9.2f} "
          f"{r['p95']:>9.2f} {r['max']:>9.2f}")
    w()

    # Heures sans ticks : week-end vs pause quotidienne vs anomalie.
    # Calendrier COMPLET entre premier et dernier tick (les jours à zéro
    # tick n'apparaissent pas dans les données : il faut les réintroduire),
    # et absences comptées uniquement dans la fenêtre de couverture réelle.
    presentes = set(zip(ticks_df["date"], ticks_df["heure"]))
    dates_avec_ticks = set(ticks_df["date"].unique())
    debut_couv, fin_couv = dt_srv.min(), dt_srv.max()
    calendrier = pd.date_range(debut_couv.normalize(), fin_couv.normalize(),
                               freq="D")
    jours_we_fermes, jours_sem_vides = [], []
    absences_semaine = {}
    for jour in calendrier:
        d = jour.date()
        if d not in dates_avec_ticks:
            if jour.dayofweek >= 5:
                jours_we_fermes.append(d)
            else:
                jours_sem_vides.append(d)
            continue
        if jour.dayofweek >= 5:
            continue
        for h in range(24):
            debut_h = jour + pd.Timedelta(hours=h)
            if debut_h < debut_couv or debut_h + pd.Timedelta(hours=1) > fin_couv:
                continue        # hors fenêtre de couverture, pas une absence
            if (d, h) not in presentes:
                absences_semaine.setdefault(h, []).append(d)
    w("jours et heures sans ticks (heure serveur) :")
    w(f"  FERMÉ WEEK-END : {len(jours_we_fermes)} jour(s) sam/dim sans "
      f"aucun tick ({', '.join(str(j) for j in jours_we_fermes)}) — "
      "exclu des statistiques, pas du spread manquant.")
    if jours_sem_vides:
        w(f"  ANOMALIE : jour(s) de semaine sans aucun tick : "
          f"{', '.join(str(j) for j in jours_sem_vides)}")
    for h in sorted(absences_semaine):
        jours = absences_semaine[h]
        w(f"  {h:02d}h serveur sans ticks {len(jours)} jour(s) de semaine "
          f"({', '.join(str(j) for j in jours[:6])}"
          f"{'…' if len(jours) > 6 else ''}) — pause quotidienne si "
          "systématique, sinon à vérifier.")
    if not absences_semaine:
        w("  aucune heure de semaine sans ticks dans la fenêtre couverte.")
    w()

    # ---------- ATR(14) et amplitudes par UT ----------
    w("--- ATR(14) WILDER ET AMPLITUDES (fenêtre demandée : "
      f"{JOURS_ATR} jours) ---")
    cutoff = epoch_serveur - JOURS_ATR * 86400
    terminal = mt5.terminal_info()
    if terminal is None:
        raise RuntimeError(f"terminal_info() None : {mt5.last_error()}")
    maxbars = champ(terminal, "maxbars")
    resultats_atr = {}
    lignes_csv = []
    for nom_ut, (tf, nb) in BARRES_DEMANDEES.items():
        nb_eff = min(nb, maxbars - 1000)
        if nb_eff < nb:
            w(f"({nom_ut} : demande plafonnée à {nb_eff} barres par le "
              f"réglage terminal maxbars={maxbars})")
        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, nb_eff)
        if rates is None:
            raise RuntimeError(
                f"copy_rates_from_pos({nom_ut}) a échoué : {mt5.last_error()}"
            )
        if len(rates) == 0:
            raise RuntimeError(f"copy_rates_from_pos({nom_ut}) : 0 barre")
        noms = rates.dtype.names
        for requis in ("time", "high", "low", "close"):
            if requis not in noms:
                raise AttributeError(
                    f"Champ rates '{requis}' absent ({nom_ut}). "
                    f"Champs réels : {noms}"
                )
        df = pd.DataFrame({"time": rates["time"], "high": rates["high"],
                           "low": rates["low"], "close": rates["close"]})
        prev_close = df["close"].shift(1)
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.ewm(alpha=1.0 / PERIODE_ATR, adjust=False).mean()
        df = df.iloc[PERIODE_ATR:]              # purge du warm-up
        fenetre = df[df["time"] >= cutoff]
        if len(fenetre) == 0:
            raise RuntimeError(f"{nom_ut} : aucune barre dans la fenêtre de "
                               f"{JOURS_ATR} jours")
        span_de = dt_naive_utc(int(fenetre["time"].iloc[0]))
        span_a = dt_naive_utc(int(fenetre["time"].iloc[-1]))
        couverture_j = (span_a - span_de).days
        ampl = fenetre["high"] - fenetre["low"]
        r = {
            "n_barres": int(len(fenetre)),
            "de_serveur": f"{span_de:%Y-%m-%d %H:%M}",
            "a_serveur": f"{span_a:%Y-%m-%d %H:%M}",
            "couverture_jours": couverture_j,
            "atr_median": float(fenetre["atr"].median()),
            "atr_moyen": float(fenetre["atr"].mean()),
            "atr_dernier": float(fenetre["atr"].iloc[-1]),
            "ampl_mediane": float(ampl.median()),
            "ampl_p90": float(ampl.quantile(0.90)),
            "ratio_spread_atr_pct": med / float(fenetre["atr"].median()) * 100,
        }
        resultats_atr[nom_ut] = r
        lignes_csv.append({"ut": nom_ut, **r})
        note = ""
        if couverture_j < JOURS_ATR - 3:
            note = (f"  ← ATTENTION : historique limité à {couverture_j} j "
                    f"(demandé {JOURS_ATR} j)")
        w(f"{nom_ut:>4} | {r['n_barres']:>6} barres | "
          f"{r['de_serveur']} → {r['a_serveur']} ({couverture_j} j){note}")
        w(f"     | ATR14 médian {r['atr_median']:>7.2f} $ | moyen "
          f"{r['atr_moyen']:>7.2f} $ | dernier {r['atr_dernier']:>7.2f} $")
        w(f"     | amplitude médiane {r['ampl_mediane']:>7.2f} $ | P90 "
          f"{r['ampl_p90']:>7.2f} $")
        w(f"     | RATIO spread_médian/ATR_médian = "
          f"{r['ratio_spread_atr_pct']:.1f} %")
        w()

    pd.DataFrame(lignes_csv).to_csv(dossier / "atr_ut.csv", index=False)

    disconnect()

    # ---------- Sauvegardes ----------
    resume = {
        "genere_utc": f"{utc_now:%Y-%m-%d %H:%M:%S}",
        "heure_serveur": f"{serveur_now:%Y-%m-%d %H:%M:%S}",
        "decalage_serveur_heures": decalage_h,
        "devise": devise,
        "capital_ref_eur": CAPITAL_REF_EUR,
        "volume_min": volume_min,
        "valeur_1usd_volume_min": float(valeur_1usd),
        "spread": {
            "n_ticks": int(n_ticks),
            "jours_couverts": JOURS_TICKS,
            "mediane": med,
            "moyenne": float(sp.mean()),
            "p95": float(sp.quantile(0.95)),
            "max": float(sp.max()),
        },
        "swap": {"mode": int(swap_mode), "mode_nom": nom_mode,
                 "long": float(swap_long), "short": float(swap_short),
                 "rollover3days": int(swap_3j),
                 "eur_nuit_long_vol_min": swap_eur_long,
                 "eur_nuit_short_vol_min": swap_eur_short},
        "atr": resultats_atr,
    }
    (dossier / "mesure_phase2.json").write_text(
        json.dumps(resume, indent=2, ensure_ascii=False), encoding="utf-8")
    rapport = "\n".join(lignes) + "\n"
    (dossier / "mesure_cout.txt").write_text(rapport, encoding="utf-8")
    print(rapport)


if __name__ == "__main__":
    main()
