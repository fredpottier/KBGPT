# 🧠 Stratégie de Canonicalisation Auto-Apprenante - Phase 1.5

**Date**: 2025-10-16
**Objectif**: Minimiser intervention admin pour canonicalisation/rationalisation
**Approche**: Hybride intelligent (règles + fuzzy + LLM ponctuel + auto-learning)

---

## 🎯 Problématique Identifiée

### Workflow Historique (Intervention Admin Lourde)

```
1. Import documents
   └─> Extraction brute → Neo4j CanonicalConcepts
   └─> "SAP" × 5, "S/4HANA PCE", "S/4 Private Cloud", etc.

2. Admin Frontend (page Normalisation)
   └─> Visualise toutes les entités brutes
   └─> MANUELLEMENT:
       - Canonicalise: "S/4HANA PCE" → "SAP S/4HANA Cloud, Private Edition"
       - Rationalise (merge): "S/4HANA PCE" + "S/4 Private Cloud" → même entité
   └─> Sauvegarde ontologie → OntologyEntity + OntologyAlias

3. Prochains imports
   └─> EntityNormalizerNeo4j lookup → Trouve ontologie
   └─> Concepts correctement canonicalisés
```

**Problème**: Admin doit SYSTÉMATIQUEMENT intervenir après chaque import de nouveau domaine.

**Objectif Phase 1.5**: Automatiser 80-90% de la canonicalisation/rationalisation, admin intervient seulement pour edge cases.

---

## 🧩 Composants Existants (Réutilisables)

### 1. EntityNormalizerNeo4j (Lookup Ontologie)
**Fichier**: `src/knowbase/ontology/entity_normalizer_neo4j.py`

```python
def normalize_entity_name(
    raw_name: str,
    entity_type_hint: Optional[str] = None,
    tenant_id: str = "default"
) -> Tuple[Optional[str], str, Optional[str], bool]:
    """
    Lookup ontologie Neo4j via index normalized.

    Returns:
        (entity_id, canonical_name, entity_type, is_cataloged)
    """
```

**Fonctionnalités**:
- ✅ Lookup O(1) via index Neo4j normalized
- ✅ Correction automatique type si LLM se trompe
- ✅ Support multi-tenant
- ✅ Domaine-agnostic (pas de fichiers statiques)

**Utilisation**: Lookup avant création CanonicalConcept pour trouver ontologie existante.

---

### 2. FuzzyMatcherService (Similarité Textuelle)
**Fichier**: `src/knowbase/api/services/fuzzy_matcher_service.py`

```python
def match_entity_to_ontology(
    entity_name: str,
    ontology_entry: Dict
) -> Tuple[bool, float, str]:
    """
    Fuzzy matching via fuzzywuzzy.

    Seuils:
    - >= 90%: Auto-match (haute confiance)
    - 75-89%: Match suggéré (confirmation manuelle)
    - < 75%: Pas de match
    """
```

**Fonctionnalités**:
- ✅ Similarité Levenshtein (fuzz.ratio)
- ✅ Test canonical_name + tous aliases
- ✅ Seuils adaptatifs (auto vs manuel)
- ✅ Preview merge_groups pour admin

**Utilisation**: Détecter doublons/variantes AVANT création CanonicalConcept.

---

### 3. OntologySaver (Persistance Ontologie)
**Fichier**: `src/knowbase/ontology/ontology_saver.py`

```python
def save_ontology_to_neo4j(
    merge_groups: List[Dict],
    entity_type: str,
    tenant_id: str = "default",
    source: str = "llm_generated"
):
    """
    Sauvegarde ontologie validée dans Neo4j.

    Workflow:
    1. Créer OntologyEntity (canonical_name, entity_id)
    2. Créer OntologyAlias pour chaque variante
    3. Lien OntologyEntity -[:HAS_ALIAS]-> OntologyAlias
    """
```

**Fonctionnalités**:
- ✅ Stockage OntologyEntity + OntologyAlias
- ✅ Support source = "llm_generated" | "manual" | "auto_learned"
- ✅ Auto-merge aliases

**Utilisation**: Sauvegarder automatiquement les normalisations découvertes.

---

### 4. EmbeddingsContextualScorer (Similarité Sémantique)
**Fichier**: `src/knowbase/agents/gatekeeper/embeddings_contextual_scorer.py`

```python
# Modèle: sentence-transformers/paraphrase-multilingual-mpnet-base-v2
# Fonctionnalités:
# - Embeddings multilingues (FR/EN/DE/ES)
# - Cosine similarity entre concepts
# - Détection rôle (PRIMARY, COMPETITOR, SECONDARY)
```

**Fonctionnalités**:
- ✅ Embeddings sémantiques multilingues
- ✅ Détection similarité contextuelle
- ✅ <200ms, 100% offline, $0 coût

**Utilisation**: Détecter concepts sémantiquement proches même si orthographe différente.

---

## 🚀 Stratégie Hybride Auto-Apprenante (Proposée)

### Vue d'Ensemble

```
┌──────────────────────────────────────────────────────────────────┐
│ Phase A: Import Real-Time (AUTOMATIQUE)                         │
├──────────────────────────────────────────────────────────────────┤
│ 1. Extraction concepts → ProtoConcepts                          │
│ 2. Pour chaque ProtoConcept:                                    │
│    a) Sélection canonicalisation (heuristique)                  │
│    b) Lookup ontologie existante (EntityNormalizerNeo4j)        │
│    c) Fuzzy matching variants (FuzzyMatcherService ≥90%)        │
│    d) LLM léger canonicalization (GPT-4o-mini, ~$0.0001/call)  │
│    e) Règles heuristiques simples (acronymes, noms propres)    │
│    f) Fallback: Garde tel quel si incertain                    │
│ 3. Déduplication CanonicalConcepts (même canonical_name)        │
│ 4. Promotion Proto → Canonical avec canonical_name normalisé    │
│                                                                  │
│ ✅ 90-92% automatiquement corrects (avec LLM léger)             │
│ ⚠️ 8-10% nécessitent apprentissage (nouveaux domaines)         │
│ 💰 Coût: ~$0.006/import (60 concepts × GPT-4o-mini)            │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│ Phase B: Post-Import Auto-Learning (PONCTUEL - 1x/semaine)      │
├──────────────────────────────────────────────────────────────────┤
│ 1. Détecter concepts "non catalogués" accumulés                 │
│ 2. Clustering automatique:                                      │
│    - Fuzzy matching (75-89% similarité)                         │
│    - Embeddings similarity (cosine ≥0.85)                       │
│ 3. LLM batch normalization (GPT-4o-mini):                       │
│    - Input: Clusters détectés                                   │
│    - Output: canonical_name + merge_groups                      │
│    - Coût: ~$0.50 pour 200 concepts                            │
│ 4. Sauvegarde automatique ontologie (OntologySaver)            │
│ 5. Logging pour review admin (optionnel)                       │
│                                                                  │
│ ✅ +20-30% concepts normalisés automatiquement                  │
│ ⚠️ 0-5% edge cases nécessitent validation admin                │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│ Phase C: Admin Review (OPTIONNEL - si doute)                    │
├──────────────────────────────────────────────────────────────────┤
│ 1. Frontend Admin affiche concepts "low confidence"             │
│ 2. Admin valide/corrige merge_groups                            │
│ 3. Sauvegarde ontologie avec source="manual"                    │
│                                                                  │
│ ✅ Admin intervient seulement si nécessaire (5-10% cas)         │
└──────────────────────────────────────────────────────────────────┘
```

---

## 📋 Algorithme Détaillé - Phase A (Import Real-Time)

### Modification Gatekeeper._promote_concepts_tool()

**Fichier**: `src/knowbase/agents/gatekeeper/gatekeeper.py`

```python
def _promote_concepts_tool(self, tool_input: PromoteConceptsInput) -> ToolOutput:
    """
    Promeut concepts avec canonicalisation auto-apprenante.

    Workflow:
    1. Sélection: Concepts "importants" uniquement
    2. Normalisation: Lookup ontologie + fuzzy + règles
    3. Déduplication: Éviter doublons CanonicalConcepts
    4. Promotion: Proto → Canonical avec canonical_name normalisé
    5. Auto-learning: Logger concepts non catalogués
    """

    concepts = tool_input.concepts
    tenant_id = tool_input.tenant_id

    promoted = []
    canonical_cache = {}  # {canonical_name: canonical_id}
    uncataloged_concepts = []  # Pour auto-learning différé

    for concept in concepts:
        concept_name = concept.get("name", "")
        concept_type = concept.get("type", "Unknown")

        # ═══════════════════════════════════════════════════════════
        # ÉTAPE 1: Décider si canonicalisation nécessaire
        # ═══════════════════════════════════════════════════════════

        if not self._should_canonicalize(concept_name, concept_type):
            # Terme basique/langage commun → Garde tel quel
            canonical_name = concept_name.strip()
            is_cataloged = False
            source = "basic_term"

        else:
            # ═══════════════════════════════════════════════════════
            # ÉTAPE 2: Tentative normalisation automatique
            # ═══════════════════════════════════════════════════════

            canonical_name, is_cataloged, source = self._normalize_concept_auto(
                concept_name=concept_name,
                concept_type=concept_type,
                tenant_id=tenant_id
            )

            # Logger concepts non catalogués pour auto-learning
            if not is_cataloged:
                uncataloged_concepts.append({
                    "name": concept_name,
                    "type": concept_type,
                    "canonical_name": canonical_name,
                    "segment_id": concept.get("segment_id"),
                    "confidence": concept.get("confidence", 0.0)
                })

        # ═══════════════════════════════════════════════════════════
        # ÉTAPE 3: Déduplication CanonicalConcepts
        # ═══════════════════════════════════════════════════════════

        if canonical_name in canonical_cache:
            # CanonicalConcept existe déjà → Réutiliser
            canonical_id = canonical_cache[canonical_name]

            # Créer ProtoConcept et lier à Canonical existant
            proto_concept_id = self.neo4j_client.create_proto_concept(...)

            self.neo4j_client.link_proto_to_canonical(
                proto_concept_id=proto_concept_id,
                canonical_id=canonical_id
            )

            logger.debug(
                f"✅ Dédupliqué: '{concept_name}' → Canonical existant '{canonical_name}'"
            )

        else:
            # Nouveau CanonicalConcept → Créer
            proto_concept_id = self.neo4j_client.create_proto_concept(
                tenant_id=tenant_id,
                concept_name=concept_name,
                concept_type=concept_type,
                segment_id=concept.get("segment_id", "unknown"),
                document_id=concept.get("document_id", "unknown"),
                extraction_method=concept.get("extraction_method", "NER"),
                confidence=concept.get("confidence", 0.0),
                metadata={
                    "original_name": concept_name,
                    "is_cataloged": is_cataloged,
                    "normalization_source": source
                }
            )

            canonical_id = self.neo4j_client.promote_to_published(
                tenant_id=tenant_id,
                proto_concept_id=proto_concept_id,
                canonical_name=canonical_name,
                unified_definition=concept.get("definition", ""),
                quality_score=concept.get("confidence", 0.0),
                metadata={
                    "is_cataloged": is_cataloged,
                    "normalization_source": source
                }
            )

            # Mettre en cache
            canonical_cache[canonical_name] = canonical_id

            if is_cataloged:
                logger.info(
                    f"✅ Catalogué: '{concept_name}' → '{canonical_name}' "
                    f"(source={source})"
                )
            else:
                logger.debug(
                    f"⚠️ Non catalogué: '{concept_name}' → '{canonical_name}' "
                    f"(à apprendre)"
                )

        promoted.append({
            "concept_id": proto_concept_id,
            "canonical_id": canonical_id,
            "canonical_name": canonical_name,
            "is_cataloged": is_cataloged
        })

    # ═══════════════════════════════════════════════════════════════
    # ÉTAPE 4: Logger concepts non catalogués pour auto-learning
    # ═══════════════════════════════════════════════════════════════

    if len(uncataloged_concepts) > 0:
        self._log_uncataloged_for_learning(
            uncataloged_concepts=uncataloged_concepts,
            tenant_id=tenant_id
        )

        logger.info(
            f"📝 {len(uncataloged_concepts)} concepts non catalogués "
            f"loggés pour auto-learning"
        )

    return PromoteConceptsOutput(
        success=True,
        message=f"Promoted {len(promoted)} concepts "
                f"({len([p for p in promoted if p['is_cataloged']])} cataloged, "
                f"{len(uncataloged_concepts)} to learn)",
        promoted_concepts=promoted
    )


def _should_canonicalize(self, concept_name: str, concept_type: str) -> bool:
    """
    Détermine si concept doit être canonicalisé.

    Critères:
    1. Type "important": SOLUTION, PRODUCT, COMPANY, TECHNOLOGY, ACRONYM
    2. OU Nom propre: commence par majuscule + > 1 mot
    3. OU Contient acronyme: mots en MAJUSCULES (SAP, ERP)
    4. OU Contient caractères spéciaux: /, -, _

    Exclure:
    - Concepts génériques: "management", "system", "process"
    - Langage commun: "customer", "data", "report"
    """
    IMPORTANT_TYPES = {
        "SOLUTION", "PRODUCT", "COMPONENT", "MODULE",
        "COMPANY", "VENDOR", "PARTNER",
        "TECHNOLOGY", "PLATFORM", "TOOL", "FRAMEWORK",
        "ACRONYM", "STANDARD", "PROTOCOL", "API"
    }

    # Type important
    if concept_type in IMPORTANT_TYPES:
        return True

    # Nom propre (capital + multi-words)
    words = concept_name.split()
    if len(words) > 1 and words[0][0].isupper():
        return True

    # Contient acronyme (2+ majuscules consécutives)
    if re.search(r'[A-Z]{2,}', concept_name):
        return True

    # Contient caractères spéciaux
    if re.search(r'[/\-_]', concept_name):
        return True

    # Sinon: terme générique
    return False


def _normalize_concept_auto(
    self,
    concept_name: str,
    concept_type: str,
    tenant_id: str
) -> Tuple[str, bool, str]:
    """
    Normalisation automatique multi-stratégies.

    Stratégies (ordre de priorité):
    1. Lookup ontologie Neo4j (EntityNormalizerNeo4j)
    2. Fuzzy matching variantes (FuzzyMatcherService ≥90%)
    3. LLM léger canonicalization (GPT-4o-mini, ~$0.0001/concept)
    4. Règles heuristiques (acronymes, casse)
    5. Fallback: Garde tel quel

    Returns:
        (canonical_name, is_cataloged, source)
        - canonical_name: Nom normalisé
        - is_cataloged: True si trouvé dans ontologie
        - source: "ontology" | "fuzzy" | "llm" | "heuristic" | "fallback"
    """

    # ───────────────────────────────────────────────────────────────
    # Stratégie 1: Lookup Ontologie Existante (Prioritaire)
    # ───────────────────────────────────────────────────────────────

    entity_id, canonical_name, real_type, is_cataloged = \
        self.entity_normalizer.normalize_entity_name(
            raw_name=concept_name,
            entity_type_hint=concept_type,
            tenant_id=tenant_id
        )

    if is_cataloged:
        # Trouvé dans ontologie → Utiliser canonical_name
        return (canonical_name, True, "ontology")

    # ───────────────────────────────────────────────────────────────
    # Stratégie 2: Fuzzy Matching (Seuil 90% auto-match)
    # ───────────────────────────────────────────────────────────────

    # Récupérer toutes les OntologyEntities du même type
    ontology_entries = self._get_ontology_entries_by_type(
        entity_type=concept_type,
        tenant_id=tenant_id
    )

    for ontology_entry in ontology_entries:
        is_match, score, matched_name = self.fuzzy_matcher.match_entity_to_ontology(
            entity_name=concept_name,
            ontology_entry=ontology_entry
        )

        if score >= 90:  # Auto-match haute confiance
            return (
                ontology_entry["canonical_name"],
                True,
                f"fuzzy:{score}"
            )

    # ───────────────────────────────────────────────────────────────
    # Stratégie 3: LLM Léger Canonicalization (GPT-4o-mini)
    # ───────────────────────────────────────────────────────────────

    # Seulement pour concepts "importants" (pas langage commun)
    # Et si budget LLM SMALL disponible
    if self._is_important_concept(concept_name, concept_type):
        if self.state.budget_remaining.get("SMALL", 0) > 0:
            try:
                canonical_from_llm = self._llm_canonicalize_single(
                    concept_name=concept_name,
                    concept_type=concept_type
                )

                if canonical_from_llm:
                    # LLM a proposé normalisation
                    logger.info(
                        f"🤖 LLM canonicalisé: '{concept_name}' → '{canonical_from_llm}'"
                    )

                    # Décrémenter budget SMALL
                    self.state.budget_remaining["SMALL"] -= 1
                    self.state.llm_calls_count["SMALL"] += 1

                    return (canonical_from_llm, False, "llm:gpt-4o-mini")

            except Exception as e:
                logger.warning(
                    f"[GATEKEEPER] LLM canonicalization failed for '{concept_name}': {e}"
                )
                # Continue vers stratégies suivantes

    # ───────────────────────────────────────────────────────────────
    # Stratégie 4: Règles Heuristiques Simples
    # ───────────────────────────────────────────────────────────────

    # Règle: Acronymes en MAJUSCULES (SAP, ERP, CRM, etc.)
    if concept_name.isupper() and len(concept_name) >= 2:
        return (concept_name.upper(), False, "heuristic:acronym")

    # Règle: Noms propres avec casse préservée
    if concept_name[0].isupper():
        # Préserver casse originale (éviter .title())
        return (concept_name.strip(), False, "heuristic:proper_noun")

    # ───────────────────────────────────────────────────────────────
    # Stratégie 5: Fallback (Garde tel quel)
    # ───────────────────────────────────────────────────────────────

    return (concept_name.strip(), False, "fallback")


def _is_important_concept(self, concept_name: str, concept_type: str) -> bool:
    """
    Détermine si concept mérite un appel LLM pour canonicalization.

    Critères:
    - Types SOLUTION, PRODUCT, COMPANY, TECHNOLOGY, ACRONYM
    - OU Noms propres (commence par majuscule)
    - OU Contient acronyme (SAP, ERP)
    - OU Contient caractères spéciaux (/, -, _)

    Exclure:
    - Termes basiques: "management", "system", "process"
    - Langage commun: "customer", "data", "report"
    """
    IMPORTANT_TYPES = {
        "SOLUTION", "PRODUCT", "COMPONENT", "MODULE",
        "COMPANY", "VENDOR", "PARTNER",
        "TECHNOLOGY", "PLATFORM", "TOOL", "FRAMEWORK",
        "ACRONYM", "STANDARD", "PROTOCOL", "API"
    }

    # Type important
    if concept_type in IMPORTANT_TYPES:
        return True

    # Nom propre (capital + multi-words)
    words = concept_name.split()
    if len(words) > 1 and words[0][0].isupper():
        return True

    # Contient acronyme (2+ majuscules consécutives)
    if re.search(r'[A-Z]{2,}', concept_name):
        return True

    # Contient caractères spéciaux
    if re.search(r'[/\-_]', concept_name):
        return True

    # Sinon: terme générique, pas important
    return False


def _llm_canonicalize_single(
    self,
    concept_name: str,
    concept_type: str
) -> Optional[str]:
    """
    Canonicalisation LLM léger pour un concept individuel.

    Utilise GPT-4o-mini (task: "canonicalization") pour normaliser.

    Prompt:
    "Given this entity: 'S/4HANA PCE' (type: SOLUTION),
     what is the official canonical name? Reply ONLY with the canonical name,
     or 'UNKNOWN' if uncertain."

    Returns:
        Canonical name ou None si LLM incertain
    """
    prompt = f"""You are an expert in entity normalization.

Given this entity:
- Name: "{concept_name}"
- Type: {concept_type}

Task: Provide the official canonical name for this entity.

Rules:
1. If it's a well-known product/company/technology, use its official name
2. Preserve proper casing (e.g., "SAP" not "Sap", "S/4HANA" not "S/4hana")
3. Use full official names when available (e.g., "SAP S/4HANA Cloud, Private Edition" not "S/4HANA PCE")
4. If uncertain or it's a generic term, reply with "UNKNOWN"

Reply ONLY with the canonical name (or "UNKNOWN"), nothing else.

Example:
Input: "S/4HANA PCE" (SOLUTION)
Output: SAP S/4HANA Cloud, Private Edition

Input: "management" (CONCEPT)
Output: UNKNOWN

Your turn:
Input: "{concept_name}" ({concept_type})
Output:"""

    try:
        # Appel LLM via dispatcher (utilise config canonicalization: gpt-4o-mini, temp=0, max_tokens=100)
        response = self.llm_client.call_llm(
            task="canonicalization",
            messages=[{"role": "user", "content": prompt}]
        )

        canonical = response["content"].strip()

        if canonical == "UNKNOWN" or canonical == concept_name:
            # LLM incertain ou pas de changement
            return None

        return canonical

    except Exception as e:
        logger.error(f"[GATEKEEPER] LLM call failed: {e}")
        return None


def _log_uncataloged_for_learning(
    self,
    uncataloged_concepts: List[Dict],
    tenant_id: str
):
    """
    Logger concepts non catalogués pour auto-learning différé.

    Options:
    1. Logger simple (fichier/DB)
    2. Créer nodes :UncatalogedConcept dans Neo4j
    3. Accumuler dans Redis queue pour batch LLM
    """

    # Option 2: Créer nodes temporaires Neo4j pour tracking
    for concept in uncataloged_concepts:
        self.neo4j_client.log_uncataloged_concept(
            concept_name=concept["name"],
            concept_type=concept["type"],
            canonical_name=concept["canonical_name"],
            segment_id=concept["segment_id"],
            confidence=concept["confidence"],
            tenant_id=tenant_id
        )
```

---

## 📋 Algorithme Détaillé - Phase B (Auto-Learning Ponctuel)

### Service Auto-Learning Batch (Nouveau)

**Fichier**: `src/knowbase/ontology/auto_learning_service.py`

```python
class AutoLearningService:
    """
    Service d'auto-apprentissage ponctuel via LLM batch.

    Workflow:
    1. Détecter concepts non catalogués accumulés
    2. Clustering automatique (fuzzy + embeddings)
    3. LLM batch normalization (GPT-4o-mini)
    4. Sauvegarde automatique ontologie
    5. Notification admin pour review (optionnel)
    """

    def __init__(
        self,
        neo4j_client,
        fuzzy_matcher,
        embeddings_scorer,
        llm_client
    ):
        self.neo4j_client = neo4j_client
        self.fuzzy_matcher = fuzzy_matcher
        self.embeddings_scorer = embeddings_scorer
        self.llm_client = llm_client

    def run_auto_learning_batch(
        self,
        tenant_id: str = "default",
        min_concepts: int = 20,
        llm_model: str = "gpt-4o-mini"
    ) -> Dict:
        """
        Exécute batch auto-learning sur concepts non catalogués.

        Args:
            tenant_id: Tenant ID
            min_concepts: Minimum concepts pour déclencher learning
            llm_model: Modèle LLM (gpt-4o-mini recommandé, coût faible)

        Returns:
            Dict avec résultats:
            {
                "concepts_analyzed": 47,
                "clusters_detected": 12,
                "ontology_entries_created": 12,
                "cost_usd": 0.52,
                "time_seconds": 15.3,
                "admin_review_required": ["CLUSTER_23", "CLUSTER_45"]
            }
        """

        # ═══════════════════════════════════════════════════════════
        # ÉTAPE 1: Récupérer concepts non catalogués
        # ═══════════════════════════════════════════════════════════

        uncataloged_concepts = self.neo4j_client.get_uncataloged_concepts(
            tenant_id=tenant_id,
            limit=500
        )

        if len(uncataloged_concepts) < min_concepts:
            logger.info(
                f"[AUTO-LEARNING] Seulement {len(uncataloged_concepts)} concepts, "
                f"attendu {min_concepts} minimum. Skip."
            )
            return {"concepts_analyzed": 0}

        logger.info(
            f"[AUTO-LEARNING] Traitement {len(uncataloged_concepts)} concepts "
            f"non catalogués..."
        )

        # ═══════════════════════════════════════════════════════════
        # ÉTAPE 2: Clustering Automatique
        # ═══════════════════════════════════════════════════════════

        clusters = self._cluster_similar_concepts(
            concepts=uncataloged_concepts,
            fuzzy_threshold=75,
            embeddings_threshold=0.85
        )

        logger.info(f"[AUTO-LEARNING] {len(clusters)} clusters détectés")

        # ═══════════════════════════════════════════════════════════
        # ÉTAPE 3: LLM Batch Normalization
        # ═══════════════════════════════════════════════════════════

        ontology_entries = []
        low_confidence_clusters = []
        total_cost = 0.0

        for cluster in clusters:
            # LLM normalization pour cluster
            result = self._normalize_cluster_with_llm(
                cluster=cluster,
                llm_model=llm_model
            )

            if result["confidence"] >= 0.85:
                # Haute confiance → Auto-sauvegarde
                ontology_entries.append(result["ontology_entry"])
                total_cost += result["cost_usd"]
            else:
                # Basse confiance → Admin review
                low_confidence_clusters.append(cluster["cluster_id"])

        logger.info(
            f"[AUTO-LEARNING] {len(ontology_entries)} ontologies créées, "
            f"{len(low_confidence_clusters)} nécessitent review admin"
        )

        # ═══════════════════════════════════════════════════════════
        # ÉTAPE 4: Sauvegarde Automatique Ontologie
        # ═══════════════════════════════════════════════════════════

        for ontology_entry in ontology_entries:
            save_ontology_to_neo4j(
                merge_groups=[ontology_entry],
                entity_type=ontology_entry["entity_type"],
                tenant_id=tenant_id,
                source="auto_learned"
            )

        # ═══════════════════════════════════════════════════════════
        # ÉTAPE 5: Marquer Concepts Comme Appris
        # ═══════════════════════════════════════════════════════════

        for ontology_entry in ontology_entries:
            for entity_name in ontology_entry["entities"]:
                self.neo4j_client.mark_concept_as_learned(
                    concept_name=entity_name,
                    tenant_id=tenant_id
                )

        return {
            "concepts_analyzed": len(uncataloged_concepts),
            "clusters_detected": len(clusters),
            "ontology_entries_created": len(ontology_entries),
            "cost_usd": total_cost,
            "admin_review_required": low_confidence_clusters
        }

    def _cluster_similar_concepts(
        self,
        concepts: List[Dict],
        fuzzy_threshold: int = 75,
        embeddings_threshold: float = 0.85
    ) -> List[Dict]:
        """
        Clustering automatique via fuzzy + embeddings.

        Stratégies:
        1. Fuzzy matching (Levenshtein ≥75%)
        2. Embeddings similarity (cosine ≥0.85)
        3. Transitive closure (si A~B et B~C alors A~C)

        Returns:
            Liste clusters:
            [
                {
                    "cluster_id": "CLUSTER_1",
                    "concepts": ["S/4HANA PCE", "S/4 Private Cloud", ...],
                    "concept_type": "SOLUTION",
                    "similarity_scores": [0.92, 0.87, ...]
                }
            ]
        """
        # Implémenter clustering (union-find ou graph clustering)
        pass

    def _normalize_cluster_with_llm(
        self,
        cluster: Dict,
        llm_model: str
    ) -> Dict:
        """
        Normalisation cluster via LLM.

        Prompt LLM:
        "Given these product variants: ['S/4HANA PCE', 'S/4 Private Cloud', 'SAP S4 HANA Private'],
         what is the official canonical name? Provide confidence score."

        Returns:
            {
                "ontology_entry": {
                    "canonical_key": "SAP_S4HANA_CLOUD_PRIVATE",
                    "canonical_name": "SAP S/4HANA Cloud, Private Edition",
                    "entities": ["S/4HANA PCE", "S/4 Private Cloud", ...],
                    "entity_type": "SOLUTION"
                },
                "confidence": 0.95,
                "cost_usd": 0.004
            }
        """
        # Appel LLM avec structured output
        pass
```

---

## 🎛️ Configuration et Déclenchement

### Option 1: Cron Job (Recommandé)

```bash
# Tous les dimanches à 3h du matin
0 3 * * 0 docker-compose exec app python -m knowbase.ontology.auto_learning_batch

# Script auto_learning_batch.py
from knowbase.ontology.auto_learning_service import AutoLearningService

service = AutoLearningService(...)
result = service.run_auto_learning_batch(
    tenant_id="default",
    min_concepts=20,
    llm_model="gpt-4o-mini"
)

print(f"✅ Auto-learning terminé: {result}")

if len(result["admin_review_required"]) > 0:
    # Envoyer notification admin
    send_admin_notification(result)
```

### Option 2: Trigger Manuel Admin

```python
# Frontend Admin: Bouton "Apprendre Concepts"
POST /api/admin/auto-learning/trigger
{
    "tenant_id": "default",
    "min_concepts": 20,
    "llm_model": "gpt-4o-mini"
}

# Backend route
@router.post("/api/admin/auto-learning/trigger")
async def trigger_auto_learning(request: AutoLearningRequest):
    service = AutoLearningService(...)
    result = await service.run_auto_learning_batch(...)
    return result
```

### Option 3: Automatique Post-Import

```python
# Dans osmose_agentique.py, après traitement document

if concepts_count > 0:
    # Check si seuil atteint
    uncataloged_count = neo4j_client.count_uncataloged_concepts(tenant_id)

    if uncataloged_count >= 50:
        logger.info(
            f"[AUTO-LEARNING] {uncataloged_count} concepts accumulés, "
            "déclenchement auto-learning..."
        )

        service = AutoLearningService(...)
        result = service.run_auto_learning_batch(tenant_id)

        logger.info(f"[AUTO-LEARNING] Résultat: {result}")
```

---

## 📊 Estimation Impact et Coût

### Scénario Typique: Import 10 Documents SAP

#### Avant (Intervention Admin Lourde)
```
Import 10 docs → 500 concepts extraits
├─> 300 doublons (même concept plusieurs fois)
├─> 150 variantes non normalisées ("S/4HANA PCE" vs "SAP S/4HANA Cloud Private")
└─> Admin passe 2-3 heures à normaliser manuellement
```

#### Après (Auto-Learning Hybride avec LLM Phase A)
```
Import 10 docs → 500 concepts extraits

Phase A (Import Real-Time avec LLM léger):
├─> 350 concepts trouvés dans ontologie (70%) → Automatique ✅
├─> 50 concepts normalisés via fuzzy ≥90% (10%) → Automatique ✅
├─> 60 concepts canonicalisés via LLM SMALL (12%) → Automatique ✅ (~$0.006)
├─> 100 doublons évités via déduplication → Automatique ✅
├─> 40 concepts non catalogués restants (8%) → Loggés pour learning ⚠️

Phase B (Auto-Learning Post-Import - optionnel):
├─> 40 concepts → 10 clusters détectés
├─> LLM normalization → 8 ontologies créées (confiance ≥85%) ✅
├─> 2 clusters ambigus → Admin review ⚠️
└─> Coût LLM: ~$0.40 (gpt-4o-mini batch)

Résultat:
├─> 98% automatiquement corrects (490/500)
├─> 2% nécessitent review admin (10/500, ~10 minutes)
└─> Gain temps: 2h45 → 10 minutes (94% réduction)
└─> Coût LLM total: $0.006 (Phase A) + $0.40 (Phase B) = ~$0.41/import
```

### Détail Coûts LLM

#### Phase A (Real-Time LLM Canonicalization)
```
60 concepts × GPT-4o-mini (task: canonicalization)
├─> Input: ~80 tokens/concept (prompt + concept)
├─> Output: ~20 tokens/concept (canonical name)
├─> Total: 60 × 100 tokens = 6,000 tokens
└─> Coût: $0.15/1M input + $0.60/1M output ≈ $0.006

Budget SMALL: 120 appels/document (défini dans AgentState)
└─> Permet jusqu'à 120 canonicalisations LLM sans surcoût
```

#### Phase B (Batch LLM Normalization)
```
40 concepts → 10 clusters
├─> 10 appels LLM (1 par cluster)
├─> Input: ~200 tokens/cluster (variantes + context)
├─> Output: ~50 tokens/cluster (canonical + aliases)
└─> Coût: 10 × 250 tokens ≈ $0.40
```

### Coûts Estimés Comparatifs

| Stratégie | Coût LLM/import | Temps Admin/import | Qualité | ROI |
|-----------|-----------------|-------------------|---------|-----|
| **Historique (100% admin)** | $0 | 2-3h | 100% | Baseline |
| **Phase A sans LLM** | $0 | 30min | 80% | +75% temps |
| **Phase A avec LLM** | $0.01 | 20min | 92% | +85% temps |
| **Phase A + B (complet)** | $0.41 | 10min | 98% | **+94% temps** |

**Coût admin @ $50/h**: Économie 2h30 = **$125/import**
**Coût LLM Phase A+B**: $0.41/import
**ROI net**: **$124.59/import (99.7% économie)**

**Recommandation**: Phase A avec LLM + Phase B hebdomadaire.

---

### Justification LLM Phase A

**Pourquoi ajouter LLM en Phase A ?**

1. **Coût négligeable** : $0.006/import (60 concepts × $0.0001)
2. **Amélioration qualité** : +12% précision (80% → 92%)
3. **Réduction Phase B** : Moins de concepts à apprendre en batch
4. **Real-time** : Admin voit résultats corrects immédiatement
5. **Budget contrôlé** : Max 120 appels SMALL/document (hard cap)

**Trade-off acceptable** :
- ✅ +$0.006 coût LLM
- ✅ +12% qualité immédiate
- ✅ -50% concepts à apprendre en Phase B
- ✅ -10 minutes temps admin

**Alternative si budget serré** : Désactiver LLM Phase A, utiliser seulement Phase B hebdomadaire.

---

## 🚦 Plan d'Implémentation

### P0: Phase A (Import Real-Time) - 4-5 jours

1. **Jour 1-2**: Intégrer `EntityNormalizerNeo4j` + `FuzzyMatcherService` dans Gatekeeper
   - Modifier `_promote_concepts_tool()`
   - Implémenter `_should_canonicalize()`
   - Implémenter `_normalize_concept_auto()`

2. **Jour 3**: Déduplication CanonicalConcepts
   - Cache en mémoire `{canonical_name: canonical_id}`
   - Méthode `neo4j_client.link_proto_to_canonical()`

3. **Jour 4**: Logging concepts non catalogués
   - Créer nodes `:UncatalogedConcept` dans Neo4j
   - Logger métadonnées pour clustering

4. **Jour 5**: Tests et validation
   - Import document test → Vérifier canonicalisation
   - Vérifier déduplication fonctionne
   - Vérifier concepts loggés

### P1: Phase B (Auto-Learning) - 5-6 jours

1. **Jour 6-7**: Clustering automatique
   - Implémenter fuzzy clustering
   - Implémenter embeddings clustering
   - Transitive closure

2. **Jour 8-9**: LLM batch normalization
   - Prompt engineering pour normalisation
   - Structured output (JSON)
   - Gestion confiance/seuils

3. **Jour 10**: Sauvegarde automatique
   - Intégrer `OntologySaver`
   - Marquer concepts comme appris
   - Notification admin si low confidence

4. **Jour 11**: Tests et déploiement
   - Test cron job
   - Test manuel trigger
   - Validation résultats

### P2: Frontend Admin Review (Optionnel) - 3-4 jours

1. **Jour 12-13**: Page Admin "Auto-Learning Review"
   - Liste clusters low confidence
   - Preview merge_groups
   - Validation/correction manuelle

2. **Jour 14-15**: Intégration workflow complet
   - Tests end-to-end
   - Documentation admin

---

## ✅ Validation Critères de Succès

### Critères Quantitatifs
- ✅ ≥90% concepts automatiquement normalisés (sans admin)
- ✅ ≥95% doublons évités via déduplication
- ✅ ≤10% concepts nécessitent review admin
- ✅ Coût LLM ≤$1 pour 200 concepts
- ✅ Temps admin réduit de ≥80% (3h → 30min)

### Critères Qualitatifs
- ✅ Domaine-agnostic (fonctionne pour SAP, Finance, IT, etc.)
- ✅ Auto-apprentissage progressif (amélioration continue)
- ✅ Transparence (logs, confidence scores)
- ✅ Admin garde contrôle (validation finale possible)

---

## 📝 Conclusion

Cette stratégie hybride combine:

1. **Real-time** (Phase A): Normalisation immédiate via ontologie existante + fuzzy + règles
2. **Batch learning** (Phase B): LLM ponctuel pour apprendre nouveaux domaines
3. **Admin review** (Phase C): Optionnel, seulement pour edge cases

**Avantages**:
- ✅ 90-95% automatisation (vs 0% actuellement)
- ✅ Coût LLM faible (~$0.50/batch)
- ✅ Domaine-agnostic (auto-learning continu)
- ✅ Admin garde contrôle final

**Next Steps**: Prioriser P0 (Phase A) pour valider approche, puis P1 (Phase B) pour auto-learning.

