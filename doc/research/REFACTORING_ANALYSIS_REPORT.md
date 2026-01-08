# Rapport d'Analyse - Refactoring pptx_pipeline.py

**Date:** 2025-11-17
**Commit refactoring:** `269be4c` - "refactor(ingestion): Modulariser pptx_pipeline.py en composants réutilisables"

## Résumé Exécutif

Analyse comparative systématique entre l'ancien monolithe `pptx_pipeline.py` et la nouvelle architecture modulaire.

**Résultat:** 3 bugs critiques détectés et corrigés.

---

## 🔴 BUGS CRITIQUES DÉTECTÉS

### 1. ❌ Extraction MegaParse - Division par regex au lieu de lignes

**Fichier:** `src/knowbase/ingestion/components/extractors/binary_parser.py`
**Fonction:** `extract_slides_from_megaparse()` et `split_megaparse_by_slide_count()`

**Problème:**
- **Ancien code (fonctionnel):** Division proportionnelle du contenu MegaParse en N parties égales par **lignes**
- **Nouveau code (cassé):** Recherche de patterns regex (`---`, `Slide X`, `Page X`) qui n'existent PAS dans l'output MegaParse
- **Impact:** Extraction de seulement 1 slide au lieu de 94, perte de 99% du contenu

**Correction appliquée:**
```python
# AVANT (cassé)
slide_pattern = r"(?:^|\n)(?:---+|Slide\s+\d+|Page\s+\d+)"
parts = re.split(slide_pattern, content)  # Ne trouve rien !

# APRÈS (restauré)
content_lines = content.split("\n")
lines_per_slide = len(content_lines) // slide_count
for slide_num in range(1, slide_count + 1):
    start_line = (slide_num - 1) * lines_per_slide
    end_line = slide_num * lines_per_slide if slide_num < slide_count else len(content_lines)
    slide_content = "\n".join(content_lines[start_line:end_line])
```

**Status:** ✅ CORRIGÉ (restauration logique originale)

---

### 2. ❌ clean_gpt_response - Suppression logique réparation JSON tronqué

**Fichier:** `src/knowbase/ingestion/components/utils/text_utils.py`
**Fonction:** `clean_gpt_response()`

**Problème:**
- **Ancien code (robuste):** 60 lignes avec réparation automatique de JSON tronqué (timeout LLM, réponse incomplète)
- **Nouveau code (fragile):** Extraction simple regex sans réparation
- **Impact:** Échec parsing JSON lors de timeouts LLM → perte de concepts extraits

**Logique supprimée:**
- Détection JSON tronqué au milieu d'une string (`s.endswith('"')`)
- Détection JSON tronqué après virgule (`s.endswith(',')`)
- Fermeture automatique des brackets manquants (`]`, `}`)
- Retry avec validation JSON après réparation

**Correction appliquée:**
```python
# Restauration COMPLÈTE de la logique originale
# - Validation JSON (json.loads())
# - Réparation automatique selon patterns détectés
# - Fallback vers "[]" si irréparable
# - Logging détaillé des tentatives
```

**Status:** ✅ CORRIGÉ (restauration logique complète + ajout paramètre logger optionnel)

---

### 3. ❌ recursive_chunk - Découpage caractères au lieu de tokens

**Fichier:** `src/knowbase/ingestion/components/utils/text_utils.py`
**Fonction:** `recursive_chunk()`

**Problème:**
- **Ancien code (correct):** Découpage par **TOKENS** (mots) - respecte les limites LLM
- **Nouveau code (incorrect):** Découpage par **CARACTÈRES** - ne respecte plus max_tokens
- **Impact:** Possibles dépassements de tokens LLM, chunking incorrect des concepts longs

**Exemple d'impact:**
```python
text = "mot " * 1000  # 1000 tokens

# ANCIEN (correct)
chunks = recursive_chunk(text, max_len=400)  # 3 chunks de ~400 tokens
# → Compatible max_tokens LLM

# NOUVEAU (cassé)
chunks = recursive_chunk(text, max_len=400)  # ~10 chunks de ~400 CHARS
# → Découpage trop fin, perte de contexte
```

**Correction appliquée:**
```python
# AVANT (cassé)
chunks.append(text[start:end])  # Découpage par INDEX de caractères

# APRÈS (restauré)
tokens = text.split()
chunk = tokens[i : i + max_len]
chunks.append(" ".join(chunk))  # Découpage par TOKENS (mots)
```

**Status:** ✅ CORRIGÉ (restauration logique tokens)

---

## ✅ COMPOSANTS VÉRIFIÉS SANS MODIFICATIONS

### Extraction
| Fonction | Fichier | Status |
|----------|---------|--------|
| `extract_notes_and_text()` | binary_parser.py | ✅ Identique |
| `extract_with_python_pptx()` | binary_parser.py | ✅ Identique (tables + charts) |

### Vision Processing
| Fonction | Fichier | Status |
|----------|---------|--------|
| `ask_gpt_slide_analysis()` | vision_analyzer.py | ✅ Identique (prompt rendering, LLM call, JSON parsing) |
| Image encoding base64 | vision_analyzer.py | ✅ Identique |
| Heartbeat worker | vision_analyzer.py | ✅ Identique |

### Utils
| Fonction | Fichier | Status |
|----------|---------|--------|
| `get_language_iso2()` | text_utils.py | ✅ Identique |
| `estimate_tokens()` | text_utils.py | ✅ Identique |

---

## 📊 Synthèse des Modifications Refactoring

### Modifications Intentionnelles (OK)
- Modularisation architecture (composants séparés)
- Ajout paramètres optionnels (logger, llm_router, prompt_registry)
- Ajout docstrings détaillées
- Export fonctions via `__init__.py`

### Modifications Non-Intentionnelles (BUGS)
1. ❌ Changement logique extraction MegaParse (regex vs lignes)
2. ❌ Suppression réparation JSON tronqué
3. ❌ Changement chunking tokens → caractères

---

## 🔄 Actions Correctives Appliquées

### 1. binary_parser.py
- ✅ Restauré fonction `split_megaparse_by_slide_count()` avec logique lignes
- ✅ Ajouté commentaire "LOGIQUE ORIGINALE (éprouvée)"
- ✅ Conservé approche hybride (python-pptx pour count + MegaParse pour contenu)

### 2. text_utils.py - clean_gpt_response
- ✅ Restauré 60 lignes logique réparation JSON
- ✅ Ajouté paramètre `logger` optionnel
- ✅ Conservé gestion erreurs robuste

### 3. text_utils.py - recursive_chunk
- ✅ Restauré découpage par tokens (`.split()`)
- ✅ Mis à jour docstring (préciser "TOKENS/mots" vs "caractères")
- ✅ Conservé signature fonction identique

---

## 🧪 Tests Recommandés

### Test 1: Extraction 94 slides
```bash
docker exec knowbase-worker python -c "
from pathlib import Path
from knowbase.ingestion.components.extractors.binary_parser import extract_notes_and_text
slides = extract_notes_and_text(Path('/data/docs_done/SAP_S4HANA_Cloud__public_edition-Security_and_Compliance__20251117_161407.pptx'), None)
assert len(slides) == 94, f'Expected 94 slides, got {len(slides)}'
print('✅ Extraction OK: 94 slides')
"
```

### Test 2: Réparation JSON tronqué
```python
from knowbase.ingestion.components.utils.text_utils import clean_gpt_response

# JSON tronqué au milieu d'une string
truncated = '{"concepts": [{"name": "SAP S/4HANA'
result = clean_gpt_response(truncated)
assert result == "[]"  # Fallback array vide

# JSON tronqué avec bracket manquant
truncated = '{"concepts": [{"name": "test"}'
result = clean_gpt_response(truncated)
# Devrait réparer en ajoutant ]}
```

### Test 3: Chunking par tokens
```python
from knowbase.ingestion.components.utils.text_utils import recursive_chunk

text = " ".join(["word"] * 1000)  # 1000 tokens
chunks = recursive_chunk(text, max_len=400, overlap_ratio=0.15)

# Vérifier nombre de chunks
assert len(chunks) == 3, f"Expected 3 chunks, got {len(chunks)}"

# Vérifier taille chunks (en tokens)
for chunk in chunks:
    token_count = len(chunk.split())
    assert token_count <= 400, f"Chunk exceeds max_len: {token_count} tokens"
```

---

## 📝 Recommandations

### Court Terme
1. ✅ **Rebuild worker avec corrections** (en cours)
2. 🔄 **Test import complet** d'un document 94 slides
3. 🔄 **Vérifier logs** pour JSON repairs et chunking

### Moyen Terme
1. **Tests unitaires** pour `clean_gpt_response()` (cas JSON tronqué)
2. **Tests unitaires** pour `recursive_chunk()` (découpage tokens)
3. **Tests d'intégration** extraction MegaParse (nombre slides)

### Long Terme
1. **CI/CD checks** avant merge refactoring
2. **Tests de régression** automatisés
3. **Validation outputs** avant/après refactoring

---

## 🎯 Conclusion

**3 bugs critiques** identifiés et corrigés lors de l'analyse comparative post-refactoring :

1. ✅ Extraction MegaParse (1 slide → 94 slides)
2. ✅ Réparation JSON tronqué (robustesse LLM timeouts)
3. ✅ Chunking par tokens (respect max_tokens LLM)

La modularisation architecturale reste valide, mais la **logique métier originale** a été restaurée pour garantir la stabilité du pipeline.

**Prochaine étape:** Test import complet avec les corrections appliquées.
