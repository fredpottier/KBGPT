# Investigation — Faible linkage Claim→Facet (~27%)

**Date** : 18/04/2026
**Contexte** : Corpus biomédical préeclampsie (57 docs, 7627 claims) post-ingestion ClaimFirst + post-import pipeline complet.
**État** : Problème identifié, pistes de correction échouées, chantier à reprendre proprement.
**Priorité** : Haute — le linkage facet a poids 55% de la famille "Structure" (35% du score global KG audit).

## 1. Constat

### Métriques audit corpus

```
Structure: 58/100 (A surveiller)
  Linkage Claim → Facet: 27.1% (2076/7627)     ← poids 55% — bloquant
  Entités non-orphelines: 93.8%                 ← OK après repair
  Sujet résolu: 100%                            ← OK
```

### Couverture fine
- **7627 claims**, seuls **2076 liés** à au moins une facet validée (27.1%)
- **5551 claims orphelins** (73%) — pas rattachés à aucune thématique
- **29 facets validées** pour 57 docs = insuffisant (on attendrait 50-100 pour un corpus scientifique)
- **175 facets deprecated** (85% des candidates générées) via `purge_orphan_facets`
- **39 docs sur 57** ont des facets → **18 docs (32%) sans aucune facet validée**

### Liste des 18 docs orphelins
Exemples : SCR_050_2019, SCR_059_2021, EMB_129_2020, ASP_001_2021, DEL_091_2011, CAL_162_2024, MGS_111_2020, ELO_159_2015, EMB_136_2018, DEF_078_2024, ASP_003_2023, CAL_174_2023, DEL_087_2025, MGS_117_2017, EMB_138_2023, MGS_120_2019, ELO_155_2012, CVR_193_2025.

Ces 18 docs contiennent **2799 claims (37% du corpus)** — c'est la majorité des claims orphelines.

## 2. Architecture de l'extraction/matching des Facets

### Phase d'ingestion (ClaimFirst)

Pour chaque document :

1. **FacetCandidateExtractor** (`facet_candidate_extractor.py`) appelle le LLM (Qwen2.5-72B via DeepInfra, TaskType.METADATA_EXTRACTION) avec :
   - Titre doc
   - Échantillon de claims
   - Prompt système demandant d'identifier les thèmes
   - **Cap `MAX_FACETS_PER_DOC`** (défaut 6, configurable via `feature_flags.yaml → claimfirst_pipeline.facet_extraction.max_per_doc`)

2. LLM retourne un JSON avec N facets : `{canonical_name, dimension_key, facet_family, keywords, confidence}`

3. **FacetRegistry** stocke les candidates avec `lifecycle='candidate'`

4. **FacetMatcher** (`facet_matcher.py`) matche les claims du doc aux facets candidates via 4 signaux pondérés :
   - `document_inheritance` (25%) — claim hérite des facets de SON doc
   - `keyword_matching` (35%) — overlap entre claim.text et facet.keywords
   - `section_context` (25%) — facets par section
   - `claimkey_pattern` (15%) — pattern regex
   - Seuil composite : `min_score = 0.3`

5. Les liens `(Claim)-[:BELONGS_TO_FACET]->(Facet)` sont persistés

### Phase post-import (`_run_facets`)

`rebuild_facets.py` refait toute la séquence :
1. **Purge** des anciennes facets (`--purge-old`)
2. **Re-extraction** par doc (LLM)
3. **Consolidation** (dédup near-duplicates par LLM)
4. **Persistance** dans Neo4j
5. **Matching global** : appelle `FacetMatcher.match(claims=ALL, validated_facets=ALL)` **sans `doc_facet_ids`** → FacetMatcher détecte ce mode et bascule sur `_assign_keyword_only` (mode permissif keyword-only, pas de seuil 0.3)

### `purge_orphan_facets`
Déprécie les facets qui :
- `lifecycle='candidate'` (pas encore validées)
- `source_doc_count <= 1`
- 0 claims liés via `BELONGS_TO_FACET`

**Conséquence** : si un doc n'a pas réussi à matcher AUCUN claim à ses propres facets pendant la phase d'ingestion ET que la facet n'est partagée avec aucun autre doc → purgé.

## 3. Causes racines probables (hypothèses)

### Cause 1 — LLM extraction trop conservatrice
Pour chaque doc, le LLM produit 3-5 facets (parfois moins). Le cap 6→12 ne change rien car le LLM ne le remplit pas.

**Preuve** : logs `[OSMOSE:FacetExtractor] N candidates from doc X...` → valeurs constantes 3-5, rarement 6, jamais plus.

**Pourquoi** : le prompt demande "thèmes principaux" → le LLM fait un résumé en top N sans aller dans la granularité.

### Cause 2 — Keywords par facet insuffisants
Chaque facet a typiquement 5-10 keywords. Pour un corpus biomédical où un même concept s'écrit de N façons ("preeclampsia", "pre-eclampsia", "PE", "hypertensive disorder of pregnancy"), 10 keywords ne couvrent pas la variété lexicale.

**Conséquence** : `_assign_keyword_only` a besoin d'au moins 1 keyword multi-mot OU 2 single-word matches. Beaucoup de claims passent à travers.

### Cause 3 — FacetMatcher est INTRA-doc dominant
Les signaux `document_inheritance` (25%) et `section_context` (25%) ne fonctionnent QUE pour les claims d'un doc qui a déjà des facets associées.

**Problème des 18 docs orphelins** : leurs candidates ont été extraites mais n'ont matché aucun claim de leur doc (keyword trop faible), donc :
- 0 claim lié
- source_doc_count = 1 (single-doc)
- → déprécied par purge_orphan_facets

### Cause 4 — Pas de signal embedding
Aucun signal sémantique n'est utilisé. Le matching repose sur :
- Overlap de mots (keyword_matching)
- Regex (claimkey_pattern)
- Transitivité doc/section (inheritance)

Pour un corpus où les claims sont des paraphrases variées d'un concept, l'overlap lexical est insuffisant.

## 4. Ce qui a été essayé (et a échoué)

### Tentative 1 — Bumper `MAX_FACETS_PER_DOC` de 6 à 12
**Résultat** : Aucun effet significatif (19 → 29 facets validées, 27.1% → 27.2% linkage).
**Pourquoi** : le LLM ne remplissait déjà pas le cap à 6. Passer à 12 ne force pas le LLM à être plus granulaire.
**Valeur utile de cette tentative** : le paramètre est maintenant configurable via `feature_flags.yaml` (plus hardcodé). À exposer dans frontend admin plus tard (voir `TODO_ADMIN_UI_CLAIMFIRST_PARAMS.md`).

### Tentative 2 — Passer `doc_facet_ids` dans `rebuild_facets.py`
Hypothèse : le FacetMatcher en post-import n'active pas `document_inheritance`. En passant `doc_facet_ids`, ce signal s'active → plus de matches.

**Résultat** : **EMPIRÉ** — linkage tombé à 15.4%.

**Pourquoi** : en regardant `FacetMatcher.match()` ligne 96 :
```python
is_post_import = not doc_facet_ids and not section_facet_map
```
Le matcher a 2 modes :
- **Post-import mode** (doc_facet_ids=None) → `_assign_keyword_only` **PERMISSIF** (1 multi-word OU 2 single-word matches, pas de seuil composite)
- **Pipeline mode** (doc_facet_ids set) → `assign_claim_to_facets` **STRICT** (seuil composite 0.3, besoin d'au moins 2 signaux forts)

En passant `doc_facet_ids`, j'ai switché en mode strict qui est MOINS permissif sur keyword_matching pur. Le signal inheritance (25%) ne compensait pas la perte du mode permissif.

### Tentative 3 — 2-passes (keyword-only + per-doc)
Hypothèse : union des 2 modes → recall maximal.

**Résultat** : 21.2% (encore pire que l'original 27.1%).

**Pourquoi suspect** :
- La variabilité LLM entre runs (les facets diffèrent à chaque rebuild --purge-old) rend les comparaisons instables.
- Possiblement les logs "Pass 1/Pass 2" n'apparaissaient pas, le code pourrait ne pas avoir tourné comme attendu.

**Revert** : retour au code original `_match_claims_to_facets` avec juste `matcher.match(claims, tenant_id, validated_facets)` sans args supplémentaires. ~27% retrouvé (sujet à variation LLM ±3 pts).

## 5. Pistes de correction propres (chantiers 1-2 jours chacun)

### Piste A — Ajouter un signal `embedding_similarity` au FacetMatcher
**Objectif** : rattraper les claims lexicalement différents mais sémantiquement proches d'une facet.

**Design** :
1. Lors de la création d'une facet, calculer un embedding de `facet.canonical_question` (ou concaténation keywords + canonical_question) via le modèle e5-large
2. Stocker `facet.embedding` (list[float] 1024d)
3. Dans `_assign_keyword_only` et `assign_claim_to_facets`, ajouter un 5ème signal :
   - Cosine similarity entre `claim.embedding` et `facet.embedding`
   - Poids proposé : 30% (en réduisant keyword_matching à 20%)
   - Seuil cosine : 0.75 pour déclencher le signal

**Effort** : ~1j (création embedding facet + intégration dans matcher + re-calcul sur facets existantes)

**Gain estimé** : +15-25 pts de linkage (27% → 45-55%)

### Piste B — Enrichir le prompt d'extraction pour plus de keywords
**Objectif** : forcer le LLM à produire 15-25 keywords par facet (vs 5-10 actuellement).

**Design** :
1. Modifier `SYSTEM_PROMPT` dans `facet_candidate_extractor.py` :
   - "Pour chaque facet, liste 20 keywords couvrant les variations lexicales : synonymes, acronymes, formes longues/courtes, jargon médical..."
2. Augmenter `max_tokens` du call LLM (500 → 1000)
3. Ajouter validation : rejeter les facets avec < 10 keywords

**Effort** : ~2h (prompt + test + re-run)

**Gain estimé** : +5-10 pts (modeste, complémentaire avec Piste A)

### Piste C — Granularité des facets (facets hiérarchiques)
**Objectif** : au lieu de 30 facets larges, avoir une hiérarchie root → sub-facets pour matcher à plusieurs niveaux.

**Design** :
1. Prompt LLM : "Extract 3 root themes + for each root, 3-5 sub-themes"
2. Schéma : `(Facet {role: 'root'})<-[:IS_SUB_FACET_OF]-(Facet {role: 'leaf'})`
3. Matching : un claim peut matcher un leaf OU un root
4. Déjà partiellement supporté via `CanonicalFacetRoot` (non utilisé actuellement, `canonical_roots_created: 0`)

**Effort** : ~2j (refactor modèle + matcher + UI)

**Gain estimé** : +10-20 pts (granularité fine = plus de matches possibles)

### Piste D — Baisser `min_ratio` dans keyword-only
**Objectif** : quick win, gains modestes.

Actuellement : `min_ratio = 0.05`. Baisser à `0.02` capturerait plus de claims mais risque faux positifs.

**Effort** : 10 min (changement 1 ligne + re-run)
**Gain estimé** : +3-5 pts (mais à surveiller faux positifs)

## 6. Questions ouvertes pour l'investigation future

1. **Pourquoi les 18 docs orphelins ont-ils échoué au matching intra-doc pendant ClaimFirst ?**
   Investiguer les logs ingestion de ces docs spécifiquement. Possibles causes :
   - Claims très courts (keyword matching impossible)
   - Facets extraites trop abstraites pour leurs propres claims
   - Bug dans le passage `doc_facet_ids` pendant ingestion

2. **Est-ce que la non-déterminisme LLM est gênant pour les comparaisons ?**
   - Chaque rebuild --purge-old produit des facets différentes (température > 0 par défaut)
   - Envisager `temperature=0` pour reproductibilité
   - Ou seeder

3. **Les facets deprecated restent dans le graph. Utiles ?**
   - Actuellement conservées pour "traçabilité"
   - Peuvent polluer les requêtes si pas filtrées sur `lifecycle != 'deprecated'`
   - Peut-être à nettoyer après 3-6 mois

4. **Le signal `claimkey_pattern` (15%) fonctionne-t-il ?**
   - Basé sur regex via `ClaimKeyPatterns`
   - Statistiques `signals_used.claimkey_pattern` à analyser
   - Si toujours à 0, supprimer ce signal et redistribuer les poids

## 7. Recommandation

**Pour une vraie correction** : combiner **Piste A (embedding) + Piste B (plus de keywords)**. C'est le chemin vers un linkage > 50%. Estimation totale : 1.5 jour de dev + re-run pipeline complet.

**Avant d'implémenter** :
1. Clarifier si le faible linkage est VRAIMENT un problème produit (vs un choix conservateur)
2. Définir la cible quantitative attendue : 50% ? 70% ? 90% ?
3. Établir un jeu de validation manuel : 50 claims annotés avec leurs facets attendues pour mesurer recall + précision après fix

---

## Annexe — État actuel des fichiers concernés

- `src/knowbase/claimfirst/extractors/facet_candidate_extractor.py` : extraction LLM
  - `_MAX_FACETS_PER_DOC_DEFAULT = 6` (défaut)
  - `_get_max_facets_per_doc()` lit `feature_flags.yaml`
- `src/knowbase/claimfirst/linkers/facet_matcher.py` : matching
  - `DEFAULT_MIN_SCORE = 0.3`
  - `DEFAULT_WEIGHTS` : doc_inheritance 25%, keyword 35%, section 25%, claimkey 15%
- `app/scripts/rebuild_facets.py` : post-import rebuild
  - `_match_claims_to_facets` : appel global keyword-only (post-import mode)
- `src/knowbase/api/routers/post_import.py` :
  - `_run_facets` → subprocess vers rebuild_facets.py
  - `_run_facet_consolidate` → subprocess vers consolidate_facet_roots.py
  - `_run_purge_orphan_facets` → Cypher direct

## Annexe — Commandes de diagnostic utiles

```bash
# Linkage actuel
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain \
  "MATCH (c:Claim {tenant_id: 'default'})-[:BELONGS_TO_FACET]->(f:Facet) \
   WHERE f.lifecycle <> 'deprecated' \
   RETURN count(DISTINCT c) AS linked, 7627 AS total"

# Facets par lifecycle
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain \
  "MATCH (f:Facet {tenant_id: 'default'}) RETURN f.lifecycle, count(f)"

# Docs sans facet
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain \
  "MATCH (dc:DocumentContext {tenant_id: 'default'}) \
   WITH collect(dc.doc_id) AS all_docs \
   MATCH (f:Facet {tenant_id: 'default', lifecycle: 'validated'}) \
   UNWIND f.source_doc_ids AS did \
   WITH all_docs, collect(DISTINCT did) AS facet_docs \
   RETURN [d IN all_docs WHERE NOT d IN facet_docs] AS orphans"

# Distribution signaux FacetMatcher (après run)
docker logs knowbase-worker | grep "OSMOSE:FacetMatcher"
```
