# Plan Implementation : StructureNumberingGate v2.1

**Date** : 2026-01-07
**Status** : Validé par User + ChatGPT
**Objectif** : Filtrer les faux positifs de numerotation structurelle de maniere agnostique

---

## 1. Contexte et Probleme

### 1.1 Faux Positifs Identifies

| Document | Markers Faux Positifs |
|----------|----------------------|
| SAP-014 | "Content 2", "PUBLIC 3" |
| SAP-016 | "Public 2", "Public 3" |
| SAP-020 | "PUBLIC 2", "PUBLIC 3" |
| SAP-021 | "PUBLIC 1", "EXTERNAL 2", "Resources 42", "PUBLIC 3" |

### 1.2 Cause Racine

Le pattern `ENTITY_NUMERAL` (`\d{1,2}`) capture "MOT + CHIFFRE" sans distinguer :
- Version produit (iPhone 15) ✓
- Numerotation section (PUBLIC 3) ✗

### 1.3 Contrainte ADR

Solution DOIT etre **agnostique** : pas de listes de mots hardcodees.

---

## 2. Architecture Solution

```
CandidateMiner (extraction)
    |
    v
    entity_numeral \d{1,2} --> is_weak_candidate = True
    |
    v
CandidateGate (filtres existants: dates, copyright, etc.)
    |
    v
StructureNumberingGate v2.1 (NOUVEAU)
    |
    +-- Evalue 3 signaux:
    |   - S1: Sequentialite (X 1/2/3... dans le doc)
    |   - S2: Position structurelle (debut ligne + ":" ou ".")
    |   - S3: Prefixe quasi-toujours numerote
    |
    +-- Decision:
        - HARD_REJECT si: Seq>=3 ET (S2 ou S3)
        - SOFT_FLAG si: Seq=2 OU signal isole
        - LOW si: aucun signal
    |
    v
HARD_REJECT --> Candidat supprime (avec log)
SOFT_FLAG --> Action configurable (default: LLM avec tag)
LOW --> Candidat normal
    |
    v
Safeguard: Si 0 markers --> Fallback max K=3 weak markers
```

---

## 3. Specifications Techniques

### 3.1 Signal S1 - Sequentialite

**Definition stricte** : Meme prefixe X avec numeros consecutifs.

```python
def detect_sequence(prefix: str, candidates: List[MarkerCandidate]) -> int:
    """
    Retourne la longueur de la plus longue sequence consecutive.

    Ex: "PUBLIC 1", "PUBLIC 2", "PUBLIC 3" -> 3
    Ex: "PUBLIC 1", "PUBLIC 3" -> 1 (pas consecutif)
    """
    numbers = sorted([
        int(c.value.split()[-1])
        for c in candidates
        if c.value.startswith(prefix + " ")
    ])

    max_seq = 1
    current_seq = 1
    for i in range(1, len(numbers)):
        if numbers[i] == numbers[i-1] + 1:
            current_seq += 1
            max_seq = max(max_seq, current_seq)
        else:
            current_seq = 1

    return max_seq
```

**Contrainte NON-NEGOCIABLE** : S1 ne compte QUE les sequences "X N" avec meme prefixe X.
PAS les numeros isoles "1", "2", "3" dans le document.

### 3.2 Signal S2 - Position Structurelle

**Definition** : Candidat en position de titre/section.

```python
SECTION_POSITION_PATTERNS = [
    r'^([A-Z][a-zA-Z]*)\s+(\d{1,2})\s*[:\.\-]',  # "PUBLIC 3:" ou "PUBLIC 3."
    r'^([A-Z][a-zA-Z]*)\s+(\d{1,2})\s*$',        # "PUBLIC 3" seul sur ligne
]

def check_position_indicator(candidate_value: str, full_text: str) -> bool:
    """True si candidat apparait en position structurelle."""
    for line in full_text.split('\n'):
        line = line.strip()
        if candidate_value not in line:
            continue

        # Seul sur la ligne
        if line == candidate_value:
            return True

        # Debut de ligne + ponctuation
        for pattern in SECTION_POSITION_PATTERNS:
            if re.match(pattern, line):
                return True

    return False
```

### 3.3 Signal S3 - Prefixe Quasi-Toujours Numerote

**Definition robuste** (ChatGPT) :

```python
def check_prefix_mostly_numbered(prefix: str, full_text: str) -> bool:
    """
    S3 = TRUE si:
    - count(X + number) >= 3 ET
    - count(X standalone) <= 1 ET
    - distinct_numbers >= 2
    """
    import re

    # Count "PREFIX N" patterns
    pattern_numbered = re.compile(rf'\b{re.escape(prefix)}\s+\d{{1,2}}\b')
    count_numbered = len(pattern_numbered.findall(full_text))

    # Count PREFIX standalone (not followed by number)
    pattern_standalone = re.compile(rf'\b{re.escape(prefix)}\b(?!\s+\d)')
    count_standalone = len(pattern_standalone.findall(full_text))

    # Count distinct numbers
    matches = pattern_numbered.findall(full_text)
    distinct_numbers = len(set(m.split()[-1] for m in matches))

    return (
        count_numbered >= 3 and
        count_standalone <= 1 and
        distinct_numbers >= 2
    )
```

---

## 4. Matrice de Decision

| S1 (Seq) | S2 (Position) | S3 (Prefixe) | Decision |
|----------|---------------|--------------|----------|
| >= 3 | TRUE | - | **HARD_REJECT** |
| >= 3 | - | TRUE | **HARD_REJECT** |
| >= 3 | TRUE | TRUE | **HARD_REJECT** |
| = 2 | - | - | SOFT_FLAG |
| = 2 | TRUE | - | SOFT_FLAG |
| = 1 | TRUE | TRUE | SOFT_FLAG |
| - | - | - | LOW |

---

## 5. Configuration

```python
@dataclass
class StructureGateConfig:
    """Configuration du StructureNumberingGate."""

    # Seuil de sequence pour HARD_REJECT
    sequence_threshold: int = 3

    # Action pour SOFT_FLAG: "llm" ou "weak_marker"
    soft_flag_action: str = "llm"

    # Max weak markers en fallback si doc silencieux
    fallback_max_markers: int = 3

    # Logging des changements de config
    log_config_changes: bool = True
```

---

## 6. Safeguard Documents Silencieux

```python
def apply_fallback_if_silent(
    final_markers: List[MarkerCandidate],
    rejected: List[MarkerCandidate],
    doc_id: str,
    config: StructureGateConfig,
) -> List[MarkerCandidate]:
    """
    Si tous les markers sont rejetes, conserver K weak markers en fallback.
    """
    if len(final_markers) == 0 and len(rejected) > 0:
        logger.warning(
            f"[StructureNumberingGate] Doc '{doc_id}' silencieux. "
            f"Rejected: {[c.value for c in rejected]}"
        )

        # Selectionner top K par frequence + dispersion
        fallback = sorted(
            rejected,
            key=lambda c: (c.occurrences, c.pages_covered),
            reverse=True
        )[:config.fallback_max_markers]

        # Taguer comme fallback
        for m in fallback:
            m.structure_fallback = True
            m.structure_risk = "FALLBACK"

        logger.info(
            f"[StructureNumberingGate] Fallback markers: "
            f"{[m.value for m in fallback]}"
        )

        return fallback

    return final_markers
```

---

## 7. Modifications de Fichiers

### 7.1 candidate_mining.py

| Section | Modification |
|---------|--------------|
| Imports | Ajouter `StructureGateConfig` |
| Constants | Ajouter `SECTION_POSITION_PATTERNS` |
| Classes | Ajouter `SequenceDetectionResult`, `StructureNumberingGate`, `StructureGateConfig` |
| MarkerCandidate | Ajouter champs: `is_weak_candidate`, `structure_risk`, `structure_risk_reason`, `structure_fallback` |
| CandidateMiner | Modifier `mine_document()` pour integrer le gate |

### 7.2 doc_context_extractor.py

| Section | Modification |
|---------|--------------|
| LLM Prompt | Si `structure_risk == "SOFT"`, ajouter contexte au prompt |

---

## 8. Checklist Implementation

### Phase 1 : Classes et Types ✅ COMPLETE (2026-01-07)
- [x] Ajouter `StructureGateConfig` dataclass
- [x] Ajouter `SequenceDetectionResult` dataclass
- [x] Ajouter champs `MarkerCandidate`: `is_weak_candidate`, `structure_risk`, `structure_risk_reason`, `structure_fallback`

### Phase 2 : StructureNumberingGate ✅ COMPLETE (2026-01-07)
- [x] Implementer `detect_sequences()` avec contrainte "same prefix"
- [x] Implementer `check_position_indicator()`
- [x] Implementer `check_prefix_mostly_numbered()` avec definition robuste S3
- [x] Implementer `compute_structure_risk()` avec matrice de decision
- [x] Implementer `filter_candidates()` avec HARD_REJECT/SOFT_FLAG

### Phase 3 : Integration Pipeline ✅ COMPLETE (2026-01-07)
- [x] Modifier `CandidateMiner.__init__()` pour accepter config
- [x] Modifier `CandidateMiner.mine_document()` pour appliquer le gate apres CandidateGate
- [x] Marquer `entity_numeral \d{1,2}` comme `is_weak_candidate=True`
- [x] Implementer fallback documents silencieux

### Phase 4 : LLM Integration (SOFT_FLAG) ✅ COMPLETE (2026-01-07)
- [x] Modifier `to_dict_enriched()` pour inclure `structure_risk`
- [x] Modifier `prompts.py` pour ajouter section "Structure Risk Warnings"
- [x] SOFT_FLAG candidats inclus dans les candidats passes au LLM

### Phase 5 : Tests ✅ COMPLETE (2026-01-07)
- [x] Test unitaire S1 (sequentialite)
- [x] Test unitaire S2 (position)
- [x] Test unitaire S3 (prefixe numerote)
- [x] Test integration sur SAP-021 markers
- [x] Test fallback document silencieux
- [x] Test cas limite: "TLS 1.3", "ISO 27001", "Stage 2"
- [x] 21 tests - tous passent

### Phase 6 : Cleanup ✅ COMPLETE (2026-01-07)
- [x] Mettre a jour exports `__all__`
- [x] Documenter dans ce fichier

---

## 9. Exemples Attendus

### 9.1 Document SAP-021 (avant)

```
Markers: ["PUBLIC 1", "2.6", "4.4", "EXTERNAL 2", "Resources 42", "PUBLIC 3"]
```

### 9.2 Document SAP-021 (apres)

```
Analyse S1: PUBLIC -> sequence [1, 3] = 2 (pas 3 consecutifs)
           Mais EXTERNAL -> [2] = 1, Resources -> [42] = 1

Analyse S2: "PUBLIC 1" en debut de ligne avec ":" -> TRUE
           "PUBLIC 3" en debut de ligne avec ":" -> TRUE

Analyse S3: PUBLIC apparait 3x avec numeros, 0x standalone -> TRUE

Decision:
- "PUBLIC 1": S1=2, S2=TRUE, S3=TRUE -> SOFT_FLAG (seq<3 mais S2+S3)
- "PUBLIC 3": S1=2, S2=TRUE, S3=TRUE -> SOFT_FLAG
- "EXTERNAL 2": S1=1, S2=TRUE, S3=FALSE -> SOFT_FLAG (S2 seul)
- "Resources 42": S1=1, S2=TRUE, S3=FALSE -> SOFT_FLAG

Resultat: Tous en SOFT_FLAG -> passes au LLM pour decision finale
```

### 9.3 Document avec "TLS 1.3" (valide)

```
Analyse S1: TLS -> [1.3] (un seul) = 1
Analyse S2: "TLS 1.3" dans texte, pas en debut ligne seul
Analyse S3: TLS apparait aussi standalone ("TLS handshake", "TLS protocol")

Decision: S1=1, S2=FALSE, S3=FALSE -> LOW (conserve)
```

---

## 10. Rollback Plan

Si le gate cause trop de faux negatifs :

1. Desactiver via config: `StructureGateConfig(enabled=False)`
2. Augmenter seuil: `sequence_threshold=4`
3. Forcer action weak: `soft_flag_action="weak_marker"`

---

**Document de reference pour implementation. Ne pas supprimer.**
