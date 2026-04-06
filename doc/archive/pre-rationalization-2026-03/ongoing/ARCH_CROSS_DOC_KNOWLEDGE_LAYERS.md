# Architecture : Couches de Connaissance Cross-Document

**Statut** : DRAFT v3 — Revu avec feedback (4 points critiques + 4 subtilités intégrés)
**Date** : 2026-02-20
**Réf** : ADR North Star (NS-1→10), ADR Navigation Layer, SPEC MVP V1 Usage B

---

## Problème

Le KG OSMOSE est un ensemble de silos par document. Les liens cross-doc sont quasi-inexistants :
- 11 entités partagées entre docs sur des milliers (canon intra-doc uniquement)
- CHAINS_TO = jointure lexicale exacte (même string normalisée, pas même concept)
- Les pivots (SubjectAnchor, ComparableSubject, ApplicabilityAxis) existent en Neo4j mais aucun chemin de requête ne les traverse
- 0 hop sémantique — deux mots différents pour le même concept ne sont pas connectés

**Conséquence** : le graphe reflète fidèlement chaque document isolément, mais ne permet ni de raisonner entre documents, ni de naviguer par concept, ni de détecter les contradictions cross-doc.

---

## Principes directeurs

1. **Evidence-locked** — Tout lien porte la preuve de son existence (claim_ids, verbatim). Pas de world knowledge.
2. **Contrat par couche** — Chaque couche a un usage autorisé explicite. Violation = bug architectural.
3. **Non-destructif** — Jamais de MERGE de nœuds existants. Les pivots cross-doc sont des nœuds NOUVEAUX reliés aux nœuds existants. Réversible, auditable.
4. **Faux négatifs > faux positifs** — Conforme à North Star NS-3 et INV-9.
5. **Post-import** — Les couches s'ajoutent par passes corpus-level (comme Phase 2.8), pas en modifiant le pipeline d'ingestion.

---

## Les 4 couches

### Couche 0 — Vérité Documentaire (existante)

> *"Le document dit X. Voici la citation verbatim."*

| Élément | Nœud Neo4j | Déjà en place |
|---------|-----------|---------------|
| Claim + verbatim_quote | `(:Claim)` | Oui |
| Entity + mentions | `(:Entity)` | Oui |
| Passage source | `(:Passage)` | Oui |
| DocumentContext | `(:DocumentContext)` | Oui |
| Liens ABOUT, SUPPORTED_BY | Relations | Oui |

**Confiance** : 100%
**Usage autorisé** : Tout (raisonnement, preuve, affichage, export)
**Interdit** : Modifier ces nœuds depuis les couches supérieures

---

### Couche 1 — Identité Structurelle Cross-Doc

> *"L'entité X dans doc A est la même entité X dans doc B."*

#### Modèle de données

```
(:Entity {doc_A})-[:SAME_CANON_AS {method, confidence}]->(:CanonicalEntity)
(:Entity {doc_B})-[:SAME_CANON_AS {method, confidence}]->(:CanonicalEntity)
```

**CanonicalEntity** = nœud pivot corpus-level. NE remplace PAS les Entity locales.

```
CanonicalEntity {
    canonical_entity_id: str        # "ce_" + hash(tenant_id + ":" + normalized_name)
    canonical_name: str             # Forme canonique choisie
    tenant_id: str
    entity_type: str                # product | component | concept | metric | actor | other
                                    # Inféré depuis Entity.entity_type source (voir règle ci-dessous)
    source_entity_ids: [str]        # Entity.entity_id de chaque doc
    doc_count: int                  # Nombre de docs
    total_mention_count: int        # Somme des mentions
    created_at: datetime
}
```

#### Garde-fou de scope (anti-faux positif d'homonymie)

Même `normalized_name` ≠ même référent. Exemple : "Authorization Object" en ABAP vs en IAM générique.

**Règle** : deux Entity ne sont reliées au même CanonicalEntity que si :
- même `tenant_id` (obligatoire)
- ET l'une des conditions suivantes :
  - même `entity_type` (product ↔ product, concept ↔ concept)
  - OU co-occurrence dans un même SubjectAnchor (même domaine documentaire)
  - OU validation LLM avec evidence des deux côtés (méthode `llm_arbiter`)

En cas de doute → deux CanonicalEntity distinctes. Possibilité de split ultérieur si un CanonicalEntity devient un "hub fourre-tout" (>50 entity sources, types hétérogènes).

#### Inférence du `entity_type`

Le `entity_type` d'un CanonicalEntity est déterminé par vote majoritaire sur les Entity sources :
1. Chaque Entity porte un `entity_type` (PRODUCT, COMPONENT, STANDARD, ACTOR, OTHER, etc.) assigné à l'extraction
2. Le CanonicalEntity prend le type majoritaire parmi ses sources
3. Si le vote est ambigu (ex: 50/50) → fallback `other`
4. Si un merge candidat croise des types incompatibles (ex: PRODUCT + ACTOR) → **ne pas merger**, créer deux CanonicalEntity distinctes

Pas de classifieur LLM supplémentaire — on s'appuie sur le type déjà extrait par le pipeline claimfirst (Phase 1). Le fallback `other` est safe car il ne bloque aucun merge, il évite juste le sur-classement.

#### Méthodes de résolution (par ordre de confiance)

| Méthode | Confiance | Exemple | Automatique ? |
|---------|-----------|---------|---------------|
| `exact_normalized` | 1.0 | "authorization object" = "authorization object" | Oui |
| `case_only` | 0.98 | "Authorization Object" = "authorization object" | Oui |
| `prefix_dedup` | 0.95 | "SAP SAP S/4HANA" → "SAP S/4HANA" | Oui |
| `version_strip` | 0.90 | "S/4HANA 2021" → "S/4HANA" | Oui |
| `llm_arbiter` | 0.85 | "S/4HANA" ↔ "SAP S/4HANA" | Oui (gates + LLM) |
| `soft_candidate` | 0.60 | "Access Control" ↔ "Authorization Concept" | Non — POSSIBLE_SAME_AS uniquement |

**Règle** : seules les méthodes ≥ 0.85 créent un lien `SAME_CANON_AS`.
En dessous → `POSSIBLE_SAME_AS` (non traversé automatiquement).

#### Ce que ça débloque

Le path cross-doc :
```cypher
MATCH (c1:Claim)-[:ABOUT]->(e1:Entity)-[:SAME_CANON_AS]->(ce:CanonicalEntity)
      <-[:SAME_CANON_AS]-(e2:Entity)<-[:ABOUT]-(c2:Claim)
WHERE c1.doc_id <> c2.doc_id
```

**Confiance** : HAUTE
**Usage autorisé** : Raisonnement (contradictions value-level, dédup), recherche, navigation
**Interdit** : Supprimer ou modifier les Entity locales

#### Métrique de succès

- Avant : ~11 entités partagées cross-doc
- Après : objectif >300 CanonicalEntity avec ≥2 docs
- Validation : audit manuel sur 50 cas, précision ≥ 95%

---

### Couche 2 — Pivots Factuels (ClaimKey)

> *"Ces claims de docs différents, avec des mots différents, répondent à la même question factuelle."*

#### Modèle de données

```
(:Claim)-[:HAS_QUESTION_SIG {evidence_span_ids, confidence}]->(:QuestionSignature)
(:QuestionSignature)-[:CONFIRMED_AS]->(:ClaimKey)
```

**Deux étapes** :

**Étape 2a — QuestionSignature** (pré-ClaimKey, par claim)

```
QuestionSignature {
    sig_id: str
    question_canonical_en: str      # "What is the minimum TLS version?"
    dimension_key: str              # OBLIGATOIRE — identifiant stable pour clustering
                                    # ex: "tls_min_version", "backup_frequency"
                                    # Format: snake_case, pas de phrases
    slot_schema: {                  # Optionnel mais recommandé
        metric: "tls_version",
        scope: "encryption",
        object_type: "protocol"
    }
    value_type: str                 # version | number | boolean | enum | string
    scope_canonical_entity_ids: [str]  # CanonicalEntity concernées (optionnel)
    inference_method: str           # "pattern_level_a" | "llm_level_b"
    confidence: float               # Score de confiance de l'inférence
    evidence_claim_ids: [str]       # Claims sources
}
```

**Contrainte de format Level B** : le LLM doit produire un `dimension_key` stable (snake_case, ≤5 mots). Sans cette contrainte, le clustering est impossible car les questions en langue naturelle dérivent ("What is the minimum TLS version?" vs "Which TLS version is required?" vs "What TLS level is mandatory?"). Le `dimension_key` est le vrai identifiant de regroupement, la `question_canonical_en` n'est qu'un label humain.

**Interaction C1 ↔ C2 — Règle de scope** : le champ `scope_canonical_entity_ids` est optionnel.
- Si présent → la QS est scopée à un produit/composant spécifique. Deux QS avec la même `dimension_key` mais des scopes différents sont des questions **distinctes** (ex: "tls_min_version pour SAP BTP" ≠ "tls_min_version pour S/4HANA").
- Si absent → la QS est **globale au document**. Lors du clustering, les QS globales matchent avec toute QS de même `dimension_key` quel que soit le scope.
- Comportement par défaut : absent (global). Le LLM Level B ne scope que s'il détecte un qualifieur explicite dans la claim.

**Étape 2b — ClaimKey** (confirmée, corpus-level)

Une QuestionSignature devient ClaimKey quand :
- ≥ 2 documents **indépendants** produisent la même `dimension_key` (ou clustering très proche)
- Le `value_type` est compatible
- La `question_canonical_en` est stable (pas de drift sémantique entre les variantes)

**Définition de "documents indépendants"** : deux documents sont indépendants si au moins l'un de ces critères est vérifié :
- `doc_A.primary_subject ≠ doc_B.primary_subject` (sujets principaux différents)
- OU `doc_A.comparable_subject ≠ doc_B.comparable_subject`
- OU si même sujet : versions/éditions différentes (via ApplicabilityAxis)

Sinon (même sujet, même version, même template) → la récurrence est artificielle et ne confirme PAS la ClaimKey. Cela évite que des documents issus d'un même template répétitif gonflent artificiellement les métriques.

```
ClaimKey {
    claimkey_id: str                # "ck_tls_min_version"
    canonical_question: str
    domain: str                     # "security.encryption"
    status: EMERGENT | COMPARABLE | DEPRECATED | ORPHAN
    info_count: int                 # Nombre de claims liées
    doc_count: int                  # Nombre de docs
    has_contradiction: bool
    value_type: str
}
```

#### Niveaux d'inférence

| Niveau | Méthode | Couverture | Précision |
|--------|---------|-----------|-----------|
| **A** (existant) | Patterns regex déterministes | ~12 patterns IT/infra | ~100% |
| **B** (à créer) | LLM evidence-locked : reformule la claim en question factuelle | Large | ~85-90% (à valider) |
| **C** (futur) | Clustering de QuestionSignatures + confirmation multi-doc | Auto | Haute (multi-doc = filtre) |

**Level B — Contraintes du prompt LLM** :
- Le LLM reçoit : claim.text + claim.verbatim_quote + entity names
- Le LLM produit : question_canonical_en + value_type + slot_schema
- Le LLM ne voit PAS d'autres documents (pas de cross-doc synthesis)
- Si le LLM ne peut pas reformuler → `null` (fail-open, pas de forçage)

#### Ce que ça débloque

Le produit Challenge (Usage B) :
```
User: "TLS 1.2 est-il suffisant ?"
→ ClaimKey "tls_min_version"
→ Toutes les claims de tous les docs qui répondent à cette question
→ ValueContract : doc A dit 1.2, doc B dit 1.3 → EVOLUTION (pas contradiction)
```

**Confiance** : HAUTE (Level A) / MOYENNE-HAUTE (Level B)
**Usage autorisé** : Comparaison value-level, challenge, timeline
**Interdit** : Modifier les claims sources

#### Métrique de succès

- Sur 5 docs : ≥ 20 QuestionSignatures récurrentes (≥2 docs)
- Ratio "stable keys" / "one-offs" > 30%
- Précision manuelle sur 50 cas ≥ 90%

---

### Couche 3 — Ponts Conceptuels (navigation uniquement)

> *"Authorization Object et Access Control Policy sont des concepts liés, mais pas identiques."*

#### Modèle de données

```
(:CanonicalEntity)-[:CONCEPTUALLY_RELATED {
    relation_type,          # SPECIALIZES | REQUIRES | ENABLES | ALTERNATIVE_TO | ASPECT_OF
    confidence,
    evidence_claim_ids,     # Claims où les deux apparaissent ensemble
    method                  # "structured_form" | "co_passage_llm"
}]->(:CanonicalEntity)
```

**PAS de lien direct entre Entity locales.** Toujours via CanonicalEntity (Couche 1 en pré-requis).

#### Conditions de création (anti-hallucination)

Un pont conceptuel ne peut être créé que si :

1. **Seed structurel** : les deux entités apparaissent dans une relation `structured_form` (S/P/O) d'au moins 1 claim, OU dans le même passage_id
2. **LLM arbiter** : le LLM reçoit les claims/passages où les deux entités co-apparaissent et juge le type de relation. Evidence-locked (pas de world knowledge)
3. **Multi-doc** : le lien n'est "navigable" que s'il est confirmé dans ≥2 documents indépendants. Sinon → `status: CANDIDATE` (non traversé par défaut)

#### Règle de non-promotion (ADR Navigation Layer)

> Un lien Couche 3 ne peut JAMAIS être utilisé pour :
> - Détecter une contradiction
> - Produire une preuve dans le Challenge (Usage B)
> - Apparaître dans une réponse comme "le document dit que..."
>
> Il ne sert QU'À la navigation : "Voir aussi", "Concepts liés", exploration thématique.

**Confiance** : MOYENNE
**Usage autorisé** : Navigation, exploration, "voir aussi"
**Interdit** : Raisonnement, preuve, contradiction, export comme fait

#### Contrainte UX obligatoire

Même si le backend cloisonne C3 correctement, l'interface peut induire un biais de perception : l'utilisateur qui navigue via un lien C3 et voit une claim peut croire qu'elle est "liée" factuellement.

**Règles UX** :
- Tout lien C3 affiché doit porter un badge visuel distinct ("Lien de navigation — pas d'équivalence factuelle")
- Couleur/style différent des liens C0/C1/C2 (ex: pointillés gris vs trait plein)
- Jamais mélangé dans les résultats "preuve" du Challenge (Usage B)

#### Métrique de succès

- 50 bridges de haute qualité avec evidence_claim_ids
- Précision manuelle ≥ 85%
- 0 bridge utilisé dans une réponse "preuve" (test de non-promotion)

---

## Pipeline d'exécution

Les couches sont ajoutées par **passes post-import**, indépendantes du pipeline claimfirst :

```
[Pipeline claimfirst existant]
    ↓ (produit Claims, Entities, ABOUT, SubjectAnchors)

[Pass C1 — Canon cross-doc entités]
    Input  : Entity nodes de tous les docs
    Output : CanonicalEntity + SAME_CANON_AS
    Quand  : après chaque import batch, ou incrémental
    Script : scripts/canonicalize_entities_cross_doc.py

[Pass C2a — QuestionSignatures]
    Input  : Claims + Entities
    Output : QuestionSignature + HAS_QUESTION_SIG
    Quand  : après C1 (utilise CanonicalEntity pour le scope)
    Script : scripts/extract_question_signatures.py

[Pass C2b — ClaimKey confirmation]
    Input  : QuestionSignatures de tous les docs
    Output : ClaimKey + CONFIRMED_AS
    Quand  : après C2a, corpus-level
    Script : scripts/confirm_claimkeys.py

[Pass C3 — Ponts conceptuels]
    Input  : CanonicalEntity + Claims avec structured_form
    Output : CONCEPTUALLY_RELATED
    Quand  : après C1, optionnel
    Script : scripts/detect_concept_bridges.py
```

Chaque pass est **idempotent** (MERGE Neo4j) et **réexécutable** après correction de code.

---

## Risques identifiés et mitigations

### Risque 1 — Explosion combinatoire C2

Level B large → centaines de QuestionSignatures → bruit.

**Mitigation** :
- Ignorer les QS uniques (1 seule claim) — pas de valeur pour le cross-doc
- Seuil minimal de récurrence : `dimension_key` présente dans ≥3 claims avant création de nœud QS.
  **Exception** : les QS avec `value_type` ∈ {number, version, percent} sont conservées dès 1 occurrence (dimensions rares mais critiques — ex: "maximum data retention period" n'apparaît qu'une fois mais porte une valeur comparée factuelle). Le seuil ≥3 s'applique uniquement aux `value_type` ∈ {string, enum, boolean}.
- Cap : max 50 QS par document (les plus fréquentes)
- Monitoring : ratio "QS récurrentes cross-doc" / "QS totales" doit rester > 20%

### Risque 2 — CanonicalEntity hub fourre-tout

Si le merge est trop large, un CanonicalEntity peut devenir un méga-hub mélangeant des sous-concepts.

**Mitigation** :
- Sous-typage dès la création : `entity_type` (product, component, concept, metric, actor, other)
- Monitoring : alerter si un CanonicalEntity a >50 Entity sources, ou >5 entity_types distincts, ou un ratio `claims_distinctes / entity_sources` < 2 (signe d'un hub artificiel : beaucoup d'entités rattachées mais peu de claims réelles derrière)
- Opération de split prévue : si un hub est détecté, le script peut le scinder en sous-CanonicalEntity basées sur le entity_type ou le SubjectAnchor d'origine
- P0 commence ultra-strict (exact + case + prefix uniquement) → audit avant d'élargir

---

## Règles anti-régression

1. **C3 jamais dans les contradictions** : tout chemin de détection de contradiction ne traverse que C0/C1/C2
2. **C2 jamais sans evidence** : toute ClaimKey porte ≥1 evidence_claim_id par document
3. **C1 jamais destructif** : les Entity locales ne sont jamais modifiées/supprimées par C1
4. **Promotion unidirectionnelle** : C3 → C2 interdit. C2 → C1 interdit. Chaque couche est indépendante.
5. **Audit trail** : chaque lien cross-doc porte `method`, `confidence`, `created_at`

---

## Relation avec les abstractions stratified existantes

| Concept stratified | Équivalent dans ce plan | Statut |
|---|---|---|
| `CanonicalConcept` (Pass 3) | `CanonicalEntity` (C1) | À connecter — même rôle, modèles compatibles |
| `CanonicalTheme` (Pass 3) | Couche 3 (thematic bridges) | À connecter |
| `ClaimKey` (claimkey/) | `ClaimKey` (C2) | Réutiliser tel quel — modèle + patterns Level A |
| `InformationMVP` | `Claim` (claimfirst) enrichie | Pas de migration — enrichissement par QuestionSignature |
| `ValueInfo` / `ValueContract` | Value comparison C2 | Réutiliser tel quel |
| Navigation Layer | Couche 3 confinement | Déjà en ADR, appliquer le contrat |

**Stratégie** : importer les abstractions stratified comme couche au-dessus de claimfirst. Pas de migration, pas de réécriture.

---

## Ordre d'implémentation (révisé après review)

### Étape 1 — C1 minimal, ultra strict (Sem 1)

Seulement les 3 méthodes déterministes les plus sûres :
- `exact_normalized` (confiance 1.0)
- `case_only` (confiance 0.98)
- `prefix_dedup` (confiance 0.95)

**PAS encore** : `version_strip`, `llm_arbiter`, `soft_candidate`.

Objectif : passer de ~11 à ~150-200 CanonicalEntity. Audit manuel avant d'élargir.

### Étape 2 — Brancher search sur C1 (immédiatement après)

Avant même C2. L'effet doit être visible sur le produit :
- Cross-doc retrieval amélioré
- Navigation plus riche
- Preuve que C1 apporte de la valeur

Sans ce feedback utilisateur, C2 reste théorique.

### Étape 3 — C2 Level B sur sous-ensemble (après validation C1)

Pas tout le corpus. Choisir :
- 2-3 docs sécurité (Security Guide 2022 + 2023 + Operations Guide)
- Tester le clustering de QuestionSignatures sur ce scope réduit

Valider :
- Précision ≥ 90% sur 50 cas
- Taux de QS récurrentes cross-doc satisfaisant
- `dimension_key` stable et clusterisable

### Étape 4 — ClaimKey confirmation (après stabilité QS)

Seulement quand les QuestionSignatures sont stables et auditées.

### Étape 5 — C3 en dernier

C3 ne doit arriver que quand C1 et C2 sont stables et éprouvés.

| # | Pass | Effort | Pré-requis | Métrique clé |
|---|------|--------|-----------|-------------|
| **1** | C1 strict (exact + case + prefix) | 2-3j | Aucun | ~150-200 CanonicalEntity |
| **2** | Search sur C1 pivots | 1j | Étape 1 | Requête couvre ≥2x plus de docs |
| **3** | C2a Level B (sous-ensemble) | 1 sem | Étape 1 auditée | ≥20 QS récurrentes |
| **4** | C2b ClaimKey confirmation | 2-3j | Étape 3 stable | Ratio stable/one-off > 30% |
| **5** | C3 — Ponts conceptuels | 2 sem | Étapes 1+3 stables | 50 bridges, précision ≥85% |
