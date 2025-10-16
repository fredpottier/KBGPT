# Guide Canonicalisation Robuste & Auto-Apprentissage

**Date**: 2025-10-16
**Phase**: OSMOSE Phase 1.5 - Semantic Core
**Version**: 1.0

---

## 📋 Table des Matières

1. [Introduction](#introduction)
2. [Architecture Générale](#architecture-générale)
3. [P0 - Features Critiques](#p0---features-critiques)
4. [P1 - Features Importantes](#p1---features-importantes)
5. [Guide Admin - API Rollback](#guide-admin---api-rollback)
6. [Profils Seuils Adaptatifs](#profils-seuils-adaptatifs)
7. [Exemples Decision Traces](#exemples-decision-traces)
8. [FAQ & Troubleshooting](#faq--troubleshooting)

---

## Introduction

Le système de **Canonicalisation Robuste** permet à KnowWhere (OSMOSE) de normaliser automatiquement les noms d'entités extraits par LLM, tout en gardant un contrôle qualité via:

- **Sandbox Auto-Learning**: Protection ontologie avec validation conditionnelle
- **Mécanisme Rollback**: Correction erreurs sans casser cohérence graphe
- **Decision Trace**: Audit complet des décisions
- **Seuils Adaptatifs**: Ajustement selon contexte documentaire
- **Similarité Structurelle**: Matching avancé au-delà du textuel
- **Séparation Surface/Canonical**: Préservation noms bruts extraits

---

## Architecture Générale

### Pipeline de Canonicalisation

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. EXTRACTION LLM                                               │
│    Nom brut: "sap s4hana" (surface_form)                       │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. NORMALISATION (EntityNormalizerNeo4j)                        │
│    Cascade:                                                      │
│    ├─ Exact match (normalized)                                  │
│    ├─ Exact match sans filtrage type                            │
│    └─ Structural match (fallback P1.2)                          │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. AUTO-VALIDATION (P0.1 Sandbox + P1.1 Seuils)                │
│    Si confidence >= seuil adaptatif:                            │
│    ├─ status = "auto_learned_validated"                        │
│    └─ Pas de validation admin requise                          │
│    Sinon:                                                        │
│    ├─ status = "auto_learned_pending"                          │
│    └─ Notification admin pour validation                       │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. PROMOTION (Gatekeeper → Neo4j Published-KG)                 │
│    CanonicalConcept créé avec:                                  │
│    ├─ canonical_name: "SAP S/4HANA Cloud"                      │
│    ├─ surface_form: "sap s4hana" (P1.3)                        │
│    └─ decision_trace_json: {...} (P0.3)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## P0 - Features Critiques

### P0.1 - Sandbox Auto-Learning

**Objectif**: Protéger l'ontologie des erreurs auto-learning en isolant les entités peu confiantes.

#### Statuts Possibles

| Statut | Description | Requires Validation |
|--------|-------------|---------------------|
| `auto_learned_validated` | Confidence >= seuil adaptatif | ❌ Non |
| `auto_learned_pending` | Confidence < seuil adaptatif | ✅ Oui |
| `manual` | Créé manuellement par admin | ❌ Non |
| `deprecated` | Remplacé par nouvelle entité | ❌ Non (ne plus utiliser) |

#### Filtrage Automatique

Par défaut, les entités `auto_learned_pending` sont **filtrées** lors des recherches de normalisation (sauf accès admin explicite avec `include_pending=True`).

#### Exemple de Log

```
[ONTOLOGY:AdaptiveThresholds] ✅ AUTO-VALIDATED 'SAP S/4HANA Cloud'
(confidence=0.96 >= 0.95, profile=SAP_OFFICIAL_DOCS, status=auto_learned_validated)

[ONTOLOGY:AdaptiveThresholds] ⏳ PENDING VALIDATION 'Oracle ERP'
(confidence=0.82 in [0.80, 0.95), profile=INTERNAL_DOCS, requires_admin=True)
```

---

### P0.2 - Mécanisme Rollback

**Objectif**: Permettre corrections d'erreurs ontologie sans casser cohérence du graphe.

#### Relation `DEPRECATED_BY`

Lorsqu'une entité est dépréciée:

1. `old_entity` status → `deprecated`
2. Relation `(old_entity)-[:DEPRECATED_BY {reason, comment}]->(new_entity)`
3. Migration atomique: tous les `CanonicalConcept` pointant vers `old_entity` sont migrés vers `new_entity`

#### Raisons de Dépréciation

| Raison | Description | Cas d'usage |
|--------|-------------|-------------|
| `incorrect_fusion` | Fusion incorrecte détectée | Oracle + SAP fusionnés à tort |
| `wrong_canonical` | Nom canonique incorrect | Typo, mauvaise casse |
| `duplicate` | Doublon détecté | "SAP S/4HANA" et "S4HANA" identiques |
| `admin_correction` | Correction manuelle admin | Raison non spécifiée |
| `data_quality` | Problème qualité données | Données source corrompues |

---

### P0.3 - Decision Trace

**Objectif**: Audit complet des décisions de canonicalisation pour debugging et compliance.

#### Modèle DecisionTrace

```json
{
  "raw_name": "sap s4hana",
  "entity_type_hint": "PRODUCT",
  "tenant_id": "default",
  "strategies": [
    {
      "strategy": "ontology_lookup",
      "attempted": true,
      "success": true,
      "canonical_name": "SAP S/4HANA Cloud",
      "confidence": 1.0,
      "execution_time_ms": 12.5,
      "metadata": {
        "entity_id": "S4HANA_CLOUD",
        "match_type": "exact"
      }
    }
  ],
  "final_canonical_name": "SAP S/4HANA Cloud",
  "final_strategy": "ontology_lookup",
  "final_confidence": 1.0,
  "is_cataloged": true,
  "timestamp": "2025-10-16T10:30:00Z",
  "total_execution_time_ms": 15.2,
  "requires_validation": false,
  "auto_validated": true
}
```

#### Stratégies Disponibles

1. **`ontology_lookup`**: Match exact dans ontologie Neo4j
2. **`fuzzy_matching`**: Similarité textuelle >= 90%
3. **`llm_canonicalization`**: Normalisation via GPT-4o-mini
4. **`heuristic_rules`**: Règles acronymes, casse, etc.
5. **`fallback`**: Garde nom tel quel (échec normalisation)

---

## P1 - Features Importantes

### P1.1 - Seuils Adaptatifs

**Objectif**: Ajuster seuils de validation selon contexte documentaire.

#### Profils Prédéfinis

| Profil | Auto-Validation | Require Human Below | Use Case |
|--------|-----------------|---------------------|----------|
| `SAP_OFFICIAL_DOCS` | 0.95 | 0.85 | Docs officielles SAP (haute qualité) |
| `INTERNAL_DOCS` | 0.95 | 0.75 | Docs internes entreprise (qualité variable) |
| `COMMUNITY_CONTENT` | 0.97 | 0.70 | Forums, slides, emails (qualité basse) |
| `SAP_PRODUCTS_CATALOG` | 0.98 | 0.90 | Produits SAP critiques (très strict) |
| `MULTILINGUAL_TECHNICAL` | 0.95 | 0.75 | Multilingue, jargon technique (tolérant) |
| `DEFAULT` | 0.95 | 0.80 | Fallback équilibré |

#### Sélection Automatique

Le profil est sélectionné selon:

1. **Priorité 1**: Domaine SAP + Type PRODUCT → `SAP_PRODUCTS_CATALOG`
2. **Priorité 2**: Domaine SAP + Source officielle → `SAP_OFFICIAL_DOCS`
3. **Priorité 3**: Source communautaire → `COMMUNITY_CONTENT`
4. **Priorité 4**: Multilingue/jargon → `MULTILINGUAL_TECHNICAL`
5. **Priorité 5**: Docs internes → `INTERNAL_DOCS`
6. **Fallback**: `DEFAULT`

#### Exemple d'Utilisation

```python
from knowbase.ontology.ontology_saver import save_ontology_to_neo4j

save_ontology_to_neo4j(
    merge_groups=groups,
    entity_type="PRODUCT",
    domain="sap_ecosystem",              # P1.1: Contexte domaine
    source_context="official_documentation",  # P1.1: Contexte source
    language="english"                    # P1.1: Contexte linguistique
)
```

---

### P1.2 - Similarité Structurelle

**Objectif**: Matching avancé au-delà de la similarité textuelle.

#### Dimensions d'Analyse

1. **Component Overlap (40%)**: Jaccard sur mots significatifs
2. **Acronym Match (30%)**: Détection acronymes SAP spécifiques
3. **Typo Similarity (20%)**: Normalisation variantes typo
4. **Affix Similarity (10%)**: Stripping préfixes/suffixes optionnels

#### Patterns SAP Reconnus

| Pattern | Variantes Détectées |
|---------|---------------------|
| `S/4HANA` | S4HANA, S/4HANA, S4H, S/4 |
| `SuccessFactors` | SuccessFactors, SF, SFSF |
| `BusinessOne` | BusinessOne, B1, SBO |
| `BusinessByDesign` | BusinessByDesign, ByDesign, ByD |

#### Exemples de Matching

| Input | Match Trouvé | Score | Méthode |
|-------|--------------|-------|---------|
| "S4H" | "SAP S/4HANA Cloud" | 0.85 | structural (acronym) |
| "ERP Cloud" | "Cloud ERP" | 0.78 | structural (components) |
| "SuccessFactors" | "SAP SuccessFactors" | 0.92 | structural (affix) |
| "sap s/4hana" | "SAP S/4HANA Cloud" | 0.93 | textual |

---

### P1.3 - Séparation Surface/Canonical

**Objectif**: Ne jamais modifier le nom d'origine extrait, toujours garder séparé.

#### Champs Stockés

```cypher
// CanonicalConcept node
{
  canonical_id: "uuid-1234",
  canonical_name: "SAP S/4HANA Cloud",  // Nom normalisé
  surface_form: "sap s4hana",            // Nom brut LLM (P1.3)
  concept_type: "PRODUCT",
  quality_score: 0.95,
  decision_trace_json: "{...}",
  promoted_at: datetime()
}
```

#### Avantages

- **Rollback**: Retrouver nom original si erreur normalisation
- **Debug**: Comprendre transformations appliquées
- **Analytics**: Comparer variantes LLM vs canoniques
- **Audit**: Traçabilité complète origin → canonical

---

## Guide Admin - API Rollback

### Endpoint: POST `/admin/ontology/deprecate`

Déprécier une entité et migrer vers nouvelle.

#### Request Body

```json
{
  "old_entity_id": "ORACLE_ERP_WRONG",
  "new_entity_id": "SAP_S4HANA_CLOUD",
  "reason": "incorrect_fusion",
  "comment": "Oracle et SAP fusionnés à tort, correction manuelle",
  "deprecated_by": "admin@example.com",
  "tenant_id": "default"
}
```

#### Response

```json
{
  "success": true,
  "old_entity_id": "ORACLE_ERP_WRONG",
  "new_entity_id": "SAP_S4HANA_CLOUD",
  "reason": "incorrect_fusion",
  "migrated_count": 15,
  "message": "Entity ORACLE_ERP_WRONG successfully deprecated and migrated to SAP_S4HANA_CLOUD"
}
```

#### Exemple cURL

```bash
curl -X POST http://localhost:8000/admin/ontology/deprecate \
  -H "Content-Type: application/json" \
  -d '{
    "old_entity_id": "ORACLE_ERP_WRONG",
    "new_entity_id": "SAP_S4HANA_CLOUD",
    "reason": "incorrect_fusion",
    "comment": "Oracle et SAP fusionnés à tort",
    "deprecated_by": "admin@example.com"
  }'
```

---

### Endpoint: GET `/admin/ontology/deprecated`

Lister toutes les entités dépréciées.

#### Query Parameters

- `tenant_id` (default: "default")
- `limit` (default: 100)

#### Response

```json
[
  {
    "entity_id": "ORACLE_ERP_WRONG",
    "canonical_name": "Oracle ERP Wrong",
    "entity_type": "PRODUCT",
    "deprecated_at": "2025-10-16T14:30:00Z",
    "deprecated_by": "admin@example.com",
    "new_entity_id": "SAP_S4HANA_CLOUD",
    "new_canonical_name": "SAP S/4HANA Cloud",
    "reason": "incorrect_fusion",
    "comment": "Oracle et SAP fusionnés à tort"
  }
]
```

---

### Endpoint: GET `/admin/ontology/pending`

Lister toutes les entités en attente validation.

#### Query Parameters

- `tenant_id` (default: "default")
- `limit` (default: 100)

#### Response

```json
[
  {
    "entity_id": "ORACLE_ERP_PENDING",
    "canonical_name": "Oracle ERP",
    "entity_type": "PRODUCT",
    "confidence": 0.82,
    "created_at": "2025-10-16T10:00:00Z",
    "created_by": "auto_learning",
    "requires_admin_validation": true
  }
]
```

---

## Profils Seuils Adaptatifs

### Configuration YAML (Recommandé)

**IMPORTANT**: Les seuils ne doivent **pas** être figés dans le code. Il faut créer un fichier de configuration YAML.

Exemple `config/canonicalization_thresholds.yaml`:

```yaml
# Profils seuils adaptatifs pour canonicalisation
profiles:
  SAP_OFFICIAL_DOCS:
    name: "SAP_OFFICIAL_DOCS"
    fuzzy_match_threshold: 0.90
    auto_validation_threshold: 0.95
    require_human_validation_below: 0.85
    promotion_threshold: 0.75
    description: "Documentation SAP officielle (haute qualité)"
    applies_to:
      domain: "sap_ecosystem"
      source: "official_documentation"

  INTERNAL_DOCS:
    name: "INTERNAL_DOCS"
    fuzzy_match_threshold: 0.85
    auto_validation_threshold: 0.95
    require_human_validation_below: 0.75
    promotion_threshold: 0.70
    description: "Documentation interne (qualité variable)"
    applies_to:
      source: "internal_documentation"

  COMMUNITY_CONTENT:
    name: "COMMUNITY_CONTENT"
    fuzzy_match_threshold: 0.80
    auto_validation_threshold: 0.97
    require_human_validation_below: 0.70
    promotion_threshold: 0.65
    description: "Contenu communautaire (forums, slides)"
    applies_to:
      source: ["forum_community", "presentation_slides", "emails_chat"]

  DEFAULT:
    name: "DEFAULT"
    fuzzy_match_threshold: 0.85
    auto_validation_threshold: 0.95
    require_human_validation_below: 0.80
    promotion_threshold: 0.70
    description: "Profil par défaut (balanced)"
```

### Personnalisation Admin

Les admins peuvent ajuster les seuils via l'interface admin (à implémenter en Phase 2):

1. **Page Admin** → Paramètres Canonicalisation
2. Modifier seuils par profil
3. Valider et sauvegarder
4. Rechargement automatique sans restart

---

## Exemples Decision Traces

### Cas 1: Match Exact Ontologie

```json
{
  "raw_name": "SAP S/4HANA Cloud",
  "strategies": [
    {
      "strategy": "ontology_lookup",
      "attempted": true,
      "success": true,
      "canonical_name": "SAP S/4HANA Cloud",
      "confidence": 1.0,
      "execution_time_ms": 8.2
    }
  ],
  "final_strategy": "ontology_lookup",
  "final_confidence": 1.0,
  "is_cataloged": true,
  "requires_validation": false,
  "auto_validated": true
}
```

### Cas 2: Match Structurel (Acronyme)

```json
{
  "raw_name": "S4H",
  "strategies": [
    {
      "strategy": "ontology_lookup",
      "attempted": true,
      "success": false,
      "confidence": 0.0
    },
    {
      "strategy": "fuzzy_matching",
      "attempted": true,
      "success": true,
      "canonical_name": "SAP S/4HANA Cloud",
      "confidence": 0.85,
      "execution_time_ms": 45.3,
      "metadata": {
        "method": "structural",
        "match_type": "acronym"
      }
    }
  ],
  "final_strategy": "fuzzy_matching",
  "final_confidence": 0.85,
  "is_cataloged": true,
  "requires_validation": false,
  "auto_validated": false
}
```

### Cas 3: Fallback (Pas Trouvé)

```json
{
  "raw_name": "Oracle Database 19c",
  "strategies": [
    {
      "strategy": "ontology_lookup",
      "attempted": true,
      "success": false
    },
    {
      "strategy": "fuzzy_matching",
      "attempted": true,
      "success": false
    }
  ],
  "final_strategy": "fallback",
  "final_canonical_name": "Oracle Database 19c",
  "final_confidence": 0.5,
  "is_cataloged": false,
  "requires_validation": true,
  "auto_validated": false
}
```

---

## FAQ & Troubleshooting

### Q: Comment savoir si une entité nécessite validation admin?

**R**: Vérifier le champ `requires_admin_validation` dans l'`OntologyEntity`. Si `true`, l'entité est en attente validation.

API: `GET /admin/ontology/pending` liste toutes les entités pending.

---

### Q: Que se passe-t-il si je déprécié une entité par erreur?

**R**: Le mécanisme de rollback permet de corriger. Créer une nouvelle entité `CORRECT_ENTITY` et déprécier `DEPRECATED_ENTITY` en pointant vers `CORRECT_ENTITY`. Les `CanonicalConcept` seront migrés automatiquement.

---

### Q: Les seuils adaptatifs sont-ils modifiables sans redéploiement?

**R**: **Non actuellement** (P1.1 a les seuils en dur dans le code). **Prochaine étape**: externaliser dans YAML/config pour permettre ajustements admin sans restart.

---

### Q: Comment débugger une décision de canonicalisation incorrecte?

**R**:
1. Récupérer le `CanonicalConcept` dans Neo4j
2. Lire le champ `decision_trace_json`
3. Analyser les stratégies tentées et les scores
4. Vérifier le `surface_form` pour voir le nom brut extrait
5. Si erreur: utiliser API rollback pour corriger

---

### Q: Quelle est la différence entre `surface_form` et `canonical_name`?

**R**:
- **`surface_form`**: Nom brut extrait par LLM, **jamais modifié** (ex: "sap s4hana")
- **`canonical_name`**: Nom normalisé après canonicalisation (ex: "SAP S/4HANA Cloud")

Permet de tracer: origin → canonical et de rollback si erreur.

---

### Q: Comment forcer la validation d'une entité pending?

**R**: Actuellement via Cypher direct:

```cypher
MATCH (ont:OntologyEntity {entity_id: "ENTITY_ID"})
SET ont.status = 'manual',
    ont.requires_admin_validation = false,
    ont.validated_by = 'admin@example.com',
    ont.validated_at = datetime()
RETURN ont
```

**Prochaine étape**: Endpoint API `POST /admin/ontology/validate` pour validation admin.

---

## Prochaines Évolutions (Roadmap Phase 2)

1. **Configuration YAML Seuils**: Externaliser seuils adaptatifs (pas figés code)
2. **Interface Admin UI**: Gestion visuelle entités pending, rollback, validation
3. **Métriques Qualité**: Dashboard qualité auto-learning (taux validation, erreurs, etc.)
4. **Suggestions LLM**: Propositions corrections via GPT-4o pour entités pending
5. **Notifications Temps Réel**: Webhook/email admin quand entité nécessite validation
6. **Tests Automatisés**: Suite tests P0.3 DecisionTrace, matching structurel

---

**Auteur**: Claude Code & Équipe OSMOSE
**Dernière Mise à Jour**: 2025-10-16
