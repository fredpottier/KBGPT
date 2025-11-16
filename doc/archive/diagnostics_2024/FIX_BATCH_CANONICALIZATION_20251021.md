# Fix Batch Canonicalization - 2025-10-21

**Date** : 2025-10-21 01:40
**Commit** : 7efaa59
**Status** : ✅ DÉPLOYÉ - PRÊT POUR TEST UTILISATEUR

---

## 📋 Résumé Exécutif

**Problème Identifié** : La méthode `canonicalize_batch()` était appelée par `gatekeeper.py:720` mais **n'existait pas** dans `llm_canonicalizer.py`, causant un `AttributeError` masqué par l'erreur "All JSON parsing attempts failed".

**Solution Implémentée** : Ajout complet de la méthode `canonicalize_batch()` avec 216 lignes de code incluant :
- Traitement batch de 20 concepts par appel LLM
- Diagnostic logging raw LLM response (1000 premiers caractères)
- Fallback robuste per-concept ET global
- Intégration circuit breaker pour résilience

**Impact Attendu** :
- ✅ Réduction 547 appels LLM → 28 batch calls (20 concepts/batch)
- ✅ Temps canonicalization : 18 min → < 1 min
- ✅ Concepts avec `canonical_name=None` : 100 (18%) → 0 (0%)
- ✅ Coût LLM : $0.82 → $0.084 (10x moins cher)

---

## 🔧 Modifications Techniques

### Fichier : `src/knowbase/ontology/llm_canonicalizer.py`

#### 1. Méthode `canonicalize_batch()` (lignes 254-388)

```python
def canonicalize_batch(
    self,
    concepts: List[Dict[str, str]],
    timeout: int = 30
) -> List[CanonicalizationResult]:
    """
    Canonicalise un batch de concepts via LLM (batch processing).

    Args:
        concepts: Liste de dicts avec clés {raw_name, context, domain_hint}
        timeout: Timeout max LLM call en secondes

    Returns:
        Liste de CanonicalizationResult (même ordre que concepts)
    """
    if not concepts:
        return []

    logger.debug(
        f"[LLMCanonicalizer:Batch] Canonicalizing batch of {len(concepts)} concepts"
    )

    # Construire prompt batch
    prompt = self._build_batch_canonicalization_prompt(concepts)

    try:
        # P0: Appel LLM via circuit breaker
        def _llm_call():
            from knowbase.common.llm_router import TaskType

            # Appel LLM via router
            response_content = self.llm_router.complete(
                task_type=TaskType.CANONICALIZATION,
                messages=[
                    {"role": "system", "content": CANONICALIZATION_BATCH_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                response_format={"type": "json_object"}
            )

            # Fix 2025-10-21: Log RAW response for diagnostic
            logger.info(
                f"[LLMCanonicalizer:Batch] 🔍 RAW LLM response (first 1000 chars):\n"
                f"{response_content[:1000]}"
            )

            # Parse résultat JSON
            result_json = self._parse_json_robust(response_content)

            # Extraire résultats pour chaque concept
            results = []
            concepts_results = result_json.get("concepts", [])

            for idx, concept_result in enumerate(concepts_results):
                try:
                    results.append(CanonicalizationResult(**concept_result))
                except Exception as e:
                    logger.error(
                        f"[LLMCanonicalizer:Batch] Failed to parse result {idx}: {e}, "
                        f"using fallback for '{concepts[idx]['raw_name']}'"
                    )
                    # Fallback pour ce concept
                    results.append(CanonicalizationResult(
                        canonical_name=concepts[idx]["raw_name"].strip().title(),
                        confidence=0.5,
                        reasoning="Batch parsing failed, fallback to title case",
                        aliases=[],
                        concept_type="Unknown",
                        domain=None,
                        ambiguity_warning="Batch canonicalization partial failure",
                        possible_matches=[],
                        metadata={"error": str(e)}
                    ))

            return results

        # Appel via circuit breaker
        results = self.circuit_breaker.call(_llm_call)

        logger.info(
            f"[LLMCanonicalizer:Batch] ✅ Batch completed: {len(results)} concepts canonicalized"
        )

        return results

    except Exception as e:
        logger.error(
            f"[LLMCanonicalizer:Batch] ❌ Batch canonicalization failed: {e}, "
            f"falling back to individual processing"
        )

        # Fallback global : appel individuel pour chaque concept
        results = []
        for concept in concepts:
            try:
                individual_result = self.canonicalize(
                    raw_name=concept.get("raw_name", ""),
                    context=concept.get("context"),
                    domain_hint=concept.get("domain_hint")
                )
                results.append(individual_result)
            except Exception as fallback_error:
                logger.error(
                    f"[LLMCanonicalizer:Batch] Fallback failed for '{concept.get('raw_name')}': {fallback_error}"
                )
                # Dernier fallback : title case
                results.append(CanonicalizationResult(
                    canonical_name=concept.get("raw_name", "Unknown").strip().title(),
                    confidence=0.3,
                    reasoning="Batch and individual canonicalization failed",
                    aliases=[],
                    concept_type="Unknown",
                    domain=None,
                    ambiguity_warning="Complete failure, using title case",
                    possible_matches=[],
                    metadata={"error": str(e), "fallback_error": str(fallback_error)}
                ))

        return results
```

**Points Clés** :
- ✅ Logging diagnostic raw LLM response (ligne 305-308)
- ✅ Fallback per-concept si JSON parsing échoue pour un concept spécifique
- ✅ Fallback global vers individual processing si batch échoue complètement
- ✅ Circuit breaker integration pour résilience API
- ✅ Retour des résultats dans le MÊME ORDRE que les concepts input

#### 2. Méthode `_build_batch_canonicalization_prompt()` (lignes 390-429)

```python
def _build_batch_canonicalization_prompt(
    self,
    concepts: List[Dict[str, str]]
) -> str:
    """Construit prompt batch pour LLM."""
    concept_lines = []

    for idx, concept in enumerate(concepts, 1):
        raw_name = concept.get("raw_name", "")
        context = concept.get("context", "")
        domain_hint = concept.get("domain_hint")

        line = f"{idx}. **Name:** {raw_name}"

        if context:
            context_snippet = self._truncate_context(context, max_length=200)
            line += f" | **Context:** {context_snippet}"

        if domain_hint:
            line += f" | **Domain:** {domain_hint}"

        concept_lines.append(line)

    concepts_text = "\n".join(concept_lines)

    return f"""
**Task:** Canonicalize the following {len(concepts)} concepts.

{concepts_text}

Return a JSON object with format:
{{
  "concepts": [
    {{"canonical_name": "...", "confidence": 0.95, "reasoning": "...", ...}},
    ...
  ]
}}

IMPORTANT: Return results in SAME ORDER as input (1-{len(concepts)}).
"""
```

**Points Clés** :
- ✅ Truncation du contexte à 200 chars par concept pour économiser tokens
- ✅ Format numéroté clair pour tracking ordre
- ✅ Instructions explicites pour retourner dans le même ordre

#### 3. Prompt Système Batch (lignes 634-671)

```python
CANONICALIZATION_BATCH_SYSTEM_PROMPT = """You are a concept canonicalization expert specialized in batch processing.

Your task is to find the OFFICIAL CANONICAL NAME for multiple concepts extracted from documents.

# Guidelines (same as single canonicalization)

1. **Official Names**: Use official product/company/standard names
2. **Acronyms**: Expand acronyms to full official names
3. **Possessives**: Remove possessive forms ('s, 's)
4. **Casing**: Preserve official casing
5. **Variants**: List common aliases/variants
6. **Ambiguity**: If uncertain, set ambiguity_warning and list possible_matches
7. **Type Detection**: Classify concept type

# Batch Output Format (JSON)

{
  "concepts": [
    {
      "canonical_name": "Official name 1",
      "confidence": 0.95,
      "reasoning": "Brief explanation",
      "aliases": ["variant1", "variant2"],
      "concept_type": "Product|Acronym|...",
      "domain": "enterprise_software|...",
      "ambiguity_warning": null,
      "possible_matches": [],
      "metadata": {}
    },
    {
      "canonical_name": "Official name 2",
      ...
    }
  ]
}

CRITICAL: Return results in SAME ORDER as input concepts. The array "concepts" must have EXACTLY the same number of elements as the input.
"""
```

**Points Clés** :
- ✅ Mêmes guidelines que canonicalization individuelle
- ✅ Format JSON strict pour batch processing
- ✅ Emphasis sur l'ordre des résultats

---

## 🎯 Design Système (Clarification Utilisateur)

### Fonctionnement Attendu du Batch Processing

**Phase 1 : Check Ontology Dictionaries**
```python
# gatekeeper.py - Avant batch LLM
for concept_name in extracted_concepts:
    if concept_name in adaptive_ontology_cache:
        canonical_name = adaptive_ontology_cache[concept_name]
        # Pas d'appel LLM nécessaire
    else:
        # Ajouter au batch pour LLM call
        batch_for_llm.append(concept_name)
```

**Phase 2 : Batch LLM Call**
```python
# Batch processing : 20 concepts par call
# Exemple : 100 concepts → 5 batch calls (au lieu de 100 individual calls)
batches = chunk_list(batch_for_llm, batch_size=20)
for batch in batches:
    results = llm_canonicalizer.canonicalize_batch(batch)
    # 1 appel LLM traite 20 concepts
```

**Phase 3 : Store Results in Ontology**
```python
# Stocker résultats dans Redis pour futurs imports
for concept_name, canonical_name in results:
    adaptive_ontology_manager.store(concept_name, canonical_name)
```

### Évolution Progressive

**Premier Import (Système Vierge)** :
- Ontology cache vide → 100% concepts envoyés au LLM
- 547 concepts → 28 batch calls (20 concepts/batch)
- Temps : ~56 secondes (28 × 2s)
- Coût : ~$0.084 (28 × $0.003)

**Deuxième Import (Ontology Partielle)** :
- Ontology cache contient 300 concepts connus
- 547 concepts - 300 cached = 247 concepts → 13 batch calls
- Temps : ~26 secondes (13 × 2s)
- Coût : ~$0.039 (13 × $0.003)

**Après 5-10 Imports (Ontology Mature)** :
- Ontology cache contient 80% concepts courants
- 547 concepts - 437 cached = 110 concepts → 6 batch calls
- Temps : ~12 secondes (6 × 2s)
- Coût : ~$0.018 (6 × $0.003)

**Objectif** : Réduire progressivement les appels LLM via apprentissage ontologique.

---

## 📊 Métriques Avant/Après

| Métrique | Avant Fix | Après Fix (Attendu) |
|----------|-----------|---------------------|
| **Méthode existe** | ❌ Non (AttributeError) | ✅ Oui (216 lignes) |
| **Batch calls** | 0 (erreur) | 28 (20 concepts/batch) |
| **Temps canonicalization** | 18 min (547 individual) | < 1 min (28 batch) |
| **Concepts canonical_name=None** | 100 (18%) | 0 (0%) |
| **Coût LLM** | $0.82 (547 calls) | $0.084 (28 calls) |
| **JSON parsing success** | 0% (erreur) | 100% (attendu) |
| **Diagnostic logging** | ❌ Non | ✅ Oui (raw response) |
| **Fallback robustesse** | ❌ Non | ✅ Per-concept + global |

---

## 🧪 Instructions Test Utilisateur

### Prérequis
- ✅ Worker rebuilded avec commit 7efaa59
- ✅ Worker redémarré (`docker-compose restart ingestion-worker`)
- ✅ Monitoring logs en cours (background bash 7d215c)

### Étapes Test

1. **Aller sur l'interface d'import** :
   ```
   http://localhost:3000/documents/import
   ```

2. **Uploader un document** (PPTX ou PDF) :
   - Exemple : RISE_with_SAP_Cloud_ERP_Private.pptx
   - Ou tout autre document de test

3. **Observer les logs en temps réel** :
   Les logs suivants devraient apparaître dans le terminal de monitoring :

   **Logs Batch Processing** :
   ```
   [GATEKEEPER:Batch] 🔄 Batch canonicalizing 547 concepts (batch_size=20)...
   [LLMCanonicalizer:Batch] Canonicalizing batch of 20 concepts
   [LLMCanonicalizer:Batch] 🔍 RAW LLM response (first 1000 chars):
   {
     "concepts": [
       {"canonical_name": "Content Owner", "confidence": 0.95, ...},
       ...
     ]
   }
   [LLMCanonicalizer:Batch] ✅ Batch completed: 20 concepts canonicalized
   ```

   **Logs Attendus (Succès)** :
   - `[GATEKEEPER:Batch]` : Démarrage batch processing
   - `[LLMCanonicalizer:Batch]` : Logs de la nouvelle méthode
   - `🔍 RAW LLM response` : Diagnostic logging du JSON retourné
   - `✅ Batch completed: X concepts` : Confirmation succès
   - **PAS de** `canonical_name.*None` warnings
   - **PAS de** `AttributeError` errors

4. **Vérifier résultats Neo4j** :
   ```bash
   docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain \
     "MATCH (c:CanonicalConcept) WHERE c.tenant_id = 'default' RETURN c.canonical_name, c.surface_form LIMIT 20"
   ```

   **Attendu** :
   - 0 concepts avec `canonical_name = null`
   - Tous les concepts ont un `canonical_name` valide

5. **Vérifier métriques de performance** :
   - Temps total canonicalization : < 1 min (au lieu de 18 min)
   - Nombre de batch calls : ~28 (affichés dans logs)
   - 0 warnings "canonical_name is None"

### Logs en Temps Réel

Un monitoring est actif en arrière-plan (bash 7d215c) qui filtre les logs pertinents :
- `[LLMCanonicalizer:Batch]`
- `[GATEKEEPER:Batch]`
- `Batch canonicalizing`
- `RAW LLM response`
- `canonical_name.*None`
- `AttributeError`

---

## 🔍 Troubleshooting

### Si AttributeError Persiste

**Symptôme** :
```
AttributeError: 'LLMCanonicalizer' object has no attribute 'canonicalize_batch'
```

**Cause** : Worker pas encore rebuilded avec nouvelle version

**Solution** :
```bash
docker-compose build ingestion-worker
docker-compose restart ingestion-worker
```

### Si JSON Parsing Échoue

**Symptôme** :
```
[LLMCanonicalizer:Batch] ❌ Batch canonicalization failed: All JSON parsing attempts failed
```

**Diagnostic** :
1. Chercher log `🔍 RAW LLM response` dans les logs
2. Vérifier le JSON retourné par LLM
3. Vérifier si le format correspond au schéma attendu

**Logs à capturer** :
```bash
docker-compose logs ingestion-worker | grep "RAW LLM response" -A 50
```

### Si Fallback Individuel Activé

**Symptôme** :
```
[GATEKEEPER:Canonicalization:Batch] ⚠️ Cache MISS for 'Content Owner', fallback to individual LLM call
```

**Interprétation** :
- **NORMAL** si batch LLM parsing a échoué pour certains concepts
- Fallback individuel assure que tous les concepts sont canonicalisés
- Vérifier pourquoi batch parsing a échoué (voir section précédente)

---

## 📝 Prochaines Étapes

Après validation du test utilisateur :

1. **Si succès** :
   - ✅ Marquer Phase A.2 complétée
   - ⏭️ Passer à Phase B.5 : Fixer `surface_forms` pour Phase 2
   - 📊 Documenter métriques réelles observées

2. **Si échec batch parsing** :
   - 🔍 Analyser raw LLM response
   - 🔧 Ajuster prompt système ou parser JSON
   - ⏭️ Passer à Phase A.4 : Fixer parser JSON + améliorer prompt

3. **Optimisations futures (Phase A.5-A.7)** :
   - Fuzzy deduplication (85% similarity)
   - Mise à jour schéma Neo4j pour stocker `aliases` (liste)
   - Mise à jour Redis ontology pour stocker `aliases`

---

## 🎯 Validation Checklist

- [ ] Worker rebuilded avec commit 7efaa59
- [ ] Worker redémarré et actif
- [ ] Monitoring logs actif (bash 7d215c)
- [ ] Upload test document via http://localhost:3000
- [ ] Logs batch processing visibles
- [ ] Logs raw LLM response visibles
- [ ] 0 concepts avec `canonical_name=None`
- [ ] Temps canonicalization < 1 min
- [ ] ~28 batch calls observés (pour 547 concepts)
- [ ] Concepts visibles dans Neo4j avec canonical_name valide

---

**Créé par** : Claude Code
**Pour** : Fix critique batch canonicalization
**Priorité** : 🔴 CRITIQUE
**Status** : ✅ DÉPLOYÉ - EN ATTENTE TEST UTILISATEUR
**Commit** : 7efaa59 - "feat(canonicalization): Implement missing canonicalize_batch() method with diagnostic logging"
