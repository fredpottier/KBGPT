# Préparation Démo OSMOSIS V0.1 — Must/Should/Nice to have

*Document autoporteur, rédigé avril 2026. Objectif : lister honnêtement tout ce qui doit être fait avant de solliciter un corpus externe non maîtrisé (typiquement chez un ancien employeur) pour valider les fondamentaux d'OSMOSIS. La date de la démo n'est pas fixée (fenêtre 10 jours à 2 mois). Ce document doit permettre, le jour où la date se précise, de savoir exactement ce qui reste à faire et dans quel ordre.*

---

## Contexte et objectif de la démo

### Ce qu'on veut prouver

**Hypothèse à valider** : les choix architecturaux d'OSMOSIS (claim-first, relations typées, response modes, tension detection, provenance verbatim) tiennent sur un corpus d'entreprise **non sélectionné par l'équipe de développement**, c'est-à-dire sans biais inconscient dans le choix des documents.

**Corpus cible** : 100+ documents réels d'entreprise fournis par un interlocuteur qualifié (ancien employeur, contact de confiance) qui peut évaluer qualitativement les réponses.

**Ce que la démo prouvera en cas de succès** :
- Les fondamentaux architecturaux généralisent au-delà du corpus SAP actuel
- Les USPs uniques (tension, cross-version, provenance verbatim) sont utiles en condition réelle
- Le système répond de façon cohérente à un évaluateur non biaisé
- OSMOSIS est prêt pour une V0.1 — un produit qui tient son pitch

**Ce que la démo NE prouvera PAS** — à cadrer explicitement avec l'interlocuteur :
- La scalabilité à 10k/100k documents (validation de principe uniquement)
- La robustesse production multi-tenant concurrent
- La stabilité long terme avec ingestions répétées
- La qualité sur des types de questions hors du périmètre du test

### Contexte de ressources

OSMOSIS est développé avec des moyens limités : pas d'open bar tokens, pas d'EC2 illimité, petite équipe. Les choix de priorité doivent tenir compte de ce contexte — on cherche le meilleur ROI par jour de travail investi, pas la perfection.

---

## MUST HAVE — non négociable avant la démo

*Ces items ne sont pas des préférences. Chacun porte un risque d'échec visible et direct du démo s'il n'est pas fait. Ne pas lancer la démo tant que cette section n'est pas complète.*

### M1. Fixer la dette ComparableSubject

**Problème** : actuellement le KG ne contient qu'un seul `ComparableSubject` (`SAP S/4HANA Cloud Private Edition`) qui agglomère tous les produits du corpus. Le `SubjectResolverV2` n'utilise pas le `product_gazetteer` du domain pack (528 produits SAP avec hiérarchie correcte) qui existe déjà.

**Pourquoi c'est bloquant pour la démo** : sur le corpus SAP actuel, tout est "autour de S/4HANA" donc le bug est masqué. Sur un corpus externe avec 3-5 produits différents, cette dette va **exploser visiblement** : tous les documents vont atterrir sur un seul Subject canonique, la détection cross-version sera cassée, la couche Perspective perdra son ancrage produit, et l'interlocuteur verra un système qui confond ses produits.

**Ce qu'il faut faire** :
1. Brancher `product_gazetteer` + `canonical_aliases` + `common_acronyms` du domain pack sur le `SubjectResolverV2`
2. Prioriser le match avec le **canonical le plus court** dans la hiérarchie quand plusieurs candidats matchent (ex: "S/4HANA" gagne sur "S/4HANA Cloud Private Edition" pour un Security Guide générique)
3. Promouvoir les variantes de déploiement (Cloud/Public/Private/On-Premise) en **qualifiers** du `DocumentContext`, pas en Subjects séparés
4. Baisser le seuil de création de Subject pour ne plus écarter les produits à 1 doc

**Effort estimé** : 1-2 jours.
**Référence** : `doc/ongoing/[futur]_DETTE_COMPARABLE_SUBJECT.md`.
**Validation** : après fix, re-ingérer le corpus SAP actuel et vérifier qu'on a plusieurs `ComparableSubject` distincts (S/4HANA, Ariba, SAP ILM, etc.) avec la hiérarchie correcte.

---

### M2. Intégrer `build_perspectives` au pipeline post-import

**Problème** : la couche Perspective V2 (HDBSCAN sur embeddings) est un clustering **global**. Ajouter des documents sans relancer le build rend les Perspectives stales : nouveaux claims invisibles, centroids périmés, frontières obsolètes. Le pipeline post-import existant (`canonicalize`, `facets`, `cluster_cross_doc`, `chains_cross_doc`, `detect_contradictions`, `claim_embeddings`, `claim_chunk_bridge`, `archive_isolated`) ne relance pas Perspective — c'est un job séparé (`app/scripts/build_perspectives.py`) qui doit être déclenché manuellement.

**Pourquoi c'est bloquant pour la démo** : on va ingérer 100+ documents en une passe, puis faire l'évaluation. Si le rebuild Perspective est oublié, le mode PERSPECTIVE répondra sur des clusters vides ou incomplets, et les questions ouvertes/thématiques (la démo inclut presque certainement ce type de question) seront dégradées sans signal d'alerte.

**Ce qu'il faut faire** :
1. Créer `rebuild_perspectives_incremental()` dans `src/knowbase/perspectives/orchestrator.py` qui wrappe la logique du CLI existant
2. L'ajouter à la séquence du post-import juste après `claim_chunk_bridge` et avant `archive_isolated`
3. Mettre à jour `cockpit/pipeline_defs.yaml` pour inclure la nouvelle étape dans la vue cockpit
4. Skip conditionnel si `new_claims_since_last_build < 100` (configurable) pour éviter le coût inutile à chaque petit ajout

**Effort estimé** : 4-8 heures.
**Référence** : `doc/ongoing/[futur]_DETTE_INCREMENTAL_REBUILD.md`.
**Validation** : lancer une ingestion test, vérifier dans les logs que la nouvelle étape du post-import tourne et que les Perspectives sont à jour.

---

### M3. Externaliser les stopwords critiques (multilingue)

**Problème** : trois listes de mots massives sont hardcodées dans le code en français + anglais uniquement :

| Liste | Fichier | Items | Usage |
|---|---|---:|---|
| `ENTITY_STOPLIST` | `claimfirst/models/entity.py:241` | 326 | Filtrage des entités "génériques" à l'extraction |
| `_STOPWORDS` | `api/services/kg_signal_detector.py:248` | 267 | Tokenisation pour signal gap detection |
| `_BM25_STOPWORDS` | `api/services/retriever.py:161` | 176 | Filtrage BM25 hybrid search |

**Pourquoi c'est bloquant pour la démo** : si l'interlocuteur fournit un corpus **en italien, allemand, néerlandais, ou espagnol**, ces listes deviennent **hors sujet**. Deux impacts concrets et dangereux :

1. **L'`ENTITY_STOPLIST` laisse passer** des mots génériques italiens comme entités ("che", "questo", "uno", "delle") → pollution du graphe, entités inutiles en masse
2. **Les stopwords BM25 ne filtrent pas** les mots-outils italiens → retrieval dégradé, scores TF-IDF biaisés
3. **Le signal gap detector** compte des mots-outils italiens comme "termes signifiants" → détection de gaps corrompue

Le pire est que **ça ne génère pas d'erreur**. Le système tournera, produira des résultats qui semblent OK au premier coup d'œil, et se dégradera silencieusement sur les questions qui dépendent de ces filtres. On pourrait chercher longtemps avant de comprendre que c'est les listes qui font tout péter. C'est **le type de risque qui tue une démo**.

**Ce qu'il faut faire** :
1. Créer `config/stopwords/` avec :
   - `config/stopwords/en.txt`
   - `config/stopwords/fr.txt`
   - `config/stopwords/it.txt`, `de.txt`, `es.txt`, `nl.txt` (pour couvrir les langues européennes probables)
   - `config/stopwords/entity_stoplist.{en,fr}.txt` (si on garde la logique spécifique entités)
2. Créer un loader `src/knowbase/common/stopwords.py` qui charge les fichiers par langue au démarrage et offre une API `get_stopwords(lang_codes: list[str]) -> set[str]`
3. Modifier les 3 fichiers critiques pour charger via le loader au lieu de la constante hardcodée
4. **Détection de langue** : à la volée sur un échantillon du document au moment de l'ingestion, pour décider quelles listes activer. OSMOSIS a déjà `langdetect` ou équivalent dans le pipeline — vérifier l'usage existant
5. **Fallback par défaut** : si la langue n'est pas détectée ou pas supportée, charger `en.txt + fr.txt` par sécurité (comportement actuel)

**Listes suggérées** : pour chaque langue cible, récupérer les stopwords standards depuis `nltk` ou `spacy` (~150-300 mots par langue, couvre 95% du besoin). Ne pas réinventer.

**Effort estimé** : 4-8 heures (le plus long est la validation que rien ne se casse sur le corpus SAP actuel après refactoring).

**Référence** : `doc/ongoing/AUDIT_HARDCODED_WORD_LISTS.md` (sections CRITIQUE).

**Validation** : lancer une ingestion test sur 2-3 documents italiens ou allemands (PDF open-source facilement trouvables), vérifier qu'aucune pollution d'entités génériques n'apparaît dans le graphe.

---

### M4. Dry-run sur un petit corpus externe de test

**Problème** : le pipeline d'ingestion a été rodé sur des documents relativement propres (PDF natifs générés par SAP). Un corpus externe peut contenir : PDF scannés avec OCR imparfait, PPTX mal structurés, Word exportés en chaos, documents avec métadonnées corrompues. **On ne peut pas découvrir ces problèmes le jour de la démo sur le corpus de l'interlocuteur**.

**Pourquoi c'est bloquant** : la découverte d'un problème de pipeline la veille ou pendant la démo est un scénario d'échec classique. On grille son crédit auprès de l'interlocuteur avec un "ah attends, il y a un bug avec les PPT...". Le dry-run existe pour **déplacer ce risque avant la démo**.

**Ce qu'il faut faire** :
1. Choisir un corpus de test externe **qu'on ne connaît pas** — idéalement dans un domaine différent de SAP (biomedical, legal, financial). 10-20 documents suffisent.
2. Sources possibles : publications open-access, documents gouvernementaux publics, corpus académiques (arXiv, ACL Anthology, etc.), rapports annuels d'entreprises cotées.
3. Ingérer **tout le corpus** via le pipeline complet (y compris le post-import nouvellement complété).
4. Vérifier manuellement :
   - Aucune erreur silencieuse dans les logs d'ingestion
   - Les `ComparableSubject` ont été créés de façon cohérente (si plusieurs produits/thèmes dans le corpus)
   - Les Perspectives V2 sont labellisées de façon cohérente
   - Les citations pointent vers les bons documents et pages
   - Le mode PERSPECTIVE produit une réponse structurée sur une question ouverte
   - Le mode TENSION se déclenche correctement s'il y a des contradictions
5. **Réparer tout ce qui se casse.** C'est pour ça que le dry-run existe. Chaque problème trouvé ici est un problème évité pendant la démo.

**Effort estimé** : 1-2 jours (préparation + ingestion + analyse + fixes éventuels).
**Dépendance** : M1, M2, M3 doivent être faits avant.

**Critère de succès** : un cycle complet d'ingestion + requête fonctionne sans intervention manuelle, avec des réponses cohérentes sur au moins 5 questions de types différents (factuelle, ouverte, cross-version, avec contradiction si possible).

---

### M5. Stabiliser les benchmarks actuels (RAGAS, T2/T5, Robustness)

**Problème** : les benchmarks sont en cours de finalisation après les fixes `job_timeout` + `TokenManager`. Tant qu'on n'a pas de scores baseline fiables sur le corpus SAP **post couche Perspective V2 + B6/B7**, on ne peut pas comparer avec les résultats du corpus externe.

**Pourquoi c'est bloquant** : sans baseline, impossible de dire "OSMOSIS tient sur le nouveau corpus **au moins aussi bien que sur le SAP**". La démo doit pouvoir produire un argumentaire chiffré : *"voici les scores sur le corpus SAP, voici les scores sur votre corpus, voici la comparaison"*.

**Ce qu'il faut faire** :
1. Laisser tourner les benchmarks en cours jusqu'à complétion (RAGAS, T2/T5, Robustness) — le fix est en place, ça devrait aller jusqu'au bout
2. Vérifier que les scores sont cohérents avec les attentes (pas de régression visible vs les runs pré-Perspective Layer)
3. **Archiver les résultats** sous un tag clair : `baseline_SAP_post_perspective_v2_20260407` par exemple
4. Documenter les scores de référence dans un doc dédié (ou dans `PREP_DEMO_V0.1.md` lui-même)

**Effort estimé** : 1 jour (attente + analyse, pas de code).

**Critère de succès** : trois rapports JSON complets dans `benchmark/results/` avec scores interprétables et aucun échec silencieux.

---

### M6. Runbook opérationnel "recevoir et ingérer un corpus externe"

**Problème** : si la démo se fait à distance (envoi de documents par l'interlocuteur puis retour des résultats), il faut un processus clair et reproductible. Si elle se fait en présentiel, il faut pouvoir ingérer le corpus en temps raisonnable sans improviser. Dans les deux cas, **un runbook écrit évite la panique de dernière minute**.

**Ce qu'il faut faire** : un document court (`doc/runbooks/INGESTION_CORPUS_EXTERNE.md`) qui couvre :

1. **Réception des documents** : format attendu, méthode de transfert sécurisée (pas d'upload sur services publics pour un corpus d'entreprise), tri des fichiers (extensions supportées, taille max, nombre max).
2. **Préparation** : vérifier l'état d'OSMOSIS (services UP, Redis clean, burst EC2 prête si nécessaire), purger les caches obsolètes, vérifier l'espace disque et Qdrant/Neo4j.
3. **Ingestion** : commande exacte à lancer, temps attendu selon le nombre de documents, comment surveiller la progression (cockpit), que faire en cas d'erreur.
4. **Post-import** : vérifier que toutes les étapes ont tourné (y compris le nouveau `build_perspectives`), quels signaux regarder pour valider le succès.
5. **Tests de sanity check** : une liste de 3-5 questions types à poser tout de suite après l'ingestion pour vérifier que le système répond cohéremment avant toute évaluation sérieuse.
6. **Rollback** : comment revenir à l'état avant ingestion si le corpus a cassé quelque chose (snapshot Neo4j + Qdrant + Redis).

**Effort estimé** : 2-4 heures.

**Validation** : le dry-run M4 est l'occasion de valider que le runbook est suivable.

---

### Récapitulatif MUST HAVE

| Item | Effort | Dépendance |
|---|---|---|
| M1. Fix ComparableSubject | 1-2 j | — |
| M2. `build_perspectives` dans post-import | 4-8 h | — |
| M3. Externalisation stopwords multilingues | 4-8 h | — |
| M4. Dry-run corpus externe de test | 1-2 j | M1, M2, M3 |
| M5. Stabiliser benchmarks baseline | 1 j (attente) | — |
| M6. Runbook ingestion externe | 2-4 h | — |
| **Total estimé** | **4-6 jours** de travail focalisé | |

**Ordre recommandé** : M1 et M2 en parallèle (indépendants), puis M3 (indépendant aussi mais à valider après M1+M2), puis M5 en laissant tourner pendant M6, puis M4 en dernier (validation finale).

---

## SHOULD HAVE — fortement souhaitable mais pas bloquant

*Ces items améliorent la qualité et réduisent les risques, mais leur absence ne tue pas la démo. À faire dans l'ordre si le temps le permet.*

### S1. Externaliser les listes de détection linguistique des benchmarks

**Problème** : les évaluateurs de benchmark utilisent des listes de mots-clés hardcodées en FR+EN pour détecter les phénomènes linguistiques dans les réponses :

- `TENSION_KEYWORDS` (divergence, contradict, however, cependant...) — évaluation T2
- `IGNORANCE_KEYWORDS` (aucune information, I don't know...) — évaluation robustesse
- `CORRECTION_KEYWORDS` (actually, en fait, au contraire...) — correction de prémisse
- `TEMPORAL_KEYWORDS` (version, release, 2023...) — évolution temporelle
- `negation_patterns`, `contradiction_markers`, `idk_phrases`...

**Pourquoi c'est should et pas must** : si le corpus externe est en français ou en anglais, ces listes continuent à fonctionner. Le risque n'existe que si on veut évaluer un corpus dans une autre langue — et même dans ce cas, le système OSMOSIS lui-même répond correctement, c'est seulement l'**évaluation automatique des réponses** qui est dégradée. Un évaluateur humain pallie le problème.

**Ce qu'il faut faire** : créer `config/detection_keywords.yaml` multilingue et y migrer les listes. Effort estimé : 1 jour.

**Référence** : `doc/ongoing/AUDIT_HARDCODED_WORD_LISTS.md` section HAUTE.

---

### S2. Consolidation des doublons `CANONICAL_PREDICATES`

**Problème** : la constante `CANONICAL_PREDICATES` est définie **trois fois** dans le code (`claim_extractor.py`, `slot_enricher.py`, `chain_detector.py`). Si on modifie une occurrence, les deux autres divergent silencieusement.

**Pourquoi c'est should** : ce n'est pas un risque de démo, c'est un risque de **maintenance**. Mais il est trivial à fixer et c'est l'occasion de le faire.

**Ce qu'il faut faire** : créer `src/knowbase/claimfirst/constants.py`, y mettre la constante canonique, importer depuis les 3 fichiers. Effort estimé : 1-2 heures.

---

### S3. Instrumentation staleness Perspective V2

**Problème** : même après avoir intégré `build_perspectives` au post-import (M2), on n'a pas de **signal visible** de la fraîcheur de la couche Perspective. Si le rebuild est skipé par erreur ou échoue silencieusement, on ne le voit pas.

**Pourquoi c'est should** : dans le contexte de la démo en une passe, l'intégration M2 suffit. Mais si la démo s'étale sur plusieurs ingestions (ex: l'interlocuteur envoie des docs au fil de l'eau), la visibilité de la staleness devient précieuse.

**Ce qu'il faut faire** :
1. Ajouter une query Cypher dans le knowledge collector du cockpit :
   ```cypher
   MATCH (p:Perspective) WITH max(p.updated_at) AS last_build
   MATCH (c:Claim) WHERE c.created_at > last_build RETURN count(c)
   ```
2. Exposer une nouvelle tuile cockpit "Perspective staleness: N new claims since last build"
3. Code coloration : vert si < 50, jaune 50-200, rouge > 200

**Effort estimé** : 2-3 heures. Référence : `[futur]_DETTE_INCREMENTAL_REBUILD.md` section 6 étape 1.

---

### S4. Documentation de cadrage pour l'interlocuteur

**Problème** : la démo sera d'autant plus crédible qu'elle est cadrée clairement dès le départ. Un interlocuteur qui découvre les limitations pendant la démo est un interlocuteur déçu ; un interlocuteur qui les connaît à l'avance est un interlocuteur qui juge le système sur ce qu'il promet, pas sur ce qu'il ne prétend pas être.

**Ce qu'il faut faire** : un document court (2-3 pages) à partager en amont qui explique :

1. **Ce qu'OSMOSIS fait bien** : extraction claim-first, détection de contradictions cross-version, citations verbatim traçables, réponses structurées par axes thématiques
2. **Ce qu'OSMOSIS ne fait pas encore** : scalabilité prouvée au-delà de quelques centaines de docs, multi-utilisateurs concurrents, certains formats exotiques
3. **Comment l'évaluation sera structurée** : types de questions attendues, méthode de notation, temps de réponse, livrables
4. **Ce qu'on demande à l'interlocuteur** : format du corpus, confidentialité, période de disponibilité pour le feedback

**Effort estimé** : 2-3 heures.

**Critère de succès** : l'interlocuteur peut dire *"ok, c'est clair, on y va"* sans attendre d'autre info.

---

### S5b. ~~Adoucir les règles de style des prompts de synthèse~~ **[RÉVISÉ 08/04 soir]** Le keyword evaluator Robustness était silencieusement cassé depuis 5 jours — c'est la vraie cause racine des "régressions"

**Investigation complète réalisée le 08/04, résultat contre-intuitif** : les "régressions" Robustness causal_why/conditional/temporal_evolution n'étaient **pas de vraies régressions**. Elles étaient un artefact d'un **LLM-juge cassé silencieusement** depuis au moins 5 jours.

**Timeline du bug** :

1. Dans `robustness_diagnostic.py`, le code du juge utilisait ce fallback :
   ```python
   judge_model = os.getenv("OSMOSIS_JUDGE_MODEL",
                            os.getenv("OSMOSIS_SYNTHESIS_MODEL", "gpt-4o-mini"))
   ```
2. À un moment entre le 02/04 (run V17) et le 07/04 (run POST_PerspectiveLayer), quelqu'un a défini `OSMOSIS_SYNTHESIS_MODEL=claude-haiku-4-5-20251001` dans l'environnement worker (variable pour la synthèse OSMOSIS).
3. `OSMOSIS_JUDGE_MODEL` n'étant pas défini, le fallback a résolu à `claude-haiku-4-5-20251001`.
4. Le code essayait alors d'appeler un modèle **Anthropic via le client OpenAI** → `400 Model not found` à chaque appel.
5. L'exception était catchée silencieusement avec un `logger.debug` (niveau invisible en prod), et le code retombait sur un **keyword evaluator** hardcodé (`CATEGORY_KEYWORD_EVALUATORS`).
6. Depuis cette date, **tous les runs POST_PL, B8, B9, JUDGE_FIX ont utilisé le keyword evaluator à 100%** pour les catégories LLM (`causal_why`, `conditional`, `temporal_evolution`, etc.), sans que le métrique `judge_mode: "llm"` du rapport le révèle.

**Preuve empirique** :

| Run | LLM-judge utilisé | Keyword fallback |
|---|---:|---:|
| V17 (02/04, baseline) | **221/246** ✓ | 25 |
| POST_PerspectiveLayer (07/04) | **0/246** ❌ | 246 |
| POST_PROMPT_B8 (08/04) | **0/246** ❌ | 246 |
| POST_PROMPT_B9 (08/04) | **0/246** ❌ | 246 |
| POST_JUDGE_FIX (08/04) | **0/246** ❌ | 246 |

**Conséquence** : toutes les "régressions" qu'on a combattues avec les fixes B7, B8, B9, prompts, pré-processing, etc. étaient orientées par un **faux signal**. Le keyword evaluator cherche des mots-clés fixes dans la réponse ; quand le style du LLM Haiku change (headers, formulation, paraphrase), les keywords matches baissent → score qui paraît régresser.

**Révélation après rescore offline avec un vrai LLM-juge (gpt-4o-mini)** :

| Catégorie | V17 (keyword cassé) | POST rescored (vrai LLM-juge) | Delta réel |
|---|---:|---:|---:|
| global_score | 0.6614 | **0.7067** | **+4.5 pts** ✓ |
| causal_why | 0.7583 | **0.8167** | **+5.8 pts** ✓ (pas de régression !) |
| conditional | 0.8042 | 0.7750 | -2.9 pts (bruit) |
| false_premise | 0.4800 | **0.8360** | **+35.6 pts** ✓ |
| negation | 0.7840 | 0.8160 | +3.2 pts |
| hypothetical | 0.7000 | 0.7478 | +4.8 pts |
| set_list | 0.6440 | 0.7240 | +8.0 pts |
| multi_hop | 0.6480 | 0.6160 | -3.2 pts (bruit) |
| synthesis_large | 0.6120 | 0.6380 | +2.6 pts |
| temporal_evolution | 0.6720 | **0.5040** | **-16.8 pts** — seule régression réelle |

**OSMOSIS s'est objectivement amélioré post-Perspective Layer.** Les "régressions" causal_why et conditional n'ont jamais existé.

**La seule vraie régression est `temporal_evolution` (-16.8 pts)**, et son analyse pointe clairement vers la **dette ComparableSubject** (cf. `doc/ongoing/[futur]_DETTE_COMPARABLE_SUBJECT.md`) : les questions de comparaison cross-version (*"différences entre 2022 et 2023"*) échouent parce que **tous les documents sont collés sur un seul ComparableSubject canonique**, sans distinction de version. Le retrieval ne peut pas cibler simultanément les chunks 2022 ET 2023 faute d'ancrage structurel. V17 avait un score plus élevé non pas parce que le système comparait vraiment — mais parce que le keyword evaluator récompensait la simple présence de mots-clés "2022"/"2023" dans la réponse.

**Fixes réellement utiles à conserver (de toute la journée 08/04)** :

1. **Fallback juge corrigé** dans `robustness_diagnostic.py` — plus jamais de fallback silencieux vers un modèle non-OpenAI. Défaut hardcodé `gpt-4o-mini`. Plus `warning` visible au lieu de `debug` en cas d'échec judge. Stats de fin de run avec ratio LLM vs keyword pour détecter le problème immédiatement si ça se reproduit.
2. **Helper `_judge_preprocess.py`** — convertit `[[SOURCE:...]]` → `(Doc, p. X)` localement au pipeline d'évaluation (jamais dans la réponse utilisateur). Utile si jamais le format backend change.
3. **Runners instrumentés** — Robustness, T2/T5, RAGAS stockent désormais les `answer` complètes + `answer_length` + `sources_used`. Indispensable pour toute analyse post-mortem future.
4. **Prompt B8 assoupli** — suppression de l'`INSTRUCTION CRITIQUE` en tête du prompt DIRECT qui causait une compression arbitraire des réponses. C'est une amélioration UX réelle indépendante du benchmark.
5. **Script `rescore_robustness.py`** — permet de re-juger offline un rapport existant sans relancer les 246 questions (50 min → 5 min).

**Fixes à ne PAS reconduire** :

- Les regex de suppression de headers en début de réponse (listes FR/EN hardcodées — casserait sur italien/espagnol)
- La liste d'interdictions explicites de headers dans le prompt (B9) — redondante et contre-productive avec un vrai LLM-juge
- Le pré-traitement de transformation `[[SOURCE:...]]` → `*(Doc, p.X)*` **dans `synthesis.py`** — casserait le rendu SourcePill du frontend
- Tout post-processing qui modifie le contenu visible par l'utilisateur "pour satisfaire le juge"

**Effort restant sur cette section** :

Essentiellement 0. Les fixes utiles sont déjà en place. Le fix du juge était la seule vraie action nécessaire. **Il est à présent dans la branche active** (commit à faire).

**Si on constatait encore des problèmes similaires** :

- **Première action** : lire le ratio `[JUDGE] LLM judge stats : N ok / M failed` dans les logs de fin de run Robustness. Si `failed > 0`, les warnings `[JUDGE] LLM judge call failed: ...` auront détaillé la cause dans les logs.
- **Deuxième action** : `rescore_robustness.py` pour re-juger offline sans relancer le bench.

**Fix ComparableSubject complété (08/04 soir)** :

La seule régression réelle identifiée par le LLM-juge sémantique était `temporal_evolution` (-16.8 pts). Investigation approfondie :

1. **Fix branché** : `SubjectResolverV2` utilise maintenant le `product_gazetteer` du domain pack + les `canonical_aliases` (cf. `[futur]_DETTE_COMPARABLE_SUBJECT.md`)
2. **Script de re-résolution offline** : `app/scripts/resolve_subjects.py` permet de régénérer les ComparableSubjects + AxisValues + propager vers Qdrant pour les documents déjà ingérés, sans re-ingestion
3. **Résultat** : 23 DocumentContexts ré-résolus, 3 `ComparableSubject` distincts (`SAP S/4HANA`, `SAP S/4HANA Cloud Private Edition`, `SAP Cloud ALM`), 22 `AxisValues` persistés (release_id, edition), 7072/7629 chunks Qdrant populés avec `axis_release_id`
4. **Constat** : **le fix structurel est nécessaire mais insuffisant** pour résoudre `temporal_evolution`. Test empirique post-fix : pour une question *"différences Security Guide 2022 vs 2023"*, le retrieval continue à ignorer les chunks 2022 parce qu'il est purement sémantique + rerank, sans contrainte structurelle *"doit couvrir les deux versions"*. Le `strategy_analyzer` détecte bien la nature cross-version en narratif mais ne l'exporte pas en filtres structurés.

**Chantier identifié post-fix : Retrieval par Query Decomposition** (cf. `doc/ongoing/[futur]_RETRIEVAL_QUERY_DECOMPOSITION.md`).

Le fix pour que `temporal_evolution` bénéficie réellement de l'infrastructure en place est un **nouveau composant `QueryDecomposer`** en amont du retrieval : LLM qui détecte les questions de comparaison/énumération/chronologie → décompose en N sous-questions → lance N retrievals indépendants → réconcilie dans un contexte structuré pour le synthétiseur. Pattern connu en RAG moderne (*Self-Ask, IRCoT, Sub-question Decomposition*). **Généralise au-delà du cross-version** : comparaison entre variantes produit, études cliniques, versions de loi, campagnes marketing, etc. Totalement domain-agnostic.

**Estimation chantier** : 1-2h pour un prototype de validation, 1-2 jours pour une intégration propre + observabilité + tests cross-domain. Ce n'est PAS un blocker MUST HAVE pour la démo V0.1, mais ce sera probablement le chantier le plus impactant en termes de qualité de réponse pour les questions complexes.

**Problème confirmé empiriquement le 08/04** après analyse question par question des rapports T2/T5 et Robustness pre/post Perspective Layer. La cause des régressions observées n'est **ni** la couche Perspective elle-même (jamais déclenchée sur Robustness, et correctement déclenchée sur T2/T5), **ni** l'override TENSION (trop peu fréquent sur T2/T5 — 3.3% — pour expliquer une baisse de 13% globale). La vraie cause est le **durcissement des règles de style** introduit en Phase B7 dans `config/synthesis_prompts.yaml`, qui affecte les modes DIRECT, TENSION et PERSPECTIVE.

**Les règles problématiques** (présentes à l'identique dans les templates DIRECT et TENSION) :

```yaml
DIRECT/TENSION:
  INSTRUCTION CRITIQUE : commence ta reponse directement par le contenu
  factuel. Ne commence JAMAIS par un titre, un header, ou le mot "Reponse".
  ...
  1. Commence IMMEDIATEMENT par le contenu factuel. INTERDIT de commencer
     par "Reponse", "Synthese", "Analyse", un titre ou un header.
  4. Utilise des puces si necessaire mais pas de gros headers markdown
     (pas de # ou ##).
```

L'intention de B7 était légitime : éliminer le verbiage structurel (`# Analyse des Incohérences`, `## 1. Synthèse`, templates `Position A / Position B`, tableaux comparatifs) qui polluait les réponses sans ajouter de valeur. Mais le LLM a mal interprété les règles et en a tiré un **comportement contre-productif** selon le mode.

**Preuves empiriques — données factuelles, non-hypothèses :**

**Sur T2/T5 (125 questions T2 communes)** :

| Métrique | PRE (04/04) | POST (08/04) | Delta |
|---|---:|---:|---:|
| Longueur moyenne des réponses | 3 810 chars | 2 927 chars | **-23.2%** |
| Longueur médiane | 4 041 | 2 661 | **-34.2%** |
| % questions avec réponse plus courte POST | — | — | 66.4% |
| Corrélation (Δ longueur, Δ claim_coverage) | — | — | **+0.60** |
| `claim1_coverage` moyen | 0.6544 | 0.4805 | **-26.6%** |
| `claim2_coverage` moyen | 0.6645 | 0.4902 | **-26.2%** |
| `both_sources_cited` moyen | 0.7400 | 0.6440 | **-13.0%** |

La corrélation de +0.60 entre la baisse de longueur et la baisse de couverture est **statistiquement significative** et directionnelle : plus une réponse raccourcit, plus la couverture factuelle des claims du ground truth baisse. **Sur T2/T5, le LLM compresse les réponses de 23 à 34% en moyenne** et perd en conséquence une partie du contenu substantiel nécessaire à couvrir les deux claims attendus.

Exemples bruts observés :
- `T2_EXP_0021` : PRE 5533 chars → POST 2712 chars (-51%), avec toutes les métriques ground truth qui chutent
- `T2_KG_0003` : PRE 4383 chars → POST 1968 chars (-55%), claim1_coverage 0.93 → 0.27

**Sur Robustness (246 questions communes)** :

L'effet est **différent mais lié à la même cause**. Les réponses ne raccourcissent pas forcément — mais **elles changent de style** : sur-structuration avec headers qui n'existaient pas en PRE.

| Catégorie | Score PRE | Score POST | Headers PRE | Headers POST |
|---|---:|---:|---:|---:|
| **causal_why** | 0.7583 | **0.4778 (-37%)** | **0/24 (0%)** | **18/24 (75%)** |
| **conditional** | 0.8042 | **0.5368 (-33%)** | 1/24 | 9/24 |
| negation | 0.7840 | 0.6561 (-16%) | 7/25 | 17/25 |
| hypothetical | 0.7000 | 0.7262 (+4%) | 1/23 | 18/23 |
| synthesis_large | 0.6120 | 0.9163 (+50%) | 23/25 | 21/25 |
| multi_hop | 0.6480 | 0.7933 (+22%) | 14/25 | 14/25 |

**Au total sur Robustness** : 30.1% des réponses PRE commençaient par un header, **59.8% des réponses POST** — le taux a **doublé** alors que les règles B7 interdisent explicitement les headers. Le LLM **ne respecte pas la règle** mais change quand même son style en conséquence.

Les catégories qui régressent sont précisément celles où les headers ont explosé. Les catégories qui progressent sont celles qui étaient déjà structurées.

**Exemple brut causal_why** (T6_CA_001 *"Pourquoi SAP S/4HANA nécessite-t-il SAP HANA comme base de données ?"*) :

**PRE** (score 0.76) — démarre direct, explicatif :
```
SAP S/4HANA nécessite SAP HANA comme base de données pour plusieurs raisons clés :

1. **Architecture optimisée** : SAP S/4HANA est conçu pour tirer parti des
   capacités de traitement en mémoire de SAP HANA...
```

**POST** (score 0.48) — démarre par un header encyclopédique :
```
## Caractère obligatoire de SAP HANA comme base de données

SAP S/4HANA requiert SAP HANA comme base de données pour fonctionner.
Cette exigence est catégorique : toute nouvelle installation...
```

La réponse POST est plus "académique", plus abstraite, moins directement en prise avec la chaîne causale attendue (*"pourquoi X ?"* appelle *"parce que Y entraîne Z"*, pas *"## Caractère obligatoire"*).

**Mécanisme de défaillance identifié** :

Le LLM Haiku reçoit des règles négatives (*"INTERDIT de commencer par..."*, *"pas de gros headers"*, *"INSTRUCTION CRITIQUE : commence ta réponse directement"*). Il les traduit en consigne interne *"sois plus formel, plus concis, moins bavard"* — et applique cette consigne de deux façons selon le contexte :

1. **Sur les questions de tension (T2/T5)** où il a beaucoup à dire : il **compresse** en coupant des détails factuels pour "être concis"
2. **Sur les questions factuelles (Robustness causal_why/conditional)** où il a peu à dire : il **sur-structure** avec des headers plus "encyclopédiques" pour "être formel"

Dans les deux cas, le résultat s'éloigne de ce qu'attendent les judges des benchmarks et les évaluateurs humains : des réponses **directes et exhaustives** sur le plan factuel.

**Fix proposé** — réécriture des prompts pour remplacer les règles négatives par des règles positives :

1. **Supprimer** l'*"INSTRUCTION CRITIQUE"* en tête des prompts DIRECT/TENSION/PERSPECTIVE — elle met le LLM en mode défensif
2. **Supprimer** les interdictions explicites (*"INTERDIT de commencer par..."*, *"pas de gros headers"*)
3. **Remplacer par des règles positives** :
   - *"Réponds directement et exhaustivement à la question, avec tous les détails factuels pertinents des sources."*
   - *"Structure ta réponse uniquement si cela aide la lisibilité du lecteur. Une question simple mérite une réponse simple ; une question complexe peut justifier des sections courtes."*
   - *"Pour les citations, utilise le format `*(Nom du document, p.XX)*` directement dans le texte."*
4. **Garder** les règles substantielles qui étaient justifiées :
   - Pas d'invention, pas de Source A/B générique, pas de "Unknown source", citations obligatoires
5. **Ne pas toucher** au template synthesis_large qui fonctionne (+50% gain) — son comportement sur-structuré est adapté à ce type de question

**Effort estimé** : 1-2 heures (édition de `config/synthesis_prompts.yaml` + re-benchmark).

**Pourquoi ce devrait être MUST HAVE et pas SHOULD HAVE** : l'impact est mesurable et significatif (-26% de claim coverage sur T2/T5, -37% sur causal_why Robustness). Le ROI du fix est extrêmement élevé : quelques lignes de prompt à réécrire pour potentiellement récupérer plusieurs dizaines de points sur des métriques clés. **Je recommande de promouvoir cet item en MUST HAVE avant la démo** et de re-benchmarker immédiatement après pour valider.

**Références** :
- Scripts d'analyse : `benchmark/probes/analyze_t2t5_diff.py`, `analyze_t2t5_answer_length.py`, `analyze_robustness_style.py`
- Données : rapports `t2t5_run_20260404_074418_V3_MODES_VS_RAG.json` (PRE) vs `t2t5_run_20260408_065401_POST_PerspectiveLayer_v3.json` (POST), `robustness_run_20260402_140940_V17_PREMISE_VERIF.json` (PRE) vs `robustness_run_20260407_131617_POST_PerspectiveLayer.json` (POST)
- Fichier à modifier : `config/synthesis_prompts.yaml` sections `DIRECT`, `TENSION`, `PERSPECTIVE`

---

### S5. Sanity check langue du corpus externe avant ingestion

**Problème** : même avec M3 (stopwords multilingues), si on ingère un corpus dans une langue qu'on n'a pas prévue (par exemple du turc ou du russe), on aura un comportement dégradé qu'on préférerait détecter **avant** plutôt que pendant l'ingestion.

**Ce qu'il faut faire** : un script de **pré-analyse** qui examine un échantillon du corpus avant l'ingestion et rapporte :
- Langues détectées par document
- Couverture des stopwords configurés
- Formats de fichiers
- Taille totale et nombre de pages estimé
- Warning si une langue non supportée représente > 10% du corpus

**Effort estimé** : 2-4 heures. C'est un script Python autonome qui charge les documents, lance `langdetect` et produit un rapport texte.

---

### Récapitulatif SHOULD HAVE

| Item | Effort |
|---|---|
| S1. Keywords de détection linguistique externalisés | 1 j |
| S2. Consolidation `CANONICAL_PREDICATES` | 1-2 h |
| S3. Instrumentation staleness Perspective | 2-3 h |
| S4. Doc de cadrage interlocuteur | 2-3 h |
| S5b. Calibrer override TENSION (régressions Robustness) | 1-2 h |
| S5. Sanity check langue pré-ingestion | 2-4 h |
| **Total estimé** | **~2-3 jours** supplémentaires |

---

## NICE TO HAVE — si on a encore du temps avant la démo

*Ces items seraient des plus visibles pour la démo mais demandent un effort important pour un gain marginal. À considérer seulement si les MUST et SHOULD sont tous faits et qu'il reste plusieurs jours.*

### N1. Domain Pack Studio — prototype minimal

**Idée** : une interface simple (page admin, ou script CLI guidé) qui permet de générer un `context_defaults.json` pour un nouveau domaine à partir d'un échantillon de documents de ce domaine. Le LLM propose un gazetteer candidat (entités récurrentes, acronymes détectés, termes spécialisés), l'utilisateur valide ou corrige.

**Pourquoi ce serait utile pour la démo** : ça transforme la narration *"OSMOSIS marche sans domain pack mais peut être spécialisé"* en *"OSMOSIS marche sans domain pack et peut être spécialisé en 30 minutes via cette interface"*. Passage d'une fonctionnalité théorique à un bénéfice démontrable.

**Pourquoi ce n'est pas should** : c'est un chantier à part entière (minimum 3-5 jours pour un MVP utilisable) et le gain est sur l'impression, pas sur la fonctionnalité core. La démo peut réussir sans.

**Effort estimé** : 3-5 jours pour un MVP, plusieurs semaines pour une version polished.

---

### N2. Rebuild incrémental partiel de Perspective V2

**Idée** : au lieu de rebuild **toutes** les Perspectives à chaque post-import, identifier celles qui sont **impactées** par les nouveaux claims (distance au centroid < seuil) et ne rebuild que celles-là.

**Pourquoi ce serait utile** : divise le coût de rebuild par 5-10 pour les grosses bases. Aujourd'hui un rebuild fait ~3-5 minutes ; incrémental partiel le réduit à ~30 secondes pour une petite ingestion.

**Pourquoi ce n'est pas should** : c'est un chantier algorithmique qui demande réflexion et tests. Pour une démo sur 100 docs, le coût de rebuild complet (~5 min) est absorbable.

**Effort estimé** : 3-5 jours.

**Référence** : `[futur]_DETTE_INCREMENTAL_REBUILD.md` section 8 Q2.

---

### N3. Atlas NarrativeTopic — prototype exploratoire

**Idée** : commencer à prototyper la couche NarrativeTopic (community detection sur le graphe biparti Perspective ↔ Subject) pour avoir un niveau macro de réponse sur des questions type *"quels sont les grands thèmes de ce corpus ?"*.

**Pourquoi ce serait utile** : ce type de question risque d'être posé par l'interlocuteur ("donne-moi un résumé de ce corpus"), et OSMOSIS n'a pas de réponse native à ça aujourd'hui — seulement via le mode PERSPECTIVE qui liste les axes mais ne synthétise pas.

**Pourquoi ce n'est pas should** : dépend de M1 (dette Subject) donc ne peut être commencé qu'après. Et c'est un chantier profond (plusieurs jours minimum). Risque élevé que ça déborde et compromette les MUST HAVE.

**Effort estimé** : 5-10 jours.

**Référence** : `doc/CHANTIER_ATLAS.md` section 7.

---

### N4. Consolidation des autres hardcoded lists (moyenne/basse priorité)

**Idée** : finir le chantier de l'audit hardcoded lists (items #5-40 qui ne sont pas dans MUST/SHOULD).

**Pourquoi ce serait utile** : propreté du code, facilité de maintenance, possibilité d'ajouter des domaines plus facilement.

**Pourquoi ce n'est pas should** : aucun de ces items ne représente un risque visible pour la démo. C'est de la dette technique légitime à traiter plus tard.

**Effort estimé** : 3-5 jours pour tout consolider.

---

### N5. Leiden probe v2 — validation avec `leidenalg`

**Idée** : installer `leidenalg` + `igraph` dans l'environnement, refaire le probe avec du vrai Leiden au lieu de Louvain (NetworkX built-in), explorer les pistes identifiées dans `[futur]_REFLEXION_LEIDEN_GRAPHRAG.md` (diagnostic qualité Perspective, complémentarité sémantique/structurel).

**Pourquoi ce serait utile** : enrichit la compréhension du corpus et peut révéler des pistes d'amélioration à long terme.

**Pourquoi ce n'est pas should** : pas de lien direct avec la démo V0.1. C'est de la recherche interne.

**Effort estimé** : 1-2 jours.

---

### N6. Cockpit enrichi — métriques de diagnostic corpus

**Idée** : ajouter des tuiles cockpit pour diagnostiquer rapidement la santé du corpus après ingestion :
- Distribution des langues détectées
- Distribution des types de documents
- Couverture des Subjects vs Documents (ratio d'ancrage produit)
- Distribution des scores de confiance des Claims
- Orphelins (claims sans Perspective, entities sans mention, etc.)

**Pourquoi ce serait utile** : lors de la démo, pouvoir montrer ces métriques sur l'écran cockpit est visuellement impressionnant et diagnostiquement utile.

**Pourquoi ce n'est pas should** : ça polish la démo mais ça ne change pas la capacité de répondre. Si le temps manque, l'interlocuteur se fiche du cockpit.

**Effort estimé** : 1 jour.

---

### Récapitulatif NICE TO HAVE

| Item | Effort | Valeur si fait |
|---|---|---|
| N1. Domain Pack Studio MVP | 3-5 j | Narration produit forte |
| N2. Rebuild Perspective incrémental partiel | 3-5 j | Scalabilité démontrée |
| N3. Atlas NarrativeTopic prototype | 5-10 j | Réponse aux questions "corpus global" |
| N4. Consolidation autres hardcoded lists | 3-5 j | Hygiène code |
| N5. Leiden probe v2 | 1-2 j | Insight recherche |
| N6. Cockpit métriques corpus | 1 j | Polish visuel |

---

## Synthèse — scénarios temporels

### Scénario "démo dans 10 jours"

Priorité absolue aux MUST HAVE + éventuellement S1 et S4 (les plus rapides et à plus haut impact).

| Jour | Activité |
|---|---|
| J1 | M1 (fix ComparableSubject) démarrage |
| J2 | M1 fin + M2 (build_perspectives dans post-import) |
| J3 | M3 (stopwords multilingues) |
| J4 | Benchmarks baseline (M5) en background + M6 (runbook) + S4 (doc cadrage) |
| J5-J6 | M4 (dry-run corpus externe) + fixes |
| J7 | Validation finale, répétition de la procédure d'ingestion |
| J8-J10 | Buffer — résolution des problèmes inattendus, polish |

**Risque principal** : M1 plus difficile que prévu (si la logique du resolver V2 est plus tortueuse qu'anticipée). **Plan B** : fallback sur une résolution plus simple (matching long-to-short canonique) qui corrige 80% du problème sans la subtilité complète.

### Scénario "démo dans 1 mois"

MUST HAVE + tous les SHOULD HAVE + sélection de NICE TO HAVE selon préférence.

| Semaine | Activité |
|---|---|
| S1 | MUST HAVE complet (M1-M6) |
| S2 | SHOULD HAVE (S1-S5) + second dry-run sur autre domaine pour robustesse |
| S3 | Sélection NICE TO HAVE (probablement N6 cockpit + N5 Leiden pour l'insight) |
| S4 | Répétitions, polish, documentation |

**Optimisation possible** : intégrer N1 (Domain Pack Studio MVP) si l'enjeu narratif est fort pour cet interlocuteur spécifique. Demande d'arbitrer tôt.

### Scénario "démo dans 2 mois"

Quasi-tout peut être fait. Le risque bascule vers la procrastination et le scope creep. Garder un focus strict sur ce qui apporte de la valeur à la démo précise, pas sur "l'amélioration générale du produit".

| Semaine | Activité |
|---|---|
| S1-S2 | MUST + SHOULD HAVE |
| S3 | N1 (Domain Pack Studio MVP), N2 (rebuild incrémental) |
| S4 | N3 (Atlas NarrativeTopic prototype) — si pertinent selon type de corpus attendu |
| S5-S6 | Dry-runs multiples, optimisations perf |
| S7 | Préparation narrative, slides, argumentaire |
| S8 | Buffer, répétition générale |

**Attention** : 2 mois est assez long pour que le scope dérive. Le plus grand risque dans ce scénario n'est pas technique, c'est psychologique — l'envie d'en faire toujours "un peu plus". Se discipliner à figer le périmètre après la S4.

---

## Check-list de départ — tout est-il prêt ?

*Cette liste doit être validée item par item la semaine précédant la démo. Tant qu'une case n'est pas cochée, la démo n'est pas prête.*

### Couche technique

- [ ] M1. `SubjectResolverV2` utilise le `product_gazetteer` — testé avec corpus SAP multi-produits
- [ ] M2. Post-import pipeline inclut `build_perspectives` — vérifié via log d'une ingestion test
- [ ] M3. Stopwords multilingues externalisés — testé avec document non-FR/EN
- [ ] M4. Dry-run corpus externe test — complété sans intervention manuelle
- [ ] M5. Benchmarks baseline SAP archivés sous tag clair
- [ ] M6. Runbook ingestion externe écrit et suivi lors du dry-run
- [ ] Cockpit fonctionnel et lisible en temps réel
- [ ] Backup complet Neo4j + Qdrant + Redis fait (snapshot)
- [ ] Plan de rollback testé

### Couche interlocuteur

- [ ] Doc de cadrage envoyé et validé (S4)
- [ ] Méthode de transfert du corpus définie et sécurisée
- [ ] Temps de disponibilité de l'interlocuteur pour le feedback calé
- [ ] Format des livrables (rapport écrit ? démo live ? JSON des réponses ?) négocié

### Couche mentale

- [ ] Liste des questions de sanity check préparée (3-5 questions types)
- [ ] Narration claire sur ce qui sera montré et comment l'interpréter
- [ ] Plan B en cas d'échec pendant la démo identifié (ex: basculer sur corpus SAP)
- [ ] Temps buffer prévu pour traiter un imprévu

---

## Ce qu'il ne faut PAS faire avant la démo

- **Ne pas démarrer de gros chantier de refonte**. Pas d'ADR fondateur, pas de re-architecture, pas de nouveau mode. La démo valide ce qu'on a, pas ce qu'on voudrait avoir.
- **Ne pas ignorer un test qui révèle un problème.** Si le dry-run M4 trouve un bug, il faut le fixer, pas le contourner. La démo ne doit pas tourner sur un contournement fragile.
- **Ne pas cacher les limitations à l'interlocuteur.** Le doc de cadrage S4 doit être honnête sur ce qui n'est pas prouvé. Un succès cadré est plus crédible qu'un succès apparent.
- **Ne pas démarrer la démo sur un système qui a changé la veille.** Figer le code 48h avant la date, seulement des patches critiques en cas d'urgence.
- **Ne pas céder au "encore un petit polish"**. Une fois la check-list validée, s'arrêter. Les dernières 10% du polish perfectionniste apportent 2% de valeur et portent 30% de risque de régression.

---

## Références croisées

- `doc/ongoing/[futur]_DETTE_COMPARABLE_SUBJECT.md` — diagnostic complet M1
- `doc/ongoing/[futur]_DETTE_INCREMENTAL_REBUILD.md` — diagnostic complet M2 + S3
- `doc/ongoing/AUDIT_HARDCODED_WORD_LISTS.md` — inventaire complet M3 + S1 + S2 + N4
- `doc/ongoing/KG_NODES_GLOSSAIRE.md` — référence schéma Neo4j (utile pour expliquer à l'interlocuteur)
- `doc/ongoing/[futur]_REFLEXION_LEIDEN_GRAPHRAG.md` — réflexion comparative, utile pour le pitch narratif (N5)
- `doc/CHANTIER_ATLAS.md` section 7 — vision Atlas narratif (N3)
- `src/knowbase/domain_packs/enterprise_sap/context_defaults.json` — domain pack existant, à étudier pour M1 et N1
- `cockpit/pipeline_defs.yaml` — à modifier pour M2 et S3
