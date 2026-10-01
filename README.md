# Recherche quantitative XAUUSD sur MetaTrader 5 — l'or est-il tradable avec 100 € ?

Étude de mesure, pas de génération de profit. **Question unique :**
existe-t-il, sur l'or (XAUUSD), une stratégie à **espérance
mathématique positive après coûts réels**, *exécutable sur un capital
de référence de 100 €* ?

**Réponse établie par mesure : non.** Sur ce capital, avec ce feed et
ces coûts, aucune des familles testées (classiques, microstructure,
saisonnalité, régimes de volatilité, structures de sortie, croisement
EMA + volume) ne produit une stratégie exécutable à espérance positive
démontrable. Un résultat négatif rigoureusement établi est, ici, un
livrable réussi.

> ⚠️ **Avertissement.** Ce dépôt est un travail de recherche
> personnel. Ce n'est **pas** un conseil en investissement. Tout le
> travail d'exécution se fait sur un **compte démo** ; le trading de
> CFD sur l'or avec effet de levier est à haut risque de perte totale.

---

## Pourquoi 100 € change tout

Le vrai mur n'est pas le spread : c'est la **conjonction** du plancher
de volume du broker (0,01 lot = 1 once = ~0,86 € de P&L par dollar de
mouvement) et d'un capital de 100 €. Cette conjonction impose des
stops de 1,7–3 $ et interdit les horizons longs (en H1/H4, le lot
minimum risque 8–33 % du capital — incompatible avec un dimensionnement
prudent type quart de Kelly). Les signaux classiques testés n'apportent
au mieux que ~+1,5 point de taux de réussite là où il en faudrait
**~+10**.

Conséquence méthodologique centrale : la contrainte active est presque
toujours l'**exécutabilité** (capital × lot minimum), pas le coût. Au
seuil de coût pur, Kelly alloue déjà zéro.

## Méthodologie

Chaque phase est pré-enregistrée (grille d'hypothèses figée **avant**
simulation), chiffrée, et comparée à un **témoin à directions
aléatoires** sur la même machinerie — pour distinguer un edge réel du
simple bêta d'échantillon. Correction multi-tests appliquée.

| Phase | Objet | Résultat |
|------|-------|----------|
| 1 | Inventaire & conversion devise | `trade_tick_value` du serveur **erroné** (~×8,6) → banni ; `order_calc_profit()` fait foi |
| 2 | Coût réel du spread | 805 095 ticks / 15 j ; spread médian 0,30 $ ≈ 0,26 € l'aller-retour au lot min |
| 3 | Seuil à battre | il faut **+9 à +10 pts** de taux de réussite au-dessus du hasard ; H1/H4 exclus, M1/M5 seuls testables |
| 4 | Backtest | 14 hypothèses figées, **toutes négatives** IS et OOS ; Kelly plein négatif partout |
| 5 | Exploration élargie | microstructure, saisonnalité, régimes ATR, sorties asym. → **37 hypothèses cumulées, 0 publiable** |
| 6 | Audit lecture seule d'un compte réel | **verdict B** : espérance dans le bruit du témoin (−1,9 σ), aucun edge ; coût broker authentique **0,40 €** l'aller-retour (+54 % vs démo) |
| 7 | Forward test prospectif (démo, ordres réels) | discipline tenue ; P&L positif **expliqué par son propre témoin** → pas un edge |
| Méthode V | EMA9/EMA21 M5 + filtre volume | meilleure de l'étude (p̂ 0,631 OOS, témoin +2,0 σ) mais t 1,68 et quart-Kelly 0,003 lot → **non exécutable** |

### Deux enseignements marquants

- **Le dimensionnement « à la confiance » ne crée pas d'information.**
  Une variante (CLAUDE.md réécrit : tailles 0,02–0,05 lot selon
  confiance, renforts jusqu'à 0,15 lot) a atteint le **kill switch en
  35 minutes** (−93,88 € sur 100 € simulés). Quatre facteurs alignés
  n'ont produit aucune information directionnelle (témoin sous le
  hasard), seulement de la taille — exactement ce que les phases 1-6
  prédisaient.

- **L'audit du compte réel confirme le verdict** avec un coût encore
  plus défavorable que le démo : il n'y avait pas d'edge à détruire ;
  le sur-dimensionnement a simplement transformé une érosion lente en
  liquidations rapides.

### Un bug honnête à signaler

Lors du forward test v4, la protection macro (pas d'entrée à moins de
15 min d'un événement à fort impact) s'est révélée **inopérante** : sous
pandas 3.0, `pd.to_datetime(...).astype("int64")` renvoie des
**microsecondes** (plus des nanosecondes), et le `// 10**9` du code
produisait des epochs ~1000× trop petits — tous les événements du
calendrier tombaient « 56 ans dans le passé », si bien que la garde ne
s'est jamais déclenchée (y compris une entrée ~5 min après une décision
FOMC). Le défaut est documenté et sert d'illustration : un harnais de
mesure se vérifie aussi rigoureusement que la stratégie qu'il teste.

## Garde-fous (règles absolues)

- `order_send()` est **interdit partout sauf** `scripts/forward_demo.py`,
  et uniquement sur le compte **démo** (vérification `login` +
  `trade_mode` avant **chaque** ordre).
- Tout accès MT5 passe par `connect.py`, qui refuse de continuer si le
  compte n'est pas le démo attendu.
- Le compte réel n'est touché **qu'en lecture seule**, dans le seul
  `scripts/audit_reel.py` (extraction → `shutdown()` → analyse hors
  connexion). Son identifiant vit dans `config.py`, **hors dépôt**.
- Capital de référence **100 €**, jamais le solde démo affiché.

## Structure du dépôt

```
connect.py             point d'entrée MT5 unique (impose le démo)
config.example.py      gabarit de configuration (copier vers config.py)
CLAUDE.md              cahier des charges / règles du projet
scripts/
  inventaire.py        phase 1 — inventaire & conversions
  mesure_cout.py       phase 2 — coût réel du spread
  seuil.py             phase 3 — seuil d'exécutabilité
  backtest.py          phase 4 — 14 hypothèses figées
  temoin_aleatoire.py  témoin à directions aléatoires
  phase5_backtest.py   phase 5 — exploration élargie
  micro_minutes.py     microstructure M1
  levier_a.py          heures à faible spread
  audit_reel.py        phase 6 — extraction compte réel (lecture seule)
  analyse_reel.py      phase 6 — analyse hors connexion
  methode_v_backtest.py  Méthode V (EMA9/EMA21 + volume)
  phase8_backtest.py   backtest complémentaire
  forward_demo.py      phase 7 — forward test prospectif (démo)
  preregistre*.md      pré-enregistrements figés de chaque campagne
```

> Le dossier `data/` (données de marché brutes, journaux, extractions du
> compte réel, résultats chiffrés) est **volontairement exclu** du dépôt
> via `.gitignore` : volumineux et/ou personnel. Les conclusions
> chiffrées sont résumées ci-dessus.

## Installation

```bash
python -m venv .venv
. .venv/Scripts/activate      # Windows ; sous Unix : source .venv/bin/activate
pip install MetaTrader5 pandas numpy
cp config.example.py config.py   # puis renseigner DEMO_LOGIN et le chemin du terminal MT5
```

Un terminal **MetaTrader 5** connecté au compte démo doit tourner sur
la machine (l'API Python s'attache au terminal ; aucun mot de passe
n'est stocké par ce projet).

## Pièges MetaTrader 5 rencontrés (utiles à d'autres)

- `symbol_info().trade_tick_value` peut être **faux** — utiliser
  `order_calc_profit()` pour toute conversion mouvement → devise.
- Heure serveur en **UTC+3** (penser aux fenêtres macro et à la pause
  quotidienne 23h→01h).
- Compte en mode **hedging** : chaque entrée est une position distincte
  — en tenir compte pour agréger un trade et ses renforts.
- pandas ≥ 3.0 : résolution datetime **microseconde** par défaut —
  ne pas supposer des nanosecondes dans les conversions d'epoch.

## Verdict

**Espérance négative après coûts réels, sur toutes les familles testées,
in-sample et out-of-sample ; aucune configuration exécutable au sens du
quart de Kelly sur 100 €.** Ce qui pourrait changer le verdict (non
testé ici) : un capital nettement plus grand, un coût aller-retour bien
plus bas (compte *raw spread*, commission par lot à mesurer), ou une
classe de signaux hors de cette étude — auquel cas le comptage
d'hypothèses repartirait de zéro.
