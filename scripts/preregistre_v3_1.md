# PRÉ-ENREGISTREMENT PHASE 7 v3.1 — MÉTHODE V ÉTENDUE
# FIGÉ le 2026-09-11, ~19h30 serveur, AVANT tout ordre v3.1.
# Remplace preregistre_v3.md (v3.0 arrêtée avec 0 trade : supersession
# propre, aucune contamination). Source : CLAUDE.md adapté par le
# propriétaire le 2026-09-11 — sizing par confiance, entrées multiples,
# analyse contextuelle, sortie anticipée.

## Entrée (inchangé)

Signal mécanique EMA9/EMA21 M5 + filtre volume (≥ moyenne 20 ET
≥ 200), à la clôture de barre uniquement, permanence des invalidations.
Entrée bloquée si : position ouverte en sens opposé, pause
22:45→01:00, spread > 2,00 $, événement macro fort impact ≤ 15 min.

## Sizing par confiance (CLAUDE.md) — constantes d'opérationnalisation

Facteurs comptés à l'entrée :
  f1 signal mécanique valide (nécessaire) ;
  f2 volume ≥ 1,5 × moyenne 20 barres ;
  f3 S/R : fractale causale K=2 (confirmée 2 barres closes plus tard)
     dans le sens du signal à ≤ 5,00 $ du prix (support sous un BUY,
     résistance sur un SELL) ;
  f4 Fibonacci : dernière jambe entre les 2 dernières fractales
     confirmées ; niveaux 23,6/38,2/50/61,8/78,6 % ; confirme si la
     jambe est dans le sens du signal et le prix à ≤ 1,50 $ d'un
     niveau ;
  f5 aucun événement fort impact à ≤ 60 min (data/calendrier_macro.csv,
     heures UTC, décalage serveur +3 h de mesure_phase2.json).
Taille : 1 facteur → 0,02 | 2 → 0,03 | 3 → 0,04 | ≥ 4 → 0,05 lot
(arrondi au volume_step). Facteurs et taille loggés par entrée.

## Entrées multiples (CLAUDE.md)

Renforcement possible à chaque barre close si : direction EMA toujours
alignée (dLast du même signe), ET un niveau confirmant NOUVEAU (S/R ou
Fibonacci, identité = prix arrondi à 0,1 $, absent de la liste déjà
utilisée par ce trade), volume cumulé ≤ 0,15 lot. Taille du renfort =
grille de confiance recomptée à cet instant. SL/TP du trade (ceux de
la première entrée) conservés sur la position agrégée (compte
netting). Un signal opposé pendant une position = loggé, jamais tradé.

## Sortie anticipée (CLAUDE.md) — règles opérationnalisées, sur barre close

- GARDE : niveau confirmant retenu à l'entrée (S/R ou fib le plus
  proche sous un long / sur un short). Clôture de barre au-delà de la
  garde de ≥ 0,50 $ contre la position → sortie « retournement S/R-fib ».
- MACRO : événement fort impact ≤ 15 min → sortie « macro imminente ».
- SÉCURISATION : distance au TP ≤ 1,50 $ ET événement ≤ 60 min →
  sortie « sécurisation avant macro ».
Chaque sortie anticipée loggée avec motif, niveaux, prix, P&L.
Le SL attaché reste le filet de sécurité permanent.

## Témoin

Apparié sur la PREMIÈRE entrée de chaque trade uniquement : mêmes
quotes, direction aléatoire (graine 20260911), même taille que la
première entrée, mêmes SL/TP, aucun renfort, aucun ordre réel. Il
mesure la valeur directionnelle du signal d'entrée ; les
renforts/sorties anticipées du réel s'évaluent par différence.

## Arrêts et critère (CLAUDE.md, inchangés)

Perte cumulée v3.1 > 20 EUR (NB consigné : à 0,03 lot, UN SEUL stop
= −25,8 EUR → arrêt au premier SL ; à 0,02, au deuxième — c'est la
conséquence arithmétique de la grille du propriétaire) ; 8 pertes
consécutives ; cible n = 30 trades. SUCCÈS = espérance > 0 ET t > 2
ET témoin battu de > 2 σ sur les trades réalisés jusqu'à l'arrêt.

## Supervision (demande du propriétaire)

Rapports toutes les 20 min ; EN POSITION : télémétrie toutes les
120 s (flottant, prix, distances SL/TP/garde, facteurs) + alertes
immédiates (SL à ≤ 2 $, TP à ≤ 1,5 $, renfort, sortie anticipée).
