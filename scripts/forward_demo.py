"""Phase 7 v4 — MÉTHODE V MÉCANIQUE PURE sur compte DÉMO 111371411.

EXCEPTION PHASE 7 (CLAUDE.md) : order_send() UNIQUEMENT ici,
UNIQUEMENT sur le démo 111371411, vérification login + trade_mode
avant CHAQUE ordre. SL attaché obligatoire. 1 trade actif maximum.

Spécification FIGÉE : scripts/preregistre_v4.md, dérivée de
l'AMENDEMENT v4 de CLAUDE.md (décision du propriétaire, 2026-09-14,
après le kill switch v3.1) :
- taille FIXE 0,01 lot, UNE entrée par trade, AUCUN renfort ;
- SL 10 $ / TP 7 $ mécaniques ; seules sorties anticipées : événement
  macro fort impact <= 15 min, et pause/week-end (22:45/22:55) ;
- analyse contextuelle (fractales K=2, Fibonacci, macro) calculée et
  LOGGUÉE (facteurs par entrée compris), sans influence sur la taille
  ni sur les sorties ;
- capital simulé : nouvelle campagne à 100 EUR ;
- arrêts : perte cumulée v4 > 20 EUR ; 8 pertes consécutives ;
  cible n = 30 (arrêt et verdict) — vérifiés après CHAQUE clôture ;
- compte en HEDGING (margin_mode 2) : le trade = l'ensemble des
  positions portant le magic (ici toujours une seule) ;
- télémétrie en position toutes les 120 s + alertes SL/TP proches.
"""

import csv
import json
import math
import sys
import time as time_mod
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from config import DEMO_LOGIN, SYMBOL
from connect import connect, disconnect

# ----- CONSTANTES FIGÉES v4 (preregistre_v4.md — NE PAS MODIFIER) -----
SL_USD = 10.0
TP_USD = 7.0
TAILLE_FIXE = 0.01
VOL_SEUIL_ABS = 200
VOL_FENETRE = 20
VOL_FACTEUR_NET = 1.5          # f2 : volume >= 1.5 x moyenne 20 (loggé)
PROX_SR = 5.0                  # f3 : S/R confirmant à <= 5 $ (loggé)
TOL_FIB = 1.5                  # f4 : niveau fib à <= 1.5 $ (loggé)
FIB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)
K_FRACTALE = 2
MACRO_FACTEUR_S = 3600         # f5 : aucun événement à <= 60 min (loggé)
MACRO_BLOCAGE_S = 900          # pas d'entrée / sortie si événement <= 15 min
SPREAD_MAX_ENTREE = 2.00
PERTE_MAX_CUM = 20.0
PERTES_CONSEC_MAX = 8
CIBLE_N = 30
CAPITAL_SIM_DEPART = 100.0     # NOUVELLE campagne v4
OBJECTIF = 1000.0
MAGIC = 20260914
GRAINE_TEMOIN = 20260914
RAPPORT_S = 1200
TELEMETRIE_S = 120
ALERTE_SL_DIST = 2.0
ALERTE_TP_DIST = 1.5
TF_S = 300

JOURNAL = RACINE / "data" / "forward_journal_v4.csv"
SIGNAUX = RACINE / "data" / "methode_v_signaux.csv"
CONTEXTE = RACINE / "data" / "contexte_m5.csv"
CALENDRIER = RACINE / "data" / "calendrier_macro.csv"
LIVE = RACINE / "data" / "forward_live.txt"

COLONNES = ["ts_srv", "sens", "volume_total", "n_entrees", "facteurs",
            "prix_premiere", "slippage_usd", "spread_entree", "sl", "tp",
            "issue", "sortie_motif", "net_eur", "duree_s", "temoin_sens",
            "temoin_issue", "temoin_net_eur", "capital_simule"]
COL_SIG = ["ts_barre", "dPrev", "dLast", "volume", "vol_moy20", "decision",
           "facteurs", "taille", "motif"]
COL_CTX = ["ts_barre", "swing_high", "swing_low", "sens_jambe",
           "niveaux_fib", "n_supports", "n_resistances",
           "prochain_evenement", "minutes_avant"]


def verifier_demo():
    info = mt5.account_info()
    if info is None:
        raise RuntimeError(f"account_info None : {mt5.last_error()}")
    if info.login != DEMO_LOGIN or \
            info.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        mt5.shutdown()
        print(f"REFUS DÉFINITIF : login={info.login} "
              f"trade_mode={info.trade_mode} — pas le démo attendu.")
        sys.exit(3)


def champ(obj, nom):
    d = obj._asdict()
    if nom not in d:
        raise AttributeError(f"Champ '{nom}' absent. Réels : {sorted(d)}")
    return d[nom]


def mode_remplissage(info_sym):
    bits = champ(info_sym, "filling_mode")
    if bits & 1:
        return mt5.ORDER_FILLING_FOK
    if bits & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def append_csv(chemin, colonnes, ligne):
    neuf = not chemin.exists()
    with open(chemin, "a", newline="", encoding="utf-8") as f:
        wcsv = csv.DictWriter(f, fieldnames=colonnes)
        if neuf:
            wcsv.writeheader()
        wcsv.writerow({k: ligne.get(k, "") for k in colonnes})


# ---------------- analyse contextuelle (barres closes) ----------------
def fractales(df):
    """Swings causaux K=2, confirmés par K barres closes suivantes.
    Comparaisons par epoch réel, jamais par texte."""
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    t = df["time"].to_numpy()
    hauts, bas = [], []
    for i in range(K_FRACTALE, len(df) - K_FRACTALE):
        if all(h[i] > h[i - k] for k in range(1, K_FRACTALE + 1)) and \
                all(h[i] > h[i + k] for k in range(1, K_FRACTALE + 1)):
            hauts.append((int(t[i]), float(h[i])))
        if all(l[i] < l[i - k] for k in range(1, K_FRACTALE + 1)) and \
                all(l[i] < l[i + k] for k in range(1, K_FRACTALE + 1)):
            bas.append((int(t[i]), float(l[i])))
    return hauts, bas


def jambe_et_fib(hauts, bas):
    if not hauts or not bas:
        return None
    th, ph = hauts[-1]
    tl, pl = bas[-1]
    if ph <= pl:
        return None
    sens = "haussiere" if th > tl else "baissiere"
    niveaux = {}
    for r in FIB_RATIOS:
        if sens == "haussiere":
            niveaux[r] = ph - r * (ph - pl)
        else:
            niveaux[r] = pl + r * (ph - pl)
    return {"sens": sens, "haut": ph, "bas": pl, "niveaux": niveaux}


def facteurs_confiance(sens, prix, vol_sig, vol_ma, hauts, bas, jambe,
                       ev_dans_s):
    """Facteurs LOGGÉS à titre d'observation (v4 : taille fixe)."""
    fs = ["f1"]
    niveaux = {}
    if vol_sig >= VOL_FACTEUR_NET * vol_ma:
        fs.append("f2")
    if sens > 0:
        sr = [p for _, p in bas if prix - PROX_SR <= p <= prix]
    else:
        sr = [p for _, p in hauts if prix <= p <= prix + PROX_SR]
    if sr:
        fs.append("f3")
        p_sr = max(sr) if sens > 0 else min(sr)
        niveaux[f"sr:{round(p_sr, 1)}"] = p_sr
    if jambe is not None:
        aligne = (sens > 0 and jambe["sens"] == "haussiere") or \
                 (sens < 0 and jambe["sens"] == "baissiere")
        if aligne:
            proches = {r: p for r, p in jambe["niveaux"].items()
                       if abs(prix - p) <= TOL_FIB}
            if proches:
                fs.append("f4")
                r0, p0 = min(proches.items(),
                             key=lambda kv: abs(prix - kv[1]))
                niveaux[f"fib{r0}:{round(p0, 1)}"] = p0
    if ev_dans_s is None or ev_dans_s > MACRO_FACTEUR_S:
        fs.append("f5")
    return fs, niveaux


class Temoin:
    """Trade virtuel apparié : mêmes quotes, direction aléatoire, mêmes
    SL/TP, taille fixe. Aucun ordre."""

    def __init__(self, sens, bid, ask, ts, volume):
        self.sens, self.ts, self.volume = sens, ts, volume
        self.entree = ask if sens > 0 else bid
        if sens > 0:
            self.sl, self.tp = self.entree - SL_USD, self.entree + TP_USD
        else:
            self.sl, self.tp = self.entree + SL_USD, self.entree - TP_USD
        self.issue = None
        self.net_usd = None

    def maj(self, bid, ask):
        if self.issue:
            return
        if self.sens > 0:
            if bid <= self.sl:
                self.issue, self.net_usd = "perte", self.sl - self.entree
            elif bid >= self.tp:
                self.issue, self.net_usd = "gain", self.tp - self.entree
        else:
            if ask >= self.sl:
                self.issue, self.net_usd = "perte", self.entree - self.sl
            elif ask <= self.tp:
                self.issue, self.net_usd = "gain", self.entree - self.tp

    def forcer(self, bid, ask):
        if self.issue:
            return
        self.issue = "forcee"
        self.net_usd = (bid - self.entree) if self.sens > 0 \
            else (self.entree - ask)


class Registre:
    def __init__(self, base_capital):
        self.base = base_capital
        self.lignes = []
        if JOURNAL.exists():
            for _, r in pd.read_csv(JOURNAL).iterrows():
                self.lignes.append(dict(r))
        self.refus_spread = 0
        self.refus_retcode = 0
        self.refus_macro = 0
        self.signaux_ignores = 0

    @property
    def total_session(self):
        return sum(float(l["net_eur"]) for l in self.lignes
                   if l.get("net_eur") not in (None, "")
                   and not (isinstance(l["net_eur"], float)
                            and math.isnan(l["net_eur"])))

    @property
    def capital(self):
        return self.base + self.total_session

    @property
    def pertes_consecutives(self):
        n = 0
        for l in reversed(self.lignes):
            v = float(l["net_eur"])
            if v < 0:
                n += 1
            elif v > 0:
                break
        return n

    def ajouter(self, ligne):
        self.lignes.append(ligne)
        self.ecrire()

    def ecrire(self):
        with open(JOURNAL, "w", newline="", encoding="utf-8") as f:
            wcsv = csv.DictWriter(f, fieldnames=COLONNES)
            wcsv.writeheader()
            for l in self.lignes:
                wcsv.writerow({k: l.get(k, "") for k in COLONNES})

    def stats(self):
        nets = np.array([float(l["net_eur"]) for l in self.lignes])
        s = {"n": len(nets)}
        if len(nets):
            s["esperance"] = float(nets.mean())
            s["total"] = float(nets.sum())
            s["t"] = (float(nets.mean() / (nets.std(ddof=1)
                                           / math.sqrt(len(nets))))
                      if len(nets) > 1 and nets.std(ddof=1) > 0
                      else float("nan"))
            diffs = np.array([float(l["net_eur"]) - float(l["temoin_net_eur"])
                              for l in self.lignes
                              if l.get("temoin_net_eur") not in (None, "")])
            diffs = diffs[np.isfinite(diffs)]
            s["ecart_temoin_sigma"] = (
                float(diffs.mean() / (diffs.std(ddof=1)
                                      / math.sqrt(len(diffs))))
                if len(diffs) > 1 and diffs.std(ddof=1) > 0 else float("nan"))
        return s


def rapport(reg, t_srv, note=""):
    s = reg.stats()
    lignes = [
        "=" * 60,
        f"RAPPORT {datetime.fromtimestamp(t_srv, tz=timezone.utc):%H:%M:%S} "
        f"serveur — phase 7 v4 MÉTHODE V mécanique (démo, capital simulé)",
        "=" * 60,
        f"trades : {s['n']}/{CIBLE_N} | refus spread : {reg.refus_spread} | "
        f"refus macro : {reg.refus_macro} | retcode≠DONE : "
        f"{reg.refus_retcode} | signaux ignorés : {reg.signaux_ignores}",
    ]
    if s["n"]:
        lignes += [
            f"espérance : {s['esperance']:+.3f} EUR/trade | total "
            f"{s['total']:+.2f} EUR | t = {s['t']:+.2f}",
            f"écart au témoin (t apparié) : {s['ecart_temoin_sigma']:+.2f} σ",
        ]
    lignes.append(f"capital simulé v4 : {reg.capital:.2f} EUR (départ "
                  f"{CAPITAL_SIM_DEPART:.0f})")
    if s["n"] and s.get("esperance", 0) > 0:
        lignes.append(f"trades vers {OBJECTIF:.0f} EUR à cette espérance : "
                      f"{(OBJECTIF - reg.capital) / s['esperance']:.0f}")
    else:
        lignes.append(f"trades vers {OBJECTIF:.0f} EUR : INATTEIGNABLE "
                      "(espérance ≤ 0 ou n=0)")
    if note:
        lignes.append(note)
    texte = "\n".join(lignes) + "\n"
    LIVE.write_text(texte, encoding="utf-8")
    print(texte)


def main():
    connect()
    term = mt5.terminal_info()
    if term is None:
        raise RuntimeError(f"terminal_info None : {mt5.last_error()}")
    if not champ(term, "trade_allowed"):
        mt5.shutdown()
        print("REFUS DE DÉMARRER : AutoTrading désactivé (Ctrl+E).")
        sys.exit(4)
    info_sym = mt5.symbol_info(SYMBOL)
    if info_sym is None:
        raise RuntimeError(f"symbol_info : {mt5.last_error()}")
    digits = champ(info_sym, "digits")
    if TAILLE_FIXE < champ(info_sym, "volume_min") - 1e-12:
        raise RuntimeError("TAILLE_FIXE < volume_min du symbole")
    remplissage = mode_remplissage(info_sym)

    m2 = json.loads((RACINE / "data" / "mesure_phase2.json")
                    .read_text(encoding="utf-8"))
    v1usd = m2["valeur_1usd_volume_min"]
    decalage_s = int(m2["decalage_serveur_heures"]) * 3600

    if not CALENDRIER.exists():
        raise RuntimeError(f"{CALENDRIER} absent — analyse macro "
                           "OBLIGATOIRE (CLAUDE.md).")
    cal = pd.read_csv(CALENDRIER)
    cal["epoch_utc"] = pd.to_datetime(cal["utc"], utc=True).astype("int64") \
        // 10 ** 9
    evenements = sorted(zip(cal["epoch_utc"], cal["evenement"]))

    def evenement_dans(t_srv):
        t_utc = t_srv - decalage_s
        for ep, nom in evenements:
            delta = ep - t_utc
            if delta >= -MACRO_BLOCAGE_S:
                return delta, nom
        return None, ""

    # v4 : NOUVELLE campagne — capital simulé 100 EUR (AMENDEMENT CLAUDE.md)
    reg = Registre(CAPITAL_SIM_DEPART)
    rng = np.random.default_rng(GRAINE_TEMOIN)
    for _ in reg.lignes:
        rng.integers(0, 2)

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        raise RuntimeError(f"tick : {mt5.last_error()}")
    derniere_barre = (int(tick.time) // TF_S) * TF_S - TF_S

    trade = None
    temoins_actifs = []
    temoins_en_attente = []
    dernier_rapport = time_mod.time()
    derniere_telemetrie = 0.0

    def positions_magic():
        return [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
                if p.magic == MAGIC]

    # adoption d'un trade orphelin (hedging : toutes les jambes du magic)
    orphelines = positions_magic()
    if orphelines:
        p0 = orphelines[0]
        t0 = mt5.symbol_info_tick(SYMBOL)
        vol_tot = sum(p.volume for p in orphelines)
        tm0 = Temoin(1, t0.bid, t0.ask, int(p0.time), p0.volume)
        tm0.issue, tm0.net_usd = "forcee", 0.0
        trade = {"tickets": [p.ticket for p in orphelines],
                 "ids": [p.identifier for p in orphelines],
                 "volumes": [p.volume for p in orphelines],
                 "sens": 1 if p0.type == mt5.POSITION_TYPE_BUY else -1,
                 "ts": int(p0.time), "prix_premiere": p0.price_open,
                 "slippage": 0.0, "spread": float("nan"),
                 "sl": p0.sl, "tp": p0.tp, "retcode": "adoptee",
                 "volume_total": vol_tot, "n_entrees": len(orphelines),
                 "facteurs": "adoptee", "temoin": tm0,
                 "alerte_sl": False, "alerte_tp": False}
        print(f"trade orphelin adopté : {len(orphelines)} jambe(s), "
              f"vol {vol_tot:.2f}")

    print(f"démarrage v4 MÉTHODE V mécanique "
          f"{datetime.fromtimestamp(int(tick.time), tz=timezone.utc):%A %H:%M:%S} "
          f"serveur — cible {CIBLE_N} trades ; capital simulé v4 "
          f"{reg.capital:.2f} EUR ; trades v4 au journal : {len(reg.lignes)}")
    rapport(reg, int(tick.time), note="démarrage")

    def fermer_marche(tr, motif):
        for p in positions_magic():
            verifier_demo()
            t = mt5.symbol_info_tick(SYMBOL)
            if t is None:
                raise RuntimeError(f"tick fermeture : {mt5.last_error()}")
            req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
                   "volume": p.volume,
                   "type": mt5.ORDER_TYPE_SELL
                   if p.type == mt5.POSITION_TYPE_BUY
                   else mt5.ORDER_TYPE_BUY,
                   "position": p.ticket,
                   "price": t.bid if p.type == mt5.POSITION_TYPE_BUY
                   else t.ask,
                   "deviation": 200, "magic": MAGIC, "comment": motif[:26],
                   "type_time": mt5.ORDER_TIME_GTC,
                   "type_filling": remplissage}
            res = mt5.order_send(req)
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                raise RuntimeError(f"clôture '{motif}' échouée sur "
                                   f"{p.ticket} : "
                                   f"{None if res is None else res.retcode} "
                                   f"{mt5.last_error()}")

    def resoudre(tr, issue_forcee=None):
        for _ in range(90):
            net_total, t_out_max = 0.0, 0
            derniers = []
            complet = True
            for pid, vol in zip(tr["ids"], tr["volumes"]):
                deals = mt5.history_deals_get(position=pid)
                sortants = [d for d in (deals or [])
                            if d.entry != mt5.DEAL_ENTRY_IN]
                vol_out = sum(d.volume for d in sortants)
                if not sortants or vol_out + 1e-9 < vol:
                    complet = False
                    break
                net_total += sum(d.profit + d.commission + d.swap + d.fee
                                 for d in deals)
                dernier = max(sortants, key=lambda d: d.time)
                derniers.append(dernier)
                t_out_max = max(t_out_max, int(dernier.time))
            if complet:
                raisons = {getattr(mt5, n): n for n in dir(mt5)
                           if n.startswith("DEAL_REASON")}
                raison = raisons.get(derniers[-1].reason,
                                     str(derniers[-1].reason))
                if issue_forcee:
                    issue = issue_forcee
                elif "DEAL_REASON_TP" in raison:
                    issue = "gain"
                elif "DEAL_REASON_SL" in raison:
                    issue = "perte"
                else:
                    issue = "gain" if net_total > 0 else "perte"
                return float(net_total), issue, t_out_max
            time_mod.sleep(1)
        raise RuntimeError(f"deals du trade {tr['ids']} incomplets")

    def journaliser(tr, issue_forcee=None, motif=""):
        net, issue, t_out = resoudre(tr, issue_forcee)
        tm = tr["temoin"]
        ligne = {"ts_srv": tr["ts"], "sens": "long" if tr["sens"] > 0
                 else "short", "volume_total": round(tr["volume_total"], 2),
                 "n_entrees": tr["n_entrees"], "facteurs": tr["facteurs"],
                 "prix_premiere": tr["prix_premiere"],
                 "slippage_usd": round(tr["slippage"], 3),
                 "spread_entree": round(tr["spread"], 3)
                 if math.isfinite(tr["spread"]) else "",
                 "sl": tr["sl"], "tp": tr["tp"], "issue": issue,
                 "sortie_motif": motif, "net_eur": round(net, 2),
                 "duree_s": t_out - tr["ts"],
                 "temoin_sens": "long" if tm.sens > 0 else "short",
                 "temoin_issue": tm.issue or "",
                 "temoin_net_eur": round(
                     tm.net_usd * v1usd * tm.volume / 0.01, 2)
                 if tm.net_usd is not None else "",
                 "capital_simule": ""}
        reg.ajouter(ligne)
        ligne["capital_simule"] = round(reg.capital, 2)
        reg.ecrire()
        if tm.net_usd is None:
            temoins_en_attente.append((tm, ligne))

    def verifier_arrets(t_srv):
        """Kill switches + cible — après CHAQUE clôture, sans exception."""
        if -reg.total_session > PERTE_MAX_CUM:
            rapport(reg, t_srv, note="KILL SWITCH : perte cumulée v4 > "
                    "20 EUR. Arrêt définitif.")
            return True
        if reg.pertes_consecutives >= PERTES_CONSEC_MAX:
            rapport(reg, t_srv, note="KILL SWITCH : 8 pertes consécutives. "
                    "Arrêt définitif.")
            return True
        if len(reg.lignes) >= CIBLE_N:
            rapport(reg, t_srv, note=f"CIBLE ATTEINTE : {CIBLE_N} trades. "
                    "Arrêt et verdict.")
            return True
        rapport(reg, t_srv)
        return False

    def envoyer_ordre(sens, volume, sl, tp, commentaire):
        verifier_demo()
        t2 = mt5.symbol_info_tick(SYMBOL)
        if t2 is None:
            raise RuntimeError(f"tick ordre : {mt5.last_error()}")
        prix = t2.ask if sens > 0 else t2.bid
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
               "volume": volume,
               "type": mt5.ORDER_TYPE_BUY if sens > 0
               else mt5.ORDER_TYPE_SELL,
               "price": prix, "sl": sl, "tp": tp, "deviation": 100,
               "magic": MAGIC, "comment": commentaire[:26],
               "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": remplissage}
        res = mt5.order_send(req)
        return res, prix, t2

    try:
        while True:
            time_mod.sleep(1)
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                continue
            t_srv = int(tick.time)
            bid, ask = tick.bid, tick.ask
            dt_srv = datetime.fromtimestamp(t_srv, tz=timezone.utc)
            heure, minute_h = dt_srv.hour, dt_srv.minute

            for tm in temoins_actifs:
                tm.maj(bid, ask)
            for tm, ligne in list(temoins_en_attente):
                if tm.net_usd is not None:
                    ligne["temoin_issue"] = tm.issue
                    ligne["temoin_net_eur"] = round(
                        tm.net_usd * v1usd * tm.volume / 0.01, 2)
                    temoins_en_attente.remove((tm, ligne))
                    reg.ecrire()
            temoins_actifs = [t for t in temoins_actifs if not t.issue
                              or (trade and t is trade["temoin"])]

            # ---- trade fermé côté serveur (SL/TP) ? ----
            if trade is not None:
                if not positions_magic():
                    journaliser(trade)
                    trade = None
                    if verifier_arrets(t_srv):
                        break

            # ---- télémétrie temps réel en position ----
            if trade is not None:
                poss = positions_magic()
                if poss:
                    profit_agg = sum(p.profit for p in poss)
                    prix_c = bid if trade["sens"] > 0 else ask
                    d_sl = abs(prix_c - trade["sl"])
                    d_tp = abs(trade["tp"] - prix_c)
                    if not trade["alerte_sl"] and d_sl <= ALERTE_SL_DIST:
                        trade["alerte_sl"] = True
                        print(f"{dt_srv:%H:%M:%S} ALERTE SL PROCHE : "
                              f"{d_sl:.2f} $ (flottant {profit_agg:+.2f} EUR)")
                    if not trade["alerte_tp"] and d_tp <= ALERTE_TP_DIST:
                        trade["alerte_tp"] = True
                        print(f"{dt_srv:%H:%M:%S} ALERTE TP PROCHE : "
                              f"{d_tp:.2f} $ (flottant {profit_agg:+.2f} EUR)")
                    if time_mod.time() - derniere_telemetrie >= TELEMETRIE_S:
                        derniere_telemetrie = time_mod.time()
                        print(f"{dt_srv:%H:%M:%S} POSITION "
                              f"{'LONG' if trade['sens'] > 0 else 'SHORT'} "
                              f"vol={trade['volume_total']:.2f} "
                              f"flottant={profit_agg:+.2f} EUR prix={prix_c} "
                              f"SL à {d_sl:.2f}$ TP à {d_tp:.2f}$")

            # ---- pause / week-end ----
            if heure == 22 and minute_h >= 55 and trade is not None:
                fermer_marche(trade, "pause_ou_weekend")
                trade["temoin"].forcer(bid, ask)
                journaliser(trade, issue_forcee="forcee",
                            motif="pause/week-end")
                trade = None
                if verifier_arrets(t_srv):
                    break
            entree_bloquee = (heure == 22 and minute_h >= 45) or \
                heure in (23, 0)

            # ---- sortie anticipée MACRO uniquement (v4) ----
            if trade is not None:
                delta_ev, nom_ev = evenement_dans(t_srv)
                if delta_ev is not None and delta_ev <= MACRO_BLOCAGE_S:
                    print(f"{dt_srv:%H:%M:%S} SORTIE ANTICIPÉE : macro "
                          f"imminente ({nom_ev}, {delta_ev / 60:.0f} min)")
                    fermer_marche(trade, "macro_imminente")
                    trade["temoin"].forcer(bid, ask)
                    journaliser(trade, issue_forcee="anticipee",
                                motif=f"macro:{nom_ev}")
                    trade = None
                    if verifier_arrets(t_srv):
                        break

            # ---------- barre M5 close : contexte + signal ----------
            barre_close = (t_srv // TF_S) * TF_S - TF_S
            if barre_close > derniere_barre:
                rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5,
                                                0, 320)
                if rates is None or len(rates) < 80:
                    continue
                noms = rates.dtype.names
                for requis in ("time", "high", "low", "close", "tick_volume"):
                    if requis not in noms:
                        raise AttributeError(f"champ '{requis}' absent. "
                                             f"Réels : {noms}")
                df = pd.DataFrame({k: rates[k] for k in
                                   ("time", "high", "low", "close",
                                    "tick_volume")})
                df = df[df["time"] <= barre_close]
                if len(df) < VOL_FENETRE + 25 or \
                        int(df["time"].iloc[-1]) != barre_close:
                    continue
                derniere_barre = barre_close

                hauts, bas = fractales(df.tail(200))
                jambe = jambe_et_fib(hauts, bas)
                delta_ev, nom_ev = evenement_dans(t_srv)
                append_csv(CONTEXTE, COL_CTX, {
                    "ts_barre": barre_close,
                    "swing_high": hauts[-1][1] if hauts else "",
                    "swing_low": bas[-1][1] if bas else "",
                    "sens_jambe": jambe["sens"] if jambe else "",
                    "niveaux_fib": ";".join(
                        f"{r}:{p:.2f}" for r, p in
                        (jambe["niveaux"].items() if jambe else [])),
                    "n_supports": len(bas), "n_resistances": len(hauts),
                    "prochain_evenement": nom_ev,
                    "minutes_avant": round(delta_ev / 60) if delta_ev
                    is not None else ""})

                ema9 = df["close"].ewm(span=9, adjust=False).mean()
                ema21 = df["close"].ewm(span=21, adjust=False).mean()
                d = (ema9 - ema21).to_numpy()
                dprev, dlast = float(d[-2]), float(d[-1])
                vol_sig = float(df["tick_volume"].iloc[-1])
                vol_ma = float(df["tick_volume"].iloc[-1 - VOL_FENETRE:-1]
                               .mean())

                haussier = dprev <= 0 and dlast > 0
                baissier = dprev >= 0 and dlast < 0
                if haussier or baissier:
                    sens = 1 if haussier else -1
                    base_sig = {"ts_barre": barre_close, "dPrev": dprev,
                                "dLast": dlast, "volume": int(vol_sig),
                                "vol_moy20": round(vol_ma, 1)}
                    if not (vol_sig >= vol_ma and vol_sig >= VOL_SEUIL_ABS):
                        append_csv(SIGNAUX, COL_SIG, {**base_sig,
                                   "decision": "INVALIDE",
                                   "motif": "volume insuffisant"})
                    elif trade is not None:
                        reg.signaux_ignores += 1
                        append_csv(SIGNAUX, COL_SIG, {**base_sig,
                                   "decision": "IGNORE",
                                   "motif": "trade en cours"})
                    elif entree_bloquee:
                        append_csv(SIGNAUX, COL_SIG, {**base_sig,
                                   "decision": "IGNORE",
                                   "motif": "pause/week-end"})
                    elif delta_ev is not None and \
                            delta_ev <= MACRO_BLOCAGE_S:
                        reg.refus_macro += 1
                        append_csv(SIGNAUX, COL_SIG, {**base_sig,
                                   "decision": "REFUSE",
                                   "motif": f"macro {nom_ev}"})
                    else:
                        t2 = mt5.symbol_info_tick(SYMBOL)
                        spread_now = (t2.ask - t2.bid) if t2 else 99.0
                        if spread_now > SPREAD_MAX_ENTREE:
                            reg.refus_spread += 1
                            append_csv(SIGNAUX, COL_SIG, {**base_sig,
                                       "decision": "REFUSE",
                                       "motif": f"spread {spread_now:.2f}"})
                        else:
                            prix_ref = t2.ask if sens > 0 else t2.bid
                            fs, niveaux = facteurs_confiance(
                                sens, prix_ref, vol_sig, vol_ma, hauts,
                                bas, jambe, delta_ev)
                            taille = TAILLE_FIXE   # v4 : taille FIXE
                            if sens > 0:
                                sl = round(prix_ref - SL_USD, digits)
                                tp = round(prix_ref + TP_USD, digits)
                            else:
                                sl = round(prix_ref + SL_USD, digits)
                                tp = round(prix_ref - TP_USD, digits)
                            if sl <= 0 or \
                                    (sens > 0 and not sl < prix_ref < tp) or \
                                    (sens < 0 and not tp < prix_ref < sl):
                                raise RuntimeError(
                                    f"SL/TP incohérents : "
                                    f"{sl}/{prix_ref}/{tp}")
                            res, prix, t3 = envoyer_ordre(
                                sens, taille, sl, tp, "methodeV-v4")
                            if res is None:
                                raise RuntimeError(
                                    f"order_send None : {mt5.last_error()}")
                            if res.retcode != mt5.TRADE_RETCODE_DONE:
                                reg.refus_retcode += 1
                                append_csv(SIGNAUX, COL_SIG, {**base_sig,
                                           "decision": "REFUSE",
                                           "motif":
                                           f"retcode {res.retcode}"})
                                print(f"entrée refusée "
                                      f"retcode={res.retcode}")
                            else:
                                poss = None
                                for _ in range(15):
                                    poss = positions_magic()
                                    if poss:
                                        break
                                    time_mod.sleep(1)
                                if not poss:
                                    raise RuntimeError(
                                        "position introuvable après DONE")
                                p0 = poss[0]
                                sens_t = 1 if rng.integers(0, 2) == 1 else -1
                                tm = Temoin(sens_t, t3.bid, t3.ask, t_srv,
                                            taille)
                                temoins_actifs.append(tm)
                                trade = {"tickets": [p0.ticket],
                                         "ids": [p0.identifier],
                                         "volumes": [p0.volume],
                                         "sens": sens, "ts": t_srv,
                                         "prix_premiere": float(res.price),
                                         "slippage":
                                         (float(res.price) - prix) * sens,
                                         "spread": spread_now, "sl": sl,
                                         "tp": tp, "retcode": res.retcode,
                                         "volume_total": taille,
                                         "n_entrees": 1,
                                         "facteurs": "+".join(fs),
                                         "temoin": tm,
                                         "alerte_sl": False,
                                         "alerte_tp": False}
                                append_csv(SIGNAUX, COL_SIG, {**base_sig,
                                           "decision": "VALIDE",
                                           "facteurs": "+".join(fs),
                                           "taille": taille,
                                           "motif": ";".join(niveaux)
                                           or "aucun niveau"})
                                print(f"{dt_srv:%H:%M:%S} ENTRÉE "
                                      f"{'LONG' if sens > 0 else 'SHORT'} "
                                      f"{taille:.2f} lot facteurs="
                                      f"{'+'.join(fs)} (observés) prix "
                                      f"{prix} → {res.price} SL {sl} "
                                      f"TP {tp} (témoin "
                                      f"{'long' if sens_t > 0 else 'short'})")

            if time_mod.time() - dernier_rapport >= RAPPORT_S:
                dernier_rapport = time_mod.time()
                rapport(reg, t_srv)
    except Exception:
        if trade is not None:
            print("EXCEPTION avec position ouverte : SL/TP restent actifs "
                  "côté serveur.")
        raise
    finally:
        disconnect()

    s = reg.stats()
    verdict = "ÉCHEC"
    if s.get("n", 0) >= CIBLE_N and s.get("esperance", 0) > 0 and \
            s.get("t", 0) > 2.0 and s.get("ecart_temoin_sigma", 0) > 2.0:
        verdict = "SUCCÈS (critères pré-enregistrés atteints)"
    with open(LIVE, "a", encoding="utf-8") as f:
        f.write(f"\nVERDICT PRÉ-ENREGISTRÉ v4 : {verdict}\n")
    print(f"VERDICT PRÉ-ENREGISTRÉ v4 : {verdict}")


if __name__ == "__main__":
    main()
