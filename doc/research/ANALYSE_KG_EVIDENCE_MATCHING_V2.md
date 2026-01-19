# Analyse: Amelioration du Matching KG-Assertion et UX Evidence

**Date**: 2026-01-17
**Statut**: Analyse en cours - Collaboration Claude/ChatGPT
**Contexte**: OSMOSE Assertion-Centric UX

---

## 1. Contexte et Problemes Observes

### 1.1 Situation Actuelle

Le systeme OSMOSE genere des reponses instrumentees avec des assertions classifiees (FACT, INFERRED, FRAGILE, CONFLICT). Un mecanisme de "KG_BOOST" permet d'upgrader une assertion FRAGILE en FACT si elle est soutenue par une relation confirmee dans le Knowledge Graph.

**Flux actuel**:
1. L'utilisateur pose une question
2. Le LLM genere des assertions candidates
3. Le classifier evalue chaque assertion contre les sources
4. Si une assertion mentionne deux concepts lies par une relation KG confirmee, elle est promue en FACT
5. L'evidence_quote de la relation KG est affichee dans le hover

### 1.2 Probleme 1: Traduction Inappropriee des Termes Techniques

**Observation**:
```
Assertion generee: "SAP S/4HANA Cloud Private Edition est une suite d'affaires
de nouvelle generation entierement construite sur la plateforme en memoire SAP HANA."
```

**Probleme**: "suite d'affaires" est une traduction mot-a-mot incorrecte de "Business Suite". Le terme technique anglais devrait etre preserve.

**Contrainte**: La solution doit etre **agnostique au domaine**. On ne peut pas ajouter d'instructions specifiques "garder les termes SAP en anglais" car le systeme doit fonctionner pour n'importe quel corpus (juridique, medical, finance, etc.).

**Caracteristiques des termes a preserver**:
- Noms propres de produits (SAP S/4HANA, Microsoft Azure, etc.)
- Acronymes techniques (ERP, CRM, API, etc.)
- Termes anglais etablis dans le domaine (Business Suite, In-Memory, On-Premise)
- Expressions composees avec majuscules (Knowledge Graph, Machine Learning)

### 1.3 Probleme 2: Matching Substring Trop Naif

**Code actuel** (`assertion_classifier.py` lignes 617-621):
```python
source_in = rel["source"] in assertion_text_lower
target_in = rel["target"] in assertion_text_lower
if source_in and target_in:
    # Boost applique
```

**Probleme**: Le matching `in` est une recherche de substring.

**Exemple problematique**:
- Relation KG: `SAP S/4HANA Cloud Private Edition --[EXTENDS]--> SAP S/4HANA`
- Assertion: "SAP S/4HANA Cloud Private Edition utilise SAP Fiori"
- Test: `"sap s/4hana" in "sap s/4hana cloud private edition utilise sap fiori"` → **True**

Le matching retourne True car "sap s/4hana" est une substring de "sap s/4hana cloud private edition", meme si l'assertion ne mentionne PAS le concept "SAP S/4HANA" en tant que tel.

**Note importante**: Les deux concepts SONT distincts ("SAP S/4HANA" ≠ "SAP S/4HANA Cloud Private Edition"), mais l'un contient l'autre comme substring.

### 1.4 Probleme 3: Absence de Validation Semantique de la Relation

**Observation**:
L'evidence_quote affichee pour TOUTES les assertions vertes est:
```
"This extension will be available to all SAP S/4HANA customers in SAP S/4HANA
Cloud Private Edition as well as those with an SAP S/4HANA on-premise deployment..."
```

Mais les assertions concernees parlent de:
- Architecture (plateforme in-memory)
- UX (SAP Fiori)
- Modele de deploiement (instances dediees)
- Integration (connecteurs)

**Aucune de ces assertions ne parle de la relation EXTENDS** (extension, derivation, version de...).

Le matching verifie la presence des concepts mais pas si l'assertion **parle semantiquement de la relation entre ces concepts**.

### 1.5 Probleme 4: UX Non Differenciee

Actuellement, toute assertion matchee affiche la meme evidence_quote, qu'elle soit pertinente ou non. L'utilisateur voit une "preuve" qui ne prouve pas ce que l'assertion affirme.

---

## 2. Analyse des Causes Racines

### 2.1 Taxonomie des Problemes

| ID | Probleme | Cause Racine | Impact UX |
|----|----------|--------------|-----------|
| P1 | Traduction mot-a-mot | Prompt LLM sans guidage preservation termes techniques | Perte de sens metier |
| P2 | Matching substring | Operateur `in` Python sur strings | Faux positifs massifs |
| P3 | Pas de validation semantique | Absence de verification relation-assertion | Evidence non pertinente |
| P4 | UX uniforme | Meme affichage quel que soit le niveau de confiance | Confiance mal calibree |

### 2.2 Dependances entre Problemes

```
P2 (Substring) ──────┐
                     ├──► P3 (Pas de validation) ──► P4 (UX uniforme)
P1 (Traduction) ─────┘
```

- P1 et P2 sont independants mais aggravent P3
- P3 est la cause directe de P4
- Resoudre P3 resout partiellement P4

---

## 3. Propositions de Solutions

### 3.1 Solution pour P1: Preservation Termes Techniques (Agnostique Domaine)

**Objectif**: Eviter la traduction mot-a-mot des termes techniques sans instruction domaine-specifique.

**Approche A: Detection Heuristique + Instruction Generique**

Ajouter au prompt de generation d'assertions:
```
REGLE LINGUISTIQUE IMPORTANTE:
- Preserve les termes techniques en anglais quand ils sont reconnus dans le domaine
- Indices de termes a preserver:
  * Noms propres (majuscules): "Business Suite", "Knowledge Graph"
  * Acronymes: ERP, API, CRM, SaaS
  * Expressions composees techniques: "on-premise", "in-memory"
  * Termes entre guillemets dans les sources
- En cas de doute, garde le terme anglais original
```

**Approche B: Post-processing avec Detection**

Apres generation, detecter les traductions probables:
1. Extraire les n-grams de l'assertion
2. Comparer avec les termes des sources (embeddings ou exact match)
3. Si un n-gram source en anglais a ete traduit, le restaurer

**Approche C: Few-shot Examples**

Inclure des exemples de bonne/mauvaise pratique dans le prompt:
```
EXEMPLES:
❌ "suite d'affaires de nouvelle generation"
✓ "Business Suite de nouvelle generation"

❌ "apprentissage automatique" (dans un contexte technique)
✓ "Machine Learning"
```

**Recommandation**: Combiner A + C pour une solution robuste et agnostique.

### 3.2 Solution pour P2: Matching de Concepts Precis

**Objectif**: Eviter les faux positifs dus au matching substring.

**Approche A: Tokenization + Word Boundaries**

```python
import re

def concept_in_text(concept: str, text: str) -> bool:
    """Verifie si le concept apparait comme entite complete, pas substring."""
    # Escape les caracteres speciaux regex
    pattern = r'\b' + re.escape(concept.lower()) + r'\b'
    return bool(re.search(pattern, text.lower()))

# Test
concept_in_text("sap s/4hana", "sap s/4hana cloud private edition")  # False ✓
concept_in_text("sap s/4hana", "sap s/4hana est une solution")       # True ✓
```

**Probleme**: Le `/` dans "S/4HANA" peut casser les word boundaries.

**Approche B: Normalisation + Tokenization Intelligente**

```python
def normalize_for_matching(text: str) -> List[str]:
    """Tokenise en preservant les entites composees."""
    # Remplacer / par espace pour tokenization
    text = text.replace('/', ' ')
    # Tokeniser
    tokens = text.lower().split()
    return tokens

def concept_matches(concept: str, text: str) -> bool:
    """Verifie si tous les tokens du concept sont presents consecutivement."""
    concept_tokens = normalize_for_matching(concept)
    text_tokens = normalize_for_matching(text)

    # Chercher la sequence de tokens
    n = len(concept_tokens)
    for i in range(len(text_tokens) - n + 1):
        if text_tokens[i:i+n] == concept_tokens:
            return True
    return False
```

**Approche C: Verification de Non-Inclusion**

```python
def concepts_both_present(source: str, target: str, text: str) -> bool:
    """Verifie que les deux concepts sont presents distinctement."""
    text_lower = text.lower()
    source_lower = source.lower()
    target_lower = target.lower()

    # Verifier que l'un n'est pas substring de l'autre
    if source_lower in target_lower or target_lower in source_lower:
        # Cas special: concepts imbriques
        # Verifier que le texte contient AUSSI le concept court seul
        # (pas juste comme partie du concept long)

        # Trouver toutes les occurrences du concept court
        short = source_lower if len(source_lower) < len(target_lower) else target_lower
        long = target_lower if len(source_lower) < len(target_lower) else source_lower

        # Le texte doit contenir le concept long ET le court hors du long
        if long not in text_lower:
            return False

        # Retirer les occurrences du long et verifier si le court reste
        text_without_long = text_lower.replace(long, "")
        return short in text_without_long

    # Cas simple: concepts non imbriques
    return source_lower in text_lower and target_lower in text_lower
```

**Recommandation**: Approche C car elle gere le cas specifique des concepts imbriques.

### 3.3 Solution pour P3: Validation Semantique de la Relation

**Objectif**: Verifier que l'assertion parle vraiment de la relation, pas juste des concepts.

**Approche A: Keywords de Relation**

Definir des patterns linguistiques par type de relation:

```python
RELATION_INDICATORS = {
    "EXTENDS": [
        "extend", "extension", "base sur", "derive de", "version de",
        "herite", "heritage", "construit sur", "evolue depuis",
        "successeur", "evolution de"
    ],
    "REQUIRES": [
        "necessite", "requiert", "depend de", "prerequis",
        "obligation", "doit avoir"
    ],
    "PART_OF": [
        "partie de", "composant de", "inclus dans", "contenu dans",
        "module de", "element de"
    ],
    "INTEGRATES_WITH": [
        "integre avec", "connecte a", "interface avec",
        "communique avec", "interopere"
    ],
    # ... autres relations
}

def relation_expressed_in_text(relation_type: str, text: str) -> bool:
    """Verifie si le texte exprime semantiquement la relation."""
    indicators = RELATION_INDICATORS.get(relation_type, [])
    text_lower = text.lower()
    return any(ind in text_lower for ind in indicators)
```

**Approche B: Embedding Similarity Evidence-Assertion**

```python
async def validate_evidence_relevance(
    assertion_text: str,
    evidence_quote: str,
    threshold: float = 0.75
) -> Tuple[bool, float]:
    """Verifie la similarite semantique entre assertion et evidence."""
    # Encoder les deux textes
    embeddings = embedder.encode([assertion_text, evidence_quote])

    # Similarite cosinus
    similarity = cosine_similarity(embeddings[0], embeddings[1])

    return similarity >= threshold, similarity
```

**Approche C: NLI (Natural Language Inference)**

Utiliser un modele NLI pour verifier si l'evidence "entails" l'assertion:

```python
from transformers import pipeline

nli = pipeline("text-classification", model="MoritzLaworker/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")

def evidence_supports_assertion(evidence: str, assertion: str) -> Tuple[str, float]:
    """Verifie si l'evidence supporte l'assertion via NLI."""
    result = nli(f"{evidence} [SEP] {assertion}")
    # Retourne: "entailment", "neutral", ou "contradiction"
    return result[0]['label'], result[0]['score']
```

**Approche D: Combinaison Hybride (Recommandee)**

```python
@dataclass
class RelationValidation:
    concepts_match: bool          # Les deux concepts sont presents
    relation_expressed: bool      # Des indicateurs de la relation sont presents
    semantic_similarity: float    # Similarite embedding evidence-assertion
    nli_label: str               # Resultat NLI
    confidence: float            # Score combine

def validate_kg_boost(
    assertion: Assertion,
    kg_relation: Dict[str, Any],
    config: ValidationConfig
) -> RelationValidation:
    """Validation complete du KG boost."""

    # Etape 1: Matching des concepts (avec gestion imbrication)
    concepts_match = concepts_both_present(
        kg_relation["source"],
        kg_relation["target"],
        assertion.text_md
    )

    if not concepts_match:
        return RelationValidation(
            concepts_match=False,
            relation_expressed=False,
            semantic_similarity=0.0,
            nli_label="neutral",
            confidence=0.0
        )

    # Etape 2: Detection indicateurs de relation
    relation_expressed = relation_expressed_in_text(
        kg_relation["relation"],
        assertion.text_md
    )

    # Etape 3: Similarite semantique (si evidence disponible)
    semantic_similarity = 0.0
    if kg_relation.get("evidence_quote"):
        _, semantic_similarity = await validate_evidence_relevance(
            assertion.text_md,
            kg_relation["evidence_quote"]
        )

    # Etape 4: NLI (optionnel, couteux)
    nli_label = "neutral"
    if config.use_nli and kg_relation.get("evidence_quote"):
        nli_label, _ = evidence_supports_assertion(
            kg_relation["evidence_quote"],
            assertion.text_md
        )

    # Calcul du score de confiance combine
    confidence = calculate_combined_confidence(
        concepts_match=concepts_match,
        relation_expressed=relation_expressed,
        semantic_similarity=semantic_similarity,
        nli_label=nli_label,
        config=config
    )

    return RelationValidation(
        concepts_match=concepts_match,
        relation_expressed=relation_expressed,
        semantic_similarity=semantic_similarity,
        nli_label=nli_label,
        confidence=confidence
    )
```

### 3.4 Solution pour P4: UX Differenciee

**Objectif**: Adapter l'affichage selon le niveau de validation.

**Proposition de Niveaux d'Evidence**:

| Niveau | Criteres | Affichage UX |
|--------|----------|--------------|
| **DIRECT** | NLI=entailment OU similarity>0.8 | Evidence quote complete + badge "Preuve directe" |
| **SUPPORTED** | relation_expressed=True ET similarity>0.6 | Evidence quote + badge "Relation confirmee" |
| **CONTEXTUAL** | concepts_match=True seulement | Message "Concepts lies dans le KG" (pas de quote) |
| **NONE** | Aucun match | Pas de section KG |

**Maquette UX**:

```
┌─────────────────────────────────────────────────────────────┐
│ NIVEAU DIRECT                                                │
├─────────────────────────────────────────────────────────────┤
│ 🔗 Preuve directe: EXTENDS                           [98%]  │
│ ───────────────────────────────────────────────────────────│
│ "This extension will be available to all SAP S/4HANA       │
│  customers in SAP S/4HANA Cloud Private Edition..."        │
│ ───────────────────────────────────────────────────────────│
│ ✓ Confirme par 2 source(s) dans le Knowledge Graph         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ NIVEAU SUPPORTED                                             │
├─────────────────────────────────────────────────────────────┤
│ 🔗 Relation confirmee: EXTENDS                       [85%]  │
│ ───────────────────────────────────────────────────────────│
│ "This extension will be available..."                       │
│ ───────────────────────────────────────────────────────────│
│ ℹ Cette assertion mentionne des concepts lies              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ NIVEAU CONTEXTUAL                                            │
├─────────────────────────────────────────────────────────────┤
│ ℹ Contexte KG                                               │
│ ───────────────────────────────────────────────────────────│
│ Les concepts mentionnes sont lies dans le Knowledge Graph:  │
│ SAP S/4HANA Cloud Private Edition ──[EXTENDS]──> SAP S/4HANA│
│                                                              │
│ (L'assertion ne traite pas directement de cette relation)   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Architecture Proposee

### 4.1 Nouveau Pipeline de Validation

```
┌─────────────────────┐
│  Assertion Candidate │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 1. Concept Matcher  │ ← Matching precis (pas substring)
│    (P2 resolution)  │
└──────────┬──────────┘
           │ concepts_match = True/False
           ▼
┌─────────────────────┐
│ 2. Relation Detector│ ← Detection indicateurs linguistiques
│    (P3 partiel)     │
└──────────┬──────────┘
           │ relation_expressed = True/False
           ▼
┌─────────────────────┐
│ 3. Semantic Validator│ ← Embedding similarity
│    (P3 complet)      │
└──────────┬──────────┘
           │ similarity_score = 0.0-1.0
           ▼
┌─────────────────────┐
│ 4. Evidence Level   │ ← Classification DIRECT/SUPPORTED/CONTEXTUAL
│    Classifier (P4)  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 5. UX Renderer      │ ← Affichage adapte au niveau
│    (P4)             │
└─────────────────────┘
```

### 4.2 Nouveaux Champs de Donnees

**Backend (AssertionSupport)**:
```python
class AssertionSupport(BaseModel):
    # ... champs existants ...

    # Nouveau: Niveau de validation KG
    kg_evidence_level: Optional[Literal["DIRECT", "SUPPORTED", "CONTEXTUAL"]] = None
    kg_semantic_similarity: Optional[float] = None
    kg_relation_expressed: Optional[bool] = None
```

**Frontend (TypeScript)**:
```typescript
interface AssertionSupport {
  // ... champs existants ...

  kg_evidence_level?: 'DIRECT' | 'SUPPORTED' | 'CONTEXTUAL'
  kg_semantic_similarity?: number
  kg_relation_expressed?: boolean
}
```

---

## 5. Plan d'Implementation

### Phase 1: Correction Matching (P2) - Priorite Haute
- [ ] Implementer `concepts_both_present()` avec gestion imbrication
- [ ] Remplacer le matching `in` actuel
- [ ] Tests unitaires avec cas limites

### Phase 2: Detection Relation (P3 partiel) - Priorite Haute
- [ ] Creer `RELATION_INDICATORS` dictionnaire multilingue
- [ ] Implementer `relation_expressed_in_text()`
- [ ] Ajouter au pipeline de classification

### Phase 3: Validation Semantique (P3 complet) - Priorite Moyenne
- [ ] Implementer `validate_evidence_relevance()` avec embeddings
- [ ] Definir seuils de similarite
- [ ] Benchmark performance (latence acceptable?)

### Phase 4: UX Differenciee (P4) - Priorite Moyenne
- [ ] Ajouter `kg_evidence_level` au schema
- [ ] Modifier `AssertionPopover.tsx` pour affichage conditionnel
- [ ] Design review des 3 niveaux

### Phase 5: Preservation Termes Techniques (P1) - Priorite Basse
- [ ] Ajouter instructions generiques au prompt
- [ ] Creer few-shot examples
- [ ] Tester sur differents domaines

---

## 6. Questions Ouvertes pour Discussion

1. **Performance**: La validation semantique (embeddings) ajoute-t-elle trop de latence?
   - Option: Validation async post-rendu initial

2. **Seuils**: Quels seuils de similarite pour DIRECT vs SUPPORTED?
   - Proposition: DIRECT > 0.80, SUPPORTED > 0.60

3. **NLI**: Faut-il integrer un modele NLI ou les embeddings suffisent?
   - Trade-off: Precision vs Latence vs Complexite

4. **Multilingue**: Les indicateurs de relation doivent couvrir FR + EN minimum
   - Comment gerer d'autres langues (DE, ES...)?

5. **Fallback**: Que faire si aucun niveau n'est atteint mais KG confirme la relation?
   - Proposition: Niveau CONTEXTUAL par defaut

---

## 7. Metriques de Succes

| Metrique | Actuel | Cible |
|----------|--------|-------|
| Faux positifs matching | ~80% | < 10% |
| Evidence pertinente affichee | ~20% | > 80% |
| Latence ajoutee | 0ms | < 100ms |
| Satisfaction utilisateur (hover) | A mesurer | Qualitative |

---

## Annexe A: Exemples de Test

### Cas 1: Match Correct - Niveau DIRECT
```
Assertion: "SAP S/4HANA Cloud Private Edition etend SAP S/4HANA avec des
           fonctionnalites cloud privees."
Relation KG: S/4HANA CPE --[EXTENDS]--> S/4HANA
Evidence: "This extension will be available to all SAP S/4HANA customers..."

→ concepts_match: True (les deux presents distinctement)
→ relation_expressed: True ("etend")
→ similarity: 0.85
→ Niveau: DIRECT ✓
```

### Cas 2: Match Incorrect Actuel - Niveau CONTEXTUAL
```
Assertion: "SAP S/4HANA Cloud Private Edition utilise SAP Fiori pour l'UX."
Relation KG: S/4HANA CPE --[EXTENDS]--> S/4HANA
Evidence: "This extension will be available..."

→ concepts_match: False (S/4HANA seul n'est pas present)
→ Niveau: NONE (pas de KG info affichee) ✓
```

### Cas 3: Concepts Presents mais Relation Differente
```
Assertion: "SAP S/4HANA Cloud Private Edition et SAP S/4HANA partagent
           la meme base de donnees HANA."
Relation KG: S/4HANA CPE --[EXTENDS]--> S/4HANA
Evidence: "This extension will be available..."

→ concepts_match: True
→ relation_expressed: False (pas de notion d'extension)
→ similarity: 0.45
→ Niveau: CONTEXTUAL ✓
```

---

*Document genere pour analyse collaborative Claude/ChatGPT*
