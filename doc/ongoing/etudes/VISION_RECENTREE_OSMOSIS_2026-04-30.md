# Vision recentrée OSMOSIS — Anchor-driven retrieval

*Date : 30 avril 2026*
*Statut : ✅ **VALIDÉE** le 30/04/2026 — référentiel maître officiel pour le chantier OSMOSIS V2*
*Genèse : retour stratégique Fred 30/04/2026 + cross-review ChatGPT (3 itérations) + amendements de cohérence (séparation KG/runtime, lecture stricte LIFECYCLE, gradation confidence Current Resolver)*

> Ce document remplace la lecture "7 modes auto-classifiés + 3 régimes RAG_LED/KG_LED/HYBRID" portée par RUNTIME_EXPLOITATION_ARCHITECTURE.md V1.1. Les ADR existantes (V3.3, Runtime V1.1, Lifecycle, KG_INJECTION_V3, etc.) ne sont pas jetées — elles sont **relues à travers ce filtre**, certaines conservées telles quelles, d'autres mises en réserve.

---

## 1. Mission primaire (reformulée)

> **OSMOSIS doit apporter la vérité telle que décrite dans les documents ingérés, malgré le caractère intrinsèquement non-homogène d'une documentation rédigée par l'humain. Quand le user pose une question, il ne veut pas savoir tout le cycle de vie de l'information — il veut UNE réponse, dans le cadre que sa question délimite (implicitement ou explicitement).**

Conséquences directes :

- **Le user ne veut pas être pollué** par les évolutions naturelles (« la réponse est X mais c'était Y avant »). C'est du bruit dans 90% des usages.
- **Le user veut être alerté** quand deux sources contemporaines se contredisent réellement (vraie incohérence du corpus). C'est le seul cas où une "tension" doit remonter spontanément.
- **Le user peut explicitement demander** l'historique d'une information (« comment X a-t-il évolué », « depuis quand Y est utilisé »). Dans ce cas, l'évolution n'est plus du bruit, c'est la réponse.

---

## 1bis. Séparation des responsabilités KG / runtime (invariant fondateur)

> **Le KG ne décide pas la vérité. Il représente fidèlement ce que disent les documents. Toute hiérarchisation, composition ou émergence d'évolution est une opération runtime, pas une donnée persistée.**

Cette séparation est l'invariant le plus important du système. Elle conditionne ce qui peut entrer dans le KG et ce qui ne peut pas.

### Ce que le KG porte (statique, persisté)

| Niveau | Contenu |
|---|---|
| **Faits documentés** | « Doc A dit X », « Doc B dit Y » — claims extraits dans leur cadre d'applicabilité |
| **Cadre d'applicabilité** | ApplicabilityFrame V2 (3 axes) + TemporalFrame, dérivés du contenu du doc lui-même |
| **Relations sémantiques cross-doc** | 9 Logical Claim→Claim (CONFLICT, EXCEPTION, SUBSET, EQUIVALENT, etc.) — calculées par le 12-class classifier sur paires intra-périmètre |
| **Successions explicitement déclarées** | LIFECYCLE_RELATION Doc→Doc **uniquement** quand le texte d'un doc déclare qu'il abroge/évolue/réaffirme un autre doc (preuve textuelle obligatoire) |

### Ce que le KG ne porte PAS (interdit)

- Inférences de succession non textuellement déclarées (ex: « Doc B est plus récent + même sujet → on persiste SUPERSEDES »)
- Notions de "vérité courante" ou de "doc autoritaire" (ce sont des compositions runtime)
- Hiérarchisation entre claims contradictoires (le KG dit qu'ils s'opposent, pas lequel a raison)
- Inférences temporelles type "current = max(publication_date)" — c'est runtime, jamais persisté

### Ce que le runtime calcule (dynamique, jamais persisté dans le KG)

| Opération | Fait à la volée par |
|---|---|
| Résolution de l'anchor de la question | Anchor Extractor (LLM sémantique) |
| Filtrage des claims par cadre | Anchor Filter (Cypher + Qdrant) |
| Détermination du doc autoritaire pour `current_default` | Current Resolver (composition de faits + heuristiques runtime) |
| Émergence d'évolutions cross-anchor | LLM de synthèse à partir de N sous-réponses |
| Hiérarchisation par autorité de source | Trust score + composition runtime |

### Précision importante — inférence runtime vs persistence d'inférence

**Le runtime A LE DROIT (et le devoir) d'inférer**. Sans cela, le système deviendrait inutilisable : un user qui pose une question implicite « current » sur un sujet avec CS-25 Amdt 27 et Amdt 28 sans déclaration textuelle explicite attend légitimement que le système comprenne que 28 > 27.

Ce qui est interdit n'est pas l'inférence, c'est la **fossilisation d'une inférence dans le KG** :

| Inférence | Autorisée au runtime ? | Persistée dans le KG ? |
|---|---|---|
| « Doc C (2024) est plus récent que Doc B (2022) » | ✅ Oui — tri par publication_date | ❌ Non — pas de LIFECYCLE_RELATION écrite |
| « Doc C est central dans le graphe ABOUT pour ce sujet » | ✅ Oui — score KG calculé à la volée | ❌ Non |
| « Amdt 28 > Amdt 27 par convention de versioning » | ✅ Oui — extraction sémantique du numéro de version | ❌ Non |
| « Doc B contient une clause `repeals Doc A` » | ✅ Détectable au runtime | ✅ **Oui** — c'est un fait documenté, persistance légitime |

**Règle** : le runtime peut composer toutes les heuristiques sûres pour répondre. Il transmet ses conclusions au user dans la **réponse** (transitoire), jamais dans le **KG** (durable).

---

## 2. L'USP réelle d'OSMOSIS — deux forces uniques

Au-delà des capacités RAG classiques, OSMOSIS a **deux forces que le RAG seul ne sait pas reproduire** :

### Force 1 — Détection des contradictions intra-périmètre (pré-calculée)

Quand deux ou plusieurs documents affirment des claims **différents sur le même sujet, dans le même cadre d'applicabilité** (même version / date / scope), c'est un signal de qualité du corpus. Le RAG ne le détecte pas car il ne croise pas systématiquement les sources.

OSMOSIS le détecte à l'ingestion via le 12-class classifier (réduit à 9 types Claim→Claim) et persiste les relations CONFLICT/EXCEPTION/SUBSET/etc. Le runtime exploite ces relations pré-calculées sans les recalculer.

**Important** : ces relations sont **descriptives** (« deux sources s'opposent ») et non **prescriptives** (« telle source a raison »). Le runtime les remonte au user, qui tranche.

### Force 2 — Construction d'un graphe cross-doc riche

Les relations sémantiques entre claims, entités canoniques et clusters permettent au runtime des inférences transitives :
- Doc_A dit « X est lié à Y »
- Doc_B dit « Y est lié à Z »
- Question : « X est-il lié à Z ? » → réponse via composition KG, qu'un RAG ne ferait pas naturellement.

Cette force repose sur l'investissement KG existant (40K claims, CanonicalEntity 2 320, ClaimCluster 9 622, Facet 68, ABOUT 168K) et n'est pas affectée par le recentrage.

### Tout le reste est ingénierie du runtime

Anchor extraction, current resolution, émergence d'évolutions par décomposition de question — ce sont des compositions runtime sur ces deux fondations. Utiles mais non-USP au sens strict.

---

## 3. Le pivot conceptuel : tout se règle sur l'anchor

Une question porte toujours, implicitement ou explicitement, sur un **cadre temporel/scope** qu'on appelle **anchor**. L'anchor est :

- **Implicite "current"** par défaut : *« Quel est le mode de chiffrement au repos de S/4HANA Cloud Private Edition ? »* → l'utilisateur veut la réponse pour la version actuellement supportée, sans avoir à le préciser.
- **Explicite ponctuel** : *« Quelles sont les API disponibles pour BusinessPartner dans S/4HANA 1809 ? »* → l'anchor est `1809`.
- **Explicite range** : *« Comment le chiffrement en transit a-t-il évolué entre la dernière version et la précédente ? »* → l'anchor est un range de versions.

### La règle d'or

```
Vérité       = filtrer les claims par anchor → réponse intra-anchor
Évolution    = comparer entre anchors        → timeline inter-anchors
Contradiction = opposition intra-anchor      → vraie incohérence à signaler
```

### Pourquoi c'est puissant

Le filtrage par anchor **élimine mécaniquement** 90% des "contradictions" qui sont en fait des évolutions normales (« Doc A dit TLS 1.2 pour S/4HANA 2022, Doc B dit TLS 1.3 pour S/4HANA 2024 »). Ce qui reste après filtrage est par construction :

- Soit une réponse unique → cas commun, pas de bruit
- Soit plusieurs sources contemporaines qui s'opposent → vraie contradiction, à signaler

On résout un problème difficile (distinguer évolution de contradiction) en un problème trivial (filtrer puis détecter résiduel).

---

## 4. Pipeline runtime — 6 étapes ordonnées

```
┌─────────────────────────────────────────────────────────────────┐
│                      QUESTION UTILISATEUR                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. SUBJECT RESOLVER  [✓ existe : SubjectResolverV2]            │
│    Identifie le sujet (S/4HANA Cloud Private Edition / 2021/821)│
│    Si ambigu → demande disambiguation au user                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. ANCHOR EXTRACTOR  [✗ à créer]                               │
│    LLM sémantique pur (pas de regex) — evidence-locked         │
│    Output: {anchor_type: point|range|current_default,          │
│             scope: {version, date, range_start, range_end}}    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. ANCHOR FILTER  [✗ à créer]                                  │
│    Filtre les claims par ApplicabilityFrame V2 + TemporalFrame │
│    Cypher + Qdrant : on ne garde que les claims dont le cadre │
│    matche l'anchor extrait                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. CURRENT RESOLVER  [✗ à créer]                               │
│    Si anchor = current_default :                               │
│      remonte la chaîne LIFECYCLE_RELATION (SUPERSEDES)         │
│      filtre par validity_start ≤ today < validity_end          │
│      tri par publication_date desc                             │
│    Le doc en tête est l'autoritaire pour ce sujet              │
│    Déterministe (pas de LLM)                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────┬──────────────────────────────────────────┐
│ 5a. SI POINT/CURRENT │ 5b. SI RANGE                            │
│ ▼                    │ ▼                                        │
│ Conflict Detector    │ Evolution Builder                        │
│ intra-anchor         │ (timeline cross-anchors)                 │
│ [partiellement existe│ [partiellement existe : SNAPSHOT/DIFF]  │
│  : 9 Logical Claim→  │                                          │
│  Claim CONFLICT]     │                                          │
└──────────────────────┴──────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              SYNTHÈSE LLM + RÉPONSE STRUCTURÉE                 │
│              Trust score + drill-down disponible                │
└─────────────────────────────────────────────────────────────────┘
```

### Posture face à l'ambiguïté (invariant runtime gradué)

Le runtime applique des heuristiques sûres pour ranker les candidats (recency, version ordering, KG centrality, trust score) et décide en fonction du **niveau de confiance** :

- **Confiance haute (top ≥ 0.85)** : auto-pick le top candidate, mentionne discrètement la source dans la réponse
- **Confiance modérée (0.55–0.85)** : propose le top + signale les alternatives, invite à préciser
- **Confiance basse (< 0.55)** : remonte au user explicitement pour disambiguation

Les seuils par défaut (0.85 / 0.55) sont configurables par persona ou globalement. L'invariant inviolé n'est pas « ne jamais inférer », c'est « ne jamais persister une inférence dans le KG ». Le runtime peut ranker, hiérarchiser, choisir — il transmet ses conclusions au user via la **réponse**, jamais via une écriture KG.

Cas où la remontée au user reste systématique :

- **Subject Resolver retourne plusieurs sujets candidats à confiance comparable** → disambiguation explicite (« Précisez : S/4HANA Cloud Private Edition / OnPrem / Public Cloud ? »). Pas d'auto-pick sur le sujet (impact trop fort sur toute la suite du pipeline).
- **Anchor Filter retourne 0 claim** → remontée explicite (« Aucune information dans le corpus pour ce cadre, voulez-vous élargir ? »). Pas de fallback automatique élargissant le scope.

Cette posture graduée garantit l'utilisabilité du système pour les cas évidents (recency franche, version ordering clair) tout en préservant l'honnêteté pour les cas réellement ambigus.

### Détail des 3 composants à créer

#### 4.1 — Anchor Extractor

**Rôle** : extraire le cadre temporel/scope porté par la question.

**Entrée** : question utilisateur + sujet résolu (étape 1)

**Sortie** :
```json
{
  "anchor_type": "point" | "range" | "current_default",
  "scope": {
    "version": "1809" | null,
    "date": "2024-01-15" | null,
    "range_start": "..." | null,
    "range_end": "..." | null,
    "extraction_evidence": "fragment de la question qui porte l'anchor"
  },
  "confidence": 0.92
}
```

**Implémentation** : LLM Qwen2.5-14B AWQ (EC2 vLLM) avec prompt sémantique pur. Pas de regex, pas de keywords. Validator evidence-locked : `extraction_evidence` doit être un substring de la question.

**Cas critiques** :
- *« Quel est le chiffrement... »* → `current_default` (aucun anchor explicite)
- *« ...dans S/4HANA 1809 »* → `point` avec `version=1809`
- *« ...comment a-t-il évolué entre 2018 et 2024 »* → `range` avec `range_start=2018, range_end=2024`
- *« ...comment a-t-il évolué »* (sans bornes) → `range` avec `range_start=null, range_end=null` (= toute l'histoire)

Multilingue par construction (LLM), domain-agnostic par construction (pas de listes de mots).

#### 4.2 — Anchor Filter

**Rôle** : restreindre l'ensemble des claims candidats à ceux dont le cadre d'applicabilité matche l'anchor.

**Entrée** : anchor + ensemble de claims candidats (issus de la recherche vectorielle Qdrant + KG)

**Sortie** : sous-ensemble de claims valides dans l'anchor

**Implémentation** :
- Pour anchor `point` (ex: version 1809) : `MATCH (c:Claim) WHERE c.applicability_frame_v2_json.release_id = "1809"`
- Pour anchor `current_default` : déléguer à Current Resolver (étape 4)
- Pour anchor `range` : `MATCH (c:Claim) WHERE c.publication_date BETWEEN $start AND $end OR c.validity_start BETWEEN $start AND $end`

Exploite les structures déjà persistées en S1a/S1b (ApplicabilityFrame V2, TemporalFrame).

**Conventions de fallback (runtime, pas KG)** :
- Claim avec `validity_start = null` (96.5% du corpus actuel) → on hérite `validity_start = doc.publication_date` au moment du filtrage. C'est une convention runtime explicite, pas un fait du KG.
- Claim sans `applicability_frame_v2` → considéré comme intemporel par défaut (inclus quel que soit l'anchor).
- Claim taggué `temporal_scope = ALL` à l'extraction (principes transversaux type CIA, normes générales) → toujours inclus. Pré-requis : l'extracteur de claims doit poser ce tag quand le LLM identifie sémantiquement un principe transversal.

#### 4.3 — Current Resolver

**Rôle** : déterminer le document autoritaire pour un sujet quand l'anchor est `current_default`. **Composition runtime sur faits documentés + heuristiques sûres**. Aucune écriture dans le KG.

**Entrée** : sujet résolu

**Sortie** : liste rankée de candidats avec scores de confiance, ou doc autoritaire unique si non-ambigu

**Algorithme en 3 phases** :

**Phase 1 — Filtrage strict sur faits documentés** (Cypher) :
```cypher
MATCH (dc:DocumentContext)
WHERE dc.subject_id = $subject_id
  AND dc.lifecycle_status = 'ACTIVE'
  AND dc.validity_start <= date()
  AND (dc.validity_end IS NULL OR dc.validity_end > date())
// Exclure les docs avec successeur EXPLICITEMENT déclaré actif (LIFECYCLE_RELATION evidence-locked)
OPTIONAL MATCH (dc)<-[:LIFECYCLE_RELATION {type: 'SUPERSEDES'}]-(successor:DocumentContext)
WHERE successor.validity_start <= date()
WITH dc WHERE successor IS NULL
RETURN collect(dc) AS candidates
```

Sortie : liste de N candidats survivant aux faits documentés.

**Phase 2 — Ranking par heuristiques runtime** (jamais écrit dans le KG) :

Pour chaque candidat, calculer un score de confiance :

```python
def runtime_confidence(candidate, all_candidates):
    score = 0.0
    # Heuristique 1 — Recency (plus récent = probablement le current)
    score += 0.50 * normalize_recency(candidate.publication_date, all_candidates)
    # Heuristique 2 — Version ordering (si version numbers extraits sémantiquement)
    if candidate.version_number is not None:
        score += 0.25 * normalize_version_rank(candidate.version_number, all_candidates)
    # Heuristique 3 — KG centrality (sujet-centré)
    score += 0.15 * kg_centrality_for_subject(candidate, subject)
    # Heuristique 4 — Trust score / autorité de la source
    score += 0.10 * candidate.trust_score
    return score  # ∈ [0, 1]
```

Les pondérations sont **runtime, configurables, jamais persistées**. Si certaines heuristiques ne s'appliquent pas (ex: pas de version_number), leur poids redistribué sur les autres.

**Phase 3 — Politique de réponse selon le top de confiance** :

| Top score | Comportement | Affichage user |
|---|---|---|
| ≥ 0.85 | **Auto-pick top candidate**. Le runtime considère que le current est suffisamment évident | Réponse directe + mention discrète de la source (« Selon Doc C, version 2024 ») |
| 0.55 ≤ top < 0.85 | **Suggérer le top + signaler les alternatives** | « La source la plus probable est Doc C (2024). Autres candidats : Doc B (2022). Voulez-vous préciser ? » |
| top < 0.55 | **Ambiguïté irréductible** → remonter au user explicitement | « Plusieurs sources actives sur ce sujet sans hiérarchie claire. Précisez : Doc A / Doc B / Doc C » |
| 1 seul candidat | Auto-pick (Phase 2 et 3 court-circuitées) | Réponse directe |
| 0 candidat | Pas de current pour ce sujet | « Aucune information dans le corpus pour ce sujet en l'état actuel » |

**Pourquoi cette gradation** : sans elle, le système escalade au user dès qu'il y a 2+ candidats, ce qui devient inutilisable (cas Amdt 27/28 sans déclaration textuelle). Avec elle, le système répond comme un humain raisonnable le ferait : il prend la source la plus récente quand l'écart est franc, et ne demande confirmation que quand l'ambiguïté est réelle.

**Invariant inviolé** : aucune des heuristiques ne déclenche d'écriture dans le KG. Le ranking est calculé à chaque query, transitoirement. Si plus tard un humain ajoute manuellement une LIFECYCLE_RELATION explicite (ou si un doc nouvellement ingéré contient la clause d'abrogation), l'écriture se fait comme un fait documenté, pas comme cristallisation d'une heuristique.

Pré-requis : LIFECYCLE_RELATION Doc→Doc implémenté avec **declaration explicite uniquement** (ADR_LIFECYCLE_VS_LOGICAL_RELATIONS, version stricte).

---

## 5. Inventaire des composants existants

### À conserver tels quels

| Composant | Rôle dans la vision recentrée |
|---|---|
| **SubjectResolverV2** | Étape 1 du pipeline. Mature, pas de modification |
| **ApplicabilityFrame V2 (3 axes)** | Source de vérité de l'Anchor Filter (étape 3) |
| **TemporalFrame doc + claim** | Source de vérité temporelle de l'Anchor Filter |
| **9 Logical Claim→Claim** (CONFLICT, EXCEPTION, SUBSET, etc.) | Conflict Detector intra-anchor (étape 5a) |
| **HyDE + reranker BAAI/bge-v2-m3** | Qualité retrieval en amont du pipeline |
| **Trust score** | Affiché en fin de pipeline pour expliquer la confiance |
| **Caches `data/extraction_cache/*.v5cache.json`** | Pas de réingestion. Pas touchés. |

### À implémenter (priorité haute)

| Composant | Ordre | Précision lecture stricte |
|---|---|---|
| **LIFECYCLE_RELATION Doc→Doc** (ADR à resserrer) | Préalable au Current Resolver | **Persistée uniquement sur preuve textuelle explicite** (Doc B contient un texte déclarant qu'il abroge/évolue/réaffirme Doc A). Pas d'inférences. Voir amendement ADR_LIFECYCLE_VS_LOGICAL_RELATIONS |
| **Anchor Extractor** | Étape 2 du pipeline | LLM sémantique pur, evidence-locked |
| **Anchor Filter** | Étape 3 du pipeline | Cypher + Qdrant sur ApplicabilityFrame V2 et TemporalFrame |
| **Current Resolver** | Étape 4 du pipeline | Composition runtime de faits documentés. Aucune écriture dans le KG. Remonte au user en cas d'ambiguïté irréductible |

### À adapter / fusionner

| Composant existant | Devient |
|---|---|
| Mode `LOOKUP_FACTUAL` (V1.1) | Cas particulier du pipeline anchor-driven (anchor=current, retour direct claim) |
| Mode `APPLICABILITY_QUERY` (V1.1) | Cas particulier (anchor=point ou current avec scope précisé) |
| Mode `SNAPSHOT_TEMPORAL` (V1.1) | Cas particulier (anchor=point sur axe date) |
| Mode `DIFF_EVOLUTION` (V1.1) | Cas particulier (anchor=range, étape 5b Evolution Builder) |
| Mode `EXPLORATION_RELATIONAL` (V1.1) | Drill-down post-réponse (UI, pas un mode de pipeline) |
| Mode `CONFLICT_RISK` (V1.1) | Toggle UI "Audit" pour le maintainer (vue spécialisée) |
| Mode `SYNTHESIS_SUMMARY` (V1.1) | C'est juste une question complexe en mode défaut, pas un mode |

### À supprimer (dette ou sur-ingénierie)

| Composant | Raison |
|---|---|
| **Mode-classifier LLM (7 modes)** | Remplacé par Anchor Extractor (rôle plus simple, plus robuste) |
| **3 régimes RAG_LED / KG_LED / HYBRID** | Remplacés par pipeline linéaire sans branche conditionnelle |
| **Auto-escalation RAG↔KG** | Remplacée par Anchor Filter result-driven (si trop peu de claims, on remonte au user) |
| **3 personas (compliance_officer, explorer, reader)** | Réduits à toggle "Audit ON/OFF" pour maintainer |
| **14 SUPERSEDES Claim→Claim incorrectes** (S3.F-4 itération 2) | Hygiène — ADR Lifecycle a établi qu'elles sont mal modelées |

### En réserve (ADR conservées mais non-prioritaires)

- ADR_RAISONNEMENT_UI : la version actuelle suppose les 7 modes. À relire et simplifier après implémentation du pipeline anchor-driven.
- ADR_TENSION_CLASSIFICATION : intéressant mais la classification de tension perd de l'importance puisque le filtrage anchor élimine 90% des tensions apparentes.

---

## 6. Statut des deux types de tensions

| Type | Avant (architecture Runtime V1.1) | Maintenant (vision recentrée) |
|---|---|---|
| **Évolution naturelle** (TLS 1.2 v.2022 → TLS 1.3 v.2024) | Détectée par DIFF_EVOLUTION mais aussi remontée comme bruit en LOOKUP_FACTUAL | **Invisible par construction** en mode défaut. Visible uniquement si anchor=range explicite |
| **Vraie contradiction** (deux sources contemporaines qui s'opposent) | Détectée par CONFLICT_RISK mais noyée dans le bruit des évolutions | **Seul résiduel** après filtrage anchor. Signal propre, haute valeur |

C'est exactement la séparation que tu décrivais : « tensions liées à l'évolution naturelle = pas un problème » vs « tensions manifestes en opposition = vrai problème ».

---

## 7. Critère de validation auto-administré

À jouer seul, sans dépendre d'un user externe (Armand ou autre). Toi-même dans le rôle d'un user expert.

### Test 1 — Vérité courante (50 questions, métrique cible 90%)

Sur tes corpus de référence (SAP que tu maîtrises + aerospace_compliance) :

- Formule 50 questions type *« Quel est X ? »* sans préciser de version/date
- OSMOSIS doit retourner la valeur du *current* uniquement
- Pas de mention « mais avant c'était Y » dans la réponse principale
- Métrique : taux de réponses factuellement correctes ≥ 90%

### Test 2 — Anchor explicite ponctuel (10 questions, métrique cible 100%)

- Formule 10 questions type *« Quel est X dans la version V / à la date D ? »*
- OSMOSIS doit retourner la réponse *uniquement* pour ce point
- Pas de mix avec d'autres versions
- Métrique : 10/10 réponses dans le bon scope (binaire)

### Test 3 — Évolution explicite (5 questions)

- Formule 5 questions type *« Comment X a-t-il évolué entre A et B ? »* ou *« Depuis quand Y est utilisé ? »*
- OSMOSIS doit retourner une timeline ordonnée
- Métrique : timeline cohérente, ordonnée, sans claim hors-range

### Test 4 — Vraies contradictions injectées (3-5 cas)

- Tu fabriques 3-5 cas en injectant manuellement un claim contradictoire dans le KG (même sujet, même anchor, valeur opposée)
- OSMOSIS doit **détecter et remonter** la contradiction au user
- Métrique : détection 5/5 (recall = 1.0)

**Critère global de réussite** : Test 1 ≥ 90% + Test 2 = 100% + Test 3 cohérent + Test 4 = 100%.

Si ces 4 tests passent sur deux corpus différents (SAP + aerospace), la mission primaire d'OSMOSIS est validée. Le reste (UI, polish, modes audit avancés) devient incrémental.

---

## 8. Implications pour les ADR existantes

| ADR | Statut |
|---|---|
| `CONTRADICTION_DETECTION_ARCHITECTURE.md V3.3` | ✅ **Conservée**. Le modèle de données (12 LogicalRelations, 3 axes, LifecycleStatus) reste exact. Seule la couche runtime change. |
| `RUNTIME_EXPLOITATION_ARCHITECTURE.md V1.1` | ⚠️ **Partiellement déprise**. Les 7 modes + 3 régimes sont remplacés par le pipeline 6-étapes anchor-driven. À refondre en V2.0. |
| `ADR_LIFECYCLE_VS_LOGICAL_RELATIONS.md` | ⚠️ **Conservée mais à resserrer**. La séparation Logical/Lifecycle est juste, mais le score hybride 4-features (structural + KG + temporal + explicit) doit être ramené à un score 1-feature : seule la **déclaration textuelle explicite** (evidence-locked) déclenche persistence d'une LIFECYCLE_RELATION. Les autres scores deviennent des **indices runtime** consultables par le Current Resolver, pas des conditions d'écriture dans le KG. |
| `ADR_KG_INJECTION_ARCHITECTURE_V3.md` | ✅ **Conservée** — concerne la couche injection, pas la couche runtime |
| `ADR_ENTITY_EXTRACTION_DOMAIN_AGNOSTIC.md` | ✅ **Conservée** — principe domain-agnostic réaffirmé ici |
| `ADR_RAISONNEMENT_UI.md` | ⏳ **À relire** après implémentation du pipeline. Suppose les 7 modes, va probablement se simplifier. |
| `ADR_TENSION_CLASSIFICATION.md` | ⏳ **En réserve**. Le filtrage anchor élimine la majorité des cas, la classification fine devient secondaire. |
| Autres ADR (Cockpit, LLM Configuration, Local LLM) | ✅ **Non-affectées** — concernent des couches transverses |

---

## 9. Plan d'implémentation suggéré

### Sprint 0 — Cleanup hygiène (1 jour)

- Supprimer les 14 SUPERSEDES Claim→Claim incorrectes (S3.F-4 itération 2)
- Marquer le mode CONFLICT_RISK Claim→Claim comme legacy en attendant la V2 anchor-driven

### Sprint 1 — LIFECYCLE_RELATION Doc→Doc (1-2 semaines, version stricte)

Implémenter l'ADR_LIFECYCLE_VS_LOGICAL_RELATIONS **version resserrée** :
- Schéma additif Neo4j
- **Détection unique : extraction LLM evidence-locked** d'une déclaration textuelle de succession dans le full_text d'un doc (« This Regulation repeals X », « This Amendment supersedes Y »). Pas de regex, pas de keywords — sémantique pur.
- Validator post-LLM : la quote extraite doit être substring du full_text (sinon rejet).
- LIFECYCLE_RELATION persistée **uniquement** si déclaration textuelle valide.
- **Pas de score hybride 4-features** (les signaux structural/KG/temporal sont des indices runtime du Current Resolver, pas des conditions de persistence).
- Backfill sur les 17 docs aerospace_compliance.
- Validation : sur les paires manifestement déclarées (ex: 2021/821 vs 428/2009 où le règlement contient explicitement la clause d'abrogation), la relation est détectée. Les paires implicites (CS-25 Amdt 27→28 si la déclaration n'est pas textuelle) ne sont **pas** persistées et seront gérées par le Current Resolver via tri date + remontée au user en cas d'ambiguïté.

### Sprint 2 — Anchor Extractor + Anchor Filter (2 semaines)

- Anchor Extractor : LLM sémantique pur, validator evidence-locked
- Anchor Filter : Cypher + Qdrant filtré par anchor extrait
- Tests unitaires sur 30 questions diverses (anchor implicite, ponctuel, range)

### Sprint 3 — Current Resolver (1 semaine)

- Algorithme déterministe Cypher
- Cas de test : 3 docs SAP "actifs" → un seul retourné
- Cas de test : règlement abrogé → ancien doc filtré

### Sprint 4 — Pipeline runtime end-to-end + suppression ancien runtime (2 semaines)

- Câbler les 6 étapes
- Supprimer mode-classifier, régimes, auto-escalation
- Réduire personas à 1 toggle Audit
- Test des 4 critères de validation auto-administré

### Sprint 5 — UI simplifiée (1-2 semaines)

- Frontend : suppression des 7 modes, ajout d'un toggle Audit
- Réponse principale + drill-down + trust score
- Mode Évolution rendu si anchor=range

**Total estimé** : 8-11 semaines (vs 18-23 semaines initialement prévues pour Runtime V1.1 complet). Lecture stricte allège Sprint 1 d'1 semaine (pas de score hybride à calibrer).

---

## 10. Ce qui rend cette vision opérable

1. **90% de l'investissement existant est conservé** : SubjectResolverV2, ApplicabilityFrame V2, TemporalFrame, 9 Logical Claim→Claim, HyDE, reranker, Trust score, caches.
2. **3 composants seulement à créer** : Anchor Extractor, Anchor Filter, Current Resolver. Pas une refonte.
3. **Le critère de validation est auto-administrable** : pas besoin d'Armand. Tu joues le rôle du user expert sur deux corpus que tu connais.
4. **Le pivot conceptuel est clair et stable** : `Vérité = intra-anchor / Évolution = inter-anchor / Contradiction = intra-anchor uniquement`. Cette formule guide tous les arbitrages.
5. **Domain-agnostic par construction** : aucun composant du pipeline ne dépend du domaine. Les hints Domain Pack restent optionnels.

---

## 11. Anti-patterns à interdire dans tout futur sprint

À titre de garde-fou, dans la lignée des invariants méthodologiques V3.3 :

1. ❌ **Pas de regex/keywords pour l'extraction d'anchor** — sémantique LLM uniquement
2. ❌ **Pas de mode auto-classifié** — l'anchor (point/range) suffit à dériver le comportement
3. ❌ **Pas de fallback complexe** — si Anchor Filter retourne 0 claim, on remonte au user, on ne devine pas
4. ❌ **Pas de "feature USP" qui n'a pas de cas d'usage validé** — chaque ajout doit s'inscrire dans la mission primaire
5. ❌ **Pas de personas avant que le mode défaut soit irréprochable** — confort UI ≠ mission
6. ❌ **Pas d'inférence persistée dans le KG** — le KG porte ce que disent les documents, pas ce que le système déduit. Toute inférence est une opération runtime, recalculée à chaque query, jamais fossilisée. **Note importante** : l'inférence runtime EST autorisée (et nécessaire). Ce qui est interdit c'est d'écrire le résultat d'une inférence dans le KG.
7. ❌ **Pas d'auto-pick silencieux à confiance basse** — si le top candidate du Current Resolver a une confiance < 0.55, le runtime remonte au user au lieu de répondre comme si c'était évident. Le système est gradué : auto-pick à haute confiance OK, suggestion à moyenne confiance OK, remontée à basse confiance obligatoire. Pas de « le plus probable » sans signal de fiabilité.

---

## Conclusion

La complexité d'OSMOSIS n'était pas dans la modélisation des données (qui est juste), elle était dans l'architecture runtime qui essayait de deviner trop de choses. En reportant la décision sur l'anchor (qui est une propriété **objective** de la question), on simplifie radicalement le runtime et on rend la mission primaire opérable.

Le mantra est désormais :

> **Quel est l'anchor ? Filtre par anchor. Réponds dans l'anchor. Le reste, c'est du bruit ou du drill-down explicite.**

---

*Vision validée par Fred le 30/04/2026. Ce document est désormais le **référentiel maître** du chantier OSMOSIS V2. Toute proposition d'ajout de complexité doit pouvoir se justifier face à la formule ci-dessus. Tout sprint futur doit être tracé contre cette vision avant lancement.*
