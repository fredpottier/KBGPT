"""
Schémas Neo4j - Facts & Entities

Définit la structure Neo4j pour:
- Facts (first-class nodes)
- Entities
- Relations
- Constraints
- Indexes
"""

from typing import List


# ===================================
# SCHÉMA FACTS (FIRST-CLASS NODES)
# ===================================

CREATE_FACT_NODE_SCHEMA = """
// Node Fact (entité indépendante)
CREATE (f:Fact {
  // Identification
  uuid: $uuid,
  tenant_id: $tenant_id,

  // Triplet RDF étendu
  subject: $subject,
  predicate: $predicate,
  object: $object,

  // Valeur structurée (pour comparaison directe)
  value: $value,
  unit: $unit,
  value_type: $value_type,

  // Classification
  fact_type: $fact_type,

  // Gouvernance
  status: $status,
  confidence: $confidence,

  // Temporalité (bi-temporelle)
  valid_from: datetime($valid_from),
  valid_until: $valid_until,
  created_at: datetime(),
  updated_at: datetime(),

  // Traçabilité
  source_chunk_id: $source_chunk_id,
  source_document: $source_document,
  approved_by: $approved_by,
  approved_at: $approved_at,

  // Provenance
  extraction_method: $extraction_method,
  extraction_model: $extraction_model,
  extraction_prompt_id: $extraction_prompt_id
})
RETURN f
"""


# ===================================
# CONSTRAINTS (UNICITÉ & INTÉGRITÉ)
# ===================================

CONSTRAINTS: List[str] = [
    # Constraint UUID unique (seule contrainte supportée par Neo4j Community)
    """
    CREATE CONSTRAINT fact_uuid_unique IF NOT EXISTS
    FOR (f:Fact)
    REQUIRE f.uuid IS UNIQUE
    """,

    # Note: Les contraintes suivantes nécessitent Neo4j Enterprise:
    # - PROPERTY EXISTENCE (IS NOT NULL)
    # - PROPERTY TYPE enforcement (IS :: STRING)
    # - CHECK constraints (IN [...])
    #
    # Pour Community Edition, la validation est faite au niveau applicatif (queries.py)
]


# ===================================
# INDEXES (PERFORMANCE)
# ===================================

INDEXES: List[str] = [
    # Index multi-tenancy (CRITICAL)
    """
    CREATE INDEX fact_tenant_idx IF NOT EXISTS
    FOR (f:Fact)
    ON (f.tenant_id)
    """,

    # Index recherche rapide (tenant + subject + predicate)
    """
    CREATE INDEX fact_tenant_subject_predicate_idx IF NOT EXISTS
    FOR (f:Fact)
    ON (f.tenant_id, f.subject, f.predicate)
    """,

    # Index status (tenant + status)
    """
    CREATE INDEX fact_tenant_status_idx IF NOT EXISTS
    FOR (f:Fact)
    ON (f.tenant_id, f.status)
    """,

    # Index fact_type
    """
    CREATE INDEX fact_type_idx IF NOT EXISTS
    FOR (f:Fact)
    ON (f.fact_type)
    """,

    # Index temporel (valid_from)
    """
    CREATE INDEX fact_valid_from_idx IF NOT EXISTS
    FOR (f:Fact)
    ON (f.valid_from)
    """,

    # Index source_document
    """
    CREATE INDEX fact_source_document_idx IF NOT EXISTS
    FOR (f:Fact)
    ON (f.source_document)
    """,
]


# ===================================
# REQUÊTES CRUD FACTS
# ===================================

CREATE_FACT = """
CREATE (f:Fact {
  uuid: $uuid,
  tenant_id: $tenant_id,
  subject: $subject,
  predicate: $predicate,
  object: $object,
  value: $value,
  unit: $unit,
  value_type: $value_type,
  fact_type: $fact_type,
  status: $status,
  confidence: $confidence,
  valid_from: datetime($valid_from),
  valid_until: $valid_until,
  created_at: datetime(),
  updated_at: datetime(),
  source_chunk_id: $source_chunk_id,
  source_document: $source_document,
  approved_by: $approved_by,
  approved_at: $approved_at,
  extraction_method: $extraction_method,
  extraction_model: $extraction_model,
  extraction_prompt_id: $extraction_prompt_id
})
RETURN f
"""


GET_FACT_BY_UUID = """
MATCH (f:Fact {uuid: $uuid, tenant_id: $tenant_id})
RETURN f
"""


GET_FACTS_BY_STATUS = """
MATCH (f:Fact {tenant_id: $tenant_id, status: $status})
RETURN f
ORDER BY f.created_at DESC
LIMIT $limit
"""


GET_FACTS_BY_SUBJECT_PREDICATE = """
MATCH (f:Fact {
  tenant_id: $tenant_id,
  subject: $subject,
  predicate: $predicate
})
RETURN f
ORDER BY f.valid_from DESC
"""


UPDATE_FACT_STATUS = """
MATCH (f:Fact {uuid: $uuid, tenant_id: $tenant_id})
SET f.status = $status,
    f.updated_at = datetime(),
    f.approved_by = $approved_by,
    f.approved_at = CASE WHEN $status = 'approved' THEN datetime() ELSE f.approved_at END
RETURN f
"""


DELETE_FACT = """
MATCH (f:Fact {uuid: $uuid, tenant_id: $tenant_id})
DELETE f
"""


# ===================================
# DÉTECTION CONFLITS
# ===================================

DETECT_CONFLICTS = """
// Détecter CONTRADICTS et OVERRIDES
MATCH (f1:Fact {status: 'approved', tenant_id: $tenant_id})
MATCH (f2:Fact {status: 'proposed', tenant_id: $tenant_id})
WHERE f1.subject = f2.subject
  AND f1.predicate = f2.predicate
  AND f1.value <> f2.value

// Calculer type conflit
WITH f1, f2,
     CASE
       WHEN f2.valid_from > f1.valid_from THEN 'OVERRIDES'
       WHEN f2.valid_from = f1.valid_from THEN 'CONTRADICTS'
       ELSE 'OUTDATED'
     END as conflict_type,
     abs(toFloat(f1.value) - toFloat(f2.value)) / toFloat(f1.value) as value_diff_pct

WHERE conflict_type IN ['CONTRADICTS', 'OVERRIDES']

RETURN f1, f2, conflict_type, value_diff_pct
ORDER BY value_diff_pct DESC
"""


DETECT_DUPLICATES = """
// Détecter DUPLICATES (même valeur, sources différentes)
MATCH (f1:Fact {status: 'approved', tenant_id: $tenant_id})
MATCH (f2:Fact {status: 'proposed', tenant_id: $tenant_id})
WHERE f1.subject = f2.subject
  AND f1.predicate = f2.predicate
  AND f1.value = f2.value
  AND f1.source_document <> f2.source_document

RETURN f1, f2, 'DUPLICATE' as conflict_type
"""


# ===================================
# TIMELINE TEMPORELLE
# ===================================

GET_FACT_TIMELINE = """
// Historique complet d'un fact (point-in-time queries)
MATCH (f:Fact {
  tenant_id: $tenant_id,
  subject: $subject,
  predicate: $predicate,
  status: 'approved'
})
RETURN f.value, f.unit, f.valid_from, f.valid_until, f.source_document
ORDER BY f.valid_from DESC
"""


GET_FACT_AT_DATE = """
// Quel était le fact à une date donnée ?
MATCH (f:Fact {
  tenant_id: $tenant_id,
  subject: $subject,
  predicate: $predicate,
  status: 'approved'
})
WHERE f.valid_from <= datetime($target_date)
  AND (f.valid_until IS NULL OR f.valid_until > datetime($target_date))
RETURN f
"""


# ===================================
# STATISTIQUES & MONITORING
# ===================================

COUNT_FACTS_BY_STATUS = """
MATCH (f:Fact {tenant_id: $tenant_id})
RETURN f.status as status, count(f) as count
ORDER BY count DESC
"""


COUNT_FACTS_BY_TYPE = """
MATCH (f:Fact {tenant_id: $tenant_id})
RETURN f.fact_type as fact_type, count(f) as count
ORDER BY count DESC
"""


GET_CONFLICTS_COUNT = """
// Nombre de facts en conflit
MATCH (f1:Fact {status: 'approved', tenant_id: $tenant_id})
MATCH (f2:Fact {status: 'proposed', tenant_id: $tenant_id})
WHERE f1.subject = f2.subject
  AND f1.predicate = f2.predicate
  AND f1.value <> f2.value
RETURN count(f2) as conflicts_count
"""


# ===================================
# SCHÉMA ENTITIES (FUTUR PHASE 2)
# ===================================

CREATE_ENTITY_SCHEMA = """
// Node Entity
CREATE (e:Entity {
  uuid: $uuid,
  tenant_id: $tenant_id,
  name: $name,
  canonical_name: $canonical_name,
  entity_type: $entity_type,
  created_at: datetime(),
  updated_at: datetime()
})
RETURN e
"""


# ===================================
# CLEANUP & MAINTENANCE
# ===================================

DELETE_ALL_FACTS_TENANT = """
// ⚠️ DANGER: Supprimer tous les facts d'un tenant
MATCH (f:Fact {tenant_id: $tenant_id})
DELETE f
"""


DELETE_REJECTED_FACTS = """
// Nettoyer facts rejetés > 30 jours
MATCH (f:Fact {tenant_id: $tenant_id, status: 'rejected'})
WHERE f.updated_at < datetime() - duration({days: 30})
DELETE f
"""
