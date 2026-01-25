# POC Lecture Stratifiée OSMOSIS v2

Validation technique de l'ADR_STRATIFIED_READING_MODEL.

## Objectif

Valider la faisabilité technique de l'approche **top-down** de lecture stratifiée :
- Subject → Themes → Concepts → Information
- Avec **frugalité stricte** (max 60 concepts)
- Information comme **overlay** (pointeurs, pas copies)

## Structure

```
poc/
├── models/
│   └── schemas.py          # Modèles Pydantic (DocumentStructure, ConceptSitué, etc.)
├── extractors/
│   ├── document_analyzer.py    # Phase 1.1 - Analyse structurelle
│   ├── concept_identifier.py   # Phase 1.2 - Identification concepts
│   └── information_extractor.py # Phase 1.3 - Extraction Information
├── validators/
│   ├── frugality_guard.py      # Coupe-circuit dur (>60 concepts = FAIL)
│   └── anchor_validator.py     # Validation des anchors
├── utils/
│   ├── text_extractor.py       # Phase 0 - Extraction texte PDF
│   └── chunker.py              # Découpage en chunks
├── prompts/
│   └── poc_prompts.yaml        # Prompts pour Qwen 14B
├── tests/
│   ├── test_models.py          # Tests unitaires modèles
│   └── test_validators.py      # Tests unitaires validateurs
├── output/                     # Résultats JSON
└── poc_stratified_reader.py    # Orchestrateur principal
```

## Documents de Test

| Type | Document | Concepts attendus |
|------|----------|-------------------|
| CENTRAL | SAP GDPR Industry Guide | 15-40 |
| TRANSVERSAL | CNIL Guide GDPR Sous-traitants | 20-50 |
| CONTEXTUAL | Euro NCAP Safe Driving | 10-35 |
| HOSTILE | Euro NCAP VRU Protocol | <10 (succès si peu) |

## Usage

```bash
# Traiter un document
python -m poc.poc_stratified_reader --doc /path/to/document.pdf --type CENTRAL

# Traiter un lot de documents
python -m poc.poc_stratified_reader --batch /path/to/folder/

# Mode test (sans LLM)
python -m poc.poc_stratified_reader --doc /path/to/document.pdf --test

# Lancer les tests
pytest poc/tests/ -v
```

## Critères de Succès

| Critère | Seuil OK | Seuil Fail |
|---------|----------|------------|
| Frugalité | 5-60 concepts | >60 = FAIL dur |
| Anchor Success Rate | ≥95% | <80% |
| Info/Concept moyenne | ≥3 | <2 |
| Document HOSTILE | <10 concepts | ≥10 = échec test |

## Coupe-circuits

1. **Frugalité** : >60 concepts → FAIL immédiat, pas de post-filtrage
2. **Document hostile** : Si type=HOSTILE et concepts≥10 → test échoué
3. **Anchors** : <80% de succès → WARNING critique

## Dépendances

- PyMuPDF (fitz) : extraction PDF
- pydantic : validation modèles
- pyyaml : lecture prompts
- pytest : tests

## Isolation

Ce POC est **isolé** du code OSMOSIS principal :
- Pas de dépendance vers `src/knowbase/`
- Propres modèles Pydantic
- Propre extraction (pas de réutilisation des pipelines)

L'infrastructure peut être réutilisée (LLMRouter, clients) mais pas la logique d'extraction.
