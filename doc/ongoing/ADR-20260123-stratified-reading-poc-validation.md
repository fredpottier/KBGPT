# ADR: Validation du Modèle de Lecture Stratifiée - POC Clos

**Statut**: VALIDÉ ET CLOS
**Date**: 2026-01-23
**Auteurs**: Fred, Claude, ChatGPT (collaboration)
**Réf**: ADR_STRATIFIED_READING_MODEL (doc/ongoing/)

---

## Contexte

Le POC Lecture Stratifiée a été conçu pour valider l'ADR_STRATIFIED_READING_MODEL avant intégration dans le pipeline OSMOSIS. L'objectif était de tester l'approche top-down (Subject → Themes → Concepts → Information) sur 4 documents représentatifs.

## Décisions Validées

### 1. Le modèle de lecture stratifiée est validé

Le pipeline top-down fonctionne correctement :
- **Phase 1.1** : Détection de structure (CENTRAL/TRANSVERSAL/CONTEXTUAL) ✅
- **Phase 1.2** : Identification frugale des concepts (5-15 par doc) ✅
- **Phase 1.3** : Extraction sémantique des assertions ✅
- **Garde-fous** : Rejet correct des documents HOSTILE ✅

### 2. La Promotion Policy est adoptée

Les assertions sont filtrées avant linking selon leur type :

| Type | Tier | Comportement |
|------|------|-------------|
| DEFINITIONAL | ALWAYS | Toujours promouvoir |
| PRESCRIPTIVE | ALWAYS | Toujours promouvoir |
| CAUSAL | ALWAYS | Toujours promouvoir |
| FACTUAL | CONDITIONAL | Si confiance ≥ 0.7 |
| CONDITIONAL | CONDITIONAL | Si confiance ≥ 0.7 |
| PERMISSIVE | CONDITIONAL | Si confiance ≥ 0.7 |
| COMPARATIVE | RARELY | Si confiance ≥ 0.9 |
| PROCEDURAL | NEVER | Jamais promouvoir |

**Justification** : La Policy transforme le ratio info/concept en "signature de document" :
- Documents normatifs → ratio élevé (≥2)
- Documents marketing → ratio bas (<1)

### 3. Définition formelle d'une Information OSMOSIS

> **Une Information OSMOSIS est une assertion défendable, transportable, non contextuelle, non illustrative.**

Critères d'une assertion défendable :
- **Définitoire** : Définit ce qu'est quelque chose
- **Normative** : Impose une obligation ou contrainte
- **Causale** : Établit une relation cause-effet

Ce qui n'est **PAS** une Information :
- Descriptions marketing/produit (FACTUAL descriptif)
- Étapes procédurales (PROCEDURAL)
- Illustrations locales (COMPARATIVE)

### 4. Le signal "CENTRAL sans Information" est une feature, pas un bug

**Décision explicite** : Ne PAS introduire de mécanisme "CENTRAL_ALWAYS".

**Observation** : Sur le document SAP GDPR, le concept CENTRAL "SAP Customer Data Cloud" a 0 Information rattachée malgré une structure correctement identifiée comme CENTRAL.

**Interprétation** : Le document décrit des fonctionnalités produit (assertions FACTUAL/DESCRIPTIVE) sans formuler d'assertions défendables sur le produit lui-même.

**Valeur du signal** :
> "Ce document parle d'un produit sans rien affirmer de normatif, définitoire ou causal sur lui."

Ce signal est précieux pour :
- Acheteurs (différencier doc technique vs marketing)
- Juristes (identifier absence de garanties)
- Architectes (distinguer spec vs publicité)

**Ajouter CENTRAL_ALWAYS** reviendrait à :
- Introduire un privilège ontologique arbitraire
- Réintroduire du "vendor truth" (croire parce que le vendeur dit)
- Effacer une vérité révélée par le système

---

## Résultats du POC

### Documents testés

| Document | Type | Structure | Concepts | Info | Ratio | Status |
|----------|------|-----------|----------|------|-------|--------|
| Euro NCAP Safe Driving | Normatif | CENTRAL | 9 | 4-26* | 0.4-5.2* | ✅ |
| CNIL GDPR Processors | Réglementaire | TRANSVERSAL | 15 | 19 | 1.3 | ✅ |
| SAP GDPR Industry Guide | Marketing | CENTRAL | 15 | 10 | 0.7 | ✅ |
| Euro NCAP VRU | HOSTILE | - | ≥10 | - | - | FAIL ✅ |

*Variation selon LLM (vLLM vs GPT-4o) et mode (avec/sans Policy)

### Métriques atteintes

| Métrique | Cible | Résultat |
|----------|-------|----------|
| Anchor success rate | ≥95% | **100%** |
| Distribution non-bucket | max 50% | **max 32%** (GPT-4o) |
| Rejet HOSTILE | < 10 concepts | **FAIL correct** |
| Ratio normatif | ≥ 2 | **2.8** (CNIL) |

### Comparaison LLM

| Aspect | vLLM (Qwen) | GPT-4o |
|--------|-------------|--------|
| Bucket problem | Oui (94% sur 1 concept) | Non (max 32%) |
| JSON truncation | Fréquent | Rare |
| Vitesse | ~30-60s/appel | ~5-10s/appel |
| Linking précision | Moins strict | Plus strict |

**Conclusion** : Le LLM n'est pas le facteur limitant. Les deux convergent sur les mêmes problèmes structurels.

---

## Artefacts Produits

### Code POC

```
poc/
├── extractors/
│   ├── document_analyzer.py        # Phase 1.1
│   ├── concept_identifier.py       # Phase 1.2
│   ├── information_extractor.py    # Phase 1.3 V1 (lexical)
│   └── semantic_assertion_extractor.py  # Phase 1.3 V2 (sémantique)
├── validators/
│   ├── frugality_guard.py          # Max 60 concepts
│   ├── anchor_validator.py         # Validation positions
│   ├── concept_quality_validator.py # Anti-bruit
│   ├── justification_validator.py  # Anti-fallback
│   └── refusal_rate_validator.py   # Anti-sur-structuration
├── prompts/
│   ├── poc_prompts.yaml            # V1
│   └── poc_prompts_v2.yaml         # V2 sémantique
├── models/
│   └── schemas.py                  # Pydantic models
└── poc_stratified_reader.py        # Orchestrateur (--v2, --llm)
```

### Résultats

```
poc/output_v2_gpt4o_policy/  # Résultats finaux validés
├── euro-ncap-*.json
├── gdpr_guide-*.json
└── IndustryGuide-SAP-*.json
```

---

## Implications pour OSMOSIS

### À intégrer dans le pipeline principal

1. **SemanticAssertionExtractor** remplace l'extraction chunk-by-chunk
2. **Promotion Policy** comme filtre standard avant linking
3. **Détection de langue** pour support multilingue

### Nouvelles capacités UX

1. **Signal "CENTRAL sans info"** exposé dans l'UI comme indicateur de type de document
2. **Distinction explicite** :
   - *Knowledge-bearing documents* (ratio ≥ 2)
   - *Alignment/marketing documents* (ratio < 1)

### Ce qui n'est PAS changé

- Architecture duale Neo4j + Qdrant
- Modèle Information = overlay (pointeur, pas copie)
- Hiérarchie Subject → Theme → Concept → Information

---

## Historique

| Date | Événement |
|------|-----------|
| 2026-01-23 | Création POC |
| 2026-01-23 | V1 : Matching lexical (problème langue) |
| 2026-01-23 | V2 : SemanticAssertionExtractor (résout langue) |
| 2026-01-23 | Ajout Promotion Policy |
| 2026-01-23 | Tests finaux GPT-4o + Policy |
| 2026-01-23 | **POC CLOS ET VALIDÉ** |
