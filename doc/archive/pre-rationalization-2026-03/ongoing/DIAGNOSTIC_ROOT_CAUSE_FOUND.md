# Diagnostic Final - Cause Racine Identifiée

**Date:** 26/01/2026
**Statut:** ✅ CAUSE IDENTIFIÉE

---

## Résumé Exécutif

Le faible taux d'anchor resolution (17.9%) est causé par un **mismatch de langue** entre les assertions Vision et les DocItems source.

---

## Données Clés

| Métrique | Valeur |
|----------|--------|
| InformationMVP total | 831 |
| PROMOTED_LINKED (concept OK) | 806 (97%) |
| Information (anchor OK) | 149 (17.9%) |

### Répartition par Langue

| Langue | InformationMVP | Information résolues | Taux Anchor |
|--------|----------------|---------------------|-------------|
| **Anglais** | 386 (48%) | **149** | **38.6%** |
| **Français** | 420 (52%) | **0** | **0%** |

---

## Cause Racine

### Le problème

1. **Document source** : ANGLAIS (RISE with SAP Cloud ERP Private)
2. **Vision génère** : Descriptions en FRANÇAIS (suivant la langue du prompt système)
3. **Anchor resolution** : Cherche le texte de l'assertion dans les DocItems
4. **Résultat** : Les assertions FR ne matchent JAMAIS les DocItems EN

### Exemple concret

**Assertion Vision (FR):**
> "Le visuel est une diapositive montrant les contrôles préventifs des services cloud de SAP."

**DocItem source (EN):**
> "SAP Cloud Services Preventive Controls for Cloud Accounts"

→ **Matching impossible** car langues différentes !

---

## Impact Quantifié

| Sans le bug langue | Actuel | Potentiel |
|--------------------|--------|-----------|
| Assertions à ancrer | 831 | 386 (EN seulement) |
| Anchor resolution | 149 | 149 |
| **Taux** | **17.9%** | **38.6%** |

Le taux réel sur les assertions anglaises est **38.6%** - bien meilleur !

---

## Solutions Proposées

### Option A: Forcer Vision à générer en anglais

**Modification:** Ajouter au prompt Vision:
```
IMPORTANT: Always generate descriptions in the same language as the source document.
If the document is in English, write your descriptions in English.
```

**Avantages:**
- Correction à la source
- Amélioration immédiate du taux d'anchor
- Cohérence linguistique du graphe

**Effort:** 1h (modification prompt)

---

### Option B: Filtrer les assertions Vision avant anchor

**Modification:** Détecter les assertions Vision (patterns FR) et les exclure de l'anchor resolution.

**Avantages:**
- Ne casse pas le pipeline existant
- Statistiques plus honnêtes

**Inconvénients:**
- Perte d'information Vision dans le graphe strict
- Les assertions Vision restent dans InformationMVP mais pas Information

**Effort:** 2h

---

### Option C: Créer un type d'anchor alternatif pour Vision

**Modification:** Ancrer les assertions Vision sur le chunk_id ou slide_number au lieu du texte.

**Avantages:**
- Préserve les informations Vision
- Ancrage au niveau page/slide

**Inconvénients:**
- Moins précis que l'ancrage texte
- Nécessite nouveau type d'anchor

**Effort:** 4h

---

## Recommandation

### Priorité 1: Option A (Forcer anglais dans prompt Vision)

C'est la correction la plus propre et la plus efficace :
- Résout le problème à la source
- Amélioration immédiate attendue : 17.9% → ~38%
- Cohérence linguistique du graphe

### Priorité 2: Améliorer le matching texte EN→EN

Même avec des assertions anglaises, le taux est 38.6% (pas 100%).
Investiguer pourquoi 61% des assertions anglaises échouent aussi.

Hypothèses :
- Texte reformulé par LLM (pas exact match)
- Assertions synthétisées (agrégation multi-paragraphes)
- Seuil fuzzy matching trop strict (0.85 actuellement)

---

## Prochaines Étapes

1. [ ] Modifier le prompt Vision pour forcer l'anglais
2. [ ] Re-run le pipeline
3. [ ] Vérifier amélioration du taux d'anchor
4. [ ] Si <50%, investiguer le matching EN→EN

---

## Tests de Validation Post-Fix

```bash
# Vérifier répartition linguistique après fix
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (mvp:InformationMVP)
WITH mvp.text as text,
     CASE WHEN text CONTAINS ' est ' OR text STARTS WITH 'Le ' THEN 'FR' ELSE 'EN' END as lang
RETURN lang, count(text)
"

# Vérifier nouveau taux d'anchor
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (mvp:InformationMVP) WITH count(mvp) as total
MATCH (i:Information) WITH total, count(i) as resolved
RETURN resolved, total, toFloat(resolved)/total * 100 as rate
"
```

---

*Diagnostic terminé le 26/01/2026*
