"""Phase 6, étape 1 — EXTRACTION lecture stricte du compte réel (REAL_LOGIN).

EXCEPTION CLAUDE.md (limitative) : ce fichier est le SEUL du projet
autorisé à cibler le compte réel (REAL_LOGIN, cf. config.py, hors dépôt),
avec pour seules fonctions MT5 :
history_deals_get / history_orders_get / account_info / symbol_info.
- Aucune fonction d'écriture ou de simulation d'ordre n'est importée ni
  appelée (pas de order_send, order_check, ni même symbol_select).
- L'initialisation gardée ci-dessous est l'unique exception à la règle 2
  (connect.py impose le démo et ne doit pas connaître REAL_LOGIN).
- Séquence : extraire le brut → shutdown() IMMÉDIAT → reconstruction et
  écriture des fichiers HORS connexion → fin. Aucune analyse en session
  connectée.

Sorties : data/deals_bruts_reel.csv, data/historique_reel.csv,
data/compte_reel.json.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import MetaTrader5 as mt5
import pandas as pd

from config import TERMINAL, REAL_LOGIN

LOGIN_REEL = REAL_LOGIN


def champ(obj, nom):
    d = obj._asdict()
    if nom not in d:
        raise AttributeError(f"Champ '{nom}' absent de {type(obj).__name__}. "
                             f"Champs réels : {sorted(d.keys())}")
    return d[nom]


def noms_constantes(prefixe):
    return {getattr(mt5, n): n for n in dir(mt5) if n.startswith(prefixe)}


def extraire():
    """Session connectée : lecture brute uniquement, puis shutdown()."""
    if not mt5.initialize(path=TERMINAL):
        raise RuntimeError(f"mt5.initialize() a échoué : {mt5.last_error()}")

    compte = mt5.account_info()
    if compte is None:
        err = mt5.last_error()
        mt5.shutdown()
        raise RuntimeError(f"account_info() None : {err}")

    if champ(compte, "login") != LOGIN_REEL:
        login = champ(compte, "login")
        mt5.shutdown()
        print(f"REFUS : le terminal est connecté au compte {login}, "
              f"pas au compte réel {LOGIN_REEL}.")
        print("Bascule le terminal sur le compte réel toi-même "
              "(Fichier > Se connecter au compte de trading), puis relance "
              "ce script. Je ne saisis jamais d'identifiants.")
        sys.exit(2)

    modes = noms_constantes("ACCOUNT_TRADE_MODE")
    trade_mode = champ(compte, "trade_mode")
    if trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
        print("=" * 64)
        print("AVERTISSEMENT : COMPTE RÉEL (ACCOUNT_TRADE_MODE_REAL).")
        print("Lecture stricte uniquement — aucun ordre, aucune écriture.")
        print("=" * 64)

    infos_compte = {
        "login": champ(compte, "login"),
        "broker": champ(compte, "company"),
        "serveur": champ(compte, "server"),
        "devise": champ(compte, "currency"),
        "levier": champ(compte, "leverage"),
        "stop_out": champ(compte, "margin_so_so"),
        "stop_out_mode": champ(compte, "margin_so_mode"),
        "solde": champ(compte, "balance"),
        "equity": champ(compte, "equity"),
        "trade_mode": trade_mode,
        "trade_mode_nom": modes.get(trade_mode, str(trade_mode)),
        "extrait_utc": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}",
    }

    deals = mt5.history_deals_get(datetime(2005, 1, 1),
                                  datetime.now(timezone.utc)
                                  + timedelta(days=2))
    if deals is None:
        err = mt5.last_error()
        mt5.shutdown()
        raise RuntimeError(f"history_deals_get() None : {err}")
    if len(deals) == 0:
        mt5.shutdown()
        raise RuntimeError("history_deals_get() a renvoyé 0 deal — "
                           "historique non synchronisé ? Ouvrir l'onglet "
                           "Historique du terminal sur « Toute la période » "
                           "puis relancer.")
    lignes_deals = [d._asdict() for d in deals]

    symboles = sorted({d["symbol"] for d in lignes_deals if d["symbol"]})
    infos_symboles = {}
    for s in symboles:
        si = mt5.symbol_info(s)
        if si is None:
            infos_symboles[s] = {"note": "symbol_info None (symbole absent "
                                         "du Market Watch ; pas de "
                                         "symbol_select en lecture stricte)"}
        else:
            infos_symboles[s] = {
                "contract_size": champ(si, "trade_contract_size"),
                "volume_min": champ(si, "volume_min"),
                "digits": champ(si, "digits"),
                "point": champ(si, "point"),
                "bid": champ(si, "bid"),
                "ask": champ(si, "ask"),
                "spread_courant": champ(si, "ask") - champ(si, "bid"),
                "devise_profit": champ(si, "currency_profit"),
            }

    tables_constantes = {
        "type": noms_constantes("DEAL_TYPE"),
        "entry": noms_constantes("DEAL_ENTRY"),
        "reason": noms_constantes("DEAL_REASON"),
    }

    mt5.shutdown()          # ← fin de la session connectée, tout de suite
    return infos_compte, infos_symboles, lignes_deals, tables_constantes


def reconstruire(infos_compte, infos_symboles, lignes_deals, tables):
    """HORS connexion : positions par position_id + contrôles."""
    df = pd.DataFrame(lignes_deals)
    df["type_nom"] = df["type"].map(tables["type"]).fillna(df["type"].astype(str))
    df["entry_nom"] = df["entry"].map(tables["entry"]).fillna(df["entry"].astype(str))
    df["reason_nom"] = df["reason"].map(tables["reason"]).fillna(df["reason"].astype(str))
    df = df.sort_values(["time", "ticket"]).reset_index(drop=True)
    df.to_csv(RACINE / "data" / "deals_bruts_reel.csv", index=False)

    est_balance = df["type_nom"].str.contains("BALANCE|CREDIT", regex=True)
    ops_balance = df[est_balance]
    trades = df[~est_balance & (df["position_id"] != 0)]

    fee = df["fee"] if "fee" in df.columns else 0.0
    df["_net"] = df["profit"] + df["commission"] + df["swap"] + fee
    total_flux = float(df["_net"].sum())
    solde_initial_implicite = infos_compte["solde"] - total_flux

    positions = []
    ouvertes, renversements = [], 0
    for pid, g in trades.groupby("position_id"):
        g = g.sort_values(["time", "ticket"])
        ins = g[g["entry_nom"] == "DEAL_ENTRY_IN"]
        outs = g[g["entry_nom"].isin(["DEAL_ENTRY_OUT", "DEAL_ENTRY_OUT_BY"])]
        inout = g[g["entry_nom"] == "DEAL_ENTRY_INOUT"]
        if len(inout):
            renversements += 1
        if len(ins) == 0:
            ouvertes.append(pid)        # entrée hors historique → tronqué
            continue
        vol_in = ins["volume"].sum()
        vol_out = outs["volume"].sum() + inout["volume"].sum()
        if vol_out + 1e-9 < vol_in or len(outs) + len(inout) == 0:
            ouvertes.append(pid)        # encore ouverte ou clôture manquante
            continue
        sens = "long" if ins.iloc[0]["type_nom"] == "DEAL_TYPE_BUY" else "short"
        sortants = pd.concat([outs, inout]) if len(inout) else outs
        positions.append({
            "position_id": pid,
            "symbole": ins.iloc[0]["symbol"],
            "sens": sens,
            "volume": vol_in,
            "prix_entree": float((ins["price"] * ins["volume"]).sum() / vol_in),
            "prix_sortie": float((sortants["price"] * sortants["volume"]).sum()
                                 / sortants["volume"].sum()),
            "t_entree": int(ins.iloc[0]["time"]),
            "t_sortie": int(sortants.iloc[-1]["time"]),
            "profit_brut": float(g["profit"].sum()),
            "commission": float(g["commission"].sum()),
            "swap": float(g["swap"].sum()),
            "fee": float(g["fee"].sum()) if "fee" in g.columns else 0.0,
            "n_deals": len(g),
            "renversement": bool(len(inout)),
            "raison_sortie": sortants.iloc[-1]["reason_nom"],
        })
    pos = pd.DataFrame(positions).sort_values("t_entree").reset_index(drop=True)
    if len(pos) == 0:
        raise RuntimeError("Aucune position fermée reconstituée.")
    pos["net"] = pos["profit_brut"] + pos["commission"] + pos["swap"] + pos["fee"]
    pos["duree_s"] = pos["t_sortie"] - pos["t_entree"]
    dt = pd.to_datetime(pos["t_entree"], unit="s")
    pos["heure_entree"] = dt.dt.hour
    pos["jour_semaine"] = dt.dt.dayofweek

    # solde avant chaque position : registre chronologique de tous les flux
    df_tri = df.sort_values(["time", "ticket"])
    cum = df_tri["_net"].cumsum().shift(1, fill_value=0.0)
    cum_avant = pd.Series(cum.to_numpy(), index=df_tri["time"].to_numpy())
    reg_t = df_tri["time"].to_numpy()
    reg_c = cum.to_numpy()
    import numpy as np
    idx = np.searchsorted(reg_t, pos["t_entree"].to_numpy(), side="left")
    pos["solde_avant"] = solde_initial_implicite + reg_c[np.minimum(
        idx, len(reg_c) - 1)]
    pos.to_csv(RACINE / "data" / "historique_reel.csv", index=False)

    premier = datetime.utcfromtimestamp(int(df["time"].min()))
    dernier = datetime.utcfromtimestamp(int(df["time"].max()))
    infos = {
        "compte": infos_compte,
        "symboles": infos_symboles,
        "n_deals": len(df),
        "n_positions_fermees": len(pos),
        "n_positions_ouvertes_ou_tronquees": len(ouvertes),
        "n_renversements": renversements,
        "premier_deal": f"{premier:%Y-%m-%d %H:%M}",
        "dernier_deal": f"{dernier:%Y-%m-%d %H:%M}",
        "depots_retraits": {
            "n": int(len(ops_balance)),
            "total": float(ops_balance["profit"].sum()),
        },
        "solde_initial_implicite": round(solde_initial_implicite, 2),
        "historique_tronque_probable": abs(solde_initial_implicite) > 0.01
        and len(ops_balance) == 0,
    }
    (RACINE / "data" / "compte_reel.json").write_text(
        json.dumps(infos, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(infos, indent=2, ensure_ascii=False))
    print(f"\npositions fermées écrites : {len(pos)} → data/historique_reel.csv")
    if abs(solde_initial_implicite) > 0.01 and len(ops_balance) > 0:
        print(f"NB : solde initial implicite {solde_initial_implicite:+.2f} "
              f"{infos_compte['devise']} (dépôts/retraits inclus dans le "
              "registre) — si ≠ 0, l'historique commence après l'ouverture "
              "du compte : TRONQUÉ, à signaler.")


def main():
    infos_compte, infos_symboles, lignes_deals, tables = extraire()
    reconstruire(infos_compte, infos_symboles, lignes_deals, tables)


if __name__ == "__main__":
    main()
