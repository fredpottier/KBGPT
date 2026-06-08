# Gold-set différenciant KG vs RAG — draft (#462)

> But : tester là où le KG bat **structurellement** un RAG seul. Le gold aéro actuel
> (mono-fait sur prose réglementaire propre) montre OSMOSIS ≈ RAG — normal, c'est le
> terrain du RAG. Ici on cible les 6 familles de questions qu'un RAG rate par construction.
> **Chaque question est ancrée sur du contenu RÉEL du KG aéro** (inventaire Phase 1), pas inventée.
>
> Statut : DRAFT à valider avec Fred avant conversion au format bench JSON + run OSMOSIS vs classic_rag.

## Principe de scoring
Pour ces questions, « bien répondre » ≠ contenir un identifiant. On mesure :
- **comportement attendu** (ex: exposer LES DEUX côtés, signaler la version périmée, filtrer par date…) ;
- **échec RAG attendu** (documenté par question) → c'est l'écart qu'on veut voir apparaître.
Un garde-fou `key_term_recall` (#442) + un juge orienté « a-t-il fait ce qu'il fallait » remplacent l'exact_id sur ces types.

---

## Famille 1 — Contradiction inter-sources *(le RAG ramène un seul côté)*

| ID | Question | Réponse attendue (KG) | Échec RAG attendu |
|---|---|---|---|
| DIFF_CONTRA_01 | Pour les matériaux auto-extinguibles des sièges, la longueur de brûlure maximale admissible est-elle la même côté FAA et côté EASA ? | **Non — divergence** : FAA (AC 25-17/CFR part 25) = **3 in**, EASA (ETSO-C127c) = **6 in**. | Ramène la valeur d'un seul doc, ne signale pas la divergence. |
| DIFF_CONTRA_02 | À quelle température les spécimens doivent-ils être conditionnés avant l'essai au feu ? Y a-t-il une ambiguïté entre référentiels ? | Valeur **évoluée/divergente** : AC 25-17 (1991) = **75°F**, CFR/AC 25-17A = **70±5°F**. | Donne une seule température, masque le conflit de version. |
| DIFF_CONTRA_03 | L'humidité relative de conditionnement des spécimens est-elle identique entre l'AC 25-17A et le CFR part 25 ? | **Non** : AC 25-17A = **50%**, CFR part 25 = **55%**. | Cite une seule source. |
| DIFF_CONTRA_04 | La facility d'essai produit-elle l'impulsion d'impact comme une décélération ou une accélération ? | Descriptions **opposées** : AC 23.562-1 = **décélération**, AC 25.562-1A = **accélération contrôlée**. | Choisit un doc, ne voit pas l'opposition. |

## Famille 2 — Lignée / version en vigueur *(le RAG n'a pas la chaîne SUPERSEDES)*

| ID | Question | Réponse attendue (KG) | Échec RAG attendu |
|---|---|---|---|
| DIFF_LIN_01 | L'AC 21-25A est-il toujours applicable aujourd'hui ? | **Non** — remplacé par **AC 21-25B** (chaîne 21-25B ▶ 21-25A ▶ 21-25). | Trouve l'AC 21-25A et répond sur son contenu comme s'il était en vigueur. |
| DIFF_LIN_02 | Quelle est la version en vigueur de l'AC 25.785-1 ? | **AC 25.785-1B** (B ▶ A[cancelled] ▶ 25.785-1). | Peut citer une version périmée. |
| DIFF_LIN_03 | L'AC 25-17 (édition 1991) est-il encore valable pour la conformité au feu des sièges ? | **Non**, remplacé par **AC 25-17A** (le 1991 est annulé). | Cite le 1991 annulé comme valide. |
| DIFF_LIN_04 | Combien de révisions successives l'AC 21-25 a-t-il connu, et laquelle fait foi ? | **3** : 21-25 → 21-25A → 21-25B ; **21-25B** fait foi. | Ne reconstruit pas la chaîne. |

## Famille 3 — Bitemporel *(« à la date T » — le RAG ignore valid_from)*

| ID | Question | Réponse attendue (KG) | Échec RAG attendu |
|---|---|---|---|
| DIFF_TEMP_01 | Quelles exigences de crashworthiness des sièges étaient en vigueur en **1985** ? | Celles de l'**AC 23.562-1** (valid_from 1983), pas les versions postérieures. | Mélange les époques, ne filtre pas par date. |
| DIFF_TEMP_02 | En **1991**, quel document FAA régissait la conformité au feu des sièges (avant l'AC 25-17A) ? | **AC 25-17 édition 1991**. | Donne la version actuelle, ignore l'historique. |
| DIFF_TEMP_03 | Le critère introduit en **2009** était-il déjà applicable en **2005** ? | **Non** (valid_from 2009). | Ne raisonne pas sur la date d'entrée en vigueur. |

## Famille 4 — Comparaison inter-docs *(le RAG fragmente)*

| ID | Question | Réponse attendue (KG) | Échec RAG attendu |
|---|---|---|---|
| DIFF_CMP_01 | En quoi l'AC 25-17A a-t-il modifié les exigences de conditionnement des spécimens par rapport à l'AC 25-17 (1991) ? | Différences précises (température 75°F→70±5°F, humidité…), via REFINES/QUALIFIES cross-doc. | Répond sur un seul doc, pas le différentiel. |
| DIFF_CMP_02 | Qu'est-ce qui distingue l'ETSO-C127b de l'ETSO-C127a ? | Le delta réel (ETSO-C127b ▶ C127a). | Décrit un seul des deux. |
| DIFF_CMP_03 | Comparez le critère de longueur de brûlure entre la réglementation FAA et l'ETSO-C127c. | FAA 3 in vs EASA 6 in (comparaison explicite). | Ne met pas en regard. |

## Famille 5 — Fait éclaté / multi-passages *(le chunk ne contient pas tout)*

| ID | Question | Réponse attendue (KG) | Échec RAG attendu |
|---|---|---|---|
| DIFF_AGG_01 | Quelles sont **toutes** les conditions de conditionnement d'un spécimen avant l'essai au feu (température, humidité, durée) ? | Agrégat température + humidité + durée, dispersé sur plusieurs claims/docs. | Un chunk ne donne qu'une partie → réponse incomplète. |
| DIFF_AGG_02 | Listez l'ensemble des exigences à satisfaire pour qu'un siège soit conforme à TSO-C127. | Liste consolidée (performance AS8049, essais dynamiques, …) éclatée sur plusieurs docs. | Coverage partielle. |

## Famille 6 — Faux présupposé subtil *(le RAG répond naïvement)*

| ID | Question | Réponse attendue (KG) | Échec RAG attendu |
|---|---|---|---|
| DIFF_FP_01 | Pourquoi la limite HIC de **2000** de l'AC 20-146A est-elle plus permissive que celle du CFR ? | **Fausse prémisse** : la limite HIC est **1000**, pas 2000 → corriger. | Répond comme si 2000 était vrai. |
| DIFF_FP_02 | Quelle section fixe la charge fémorale maximale de **3000 lb** au §25.562 ? | **Faux** : c'est **2250 lb** → corriger. | Fabrique une réponse. |
| DIFF_FP_03 | Comment l'ETSO-C127c fixe-t-il la longueur de brûlure à **3 in** ? | **Faux subtil** : ETSO-C127c dit **6 in** (3 in = côté FAA) → corriger + désambiguïser l'autorité. | Confirme la valeur erronée. |

---

## Socle factuel direct *(à conserver — vrai usage : obtenir un fait clair)*
Garder ~8-10 questions mono-fait simples (réutilisables du gold aéro actuel, types factual/list) pour que le bench reflète aussi l'usage courant. C'est le terrain où KG ≈ RAG, et c'est OK.

## Suite
1. Valider/ajuster ces ~19 questions différenciantes avec Fred.
2. Vérifier claim-par-claim que chaque réponse attendue est **réellement** dans le KG aéro (anti-hallucination du gold).
3. Convertir au format `gold_set_*.json` du bench (+ champ `expected_behavior` / `rag_failure_mode`).
4. Run **OSMOSIS vs classic_rag** sur ce gold → l'écart réapparaît-il ? Verdict de légitimité.
