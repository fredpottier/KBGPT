# Spec: Vision Anchor Resolution Fix

**Date:** 26/01/2026
**Statut:** Implémenté
**Auteur:** Claude + ChatGPT diagnostic

---

## Problème Identifié

### Symptôme
- Anchor resolution: **17.9%** (149/831)
- Cible: >80%

### Diagnostic
1. **52% des assertions sont en FRANÇAIS** alors que le document est en ANGLAIS
2. Les assertions FR ne peuvent **jamais** matcher les DocItems EN
3. Cause: Le prompt `VISION_SEMANTIC_SYSTEM_PROMPT` était en français

### Impact Quantifié

| Langue | Assertions | Anchor OK | Taux |
|--------|------------|-----------|------|
| Anglais | 386 | 149 | 38.6% |
| Français | 420 | 0 | 0% |
| **Global** | 831 | 149 | **17.9%** |

---

## Corrections Apportées

### 1. Prompt Vision (`semantic_reader.py`)

**Avant (v1.0):**
```python
VISION_SEMANTIC_SYSTEM_PROMPT = """Tu es un expert en analyse de documents techniques.
Ta tâche : décrire le contenu visuel de manière FACTUELLE et OBSERVABLE.
...
"""
```

**Après (v2.0):**
```python
VISION_SEMANTIC_SYSTEM_PROMPT = """You are a technical document analysis expert.
Your task: describe visual content in a FACTUAL and OBSERVABLE manner.

CRITICAL LANGUAGE RULE:
- You MUST write your description in the SAME LANGUAGE as the visible text
- If the document/slide is in English, write your description in English
- NEVER translate - use the same language as the source

...
RESPONSE FORMAT (JSON):
{
  ...
  "exact_quotes": ["verbatim text from image", ...],
  "detected_language": "en|fr|de|es|other",
  ...
}
```

### 2. Nouveaux Enums (`assertion_v1.py`)

**RuleUsed:**
```python
LANG_MISMATCH_REJECT = "LANG_MISMATCH_REJECT"
NO_EXTRACTIVE_EVIDENCE = "NO_EXTRACTIVE_EVIDENCE"
VISION_SYNTHETIC_REJECT = "VISION_SYNTHETIC_REJECT"
```

**AbstainReason:**
```python
LANG_MISMATCH = "LANG_MISMATCH"
NO_EXTRACTIVE_QUOTE = "NO_EXTRACTIVE_QUOTE"
VISION_ONLY_CONTENT = "VISION_ONLY_CONTENT"
```

### 3. Nouveaux Champs (`VisionSemanticResult`)

```python
exact_quotes: List[str]  # Verbatim text for anchoring
detected_language: str   # "en", "fr", etc.
```

---

## Checklist de Validation

### Test 1: Vérifier la distribution linguistique après fix

```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (mvp:InformationMVP)
WITH mvp.text as text,
     CASE
       WHEN text CONTAINS ' est ' OR text CONTAINS ' sont '
            OR text STARTS WITH 'Le ' OR text STARTS WITH 'La '
       THEN 'FR'
       ELSE 'EN'
     END as lang
RETURN lang, count(text) as count
ORDER BY count DESC
"
```

**Attendu après fix:**
- FR: <10% (résiduel de contenu source bilingue)
- EN: >90%

### Test 2: Vérifier le nouveau taux d'anchor

```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (mvp:InformationMVP) WITH count(mvp) as total
MATCH (i:Information) WITH total, count(i) as resolved
RETURN resolved, total, toFloat(resolved)/total * 100 as anchor_rate_pct
"
```

**Attendu après fix:**
- Anchor rate: >35% (vs 17.9% avant)

### Test 3: Vérifier les exact_quotes

```bash
# Après un nouveau run, vérifier que exact_quotes sont présents
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (mvp:InformationMVP)
WHERE mvp.exact_quote IS NOT NULL AND mvp.exact_quote <> ''
RETURN count(mvp) as with_quote
"
```

**Attendu:**
- with_quote: >50% des assertions Vision

---

## Procédure de Test Complet

1. **Purger Neo4j:**
```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  "MATCH (n) WHERE NOT n:OntologyAlias AND NOT n:OntologyEntity DETACH DELETE n"
```

2. **Redémarrer le container:**
```bash
docker compose -f docker-compose.infra.yml -f docker-compose.yml restart app
```

3. **Relancer le reprocessing:**
```bash
curl -s -X POST "http://localhost:8000/api/v2/reprocess/start" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "default", "run_pass2": true}'
```

4. **Monitorer les logs:**
```bash
docker compose -f docker-compose.infra.yml -f docker-compose.yml logs app -f | grep OSMOSE
```

5. **Exécuter les 3 tests de validation ci-dessus**

---

## Résultats Attendus

| Métrique | Avant Fix | Après Fix (estimé) |
|----------|-----------|-------------------|
| Assertions FR | 52% | <10% |
| Anchor rate global | 17.9% | >35% |
| Anchor rate EN-only | 38.6% | >50% |

---

## Fichiers Modifiés

1. `src/knowbase/extraction_v2/vision/semantic_reader.py`
   - Prompt v1.0 → v2.0 (EN, same-language, exact_quotes)
   - VisionSemanticResult: +exact_quotes, +detected_language

2. `src/knowbase/stratified/models/assertion_v1.py`
   - RuleUsed: +LANG_MISMATCH_REJECT, +NO_EXTRACTIVE_EVIDENCE, +VISION_SYNTHETIC_REJECT
   - AbstainReason: +LANG_MISMATCH, +NO_EXTRACTIVE_QUOTE, +VISION_ONLY_CONTENT

---

## Prochaines Étapes (Post-Validation)

1. [ ] Implémenter le garde-fou `LANG_MISMATCH_REJECT` dans promotion_engine.py
2. [ ] Implémenter la vérification `exact_quote` pour anchor resolution
3. [ ] Investiguer le 61% restant (EN mais anchor failed) - paraphrase vs extraction

---

*Spec créée le 26/01/2026*
