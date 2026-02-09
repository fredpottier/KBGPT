# OSMOSE — Chantiers prochaines étapes

*Date : 2026-02-09*

## État actuel du KG (5 documents)

### Inventaire des nodes

| Label | Nombre | Par doc (moy.) | Projection 500 docs |
|-------|--------|----------------|---------------------|
| Claim | 10 959 | 2 192 | ~1 096 000 |
| Passage | 6 220 | 1 244 | ~622 000 |
| Entity | 4 417 | ~883* | ~200 000** |
| ClaimCluster | 1 151 | 230 | ~115 000 |
| DocumentContext | 5 | 1 | 500 |
| Autres (Facet, SubjectAnchor...) | 48 | ~10 | ~5 000 |
| **TOTAL NODES** | **22 800** | **4 560** | **~2 038 000** |

*\* Les entities sont partiellement partagées entre docs (111 cross-doc sur 4 417).*
*\*\* L'Entity count scale sub-linéairement grâce au partage cross-doc, estimé ~200K.*

### Inventaire des edges

| Type | Nombre | Description |
|------|--------|-------------|
| ABOUT | 13 827 | Claim → Entity |
| SUPPORTED_BY | 10 959 | Claim → Passage |
| IN_CLUSTER | 4 443 | Claim → ClaimCluster |
| CHAINS_TO | 1 882 | Claim → Claim (1 596 intra + 286 cross) |
| HAS_FACET | 1 435 | Claim → Facet |
| REFINES | 892 | Claim → Claim |
| QUALIFIES | 222 | Claim → Claim |
| Autres | 32 | ABOUT_SUBJECT, HAS_AXIS_VALUE, ABOUT_COMPARABLE |
| **TOTAL EDGES** | **33 692** | **Ratio edges/nodes = 1.48** |

### Claims par document

| Document | Claims | Passages | Ratio claims/passages |
|----------|--------|----------|-----------------------|
| Feature Scope 2023 (025) | 5 839 | 1 927 | 3.03 |
| Business Scope 2025 (023) | 2 291 | 1 972 | 1.16 |
| Business Scope 1809 (018) | 1 245 | 1 072 | 1.16 |
| Operations Guide 2021 (014) | 929 | 719 | 1.29 |
| RISE with SAP (020) | 655 | 530 | 1.24 |

**Observation critique :** Le Feature Scope 2023 génère à lui seul 5 839 claims (53% du total) pour un doc certes volumineux mais dont beaucoup de claims sont des listes de features unitaires. La densité de claims varie de 1:1 à 3:1 par passage.

---

## ⚠️ CHANTIER 0 — Rationalisation du graphe (PRIORITAIRE)

### Le problème

**22 800 nodes pour 5 documents.** Projection linéaire : **~2 millions de nodes pour 500 documents.** Même avec Neo4j Enterprise, cette densité pose des problèmes de :

1. **Performance des traversées** — Les requêtes cross-doc (CHAINS_TO) deviennent coûteuses quand chaque join_key touche des centaines de claims
2. **Coût d'extraction** — Chaque document passe par un LLM pour l'extraction, le coût scale linéairement avec le nombre de claims
3. **Bruit** — Beaucoup de claims unitaires ("Feature X NEW 1809") apportent peu de valeur sémantique mais gonflent le graphe
4. **Visualisation** — Le graphe devient illisible au-delà de ~50 000 nodes

### Axes de rationalisation à investiguer

#### A. Réduction des Claims à l'extraction

- **Claims à faible valeur informationnelle** : "Feature X NEW 1809", "Check Major Assembly Projects" — ces claims sans structured_form et sans contenu riche pourraient être filtrées plus agressivement
- **Granularité adaptative** : les documents de type "feature list" (scope) n'ont pas besoin d'une claim par bullet point — un clustering plus agressif réduirait le volume
- **Seuil de confiance** : ne persister que les claims au-dessus d'un seuil de confiance minimum

#### B. Compression des Passages

- **Ratio Passage/Claim** : 6 220 passages pour 10 959 claims — le passage est-il toujours nécessaire comme nœud séparé, ou pourrait-il être une propriété de la claim ?
- **Déduplication de passages** : des passages identiques ou quasi-identiques existent-ils entre documents ?

#### C. Entity Resolution plus agressive

- **4 417 entities pour 5 docs** — beaucoup sont des variantes du même concept ("SAP S/4HANA", "S/4HANA", "S4HANA", "SAP S/4HANA Cloud")
- Une résolution d'entités plus agressive (ER phase 2) réduirait le nombre d'entities et densifierait le graphe utilement
- Objectif : passer de ~883 entities/doc à ~200-300 après ER

#### D. ClaimClusters comme couche d'agrégation

- **1 151 clusters pour 10 959 claims** (~9.5 claims/cluster) — les clusters pourraient devenir le niveau de navigation principal
- Le KG pourrait opérer à deux niveaux : clusters pour la navigation, claims pour le détail
- Les CHAINS_TO cross-doc pourraient être dupliquées au niveau cluster (réduction 10x du nombre d'edges à traverser)

#### E. Archivage des claims low-value

- Claims sans structured_form ET sans CHAINS_TO → candidates à l'archivage (marquage `archived: true`, exclusion des traversées)
- Estimation : ~4 000 claims pourraient être archivées (les 46% sans SF dont beaucoup sont des titres de section ou des mentions triviales)

### Cibles de rationalisation

| Métrique | Actuel (5 docs) | Cible rationalisée (5 docs) | Projection 500 docs |
|----------|-----------------|----------------------------|---------------------|
| Claims | 10 959 | ~6 000-7 000 | ~400 000 |
| Passages | 6 220 | Fusionnés en propriétés | 0 (propriétés) |
| Entities | 4 417 | ~1 500-2 000 (post-ER) | ~50 000 |
| ClaimClusters | 1 151 | ~1 000 | ~100 000 |
| **TOTAL NODES** | **22 800** | **~9 000** | **~550 000** |
| **Réduction** | — | **~60%** | **~73% vs projection naive** |

---

## Chantier 1 — Couche d'exploitation hybride RAG + KG

### Objectif
Permettre à un utilisateur de poser une question en langage naturel et recevoir une réponse qui combine le RAG (réponse directe) et le KG (connaissance transversale).

### Approche envisagée
1. L'utilisateur pose une question
2. **Branche RAG** : recherche vectorielle Qdrant → top-k chunks
3. **Branche KG** : extraction d'entités de la question → résolution vers Entity nodes → traversée CHAINS_TO (2-3 hops) → claims atteintes
4. **Fusion** : les deux ensembles de contexte sont combinés et passés au LLM pour synthèse
5. **Réponse** : le LLM cite ses sources (chunks RAG + chaînes KG)

### Valeur
C'est ce qui transforme le PoC en produit. Sans ça, le KG reste un bel objet technique que seul un développeur Cypher peut interroger. Le jour où un utilisateur tape *"Predictive Accounting dependencies?"* et reçoit la chaîne 3-docs — là on a un produit.

### Prérequis
- Chantier 0 (rationalisation) pour garantir que les traversées restent rapides
- Un endpoint API qui orchestre les deux branches

### Preuve de concept existante
- Comparaison RAG vs KG documentée : `doc/ongoing/COMPARAISON_RAG_VS_KG_CROSS_DOC.md`
- RAG : 0/40 pertinents sur questions transversales
- KG : ~15/15 pertinents avec chaînes complètes

---

## Chantier 2 — Détection CONTRADICTS cross-doc

### Objectif
Détecter les contradictions entre documents — le cas le plus critique pour la fiabilité des réponses RFP.

### Exemples concrets attendus
- Doc 1809 : *"Feature X is available"* → Doc 2023 : *"Feature X has been deprecated"*
- Doc scope : *"Supports up to 10 000 users"* → Doc ops : *"Recommended for up to 5 000 users"*

### Approche envisagée
1. **Phase déterministe** : mêmes subject+object, prédicats contradictoires (USES/REPLACES, ENABLES/REQUIRES)
2. **Phase LLM** : pour les cas ambigus, passer les paires de claims au LLM avec prompt de détection de contradiction
3. **Relation CONTRADICTS** sur le graphe avec propriétés de traçabilité

### Prérequis
- Structured_form sur un maximum de claims (enrichir les 46% manquants)
- Chantier 0 pour réduire le nombre de paires à comparer

---

## Chantier 3 — Timeline / Evolution Tracker

### Objectif
Matérialiser la dimension temporelle du graphe — comment les features évoluent entre versions de documents.

### Données disponibles
Les 5 documents couvrent 4 millésimes : 1809 → 2021 → 2023 → 2025. Les CHAINS_TO cross-doc relient déjà des claims entre versions mais sans notion d'ordre temporel.

### Approche envisagée
1. **Attribut `doc_date` ou `doc_version`** sur les DocumentContext
2. **Relation SUPERSEDES** : quand une claim de doc récent affine/remplace une claim de doc ancien sur le même sujet
3. **Vue timeline** : pour une entity donnée, afficher l'évolution chronologique de ses claims

### Valeur
C'est la promesse originale OSMOSE ("CRR Evolution Tracker"). Pouvoir dire *"le Material Ledger était optionnel en 1809, intégré en 2023, et inclus dans PCE en 2025"* à partir du graphe.

---

## Chantier 4 — Enrichissement des structured_forms manquantes

### Objectif
Passer de 53.7% à 80%+ de claims avec structured_form.

### Situation actuelle
- 5 888 / 10 959 claims ont une SF (53.7%)
- Les 46% restantes sont des impasses dans le graphe (pas de CHAINS_TO, pas de join)
- Beaucoup sont des titres de section, des bullet points courts, ou des phrases complexes que le LLM n'a pas su structurer

### Approche envisagée
- Prompt V3 plus agressif pour l'extraction S/P/O
- Pass de ré-extraction ciblé uniquement sur les claims sans SF
- Ou : archivage des claims non-structurables (cf. Chantier 0)

---

## Chantier 5 — Ingestion de documents supplémentaires

### Objectif
Passer de 5 à 20+ documents pour augmenter la valeur cross-doc.

### Impact attendu
La valeur du cross-doc est **quadratique** : chaque nouveau document se connecte potentiellement à tous les existants. Avec 20 documents, on passerait de 10 paires de docs possibles à 190 paires.

### Prérequis
- Chantier 0 (rationalisation) IMPÉRATIF avant de scale — sinon explosion à 2M+ nodes
- Pipeline d'ingestion optimisé pour batch

---

## Chantier 6 — Détection REFINES cross-doc

### Objectif
Détecter quand une claim d'un document précise/détaille une claim d'un autre document.

### Exemple
- Doc A : *"S/4HANA supports asset management"*
- Doc B : *"S/4HANA supports asset management with predictive maintenance, IoT integration, and mobile work orders"*

La claim B **raffine** la claim A. Détecter ça permettrait de toujours présenter la version la plus détaillée.

### Note
Des REFINES intra-doc existent déjà (892 edges). L'extension au cross-doc suivrait le même pattern que CHAINS_TO cross-doc.

---

## Ordre de priorité recommandé

```
Chantier 0 — Rationalisation du graphe          ████████████ BLOQUANT
    ↓
Chantier 1 — Hybride RAG + KG                   ████████████ PRODUIT
    ↓
Chantier 5 — Plus de documents                   ████████░░░░ SCALE
    ↓
Chantier 2 — CONTRADICTS                         ███████░░░░░ VALEUR MÉTIER
Chantier 3 — Timeline                            ███████░░░░░ PROMESSE OSMOSE
    ↓
Chantier 4 — Enrichissement SF                   ██████░░░░░░ DENSIFICATION
Chantier 6 — REFINES cross-doc                   █████░░░░░░░ PRÉCISION
```

**Le Chantier 0 (rationalisation) est bloquant pour tout le reste.** Sans lui, chaque chantier suivant aggrave le problème de scale. Il doit être traité en premier.

---

## Références

- Comparaison RAG vs KG : `doc/ongoing/COMPARAISON_RAG_VS_KG_CROSS_DOC.md`
- Implémentation cross-doc : `src/knowbase/claimfirst/composition/chain_detector.py`
- Script cross-doc : `app/scripts/detect_cross_doc_chains.py`
- Tests : `tests/claimfirst/test_chain_detector_cross_doc.py` (32 tests)
