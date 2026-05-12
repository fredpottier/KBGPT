# Cadrage panel stress-test 100q multi-domaines (Facts-First v1)

> **Status** : Figé 2026-05-06 (CH-41.M, livrable 4)
> **Décision source** : `ADR_V4_FACTS_FIRST.md` D-FF12
> **Validation HFF5** : couverture types ≥ 95% sur ce panel
> **Construction effective** : à livrer en CH-41.0 (pré-requis Tranche 1)

## 1. Objectif unique du panel

Ce panel sert **EXCLUSIVEMENT** à valider l'hypothèse HFF5 :

> **HFF5** : ≥ 95% du trafic doit tomber dans un type primaire avec confidence QuestionAnalyzer ≥ 0.5, sur un échantillon multi-domaines représentatif de l'usage potentiel d'OSMOSIS.

C'est-à-dire : **valider la couverture typologique** des 6 types primaires (factual, list, temporal, comparison, causal, unanswerable/false_premise).

### 1.1 Ce que le panel mesure

- **Coverage rate** : % de questions classifiées avec confidence ≥ 0.5
- **Type distribution** : combien de questions tombent dans chaque type
- **Multi-label rate** : combien de questions sont en top-2 (confidence 0.5-0.7)
- **EAV fallback rate** : combien tombent en EAV (confidence < 0.5)

### 1.2 Ce que le panel NE mesure PAS

- **PAS** la qualité de la réponse (factual_correctness, item_recall, etc.) — ça reste sur le gold-set v4 enrichi par tranche
- **PAS** la latence end-to-end — mesurée séparément en CH-41.4
- **PAS** la précision du Structurer — chaque tranche a son gold-set d'atomes annoté

**Garde-fou D-FF12** : ne PAS ouvrir un chantier parallèle « bench multi-domaines » à partir de ce panel. Il sert juste à valider HFF5, point.

## 2. Construction du panel

### 2.1 Structure cible

```
panel_stress_test_100q.json
├── 5 domaines × 20 questions = 100 questions
├── Stratification par type primaire visé attendu
└── Annotation type primaire attendu par construction
```

### 2.2 Domaines couverts

| Domaine | 20q | Justification |
|---------|----|---------------|
| **Médical** | 20 | Posologie, contre-indications, interactions, protocoles, validation clinique. Domain very common. |
| **Juridique** | 20 | Articles de loi, jurisprudence, clauses contractuelles, applicabilité juridictionnelle. |
| **Software docs** | 20 | API specs, configuration, troubleshooting, versioning, dépendances. Domain procedural-heavy. |
| **RH / politique d'entreprise** | 20 | Procédures internes, droits employés, processus onboarding, politiques diversité. |
| **Produit / e-commerce** | 20 | Specs techniques, comparaisons produits, disponibilité, garanties. |

### 2.3 Stratification par type attendu

Pour chaque domaine, viser une distribution proche de :

| Type primaire | Questions par domaine |
|---------------|-----------------------|
| factual | 5 |
| list | 4 |
| temporal | 3 |
| comparison | 3 |
| causal | 3 |
| unanswerable / false_premise | 2 |

**Total** par domaine = 20. **Total** panel = 100.

Cette stratification reflète une distribution naturelle attendue (factual le plus fréquent, unanswerable le moins fréquent).

### 2.4 Inclusion explicite de cas limites

Sur les 100 questions, **réserver explicitement** :

- **10 questions multi-label naturelles** (ex « Quels articles ont changé entre v1 et v2 ? » = list + temporal). Réparties sur les 5 domaines.
- **5 questions méta** (ex « Comment ce système gère-t-il les contradictions ? »). Hors-typologie attendue → test du fallback EAV.
- **5 questions très ambiguës** (formulations floues, intentions multiples). Stress test du seuil 0.5.

Ces 20 cas limites valident que :
- Multi-label top-2 fonctionne (confidence 0.5-0.7)
- EAV fallback se déclenche correctement (confidence < 0.5)
- Le router ne sur-classifie pas (pas de false high confidence)

## 3. Format de sortie

### 3.1 Structure JSON par item

```json
{
  "id": "STRESS_v1_001",
  "domain": "medical",
  "question": "Quelles sont les contre-indications de la warfarine ?",
  "language": "fr",
  "expected_primary_type": "list",
  "expected_secondary_type": null,
  "expected_difficulty": "normal",
  "expected_to_trigger_eav": false,
  "annotation_meta": {
    "annotator": "fred + claude_review",
    "annotated_at": "2026-05-08",
    "construction_method": "manual + LLM-bootstrap"
  }
}
```

### 3.2 Distribution check du panel

Au moment de la livraison, valider :
```python
assert len(panel) == 100
assert {q["domain"] for q in panel} == {"medical", "legal", "software", "hr", "product"}
for domain in ["medical", "legal", "software", "hr", "product"]:
    domain_qs = [q for q in panel if q["domain"] == domain]
    assert len(domain_qs) == 20
    assert sum(1 for q in domain_qs if q["expected_primary_type"] == "factual") == 5
    # ... etc
assert sum(1 for q in panel if q["expected_to_trigger_eav"]) >= 5
```

## 4. Mesure HFF5

### 4.1 Procédure

1. Lancer QuestionAnalyzer sur les 100 questions du panel
2. Pour chaque question, capturer `(predicted_primary_type, predicted_confidence, secondary_type, secondary_confidence)`
3. Calculer :
   - `coverage_rate` = #questions avec confidence ≥ 0.5 / 100
   - `type_match_rate` = #questions où predicted_primary_type == expected_primary_type / 100
   - `multi_label_rate` = #questions avec 0.5 ≤ confidence < 0.7 / 100
   - `eav_rate` = #questions avec confidence < 0.5 / 100

### 4.2 Critères de validation HFF5

| Métrique | Seuil | Action si non-atteint |
|----------|-------|------------------------|
| `coverage_rate` ≥ 95% | OUI | Bloquant — revoir typologie ou QuestionAnalyzer |
| `eav_rate` ≤ 10% | OUI | Bloquant — typologie insuffisante |
| `type_match_rate` ≥ 80% | OUI | Bloquant — QuestionAnalyzer mal calibré |
| `multi_label_rate` cohérent avec questions multi-label attendues | OUI | Si > 50% → router trop hésitant |

### 4.3 Distribution attendue par type

Les 100 questions sont stratifiées (cf §2.3). Validation cohérence :
```
factual : ~25 questions (5 par domaine × 5 domaines)
list : ~20 questions
temporal : ~15 questions
comparison : ~15 questions
causal : ~15 questions
unanswerable / false_premise : ~10 questions
```

Si predicted distribution diverge fortement de cette stratification → soit le router se trompe, soit la stratification est mal calibrée vs réalité du domaine.

## 5. Process de construction

### Étape 1 : Génération auto bootstrap (jour 1)
- Pour chaque domaine, prompt LLM (Qwen-72B DeepInfra ou Claude) avec :
  ```
  Generate 25 candidate questions in domain "<domain>" stratified as :
  - 6 factual (single fact lookup)
  - 5 list (enumeration)
  - 4 temporal (versioning, dates)
  - 4 comparison (≥2 sources/positions)
  - 4 causal (why questions)
  - 2 unanswerable or false premise
  Mix FR (60%) and EN (40%). Output JSON.
  ```
- Récolter ~125 questions candidates (5 × 25), garder 100 après revue

### Étape 2 : Review humain ciblé (jour 1-2)
- Fred review chaque question : conserve / reformule / rejette
- Annotate `expected_primary_type` + cas limites
- Cible 100 questions validées

### Étape 3 : Validation cohérence (jour 2)
- Run check distribution §3.2
- Run QuestionAnalyzer dummy (sans pipeline complet, juste classification) si disponible — sinon différer en CH-41.1

### Étape 4 : Persistance
- Output `benchmark/questions/panel_stress_test_100q.json`
- Doc `doc/ongoing/STRESS_TEST_PANEL_REPORT.md` (à créer post-mesure HFF5)

## 6. Charte de neutralité

### 6.1 Pas de bias OSMOSIS
Le panel doit être construit **sans biais** vers la typologie OSMOSIS actuelle. Si une question naturelle ne rentre dans aucun type, elle reste dans le panel — c'est précisément le test.

### 6.2 Pas de cherry-picking
Une fois le panel construit, **ne PAS** retirer des questions parce qu'elles cassent les métriques. Si HFF5 échoue, c'est un signal architectural, pas un problème de panel.

### 6.3 Re-construction périodique
Le panel est figé pour la mesure HFF5 initiale (Sprint S0.5 ou début Tranche 1). À reconstruire tous les 6 mois pour suivre l'évolution des usages réels (post-déploiement Armand notamment).

## 7. Référentiels

- ADR : `doc/ongoing/ADR_V4_FACTS_FIRST.md` D-FF12 + HFF5
- Tâche : `CH-41.0 — Pré-requis V4 Facts-First (gold-sets + panel stress-test)` (livrable 3)
- Output prévu : `benchmark/questions/panel_stress_test_100q.json` + `doc/ongoing/STRESS_TEST_PANEL_REPORT.md`
- Validation : par mesure post-CH-41.1 (QuestionAnalyzer livré)
