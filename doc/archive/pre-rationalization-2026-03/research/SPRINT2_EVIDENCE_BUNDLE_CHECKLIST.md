# Sprint 2: Evidence Bundle Resolver - Extended Mode

**Objectif**: 15-25 relations validées, précision ≥ 90%
**Scope**: Cross-section + Topic Binding + Retypage visuel
**Prérequis**: Sprint 1 complété et validé
**Référence**: `ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md` v1.3

---

## ⚠️ PRE-DEV GATE - Vérifier AVANT de coder Sprint 2

| # | Check | Status |
|---|-------|--------|
| 0 | **Charspans disponibles** - ProtoConcepts ont `char_start`/`char_end` (Phase 0) | ☐ |
| 1 | **Sprint 1 validé** - architecture validée, en attente charspans | ✅ |
| 2 | **Pas de GENERIC_REFERENCE_NOUNS** - approche D+ structurelle uniquement | ☐ |
| 3 | **Competing antecedents affiné** - fenêtre de tokens, pas tous les concepts | ☐ |
| 4 | **SectionContext.parent_section_id** disponible pour cross-section | ☐ |
| 5 | **SectionContext.reading_order_index** disponible pour distance | ☐ |
| 6 | **Docling visual relations** - `diagram_elements` dans cache v2 | ☐ |
| 7 | **Normalisation relation_type** - mapping lemme → forme canonique (pas métier) | ☐ |

> **STOP** si un check échoue. Résoudre avant de commencer Sprint 2.
> **Note Sprint 1**: Architecture validée mais non activable sans charspans. Phase 0 résout ce bloqueur.

---

## Différences Sprint 1 → Sprint 2

| Capacité | Sprint 1 | Sprint 2 |
|----------|----------|----------|
| Bundles intra-section | ✅ | ✅ |
| Bundles cross-section | ❌ | ✅ |
| Topic Binding ("ce médicament" → Metformine) | ❌ | ✅ |
| Coréférence cross-section | ❌ | ✅ |
| Relations visuelles (flèches, diagrammes) | ❌ | ✅ |
| Retypage visuel → sémantique | ❌ | ✅ |

---

## Phase 0: Enrichir Pipeline + Réimport Propre (Prérequis Sprint 2)

### 0.1 Contexte

Le Sprint 1 a validé l'architecture mais les ProtoConcepts n'ont pas de `char_start`/`char_end`.
Sans charspans, le système ne peut pas:
- Localiser les entités dans le texte
- Vérifier que le prédicat est **entre** les deux entités
- Garantir la précision ≥ 95%

### 0.2 Décision: Purge + Réimport Propre

**Approche retenue**: Enrichir le pipeline puis réimporter depuis zéro.

| ❌ Rejeté | ✅ Retenu |
|-----------|-----------|
| Correction rétroactive (match approximatif) | Enrichir Pass 2 + purge + réimport |
| Risque de faux positifs sur matching | Données propres dès l'extraction |
| Confusion "ça marche ou pas?" | Pipeline validé de bout en bout |

**Avantage clé**: Le cache d'extraction (`data/extraction_cache/`) est préservé, donc pas de re-extraction coûteuse.

### 0.3 Enrichir Pass 2 pour capturer les charspans

**Fichier à modifier**: `src/knowbase/api/services/pass2_service.py` (ou équivalent)

Les DocItems Docling contiennent déjà les positions:
- `prov.charspan[0]` → char_start
- `prov.charspan[1]` → char_end

Il faut propager ces valeurs lors de la création des ProtoConcepts.

```python
# Dans la création du ProtoConcept
proto_concept = {
    "concept_name": mention.text,
    "definition": mention.context,
    "context_id": section_id,
    "char_start": mention.char_start,  # NOUVEAU
    "char_end": mention.char_end,      # NOUVEAU
    # ...
}
```

### 0.4 Procédure de réimport

```bash
# 1. Purger Neo4j (garder le schéma)
docker-compose exec app python scripts/reset_proto_kg.py

# 2. Purger Qdrant
curl -X DELETE "http://localhost:6333/collections/knowbase"
curl -X DELETE "http://localhost:6333/collections/rfp_qa"

# 3. Réimporter depuis le cache (pas de re-extraction)
# Le cache data/extraction_cache/*.knowcache.json est préservé
docker-compose exec app python -m knowbase.ingestion.reimport_from_cache

# 4. Vérifier les charspans
docker-compose exec app python -c "
from knowbase.common.clients.neo4j_client import Neo4jClient
client = Neo4jClient()
with client.driver.session(database=client.database) as s:
    r = s.run('MATCH (p:ProtoConcept) WHERE p.char_start IS NOT NULL RETURN count(p)')
    print(f'ProtoConcepts avec charspan: {r.single()[0]}')
"
```

### 0.5 Checklist Phase 0

- [ ] Identifier où les charspans sont disponibles dans Docling
- [ ] Modifier Pass 2 pour capturer `char_start`/`char_end`
- [ ] Tester l'extraction sur 1 document
- [ ] Purger Neo4j + Qdrant
- [ ] Réimporter les documents depuis le cache
- [ ] Valider que les ProtoConcepts ont des charspans
- [ ] Tester le resolver Sprint 1 avec vrais charspans

### 0.6 Critères de sortie Phase 0

| Métrique | Cible |
|----------|-------|
| ProtoConcepts avec charspan | ≥ 80% |
| Relations validées (vrais charspans) | ≥ 5 |
| Précision sur échantillon | ≥ 95% |

> **Une fois Phase 0 complétée**, le Sprint 1 est pleinement opérationnel et on peut enchaîner sur les fonctionnalités Sprint 2.

---

## Critères de Succès Sprint 2

| Métrique | Cible | Mesure |
|----------|-------|--------|
| Relations promues (total) | 15-25 | Cypher count |
| Précision | ≥ 90% | Audit manuel |
| Relations cross-section | ≥ 5 | Bundles avec sections différentes |
| Relations via Topic Binding | ≥ 3 | Bundles avec EL non null |
| Relations visuelles | ≥ 2 | Bundles avec PREDICATE_VISUAL |

---

## Nouveaux Composants Sprint 2

### A. Document Topic Binding
### B. Validation de Proximité Cross-Section
### C. Coréférence Cross-Section (EL)
### D. Extraction Relations Visuelles
### E. Retypage Visuel Agnostique

---

## A. Document Topic Binding

### A.1 Problème à résoudre

```
Page 1: "La Metformine est un antidiabétique oral."
Page 3: "Ce médicament ne doit pas être associé avec l'alcool."
```

"Ce médicament" doit être résolu vers "Metformine".

### A.2 Modèle de données

**Fichier**: `src/knowbase/relations/topic_binding.py`

```python
@dataclass
class DocumentTopicBinding:
    """
    Liaison entre références implicites et topic documentaire.

    Permet de résoudre:
    - "ce médicament" → "Metformine"
    - "the solution" → "SAP S/4HANA"
    - "le règlement" → "RGPD"
    """
    document_id: str
    tenant_id: str

    # Topics dominants du document (ordonnés par fréquence)
    primary_topics: List[TopicCandidate]

    # Mappings de références implicites
    reference_mappings: Dict[str, ResolvedReference]

    # Métadonnées
    created_at: datetime
    confidence: float  # Confiance globale du binding


@dataclass
class TopicCandidate:
    """Un topic candidat du document."""
    concept_id: str           # CanonicalConcept.canonical_id
    label: str                # "Metformine"
    mention_count: int        # Nombre de mentions dans le doc
    first_mention_page: int   # Première apparition
    dominance_score: float    # mention_count / total_mentions
    source_evidence: List[str]  # context_ids où mentionné


@dataclass
class ResolvedReference:
    """Une référence implicite résolue."""
    reference_text: str       # "ce médicament", "the solution"
    resolved_to: str          # concept_id
    resolved_label: str       # "Metformine"
    confidence: float         # Confiance de la résolution
    resolution_method: str    # "TITLE_MATCH", "DOMINANCE", "SECTION_SCOPE"
```

### A.3 Algorithme de détection du Topic

```python
def detect_document_topics(document_id: str, tenant_id: str) -> DocumentTopicBinding:
    """
    Détecte les topics dominants d'un document.

    Stratégie multi-signal:
    1. Titre du document (très fort)
    2. Fréquence des concepts (fort)
    3. Position (première page = plus fort)
    4. Type de concept (PRODUCT, REGULATION > GENERIC)
    """

    # 1. Extraire titre du document
    doc_title = get_document_title(document_id)  # "Notice Metformine 500mg"
    title_concepts = extract_concepts_from_title(doc_title)  # ["Metformine"]

    # 2. Compter les mentions par concept
    concept_counts = count_concept_mentions(document_id, tenant_id)
    # {"Metformine": 47, "Alcool": 3, "Diabète": 12, ...}

    # 3. Calculer le score de dominance
    total_mentions = sum(concept_counts.values())

    topics = []
    for concept_id, count in concept_counts.items():
        dominance = count / total_mentions

        # Bonus si dans le titre
        title_bonus = 0.3 if concept_id in title_concepts else 0.0

        # Bonus si première page
        first_page = get_first_mention_page(concept_id, document_id)
        position_bonus = 0.1 if first_page == 1 else 0.0

        final_score = dominance + title_bonus + position_bonus

        topics.append(TopicCandidate(
            concept_id=concept_id,
            label=get_concept_label(concept_id),
            mention_count=count,
            first_mention_page=first_page,
            dominance_score=final_score,
        ))

    # 4. Trier par score et garder les tops
    topics.sort(key=lambda t: t.dominance_score, reverse=True)
    primary_topics = topics[:3]  # Max 3 topics primaires

    return DocumentTopicBinding(
        document_id=document_id,
        tenant_id=tenant_id,
        primary_topics=primary_topics,
        reference_mappings={},  # Rempli ensuite
        confidence=primary_topics[0].dominance_score if primary_topics else 0.0,
    )
```

### A.4 Détection des références anaphoriques (Approche D+)

**Principe fondamental** : "générique" n'est pas une propriété du mot, c'est une propriété de **l'usage dans la phrase**.

Le mot "médicament" peut être :
- Un concept taxonomique (spécifique) : "Les médicaments génériques vs princeps"
- Une reprise anaphorique (générique) : "Ce médicament ne doit pas..."

On capture cela via **traits grammaticaux** (Universal Dependencies), pas via liste de mots.

```python
@dataclass
class ImplicitReference:
    """Une référence implicite détectée."""
    text: str                    # "ce médicament", "the solution"
    span_start: int
    span_end: int
    noun_lemma: str              # "médicament", "solution"
    noun_token: Token            # Token spaCy pour analyse
    has_anaphoric_pattern: bool  # Pattern de reprise détecté
    has_specific_modifier: bool  # Modifieur spécifique (acronyme, nom propre)


def detect_implicit_references(doc) -> List[ImplicitReference]:
    """
    Détecte les références implicites via patterns syntaxiques.

    AGNOSTIQUE LANGUE: utilise Universal Dependencies (POS/DEP/Morph).
    """
    references = []

    for token in doc:
        # Pattern 1: Déterminant défini/démonstratif + Nom
        if token.pos_ == "DET":
            morph = token.morph.to_dict()
            is_definite = morph.get("Definite") == "Def"
            is_demonstrative = morph.get("PronType") == "Dem"

            if is_definite or is_demonstrative:
                # Chercher la tête nominale
                head_noun = find_noun_head(token)
                if head_noun and head_noun.pos_ == "NOUN":
                    references.append(ImplicitReference(
                        text=doc[token.i:head_noun.i + 1].text,
                        span_start=token.idx,
                        span_end=head_noun.idx + len(head_noun.text),
                        noun_lemma=head_noun.lemma_,
                        noun_token=head_noun,
                        has_anaphoric_pattern=is_demonstrative or is_definite,
                        has_specific_modifier=has_specific_modifier(head_noun),
                    ))

    return references


def find_noun_head(det_token: Token) -> Optional[Token]:
    """Trouve la tête nominale d'un déterminant."""
    # Le nom est généralement le head du déterminant ou son voisin direct
    if det_token.head.pos_ == "NOUN":
        return det_token.head
    # Ou le token suivant
    if det_token.i + 1 < len(det_token.doc):
        next_tok = det_token.nbor(1)
        if next_tok.pos_ == "NOUN":
            return next_tok
    return None


def has_specific_modifier(noun_token: Token) -> bool:
    """
    Vérifie si le nom a un modifieur spécifique (qui le rend non-anaphorique).

    AGNOSTIQUE LANGUE: basé sur POS/DEP, pas sur mots.

    Modifieurs spécifiques:
    - Nom propre (PROPN): "le médicament Metformine"
    - Acronyme (détecté via pattern): "le système SAP"
    - Composé long (multiple NOUN children)
    """
    for child in noun_token.children:
        # Nom propre = spécifique
        if child.pos_ == "PROPN":
            return True
        # Acronyme (tout en majuscules, >= 2 chars)
        if child.text.isupper() and len(child.text) >= 2:
            return True
        # Adjectif qualificatif technique (composé)
        if child.dep_ in ("amod", "nmod") and child.pos_ == "NOUN":
            return True

    return False
```

### A.4b Règle D+ : Résolution avec garde-fous structurels

```python
def is_resolvable_to_topic(
    reference: ImplicitReference,
    topic: TopicCandidate,
    document_concepts: Dict[str, int],  # concept_lex_key -> mention_count
    section_context_id: str,
    section_concept_mentions: List[ConceptMention],  # Mentions avec positions
    doc  # spaCy doc de la section (pour fenêtre de tokens)
) -> Tuple[bool, Optional[str]]:
    """
    Détermine si une référence implicite est résoluble vers le topic.

    APPROCHE D+ : 4 conditions structurelles, aucune liste lexicale.

    Returns:
        (is_resolvable, rejection_reason)
    """

    # ═══════════════════════════════════════════════════════════════════
    # GARDE-FOU 1: Pattern anaphorique
    # ═══════════════════════════════════════════════════════════════════
    # Le syntagme doit ressembler à une reprise (DET défini/démonstratif, NP courte)

    if not reference.has_anaphoric_pattern:
        return False, "NO_ANAPHORIC_PATTERN"

    # Si modifieur spécifique (nom propre, acronyme) → pas une reprise
    if reference.has_specific_modifier:
        return False, "HAS_SPECIFIC_MODIFIER"

    # ═══════════════════════════════════════════════════════════════════
    # GARDE-FOU 2: Concept non extrait OU concept faible (ratio fréquence)
    # ═══════════════════════════════════════════════════════════════════

    noun_key = compute_lex_key(reference.noun_lemma)
    noun_count = document_concepts.get(noun_key, 0)

    if noun_key in document_concepts:
        # Le nom EST un concept extrait → vérifier s'il est "faible"
        if topic.mention_count > 0:
            ratio = noun_count / topic.mention_count
            if ratio >= 0.2:
                # Concept fréquent → pas une simple reprise
                return False, "CONCEPT_TOO_FREQUENT"
        else:
            return False, "TOPIC_NO_MENTIONS"
    # else: noun_key pas extrait → OK, c'est générique

    # ═══════════════════════════════════════════════════════════════════
    # GARDE-FOU 3: Proximité structurale (déjà validée ailleurs, rappel)
    # ═══════════════════════════════════════════════════════════════════
    # Note: Cette validation est faite dans validate_proximity_cross_section()
    # On vérifie ici que le topic est "dans le scope" (section ou ancêtres)

    if not is_topic_in_scope(topic.concept_id, section_context_id):
        return False, "TOPIC_NOT_IN_SCOPE"

    # ═══════════════════════════════════════════════════════════════════
    # GARDE-FOU 4: Pas de compétiteur (Competing Antecedents)
    # ═══════════════════════════════════════════════════════════════════
    # Si plusieurs concepts canoniques récents sont compatibles → ABSTAIN

    competing = find_competing_antecedents(
        reference=reference,
        doc=doc,
        section_concept_mentions=section_concept_mentions,
        topic_concept_id=topic.concept_id,
        window_tokens=50  # Configurable
    )

    if len(competing) > 0:
        return False, f"COMPETING_ANTECEDENTS:{len(competing)}"

    # ═══════════════════════════════════════════════════════════════════
    # Tous les garde-fous passés → RESOLVABLE
    # ═══════════════════════════════════════════════════════════════════
    return True, None


def find_competing_antecedents(
    reference: ImplicitReference,
    doc,  # spaCy doc de la section
    section_concept_mentions: List[ConceptMention],  # Mentions avec positions
    topic_concept_id: str,
    window_tokens: int = 50  # Fenêtre de compétition
) -> List[str]:
    """
    Trouve les antécédents compétiteurs PROCHES de la référence.

    ⚠️ VERSION AFFINÉE: On ne considère compétiteur que si:
    1. Il est dans une fenêtre de N tokens autour de la référence
    2. ET il a un type grammatical compatible (PROPN/NOUN head)
    3. ET il n'est PAS le topic dominant

    Cela évite de bloquer le topic binding dans les sections riches
    où beaucoup de concepts sont mentionnés mais pas tous pertinents.

    AGNOSTIQUE LANGUE: basé sur positions et POS, pas sur vocabulaire.

    Exemple:
    - Section: "S/4HANA provides... [long text]... This system connects to BTP."
    - Référence: "This system" (position 100-110)
    - S/4HANA mentionné à position 0-8 (trop loin) → PAS compétiteur
    - BTP mentionné à position 120-123 (proche) → compétiteur potentiel
    """
    competitors = []
    ref_start = reference.span_start
    ref_end = reference.span_end

    # Convertir positions char en positions token pour la fenêtre
    ref_token_start = None
    ref_token_end = None
    for i, tok in enumerate(doc):
        if tok.idx <= ref_start < tok.idx + len(tok.text):
            ref_token_start = i
        if tok.idx <= ref_end <= tok.idx + len(tok.text):
            ref_token_end = i
            break

    if ref_token_start is None:
        return []  # Impossible de localiser → pas de compétiteurs

    # Fenêtre de tokens autour de la référence
    window_start = max(0, ref_token_start - window_tokens)
    window_end = min(len(doc), (ref_token_end or ref_token_start) + window_tokens)

    for mention in section_concept_mentions:
        if mention.concept_id == topic_concept_id:
            continue  # Le topic n'est pas un compétiteur

        # Vérifier si la mention est dans la fenêtre
        mention_token_idx = get_token_index_for_char(doc, mention.char_start)
        if mention_token_idx is None:
            continue

        if not (window_start <= mention_token_idx <= window_end):
            continue  # Hors fenêtre → pas compétiteur

        # Vérifier le type grammatical (doit être un nom/nom propre)
        mention_token = doc[mention_token_idx]
        if mention_token.pos_ not in {"NOUN", "PROPN"}:
            continue  # Pas un nominal → pas compétiteur

        # C'est un compétiteur valide
        competitors.append(mention.concept_id)

    # Dédupliquer (un concept peut être mentionné plusieurs fois)
    return list(set(competitors))


@dataclass
class ConceptMention:
    """Une mention de concept dans une section avec sa position."""
    concept_id: str
    label: str
    char_start: int
    char_end: int


def get_token_index_for_char(doc, char_pos: int) -> Optional[int]:
    """Retourne l'index du token contenant la position char."""
    for i, tok in enumerate(doc):
        if tok.idx <= char_pos < tok.idx + len(tok.text):
            return i
    return None
```

### A.5 Résolution des références (avec D+)

```python
def resolve_reference(
    reference: ImplicitReference,
    topic_binding: DocumentTopicBinding,
    section_context_id: str,
    document_concepts: Dict[str, int],  # lex_key -> mention_count
    section_concepts: List[str]  # concept_ids dans la section
) -> Optional[ResolvedReference]:
    """
    Résout une référence implicite vers un topic.

    APPROCHE D+ : 4 garde-fous structurels, aucune liste lexicale.

    Stratégie:
    1. Vérifier pattern anaphorique (DET défini/démonstratif, pas de modifieur spécifique)
    2. Vérifier concept non extrait OU concept faible (ratio < 0.2)
    3. Vérifier proximité structurale (topic dans le scope)
    4. Vérifier absence de compétiteurs (sinon ABSTAIN)
    """

    # Vérifier qu'un topic dominant existe
    if not topic_binding.primary_topics:
        return None

    primary_topic = topic_binding.primary_topics[0]

    # Vérifier la dominance minimale
    if primary_topic.dominance_score < 0.3:
        return None  # ABSTAIN - pas assez dominant

    # ═══════════════════════════════════════════════════════════════════
    # Appliquer les 4 garde-fous D+
    # ═══════════════════════════════════════════════════════════════════

    is_resolvable, rejection_reason = is_resolvable_to_topic(
        reference=reference,
        topic=primary_topic,
        document_concepts=document_concepts,
        section_context_id=section_context_id,
        section_concepts=section_concepts,
    )

    if not is_resolvable:
        logger.debug(
            f"[OSMOSE:TopicBinding] ABSTAIN: '{reference.text}' "
            f"reason={rejection_reason}"
        )
        return None

    # ═══════════════════════════════════════════════════════════════════
    # Résolution acceptée
    # ═══════════════════════════════════════════════════════════════════

    return ResolvedReference(
        reference_text=reference.text,
        resolved_to=primary_topic.concept_id,
        resolved_label=primary_topic.label,
        confidence=min(primary_topic.dominance_score, 0.85),  # Cap à 0.85
        resolution_method="D_PLUS_STRUCTURAL",
    )
```

### A.6 Garde-fous Topic Binding

```python
# Règles de REJET pour Topic Binding

def validate_topic_resolution(
    resolution: ResolvedReference,
    topic_binding: DocumentTopicBinding,
    section_context_id: str
) -> Tuple[bool, Optional[str]]:
    """
    Valide qu'une résolution de référence est légitime.

    Returns:
        (is_valid, rejection_reason)
    """

    # R1: Confiance minimale
    if resolution.confidence < 0.5:
        return False, "TOPIC_CONFIDENCE_TOO_LOW"

    # R2: Le topic doit être mentionné explicitement quelque part
    topic = get_topic_by_id(resolution.resolved_to, topic_binding)
    if topic.mention_count < 2:
        return False, "TOPIC_MENTIONED_ONLY_ONCE"

    # R3: Pas de résolution si plusieurs topics sont équivalents
    if len(topic_binding.primary_topics) >= 2:
        top1 = topic_binding.primary_topics[0].dominance_score
        top2 = topic_binding.primary_topics[1].dominance_score
        if top2 / top1 > 0.8:  # Top 2 est à 80% du top 1
            return False, "AMBIGUOUS_DOMINANT_TOPIC"

    # R4: Distance de section
    topic_sections = topic.source_evidence
    if not sections_are_related(section_context_id, topic_sections):
        return False, "TOPIC_NOT_IN_RELATED_SECTION"

    return True, None
```

---

## B. Validation de Proximité Cross-Section

### B.1 Problème

En Sprint 1, on exige `p1.context_id = p2.context_id` (même section).

En Sprint 2, on autorise des sections différentes MAIS avec des règles strictes.

### B.2 Règles de proximité (de l'ADR)

```python
def validate_proximity_cross_section(bundle: EvidenceBundle) -> Tuple[bool, str]:
    """
    Valide la proximité documentaire pour bundles cross-section.

    Au moins UNE condition doit être vraie.
    """
    contexts = collect_all_contexts(bundle)

    # Condition 1: Même section (Sprint 1 - toujours valide)
    if len(set(contexts)) == 1:
        return True, "SAME_SECTION"

    # Condition 2: Sections avec parent commun (frères)
    if have_common_parent(contexts):
        return True, "SIBLING_SECTIONS"

    # Condition 3: Lien explicite via TOC/structure
    if has_structural_link(contexts):
        return True, "STRUCTURAL_LINK"

    # Condition 4: Distance max de 3 sections consécutives
    if max_section_distance(contexts) <= 3:
        return True, "CONSECUTIVE_SECTIONS"

    return False, "EXCESSIVE_DISTANCE"


def have_common_parent(context_ids: List[str]) -> bool:
    """
    Vérifie si toutes les sections ont un parent commun.

    Exemple:
    - "3.1 Interactions" et "3.2 Contre-indications"
    - Parent commun: "3. Précautions"
    → True
    """
    parents = set()
    for ctx_id in context_ids:
        parent = get_parent_section(ctx_id)
        if parent:
            parents.add(parent)

    return len(parents) == 1  # Toutes ont le même parent


def max_section_distance(context_ids: List[str]) -> int:
    """
    Calcule la distance maximale entre sections.

    Distance = différence d'index dans l'ordre de lecture.
    """
    indices = [get_section_reading_order(ctx) for ctx in context_ids]
    return max(indices) - min(indices)


def has_structural_link(context_ids: List[str]) -> bool:
    """
    Vérifie s'il existe un lien structurel explicite.

    Exemples:
    - Section A référence Section B ("voir section 3.2")
    - TOC lie les deux sections
    - Cross-reference explicite
    """
    for ctx1 in context_ids:
        for ctx2 in context_ids:
            if ctx1 != ctx2:
                if section_references_section(ctx1, ctx2):
                    return True
    return False
```

### B.3 Requête Cypher Cross-Section

```cypher
-- Trouver les paires de concepts dans des sections LIÉES
MATCH (p1:ProtoConcept {tenant_id: $tenant_id, document_id: $document_id})
      -[:INSTANCE_OF]->(c1:CanonicalConcept)
MATCH (p2:ProtoConcept {tenant_id: $tenant_id, document_id: $document_id})
      -[:INSTANCE_OF]->(c2:CanonicalConcept)
WHERE c1.canonical_id < c2.canonical_id
  AND p1.context_id IS NOT NULL
  AND p2.context_id IS NOT NULL
  AND p1.context_id <> p2.context_id  -- Sections DIFFÉRENTES

-- Joindre les SectionContext pour vérifier la proximité
MATCH (s1:SectionContext {context_id: p1.context_id, tenant_id: $tenant_id})
MATCH (s2:SectionContext {context_id: p2.context_id, tenant_id: $tenant_id})

-- Filtre: sections liées (même parent OU distance <= 3)
WHERE s1.parent_section_id = s2.parent_section_id
   OR abs(s1.reading_order_index - s2.reading_order_index) <= 3

RETURN
    c1.canonical_id AS subject_id,
    c1.label AS subject_label,
    c2.canonical_id AS object_id,
    c2.label AS object_label,
    p1.context_id AS subject_context,
    p2.context_id AS object_context,
    s1.section_path AS subject_section_path,
    s2.section_path AS object_section_path
```

---

## C. Coréférence Cross-Section (Evidence Link)

### C.1 Intégration avec Topic Binding

Le composant **EL (Evidence Link)** du bundle utilise le Topic Binding:

```python
def build_evidence_link(
    reference: ImplicitReference,
    topic_binding: DocumentTopicBinding,
    section_context_id: str
) -> Optional[EvidenceFragment]:
    """
    Construit un EvidenceFragment de type COREFERENCE_LINK.
    """
    resolution = resolve_reference(reference, topic_binding, section_context_id)

    if not resolution:
        return None

    is_valid, rejection = validate_topic_resolution(
        resolution, topic_binding, section_context_id
    )

    if not is_valid:
        logger.info(f"[OSMOSE:EvidenceLink] Rejected: {rejection}")
        return None

    return EvidenceFragment(
        fragment_id=generate_fragment_id(),
        fragment_type="COREFERENCE_LINK",
        text=f"{reference.text} → {resolution.resolved_label}",
        source_context_id=section_context_id,
        confidence=resolution.confidence,
        extraction_method=resolution.resolution_method,
    )
```

### C.2 Exemple complet

**Document**: Notice Metformine

```
Section 1 (page 1): "La Metformine est un antidiabétique oral de première intention."
Section 3 (page 3): "Ce médicament ne doit pas être associé avec l'alcool."
```

**Topic Binding**:
```python
DocumentTopicBinding(
    primary_topics=[
        TopicCandidate(label="Metformine", dominance_score=0.65),
        TopicCandidate(label="Diabète", dominance_score=0.15),
    ],
    reference_mappings={
        "ce médicament": ResolvedReference(
            resolved_to="concept_metformine_123",
            resolved_label="Metformine",
            confidence=0.65,
        )
    }
)
```

**Bundle généré**:
```python
EvidenceBundle(
    evidence_subject=EvidenceFragment(
        fragment_type="ENTITY_MENTION",
        text="Metformine",
        source_context_id="section_1",
        confidence=0.95,
    ),
    evidence_object=EvidenceFragment(
        fragment_type="ENTITY_MENTION",
        text="alcool",
        source_context_id="section_3",
        confidence=0.90,
    ),
    evidence_predicate=[EvidenceFragment(
        fragment_type="PREDICATE_LEXICAL",
        text="ne doit pas être associé avec",
        source_context_id="section_3",
        confidence=0.85,
    )],
    evidence_link=EvidenceFragment(
        fragment_type="COREFERENCE_LINK",
        text="ce médicament → Metformine",
        source_context_id="section_3",
        confidence=0.65,
    ),

    confidence=min(0.95, 0.90, 0.85, 0.65) = 0.65,  # EL est le maillon faible
    validation_status="CANDIDATE",
)
```

---

## D. Extraction Relations Visuelles

### D.1 Source des données

Docling extrait déjà les relations visuelles dans `.v2cache.json`:
- `arrow_to`, `arrow_from`
- `connected_to`, `flow_to`
- `contains`
- `grouped_with` (ambigu - rejeté)

### D.2 Extraction depuis le cache

```python
def extract_visual_relations(document_id: str) -> List[VisualRelation]:
    """
    Extrait les relations visuelles du cache Docling.
    """
    cache = load_v2cache(document_id)

    relations = []
    for item in cache.get("diagram_elements", []):
        if item.get("relation_type") in VALID_VISUAL_RELATIONS:
            relations.append(VisualRelation(
                source_text=item["source_text"],
                target_text=item["target_text"],
                relation_type=item["relation_type"],
                caption=item.get("caption"),
                page=item["page"],
                bbox=item.get("bbox"),
            ))

    return relations


VALID_VISUAL_RELATIONS = {
    "arrow_to", "arrow_from", "bidirectional_arrow",
    "connected_to", "flow_to", "contains"
}

# Rejetées car ambiguës
AMBIGUOUS_VISUAL_RELATIONS = {
    "grouped_with", "near", "aligned_with"
}
```

### D.3 Matching avec les concepts

```python
def match_visual_to_concepts(
    visual: VisualRelation,
    concepts: List[CanonicalConcept]
) -> Optional[Tuple[str, str]]:
    """
    Matche les textes du diagramme avec les concepts extraits.

    Returns:
        (subject_concept_id, object_concept_id) ou None
    """
    subject_match = fuzzy_match_concept(visual.source_text, concepts)
    object_match = fuzzy_match_concept(visual.target_text, concepts)

    if subject_match and object_match:
        return (subject_match.canonical_id, object_match.canonical_id)

    return None


def fuzzy_match_concept(
    text: str,
    concepts: List[CanonicalConcept],
    threshold: float = 0.8
) -> Optional[CanonicalConcept]:
    """
    Match fuzzy entre texte de diagramme et concepts.

    Utilise lex_key pour normalisation.
    """
    text_key = compute_lex_key(text)

    for concept in concepts:
        if concept.lex_key == text_key:
            return concept

        # Fuzzy match si exact match échoue
        similarity = jaro_winkler(text_key, concept.lex_key)
        if similarity >= threshold:
            return concept

    return None
```

---

## E. Retypage Visuel Agnostique

### E.1 Stratégie (de l'ADR v1.3)

```python
def retype_visual_relation(
    visual: VisualRelation,
    doc  # spaCy doc du contexte adjacent
) -> Tuple[str, float]:
    """
    Retypage agnostique basé sur le texte présent.

    Priorité:
    1. Caption/label explicite de la flèche
    2. Prédicat extrait du contexte adjacent
    3. Type générique basé sur la forme visuelle
    """

    # 1. Caption explicite (meilleure evidence)
    if visual.caption and len(visual.caption.strip()) > 0:
        relation_type = normalize_relation_type(visual.caption)
        return relation_type, 0.9

    # 2. Extraction du contexte adjacent
    adjacent_text = get_adjacent_text(visual.page, visual.bbox)
    if adjacent_text:
        predicate = extract_predicate_from_context(doc, adjacent_text)
        if predicate and not is_modal_or_intentional(doc, predicate):
            return normalize_relation_type(predicate.lemma_), 0.7

    # 3. Types génériques (fallback)
    GENERIC_VISUAL_TYPES = {
        "arrow_to": "DIRECTED_RELATION",
        "arrow_from": "DIRECTED_RELATION",
        "bidirectional_arrow": "BIDIRECTIONAL_RELATION",
        "connected_to": "CONNECTED_TO",
        "flow_to": "FLOW_RELATION",
        "contains": "CONTAINS",
    }

    return GENERIC_VISUAL_TYPES.get(visual.relation_type, "VISUAL_ASSOCIATION"), 0.5
```

### E.2 Bundle avec relation visuelle

```python
def build_visual_bundle(
    visual: VisualRelation,
    subject_concept: CanonicalConcept,
    object_concept: CanonicalConcept,
    doc
) -> EvidenceBundle:
    """
    Construit un bundle à partir d'une relation visuelle.
    """
    relation_type, typing_confidence = retype_visual_relation(visual, doc)

    return EvidenceBundle(
        evidence_subject=EvidenceFragment(
            fragment_type="ENTITY_MENTION",
            text=subject_concept.label,
            source_page=visual.page,
            confidence=0.85,  # Visuels = confiance légèrement réduite
            extraction_method="DIAGRAM_ELEMENT",
        ),
        evidence_object=EvidenceFragment(
            fragment_type="ENTITY_MENTION",
            text=object_concept.label,
            source_page=visual.page,
            confidence=0.85,
            extraction_method="DIAGRAM_ELEMENT",
        ),
        evidence_predicate=[EvidenceFragment(
            fragment_type="PREDICATE_VISUAL",
            text=visual.relation_type,
            source_page=visual.page,
            confidence=typing_confidence,
            extraction_method=f"VISUAL_{visual.relation_type.upper()}",
        )],
        evidence_link=None,  # Pas de coréférence pour visuels

        relation_type_candidate=relation_type,
        typing_confidence=typing_confidence,
        confidence=min(0.85, 0.85, typing_confidence),
    )
```

---

## Ordre d'Implémentation Sprint 2

| Étape | Tâche | Dépendances | Effort |
|-------|-------|-------------|--------|
| **0a** | **Identifier charspans dans Docling/Pass2** | - | 1h |
| **0b** | **Modifier Pass 2 pour capturer charspans** | 0a | 3h |
| **0c** | **Purge Neo4j + Qdrant** | - | 0.5h |
| **0d** | **Réimport depuis cache** | 0b, 0c | 1h |
| **0e** | **Validation Phase 0 (test resolver)** | 0d | 1h |
| 1 | Modèles Topic Binding (A.2) | Phase 0 | 2h |
| 2 | Détection topics (A.3) | 1 | 3h |
| 3 | Patterns références implicites (A.4) | - | 2h |
| 4 | Résolution références (A.5) | 2, 3 | 2h |
| 5 | Validation proximité cross-section (B.2) | Phase 0 | 2h |
| 6 | Requête Cypher cross-section (B.3) | 5 | 1h |
| 7 | Evidence Link builder (C.1) | 4 | 1h |
| 8 | Extraction relations visuelles (D.2) | - | 2h |
| 9 | Matching visuels/concepts (D.3) | 8 | 2h |
| 10 | Retypage agnostique (E.1) | 9 | 2h |
| 11 | Intégration dans Resolver | Tous | 3h |
| 12 | Tests Sprint 2 | Tous | 4h |

**Effort Phase 0**: ~6.5h
**Effort Sprint 2 (hors Phase 0)**: ~26h
**Effort total**: ~32.5h

---

## Fichiers à Créer/Modifier (Sprint 2)

```
# Phase 0 - Modifications pipeline existant
src/knowbase/api/services/pass2_service.py      # Modifier pour capturer charspans
src/knowbase/ingestion/reimport_from_cache.py   # Script de réimport (si nécessaire)

# Sprint 2 - Nouveaux fichiers
src/knowbase/relations/
├── topic_binding.py              # A.1-A.6
├── proximity_validator.py        # B.2 (extension de bundle_validator.py)
├── visual_relation_extractor.py  # D.2-D.3
└── visual_retyper.py             # E.1-E.2

tests/relations/
├── test_topic_binding.py
├── test_cross_section_proximity.py
└── test_visual_relations.py
```

---

## Cas de Test Sprint 2

### Test 1: Topic Binding simple
```
Input:
  - Titre: "Notice Metformine 500mg"
  - Page 1: "La Metformine est un antidiabétique."
  - Page 3: "Ce médicament est contre-indiqué avec l'alcool."

Expected:
  - Topic dominant: Metformine (dominance > 0.5)
  - "Ce médicament" → Metformine (confidence ~0.65)
  - Bundle créé avec EL
```

### Test 2: Topic Binding rejeté (ambigu)
```
Input:
  - Titre: "Comparatif Metformine vs Glibenclamide"
  - Mentions: Metformine (23), Glibenclamide (21)

Expected:
  - REJET: AMBIGUOUS_DOMINANT_TOPIC
  - Pas de résolution "ce médicament"
```

### Test 2b: Rejet - Pas de pattern anaphorique
```
Input:
  - Référence: "médicament générique" (sans DET défini/démonstratif)
  - has_anaphoric_pattern = False

Expected:
  - REJET: NO_ANAPHORIC_PATTERN
  - Pas de résolution
```

### Test 2c: Rejet - Modifieur spécifique
```
Input:
  - Référence: "ce médicament Metformine" (DET.Dem + NOUN + PROPN)
  - has_specific_modifier = True

Expected:
  - REJET: HAS_SPECIFIC_MODIFIER
  - Pas de résolution (c'est une mention explicite, pas une reprise)
```

### Test 2d: Rejet - Concept trop fréquent
```
Input:
  - Topic: Metformine (47 mentions)
  - Référence: "ce médicament"
  - "médicament" extrait avec 15 mentions (ratio = 15/47 = 0.32 >= 0.2)

Expected:
  - REJET: CONCEPT_TOO_FREQUENT
  - "médicament" est un concept central, pas une simple reprise
```

### Test 2e: Rejet - Compétiteurs PROCHES présents
```
Input:
  - Topic dominant: S/4HANA
  - Section: "S/4HANA connects to BTP. This system enables integration with Fiori."
  - Positions: S/4HANA(0-8), BTP(22-25), "This system"(27-38), Fiori(70-75)
  - Référence: "This system" (position 27-38)
  - Fenêtre: 50 tokens

Expected:
  - BTP (position 22-25) est dans la fenêtre → compétiteur
  - REJET: COMPETING_ANTECEDENTS:1
  - Ambiguïté locale → ABSTAIN
```

### Test 2e-bis: Succès - Compétiteurs HORS fenêtre
```
Input:
  - Topic dominant: S/4HANA
  - Section: "S/4HANA is the core ERP. [... 200 tokens de texte ...]
             This system provides real-time analytics."
  - Positions: S/4HANA(0-8), "This system"(position 500+)
  - Pas d'autre concept mentionné près de "This system"
  - Fenêtre: 50 tokens

Expected:
  - S/4HANA (position 0-8) est HORS fenêtre → PAS compétiteur
  - Pas de compétiteur proche
  - SUCCÈS: résolution vers S/4HANA (topic dominant)
```

### Test 2f: Succès - Tous garde-fous passés
```
Input:
  - Topic: Metformine (47 mentions, dominance 0.65)
  - Référence: "ce médicament" (DET.Dem + NOUN, pas de modifieur)
  - "médicament" non extrait OU extrait avec 3 mentions (ratio < 0.2)
  - Section mentionne seulement Metformine (pas de compétiteur)

Expected:
  - SUCCÈS: résolution vers Metformine
  - resolution_method = "D_PLUS_STRUCTURAL"
  - confidence = 0.65
```

### Test 3: Cross-section valide (frères)
```
Input:
  - Section 3.1: "Metformine..."
  - Section 3.2: "Alcool..."
  - Parent commun: Section 3

Expected:
  - Proximité validée: SIBLING_SECTIONS
```

### Test 4: Cross-section rejeté (trop loin)
```
Input:
  - Section 1: "Metformine..."
  - Section 8: "Alcool..."
  - Distance: 7 sections

Expected:
  - REJET: EXCESSIVE_DISTANCE
```

### Test 5: Relation visuelle avec caption
```
Input:
  - Diagramme page 5: Box "S/4HANA" → Box "BTP"
  - Caption sur la flèche: "integrates"

Expected:
  - relation_type_candidate: "INTEGRATES"
  - typing_confidence: 0.9
```

### Test 6: Relation visuelle sans caption
```
Input:
  - Diagramme page 5: Box "S/4HANA" → Box "BTP"
  - Pas de caption
  - Texte adjacent: "...the integration between systems..."

Expected:
  - relation_type_candidate: "INTEGRATION" (extrait du contexte)
  - typing_confidence: 0.7
```

### Test 7: Relation visuelle fallback
```
Input:
  - Diagramme page 5: Box "A" → Box "B"
  - Pas de caption, pas de contexte utile

Expected:
  - relation_type_candidate: "DIRECTED_RELATION"
  - typing_confidence: 0.5
```

---

## Validation Finale Sprint 2

Avant de passer au Sprint 3, vérifier:

- [ ] ≥ 15 relations promues (total Sprint 1 + 2)
- [ ] ≥ 5 relations cross-section
- [ ] ≥ 3 relations via Topic Binding
- [ ] ≥ 2 relations visuelles
- [ ] Précision ≥ 90% sur échantillon de 15 relations
- [ ] Tous les EL ont une `resolution_method` explicite
- [ ] Tous les rejets Topic Binding sont tracés
- [ ] Tests passent

---

*Checklist Sprint 2 - Evidence Bundle Resolver - Extended Mode*
*Référence: ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md v1.3*
