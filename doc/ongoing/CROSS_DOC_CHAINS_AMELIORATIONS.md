# Améliorations Futures — CHAINS_TO Cross-Doc

*Créé le 2026-02-11 après audit qualité et corrections V1*

## Contexte

L'audit du 2026-02-11 sur 22 documents / 37 748 claims a révélé 6 problèmes.
4 ont été corrigés immédiatement (voir section "Corrigé"). 2 restent ouverts.

---

## Corrigé (2026-02-11)

### 1. chain_type = NULL → 16 types sémantiques
- **Fichiers** : `chain_detector.py`, `detect_cross_doc_chains.py`
- **Solution** : `derive_chain_type(source_pred, target_pred)` classifie en dependency_chain, integration_chain, composition_chain, evolution_chain, capability_chain, transitive_*, generic_chain
- **Résultat** : 817 dependency, 356 integration, 269 composition, 116 evolution...

### 2. confidence = 1.0 fixe → IDF-based [0.1, 0.99]
- **Fichier** : `detect_cross_doc_chains.py` — `idf_to_confidence(idf)`
- **Formule** : `max(0.1, min(idf / 10.0, 0.99))`
- **Résultat** : distribution 0.73 → 0.91

### 3. 46 claims doublons texte identique
- **Fichier** : `chain_detector.py` — `detect_cross_doc()`
- **Solution** : skip si `src.text == tgt.text`
- **Résultat** : 70 paires éliminées, 0 doublons restants

### 4. 24 chaînes bruit (IDF < 4)
- **Fichier** : `chain_detector.py` — paramètre `min_idf=4.0`
- **Résultat** : 0 chaîne sous IDF 4.0 (hubs + plancher IDF)

### Nouveau paramètre CLI
```bash
python scripts/detect_cross_doc_chains.py --execute --purge-first --min-idf 4.0
```

### Impact global
- Avant : 2 301 chaînes cross-doc (dont bruit + doublons, sans typage)
- Après : 1 893 chaînes cross-doc (propres, typées, confidence calibrée)

---

## Non corrigé — Améliorations futures

### 5. Entités fantômes (orphelins de canonicalisation)

**Problème** : Certains `join_key` de type `entity_id` pointent vers des Entity nodes qui n'existent plus dans Neo4j (supprimés lors de la canonicalisation ou du re-import). Cela crée des références orphelines dans les propriétés des relations CHAINS_TO.

**Impact** : Faible. Les chaînes restent fonctionnelles (les claims existent), seul le `join_key` n'est plus résolvable vers un nom d'entity. Le raisonnement cross-doc n'est pas cassé.

**Solution proposée** :
- Option A : Au moment du `persist_cross_doc_chain`, vérifier que l'entity_id existe encore → fallback sur normalized_name sinon
- Option B : Script de nettoyage post-canonicalisation qui met à jour les CHAINS_TO dont le join_key pointe vers une entity supprimée
- Option C : Stocker `join_key_name` (normalized_name) EN PLUS de `join_key` (entity_id) pour que la résolution ne dépende pas de l'existence du node

**Recommandation** : Option C — ajouter `r.join_key_name = $join_key_name` dans `persist_cross_doc_chain`. Nécessite de passer le normalized_name à travers le ChainLink.

**Effort estimé** : Faible (1-2h)

---

### 6. Méthode de détection unique (spo_join déterministe)

**Problème** : Toutes les chaînes cross-doc utilisent la méthode `spo_join_cross_doc` (jointure déterministe objet→sujet via normalized_name ou entity_id). Il n'y a pas de :
- Similarité sémantique (embedding cosine entre claims)
- Co-référence LLM (validation que deux claims parlent du même sujet)
- Détection temporelle (version N → version N+1 d'un même document)
- Détection de contradiction (claim A contredit claim B cross-doc)

**Impact** : Moyen. Le spo_join couvre les cas les plus structurés et les plus fiables, mais rate les connexions sémantiques sans chevauchement SPO littéral. Exemple : "S/4HANA supporte la migration depuis ECC" et "La migration ECC nécessite un assessment préalable" — ces deux claims sont liés sémantiquement mais n'ont pas de jointure SPO directe si les termes ne sont pas identiques.

**Solutions proposées par priorité** :

#### 6a. Détection temporelle (version tracking)
- Pour des documents qui sont des versions successives du même guide (Operations Guide 2021 → 2022 → 2023), détecter automatiquement les chaînes d'évolution.
- Algorithme : identifier les paires de docs sur le même ComparableSubject, comparer les claims par fingerprint/embedding, créer des relations SUPERSEDES/EVOLVES.
- **Effort** : Moyen (1-2 semaines)
- **Valeur** : Élevée — c'est le cas d'usage "CRR Evolution Tracker" d'OSMOSE

#### 6b. Similarité sémantique cross-doc
- Utiliser les embeddings des claims (déjà calculés dans Qdrant) pour trouver des paires de claims cross-doc avec cosine > seuil.
- Filtrer par : même domaine, claims différents, docs différents.
- Avantage : capture les connexions que le SPO join rate.
- **Effort** : Moyen (1 semaine)
- **Valeur** : Moyenne — ajoute du rappel mais risque de bruit si le seuil est trop bas

#### 6c. Validation LLM des chaînes existantes
- Pour les chaînes détectées par spo_join, faire un post-processing LLM pour valider la pertinence et enrichir le chain_type.
- Permet de distinguer les vraies chaînes logiques des coïncidences de nommage.
- **Effort** : Faible (quelques jours) mais coût LLM récurrent
- **Valeur** : Moyenne — améliore la précision mais ajoute une dépendance LLM

#### 6d. Détection de contradictions cross-doc
- Identifier les claims qui se contredisent entre documents (ex: prérequis changé entre versions).
- Nécessite un LLM pour comparer les SPO sémantiquement.
- **Effort** : Élevé (2-3 semaines)
- **Valeur** : Très élevée pour l'USP OSMOSE

---

## Métriques de référence (2026-02-11)

```
Documents           : 22
Claims totales      : 37 748
Claims avec SF      : 17 139
Entity index        : 22 329
Hubs exclus         : 6
CHAINS_TO intra-doc : 2 969
CHAINS_TO cross-doc : 1 893
  - dependency_chain    : 817
  - integration_chain   : 356
  - composition_chain   : 269
  - transitive_uses     : 183
  - evolution_chain     : 116
  - transitive_requires :  82
  - autres              :  70
Confidence range    : 0.73 — 0.91
Doublons texte      : 0
Chaînes IDF < 4     : 0
Multi-hop 3+ docs   : ~695 (523 2-hop + 172 3-hop)
```

---

## Fichiers modifiés

| Fichier | Modifications |
|---------|--------------|
| `src/knowbase/claimfirst/composition/chain_detector.py` | Ajout `min_idf` param, filtre doublons texte, stats enrichis |
| `app/scripts/detect_cross_doc_chains.py` | `derive_chain_type()`, `idf_to_confidence()`, persist enrichi, `--min-idf` CLI |
| `scripts/detect_cross_doc_chains.py` | Miroir de app/scripts/ |
| `src/knowbase/claimfirst/persistence/claim_persister.py` | Batch UNWIND (non lié mais même session) |
