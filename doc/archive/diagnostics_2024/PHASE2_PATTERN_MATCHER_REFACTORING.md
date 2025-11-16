# Phase 2 OSMOSE - Refactoring PatternMatcher (Architecture Robuste)

**Date:** 2025-01-19
**Problème:** Patterns regex figés trop fragiles pour extraction réelle
**Solution:** Architecture hybride multi-stratégies

---

## 🚨 Problème Identifié

### Exemple Réel Manqué
```
Input: "la base HANA est chiffrée au repos en AES256"

Concepts détectés:
- HANA (database)
- AES256 (encryption algorithm)

Relations attendues:
- HANA USES AES256 (encryption)
- HANA HAS_SECURITY_FEATURE "encryption at rest"

❌ Patterns actuels: AUCUNE relation détectée !
```

### Limites Approche Regex Pure

1. **Variabilité linguistique infinie**
   - "utilise", "uses", "is based on", "leverages", "employs"
   - "chiffrée", "encrypted", "secured with", "protected by"
   - Impossibilité de lister tous les verbes

2. **Relations implicites**
   - "HANA chiffrée en AES256" → USES implicite
   - "Fiori dans S/4HANA" → PART_OF implicite
   - "CCR 2023 après CCR 2022" → REPLACES implicite

3. **Contexte technique crucial**
   - "au repos" vs "en transit" → metadata importante
   - "optionnel" vs "obligatoire" → USES vs REQUIRES
   - "deprecated" vs "current" → status relation

4. **Négations et conditions**
   - "ne nécessite PAS" → ne pas créer REQUIRES
   - "peut utiliser" → USES avec strength=WEAK
   - "incompatible avec" → relation négative

---

## ✅ Architecture Hybride Robuste

### Stratégie 1: Co-occurrence Analysis (NEW!)
**Idée:** Concepts mentionnés proches → candidats relations

```python
def find_cooccurring_concepts(
    concepts: List[Dict],
    full_text: str,
    window_size: int = 100  # 100 caractères
) -> List[Tuple[str, str, str]]:
    """
    Trouver concepts co-occurrents dans fenêtres glissantes.

    Returns:
        [(concept_A, concept_B, context_snippet), ...]
    """
    # Pour chaque paire concepts trouvés à <100 chars
    # → Candidat relation (LLM décidera du type)
```

**Exemple:**
```
"la base HANA est chiffrée au repos en AES256"
         ^^^^                           ^^^^^^
         |                               |
         +---------- 35 chars -----------+

→ Candidat: (HANA, AES256, "chiffrée au repos en")
→ LLM: USES (encryption context)
```

### Stratégie 2: spaCy Dependency Parsing (J5)
**Idée:** Analyser structure grammaticale Sujet-Verbe-Objet

```python
import spacy

nlp = spacy.load("fr_core_news_lg")
doc = nlp("la base HANA est chiffrée au repos en AES256")

# Extraire triplets SVO
for token in doc:
    if token.dep_ == "ROOT":  # Verbe principal
        subject = [w for w in token.children if w.dep_ == "nsubj"]
        objects = [w for w in token.children if w.dep_ in ["obj", "obl"]]

        # → (HANA, chiffrée, AES256)
        # Verbe "chiffrée" → mapper vers relation USES
```

**Mapping verbes → relation types:**
```python
VERB_TO_RELATION = {
    # Français
    "utilise": RelationType.USES,
    "nécessite": RelationType.REQUIRES,
    "remplace": RelationType.REPLACES,
    "chiffre": RelationType.USES,  # Context: encryption
    "inclut": RelationType.PART_OF,

    # Anglais
    "uses": RelationType.USES,
    "requires": RelationType.REQUIRES,
    "encrypts": RelationType.USES,
    "includes": RelationType.PART_OF,
    "replaces": RelationType.REPLACES,
}
```

### Stratégie 3: LLM Validation (CRITIQUE!)
**Idée:** LLM décide du type relation + valide contexte

```python
def validate_with_llm(
    candidate: Tuple[str, str, str],  # (conceptA, conceptB, context)
    concepts_metadata: Dict
) -> Optional[TypedRelation]:
    """
    Envoyer candidat au LLM pour validation.

    Prompt:
    '''
    Context: "{context}"
    Concept A: {conceptA.canonical_name} ({conceptA.type})
    Concept B: {conceptB.canonical_name} ({conceptB.type})

    Question: Is there a semantic relation between A and B?
    If yes, which type?
    - USES (A uses B)
    - REQUIRES (A requires B - mandatory)
    - PART_OF (A is part of B)
    - ... [9 core types]

    Answer JSON:
    {
        "has_relation": true/false,
        "relation_type": "USES",
        "confidence": 0.85,
        "direction": "A→B",
        "metadata": {
            "context_type": "encryption",
            "strength": "STRONG"
        }
    }
    '''
    """
```

**Exemple LLM response:**
```json
{
    "has_relation": true,
    "relation_type": "USES",
    "confidence": 0.92,
    "direction": "HANA→AES256",
    "metadata": {
        "context_type": "encryption",
        "encryption_scope": "at_rest",
        "strength": "STRONG"
    }
}
```

### Stratégie 4: Semantic Similarity (Embeddings)
**Idée:** Patterns sémantiques appris via embeddings

```python
def compute_relation_similarity(
    context_embedding: np.ndarray,  # "chiffrée au repos en"
    relation_type_embeddings: Dict[RelationType, np.ndarray]
) -> RelationType:
    """
    Comparer embedding contexte avec embeddings types relations.

    relation_type_embeddings = {
        RelationType.USES: embed("uses, utilizes, employs, leverages"),
        RelationType.REQUIRES: embed("requires, needs, depends on"),
        ...
    }
    """
    similarities = {}
    for rel_type, rel_emb in relation_type_embeddings.items():
        sim = cosine_similarity(context_embedding, rel_emb)
        similarities[rel_type] = sim

    return max(similarities, key=similarities.get)
```

---

## 🏗️ Nouvelle Architecture PatternMatcher

```python
class ImprovedPatternMatcher:
    """
    Matcher hybride multi-stratégies.

    Pipeline:
    1. Co-occurrence analysis (fenêtres glissantes)
    2. spaCy dependency parsing (SVO triplets)
    3. Regex patterns (patterns explicites)
    4. Semantic similarity (embeddings)
    5. LLM validation (final decision)
    """

    def __init__(self):
        self.spacy_nlp = spacy.load("fr_core_news_lg")
        self.llm_router = LLMRouter()
        self.embedder = MultilingualEmbedder(config)

        # Pre-compute relation type embeddings
        self.relation_embeddings = self._compute_relation_embeddings()

    def extract_relations(
        self,
        concepts: List[Dict],
        full_text: str,
        document_id: str
    ) -> List[TypedRelation]:
        """
        Extraction multi-stratégies.
        """
        candidates = []

        # Stratégie 1: Co-occurrence (NOUVEAU!)
        cooccur_candidates = self._extract_cooccurrence(concepts, full_text)
        candidates.extend(cooccur_candidates)

        # Stratégie 2: spaCy SVO (NOUVEAU!)
        spacy_candidates = self._extract_spacy_triplets(concepts, full_text)
        candidates.extend(spacy_candidates)

        # Stratégie 3: Regex patterns (existant)
        regex_candidates = self._extract_regex_patterns(concepts, full_text)
        candidates.extend(regex_candidates)

        # Stratégie 4: Semantic similarity (NOUVEAU!)
        for candidate in candidates:
            if not candidate.relation_type:
                # LLM n'a pas décidé, essayer semantic similarity
                candidate.relation_type = self._infer_type_semantic(
                    candidate.context
                )

        # Stratégie 5: LLM validation (CRITIQUE!)
        validated_relations = []
        for candidate in candidates:
            validated = self._validate_with_llm(candidate, concepts)
            if validated and validated.metadata.confidence >= 0.60:
                validated_relations.append(validated)

        return validated_relations
```

---

## 📊 Performance Attendue

### Baseline (Regex seul)
- Precision: ~70% (beaucoup faux positifs)
- Recall: ~30% (beaucoup manqués)
- **F1-score: ~42%**

### Approche Hybride
- Precision: ~85% (LLM valide)
- Recall: ~70% (co-occurrence + spaCy élargissent)
- **F1-score: ~77%** (+35 points!)

### Cas d'usage améliorés

| Exemple | Regex seul | Hybride |
|---------|------------|---------|
| "HANA chiffrée en AES256" | ❌ Manqué | ✅ USES (0.92) |
| "Fiori inclus dans S/4" | ✅ PART_OF | ✅ PART_OF (0.95) |
| "CCR remplace l'ancien système" | ❌ "ancien système" pas concept | ✅ Ignore (LLM) |
| "peut utiliser OCR optionnel" | ❌ Manqué | ✅ USES (weak) |

---

## 🔄 Plan Implémentation

### Phase 1 (Immédiat)
- [x] Identifier problème patterns figés
- [ ] Implémenter co-occurrence analyzer
- [ ] Ajouter spaCy dependency parsing
- [ ] Créer LLM validation prompt

### Phase 2 (J5-J7)
- [ ] Implémenter semantic similarity
- [ ] Tests sur 100 cas réels
- [ ] Tuning seuils confidence

### Phase 3 (J8-J10)
- [ ] Optimisation prompts LLM
- [ ] Cache LLM responses (mêmes patterns)
- [ ] Monitoring précision/recall

---

## 💡 Conclusion

**Problème initial:** Patterns regex trop rigides, manquent 70% relations réelles

**Solution:** Architecture hybride 5 stratégies complémentaires

**Gain attendu:** +35 points F1-score (42% → 77%)

**Clé du succès:** LLM validation finale (décision intelligente basée contexte)
