# Plan de Tests Diagnostiques - Anchor Resolution

**Date:** 26/01/2026
**Objectif:** Identifier la cause exacte du faible taux de linking (17.9%)
**Hypothèse ChatGPT:** "Les assertions sont plus spécifiques que les concepts disponibles"

---

## Contexte Actuel

| Métrique | Valeur |
|----------|--------|
| Assertions promues | 831 |
| Concepts disponibles | 10 |
| Anchor resolution | 17.9% (149/831) |
| ABSTAINED | 682 (82%) |
| Concept dominant | "Sécurité" (70 infos = 47%) |

---

## TEST 1: Audit Manuel des `no_concept_match`

### Objectif
Comprendre POURQUOI 682 assertions n'ont pas été liées.

### Protocole
1. Extraire 30 assertions ABSTAINED aléatoires
2. Pour chacune, classifier manuellement :
   - **A)** Concept évident existe → problème de matching
   - **B)** Concept existant trop large → besoin de sous-concepts
   - **C)** Concept manquant → besoin de nouveaux concepts
   - **D)** Assertion multi-concepts → problème de modèle
   - **E)** Assertion non-classifiable → bruit résiduel

### Requête Neo4j
```cypher
// Extraire 30 assertions ABSTAINED avec leur texte
MATCH (al:AssertionLog)
WHERE al.status = 'ABSTAINED'
WITH al, rand() as r
ORDER BY r
LIMIT 30
RETURN al.assertion_id as id, al.text as text
```

### Livrable
Tableau avec classification manuelle + patterns dominants.

---

## TEST 2: Top-2 Concepts Candidats (Diagnostic)

### Objectif
Savoir si le problème est :
- Manque de concepts (0 candidat)
- Rigidité du linking (2+ candidats mais aucun assez fort)

### Protocole
1. Modifier temporairement le linking pour logger les 2 meilleurs scores
2. Pour chaque assertion ABSTAINED, enregistrer :
   - `concept_1`, `score_1`
   - `concept_2`, `score_2`
   - `decision_margin` = score_1 - score_2

### Implémentation
Modifier `promotion_engine.py` ou `concept_linker.py` pour ajouter un mode diagnostic.

### Métriques attendues
- % d'assertions avec 0 candidat (concept manquant)
- % d'assertions avec score_1 < seuil (matching faible)
- % d'assertions avec margin < 0.1 (ambiguïté)

### Livrable
Distribution des scores et identification du pattern dominant.

---

## TEST 3: Scission du Concept "Sécurité"

### Objectif
Vérifier si la granularité des concepts impacte le taux de linking.

### Protocole
1. Analyser les 70 informations sous "Sécurité"
2. Identifier les sous-catégories naturelles :
   - Chiffrement (TLS, encryption)
   - Contrôle d'accès (authentication, authorization)
   - Firewall/Réseau (FWaaS, NSG, WAF)
   - Patch Management (SPM, updates)
   - Conformité (SOC2, GDPR, audit)
3. Rejouer Pass 1.2 avec ces sous-concepts

### Requête d'analyse
```cypher
// Analyser le vocabulaire des informations "Sécurité"
MATCH (c:Concept {name: 'Sécurité'})-[:HAS_INFORMATION]->(i:Information)
RETURN i.text as text, i.type as type
ORDER BY i.type
```

### Livrable
Proposition de sous-concepts + estimation de gain de linking.

---

## TEST 4: Détection des Assertions Multi-Pivots

### Objectif
Quantifier les assertions qui relèvent de plusieurs concepts.

### Protocole
1. Pour chaque assertion promue, calculer le nombre de concepts pertinents
2. Flagger `MULTI_CONCEPT_CANDIDATE` si ≥ 2 concepts avec score > 0.5

### Exemple type
> "All HTTP connections must be secured using TLS 1.2 or higher."

Concepts potentiels :
- Sécurité (chiffrement)
- Infrastructure Client (configuration réseau)
- Services Cloud (protocole)

### Livrable
% d'assertions multi-concepts + recommandation modèle.

---

## Ordre d'Exécution Recommandé

| # | Test | Effort | Impact Diagnostic |
|---|------|--------|-------------------|
| 1 | Audit manuel 30 ABSTAINED | 30 min | ⭐⭐⭐⭐⭐ |
| 2 | Log top-2 candidates | 1-2h code | ⭐⭐⭐⭐ |
| 3 | Scission "Sécurité" | 2-3h | ⭐⭐⭐ |
| 4 | Flag multi-concepts | 1h | ⭐⭐ |

---

## Scripts de Test Prêts à Exécuter

### Script TEST 1: Extraction échantillon ABSTAINED
```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (mvp:InformationMVP)
WHERE mvp.promotion_status = 'PROMOTED_LINKED'
WITH collect(mvp.text) as linked_texts
MATCH (mvp2:InformationMVP)
WHERE mvp2.promotion_status = 'PROMOTED_UNLINKED'
WITH linked_texts, collect(mvp2.text) as unlinked_texts
RETURN size(linked_texts) as linked, size(unlinked_texts) as unlinked
"
```

### Script TEST 1b: Échantillon assertions non-liées
```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (mvp:InformationMVP)
WHERE mvp.promotion_status = 'PROMOTED_UNLINKED'
RETURN mvp.text as text
LIMIT 30
"
```

### Script TEST 3: Analyse vocabulaire "Sécurité"
```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (c:Concept {name: 'Sécurité'})-[:HAS_INFORMATION]->(i:Information)
RETURN i.type as type, i.text as text
ORDER BY i.type, i.text
"
```

---

## Hypothèses à Valider/Invalider

| Hypothèse | Test | Résultat attendu si vrai |
|-----------|------|--------------------------|
| H1: Concepts trop larges | TEST 1 | Majorité de classifications "B" |
| H2: Concepts manquants | TEST 1 | Majorité de classifications "C" |
| H3: Matching trop strict | TEST 2 | Beaucoup de score_1 proche du seuil |
| H4: Ambiguïté multi-concepts | TEST 2, 4 | Margin faible + flag fréquent |
| H5: Bruit résiduel | TEST 1 | Majorité de classifications "E" |

---

## Décision Post-Tests

| Si Pattern Dominant | Action Recommandée |
|---------------------|-------------------|
| Concepts trop larges (B) | Scission automatique des concepts > 25 infos |
| Concepts manquants (C) | Enrichir Pass 1.2 avec extraction plus fine |
| Matching trop strict | Baisser seuil de linking de 0.7 → 0.5 |
| Multi-concepts fréquent | Implémenter multi-linking (1 assertion → N concepts) |
| Bruit résiduel | Renforcer les filtres amont |

---

*Plan créé le 26/01/2026 - À exécuter dans l'ordre*
