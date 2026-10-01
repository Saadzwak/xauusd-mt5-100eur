"""Point d'entrée UNIQUE pour tout accès à MetaTrader 5.

Règles appliquées ici (voir CLAUDE.md) :
- vérifie login == DEMO_LOGIN et trade_mode == ACCOUNT_TRADE_MODE_DEMO
  avant de rendre la main ; sinon shutdown + exception.
- aucune valeur de repli : toute erreur MT5 remonte avec mt5.last_error().
Aucun autre module ne doit appeler mt5.initialize() directement.
"""

import MetaTrader5 as mt5

from config import DEMO_LOGIN, TERMINAL


def connect():
    """Attache au terminal MT5 déjà lancé et vérifie le compte.

    Retourne l'objet account_info après vérification.
    Lève RuntimeError si le login ou le trade_mode ne correspondent pas.
    """
    if not mt5.initialize(path=TERMINAL):
        raise RuntimeError(f"mt5.initialize() a échoué : {mt5.last_error()}")

    info = mt5.account_info()
    if info is None:
        err = mt5.last_error()
        mt5.shutdown()
        raise RuntimeError(f"account_info() a renvoyé None : {err}")

    if info.login != DEMO_LOGIN:
        login = info.login
        mt5.shutdown()
        raise RuntimeError(
            f"REFUS : login connecté {login} != login démo attendu {DEMO_LOGIN}. "
            "Déconnexion immédiate."
        )

    if info.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        mode = info.trade_mode
        mt5.shutdown()
        raise RuntimeError(
            f"REFUS : trade_mode={mode} n'est pas ACCOUNT_TRADE_MODE_DEMO "
            f"({mt5.ACCOUNT_TRADE_MODE_DEMO}). Déconnexion immédiate."
        )

    return info


def disconnect():
    mt5.shutdown()
