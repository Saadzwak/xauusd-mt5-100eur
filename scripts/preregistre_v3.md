# PRÉ-ENREGISTREMENT PHASE 7 v3 — MÉTHODE V — FIGÉ le 2026-09-11,
# 19h00 serveur, AVANT tout ordre. Non modifiable ensuite.

Spec fournie par le propriétaire (« Méthode V — EMA9/EMA21 M5 avec
filtre de volume »), hypothèse n° 51 du compteur cumulatif. Backtest
préalable exécuté (data/methode_v_backtest.txt) : p̂ 0,631, témoin
+2,0 σ, MAIS t 1,68 < 2,80 et quart-Kelly 0,003 lot → non exécutable.
Le forward-test mesure la spec en conditions réelles ; il ne la
valide pas d'avance.

## Règles (fidèles à la spec, aucune variante)

- Signal à la clôture de chaque barre M5, jamais sur la barre en
  formation : dPrev = EMA9[n-2]−EMA21[n-2], dLast = EMA9[n-1]−EMA21[n-1] ;
  BUY si dPrev ≤ 0 et dLast > 0 ; SELL si dPrev ≥ 0 et dLast < 0.
- Filtre volume : tick_volume(barre signal) ≥ moyenne des 20 barres
  closes précédentes ET ≥ 200. (Constat consigné : sur ce feed
  MetaQuotes-Demo, 100 % des barres dépassent 200 — le seuil absolu
  est inerte ici, seule la moyenne mobile filtre.)
- Permanence : chaque barre close n'est évaluée qu'une seule fois ;
  un croisement invalidé ne se re-signale jamais.
- Entrée au marché immédiatement après la clôture de la barre signal.
- SL fixe 10 $ ; TP fixe 7 $ — jamais modulés, aucun trailing.
- Journal des signaux (spec §8) : chaque croisement est loggé dans
  data/methode_v_signaux.csv (barre, dPrev, dLast, volume, moyenne 20,
  décision, motif d'invalidation).

## Décisions d'implémentation consignées

- VOLUME : 0,01 lot FIXE. La demande de 0,02–0,05 « selon la
  confiance » est refusée : (a) CLAUDE.md, exception phase 7, fige le
  volume à 0,01 non paramétrable ; (b) aucune variable de confiance
  n'existe dans la spec (signal binaire) — la moduler serait du sizing
  discrétionnaire ; (c) 0,02–0,05 = 3× à 8× le quart-Kelly mesuré au
  backtest. Modifiable uniquement par édition de CLAUDE.md par le
  propriétaire, pour une valeur FIXE.
- CAPITAL DE RÉFÉRENCE : 100 EUR (CLAUDE.md règle 7). Le souhait de
  200 € est consigné mais exige la même édition. Capital de campagne
  poursuivi : 100 + v1 (+14,20) + v2 (−5,05) = 109,15 EUR.
- TP à 7 $ exactement (la « plage 6-8 » de la spec est indicative).

## Témoin, arrêts, critère

- Témoin apparié par trade : mêmes instants/quotes, direction
  aléatoire (graine 20260911), mêmes SL/TP/coûts, aucun ordre.
- Arrêts automatiques : perte cumulée v3 > 20 EUR ; 8 pertes
  consécutives ; CIBLE n = 30 trades v3 atteinte (CLAUDE.md :
  « n_trades atteint la cible ») ; spread > 2,00 $ = pas d'entrée ;
  pause 22:45 → 01:00 (couvre la fermeture hebdomadaire du vendredi).
  Pas de fin de session horaire : le test court jusqu'à un arrêt.
- SUCCÈS (déclaré maintenant) : sur les 30 trades v3 : espérance > 0
  ET t > 2,0 ET écart au témoin apparié > 2 σ. Tout le reste = échec.
- Garde-fous inchangés : démo 111371411 vérifié avant CHAQUE ordre,
  SL attaché obligatoire, 1 position max, volume 0,01, magic 20260911.
