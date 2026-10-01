# PRÉ-ENREGISTREMENT PHASE 7 v2 — FIGÉ le 2026-08-25, 23h05 serveur
# (corrigé avant tout ordre : la version initiale datait par erreur la
# session au vendredi 21/08 ; nous sommes mardi 25/08 en pause 23h→01h)

Demande du propriétaire après la session v1 : accélérer la fréquence
des trades ; autorisation d'un stop jusqu'à 20 EUR. Ce document fige
l'implémentation AVANT le premier ordre v2. Non modifiable ensuite.

## Configuration v2 (hypothèse n° 44 du compteur cumulatif — config
unique, jamais testée en simulation : test purement prospectif)

Différences vs v1 (scripts/preregistre.md), tout le reste inchangé :
- seuil de signal : z ≥ 2.0 (au lieu de 2.5) — fréquence accélérée ;
- stop : min(2.0 × ATR14 M1, 20 EUR convertis via order_calc_profit)
  — le « SL de 20 euros » est un PLAFOND, pas une valeur fixe : un SL
  fixe de 20 EUR ferait tomber le kill switch CLAUDE.md (perte
  cumulée > 20 EUR) à la première perte, test dégénéré ;
- RR inchangé : TP = 2 × stop ;
- session : du lancement (mardi 25/08, pause 23h→01h en cours, aucune
  entrée avant mercredi 01:00) jusqu'à mercredi 08:00 heure serveur ;
  règle générale conservée dans le code : toute session un vendredi se
  termine à 22:55 (fermeture hebdomadaire) ;
- journal séparé : data/forward_journal_v2.csv (les statistiques v2 ne
  se mélangent JAMAIS aux 15 trades v1) ;
- capital simulé : poursuivi à 114,20 EUR (métrique 100→1000 du
  propriétaire, cumulative sur la campagne) ; les critères de succès
  et le kill switch se mesurent sur les trades v2 uniquement ;
- graine témoin : 20260821 ; magic : 20260821.

## Inchangé et non négociable

- volume 0.01 lot en dur (exception CLAUDE.md : jamais paramétrable) ;
- vérification login + trade_mode avant CHAQUE order_send ;
- SL attaché obligatoire, 1 position max, témoin apparié par trade ;
- kill switches : perte cumulée v2 > 20 EUR ; 8 pertes consécutives ;
  spread > 2,00 $ ; pause 22:45 → 01:00 ;
- filtre stop ≥ 3 × spread médian horaire ;
- SUCCÈS v2 : sur n ≥ 30 trades v2 : espérance > 0 ET t > 2.0 ET
  écart au témoin apparié > 2 σ. Tout le reste = échec, aucune
  réinterprétation.

## Avertissement méthodologique consigné d'avance

Élargir le stop à 2×ATR avec RR 2 augmente le taux de réussite
attendu mécaniquement (barrières plus lointaines) mais chaque perte
coûte ~2× plus cher ; et le témoin v1 a montré que cette structure
gagne TOUTE SEULE en régime volatil. La seule lecture valide reste
l'écart au témoin, pas le P&L.
