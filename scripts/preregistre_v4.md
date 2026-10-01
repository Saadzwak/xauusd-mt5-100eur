# PRÉ-ENREGISTREMENT PHASE 7 v4 — MÉTHODE V MÉCANIQUE PURE
# FIGÉ le 2026-09-14, 23h00 serveur (pause), AVANT tout ordre v4.
# Source : AMENDEMENT v4 de CLAUDE.md (décision explicite du
# propriétaire après le kill switch v3.1).

## Ce qui est mesuré

L'edge directionnel de la Méthode V (EMA9/EMA21 M5 + filtre volume,
SL 10 $ / TP 7 $) en conditions réelles, à n ≥ 30 trades, sans aucun
levier de sizing : c'est la réplique live du backtest de référence
(hypothèse n° 51 : p̂ 0,631, témoin +2,0 σ).

## Règles

- Signal, filtre volume (≥ moy20 ET ≥ 200), permanence : inchangés.
- Entrée au marché à la clôture de la barre signal ; UNE entrée par
  trade ; AUCUN renfort ; taille FIXE 0,01 lot.
- SL 10 $ / TP 7 $ attachés, sorties MÉCANIQUES uniquement, sauf :
  événement macro fort impact ≤ 15 min (clôture immédiate, loggée) et
  pause/week-end (22:45 blocage, 22:55 clôture). Pas de sortie sur
  garde S/R en v4. Pas de sécurisation avant TP.
- Analyse contextuelle (fractales K=2, Fibonacci, macro) calculée et
  loggée à chaque barre close + facteurs de confiance loggés à chaque
  entrée — à titre d'observation uniquement.
- Témoin apparié par trade (graine 20260914) : mêmes quotes, direction
  aléatoire, mêmes SL/TP, 0,01 lot.
- Capital simulé : NOUVELLE campagne à 100 EUR.
- Arrêts : perte cumulée v4 > 20 EUR (≈ 2 SL pleins + 1 partiel à
  0,01) ; 8 pertes consécutives ; CIBLE n = 30 (arrêt et verdict).
- SUCCÈS : sur les trades réalisés à l'arrêt, avec n ≥ 30 : espérance
  > 0 ET t > 2,0 ET écart au témoin > 2 σ. Tout le reste = échec.
- Garde-fous inchangés : démo 111371411 vérifié avant chaque ordre,
  SL obligatoire, 1 trade max, magic 20260914, hedging géré, kill
  checks après toute clôture.

## Référence attendue (du backtest, pour lecture au fil de l'eau)

p_be = 0,606 ; p̂ attendu ≈ 0,63 ; espérance attendue ≈ +0,6 EUR/trade
à 0,01 lot ; ~3-4 trades valides/jour → n = 30 en ~2 semaines.
FOMC mercredi 16/09 21:00 serveur : blocage/sortie macro automatiques.
