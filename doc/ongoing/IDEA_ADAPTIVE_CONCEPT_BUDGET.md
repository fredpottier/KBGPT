# Idée : Budget Conceptuel Adaptatif

**Date:** 2026-01-27
**Statut:** À implémenter plus tard
**Source:** Analyse ChatGPT + discussion Claude

---

## Problème

- `MAX_CONCEPTS=30` est arbitraire et inadapté aux gros documents SAP (1500+ pages)
- "1 concept / X pages" est une fausse bonne idée (pagination ≠ densité conceptuelle)
- Besoin d'un budget lié à la **structure** et non au volume brut

---

## Proposition : Budget Adaptatif

### Signaux à utiliser (déjà disponibles)

- `#themes` (Pass 1.1)
- `#sections` (Docling)
- `#units` (Pass 0.5)
- `#quality_assertions` (PRESCRIPTIVE / value-bearing)

### Formule suggérée (ChatGPT)

```python
central = clamp(6, 10, round(sqrt(themes) * 3))
standard = clamp(12, 60, round(sqrt(sections) * 2))
contextual = clamp(6, 30, round(log1p(units) * 3))

max_concepts = clamp(25, 120, central + standard + contextual)
```

### Formule simplifiée (recommandée pour v1)

```python
MAX_CONCEPTS = clamp(25, 80, 15 + sqrt(sections) * 3)
```

---

## Garde-fous

1. **Hard cap sécurité** : 100-150 concepts max (éviter O(n²) au linking)
2. **Cap par thème** : `max(5, round(max_concepts / n_themes * 1.5))`
3. **Saturation (C4 + Pass 1.2b)** : Le vrai contrôle reste la saturation, pas le plafond

---

## Alternative : Concepts par Thème

Au lieu d'une liste plate, forcer le LLM à produire :
- Pour chaque thème : 2-5 concepts Central/Standard
- Plus 0-3 Contextual
- Budget total = somme

Avantage : structure stable
Risque : concepts artificiels pour "remplir"

---

## Implémentation (quand on y reviendra)

1. Modifier `concept_identifier.py` :
   - Remplacer `MAX_CONCEPTS=30` par `compute_budget(themes, sections, units)`
   - Ajouter `MAX_CONCEPTS_MIN=25`, `MAX_CONCEPTS_MAX=100`

2. Modifier `orchestrator.py` :
   - Passer les compteurs structurels à `ConceptIdentifierV2`
   - Autoriser `total_concepts` jusqu'à 100-120 si C1/C2 validés

3. Ajuster `schemas.py` :
   - `max_length` de concepts list = 150 (avec validation C1/C2)

---

## Ordres de grandeur typiques (à mesurer)

| Type Document | Sections | Themes | Units | Budget suggéré |
|---------------|----------|--------|-------|----------------|
| Guide simple | 20-50 | 5-7 | 500 | 30-40 |
| Admin guide SAP | 200-500 | 10-15 | 2000+ | 60-80 |
| Pavé 1500 pages | 500+ | 15-20 | 5000+ | 80-120 |

*À valider sur documents réels*

---

## Référence

- Discussion originale : session Claude 2026-01-27
- Contexte : après implémentation C3 v2 (soft gate + hard gate)
