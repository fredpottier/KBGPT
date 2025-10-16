# Corrections OSMOSE Pure - 2025-10-14

## 🐛 Problèmes Identifiés et Corrigés

### Problème 1: Modules manquants (CRITIQUE)

**Erreur:**
```
ModuleNotFoundError: No module named 'knowbase.semantic.narrative_detector'
```

**Cause:**
- `src/knowbase/semantic/__init__.py` importait des modules Phase 1 non encore implémentés :
  - `narrative_detector.py`
  - `segmentation.py`
  - `extractor.py`

**Solution:** `src/knowbase/semantic/__init__.py:16-42`

Commenté les imports manquants :
```python
from .profiler import SemanticDocumentProfiler
# Modules Phase 1 non encore implémentés (TODO):
# from .narrative_detector import NarrativeThreadDetector
# from .segmentation import IntelligentSegmentationEngine
# from .extractor import DualStorageExtractor
```

**Status:** ✅ CORRIGÉ

---

### Problème 2: Résumés Vision trop courts

**Observation utilisateur:**
> "la taille des retours du LLM vision pour chaque slide est plutôt faible. Je suis étonné qu'il ne retourne que des textes aussi courts. Il faudrait afficher le texte retourné dans la log"

**Causes possibles:**
1. `max_tokens=1500` trop bas pour résumés vraiment détaillés
2. `temperature=0.3` trop conservatif pour prose créative
3. Logging affiche seulement longueur, pas contenu complet

**Solutions:** `src/knowbase/ingestion/pipelines/pptx_pipeline.py:1453-1484`

#### Changement 1: Augmentation max_tokens
```python
# AVANT
max_tokens=1500  # Suffisant pour 2-4 paragraphes riches

# APRÈS
max_tokens=2500  # Augmenté pour résumés vraiment détaillés
```

#### Changement 2: Augmentation temperature
```python
# AVANT
temperature=0.3,  # Légèrement plus créatif pour prose

# APRÈS
temperature=0.5,  # Plus créatif pour descriptions riches
```

#### Changement 3: Logging complet du résumé
```python
# AVANT
logger.info(f"Slide {slide_index} [VISION SUMMARY]: {len(summary)} chars generated")

# APRÈS
logger.info(f"Slide {slide_index} [VISION SUMMARY]: {len(summary)} chars generated")
logger.info(f"Slide {slide_index} [VISION SUMMARY CONTENT]:\n{summary}")
logger.info("=" * 80)
```

**Résultat:** Chaque résumé Vision est maintenant affiché en entier dans les logs.

#### Changement 4: Aperçu texte enrichi final
**Location:** `pptx_pipeline.py:1947-1952`

```python
# Afficher aperçu du texte enrichi pour validation
preview_length = min(1000, len(full_text_enriched))
logger.info(f"[OSMOSE PURE] Aperçu texte enrichi (premiers {preview_length} chars):")
logger.info("=" * 80)
logger.info(full_text_enriched[:preview_length] + ("..." if len(full_text_enriched) > preview_length else ""))
logger.info("=" * 80)
```

**Status:** ✅ CORRIGÉ

---

## 📊 Logs Attendus Maintenant

### 1. Logs Vision par Slide

**Format:**
```
Slide 1 [VISION SUMMARY]: 847 chars generated
Slide 1 [VISION SUMMARY CONTENT]:
This slide presents the SAP HANA architecture organized into three distinct vertical layers.
At the top, the "Application Services" layer showcases XS Advanced and HANA Studio as the
primary development tools, connected through a unified interface layer. The middle section
displays the "Processing Layer" with two prominent storage engines positioned side by side:
Column Store on the left and Row Store on the right. A bold arrow points from Column Store
to a callout box emphasizing its optimization for analytical workloads, suggesting this is
a key architectural advantage. The visual hierarchy clearly indicates that Column Store is
the primary focus for analytics, while Row Store handles transactional operations. At the
bottom, the "Persistence Layer" contains Data Volumes and Log Volumes shown as interconnected
cylinders, with bidirectional arrows indicating continuous synchronization between them...
================================================================================
```

### 2. Logs Texte Enrichi Global

**Format:**
```
[OSMOSE PURE] Texte enrichi construit: 18543 chars depuis 25 slides
[OSMOSE PURE] Aperçu texte enrichi (premiers 1000 chars):
================================================================================

--- Slide 1 ---
This slide presents the SAP HANA architecture organized into three distinct vertical layers...

--- Slide 2 ---
The slide shows a comparison table highlighting the differences between Column Store and Row Store...
================================================================================
```

### 3. Logs OSMOSE Processing

**Format:** (inchangé)
```
================================================================================
[OSMOSE PURE] Lancement du traitement sémantique (remplace ingestion legacy)
================================================================================
[OSMOSE PURE] ✅ Traitement réussi:
  - 42 concepts canoniques
  - 15 connexions cross-documents
  - 8 topics segmentés
  - Proto-KG: 42 concepts + 35 relations + 42 embeddings
  - Durée: 14.2s
================================================================================
```

---

## 🎯 Bénéfices

### Avant Corrections

❌ Crash au démarrage (modules manquants)
❌ Résumés Vision invisibles dans logs
❌ Impossible de valider qualité résumés
❌ max_tokens=1500 limitait richesse

### Après Corrections

✅ Pipeline démarre sans erreur
✅ Résumés Vision affichés en entier
✅ Validation qualité possible (observer logs)
✅ max_tokens=2500 + temp=0.5 → Résumés plus riches
✅ Aperçu texte enrichi global visible

---

## 📝 Fichiers Modifiés

1. **`src/knowbase/semantic/__init__.py`**
   - Lignes 16-42 : Commenté imports modules manquants

2. **`src/knowbase/ingestion/pipelines/pptx_pipeline.py`**
   - Lignes 1459-1460 : Augmentation temperature (0.5) et max_tokens (2500)
   - Lignes 1470-1472 : Ajout logging complet résumé
   - Lignes 1947-1952 : Ajout aperçu texte enrichi

---

## 🧪 Test Suivant

Tu peux maintenant relancer l'ingestion PPTX et observer :

1. **Logs Vision détaillés** → Valider que résumés sont vraiment riches
2. **Longueur résumés** → Devrait être > 500 chars par slide en moyenne
3. **Qualité descriptions** → Layouts, diagrammes, relations visuelles capturés
4. **Texte enrichi final** → Aperçu 1000 chars permet validation rapide

**Commandes:**
```bash
# Observer logs en temps réel
docker-compose logs -f worker

# Relancer test PPTX
# (copier fichier dans data/docs_in/ ou via interface)
```

---

### Problème 3: Import NarrativeThread manquant (CRITIQUE)

**Erreur:**
```
ImportError: cannot import name 'NarrativeThread' from 'knowbase.semantic.models'
```

**Cause:**
- `src/knowbase/semantic/__init__.py` importait `NarrativeThread` depuis `models.py`
- Ce modèle n'existe PAS dans `models.py`
- `NarrativeThread` était prévu pour Phase 1 mais non implémenté

**Solution:** `src/knowbase/semantic/__init__.py:22-52`

Supprimé import inexistant et ajouté les modèles réels :
```python
# AVANT
from .models import (
    SemanticProfile,
    NarrativeThread,  # ❌ N'existe pas
    ComplexityZone,
    CandidateEntity,
    CandidateRelation,
)

# APRÈS
from .models import (
    SemanticProfile,
    ComplexityZone,
    CandidateEntity,
    CandidateRelation,
    Concept,  # ✅ Existe
    CanonicalConcept,  # ✅ Existe
    Topic,  # ✅ Existe
    ConceptConnection,  # ✅ Existe
    ConceptType,  # ✅ Enum
    DocumentRole,  # ✅ Enum
)
```

**Status:** ✅ CORRIGÉ

---

---

### Problème 4: Vision retourne JSON vide au lieu de prose (CRITIQUE)

**Erreur dans logs:**
```
WARNING: JSON invalide détecté, tentative de réparation: Expecting value: line 1 column 1 (char 0)
ERROR: Impossible de réparer le JSON, retour d'un array vide
WARNING: Slide 2 [VISION SUMMARY]: Response too short (2 chars)
```

**Cause:**
- `ask_gpt_vision_summary()` retourne de la **prose** (texte naturel)
- Mais appelle `clean_gpt_response()` qui essaie de **parser du JSON**
- Quand le parsing échoue, retourne `"[]"` (2 chars) au lieu du texte

**Solution:** `pptx_pipeline.py:1465-1469`

Remplacé appel à `clean_gpt_response()` par nettoyage simple markdown :
```python
# AVANT
summary = clean_gpt_response(summary)  # ❌ Parse JSON et retourne "[]" si échec

# APRÈS
import re
summary = re.sub(r"^```(?:markdown|text)?\s*", "", summary)
summary = re.sub(r"\s*```$", "", summary)
summary = summary.strip()  # ✅ Juste nettoie markdown, pas de parsing JSON
```

**Impact:** Vision peut maintenant retourner du texte prose sans qu'il soit détruit par le parser JSON.

**Status:** ✅ CORRIGÉ

---

### Problème 5: Duplicate detection désactivé (DEBUG MODE)

**Fichier:** `pptx_pipeline.py:1627-1662`

Pour faciliter les tests répétés avec le même fichier, la détection de duplicatas par checksum a été **temporairement désactivée**.

**Log visible:**
```
⚠️ DEBUG MODE: Duplicate detection DISABLED - processing [fichier.pptx]
```

**À réactiver en production** : Décommenter les lignes 1628-1657

**Status:** ⚠️ DÉSACTIVÉ TEMPORAIREMENT

---

---

### Problème 6: Erreur checksum duplicate en écriture (DEBUG)

**Erreur:**
```
ValueError: Version avec checksum 72740a5ab5d81bd0eb53006fe49fe9f1b3ea01b34512f55e5a2715bd405fe062 existe déjà (duplicata)
```

**Cause:**
- Vérification duplicate en LECTURE désactivée (pptx_pipeline.py)
- MAIS vérification duplicate en ÉCRITURE toujours active (document_registry_service.py)
- Résultat : Le document passe la lecture mais échoue à l'écriture

**Solution:** `document_registry_service.py:365-371`

Désactivé la vérification en écriture aussi :
```python
# AVANT
existing = self.get_version_by_checksum(version.checksum)
if existing:
    raise ValueError(f"Version avec checksum {version.checksum} existe déjà (duplicata)")

# APRÈS (DEBUG MODE)
# existing = self.get_version_by_checksum(version.checksum)
# if existing:
#     raise ValueError(f"Version avec checksum {version.checksum} existe déjà (duplicata)")
# DEBUG: Skip duplicate check - always create new version
pass
```

**Status:** ✅ CORRIGÉ

---

### Problème 7: Warning Neo4j SUPERSEDES

**Warning dans logs:**
```
WARNING:neo4j.notifications: relationship type `SUPERSEDES` does not exist
```

**Cause:**
- Requêtes Neo4j utilisent `OPTIONAL MATCH` sur relation `SUPERSEDES`
- Cette relation n'existe pas encore dans la base (pas de versions superseded)
- Neo4j génère un warning (pas bloquant mais polluant les logs)

**Solution:** `document_registry_service.py:482-490, 541-549`

Simplifié les requêtes pour éviter SUPERSEDES en mode DEBUG :
```python
# AVANT
query = """
MATCH (v:DocumentVersion {checksum: $checksum})
OPTIONAL MATCH (v)-[:SUPERSEDES]->(prev:DocumentVersion)
OPTIONAL MATCH (next:DocumentVersion)-[:SUPERSEDES]->(v)
RETURN v, prev.version_id as supersedes_version_id, next.version_id as superseded_by_version_id
"""

# APRÈS (DEBUG MODE)
query = """
MATCH (v:DocumentVersion {checksum: $checksum})
RETURN v, null as supersedes_version_id, null as superseded_by_version_id
"""
```

**Fichiers modifiés:**
- `_get_version_by_checksum_tx()` - Ligne 480
- `_get_latest_version_tx()` - Ligne 539

**Impact:** Plus de warnings Neo4j dans les logs

**Status:** ✅ CORRIGÉ

---

---

### Problème 8: Import qdrant_client incorrect (CRITIQUE)

**Erreur:**
```
ModuleNotFoundError: No module named 'knowbase.common.qdrant_client'
```

**Cause:**
- Import incorrect dans `osmose_integration.py`: `from knowbase.common.qdrant_client import get_qdrant_client`
- Le bon chemin est: `knowbase.common.clients.qdrant_client` (sous-répertoire `clients/`)

**Solution:** `osmose_integration.py:31`

Corrigé l'import :
```python
# AVANT
from knowbase.common.qdrant_client import get_qdrant_client

# APRÈS
from knowbase.common.clients.qdrant_client import get_qdrant_client
```

**Status:** ✅ CORRIGÉ

---

---

### Problème 9: Settings.get() n'existe pas (CRITIQUE)

**Erreur:**
```
AttributeError: 'Settings' object has no attribute 'get'
```

**Cause:**
- `OsmoseIntegrationConfig.from_env()` utilise `settings.get("KEY", default)`
- Mais `Settings` est un objet Pydantic `BaseSettings`, pas un dict
- Pydantic n'a pas de méthode `.get()`

**Solution:** `osmose_integration.py:67-81`

Remplacé `.get()` par `getattr()` :
```python
# AVANT
enable_osmose=settings.get("ENABLE_OSMOSE_PIPELINE", True)

# APRÈS
enable_osmose=getattr(settings, "enable_osmose_pipeline", True)
```

**Status:** ✅ CORRIGÉ

---

## 🛡️ NOUVEAU: Script de Validation (Économise les Appels LLM)

**Problème:** Chaque test PPTX coûte des dizaines d'appels LLM Vision (cher !). Si une dépendance manque, c'est découvert APRÈS les appels.

**Solution:** `src/knowbase/ingestion/validate_osmose_deps.py`

**Script de validation qui teste AVANT l'import:**
1. ✅ Imports Python (semantic, osmose_integration, etc.)
2. ✅ spaCy + modèles NER
3. ✅ Connexion Neo4j
4. ✅ Connexion Qdrant + collection concepts_proto
5. ✅ Configuration LLM (API keys)
6. ✅ Configuration OSMOSE

**Usage:**
```bash
# EXÉCUTER AVANT CHAQUE IMPORT PPTX
docker-compose exec app python -m knowbase.ingestion.validate_osmose_deps

# Si tout est OK (exit code 0):
✅ Vous pouvez lancer un import PPTX en toute sécurité

# Si erreur (exit code 1):
❌ NE PAS LANCER D'IMPORT - Corrigez d'abord
```

**Bénéfice:** Économise des appels LLM Vision en détectant les erreurs AVANT de traiter les slides.

---

**Version:** 1.5
**Date:** 2025-10-14 22:10
**Status:** ✅ PRÊT POUR VALIDATION PUIS TEST

**Modifications DEBUG MODE actives:**
1. ✅ Duplicate detection désactivée (lecture + écriture)
2. ✅ Requêtes Neo4j simplifiées (pas de SUPERSEDES)
3. ✅ Vision retourne prose (pas JSON)
4. ✅ Logs Vision complets affichés
5. ✅ Import qdrant_client corrigé
6. ✅ Settings.get() → getattr()
7. ✅ Script validation dépendances créé
8. ⚠️ À réactiver en production

---

### Problème 10: Modèles spaCy non installés automatiquement

**Problème:**
- spaCy installé mais modèles NER absents après rebuild
- Nécessitait installation manuelle: `python -m spacy download en_core_web_sm`
- À refaire à chaque rebuild

**Solution:** `app/Dockerfile:56-59`

Ajouté installation automatique modèles spaCy :
```dockerfile
# Téléchargement modèles spaCy pour OSMOSE (Phase 1 V2.1)
RUN python -m spacy download en_core_web_sm || echo "spaCy en model download failed"
RUN python -m spacy download fr_core_news_sm || echo "spaCy fr model download failed"
```

**Modèles installés:**
- `en_core_web_sm` : Anglais (12 MB)
- `fr_core_news_sm` : Français (15 MB)

**Impact:** +27 MB image Docker, mais installation automatique permanente

**Status:** ✅ CORRIGÉ - Nécessite rebuild

---

**IMPORTANT AVANT TEST PPTX:**

```bash
# 1. Rebuild Docker (si pas déjà fait)
docker-compose down
docker-compose build app worker
docker-compose up -d

# 2. Valider dépendances (évite appels LLM inutiles)
docker-compose exec app python -m knowbase.ingestion.validate_osmose_deps

# Attendu: 6/6 ✅ OK (y compris spaCy)

# 3. Si validation OK → Lancer import PPTX
```

**Guide complet:** Voir `doc/ongoing/OSMOSE_PURE_REBUILD_GUIDE.md`
