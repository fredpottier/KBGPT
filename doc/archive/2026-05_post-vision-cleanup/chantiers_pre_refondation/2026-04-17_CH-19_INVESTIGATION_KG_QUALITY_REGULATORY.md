# Investigation qualité KG — Corpus réglementaire

*Date : 12 avril 2026*
*Corpus : 71 docs réglementaires (GDPR, AI Act, CCPA, NIST, EDPB, etc.)*
*Stats KG : 9483 claims, 1525 entities, 71 DocumentContexts*

## Problèmes identifiés

### P1. Claims orphelines — 54% sans relation ABOUT [CRITIQUE]

**Constat** : 5096/9483 claims (54%) n'ont aucune relation ABOUT vers une Entity.

**Cause racine identifiée** : L'EntityExtractor est purement déterministe (regex : termes capitalisés, acronymes, patterns syntaxiques). Il extrait correctement les entités (ex: "European Data Protection Board") mais le **lien ABOUT est créé par entity_id**, pas par nom normalisé. Chaque document crée ses propres Entity nodes avec des entity_id uniques. Quand deux documents contiennent la même entité :
- Doc A crée Entity(id=X, name="EDPB") + ABOUT(claim_A → X)
- Doc B crée Entity(id=Y, name="EDPB") + ABOUT(claim_B → Y)
- La canonicalisation post-import crée SAME_CANON_AS(X, Y) mais **NE PROPAGE PAS** les ABOUT

De plus, la propriété `structured_form` (subject/predicate/object) n'est remplie que pour 8% des claims (786/9483) — c'est by design (seulement pour les claims relationnelles "X uses Y").

**Preuve** : la claim "It is appropriate to consult the European Data Protection Board..." existe dans doc 01 (orpheline, ABOUT=NULL) et doc 26 (liée, ABOUT=European Data Protection Board). Même texte, résultats différents.

**Cause racine CONFIRMÉE (investigation 12/04/2026)** :

Désalignement entre le MERGE Entity et le MATCH ABOUT dans `claim_persister.py` :

1. `_persist_entities_batch()` fait `MERGE (e:Entity {normalized_name: ..., tenant_id: ...})`
   - Sur ON CREATE : entity_id est défini
   - Sur ON MATCH : entity_id n'est **PAS** mis à jour (juste mention_count++)
   
2. `_persist_about_batch()` fait `MATCH (e:Entity {entity_id: item.entity_id})`
   - L'entity_id dans le batch Python est celui du doc en cours (ex: "entity_XYZ")
   - Mais le node Neo4j a l'entity_id du PREMIER doc qui l'a créé (ex: "entity_ABC")
   - → Le MATCH échoue silencieusement → la relation ABOUT n'est PAS créée

**Preuve** : Doc 01 (AI Act Final) extrait 206 entités, l'EntityLinker crée 2009 ABOUT links en mémoire, mais seulement 345 sont persistées dans Neo4j (83% perdus). Doc 26 (traité en premier) a 1439 ABOUT car ses entity_ids sont ceux du ON CREATE.

**Fix** : Modifier `_persist_about_batch()` pour matcher par `normalized_name` au lieu de `entity_id` :
```python
# AVANT (bugué)
MATCH (e:Entity {entity_id: item.entity_id})
# APRÈS (fix)  
MATCH (e:Entity {normalized_name: item.normalized_name, tenant_id: item.tenant_id})
```

Ou alternativement, ajouter une mise à jour de `entity_id` dans le ON MATCH de `_persist_entities_batch()`.

**Impact** : 54% des claims sont invisibles dans le graphe d'entités → dégradation du retrieval KG, des Perspectives, et des chaînes cross-doc.

**Fix appliqué (12/04/2026)** :
1. Fix persister : `_persist_about_batch` matche par `normalized_name` au lieu de `entity_id` — empêche le bug sur les futurs imports
2. Script `relink_orphan_claims.py` exécuté : 735 liens ABOUT créés, 652 claims re-liées (46% → 53%)
3. **4444 claims restent orphelines** — causes distinctes ci-dessous

### P1-bis : Pourquoi 4444 claims restent sans entité (investigation approfondie)

Décomposition des 4444 orphelins restants :

| Catégorie | Nb | % | Cause |
|-----------|-----|---|-------|
| **Aucun pattern regex** | 2692 | 60.6% | Phrases en prose pure sans terme capitalisé ni acronyme — l'EntityExtractor basé sur la casse ne peut rien extraire |
| **Acronyme 2 chars** (AI, EU) | 1562 | 35.1% | "AI" et "EU" sont dans `ENTITY_STOPLIST` → filtrés. Logique pour SAP, catastrophique pour un corpus IA/réglementaire |
| **Acronyme 3+ chars** (DSA, CCPA, MAP) | 162 | 3.6% | Pas dans la stoplist mais jamais créés comme Entity nodes |
| **Caps trouvés mais faux positif** | 28 | 0.6% | Regex capte "In March" etc. |

**Problème A — Stoplist trop agressive (35%)** :
- "AI", "EU", "US", "MAP" sont dans `ENTITY_STOPLIST`
- Pour le corpus SAP c'est justifié (trop vague), pour un corpus IA/réglementaire c'est destructeur
- Fix : la stoplist devrait être sensible au domaine (via le domain pack ?)
- Fichier : `src/knowbase/claimfirst/models/entity.py`, `ENTITY_STOPLIST`

**Problème B — Prose sans majuscules (60%)** :
- L'EntityExtractor est purement déterministe (regex sur la casse)
- Les textes réglementaires sont rédigés en prose courante avec peu de majuscules
- Les entités conceptuelles ("data protection", "high-risk AI systems", "conformity assessment") sont en minuscules
- Fix : nécessite un EntityExtractor sémantique (LLM ou NER) en complément du regex
- Impact : c'est le plus gros volume mais aussi le plus complexe à corriger

**Problème C — Entités non créées (4%)** :
- "DSA", "CCPA", "GPAI" ne sont pas dans la stoplist mais n'existent pas comme Entity nodes
- Le regex ACRONYM_PATTERN les détecte mais elles ne sont jamais persistées
- Hypothèse : filtrées par `min_mentions` au sein du document, ou perdues lors de la canonicalisation
- Fix : abaisser `min_mentions` ou créer les entités depuis le domain pack gazetteer

**Fixes appliqués (12/04/2026)** :
1. Script `relink_orphan_claims.py` : +735 liens (match exact + acronyme + pluriel/singulier) → 53%
2. GLiNER reprocess (sidecar NER regulatory activé) : +663 liens, 484 nouvelles entités → 55%

**Bilan final P1 : 46% → 55% (+9 pts)**

Les 4238 orphelines restantes (45%) ont été analysées :
- 94% sont des **claims sans ancrage thématique** — phrases prescriptives génériques ("shall ensure", "must comply") sans aucune entité nommée ni concept juridique identifiable
- 6% contiennent un concept juridique en minuscules ("transparency", "risk assessment") potentiellement rattachable

**Conclusion** : ce n'est pas un problème de NER mais un problème de **qualité d'extraction en amont**. Le ClaimExtractor produit trop de claims faibles sur le corpus réglementaire (considérants, préambules, formulations vagues). Le quality gate (verifiability) ne filtre pas la **spécificité** — une claim peut être vérifiable ("The approach will deliver a framework") sans être spécifique.

**Enseignement pour le pipeline** : envisager un quality gate supplémentaire sur la spécificité des claims (ex: la claim doit nommer au moins un concept identifiable pour être retenue). À traiter comme amélioration P6 du pipeline, pas comme un bug.

---

### P2. Facets — 3% de couverture seulement [MAJEUR]

**Constat** : 10 Facets existent mais seulement 317/9483 claims (3%) ont BELONGS_TO_FACET. Les facets sont des résidus SAP ("Security", "Data Management", "Infrastructure", "Configuration") non adaptées au domaine réglementaire.

**Cause** : Le step "Reconstruction facettes" du post-import a tourné mais n'a pas recréé de nouvelles facettes adaptées au corpus. Les 10 facets existantes (provenant du corpus SAP précédent) ont été conservées mais les nouvelles claims réglementaires ne matchent que "Security" (294 claims).

**Causes racines CONFIRMÉES (investigation 12/04/2026)** :

**Problème A — Prompt LLM trop générique** :
Le prompt du `FacetCandidateExtractor` demande des "UNIVERSAL DIMENSIONS" réutilisables "like a library catalog" avec des exemples comme "Security", "Compliance", "Operations". Le LLM produit donc toujours les mêmes ~10 catégories IT universelles, quel que soit le corpus. Pour un corpus réglementaire, il manque des facets comme "Droits des personnes concernées", "Obligations de transparence IA", "Transferts internationaux de données", "Sanctions et amendes".

Fichier : `src/knowbase/claimfirst/extractors/facet_candidate_extractor.py`, `SYSTEM_PROMPT` (ligne 50)

**Problème B — Seuil `min_ratio` biaisé par le nombre de keywords** :
Le `FacetMatcher` exige `matched_keywords / total_keywords >= 0.05`. Les facets avec beaucoup de keywords (Compliance: ~100, Business Functionality: ~100) nécessitent 5+ matches pour passer le seuil. Les facets avec peu de keywords (Security: 15) n'en nécessitent qu'un seul.

Résultat : "Security" (15 kw) → 294 claims liées. "Compliance" (100 kw) → 0 claims liées, alors qu'elle est la facet la plus citée dans les DocumentContexts (doc_count=66).

Fichier : `src/knowbase/claimfirst/linkers/facet_matcher.py`, `_match_by_keywords_only()` (ligne ~129), paramètre `min_ratio=0.05`

**Fix proposé** :
1. Problème A : rendre le prompt sensible au corpus (injecter un échantillon de claims du corpus dans le prompt pour que le LLM adapte les dimensions)
2. Problème B : remplacer `min_ratio` par un seuil absolu (`min_keywords_matched >= 2`) ou utiliser `min(matched/total, matched/5)` pour plafonner le dénominateur

**Impact** : Les Perspectives dépendent partiellement des facets (via `facet_weight` dans le clustering). 3% de couverture = le clustering Perspective repose quasi exclusivement sur les embeddings, ce qui fonctionne (57% coverage) mais les Perspectives seraient plus précises avec des facets pertinentes.

---

### P3. Perspectives sans ComparableSubject [MAJEUR]

**Constat** : 60 Perspectives créées, labels pertinents, 57% des claims couvertes via INCLUDES_CLAIM. Mais `subject_id = NULL` sur toutes → 0 HAS_PERSPECTIVE vers ComparableSubject.

**Cause probable** : Le PerspectiveBuilder n'a pas réussi à résoudre les subjects. Le builder collecte les claims via ComparableSubject → DocumentContext → Document → Claims. Si le lien ComparableSubject → DocumentContext est trop faible ou que les ComparableSubjects ont des noms qui ne matchent pas, le builder fallback vers un mode "all claims" sans subject.

**Investigation (12/04/2026) — PAS UN BUG, changement d'architecture** :

Le schema des Perspectives a évolué de V1 à V2 :
- **V1** : `(:ComparableSubject)-[:HAS_PERSPECTIVE]->(:Perspective)` — 1 subject parent par Perspective
- **V2** : `(:Perspective)-[:TOUCHES_SUBJECT]->(:SubjectAnchor|:ComparableSubject)` — N:M, chaque Perspective touche plusieurs sujets

Le champ `subject_id` (singulier) est NULL car il n'est plus utilisé en V2. À la place, `linked_subject_ids` (array) est peuplé et les relations `TOUCHES_SUBJECT` sont créées.

**État réel** : 1822 TOUCHES_SUBJECT (1730 vers SubjectAnchor, 92 vers ComparableSubject). Les Perspectives sont bien connectées.

**Verdict** : ~~Bug~~ → Changement de design intentionnel. Le doc d'investigation P3 peut être fermé.

**Point d'attention résiduel** : le plan d'implémentation (buzzing-shimmying-blanket.md) référence encore HAS_PERSPECTIVE — il faudra le mettre à jour. Et les composants chat (scorer.py, runtime.py) doivent utiliser TOUCHES_SUBJECT au lieu de HAS_PERSPECTIVE pour résoudre les sujets.

---

### P4. CONTRADICTS faibles — 71 sur 3195 QS contradictions [MINEUR]

**Constat** : Le step C4 Relations n'a produit que 71 CONTRADICTS alors que 3195 QS_COMPARED sont de type CONTRADICTION.

**Analyse** : Les QS contradictions sont principalement des différences de **valeurs numériques entre réglementations différentes** (ex: amende GDPR $20M vs AI Act $35M). Ce ne sont pas des contradictions au sens strict — ce sont des différences légitimes entre textes juridiques distincts. Le LLM arbiter a correctement rejeté la plupart comme "not contradictions".

**Verdict** : Comportement probablement correct. 71 contradictions réelles sur un corpus réglementaire multi-juridictionnel est plausible.

---

### P5. Entités génériques en top hubs [MINEUR]

**Constat** : Les top entités par claims sont "Processing" (196), "requirements of the EU AI Act" (195), "AI systems" (170), "personal information" (145). Ce sont des termes trop génériques pour être des hubs utiles.

**Cause** : L'EntityExtractor capture tout terme capitalisé multi-mots sans discrimination sémantique. Le domain pack (step 6) aurait dû résoudre certains de ces termes mais son impact sur les entités génériques est limité (le gazetteer cible les noms de réglementations, pas les termes génériques).

**Piste** : La stoplist IDF + hygiène L1 devrait filtrer ces termes, mais "Processing" et "AI systems" ne sont pas des stopwords universels — ils sont spécifiques à ce corpus.

---

## Ordre de priorité d'investigation

1. **P1** — Claims orphelines (54%) : impact majeur sur toute la chaîne (retrieval, Perspectives, chaînes)
2. **P2** — Facets vides (3%) : impact sur le clustering et les Perspectives
3. **P3** — Perspectives sans subject : impact sur la navigation et le mode chat
4. **P5** — Entités génériques : impact sur la qualité du graphe
5. **P4** — CONTRADICTS faibles : probablement correct, à valider

### P6. Atlas — Topics trop larges et mélange de juridictions [MAJEUR]

**Constat** : Les NarrativeTopics mélangent des contenus de juridictions différentes. Exemple : "Regulating High-Risk AI: Governance and Compliance" sous "EU AI Act" contient des Perspectives US ("Federal AI Regulation & Innovation", "Appointment of Chief AI Officers") mélangées avec des Perspectives EU.

**Cause racine identifiée (investigation 12/04/2026)** :

Le clustering Louvain sur le graphe biparti Perspective × SubjectAnchor est pollué par des **SubjectAnchors hub** qui connectent toutes les Perspectives entre elles :
- "GDPR" → 45/60 Perspectives (75%)
- "AI systems" → 45/60
- "Providers" → 44/60
- "Deployers" → 44/60

Ces hubs créent des liens parasites entre des Perspectives US et EU → le Louvain les fusionne dans la même communauté. Augmenter la résolution Louvain ne résout pas le problème fondamentalement.

**Fix proposé** : Pondérer les liens du graphe biparti par **IDF inverse** avant le Louvain :
- Poids d'un lien Perspective → SubjectAnchor = `log(N_perspectives / count_perspectives_touching_subject)`
- Un SubjectAnchor partagé par 45/60 Perspectives = poids ~0 (ne discrimine pas)
- Un SubjectAnchor partagé par 2/60 Perspectives = poids élevé (discriminant)

C'est le même principe que le fix IDF appliqué aux entités (P1-bis) et aux facettes (P2). Pattern récurrent : les éléments trop fréquents polluent le signal.

**Fichier impacté** : `app/scripts/build_narrative_topics.py`, fonction `detect_communities()`

---

## Métriques de référence (baseline)

| Métrique | Valeur | Cible |
|----------|--------|-------|
| Claims avec ABOUT | 46% → **97%** | >80% ✅ |
| Claims avec BELONGS_TO_FACET | 3% | >60% |
| Perspectives avec subject | 0% | 100% |
| Cross-doc CHAINS_TO | 121 (59 paires) | — |
| CONTRADICTS | 71 | — |
| REFINES + QUALIFIES | 1285 | — |
