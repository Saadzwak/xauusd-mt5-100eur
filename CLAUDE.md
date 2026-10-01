# Projet : recherche quantitative XAUUSD sur MetaTrader 5 (lecture seule)

## CONTRAINTE CENTRALE — LE CAPITAL SIMULÉ

Le démo affiche 3000 €. Ce chiffre est FAUX pour nos besoins.
Tous les calculs de risque, de sizing et de drawdown se font sur un
capital de référence de 100 EUR. Le solde démo réel n'est jamais
utilisé comme base de calcul, sous aucun prétexte.
Raison : le capital réel disponible est de 100 €. Un backtest calibré
sur 3000 € produirait des résultats sans rapport avec ce qui est
exécutable.

Cette contrainte a une conséquence dure à intégrer et quantifier :
le volume minimum broker est 0.01 lot, soit 1 once, soit 1 $ de P&L
par dollar de mouvement. Sur 100 €, cela impose un plancher de
risque par trade qui doit être calculé et rapporté explicitement
dès l'inventaire. Consigne mise à jour : la taille réellement
utilisée pour trader est bornée à la plage 0.02 – 0.05 lot par
entrée (cf. SIZING PAR ENTRÉE ci-dessous) — 0.01 lot n'est utilisé
nulle part comme taille de trade, uniquement comme granularité
minimale du broker.

## SIZING PAR ENTRÉE — basé sur la confiance (remplace l'ancienne approche Kelly)

La taille de position n'est pas fixée a priori et n'est plus dérivée
d'une formule de Kelly. Elle est fixée entrée par entrée, entre
0.02 et 0.05 lot, selon le niveau de confiance du signal au moment
de cette entrée précise — arrondie au pas de volume du broker
(symbol_info().volume_step).

Le niveau de confiance se compte à partir du nombre de facteurs
alignés au moment de l'entrée, parmi ceux déjà définis ailleurs
dans ce fichier :
1. le signal mécanique EMA9/EMA21 + filtre de volume est valide
   (condition nécessaire dans tous les cas) ;
2. le volume de la bougie de signal dépasse nettement le seuil
   (pas juste au-dessus, ex : ≥ 1,5x la moyenne des 20 bougies) ;
3. un support/résistance proche confirme le sens du signal ;
4. un niveau de retracement Fibonacci confirme le sens du signal ;
5. aucun événement macro à fort impact (Fed/FOMC ou autre rapport
   fort impact) n'est imminent.

Grille indicative — proposition à valider/ajuster par toi après
tests, ce n'est pas un chiffre qu'on avait déjà fixé ensemble :
- signal mécanique seul (facteur 1 uniquement) → 0.02 lot
- signal + 1 facteur de confirmation (2 au total) → 0.03 lot
- signal + 2 facteurs de confirmation (3 au total) → 0.04 lot
- signal + 3 facteurs de confirmation (4 au total) → 0.05 lot

Le bot doit logguer, pour chaque entrée, la liste des facteurs
retenus et la taille choisie, pour permettre une vérification a
posteriori.

## ENTRÉES MULTIPLES SUR UN MÊME TRADE

Le bot n'est plus limité à une seule entrée par trade. Il peut
renforcer une position déjà ouverte (plusieurs entrées dans le même
sens), à condition que :
- chaque entrée additionnelle soit justifiée par un nouveau facteur
  de confiance constaté à ce moment-là (ex : un nouveau niveau S/R
  ou Fibonacci validé, pas un simple ajout mécanique sans raison
  nouvelle) ;
- chaque entrée additionnelle ait sa propre taille déterminée par la
  grille de confiance ci-dessus ;
- le volume cumulé de toutes les entrées d'un même trade reste
  plafonné — proposition à valider : 0.15 lot au total par trade,
  chiffre nouveau que je propose ici, pas un plafond qu'on avait
  déjà arrêté ensemble ;
- le stop-loss et le kill switch (perte cumulée > 20 % du capital
  de référence) s'appliquent toujours sur la position agrégée, pas
  entrée par entrée isolément.

## DÉCOUVERTE PHASE 1 — trade_tick_value erroné

Sur MetaQuotes-Demo, symbol_info("XAUUSD").trade_tick_value renvoie
0.1 EUR/tick/lot, incohérent (facteur ~8,6) avec trade_contract_size
= 100 et EURUSD. Arbitré par order_calc_profit() : 0,86 EUR par
dollar de mouvement pour 0.01 lot. trade_tick_value est BANNI des
calculs ; order_calc_profit() fait foi pour toute conversion
mouvement → devise du compte.

## RÈGLE DE SIGNAL — MÉTHODE V (EMA9/EMA21 M5 + filtre de volume)

Instrument : XAUUSD. Timeframe : M5. Indicateurs : EMA9 et EMA21 sur
le prix de clôture (close).

Signal calculé uniquement à la clôture d'une bougie, jamais sur la
bougie en formation (pas de lookahead) :

```
dPrev = EMA9[n-2] - EMA21[n-2]
dLast = EMA9[n-1] - EMA21[n-1]

BUY  si dPrev <= 0 ET dLast > 0
SELL si dPrev >= 0 ET dLast < 0
```

Filtre de volume obligatoire : le volume de la bougie de signal doit
être `>=` moyenne du volume des 20 bougies clôturées précédentes
(bougie de signal exclue) ET `>= 200` (seuil absolu). Si l'une des
deux conditions échoue, le signal est invalide.

Permanence : un croisement invalidé pour volume insuffisant sur une
bougie donnée est invalide pour toujours. Ne jamais le re-signaler
ni ré-agir dessus, même si les EMA restent proches ensuite.

SL/TP standard, en unités de prix XAUUSD (niveau d'entrée ± N) :

```
BUY  : SL = entrée - 10   |  TP indicatif = entrée + 7 (plage 6 à 8)
SELL : SL = entrée + 10   |  TP indicatif = entrée - 7 (plage 6 à 8)
```

Ces niveaux standard ne varient jamais automatiquement d'un signal
à l'autre. Le bot peut en revanche sortir avant qu'ils soient
touchés — cf. section "Gestion de sortie anticipée" plus bas.

## RÈGLES ABSOLUES

1. order_send() est INTERDIT. Aucun ordre, même sur le démo, même en
   test. Le dossier execution/ n'existe pas et ne doit pas être créé.
2. Tout accès MT5 passe par connect.py, qui vérifie login ET
   trade_mode avant toute opération. Aucun appel direct à
   mt5.initialize() ailleurs.
3. Refuser et s'arrêter si login != 111371411 ou si trade_mode
   n'est pas ACCOUNT_TRADE_MODE_DEMO.
4. Aucune valeur numérique en dur pour le contrat, le spread, le
   volume minimum ou le levier. Tout vient de symbol_info() et
   account_info().
5. Échouer bruyamment. Aucun try/except silencieux, aucune valeur de
   repli. Toute erreur MT5 remonte avec mt5.last_error().
6. Ne jamais inventer un nom d'attribut de l'API MetaTrader5. En cas
   de doute, introspecter avec _asdict(), lister les champs réels, et
   le signaler.
7. Capital de référence : 100 EUR. Jamais le solde démo.

## ANALYSE CONTEXTUELLE OBLIGATOIRE (avant tout signal ET pendant toute position ouverte)

En plus du croisement EMA9/EMA21 + filtre de volume (règle mécanique de base, inchangée pour l'ENTRÉE), le bot doit désormais aussi calculer et logguer, à chaque bougie clôturée :

- Niveaux de retracement Fibonacci : calculés causalement, sur le dernier swing haut/bas détecté sur les seules bougies clôturées — jamais sur la bougie en formation. Niveaux standards : 23,6 % / 38,2 % / 50 % / 61,8 % / 78,6 %.
- Supports et résistances : méthode fractale causale (swing high/low sur fenêtre de K bougies clôturées, K=2 ou K=3), filtrée par timestamp epoch réel — jamais par comparaison de chaîne de caractères sur l'heure.
- Contexte macro / news : vérifier le calendrier économique avant d'entrer et pendant toute position ouverte, en particulier les décisions et discours de la Fed (FOMC, décision de taux, conférence de presse, discours de membres du FOMC), ainsi que les autres rapports à fort impact (NFP, CPI, PCE, Michigan Consumer Sentiment, et tout autre événement classé fort impact sur le calendrier économique). Ne jamais ignorer un événement macro majeur prévu dans les minutes ou heures suivantes.

Ces éléments ne remplacent jamais le signal mécanique EMA9/EMA21 + volume pour décider une ENTRÉE. Ils servent (a) de contexte loggé systématiquement pour l'analyse post-trade, et (b) de base pour la gestion de sortie anticipée décrite plus bas.

## EXCEPTION PHASE 6 — audit du compte réel (lecture stricte)

Compte réel (REAL_LOGIN, cf. config.py) autorisé UNIQUEMENT dans scripts/audit_reel.py,
UNIQUEMENT pour history_deals_get / history_orders_get / account_info /
symbol_info.

- Ce fichier n'importe ni order_send, ni order_check, ni aucune
  fonction d'écriture ou de simulation d'ordre.
- Il extrait, écrit data/historique_reel.csv, appelle shutdown(),
  et se termine. Aucune analyse en session connectée.
- Toute l'analyse se fait ensuite hors connexion, sur le CSV, dans
  un fichier séparé : scripts/analyse_reel.py, qui n'importe jamais
  MetaTrader5.
- Aucun autre script du projet ne peut cibler le compte réel. La règle 1
  reste en vigueur partout ailleurs.

## EXCEPTION PHASE 7 — exécution démo (test prospectif)

order_send() autorisé UNIQUEMENT dans scripts/forward_demo.py,
UNIQUEMENT sur le compte démo 111371411 (vérif login + trade_mode
avant CHAQUE ordre, pas seulement à la connexion).
- entrée déclenchée uniquement par un signal valide de la RÈGLE DE
  SIGNAL — MÉTHODE V ci-dessus (EMA9/EMA21 + filtre de volume)
- taille de chaque entrée dans la plage 0.02 – 0.05 lot, selon le
  niveau de confiance (cf. SIZING PAR ENTRÉE), jamais à 0.01
- plusieurs entrées autorisées sur un même trade dans le même sens
  (cf. ENTRÉES MULTIPLES SUR UN MÊME TRADE), plafonnées au total
- max 1 trade actif à la fois (un seul sens, une seule position
  nette ouverte ; les entrées additionnelles renforcent ce même
  trade, ce n'est pas un second trade indépendant)
- stop-loss obligatoire attaché à chaque entrée ; ordre refusé sans SL
- kill switch : arrêt définitif si perte cumulée > 20 % du capital
  de référence (100 EUR) ou si n_trades atteint la cible
- aucun accès au compte réel, jamais

## AMENDEMENT v4 (2026-09-14, décision du propriétaire après le kill
## switch v3.1 — choix explicite : « Test 0,01 lot, plusieurs semaines »)

Pour le test v4 de la Méthode V uniquement, par dérogation aux
sections SIZING PAR ENTRÉE et ENTRÉES MULTIPLES :
- taille FIXE 0.01 lot, une seule entrée par trade, aucun renfort ;
- capital simulé de campagne remis à 100 EUR (l'historique 100 →
  15,27 EUR est archivé dans data/conclusion.md) ;
- sorties anticipées limitées à l'événement macro imminent et à la
  pause/week-end ; la sortie sur garde S/R est SUSPENDUE — mesure
  mécanique pure SL 10 / TP 7, comparable au backtest de référence
  (post-mortem v3.1 : mécanique +26,00 EUR vs gardes −93,88 sur les
  2 trades, n trop faible pour conclure, d'où la mesure propre) ;
- l'analyse contextuelle reste calculée et LOGGUÉE (facteurs par
  entrée compris) pour la vérification a posteriori, sans influer
  sur la taille ni sur les sorties ;
- objectif : trancher l'edge à n ≥ 30 avant tout retour aux tailles
  0.02 – 0.05.

### Gestion de sortie anticipée (Phase 7 uniquement)

Le bot n'est plus obligé de laisser une position courir jusqu'au TP ou au SL fixés à l'entrée. Le stop-loss reste OBLIGATOIRE et attaché à l'ordre dès l'envoi (règle inchangée ci-dessus) — c'est un filet de sécurité, pas la seule sortie possible.

Le bot peut clôturer une position manuellement, avant que le SL ou le TP ne soit touché, si l'un des cas suivants est détecté sur bougie clôturée (jamais sur la bougie en formation, pas de lookahead) :

- Retournement de marché contre la position : la bougie clôturée franchit un niveau de support/résistance clé dans le sens contraire à la position, ou un niveau de retracement Fibonacci important est cassé dans le sens contraire.
- Un événement macro à fort impact (Fed/FOMC en particulier, ou tout autre rapport fort impact) devient imminent ou vient d'être publié et rend le maintien de la position trop risqué.
- Le prix approche du SL et le contexte (S/R, Fibonacci, macro) indique qu'un retournement est probable — sortie anticipée plutôt que d'attendre le SL exact.
- Le prix approche du TP mais le contexte indique un retournement possible ou un risque accru — le bot peut sécuriser le gain avant le TP plutôt que d'attendre.

Chaque sortie anticipée doit être logguée avec : la raison exacte (S/R, Fibonacci, macro, ou combinaison), les niveaux/données ayant motivé la décision, le prix de sortie, et le P&L résultant — pour permettre une comparaison a posteriori entre sortie anticipée et sortie mécanique (SL/TP fixes).

Cette gestion de sortie reste strictement encadrée par les règles absolues et les contraintes Phase 7 déjà en vigueur : login/trade_mode vérifiés avant chaque ordre (y compris une clôture), taille de chaque entrée dans la plage 0.02 – 0.05 lot, max 1 trade actif à la fois (entrées multiples autorisées dans le même sens, plafonnées au total), kill switch inchangé, aucun accès au compte réel, jamais.