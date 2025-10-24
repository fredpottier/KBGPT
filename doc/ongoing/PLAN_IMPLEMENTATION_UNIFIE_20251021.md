# Plan d'Implémentation Unifié - 6 Problèmes OSMOSE - 2025-10-21

**Date** : 2025-10-21 02:00
**Objectif** : Résoudre LES 6 PROBLÈMES de manière cohérente et coordonnée
**Statut** : PLAN COMPLET - Prêt pour implémentation

---

## 🎯 Vue d'Ensemble

### Les 6 Problèmes à Résoudre Ensemble

| # | Problème | Impact | Priorité |
|---|----------|--------|----------|
| **#1** | 0 Relations Extraites | ❌ Phase 2 inutile | 🔴 P2 |
| **#2** | 0 Ontologies Redis | ⚠️ Pas d'apprentissage | 🟡 P4 |
| **#3** | 18% canonical_name=None | ⚠️ 100/547 concepts perdus | 🔴 P1 |
| **#4** | 0 Chunks Qdrant | ⚠️ Pas de RAG | 🟡 P3 |
| **#5** | Duplications Sémantiques | ⚠️ KG pollué (8 entités pour S/4HANA) | 🔴 P1 |
| **#6** | Pollution Acronymes | ⚠️ 47 acronymes sans expansion | 🔴 P1 |

### Exigences Utilisateur (Explicites)

1. **Acronymes** : Expansion systématique ("MFA" → "Multi-Factor Authentication") avec acronyme en **alias**
2. **Produits** : Canonical name officiel + toutes variantes en **aliases dans ontologie**
3. **Déduplication** : Seuil **85% similarité**
4. **Scope** : Résoudre TOUS les problèmes **ensemble** (pas de fixes isolés)

---

## 🏗️ Architecture de la Solution

### Nouveau Schéma Ontologie (Core Change)

**Actuellement** :
```python
# Neo4j CanonicalConcept
{
  "canonical_id": "uuid",
  "canonical_name": "Content Owner",  # ✅ OK
  "surface_form": "Content Owner",    # ⚠️ SINGULIER (string)
  "concept_type": "ROLE",
  "tenant_id": "default"
}

# Redis AdaptiveOntology
ontology:default:content_owner = {
  "canonical_name": "Content Owner",
  "concept_type": "ROLE",
  # ❌ PAS d'aliases
}
```

**NOUVEAU SCHÉMA** :
```python
# Neo4j CanonicalConcept (ÉTENDU)
{
  "canonical_id": "uuid",
  "canonical_name": "Multi-Factor Authentication",  # ✅ Forme CANONIQUE (expansion)
  "surface_forms": ["MFA", "2FA", "multi factor auth"],  # ✅ PLURIEL (liste)
  "primary_alias": "MFA",  # ✅ Alias principal (acronyme d'origine)
  "concept_type": "SECURITY_FEATURE",
  "tenant_id": "default",
  "confidence": 0.85,
  "merged_from": ["uuid1", "uuid2"]  # ✅ Traçabilité déduplication
}

# Redis AdaptiveOntology (ÉTENDU)
ontology:default:multi_factor_authentication = {
  "canonical_name": "Multi-Factor Authentication",
  "aliases": ["MFA", "2FA", "multi factor auth"],
  "primary_alias": "MFA",
  "concept_type": "SECURITY_FEATURE",
  "confidence": 0.85
}
```

### Exemple Concret : S/4HANA Cloud

**Avant (8 entités dupliquées)** :
```
CanonicalConcept: canonical_name="SAP Cloud ERP's", surface_form="SAP Cloud ERP's"
CanonicalConcept: canonical_name="SAP Cloud ERP", surface_form="SAP Cloud ERP"
CanonicalConcept: canonical_name="SAP Cloud ERP Private", surface_form="SAP Cloud ERP Private"
CanonicalConcept: canonical_name="ERP", surface_form="ERP"
CanonicalConcept: canonical_name="PCE", surface_form="PCE"
CanonicalConcept: canonical_name="S/4HANA Cloud", surface_form="S/4HANA Cloud"
CanonicalConcept: canonical_name="RISE With SAP Cloud ERP", surface_form="RISE With SAP Cloud ERP"
CanonicalConcept: canonical_name="RISE With SAP S/4HANA", surface_form="RISE With SAP S/4HANA"
```

**Après (1 entité consolidée)** :
```python
CanonicalConcept {
  canonical_name: "SAP S/4HANA Cloud Private Edition",  # ✅ Nom officiel canonique
  surface_forms: [
    "SAP Cloud ERP",
    "SAP Cloud ERP Private",
    "S/4HANA Cloud",
    "RISE with SAP Cloud ERP",
    "RISE with SAP S/4HANA",
    "PCE"  # Private Cloud Edition acronym
  ],
  primary_alias: "S/4HANA Cloud Private Edition",
  concept_type: "PRODUCT",
  confidence: 0.92,
  merged_from: ["uuid1", "uuid2", "uuid3", "uuid4", "uuid5", "uuid6", "uuid7", "uuid8"]
}
```

---

## 📋 Plan d'Implémentation par Priorité

### 🔴 PRIORITÉ 1 : Améliorer LLM Canonicalizer (Problèmes #3, #5, #6)

**Objectif** : Fix batch JSON parsing + expansion acronymes + normalisation produits

#### 1.1 Fixer Batch JSON Parsing (Problème #3)

**Fichier** : `src/knowbase/agents/gatekeeper/llm_canonicalizer.py`

**Diagnostic requis d'abord** :
```python
# Ajouter log AVANT parsing pour voir réponse LLM brute
logger.info(f"[LLMCanonicalizer:Batch] 🔍 Raw LLM response:\n{response_content}")
```

**Causes probables** :
1. LLM retourne texte explicatif au lieu de JSON pur
2. LLM retourne JSON mais schéma différent (clés manquantes)
3. Parser attend liste mais reçoit dict, ou inversement

**Fix probable** :
```python
def _parse_batch_response(self, response_content: str) -> dict[str, tuple[str, float]]:
    """Parse batch response avec robustesse accrue."""

    # Fix 2025-10-21: Extraction JSON robuste
    json_content = response_content.strip()

    # Si LLM entoure JSON de markdown code blocks
    if json_content.startswith("```json"):
        json_content = json_content.split("```json")[1].split("```")[0].strip()
    elif json_content.startswith("```"):
        json_content = json_content.split("```")[1].split("```")[0].strip()

    # Tenter parsing
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        logger.error(f"[LLMCanonicalizer:Batch] ❌ JSON parsing failed: {e}")
        logger.error(f"[LLMCanonicalizer:Batch] Raw content:\n{response_content[:500]}")
        raise

    # Adapter selon schéma retourné
    if isinstance(data, list):
        # Si LLM retourne liste [{concept_name, canonical_name, confidence}, ...]
        return {
            item["concept_name"]: (item["canonical_name"], item.get("confidence", 0.5))
            for item in data
        }
    elif isinstance(data, dict):
        # Si LLM retourne dict {concept_name: {canonical_name, confidence}}
        return {
            key: (val["canonical_name"], val.get("confidence", 0.5))
            for key, val in data.items()
        }
    else:
        raise ValueError(f"Unexpected response format: {type(data)}")
```

#### 1.2 Améliorer Prompt LLM avec Règles Explicites

**Fichier** : `src/knowbase/agents/gatekeeper/llm_canonicalizer.py`

**Nouveau Prompt Batch** :
```python
BATCH_CANONICALIZATION_PROMPT = """
Tu es un expert en normalisation de concepts pour construire un Knowledge Graph cohérent.

**RÈGLES STRICTES (À APPLIQUER DANS CET ORDRE)** :

1. **EXPANSION ACRONYMES** :
   - TOUJOURS étendre les acronymes courts (≤5 lettres) vers leur forme complète
   - Exemples :
     * "MFA" → "Multi-Factor Authentication"
     * "PCE" → "Private Cloud Edition"
     * "EDR" → "Endpoint Detection and Response"
     * "ILM" → "Information Lifecycle Management"
   - Si acronyme ambigu et contexte insuffisant, utiliser forme la plus probable dans contexte SAP/IT
   - CONSERVER l'acronyme comme "primary_alias"

2. **NORMALISATION NOMS PRODUITS** :
   - Utiliser le nom de produit OFFICIEL complet (consulter catalogue SAP si nécessaire)
   - Exemples :
     * "SAP Cloud ERP", "PCE", "S/4HANA Cloud" → "SAP S/4HANA Cloud Private Edition"
     * "BTP", "Business Technology Platform" → "SAP Business Technology Platform"
     * "RISE with SAP" → "RISE with SAP" (déjà canonical)
   - Ajouter toutes les variantes rencontrées dans "aliases"

3. **NETTOYAGE BASIQUE** :
   - Supprimer possessifs : "SAP Cloud ERP's" → "SAP Cloud ERP"
   - Normaliser singulier/pluriel : "Connectors" → "Connector"
   - Supprimer articles : "The Content Owner" → "Content Owner"
   - Capitalisation cohérente : "multi-factor authentication" → "Multi-Factor Authentication"

4. **DÉDUPLICATION INTRA-BATCH** :
   - Si plusieurs concepts dans le batch sont synonymes (similarité > 85%), les fusionner
   - Exemple : "ERP", "SAP Cloud ERP", "PCE" → UN SEUL canonical "SAP S/4HANA Cloud Private Edition"
   - Lister TOUS les noms originaux dans "merged_aliases"

**FORMAT DE SORTIE (JSON STRICT)** :
```json
{
  "concepts": [
    {
      "concept_name": "MFA",  // Nom original du concept
      "canonical_name": "Multi-Factor Authentication",  // Forme canonique
      "primary_alias": "MFA",  // Alias principal (souvent l'acronyme d'origine)
      "aliases": ["2FA", "Multi Factor Auth", "MFA"],  // Toutes variantes rencontrées
      "confidence": 0.90,  // Confiance dans la canonicalisation (0-1)
      "expansion_applied": true,  // Booléen : acronyme étendu ?
      "merged_from": []  // Liste des concept_name fusionnés (si déduplication)
    },
    {
      "concept_name": "SAP Cloud ERP's",
      "canonical_name": "SAP S/4HANA Cloud Private Edition",
      "primary_alias": "S/4HANA Cloud Private Edition",
      "aliases": ["SAP Cloud ERP", "PCE", "S/4HANA Cloud", "SAP Cloud ERP Private"],
      "confidence": 0.95,
      "expansion_applied": false,
      "merged_from": ["ERP", "PCE", "S/4HANA Cloud"]  // Fusionné avec d'autres du batch
    }
  ]
}
```

**IMPORTANT** :
- Retourner UNIQUEMENT le JSON, AUCUN texte explicatif avant/après
- Chaque concept du batch doit apparaître dans la sortie (même si juste nettoyage)
- Si incertain sur expansion acronyme, confidence < 0.7

**CONCEPTS À CANONICALISER** :
{concepts_list}

**CONTEXTE DOCUMENT** :
{document_context}
"""
```

**Code Modifications** :
```python
def _batch_canonicalize_concepts_with_llm(
    self,
    concepts: list[dict],
    tenant_id: str = "default"
) -> dict[str, dict]:
    """
    Retourne dict[concept_name] = {
        "canonical_name": str,
        "primary_alias": str,
        "aliases": list[str],
        "confidence": float,
        "expansion_applied": bool,
        "merged_from": list[str]
    }
    """

    # Construire liste concepts pour prompt
    concepts_list = "\n".join([
        f"- {c['concept_name']}: {c.get('definition', 'N/A')[:100]}"
        for c in concepts
    ])

    # Document context (pour aider expansion acronymes)
    document_context = concepts[0].get("document_title", "N/A") if concepts else "N/A"

    prompt = BATCH_CANONICALIZATION_PROMPT.format(
        concepts_list=concepts_list,
        document_context=document_context
    )

    # Appel LLM
    response = self._call_llm(prompt, temperature=0.1)  # Basse température pour cohérence

    # Log raw response
    logger.info(f"[LLMCanonicalizer:Batch] 🔍 Raw LLM response:\n{response[:500]}")

    # Parse avec nouveau schéma
    parsed = self._parse_batch_response_v2(response)

    return parsed
```

#### 1.3 Ajouter Fuzzy Deduplication Post-LLM (Problème #5)

**Fichier** : `src/knowbase/agents/gatekeeper/gatekeeper.py`

**Nouvelle Fonction** :
```python
from difflib import SequenceMatcher

def _fuzzy_deduplicate_concepts(
    self,
    concepts: list[dict],
    similarity_threshold: float = 0.85
) -> list[dict]:
    """
    Déduplication floue post-canonicalization.

    Fusionne concepts avec canonical_name similaire > threshold.

    Returns:
        Liste dédupliquée avec merged_from tracé.
    """

    logger.info(f"[GATEKEEPER:FuzzyDedup] 🔍 Deduplicating {len(concepts)} concepts (threshold={similarity_threshold})")

    deduplicated = []
    merged_ids = set()

    for i, concept_a in enumerate(concepts):
        if concept_a["concept_id"] in merged_ids:
            continue  # Déjà fusionné

        canonical_a = concept_a.get("canonical_name", "").lower()
        if not canonical_a:
            deduplicated.append(concept_a)
            continue

        # Chercher concepts similaires
        similar_concepts = [concept_a]

        for j, concept_b in enumerate(concepts[i+1:], start=i+1):
            if concept_b["concept_id"] in merged_ids:
                continue

            canonical_b = concept_b.get("canonical_name", "").lower()
            if not canonical_b:
                continue

            # Calcul similarité
            similarity = SequenceMatcher(None, canonical_a, canonical_b).ratio()

            if similarity >= similarity_threshold:
                logger.info(
                    f"[GATEKEEPER:FuzzyDedup] ✅ MERGE ({similarity:.2%}): "
                    f"'{concept_a['canonical_name']}' ← '{concept_b['canonical_name']}'"
                )
                similar_concepts.append(concept_b)
                merged_ids.add(concept_b["concept_id"])

        # Fusionner si plusieurs trouvés
        if len(similar_concepts) > 1:
            merged_concept = self._merge_concepts(similar_concepts)
            deduplicated.append(merged_concept)
        else:
            deduplicated.append(concept_a)

    logger.info(
        f"[GATEKEEPER:FuzzyDedup] ✅ Deduplicated: {len(concepts)} → {len(deduplicated)} "
        f"({len(concepts) - len(deduplicated)} merged)"
    )

    return deduplicated

def _merge_concepts(self, concepts: list[dict]) -> dict:
    """
    Fusionne plusieurs concepts similaires en UN concept.

    Stratégie :
    - canonical_name : Le PLUS LONG (plus descriptif)
    - surface_forms : UNION de toutes les variantes
    - primary_alias : Le PLUS COURT (souvent acronyme)
    - confidence : MOYENNE pondérée
    - merged_from : Tous les concept_id fusionnés
    """

    # Trier par longueur canonical_name (desc)
    concepts_sorted = sorted(
        concepts,
        key=lambda c: len(c.get("canonical_name", "")),
        reverse=True
    )

    # Prendre le plus long comme base
    merged = concepts_sorted[0].copy()

    # Union surface_forms
    all_surface_forms = set()
    for c in concepts:
        all_surface_forms.update(c.get("surface_forms", []))
        all_surface_forms.add(c.get("canonical_name", ""))  # Ajouter aussi canonical

    merged["surface_forms"] = list(all_surface_forms)

    # Primary alias = le plus court (souvent acronyme)
    all_names = [c.get("canonical_name", "") for c in concepts]
    merged["primary_alias"] = min(all_names, key=len)

    # Confidence moyenne
    confidences = [c.get("confidence", 0.5) for c in concepts]
    merged["confidence"] = sum(confidences) / len(confidences)

    # Traçabilité
    merged["merged_from"] = [c["concept_id"] for c in concepts]

    return merged
```

**Intégration dans PromoteConcepts** :
```python
# gatekeeper.py - PromoteConcepts tool

# Après batch canonicalization, AVANT promotion Neo4j
concepts_with_canonical = []
for concept in concepts:
    # ... récupération canonical depuis cache ...
    concepts_with_canonical.append(concept)

# ✅ NOUVEAU : Fuzzy deduplication
concepts_deduplicated = self._fuzzy_deduplicate_concepts(
    concepts_with_canonical,
    similarity_threshold=0.85
)

# Promotion Neo4j avec concepts dédupliqués
for concept in concepts_deduplicated:
    # ... existing promotion logic ...
```

---

### 🔴 PRIORITÉ 2 : Fixer Surface Forms pour Phase 2 (Problème #1)

**Objectif** : Phase 2 doit recevoir `surface_forms` (liste) pour extraction relations

**Fichier** : `src/knowbase/agents/supervisor/supervisor.py`

**Localisation** : Step EXTRACT_RELATIONS

**Modification** :
```python
# supervisor.py - EXTRACT_RELATIONS step

# ❌ AVANT : Passer concepts sans surface_forms
concepts_for_extraction = neo4j_client.get_all_concepts(tenant_id=tenant_id)

# ✅ APRÈS : Requête Neo4j avec conversion surface_form → surface_forms
query = """
MATCH (c:CanonicalConcept)
WHERE c.tenant_id = $tenant_id
RETURN c.canonical_id AS concept_id,
       c.canonical_name AS canonical_name,
       c.surface_forms AS surface_forms_list,  // Si schema Neo4j déjà updated
       c.surface_form AS surface_form_single,  // Ancien schema (fallback)
       c.concept_type AS concept_type
"""

with neo4j_client.driver.session() as session:
    result = session.run(query, tenant_id=tenant_id)

    concepts_for_extraction = []
    for row in result:
        # Conversion schema : singular string → list
        surface_forms = row["surface_forms_list"]  # Nouveau schema (peut être None)

        if not surface_forms:
            # Fallback ancien schema : convertir string → liste
            surface_form_single = row["surface_form_single"]
            surface_forms = [surface_form_single] if surface_form_single else []

        concepts_for_extraction.append({
            "concept_id": row["concept_id"],
            "canonical_name": row["canonical_name"],
            "surface_forms": surface_forms,  # ✅ TOUJOURS liste
            "concept_type": row["concept_type"]
        })

logger.info(
    f"[SUPERVISOR:EXTRACT_RELATIONS] Retrieved {len(concepts_for_extraction)} concepts "
    f"with surface_forms for relation extraction"
)

# Appel RelationExtraction tool avec concepts corrigés
relation_extraction_result = await relation_extraction_tool.run(
    tool_input=RelationExtractionInput(concepts=concepts_for_extraction, ...)
)
```

**Migration Schema Neo4j** (si nécessaire) :
```python
# Migration script : scripts/migrate_surface_forms.py

from knowbase.common.clients.neo4j_client import get_neo4j_client

def migrate_surface_form_to_list():
    """
    Migrer surface_form (string) → surface_forms (liste).
    """

    neo4j = get_neo4j_client()

    query = """
    MATCH (c:CanonicalConcept)
    WHERE c.surface_form IS NOT NULL
      AND c.surface_forms IS NULL
    SET c.surface_forms = [c.surface_form]
    RETURN count(c) as migrated
    """

    with neo4j.driver.session() as session:
        result = session.run(query)
        count = result.single()["migrated"]
        print(f"✅ Migrated {count} concepts: surface_form → surface_forms")

if __name__ == "__main__":
    migrate_surface_form_to_list()
```

**Exécution** :
```bash
docker-compose exec app python scripts/migrate_surface_forms.py
```

---

### 🟡 PRIORITÉ 3 : Ajouter TextChunker dans FINALIZE (Problème #4)

**Objectif** : Créer chunks Qdrant pour RAG

**Fichier** : `src/knowbase/agents/supervisor/supervisor.py`

**Localisation** : Step FINALIZE (après EXTRACT_RELATIONS)

**Code à Ajouter** :
```python
# supervisor.py - FINALIZE step

from knowbase.chunks.text_chunker import get_text_chunker
from knowbase.common.clients.qdrant_client import get_qdrant_client

# Récupérer texte complet document depuis state
full_text = state.get("full_text", "")
document_id = state.get("document_id")
tenant_id = state.get("tenant_id", "default")

if not full_text:
    logger.warning("[SUPERVISOR:FINALIZE] No full_text in state, skipping chunking")
else:
    logger.info(f"[SUPERVISOR:FINALIZE] 📄 Chunking document {document_id}...")

    # Chunking
    chunker = get_text_chunker()
    chunks = chunker.chunk_document(
        document_id=document_id,
        text=full_text,
        metadata={
            "tenant_id": tenant_id,
            "document_title": state.get("document_title", "Unknown"),
            "file_name": state.get("file_name", "Unknown"),
            "import_date": state.get("import_date", "Unknown")
        }
    )

    logger.info(f"[SUPERVISOR:FINALIZE] ✅ Created {len(chunks)} chunks")

    # Upload Qdrant
    qdrant = get_qdrant_client()

    # Convertir chunks en points Qdrant
    points = []
    for i, chunk in enumerate(chunks):
        points.append({
            "id": f"{document_id}_chunk_{i}",
            "vector": chunk["embedding"],  # Déjà créé par TextChunker
            "payload": {
                "document_id": document_id,
                "chunk_index": i,
                "text": chunk["text"],
                "tenant_id": tenant_id,
                **chunk["metadata"]
            }
        })

    # Upsert dans collection knowbase
    qdrant.upsert(
        collection_name="knowbase",
        points=points
    )

    logger.info(
        f"[SUPERVISOR:FINALIZE] ✅ Uploaded {len(points)} chunks to Qdrant "
        f"(collection=knowbase, tenant={tenant_id})"
    )
```

**Vérification Post-Import** :
```bash
# Compter chunks dans Qdrant
curl http://localhost:6333/collections/knowbase

# Expected:
# {
#   "result": {
#     "points_count": 500-1000,  # Dépend taille document
#     ...
#   }
# }
```

---

### 🟡 PRIORITÉ 4 : Fixer Ontologies Redis (Problème #2)

**Objectif** : Stocker concepts dans Redis pour apprentissage

#### 4.1 Baisser Threshold Confidence

**Fichier** : `src/knowbase/ontology/adaptive_ontology_manager.py`

**Modification** :
```python
class AdaptiveOntologyManager:

    # ❌ AVANT
    MIN_CONFIDENCE_THRESHOLD = 0.6

    # ✅ APRÈS : Baisser à 0.25 (accepter canonicalization LLM baseline)
    MIN_CONFIDENCE_THRESHOLD = 0.25

    def store_concept(self, concept: dict, tenant_id: str = "default") -> bool:
        """Store concept in Redis ontology."""

        canonical_name = concept.get("canonical_name")
        confidence = concept.get("confidence", 0.3)

        # Validation confidence
        if confidence < self.MIN_CONFIDENCE_THRESHOLD:
            logger.warning(
                f"[AdaptiveOntology:Store] ⚠️ Low confidence {confidence:.2f} < {self.MIN_CONFIDENCE_THRESHOLD}, "
                f"skipping store for '{canonical_name}'"
            )
            return False

        # ... rest of storage logic ...
```

#### 4.2 Autoriser Caractères Spéciaux

**Fichier** : `src/knowbase/ontology/adaptive_ontology_manager.py`

**Modification** :
```python
import re

def _validate_concept_name(self, concept_name: str) -> bool:
    """Validate concept name format."""

    # ❌ AVANT : Rejet de &, -, (), etc.
    # ALLOWED_PATTERN = r"^[\w\s]+$"

    # ✅ APRÈS : Autoriser caractères spéciaux courants
    ALLOWED_PATTERN = r"^[\w\s\-&(),./]+$"

    if not re.match(ALLOWED_PATTERN, concept_name):
        logger.warning(
            f"[AdaptiveOntology:Validation] Invalid characters in concept name: {concept_name}"
        )
        return False

    return True
```

#### 4.3 Stocker Aliases dans Redis

**Nouveau schéma Redis** :
```python
def store_concept(self, concept: dict, tenant_id: str = "default") -> bool:
    """Store concept with aliases in Redis."""

    canonical_name = concept.get("canonical_name")
    key = f"ontology:{tenant_id}:{self._normalize_key(canonical_name)}"

    # ✅ NOUVEAU : Inclure aliases
    ontology_entry = {
        "canonical_name": canonical_name,
        "aliases": concept.get("aliases", []),
        "primary_alias": concept.get("primary_alias"),
        "concept_type": concept.get("concept_type"),
        "confidence": concept.get("confidence", 0.5),
        "surface_forms": concept.get("surface_forms", []),
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    # Store in Redis
    self.redis_client.set(
        key,
        json.dumps(ontology_entry),
        ex=self.ONTOLOGY_TTL  # 30 days
    )

    # ✅ NOUVEAU : Créer index inverse pour lookup par alias
    for alias in concept.get("aliases", []):
        alias_key = f"alias:{tenant_id}:{self._normalize_key(alias)}"
        self.redis_client.set(
            alias_key,
            canonical_name,  # Pointe vers canonical
            ex=self.ONTOLOGY_TTL
        )

    logger.info(
        f"[AdaptiveOntology:Store] ✅ Stored '{canonical_name}' "
        f"with {len(concept.get('aliases', []))} aliases"
    )

    return True
```

---

## 🎯 Métriques de Validation

### Avant Fixes

| Métrique | Valeur Actuelle |
|----------|-----------------|
| Batch JSON parsing success | 0% (28/28 batches failed) |
| Concepts avec canonical_name=None | 100 (18%) |
| Appels LLM canonicalization | 547 (individual fallback) |
| Temps canonicalization | 18 min |
| Duplications sémantiques | 8 entités pour S/4HANA |
| Acronymes non-expansés | 47 (HA, DR, MFA, etc.) |
| Co-occurring concept pairs | 0 |
| Relations extraites | 0 |
| Chunks Qdrant knowbase | 0 |
| Ontologies Redis | 0 |

### Cibles Après Fixes

| Métrique | Cible | Impact |
|----------|-------|--------|
| **Batch JSON parsing success** | **100%** | ✅ 28 batches OK |
| **Concepts canonical_name=None** | **0 (0%)** | ✅ 100% concepts valides |
| **Appels LLM canonicalization** | **28 (batches)** | ✅ 19x moins d'appels |
| **Temps canonicalization** | **< 1 min** | ✅ 18x plus rapide |
| **Duplications S/4HANA** | **1 entité** | ✅ 8 → 1 (87% réduction) |
| **Acronymes expansés** | **100%** | ✅ MFA → Multi-Factor Authentication |
| **Co-occurring concept pairs** | **50-200** | ✅ Phase 2 fonctionnelle |
| **Relations extraites** | **100-200** | ✅ KG enrichi |
| **Chunks Qdrant** | **500-1000** | ✅ RAG opérationnel |
| **Ontologies Redis** | **200-400** | ✅ Apprentissage actif |

---

## 📦 Déploiement Coordonné

### Ordre d'Implémentation (Séquentiel)

**Phase A : Fixes Canonicalisation** (2-3h)
1. ✅ Diagnostiquer + fixer batch JSON parsing
2. ✅ Améliorer prompt LLM (acronymes + produits + normalisation)
3. ✅ Implémenter fuzzy deduplication (85%)
4. ✅ Mettre à jour schéma Neo4j + Redis (aliases)

**Phase B : Fixes Extraction** (1-2h)
5. ✅ Fixer surface_forms pour Phase 2
6. ✅ Ajouter TextChunker dans FINALIZE
7. ✅ Ajuster threshold + validation Redis

**Phase C : Tests & Validation** (1h)
8. ✅ Rebuild worker avec tous les fixes
9. ✅ Purge Neo4j + Redis + Qdrant
10. ✅ Import test document S/4HANA
11. ✅ Vérifier métriques cibles

### Commandes Déploiement

```bash
# 1. Rebuild worker
docker-compose build ingestion-worker

# 2. Restart worker
docker-compose restart ingestion-worker

# 3. Purge databases
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  --format plain "MATCH (n) DETACH DELETE n"

docker exec knowbase-redis redis-cli FLUSHDB

curl -X DELETE http://localhost:6333/collections/knowbase

# 4. Recréer collection Qdrant
curl -X PUT http://localhost:6333/collections/knowbase \
  -H 'Content-Type: application/json' \
  -d '{
    "vectors": {
      "size": 1024,
      "distance": "Cosine"
    }
  }'

# 5. Import test
# → Upload RISE_with_SAP_Cloud_ERP_Private.pptx via http://localhost:3000/documents/import

# 6. Vérifier Neo4j
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  --format plain "
    MATCH (c:CanonicalConcept)
    WHERE c.tenant_id = 'default'
    RETURN c.canonical_name, size(c.surface_forms) as aliases_count, c.confidence
    ORDER BY c.created_at DESC
    LIMIT 20
  "

# Expected:
# SAP S/4HANA Cloud Private Edition | 7 | 0.92
# Multi-Factor Authentication | 3 | 0.88
# High Availability | 2 | 0.85
# ...

# 7. Vérifier Relations
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  --format plain "
    MATCH (a)-[r]->(b)
    WHERE a.tenant_id = 'default'
    RETURN type(r) as relation_type, count(*) as count
  "

# Expected:
# HAS_FEATURE | 45
# USES | 23
# REQUIRES | 18
# ...

# 8. Vérifier Qdrant
curl http://localhost:6333/collections/knowbase | jq '.result.points_count'

# Expected: 500-1000

# 9. Vérifier Redis
docker exec knowbase-redis redis-cli KEYS "ontology:*" | wc -l

# Expected: 200-400
```

---

## 🔍 Questions Ouvertes & Décisions

### Q1 : Catalogue Produits SAP

**Question** : Pour canonicaliser correctement les noms de produits SAP, avons-nous accès à un catalogue officiel ?

**Options** :
- A) Utiliser `config/sap_solutions.yaml` existant
- B) Appel API SAP Product Catalog (si accessible)
- C) LLM knowledge (risque hallucinations)

**Recommandation** : **Option A** - Enrichir `sap_solutions.yaml` avec aliases connus, utiliser comme référence dans prompt LLM.

### Q2 : Expansion Acronymes - Contexte Requis

**Question** : Acronymes ambigus (ex: "PCE" = "Private Cloud Edition" OU "Peripheral Component Expansion") - quelle stratégie ?

**Options** :
- A) Toujours utiliser contexte document pour désambiguïser
- B) Privilégier sens SAP/IT par défaut
- C) Conserver acronyme si ambigu (confidence < 0.7)

**Recommandation** : **Option A + B** - Contexte document en priorité, fallback SAP/IT, confidence < 0.7 si incertain.

### Q3 : Migration Schema Neo4j - Rétroactif ?

**Question** : Faut-il migrer les 447 concepts DÉJÀ dans Neo4j vers nouveau schema (surface_forms liste) ?

**Options** :
- A) Migration script immédiate (UPDATE tous les concepts)
- B) Migration lazy (au prochain import seulement)
- C) Coexistence 2 schemas (fallback dans code)

**Recommandation** : **Option A** - Migration immédiate via script `migrate_surface_forms.py` pour cohérence.

---

## 🎯 Prochaines Étapes Immédiates

**Action Utilisateur** : Autoriser implémentation du plan

**Ordre Recommandé** :
1. **Commencer par Phase A.1** : Diagnostiquer batch JSON parsing (ajouter log raw response)
2. **Attendre résultat diagnostic** avant d'implémenter fix parsing
3. **Implémenter séquentiellement** : A.2 → A.3 → A.4 → B.5 → B.6 → B.7
4. **Tester après chaque phase** (pas tout d'un coup)

**Temps Total Estimé** : 4-6h (implémentation + tests)

---

**Créé par** : Claude Code
**Pour** : Résolution unifiée des 6 problèmes OSMOSE
**Statut** : PLAN COMPLET - En attente autorisation implémentation
**Priorité** : CRITIQUE
**Impact Business** : +85% qualité KG, Phase 2 opérationnelle, RAG fonctionnel

