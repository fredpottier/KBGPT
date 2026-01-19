# ADR: Multi-Span Evidence Bundles for Relation Promotion

**Statut**: Accepted with Clarifications
**Date**: 2026-01-17
**Auteurs**: Collaboration Claude/ChatGPT
**Revue**: ChatGPT - Validation avec ajustements mineurs
**Contexte**: OSMOSE Semantic Core - Resolution du probleme KG pauvre

---

## 1. Contexte et Probleme

### 1.1 Situation Actuelle

Le pipeline OSMOSE actuel produit un Knowledge Graph semantiquement pur mais **structurellement pauvre**:

| Metrique | Valeur Actuelle | Probleme |
|----------|-----------------|----------|
| Proto-concepts | 2981 | OK |
| Concepts canoniques | 850 | OK |
| Relations candidates | 58 | Tres faible |
| Relations validees | 1 | **Critique** |

### 1.2 Diagnostic

Le probleme n'est **pas** la philosophie "verite prouvee". Le probleme est que le systeme est **"localiste"**: il cherche une preuve complete (A + predicat + B) dans une fenetre de ~512 tokens, alors que les preuves sont **fragmentees** a l'echelle du document.

**Exemple concret** (PDF RISE with SAP):
- Page 1: "SAP S/4HANA Cloud, Private Edition is the flagship ERP..."
- Page 5: "The solution integrates seamlessly with SAP BTP..."
- Page 8: Schema montrant S/4HANA PCE vers BTP avec fleche

Les 3 fragments **prouvent** la relation `S/4HANA_PCE --[INTEGRATES_WITH]--> SAP_BTP`, mais aucun fragment individuel ne la contient entierement.

### 1.3 Ce que Docling Extrait Deja

Le cache `.v2cache.json` montre que Docling extrait:
- `is_relation_bearing: true` sur certains chunks
- Relations visuelles: `grouped_with`, `arrow_to`, `connected_to`
- Elements de diagrammes avec positions et textes

**Le probleme n'est pas l'extraction. C'est l'assemblage.**

---

## 2. Decision

### 2.1 Principe Directeur

> **"Une verite documentaire peut etre prouvee par plusieurs fragments coordonnes, a condition que leur assemblage soit explicite, tracable et refutable."**

### 2.2 Solution: Evidence Bundle Resolver

Introduire un nouveau sous-systeme qui assemble des preuves fragmentees en **bundles coherents** avant la promotion des relations.

```
EVIDENCE BUNDLE
===============
EA: Evidence de l'entite A (sujet)
    -> "SAP S/4HANA Cloud, Private Edition" (page 1)

EB: Evidence de l'entite B (objet)
    -> "SAP BTP" (page 5, schema page 8)

EP: Evidence du predicat
    -> "integrates with" (page 5) + fleche schema (page 8)

EL: Evidence du lien linguistique (optionnel)
    -> "the solution" -> S/4HANA PCE (resolution coreference)

confidence = min(conf_EA, conf_EB, conf_EP, conf_EL)
```

---

## 3. Specification Formelle

### 3.1 Definition d'un Evidence Bundle

```python
@dataclass
class EvidenceFragment:
    """Fragment de preuve individuel."""
    fragment_id: str
    fragment_type: Literal[
        "ENTITY_MENTION",      # Mention d'une entite
        "PREDICATE_LEXICAL",   # Predicat textuel explicite
        "PREDICATE_VISUAL",    # Predicat visuel (fleche, lien)
        "COREFERENCE_LINK"     # Lien de coreference
    ]
    text: str
    source_context_id: str
    source_chunk_id: Optional[str]
    source_page: Optional[int]
    confidence: float
    extraction_method: str


@dataclass
class EvidenceBundle:
    """
    Bundle de preuves pour une relation candidate.

    IMPORTANT - Statut ontologique:
    Un EvidenceBundle n'est PAS de la connaissance.
    C'est un ARTEFACT DE JUSTIFICATION structure.
    Il ne doit jamais etre navigue comme une relation dans le KG.
    """
    bundle_id: str

    # Les 4 composants
    evidence_subject: EvidenceFragment          # EA
    evidence_object: EvidenceFragment           # EB
    evidence_predicate: List[EvidenceFragment]  # EP (peut etre multiple)
    evidence_link: Optional[EvidenceFragment]   # EL (optionnel)

    # Relation candidate resultante (TENTATIF jusqu'a promotion)
    subject_concept_id: str
    object_concept_id: str
    relation_type_candidate: str       # Type propose, pas encore valide
    typing_confidence: float           # Confiance dans le typage (0.0-1.0)

    # Metriques
    confidence: float          # min(all fragments)
    coherence_score: float
    proximity_valid: bool

    # Tracabilite
    document_id: str
    created_at: datetime
    validation_status: Literal["CANDIDATE", "PROMOTED", "REJECTED"]
    rejection_reason: Optional[str]


@dataclass
class DocumentTopicBinding:
    """Liaison entre references implicites et topic documentaire."""
    document_id: str
    primary_topics: List[str]
    reference_mappings: Dict[str, str]  # "the solution" -> concept_id
    confidence: float
    evidence_sources: List[str]
```

### 3.2 Regles de Coherence (OBLIGATOIRES)

#### Regle 1: Proximite Documentaire

Un bundle est **valide** seulement si au moins UNE des conditions est vraie:

```python
def validate_proximity(bundle: EvidenceBundle) -> bool:
    """Valide la proximite documentaire des fragments."""

    contexts = [
        bundle.evidence_subject.source_context_id,
        bundle.evidence_object.source_context_id,
        *[ep.source_context_id for ep in bundle.evidence_predicate]
    ]
    if bundle.evidence_link:
        contexts.append(bundle.evidence_link.source_context_id)

    # Condition 1: Meme section
    if len(set(contexts)) == 1:
        return True

    # Condition 2: Sections avec parent commun (freres)
    if have_common_parent(contexts):
        return True

    # Condition 3: Lien explicite via TOC/structure
    if has_structural_link(contexts):
        return True

    # Condition 4: Distance max de 3 sections consecutives
    if max_section_distance(contexts) <= 3:
        return True

    return False
```

#### Regle 2: Validation du Lien Linguistique (EL)

```python
def validate_linguistic_link(
    bundle: EvidenceBundle,
    topic_binding: DocumentTopicBinding
) -> bool:
    """Valide que le lien linguistique est legitime."""

    if not bundle.evidence_link:
        return True  # Pas de lien = pas de validation requise

    reference_text = bundle.evidence_link.text.lower()
    resolved_topic = topic_binding.reference_mappings.get(reference_text)

    if not resolved_topic:
        return False

    # Le topic doit etre mentionne dans la section OU ses ancetres
    section_context = bundle.evidence_link.source_context_id
    if not topic_mentioned_in_scope(resolved_topic, section_context):
        return False

    # Le topic doit etre dominant (> 50% des mentions)
    if topic_binding.confidence < 0.5:
        return False

    return True
```

#### Regle 3: Coherence Semantique du Predicat (Agnostique Domaine + Langue)

> **Principe fondamental**: OSMOSE raisonne sur la FORME de l'assertion, jamais sur le vocabulaire metier.
> Aucune whitelist lexicale de predicats. Detection morpho-syntaxique uniquement.

##### 3.3.1 Detection des Predicats Valides (Patterns Syntaxiques)

```python
# Patterns morpho-syntaxiques pour detecter les structures predicatives
# Agnostique au domaine: "integrates with", "inhibits", "supersedes" = meme structure
PREDICATE_SYNTACTIC_PATTERNS = [
    # "X verbe Y" / "X verbe prep Y"
    {"pattern": [{"POS": "NOUN"}, {"POS": "VERB"}, {"POS": "ADP", "OP": "?"}, {"POS": "NOUN"}]},

    # "X is verbed by Y" (passif)
    {"pattern": [{"POS": "NOUN"}, {"LEMMA": "be"}, {"POS": "VERB"}, {"POS": "ADP"}, {"POS": "NOUN"}]},
]

# ═══════════════════════════════════════════════════════════════════════════
# DETECTION DES VERBES GENERIQUES - APPROCHE STRUCTURELLE (AGNOSTIQUE LANGUE)
# ═══════════════════════════════════════════════════════════════════════════
#
# Au lieu d'une liste de lemmes (be, have, do...), on detecte structurellement:
# 1. Auxiliaires → POS = AUX (deja gere dans is_modal_or_intentional)
# 2. Copules → dependance "cop" ou structure attributive
# 3. Verbes legers → structure sans complement prepositionnel informatif
#
# NOTE HISTORIQUE: L'ancienne liste GENERIC_VERBS_EXCLUDED = {"be", "have",...}
# etait anglais-only et violait l'agnosticite linguistique.
# ═══════════════════════════════════════════════════════════════════════════
```

##### 3.3.2 Filtrage des Modaux et Intentionnels (Universal Dependencies)

```python
def is_modal_or_intentional(doc, predicate_token) -> bool:
    """
    Rejette les predicats modaux/intentionnels.

    AGNOSTIQUE LANGUE: Utilise Universal Dependencies (POS tags universels).
    Fonctionne pour: en, fr, de, es, it, pt, nl, ru, zh, ja, etc.

    Rejette:
    - "X can/peut/kann inhibit Y" (modal)
    - "X is designed to / vise a / bestimmt fur Y" (intentionnel)
    - "X could/pourrait/konnte connect to Y" (conditionnel)
    """

    # 1. Auxiliaire modal (universel: AUX avec dependance aux)
    if predicate_token.pos_ == "AUX":
        return True  # can, peut, kann, puede, 可以...

    # 2. Mode conditionnel (morphologie universelle)
    if "Mood=Cnd" in str(predicate_token.morph):
        return True  # would, pourrait, konnte...

    # 3. Structure intentionnelle "V to-infinitive" / "V a-infinitif"
    if has_infinitive_complement(predicate_token):
        return True  # designed to, vise a, bestimmt fur...

    return False


def has_infinitive_complement(token) -> bool:
    """
    Detecte les structures 'X to Y' / 'X a Y' / 'X zu Y'.
    Pattern universel: dependance xcomp ou advcl vers un verbe.
    """
    for child in token.children:
        if child.dep_ in {"xcomp", "advcl"} and child.pos_ == "VERB":
            return True
    return False
```

##### 3.3.3 Validation Complete du Predicat

```python
def validate_predicate_coherence(bundle: EvidenceBundle, doc) -> Tuple[bool, str]:
    """
    Valide la coherence du predicat - AGNOSTIQUE domaine et langue.

    Returns:
        (is_valid, rejection_reason)
    """
    for ep in bundle.evidence_predicate:

        if ep.fragment_type == "PREDICATE_LEXICAL":
            predicate_token = get_predicate_token(doc, ep.text)

            # R1: Rejeter les auxiliaires (includes modals)
            # AGNOSTIQUE LANGUE: POS = AUX est universel
            if predicate_token.pos_ == "AUX":
                return False, "AUXILIARY_VERB"

            # R2: Rejeter les copules (structure attributive)
            # AGNOSTIQUE LANGUE: dependance "cop" est universelle
            if is_copula_or_attributive(doc, predicate_token):
                return False, "COPULA_OR_ATTRIBUTIVE"

            # R3: Rejeter les modaux/intentionnels (POS-based, universel)
            if is_modal_or_intentional(doc, predicate_token):
                return False, "MODAL_OR_INTENTIONAL"

            # R4: Verifier la structure predicative (sujet-verbe-objet/prep)
            if not has_valid_predicate_structure(doc, predicate_token):
                return False, "NO_PREDICATE_STRUCTURE"

        elif ep.fragment_type == "PREDICATE_VISUAL":
            # Relations visuelles: whitelist technique (pas metier)
            if ep.extraction_method in AMBIGUOUS_VISUAL_RELATIONS:
                return False, "AMBIGUOUS_VISUAL"

    return True, None


def is_copula_or_attributive(doc, token) -> bool:
    """
    Detecte les copules et structures attributives.

    AGNOSTIQUE LANGUE: utilise Universal Dependencies.

    Patterns detectes:
    - "X is Y" / "X est Y" / "X ist Y" (copule)
    - "X is called Y" / "X s'appelle Y" (attributif)
    - Verbe avec dependance "cop" ou "attr"

    Examples rejetés:
    - "Metformine is an antidiabetic" → copule (non informatif)
    - "The system is called SAP" → attributif

    Examples acceptés:
    - "Metformine inhibits glucose production" → verbe lexical
    """
    # 1. Verifier si le token a une dependance "cop" (copula)
    if token.dep_ == "cop":
        return True

    # 2. Verifier si le token gouverne un attribut
    for child in token.children:
        if child.dep_ in {"attr", "acomp", "oprd"}:  # attribut, adj complement, object predicate
            return True

    # 3. Verifier si le token est un root sans complement prepositionnel
    # (structure "X verb Y" sans prep = souvent attributif ou possessif)
    if token.dep_ == "ROOT":
        has_prep_complement = any(
            child.dep_ in {"prep", "prt", "agent"} or child.pos_ == "ADP"
            for child in token.children
        )
        has_object = any(child.dep_ in {"dobj", "obj"} for child in token.children)

        # Si pas de complement prepositionnel et objet direct simple → structure faible
        if has_object and not has_prep_complement:
            # On accepte quand meme si le verbe n'est pas un verbe d'etat
            # Heuristique: verbes d'etat ont souvent des dependances specifiques
            pass  # On laisse passer, R4 filtrera si pas de structure claire

    return False


# Relations visuelles: whitelist TECHNIQUE (Docling output), pas metier
VALID_VISUAL_RELATIONS = {
    "arrow_to", "arrow_from", "bidirectional_arrow",
    "connected_to", "flow_to", "contains"
}

AMBIGUOUS_VISUAL_RELATIONS = {
    "grouped_with",  # Layout, pas semantique
    "near",          # Proximite spatiale != relation
    "aligned_with"   # Alignement visuel != relation
}
```

##### 3.3.4 Traitement des Assertions Normatives

Les assertions normatives ("shall", "must", "doit") sont grammaticalement modales mais epistemiquement factuelles dans un cadre reglementaire.

```python
def classify_assertion_type(predicate_token) -> Literal["FACTUAL", "MODAL", "NORMATIVE"]:
    """
    Distingue les types d'assertions.

    NORMATIVE: modal mais prescriptif (shall, must, doit)
    - Non promu comme relation factuelle
    - Mais trace comme signal documentaire
    """
    if predicate_token.pos_ == "AUX":
        # Modaux normatifs (prescriptifs)
        if predicate_token.lemma_.lower() in {"shall", "must", "devoir"}:
            return "NORMATIVE"
        return "MODAL"

    if "Mood=Cnd" in str(predicate_token.morph):
        return "MODAL"

    return "FACTUAL"
```

**Comportement OSMOSE pour les assertions normatives:**
- `FACTUAL` → Eligible pour promotion en relation
- `MODAL` → Rejete (non factuel)
- `NORMATIVE` → Non promu, mais stocke avec `assertion_type=NORMATIVE` pour tracabilite

#### Regle 4: Score Composite Conservateur

```python
def compute_bundle_confidence(bundle: EvidenceBundle) -> float:
    """Le maillon faible gouverne."""
    confidences = [
        bundle.evidence_subject.confidence,
        bundle.evidence_object.confidence,
        min(ep.confidence for ep in bundle.evidence_predicate)
    ]
    if bundle.evidence_link:
        confidences.append(bundle.evidence_link.confidence)

    return min(confidences)  # JAMAIS de moyenne
```

### 3.4 Cas d'Exclusion Explicites

Un bundle est **automatiquement rejete** si:

| Regle | Condition | Exemple | Agnostique? |
|-------|-----------|---------|-------------|
| AUXILIARY_VERB | POS = AUX | "is", "hat", "est", "ha" | ✅ POS-based (universel) |
| COPULA_OR_ATTRIBUTIVE | Structure attributive (dep=cop/attr) | "X is Y", "X est Y" | ✅ Dep-based (universel) |
| MODAL_OR_INTENTIONAL | Predicat modal ou intentionnel | "can integrate", "designed to connect" | ✅ POS-based |
| NO_PREDICATE_STRUCTURE | Pas de structure sujet-verbe-objet | Fragment nominal isole | ✅ Syntaxique |
| SCOPE_MISMATCH | Entites dans scopes distincts | Section 'Prerequisites' vs 'Roadmap' | ✅ Structurel |
| GLOBAL_TOPIC_ONLY | Lien base uniquement sur topic global | "the solution" sans mention locale | ✅ Structurel |
| AMBIGUOUS_VISUAL | Relation visuelle non confirmee | `grouped_with` sans caption | ✅ Technique |
| EXCESSIVE_DISTANCE | Fragments trop eloignes | Page 1 et page 50 sans lien | ✅ Structurel |

**Note importante**: Aucune regle d'exclusion n'est basee sur le vocabulaire metier.
Toutes les regles sont linguistiques (POS, syntaxe) ou structurelles (position, scope).

---

## 4. Retypage des Relations Visuelles (Agnostique)

### 4.1 Principe

Le retypage transforme une relation visuelle brute (`arrow_to`) en relation semantique typee.

**Ce n'est PAS de l'inference. C'est de l'interpretation basee sur le TEXTE PRESENT dans le document.**

> **Regle d'agnosticite**: Le systeme ne presuppose AUCUN vocabulaire metier.
> Le type de relation est derive du texte explicite (caption, label, contexte adjacent).

### 4.2 Strategie de Retypage Agnostique

```python
def retype_visual_relation(
    visual_relation: str,
    caption_text: Optional[str],
    adjacent_text: str,
    doc
) -> Tuple[str, float]:
    """
    Retypage agnostique base sur le texte present.

    Strategie:
    1. Si caption/label present → utiliser comme type
    2. Si predicat dans texte adjacent → extraire via POS
    3. Sinon → type generique base sur la forme visuelle
    """

    # 1. Caption explicite (meilleure evidence)
    if caption_text and len(caption_text.strip()) > 0:
        # Le texte de la fleche EST le type de relation
        return normalize_relation_type(caption_text), 0.9

    # 2. Extraction du predicat du contexte adjacent
    predicate = extract_predicate_from_context(doc, adjacent_text)
    if predicate and not is_modal_or_intentional(doc, predicate):
        return normalize_relation_type(predicate.lemma_), 0.7

    # 3. Fallback: types generiques bases sur la forme visuelle
    GENERIC_VISUAL_TYPES = {
        "arrow_to": "DIRECTED_RELATION",
        "arrow_from": "DIRECTED_RELATION",
        "bidirectional_arrow": "BIDIRECTIONAL_RELATION",
        "connected_to": "CONNECTED_TO",
        "flow_to": "FLOW_RELATION",
        "contains": "CONTAINS",
    }
    return GENERIC_VISUAL_TYPES.get(visual_relation, "VISUAL_ASSOCIATION"), 0.5


def normalize_relation_type(text: str) -> str:
    """
    Normalise un texte en type de relation.
    Ex: "integrates with" -> "INTEGRATES_WITH"
        "SSO" -> "SSO"
        "data flow" -> "DATA_FLOW"
    """
    # Supprime articles et prepositions communes
    cleaned = re.sub(r'\b(the|a|an|to|with|by|from|of)\b', '', text.lower())
    # Snake case uppercase
    return re.sub(r'\s+', '_', cleaned.strip()).upper()
```

### 4.3 Extension Optionnelle: Mapping Tenant-Specific

Pour les cas ou un client souhaite des types metier specifiques, un **mapping optionnel** peut etre fourni:

```python
# Configuration OPTIONNELLE par tenant (pas dans le coeur)
# Fichier: config/tenant/{tenant_id}/relation_mappings.yaml
TENANT_RELATION_MAPPINGS = {
    # Exemple SAP (optionnel, pas dans le coeur OSMOSE)
    "INTEGRATES": "INTEGRATES_WITH",
    "SSO": "AUTHENTICATED_BY",
    "DEPLOYED": "DEPLOYED_ON",

    # Exemple Lifescience (autre tenant)
    "INHIBITS": "INHIBITS",
    "ACTIVATES": "ACTIVATES",
    "BINDS": "BINDS_TO",
}
```

**Important**: Ce mapping est une **extension**, pas le coeur.
Le systeme fonctionne sans lui (types generiques).

### 4.4 Relations Non Retypees

Si aucune evidence textuelle et pas de mapping:
```
VISUAL_ASSOCIATION (maturity=OBSERVED, confidence=0.5)
```
Tracable mais non promue comme relation semantique.

---

## 5. Integration dans le Pipeline

### 5.1 Position

```
Pass 1: Document Processing (Docling)
Pass 2: Concept Extraction
Pass 3: Relation Extraction (existant)
        |
        v
+----------------------------------+
| Pass 3.5: Evidence Bundle Resolver|  <-- NOUVEAU
|                                   |
|  1. Document Topic Detection      |
|  2. Cross-Section Coreference     |
|  3. Bundle Generation             |
|  4. Bundle Validation             |
|  5. Relation Promotion            |
+----------------------------------+
        |
        v
Pass 4: Entity Resolution
Pass 5: Corpus-level Consolidation
```

### 5.2 Structures Neo4j

```cypher
// Nouveau noeud: EvidenceBundle
CREATE CONSTRAINT evidence_bundle_id IF NOT EXISTS
FOR (eb:EvidenceBundle) REQUIRE eb.bundle_id IS UNIQUE;

// Relation: Bundle promu devient SemanticRelation
// (EvidenceBundle)-[:PROMOTED_TO]->(SemanticRelation)
```

---

## 6. Mode Progressif

### Phase 1: Safe Mode (Sprint 1)
- Relations textuelles explicites uniquement
- Bundles intra-section uniquement
- Aucun retypage visuel
- **Objectif:** 5-10 relations, precision >= 95%

### Phase 2: Extended Mode (Sprint 2)
- Bundles inter-sections liees
- Document Topic Binding (mono-topic)
- Retypage sous whitelist stricte
- **Objectif:** 15-25 relations, precision >= 90%

### Phase 3: Assisted Mode (Sprint 3)
- Suggestions de bundles non promus (UI)
- Validation humaine pour cas ambigus
- **Objectif:** Pipeline complet avec human-in-the-loop

---

## 7. Metriques de Qualite

| Metrique | Seuil | Description |
|----------|-------|-------------|
| `bundle_promotion_precision` | >= 90% | Relations promues correctes |
| `bundle_rejection_rate` | >= 60% | Bundles rejetes / generes |
| `audit_trace_completeness` | 100% | Toute relation tracable |
| `avg_evidence_fragments` | >= 2.5 | Fragments par bundle |

---

## 8. Risques et Mitigations

| Risque | Mitigation |
|--------|------------|
| Faux positifs par assemblage | Regles d'exclusion + mode progressif |
| Performance | Traitement batch, pas temps-reel |
| Retypage incorrect | Whitelist + human-in-the-loop |

### 8.1 Estimation du Cout

Le Evidence Bundle Resolver ajoute une charge supplementaire au pipeline:

| Phase | Cout Relatif | Justification |
|-------|--------------|---------------|
| Safe Mode (Sprint 1) | ~×1.2 | Intra-section uniquement, peu de calculs cross-ref |
| Extended Mode (Sprint 2) | ~×1.5 | Topic binding + cross-section, plus de comparaisons |
| Assisted Mode (Sprint 3) | ~×1.3 | UI suggestions, mais humain fait le gros du travail |

**Note:** Le gain qualitatif (KG utilisable vs KG vide) justifie largement ce cout.
Un KG avec 1 relation est inutile; un KG avec 15-25 relations validees a de la valeur.

---

## 9. Non-Goals Explicites

1. **Pas d'inference** - Aucune relation inventee
2. **Pas d'ontologie metier** - Regles generiques
3. **Pas de ML/LLM libre** - Pattern-based et auditable
4. **Pas de modification du KG existant** - On ajoute
5. **Pas de temps-reel** - Batch a l'ingestion

---

## 10. Exemple Complet

### Input (RISE Security Guide):
```
Page 1: "SAP S/4HANA Cloud, Private Edition provides security..."
Page 5: "The solution integrates with SAP Identity Authentication..."
Page 8: [Diagram] S/4HANA PCE -> IAS (arrow "SSO")
```

### Bundle Genere:
```
EA: "SAP S/4HANA Cloud, Private Edition" (p.1, conf=0.95)
EB: "SAP Identity Authentication Service" (p.5, conf=0.90)
EP: ["integrates with" (p.5), "arrow SSO" (p.8)] (conf=0.80)
EL: "the solution" -> topic (conf=0.85)

confidence = min(0.95, 0.90, 0.80, 0.85) = 0.80
status = PROMOTED
```

### Relation Promue:
```
(S/4HANA CPE)--[INTEGRATES_WITH {conf:0.80, bundle:"bnd_xxx"}]-->(IAS)
```

---

## 11. Cas de Rejet (TLS 1.2)

### Input:
```
Page 1: "SAP S/4HANA Cloud, Private Edition is our flagship."
Page 5: "TLS 1.2 is the minimum encryption standard."
Page 8: "All connections must be secured."
```

### Resultat:
```
REJECTED - NO_PREDICATE_STRUCTURE
Reason: "secured" est un participe passif isole sans structure relationnelle claire.
```

---

---

## 12. Clarifications (suite revue ChatGPT)

### 12.1 Statut Ontologique

> **Un EvidenceBundle n'est PAS de la connaissance. C'est un artefact de justification structure.**

Implications:
- On ne "navigue" pas sur les bundles comme sur des relations
- L'UI ne doit pas presenter les bundles comme des faits
- Seules les `SemanticRelation` promues font partie du KG navigable

### 12.2 Typage Tentatif

Le champ `relation_type_candidate` (et non `relation_type`) rappelle que:
- Le type est une **proposition** jusqu'a promotion
- Le champ `typing_confidence` indique la certitude du typage
- Un bundle peut etre PROMOTED avec un type different de celui propose

---

---

## 13. Principe d'Agnosticite (Ajout v1.2)

Suite a la revue collaborative Claude/ChatGPT, l'ADR a ete amende pour garantir une **double agnosticite**:

### 13.1 Agnosticite Domaine

| Element | Avant (v1.0) | Apres (v1.2) |
|---------|--------------|--------------|
| Predicats valides | Whitelist metier IT | Detection morpho-syntaxique |
| Types de relations | INTEGRATES_WITH, AUTHENTICATED_BY | Types generiques + mapping optionnel |
| Exclusions | "secured", "recommended" | Verbes generiques (is, has) |

### 13.2 Agnosticite Langue

| Element | Avant (v1.0) | Apres (v1.2) |
|---------|--------------|--------------|
| Detection modaux | Liste de mots EN | POS tagging Universal Dependencies |
| Detection intentionnels | "designed to", "aims to" | Pattern syntaxique xcomp |
| Couverture | EN + FR | Toute langue supportee par spaCy |

### 13.3 Invariant Fondamental

> **OSMOSE raisonne sur la FORME des assertions (structure linguistique, position documentaire), jamais sur le CONTENU metier.**

Toute regle doit etre:
- Linguistique (POS, syntaxe, morphologie)
- OU structurelle (position, scope, proximite)
- JAMAIS lexicale-metier

---

*Document v1.3 - Revue collaborative Claude/ChatGPT - Agnosticite domaine + langue*

---

## 14. Changelog

| Version | Date | Changements |
|---------|------|-------------|
| v1.0 | 2026-01-17 | Version initiale |
| v1.1 | 2026-01-17 | Clarifications ontologiques, `relation_type_candidate`, `typing_confidence` |
| v1.2 | 2026-01-17 | Suppression whitelist lexicale, validation POS-based universelle |
| v1.3 | 2026-01-17 | Suppression `GENERIC_VERBS_EXCLUDED`, detection structurelle copules/attributifs |
