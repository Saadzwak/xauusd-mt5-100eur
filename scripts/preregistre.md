# PRÉ-ENREGISTREMENT PHASE 7 — FIGÉ le 2026-08-20 03:06 heure serveur

Ce document est écrit AVANT le premier ordre et n'est plus modifiable.
Toute divergence entre ce document et l'exécution est un défaut à
rapporter, pas à corriger en cours de nuit.

## 1. Stratégie (unique, aucune variante, aucun réglage)

F2 — renversement après élargissement du spread, telle que simulée en
phase 5 :
- signal : à la clôture de chaque minute, z du spread moyen minute
  ≥ 2.5, où z = (x − moyenne des 60 minutes précédentes) / écart-type
  de ces 60 minutes (minimum 30 minutes valides) ;
- direction : OPPOSÉE au signe du rendement (bid) de la minute du
  signal ; rendement nul → pas de signal ;
- entrée : ordre au marché immédiatement après la clôture de la minute
  (= open de la minute suivante), spread réel payé au moment de
  l'entrée ;
- stop : 1.0 × ATR14 M1 (Wilder, dernière barre M1 FERMÉE) attaché à
  l'ordre ; objectif : RR 2 (TP = 2 × stop), attaché à l'ordre ;
- filtre de cohérence hérité de la simulation phase 5 : pas d'entrée si
  stop < 3 × spread médian de l'heure courante (table phase 2) ;
- pas de restriction horaire cette nuit (le coût élevé fait partie du
  test) ; les autres gardes (pause quotidienne, spread > 2 $) restent.

## 2. Témoin en parallèle

À chaque ordre réel exécuté, une direction aléatoire est tirée
(générateur graine 20260820) et un trade VIRTUEL est suivi sur les
mêmes cotations live : même instant d'entrée, même distance de stop,
même RR, même convention de coût (entrée long au ask / sortie au bid,
et inversement). Le témoin ne passe jamais d'ordre. La comparaison
réel vs témoin (t apparié) décide, pas le P&L brut.

## 3. Volume

0.01 lot, EN DUR dans le code, non paramétrable, jamais modifié,
quelle que soit la confiance ou la série en cours.

## 4. Critère de succès (déclaré maintenant, aucune réinterprétation)

SUCCÈS si et seulement si, sur n ≥ 30 trades réels :
- espérance nette > 0 EUR/trade, ET
- t de Student de la série > 2.0, ET
- écart au témoin apparié > 2 σ.
Tout le reste — y compris n < 30 — est un ÉCHEC du test.

## 5. Arrêts automatiques (kill switch, le premier atteint)

- perte cumulée > 20 EUR sur le capital simulé de 100 EUR ;
- 8 pertes consécutives ;
- 08:00 heure serveur (position ouverte fermée au marché à cet
  instant, marquée « forcée ») ;
- spread instantané > 2,00 $ : aucune entrée tant qu'il n'est pas
  redescendu (les positions ouvertes gardent leur SL/TP) ;
- pause quotidienne : aucune entrée à partir de 22:45 serveur,
  fermeture forcée à 22:55, aucune entrée avant 01:00.

## 6. Métrique suivie (jamais une contrainte)

Objectif déclaré du propriétaire : 100 → 1000 EUR. Suivi à chaque
rapport : capital simulé courant (100 + Σ nets à 0.01 lot), écart au
trajet géométrique requis sur la session, et nombre de trades
nécessaires à l'espérance observée pour atteindre 1000 EUR
(« inatteignable » si espérance ≤ 0). Le volume ne change JAMAIS pour
s'en rapprocher.

## 7. Journalisation

- data/forward_journal.csv : une ligne par trade réel (horodatage,
  sens, prix demandé, prix obtenu, SLIPPAGE, spread à l'entrée,
  retcode, stop, résultat net EUR, témoin : sens/issue/net).
  Les entrées refusées (retcode ≠ DONE, spread > 2 $) sont journalisées
  à part dans le rapport.
- data/forward_live.txt : rapport toutes les 20 minutes (n, espérance,
  t, écart témoin, slippage médian, capital simulé, trajet).
- Le slippage mesuré (prix obtenu − prix demandé, signé défavorable
  positif) est un livrable en soi.

## 8. Garde-fous d'exécution

Compte démo 111371411 exclusivement ; vérification login + trade_mode
avant CHAQUE order_send (entrée comme fermeture) ; SL non nul attaché,
sinon l'ordre n'est pas envoyé ; 1 position maximum ; magic 20260820.
En cas de crash du script, les positions restent protégées par leur
SL/TP côté serveur ; au redémarrage, le registre est rechargé depuis
le journal (capital, série de pertes) — aucun critère n'est remis à
zéro.
