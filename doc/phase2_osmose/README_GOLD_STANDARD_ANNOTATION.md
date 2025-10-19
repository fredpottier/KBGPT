# 📊 Script Annotation Gold Standard - Phase 2

**Objectif:** Créer un dataset de référence avec 450 relations annotées manuellement (50 par type core) pour valider la precision/recall du RelationExtractionEngine.

---

## 🎯 Qu'est-ce que le Gold Standard ?

### Définition

Le **Gold Standard** est un dataset de référence annoté **manuellement par des humains** qui sert de vérité terrain pour :

1. **Entraîner** des algorithmes (si ML supervisé)
2. **Valider** la performance d'extraction automatique
3. **Calculer** precision, recall, F1-score
4. **Comparer** différentes approches (pattern-based vs LLM)

### Exemple Concret

```json
{
  "relation_id": "gold_001",
  "source_concept": "SAP Fiori",
  "target_concept": "SAP S/4HANA Cloud",
  "relation_type": "PART_OF",
  "context": "SAP Fiori is a component of SAP S/4HANA Cloud providing user experience layer...",
  "document_id": "doc_sap_s4hana_overview.pptx",
  "chunk_id": "chunk_12",
  "annotator": "john.doe@company.com",
  "confidence_human": 1.0,
  "notes": "Clear compositional relationship, explicitly stated",
  "created_at": "2025-10-19T14:30:00Z"
}
```

---

## 🛠️ Script `annotate_relations_gold_standard.py`

### Vue d'Ensemble

```python
# scripts/annotate_relations_gold_standard.py

"""
Script interactif pour annoter manuellement des relations entre concepts.

Usage:
    python scripts/annotate_relations_gold_standard.py \
        --corpus data/phase2_test/ \
        --types PART_OF,REQUIRES,USES,INTEGRATES_WITH,SUBTYPE_OF,VERSION_OF,PRECEDES,REPLACES,DEPRECATES \
        --samples_per_type 50 \
        --annotators 2 \
        --output data/phase2_gold_standard.json

Output:
    - data/phase2_gold_standard.json : Relations annotées
    - data/phase2_gold_standard_stats.json : Statistiques inter-annotator agreement
"""
```

---

### Architecture

```
┌────────────────────────────────────────────────────────┐
│ 1. EXTRACTION CANDIDATE RELATIONS                      │
│    - Parse corpus documents (PPTX/PDF)                 │
│    - Detect concept pairs co-occurring                 │
│    - Generate 500+ candidate relations                 │
└────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────┐
│ 2. SAMPLING STRATIFIED                                 │
│    - Sample 50 relations par type (balanced)           │
│    - Assurer diversité domaines (Software, Pharma...)  │
│    - Éviter biais sur documents populaires             │
└────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────┐
│ 3. ANNOTATION INTERFACE (CLI ou Web)                   │
│    - Présenter context chunk                           │
│    - Proposer (Concept A, Concept B)                   │
│    - Demander : Relation type ? [PART_OF|NONE|...]     │
│    - Valider : Confidence ? [0.5|0.75|1.0]             │
└────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────┐
│ 4. INTER-ANNOTATOR AGREEMENT                           │
│    - 2 annotateurs indépendants                        │
│    - Cohen's Kappa calculation                         │
│    - Résolution conflits (3e annotateur si Kappa<0.75) │
└────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────┐
│ 5. EXPORT GOLD STANDARD                                │
│    - JSON avec 450 relations validées                  │
│    - Stats : Kappa, confusion matrix                   │
└────────────────────────────────────────────────────────┘
```

---

## 📋 Étapes Détaillées

### Étape 1 : Extraction Candidate Relations

```python
def extract_candidate_relations(corpus_path: str) -> List[CandidateRelation]:
    """
    Parse documents et extrait paires de concepts co-occurrents.

    Returns:
        Liste de 500+ candidates (non-annotés) pour sélection.
    """
    candidates = []

    for doc_path in glob(f"{corpus_path}/**/*.pptx"):
        # Parse document (réutiliser PPTXPipeline Phase 1.5)
        text, chunks = extract_text_chunks(doc_path)

        # Detect concepts (simple NER ou réutiliser Phase 1.5 concepts)
        concepts = detect_concepts(text)

        # Co-occurrence dans même chunk (fenêtre 500 caractères)
        for chunk in chunks:
            chunk_concepts = [c for c in concepts if c.text in chunk.text]

            # Générer paires (A, B)
            for i, concept_a in enumerate(chunk_concepts):
                for concept_b in chunk_concepts[i+1:]:
                    candidates.append(CandidateRelation(
                        source=concept_a.text,
                        target=concept_b.text,
                        context=chunk.text[:500],  # Limite 500 chars
                        document_id=doc_path,
                        chunk_id=chunk.id
                    ))

    return candidates
```

**Output Attendu:**
- ~500-1000 candidate relations extraites du corpus
- Stockage temporaire : `data/phase2_candidates.json`

---

### Étape 2 : Sampling Stratifié

```python
def stratified_sampling(
    candidates: List[CandidateRelation],
    types: List[str],
    samples_per_type: int = 50
) -> List[CandidateRelation]:
    """
    Sélection équilibrée de relations à annoter.

    Args:
        candidates: Liste complète candidates
        types: 9 types core relations
        samples_per_type: 50 relations par type

    Returns:
        450 candidates sélectionnés (50 × 9 types)
    """
    selected = []

    for relation_type in types:
        # Filtrer candidates pertinents pour ce type (heuristiques basiques)
        # Ex: PART_OF → chercher "component", "module", "part of" dans context
        type_candidates = filter_by_type_heuristic(candidates, relation_type)

        # Diversité domaines
        balanced = balance_by_domain(type_candidates, domains=["Software", "Pharma", "Retail", "Other"])

        # Sample aléatoire 50
        sampled = random.sample(balanced, min(50, len(balanced)))
        selected.extend(sampled)

    return selected
```

**Stratégie Balancing:**
- 40% Software (SAP, Oracle, etc.)
- 20% Pharma (médicaments, essais cliniques)
- 20% Retail (e-commerce, supply chain)
- 20% Other (Manufacturing, Finance, Legal)

---

### Étape 3 : Interface Annotation CLI

```python
def annotate_cli(candidates: List[CandidateRelation], annotator_id: str) -> List[AnnotatedRelation]:
    """
    Interface CLI interactive pour annotation manuelle.
    """
    annotations = []

    for i, candidate in enumerate(candidates, 1):
        print(f"\n{'='*80}")
        print(f"Relation {i}/{len(candidates)}")
        print(f"{'='*80}")
        print(f"\nDocument: {candidate.document_id}")
        print(f"\nContext:\n{candidate.context}\n")
        print(f"Concept A: [{candidate.source}]")
        print(f"Concept B: [{candidate.target}]")
        print(f"\nQuelle relation existe entre A et B ?")
        print("Options:")
        print("  1. PART_OF         (A est composant de B)")
        print("  2. SUBTYPE_OF      (A est sous-catégorie de B)")
        print("  3. REQUIRES        (A nécessite B - obligatoire)")
        print("  4. USES            (A utilise B - optionnel)")
        print("  5. INTEGRATES_WITH (A s'intègre avec B)")
        print("  6. VERSION_OF      (A est version de B)")
        print("  7. PRECEDES        (A précède B chronologiquement)")
        print("  8. REPLACES        (A remplace B)")
        print("  9. DEPRECATES      (A déprécie B)")
        print("  0. NONE            (Aucune relation)")

        choice = input("\nVotre choix [0-9]: ").strip()

        if choice == "0":
            relation_type = "NONE"
            confidence = 1.0
        else:
            relation_type = RELATION_TYPES[int(choice)]
            confidence = float(input("Confidence [0.5/0.75/1.0]: ").strip())

        notes = input("Notes optionnelles: ").strip()

        annotations.append(AnnotatedRelation(
            relation_id=f"gold_{annotator_id}_{i:03d}",
            source=candidate.source,
            target=candidate.target,
            relation_type=relation_type,
            context=candidate.context,
            document_id=candidate.document_id,
            chunk_id=candidate.chunk_id,
            annotator=annotator_id,
            confidence_human=confidence,
            notes=notes,
            created_at=datetime.utcnow().isoformat()
        ))

        # Sauv egarde progressive tous les 10 annotations
        if i % 10 == 0:
            save_checkpoint(annotations, f"data/phase2_gold_{annotator_id}_checkpoint.json")

    return annotations
```

**Interface Alternative (Web Streamlit) :**

```python
# scripts/annotate_relations_streamlit.py

import streamlit as st

def annotate_web():
    """Interface web Streamlit pour annotation plus conviviale"""

    st.title("📊 Gold Standard Annotation - Phase 2 OSMOSE")

    # Load candidates
    candidates = load_candidates("data/phase2_candidates.json")

    # Progress bar
    progress = st.progress(0)

    # Annotation form
    for i, candidate in enumerate(candidates):
        st.header(f"Relation {i+1}/{len(candidates)}")

        # Context display
        st.text_area("Context", candidate.context, height=150, disabled=True)

        # Concepts
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Concept A:** {candidate.source}")
        with col2:
            st.info(f"**Concept B:** {candidate.target}")

        # Relation type selection
        relation_type = st.selectbox(
            "Type de relation",
            ["NONE", "PART_OF", "SUBTYPE_OF", "REQUIRES", "USES",
             "INTEGRATES_WITH", "VERSION_OF", "PRECEDES", "REPLACES", "DEPRECATES"]
        )

        # Confidence
        confidence = st.slider("Confidence", 0.5, 1.0, 1.0, step=0.25)

        # Notes
        notes = st.text_input("Notes optionnelles")

        # Submit
        if st.button("Valider"):
            save_annotation(candidate, relation_type, confidence, notes)
            st.success("Annotation sauvegardée !")
            progress.progress((i+1) / len(candidates))
```

---

### Étape 4 : Inter-Annotator Agreement

```python
def calculate_inter_annotator_agreement(
    annotations_a: List[AnnotatedRelation],
    annotations_b: List[AnnotatedRelation]
) -> Dict[str, float]:
    """
    Calcule Cohen's Kappa entre 2 annotateurs.

    Returns:
        {
            "kappa": 0.82,           # Cohen's Kappa
            "agreement_rate": 0.89,  # % accord total
            "confusion_matrix": {...}
        }
    """
    from sklearn.metrics import cohen_kappa_score, confusion_matrix

    # Alignment annotations (même source, target)
    aligned = align_annotations(annotations_a, annotations_b)

    # Extract labels
    labels_a = [a.relation_type for a in aligned["annotator_a"]]
    labels_b = [b.relation_type for b in aligned["annotator_b"]]

    # Cohen's Kappa
    kappa = cohen_kappa_score(labels_a, labels_b)

    # Agreement rate
    agreement_rate = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / len(labels_a)

    # Confusion matrix
    cm = confusion_matrix(labels_a, labels_b, labels=RELATION_TYPES + ["NONE"])

    return {
        "kappa": kappa,
        "agreement_rate": agreement_rate,
        "confusion_matrix": cm.tolist(),
        "interpretation": interpret_kappa(kappa)
    }

def interpret_kappa(kappa: float) -> str:
    """Interprétation Cohen's Kappa"""
    if kappa >= 0.81:
        return "✅ Excellent agreement"
    elif kappa >= 0.61:
        return "✅ Substantial agreement"
    elif kappa >= 0.41:
        return "⚠️ Moderate agreement - Review conflicts"
    else:
        return "❌ Poor agreement - Retraining needed"
```

**Critères Qualité:**
- **Cohen's Kappa ≥ 0.75** : Target minimum (substantial agreement)
- **Cohen's Kappa ≥ 0.85** : Excellent (idéal pour gold standard)
- **Cohen's Kappa < 0.75** : Nécessite résolution conflits (3e annotateur)

**Résolution Conflits:**

```python
def resolve_conflicts(
    annotations_a: List[AnnotatedRelation],
    annotations_b: List[AnnotatedRelation],
    kappa: float
) -> List[AnnotatedRelation]:
    """
    Résolution conflits si Kappa < 0.75
    """
    if kappa >= 0.75:
        # Majorité agreement → merger avec vote majoritaire
        return merge_by_majority_vote(annotations_a, annotations_b)

    # Identifier désaccords
    conflicts = []
    for ann_a, ann_b in zip(annotations_a, annotations_b):
        if ann_a.relation_type != ann_b.relation_type:
            conflicts.append((ann_a, ann_b))

    print(f"⚠️ {len(conflicts)} conflicts detected (Kappa={kappa:.2f})")

    # 3e annotateur pour résolution
    print("🔍 Requiring 3rd annotator for conflict resolution...")
    resolved = annotate_conflicts_by_third_annotator(conflicts)

    # Merger avec résolutions
    final = merge_with_resolutions(annotations_a, annotations_b, resolved)

    return final
```

---

### Étape 5 : Export Gold Standard

```python
def export_gold_standard(
    annotations: List[AnnotatedRelation],
    output_path: str = "data/phase2_gold_standard.json"
):
    """
    Export final gold standard avec stats.
    """
    # Filter out NONE relations
    valid_relations = [a for a in annotations if a.relation_type != "NONE"]

    # Statistics
    stats = {
        "total_relations": len(valid_relations),
        "relations_per_type": {
            rel_type: len([a for a in valid_relations if a.relation_type == rel_type])
            for rel_type in RELATION_TYPES
        },
        "domains_distribution": calculate_domain_distribution(valid_relations),
        "avg_confidence": np.mean([a.confidence_human for a in valid_relations]),
        "inter_annotator_kappa": 0.82,  # From previous step
        "created_at": datetime.utcnow().isoformat()
    }

    # Export JSON
    output = {
        "metadata": stats,
        "relations": [asdict(a) for a in valid_relations]
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"✅ Gold Standard exported: {output_path}")
    print(f"   Total relations: {len(valid_relations)}")
    print(f"   Cohen's Kappa: {stats['inter_annotator_kappa']}")
    print(f"   Avg confidence: {stats['avg_confidence']:.2f}")
```

**Output Format:**

```json
{
  "metadata": {
    "total_relations": 423,
    "relations_per_type": {
      "PART_OF": 48,
      "SUBTYPE_OF": 45,
      "REQUIRES": 50,
      "USES": 47,
      "INTEGRATES_WITH": 43,
      "VERSION_OF": 50,
      "PRECEDES": 46,
      "REPLACES": 49,
      "DEPRECATES": 45
    },
    "domains_distribution": {
      "Software": 169,
      "Pharma": 85,
      "Retail": 85,
      "Other": 84
    },
    "avg_confidence": 0.92,
    "inter_annotator_kappa": 0.82,
    "created_at": "2025-10-19T18:45:00Z"
  },
  "relations": [
    {
      "relation_id": "gold_001",
      "source": "SAP Fiori",
      "target": "SAP S/4HANA Cloud",
      "relation_type": "PART_OF",
      "context": "SAP Fiori is a component of SAP S/4HANA Cloud...",
      "document_id": "doc_sap_s4hana_overview.pptx",
      "chunk_id": "chunk_12",
      "annotator": "john.doe@company.com",
      "confidence_human": 1.0,
      "notes": "Clear compositional relationship",
      "created_at": "2025-10-19T14:30:00Z"
    }
    // ... 422 autres relations
  ]
}
```

---

## 📈 Utilisation pour Validation

### Calcul Precision/Recall

```python
# scripts/evaluate_relation_extraction.py

def evaluate_against_gold_standard(
    gold_standard_path: str,
    predictions_path: str
) -> Dict[str, float]:
    """
    Compare prédictions automatiques vs gold standard.

    Returns:
        {
            "precision": 0.82,
            "recall": 0.67,
            "f1_score": 0.74,
            "per_type_metrics": {...}
        }
    """
    from sklearn.metrics import precision_recall_fscore_support

    # Load gold standard
    gold = load_json(gold_standard_path)["relations"]

    # Load predictions (extraction automatique)
    predictions = load_json(predictions_path)

    # Alignment (même source, target)
    aligned_gold, aligned_pred = align_gold_with_predictions(gold, predictions)

    # Extract labels
    y_true = [g["relation_type"] for g in aligned_gold]
    y_pred = [p["relation_type"] for p in aligned_pred]

    # Calculate metrics
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, average="weighted"
    )

    # Per-type metrics
    per_type = {}
    for rel_type in RELATION_TYPES:
        type_gold = [1 if g == rel_type else 0 for g in y_true]
        type_pred = [1 if p == rel_type else 0 for p in y_pred]
        p, r, f, _ = precision_recall_fscore_support(type_gold, type_pred, average="binary")
        per_type[rel_type] = {"precision": p, "recall": r, "f1": f}

    return {
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "per_type_metrics": per_type
    }
```

**Exemple Utilisation:**

```bash
# 1. Créer gold standard (S14 J3)
python scripts/annotate_relations_gold_standard.py \
    --corpus data/phase2_test/ \
    --types PART_OF,SUBTYPE_OF,REQUIRES,USES,INTEGRATES_WITH,VERSION_OF,PRECEDES,REPLACES,DEPRECATES \
    --samples_per_type 50 \
    --annotators 2 \
    --output data/phase2_gold_standard.json

# 2. Extraire relations automatiquement (S15 J10)
python scripts/extract_relations_auto.py \
    --corpus data/phase2_test/ \
    --engine hybrid \
    --output data/phase2_predictions_S15.json

# 3. Évaluer performance
python scripts/evaluate_relation_extraction.py \
    --gold_standard data/phase2_gold_standard.json \
    --predictions data/phase2_predictions_S15.json \
    --output reports/phase2_evaluation_S15.json
```

**Output Attendu:**

```json
{
  "precision": 0.82,
  "recall": 0.67,
  "f1_score": 0.74,
  "per_type_metrics": {
    "PART_OF": {"precision": 0.88, "recall": 0.72, "f1": 0.79},
    "SUBTYPE_OF": {"precision": 0.75, "recall": 0.60, "f1": 0.67},
    "REQUIRES": {"precision": 0.85, "recall": 0.70, "f1": 0.77},
    "USES": {"precision": 0.78, "recall": 0.64, "f1": 0.70},
    // ... autres types
  },
  "evaluation_date": "2025-10-25T10:00:00Z"
}
```

---

## 🎯 Planning Intégration Semaine 14

### Jour 3 (Setup corpus)

1. **Sélectionner 100 documents multi-domaines**
   - 40 docs Software (SAP, Oracle, Salesforce...)
   - 20 docs Pharma (Clinical trials, Drug protocols...)
   - 20 docs Retail (E-commerce, Supply chain...)
   - 20 docs Other (Manufacturing, Finance, Legal)

2. **Extraire candidates relations**
   ```bash
   python scripts/annotate_relations_gold_standard.py \
       --corpus data/phase2_test/ \
       --extract_candidates_only \
       --output data/phase2_candidates.json
   ```
   → Output: ~500-1000 candidate relations

3. **Stratified sampling**
   ```bash
   python scripts/annotate_relations_gold_standard.py \
       --candidates data/phase2_candidates.json \
       --sample_stratified \
       --types PART_OF,SUBTYPE_OF,REQUIRES,USES,INTEGRATES_WITH,VERSION_OF,PRECEDES,REPLACES,DEPRECATES \
       --samples_per_type 50 \
       --output data/phase2_to_annotate.json
   ```
   → Output: 450 relations à annoter (50 × 9 types)

### Jour 3-5 (Annotation manuelle - en parallèle dev)

**Annotateur 1:**
```bash
python scripts/annotate_relations_cli.py \
    --input data/phase2_to_annotate.json \
    --annotator john.doe@company.com \
    --output data/phase2_annotations_john.json
```

**Annotateur 2:**
```bash
python scripts/annotate_relations_cli.py \
    --input data/phase2_to_annotate.json \
    --annotator jane.smith@company.com \
    --output data/phase2_annotations_jane.json
```

**Temps estimé:**
- 450 relations × 30 secondes/relation = 225 minutes = **~4 heures par annotateur**
- Total : 8 heures annotation (parallélisable avec dev J4-J7)

### Jour 7 (Inter-annotator agreement)

```bash
python scripts/calculate_inter_annotator_agreement.py \
    --annotations_a data/phase2_annotations_john.json \
    --annotations_b data/phase2_annotations_jane.json \
    --output data/phase2_agreement_stats.json
```

**Si Kappa ≥ 0.75:**
```bash
python scripts/merge_annotations.py \
    --annotations_a data/phase2_annotations_john.json \
    --annotations_b data/phase2_annotations_jane.json \
    --output data/phase2_gold_standard.json
```

**Si Kappa < 0.75:**
```bash
python scripts/resolve_conflicts.py \
    --annotations_a data/phase2_annotations_john.json \
    --annotations_b data/phase2_annotations_jane.json \
    --third_annotator tom.brown@company.com \
    --output data/phase2_gold_standard.json
```

---

## 📊 KPIs Gold Standard

| Métrique | Target | Critique |
|----------|--------|----------|
| **Total relations annotées** | 450 (50 × 9 types) | ✅ OUI |
| **Cohen's Kappa** | ≥ 0.75 | ✅ OUI |
| **Avg confidence humaine** | ≥ 0.85 | ⚠️ Nice-to-have |
| **Balance domaines** | 40/20/20/20 | ✅ OUI |
| **Balance types** | 50 ± 5 par type | ✅ OUI |

---

## 🔗 Ressources

### Documentation Externe
- [Cohen's Kappa - Scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.cohen_kappa_score.html)
- [Inter-rater Reliability - Wikipedia](https://en.wikipedia.org/wiki/Inter-rater_reliability)
- [Gold Standard Dataset Best Practices](https://aclanthology.org/L18-1239.pdf)

### Scripts Fournis (à créer)
- `scripts/annotate_relations_gold_standard.py` - Script principal
- `scripts/annotate_relations_cli.py` - Interface CLI annotation
- `scripts/annotate_relations_streamlit.py` - Interface web Streamlit
- `scripts/calculate_inter_annotator_agreement.py` - Calcul Kappa
- `scripts/evaluate_relation_extraction.py` - Validation performance

---

**Résumé:** Le Gold Standard est essentiel pour valider que ton RelationExtractionEngine atteint les KPIs (Precision ≥ 80%, Recall ≥ 65%). Sans ce dataset de référence, tu n'as aucune vérité terrain pour mesurer la performance réelle de ton système.
