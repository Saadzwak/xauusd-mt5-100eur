"""Phase 1 — inventaire en LECTURE SEULE du compte et du symbole or.

Ne passe aucun ordre. Écrit son rapport dans data/inventaire.txt.
Toute donnée chiffrée vient de account_info() / symbol_info() /
order_calc_margin() ; rien n'est codé en dur (voir CLAUDE.md, règle 4).
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import MetaTrader5 as mt5

from config import CAPITAL_REF_EUR, SYMBOL
from connect import connect, disconnect


def champ(obj, nom):
    """Accès à un attribut d'une structure MT5 sans jamais inventer un nom.

    Si l'attribut n'existe pas, échoue bruyamment en listant les champs
    réellement présents (règle 6 de CLAUDE.md).
    """
    d = obj._asdict()
    if nom not in d:
        raise AttributeError(
            f"Champ '{nom}' absent de {type(obj).__name__}. "
            f"Champs réels : {sorted(d.keys())}"
        )
    return d[nom]


def nom_trade_mode(mode):
    correspondance = {
        mt5.ACCOUNT_TRADE_MODE_DEMO: "ACCOUNT_TRADE_MODE_DEMO",
        mt5.ACCOUNT_TRADE_MODE_CONTEST: "ACCOUNT_TRADE_MODE_CONTEST",
        mt5.ACCOUNT_TRADE_MODE_REAL: "ACCOUNT_TRADE_MODE_REAL",
    }
    if mode not in correspondance:
        raise ValueError(f"trade_mode inconnu : {mode}")
    return correspondance[mode]


def main():
    compte = connect()
    lignes = []

    def w(texte=""):
        lignes.append(texte)

    # ---------------- Compte ----------------
    w("=" * 64)
    w("INVENTAIRE PHASE 1 — LECTURE SEULE")
    w("=" * 64)
    w()
    w("--- COMPTE ---")
    w(f"login            : {champ(compte, 'login')}")
    w(f"serveur          : {champ(compte, 'server')}")
    w(f"société          : {champ(compte, 'company')}")
    w(f"devise           : {champ(compte, 'currency')}")
    w(f"solde            : {champ(compte, 'balance')}")
    w(f"levier           : 1:{champ(compte, 'leverage')}")
    w(f"trade_mode       : {champ(compte, 'trade_mode')} "
      f"({nom_trade_mode(champ(compte, 'trade_mode'))})")
    w(f"stop-out (margin_so_so)   : {champ(compte, 'margin_so_so')}")
    w(f"mode stop-out (margin_so_mode) : {champ(compte, 'margin_so_mode')} "
      f"(0 = pourcentage, 1 = montant)")
    w()

    devise_compte = champ(compte, "currency")

    # ---------------- Symbole ----------------
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        candidats = mt5.symbols_get()
        if candidats is None:
            raise RuntimeError(f"symbols_get() a échoué : {mt5.last_error()}")
        ors = [s.name for s in candidats
               if "XAU" in s.name.upper() or "GOLD" in s.name.upper()]
        disconnect()
        print(f"Symbole '{SYMBOL}' introuvable.")
        print(f"Symboles contenant XAU ou GOLD chez ce broker : {ors}")
        print("Indiquer lequel utiliser dans config.py.")
        sys.exit(2)

    if not champ(info, "visible"):
        if not mt5.symbol_select(SYMBOL, True):
            raise RuntimeError(
                f"symbol_select({SYMBOL}) a échoué : {mt5.last_error()}"
            )
        info = mt5.symbol_info(SYMBOL)
        if info is None:
            raise RuntimeError(
                f"symbol_info({SYMBOL}) None après symbol_select : {mt5.last_error()}"
            )

    bid = champ(info, "bid")
    ask = champ(info, "ask")
    point = champ(info, "point")
    digits = champ(info, "digits")
    volume_min = champ(info, "volume_min")
    volume_step = champ(info, "volume_step")
    volume_max = champ(info, "volume_max")
    contrat = champ(info, "trade_contract_size")
    stops_level = champ(info, "trade_stops_level")
    freeze_level = champ(info, "trade_freeze_level")
    tick_value = champ(info, "trade_tick_value")
    tick_size = champ(info, "trade_tick_size")

    if bid <= 0 or ask <= 0:
        raise RuntimeError(
            f"Prix invalides pour {SYMBOL} : bid={bid}, ask={ask}. "
            "Marché fermé ou symbole non coté ?"
        )
    if tick_size <= 0 or tick_value <= 0:
        raise RuntimeError(
            f"trade_tick_size={tick_size} / trade_tick_value={tick_value} "
            "invalides — impossible de convertir un mouvement en devise du compte."
        )

    spread_abs = ask - bid

    w(f"--- SYMBOLE : {SYMBOL} ---")
    w(f"description         : {champ(info, 'description')}")
    w(f"trade_contract_size : {contrat}")
    w(f"volume_min          : {volume_min}")
    w(f"volume_step         : {volume_step}")
    w(f"volume_max          : {volume_max}")
    w(f"digits              : {digits}")
    w(f"point               : {point}")
    w(f"bid                 : {bid}")
    w(f"ask                 : {ask}")
    w(f"spread absolu (ask-bid) : {spread_abs:.{digits}f} "
      f"(= {spread_abs / point:.0f} points)")
    w(f"trade_stops_level   : {stops_level} points")
    w(f"trade_freeze_level  : {freeze_level} points")
    w(f"trade_tick_value    : {tick_value} {devise_compte} par tick et par lot")
    w(f"trade_tick_size     : {tick_size}")
    w()

    # ---------------- Marge pour le volume minimum ----------------
    marge = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, SYMBOL, volume_min, ask)
    if marge is None:
        raise RuntimeError(
            f"order_calc_margin() a échoué : {mt5.last_error()}"
        )
    w(f"--- MARGE ---")
    w(f"marge requise pour {volume_min} lot (achat au ask) : "
      f"{marge} {devise_compte}")
    w(f"soit {marge / CAPITAL_REF_EUR * 100:.1f} % du capital de référence "
      f"({CAPITAL_REF_EUR:.0f} EUR)")
    w()

    # ---------------- Dérivés sur capital de référence ----------------
    # Valeur d'un mouvement de 1 $ : on n'utilise PAS trade_tick_value.
    # Autorité : order_calc_profit(), le calculateur du terminal (lecture
    # seule, aucun ordre). Contrôle croisé contre trade_tick_value ci-dessous.
    valeur_1usd = mt5.order_calc_profit(
        mt5.ORDER_TYPE_BUY, SYMBOL, volume_min, ask, ask + 1.0
    )
    if valeur_1usd is None:
        raise RuntimeError(f"order_calc_profit() a échoué : {mt5.last_error()}")
    if valeur_1usd <= 0:
        raise RuntimeError(f"order_calc_profit() a renvoyé {valeur_1usd} <= 0")

    valeur_1usd_tick = 1.0 / tick_size * tick_value * volume_min

    w(f"--- DÉRIVÉS (capital de référence : {CAPITAL_REF_EUR:.0f} EUR) ---")
    if devise_compte != "EUR":
        w(f"ATTENTION : devise du compte = {devise_compte}, pas EUR. "
          "Les pourcentages ci-dessous sont en devise du compte et "
          "nécessitent une conversion explicite avant toute décision.")
    w(f"Valeur d'un mouvement de 1 $ du prix, pour {volume_min} lot :")
    w(f"  via order_calc_profit (AUTORITÉ) : {valeur_1usd:.4f} {devise_compte}")
    w(f"  via trade_tick_value (contrôle)  : {valeur_1usd_tick:.4f} {devise_compte}")
    if abs(valeur_1usd - valeur_1usd_tick) / valeur_1usd > 0.02:
        w(f"  ANOMALIE : trade_tick_value ({tick_value}) est incohérent avec "
          "le calculateur du terminal et la taille de contrat. "
          "trade_tick_value NE DOIT PAS être utilisé dans les phases suivantes ; "
          "order_calc_profit fait foi.")
    w()
    w(f"Risque à l'atteinte du stop, position de {volume_min} lot "
      "(via order_calc_profit) :")
    for stop_usd in (5.0, 10.0, 20.0):
        risque = stop_usd * valeur_1usd
        pct = risque / CAPITAL_REF_EUR * 100.0
        w(f"  stop {stop_usd:5.1f} $ : perte {risque:8.2f} {devise_compte} "
          f"= {pct:5.1f} % du capital de référence")
    w()
    cout_spread = spread_abs * valeur_1usd
    w(f"Coût du spread instantané pour un aller-retour de {volume_min} lot : "
      f"{spread_abs:.{digits}f} $ × {valeur_1usd:.4f} = {cout_spread:.2f} "
      f"{devise_compte} = {cout_spread / CAPITAL_REF_EUR * 100:.2f} % du "
      "capital de référence (mesure ponctuelle ; la phase 2 mesurera la "
      "distribution réelle)")
    w()
    stop_min_prix = stops_level * point
    w(f"Stop minimum autorisé (trade_stops_level × point) : "
      f"{stop_min_prix:.{digits}f} $ ({stops_level} points)")
    if stops_level == 0:
        w("  → trade_stops_level = 0 : le broker n'impose pas de distance "
          "minimale via ce champ (le spread reste la contrainte pratique).")
    w()
    w("PLANCHER DE RISQUE : le volume ne peut pas descendre sous "
      f"{volume_min} lot. Tout stop de S dollars coûte donc au minimum "
      f"S × {valeur_1usd:.4f} {devise_compte}, spread non compris. "
      "Le risque par trade ne peut être réduit qu'en réduisant la distance "
      "du stop, jamais la taille de position.")

    disconnect()

    rapport = "\n".join(lignes) + "\n"
    dossier_data = RACINE / "data"
    dossier_data.mkdir(exist_ok=True)
    (dossier_data / "inventaire.txt").write_text(rapport, encoding="utf-8")
    print(rapport)


if __name__ == "__main__":
    main()
