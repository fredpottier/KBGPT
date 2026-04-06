# ADR — Couche Perspective : de la collection de faits à la compréhension structurée

**Date** : 2026-04-06
**Statut** : Proposition (à valider)
**Auteur** : Claude Code + Fred
**Portée** : Architecture cible, pas MVP

---

## 1. Le problème

OSMOSIS sait **retrouver** des faits. Il ne sait pas **comprendre** des sujets.

Quand un utilisateur pose "Qu'apporte la nouvelle version de S/4HANA ?", le système remonte des chunks épars et produit une liste plate de faits juxtaposés. Un expert humain répondrait par axes thématiques (sécurité, fonctionnalités, compatibilité), avec des évolutions, des nuances, et des signalements de zones non couvertes.

### Ce qui marche déjà

Le KG apporte une valeur réelle et mesurée par rapport au RAG simple :
- **Expansion des preuves** : le KG détecte des documents liés par tensions ou chaînes cross-doc et déclenche des recherches Qdrant ciblées → le LLM reçoit des sources que le RAG seul n'aurait jamais trouvées
- **Détection de signaux** : tensions, évolutions temporelles, gaps de couverture, exactitude
- **Disclosure forcée** : ContradictionEnvelope oblige le LLM à adresser les divergences
- **Response modes** : DIRECT/AUGMENTED/TENSION/STRUCTURED_FACT adaptent le flow selon les signaux

### Ce qui manque

Le KG **élargit** le pool de preuves mais ne les **organise** pas. Le LLM reçoit :
- ~10-18 chunks en liste non organisée (RAG initiaux + chunks injectés par le KG via tension docs + CHAINS_TO docs)
- Quelques instructions de lecture procédurales (2-3 lignes en mode TENSION, 0 en mode DIRECT/AUGMENTED)

**Point crucial** : avec les Response Modes V3 activés en production (`OSMOSIS_RESPONSE_MODES=true`), le `graph_context_text` est **vidé** en mode DIRECT et AUGMENTED (les deux modes les plus fréquents). En mode TENSION, seules 2-3 lignes de contraintes procédurales sont injectées (~50-80 tokens). Le KG n'injecte PAS de contenu sémantique dans le prompt — conformément à INV-ARCH-06 ("Le KG diagnostique, il ne raconte pas"). Toute la valeur ajoutée du KG passe par l'injection de **chunks supplémentaires** dans le pool de preuves.

Le LLM doit donc **lui-même** deviner la structure de sa réponse à partir d'une liste plate de chunks. Pour une question directe, ça suffit. Pour une question ouverte, ça produit du "plat".

### Le diagnostic précis

Ce n'est pas un problème de retrieval (on trouve les bonnes preuves grâce à l'expansion KG). Ce n'est pas un problème d'injection de contexte narratif (on a délibérément écarté cette approche après une dégradation de 8 points de factualité). C'est un problème de **composition** : les preuves arrivent au LLM sans structure intermédiaire qui les organise par dimension thématique. Le KG sait **élargir** les preuves, mais pas les **structurer pour la restitution**.

---

## 2. Les approches écartées et pourquoi

### 2a. "Concept Dossiers" persistants (proposition initiale Claude)

Construire pour chaque concept majeur un dossier structuré figé dans le KG.

**Écarté parce que** :
- Impose une grille de lecture unique par concept, indépendante de la question
- La même base de preuves doit être organisée différemment selon qu'on demande "Qu'apporte la nouvelle version ?" vs "Quels risques sécurité ?" vs "Comparez 2022 et 2023"
- Statique → risque de staleness quand le corpus évolue
- Sous-exploite la force d'OSMOSIS qui est dans l'activation dynamique du graphe

### 2b. "Answer Planner" purement runtime (proposition ChatGPT)

Construire un plan de réponse ad hoc à chaque question, sans rien persister.

**Écarté parce que** :
- Non reproductible (le même set de preuves peut donner des axes différents)
- Non cumulatif (on recommence à zéro à chaque question)
- Inutilisable pour Atlas/Wiki (qui a besoin de structures persistantes)
- Dépendance totale au LLM pour la découverte d'axes → instabilité

### 2c. "ResponseFrames" métier (variante ChatGPT)

Typer les questions en catégories métier (WHATS_NEW, SECURITY_POSTURE, MIGRATION_IMPACTS).

**Écarté parce que** :
- Casse l'agnosticisme domaine d'OSMOSIS (INV fondamental)
- Un corpus médical ou juridique n'a pas les mêmes catégories qu'un corpus SAP
- Réintroduit du hardcoding là où tout doit être découvert

---

## 3. L'architecture cible : la couche Perspective

### 3a. Principe fondateur

**Les briques sont pré-calculées et persistent dans le KG.
L'assemblage est dynamique, piloté par la question.**

Comme un cerveau humain : la connaissance est structurée en amont (lecture des documents), mais la restitution s'adapte à ce qu'on demande.

### 3b. Qu'est-ce qu'une Perspective ?

Une **Perspective** est le regroupement thématique des claims autour d'un aspect cohérent d'un sujet. C'est l'intersection matérialisée d'un **ComparableSubject** et d'un **groupe de Facets apparentées**.

Exemples concrets :
- Sujet "SAP S/4HANA 2023" × Facets {network.security, authentication.sso, encryption.tls} → **Perspective "Sécurité & Authentification"**
- Sujet "SAP S/4HANA 2023" × Facets {customs.calculation, financial.planning, asset.management} → **Perspective "Capacités fonctionnelles"**
- Sujet "GDPR" (corpus juridique) × Facets {data.retention, consent.management} → **Perspective "Conservation & consentement"**
- Sujet "Molécule X" (corpus médical) × Facets {efficacy.endpoints, adverse.effects} → **Perspective "Efficacité vs effets indésirables"**

**La Perspective n'est PAS un Concept Dossier** : elle ne contient pas de texte généré, pas de résumé. C'est une **structure de regroupement** avec des métriques. Le texte n'est produit qu'au moment de la restitution.

**La Perspective n'est PAS une Facet** : les Facets sont corpus-wide et granulaires. Une Perspective est subject-scoped et regroupe plusieurs Facets apparentées dans le contexte d'un sujet précis.

**La Perspective n'est PAS une section de réponse** : c'est une **brique d'assemblage**. Le LLM de synthèse est libre de fusionner des Perspectives, d'en éclater une en sous-axes, ou de réorganiser les preuves selon un angle différent de celui des Perspectives. Les Perspectives structurent les preuves en amont ; le LLM compose la réponse en aval. La même question "migration depuis ECC" peut piocher dans les Perspectives "Compatibilité", "Fonctionnalités" et "Sécurité" pour recomposer des axes "Prérequis", "Breaking changes" et "Gains" qui n'existent pas comme Perspectives mais émergent de leur croisement.

### 3c. Pourquoi matérialiser plutôt que calculer à la volée ?

| Critère | À la volée | Matérialisé |
|---------|-----------|-------------|
| Reproductibilité | ❌ Varie à chaque appel | ✅ Stable |
| Latence | ❌ Clustering + LLM à chaque question | ✅ Lookup Neo4j ~5ms |
| Dual-use (chat + Atlas) | ❌ Chat seulement | ✅ Les deux |
| Cumul (métriques, évolutions) | ❌ Impossible | ✅ Métriques pré-calculées |
| Fraîcheur | ✅ Toujours à jour | ⚠️ Update incrémental nécessaire |
| Volume | N/A | ✅ ~90 nœuds (15 sujets × 6 perspectives) |

Le volume est trivial (~90 nœuds). Le gain est massif. La fraîcheur est gérable par update incrémental.

---

## 4. Modèle de données

### 4a. Nœud Perspective

```
(:Perspective {
    perspective_id: str,              # UUID
    tenant_id: str,
    subject_id: str,                  # → ComparableSubject.subject_id
    
    # Label découvert (LLM, domain-agnostic)
    label: str,                       # Ex: "Sécurité & Authentification"
    description: str,                 # 1-2 phrases descriptives
    negative_boundary: str,           # Ce que cette Perspective n'est PAS
    keywords: [str],                  # 5-8 mots-clés pour matching
    
    # Métriques
    claim_count: int,                 # Nombre de claims dans cette Perspective
    doc_count: int,                   # Nombre de documents sources distincts
    tension_count: int,               # Tensions internes (CONTRADICTS/REFINES)
    coverage_ratio: float,            # % des claims du sujet couverts par cette Perspective
    importance_score: float,          # Score d'importance composite
    
    # Facets sources
    source_facet_ids: [str],          # Facets regroupées dans cette Perspective
    
    # Claims représentatifs (pour scoring rapide)
    representative_claim_ids: [str],  # Top 5-7 claims les plus importants
    representative_texts: [str],      # Leurs textes (pour embedding sans traversal)
    
    # Embedding (pour scoring vs question)
    embedding: [float],               # Calculé depuis label + keywords + representative_texts
    
    # Évolution cross-version (pré-calculé)
    evolution_summary: str,           # "TLS 1.2 recommandé → requis", vide si pas d'évolution
    added_claim_count: int,           # Claims ajoutés vs version précédente
    removed_claim_count: int,         # Claims absents vs version précédente
    changed_claim_count: int,         # Claims avec valeurs modifiées
    
    # Métadonnées
    created_at: datetime,
    updated_at: datetime,
    build_method: str,                # "facet_clustering" | "incremental"
})
```

### 4b. Relations

```
(ComparableSubject)-[:HAS_PERSPECTIVE]->(Perspective)
(Perspective)-[:INCLUDES_CLAIM]->(Claim)
(Perspective)-[:SPANS_FACET]->(Facet)            # N:M — une Perspective regroupe plusieurs Facets
(Perspective)-[:EVOLVES_FROM]->(Perspective)      # Cross-version (même sujet, axes différents)
```

**Pas de nouveau type de nœud** hormis Perspective. On réutilise entièrement les nœuds existants (ComparableSubject, Claim, Facet).

### 4c. Raccourci de performance

Aujourd'hui, ComparableSubject → Claim nécessite 4 hops (ComparableSubject → DocumentContext → Document → Claim). Le nœud Perspective offre un raccourci :

```
(ComparableSubject)-[:HAS_PERSPECTIVE]->(Perspective)-[:INCLUDES_CLAIM]->(Claim)
```

2 hops au lieu de 4 pour obtenir les claims d'un sujet, groupés par thème.

---

## 5. Pipeline de construction (batch, à l'ingestion)

### 5a. Déclenchement

Après chaque ingestion de document, si le document est lié à un ComparableSubject qui a ≥ 10 claims au total.

### 5b. Algorithme

```
Pour chaque ComparableSubject éligible :

1. COLLECTE
   - Traverser ComparableSubject → DocumentContext → Document → Claims
   - Pour chaque claim, charger ses Facets (BELONGS_TO_FACET)
   - Résultat : liste de (claim, [facet_ids])

2. REGROUPEMENT PAR FACETS
   - Construire une matrice claim × facet (binaire)
   - Ajouter les embeddings des claims comme features complémentaires
   - Résultat : vecteur composite par claim (facet membership + sémantique)

3. CLUSTERING AGGLOMÉRATIF
   - Clustering hiérarchique sur les vecteurs composites
   - Cible : 4-8 clusters (adaptatif selon nombre de claims)
     - < 30 claims → 3-4 clusters
     - 30-100 claims → 4-6 clusters
     - > 100 claims → 5-8 clusters
   - Seuil de merge : cosine distance < 0.4 entre centroids
   - Claims sans facet (orphelins) : assigner au cluster le plus proche par embedding

4. FILTRAGE QUALITÉ
   - Cluster < 3 claims → fusionner avec le plus proche
   - Cluster avec 1 seul document source → flaguer "couverture faible"
   - Cluster dont > 80% des claims viennent d'un seul doc → flaguer "concentration"

5. LABELLISATION (LLM, 1 appel par Perspective)
   Input : top 7 claims du cluster + facets associées
   Output : {label, description, negative_boundary, keywords}
   Contrainte LLM : "Décris ce groupe thématique sans référence à un domaine métier spécifique"
   
6. MÉTRIQUES
   - claim_count, doc_count (diversité)
   - tension_count : compter les CONTRADICTS/REFINES entre claims de cette Perspective
   - coverage_ratio : claim_count / total_claims_du_sujet
   - importance_score : f(claim_count, doc_count, tension_count, diversity)
   
7. EMBEDDING
   - Concaténer : label + keywords + top 3 representative_texts
   - Encoder via le même modèle d'embedding qu'Qdrant (E5-large)
   
8. ÉVOLUTION CROSS-VERSION
   Pour les sujets avec ApplicabilityAxis ordonnables :
   a. Matcher les Perspectives de version N avec version N-1
      - Par similarity d'embedding entre Perspectives (seuil 0.7)
      - Par overlap de facets sources (Jaccard > 0.5)
   b. Pour chaque paire matchée :
      - Claims dans N mais pas dans N-1 → added_count
      - Claims dans N-1 mais pas dans N → removed_count
      - Claims similaires avec valeurs différentes → changed_count
      - Résumé d'évolution via LLM (1 appel par paire)
   c. Créer relation EVOLVES_FROM

9. PERSISTANCE
   - Créer/mettre à jour les nœuds Perspective dans Neo4j
   - Créer les relations HAS_PERSPECTIVE, INCLUDES_CLAIM, SPANS_FACET, EVOLVES_FROM
```

### 5c. Update incrémental

Quand un nouveau document est ingéré :

```
1. Identifier les ComparableSubjects affectés
2. Pour chaque sujet affecté :
   a. Charger les Perspectives existantes
   b. Pour chaque nouveau claim :
      - Calculer son embedding
      - Scorer contre chaque Perspective existante (embedding + facet overlap)
      - Si score > 0.6 → ajouter à la Perspective
      - Sinon → accumuler dans un buffer "orphelins"
   c. Si buffer orphelins ≥ 3 claims → créer une nouvelle Perspective
   d. Si une Perspective a grossi de > 50% → re-valider le label
   e. Recalculer les métriques
```

---

## 6. Pipeline de réponse (runtime, à la question)

### 6a. Détection : quand activer le mode Perspective ?

La question clé : comment distinguer une question ouverte (qui bénéficie des Perspectives) d'une question directe (qui n'en a pas besoin) ?

**Heuristique composite (pas de LLM nécessaire)** :

```python
def should_activate_perspectives(
    question: str,
    reranked_chunks: list[dict],
    kg_claims: list[dict],
    subject_ids: list[str],
) -> bool:
    """Détecte si la question est ouverte/panoramique."""
    
    # Condition 1 : un sujet identifiable avec des Perspectives
    if not subject_ids:
        return False
    perspectives_exist = check_perspectives_exist(subject_ids)
    if not perspectives_exist:
        return False
    
    # Condition 2 : dispersion des chunks sur plusieurs facets
    # Si les top chunks couvrent ≥ 4 facets distinctes, la question est probablement ouverte
    facet_ids = set()
    for chunk in reranked_chunks[:10]:
        for claim in kg_claims:
            if claim.get("source_file") == chunk.get("source_file"):
                facet_ids.update(claim.get("facet_ids", []))
    facet_diversity = len(facet_ids)
    
    # Condition 3 : patterns linguistiques (légers, sans LLM)
    open_patterns = [
        "qu'apporte", "que propose", "quoi de neuf", "what's new",
        "vue d'ensemble", "overview", "résumé", "summary",
        "quels sont les", "what are the", "décrivez", "describe",
        "différences entre", "compare", "évolution",
        "tout savoir sur", "tell me about", "expliquez",
    ]
    has_open_pattern = any(p in question.lower() for p in open_patterns)
    
    # Activation si : sujet connu + (dispersion ≥ 4 facets OU pattern ouvert)
    return facet_diversity >= 4 or has_open_pattern
```

**Note** : les patterns linguistiques sont cross-domain (pas de termes métier). Ils détectent la **forme** de la question, pas le **sujet**.

### 6b. Nouveau ResponseMode : PERSPECTIVE

Intégration dans le système V3 existant :

```python
class ResponseMode(str, Enum):
    DIRECT = "DIRECT"
    AUGMENTED = "AUGMENTED"
    TENSION = "TENSION"
    STRUCTURED_FACT = "STRUCTURED_FACT"
    PERSPECTIVE = "PERSPECTIVE"          # NOUVEAU
```

**Stage A** (signal_policy.py) — Candidature :
- Condition : `should_activate_perspectives()` retourne True
- Confidence : proportionnelle à facet_diversity

**Stage B** (validation par KG trust) :
- Au moins 2 Perspectives scorent > 0.3 contre la question
- Les Perspectives sélectionnées couvrent ≥ 50% des claims du sujet
- Fallback → DIRECT si les conditions ne sont pas remplies

### 6c. Assemblage des Perspectives au runtime

```python
async def assemble_perspective_context(
    question: str,
    question_embedding: list[float],
    subject_ids: list[str],
    reranked_chunks: list[dict],
    kg_claims: list[dict],
    tenant_id: str,
) -> str:
    """Assemble le contexte Perspective pour la synthèse.
    
    Returns:
        Markdown structuré par axes thématiques.
    """
    # 1. Charger les Perspectives des sujets identifiés
    perspectives = load_perspectives(subject_ids, tenant_id)
    
    # 2. Scorer chaque Perspective contre la question (multi-signaux, pas juste cosine)
    for p in perspectives:
        semantic_score = cosine_similarity(question_embedding, p.embedding)
        tension_bonus = 0.15 if p.tension_count > 0 else 0.0
        evolution_bonus = 0.10 if p.added_claim_count > 0 or p.changed_claim_count > 0 else 0.0
        diversity_bonus = 0.10 if p.doc_count >= 3 else 0.0
        coverage_weight = p.coverage_ratio * 0.20  # Perspectives larges = plus de contexte
        p.relevance_score = semantic_score + tension_bonus + evolution_bonus + diversity_bonus + coverage_weight
    
    # 2b. Keyword overlap bonus (alignement question-intent)
    question_terms = extract_key_terms(question)  # acronymes, termes techniques, mots-clés
    for p in perspectives:
        # Compter combien de termes de la question apparaissent dans les representative_texts
        matching_terms = sum(
            1 for term in question_terms
            if any(term.lower() in rt.lower() for rt in p.representative_texts)
        )
        p.relevance_score += 0.10 * min(matching_terms, 3)  # max +0.30
    
    # 3. Sélectionner les top 3-5 (pas plus, pour éviter la surcharge cognitive du LLM)
    #    - Toujours garder celles avec tensions (même si score faible)
    #    - Toujours garder celles avec évolution (même si score faible)
    #    - Max 5-8 claims par Perspective dans le prompt (les plus importants)
    selected = select_perspectives(perspectives, min=3, max=5)
    
    # 4. Pour chaque Perspective sélectionnée, charger les claims
    for p in selected:
        p.claims = load_claims_for_perspective(p.perspective_id)
        p.tensions = load_tensions_for_perspective(p.perspective_id)
    
    # 5. Dériver les indices de structuration (heuristiques, sans LLM)
    hints = derive_structuring_hints(question, selected)
    
    # 6. Construire le prompt structuré (Perspectives + hints + consigne)
    return build_perspective_prompt(question, selected, reranked_chunks, hints)
```

### 6d. Indices de structuration (heuristiques, sans LLM)

Avant de construire le prompt, on dérive algorithmiquement des **hints** à partir des métadonnées des Perspectives sélectionnées. Ces hints aident le LLM à recomposer les axes sans qu'on lui impose une structure rigide.

```python
def derive_structuring_hints(question: str, perspectives: list) -> list[str]:
    """Dérive des indices de structuration à partir des métadonnées Perspectives.
    
    Pas d'appel LLM. Règles déterministes sur les métadonnées.
    """
    hints = []
    q_lower = question.lower()
    
    # Hint cross-version si les Perspectives couvrent plusieurs versions
    has_evolution = any(p.evolution_summary for p in perspectives)
    if has_evolution:
        hints.append("Certains éléments ont évolué entre versions — distinguez ce qui est nouveau, modifié ou inchangé.")
    
    # Hint tensions si des Perspectives contiennent des tensions
    tension_perspectives = [p for p in perspectives if p.tension_count > 0]
    if tension_perspectives:
        hints.append("Des positions divergentes existent entre sources sur certains points — présentez-les explicitement.")
    
    # Hint migration si le mot apparaît dans la question
    if any(w in q_lower for w in ["migr", "transition", "passage", "upgrade"]):
        hints.append("Distinguez les prérequis, les changements de comportement et les impacts.")
    
    # Hint comparaison si la question compare
    if any(w in q_lower for w in ["compar", "différence", "vs", "entre"]):
        hints.append("Structurez autour des dimensions comparées, pas des sources.")
    
    # Hint sécurité/conformité si la question cible un domaine
    # Note : pas de termes métier ici — on détecte la FORME, pas le DOMAINE
    if any(w in q_lower for w in ["risque", "risk", "impact", "conséquence", "consequence"]):
        hints.append("Distinguez les éléments critiques des éléments secondaires.")
    
    return hints
```

### 6e. Limites de complexité du prompt

Pour éviter la surcharge cognitive du LLM :

| Paramètre | Limite | Raison |
|-----------|--------|--------|
| Perspectives dans le prompt | 3-5 max | Au-delà, le LLM ne recompose plus efficacement |
| Claims par Perspective | 5-8 max | Les plus importants (par confidence + mention_count) |
| Total claims dans le prompt | ~25-40 | Zone optimale pour Haiku 4.5 |
| Hints de structuration | 2-3 max | Trop de hints = contradiction |

Si une Perspective a 20 claims, on n'en injecte que les 5-8 les plus représentatifs. Les métriques (claim_count, doc_count, tension_count) donnent au LLM l'image complète sans charger tous les claims.

### 6f. Le prompt structuré

C'est ici que tout se joue. Le LLM ne reçoit plus une soupe, mais un document structuré :

```markdown
## Sujet identifié : SAP S/4HANA 2023

### Axe 1 : Sécurité & Authentification
*14 faits issus de 4 documents (Security Guide 2023, Security Guide 2022, Feature Scope 2023, Architecture Guide)*

**Faits clés :**
- "TLS 1.2 is required for all inbound and outbound network connections" — Security Guide 2023
- "SNC protects RFC and DIAG connections with encryption" — Security Guide 2023
- "SSO mechanisms provided by Application Server ABAP technology" — Security Guide 2023
- "Authorization object S_PROGRAM based on report RPCIPD00" — Security Guide 2023

**Tension détectée :**
- Security Guide 2022 recommande TLS 1.2, Security Guide 2023 l'exige → renforcement

**Évolution vs version précédente :**
- TLS 1.2 : recommandé → requis
- 3 nouveaux objets d'autorisation ajoutés

---

### Axe 2 : Capacités fonctionnelles
*22 faits issus de 3 documents (Feature Scope 2023, Feature Scope 2022, Cloud Private Edition)*

**Faits clés :**
- "Automatic calculation of customs duties and tariffs" — Feature Scope 2023
- "Integrated financial planning part of supported business processes" — Feature Scope 2023
- "Asset Management integrated with SAP APM" — Feature Scope 2023

**Évolution vs version précédente :**
- Calcul douanier automatique : nouveau en 2023
- Planification financière : étendue en 2023

---

### Axe 3 : Compatibilité technique
*8 faits issus de 5 documents*

**Faits clés :**
- "Requires SAP HANA database" — Feature Scope 2023
- "Based on ABAP platform" — Security Guide 2023

---

### Zones non couvertes par le corpus
- Pricing / coûts de licence (aucune information)
- Benchmarks de performance (aucune information)
- Chemin de migration depuis ECC (non documenté dans le corpus actuel)

### Indices de structuration
- Certains éléments ont évolué entre versions — distinguez ce qui est nouveau, modifié ou inchangé.
- Des positions divergentes existent entre sources sur certains points — présentez-les explicitement.

---

**Consigne** : Les axes ci-dessus organisent les preuves par thème — utilise-les
comme matière première, pas comme plan imposé. Tu peux restructurer, fusionner ou
éclater les axes selon ce qui répond le mieux à la question posée.

Règles de structuration :
- Tes axes de réponse doivent être mutuellement exclusifs (pas de recouvrement) et couvrir l'ensemble des éléments pertinents
- Priorise les axes les plus importants pour la question, pas ceux qui ont le plus de faits
- Organise dans un ordre logique pour un lecteur humain (du plus structurant au plus détaillé)
- Pour chaque axe, appuie-toi sur les faits clés et les évolutions fournis
- Mentionne les tensions si pertinent
- Signale les zones non couvertes en fin de réponse
- Ne génère AUCUNE information qui ne soit pas dans les faits ci-dessus
```

### 6g. Ce que le LLM reçoit vs aujourd'hui

| Aujourd'hui | Avec Perspectives |
|-------------|-------------------|
| 10-18 chunks en liste plate non organisée | 10-18 chunks **groupés par axe thématique** |
| 0-80 tokens d'instructions procédurales KG (modes DIRECT/AUGMENTED = 0, TENSION = 2-3 lignes) | ~1500-3000 tokens de contexte structuré (axes, faits clés, tensions **par axe**, évolutions, blind spots) |
| Le KG élargit les preuves mais ne les organise pas | Le KG élargit les preuves **ET** les organise |
| Le LLM doit deviner la structure de sa réponse | Le LLM **reçoit** la structure |
| Pas de notion d'évolution cross-version | Évolutions pré-calculées et injectées par axe |
| Pas de blind spots | Zones non couvertes identifiées |

**Note** : c'est un changement de paradigme par rapport à INV-ARCH-06 ("le KG diagnostique, il ne raconte pas"). Avec les Perspectives, le KG ne "raconte" toujours pas (les textes viennent des claims verbatim), mais il **structure** — ce qu'il ne fait pas aujourd'hui. L'invariant est respecté dans l'esprit (pas de contenu narratif généré par le KG) mais étendu (le KG fournit un plan d'organisation des preuves).

---

## 7. Pourquoi pas de "PerspectiveComposer" algorithmique

Une critique légitime de cette architecture est : "les Perspectives sont des briques figées, il faut un composant qui les recompose dynamiquement selon la question". L'alternative serait un `PerspectiveComposer` algorithmique qui fusionne, découpe et réordonne les Perspectives avant de les envoyer au LLM.

**Nous choisissons délibérément de ne PAS ajouter cette couche.** Voici pourquoi :

1. **Le LLM de synthèse EST le composer.** Haiku est parfaitement capable de recevoir des preuves groupées par axes thématiques et de les réorganiser selon l'angle de la question. C'est même sa compétence première. Ajouter un algorithme intermédiaire pour faire ce que le LLM fait mieux de manière émergente serait de la sur-ingénierie.

2. **Un composer algorithmique réintroduit de la fragilité.** Décider algorithmiquement que "migration" nécessite de fusionner "compatibilité" + "fonctionnalités" est du hardcoding déguisé. Ça casse dès qu'un nouveau type de question apparaît.

3. **Le levier est dans le prompt, pas dans l'architecture.** La consigne de synthèse dit explicitement au LLM que les axes sont de la "matière première" à restructurer, pas un plan imposé. C'est suffisant pour obtenir des réponses adaptées à l'angle de la question.

4. **Cohérence avec INV-ARCH-06.** Le KG structure les preuves (Perspectives), le LLM compose la réponse. Chacun fait ce qu'il fait le mieux.

**Si cette approche s'avère insuffisante** (le LLM ne recompose pas assez bien), la porte reste ouverte pour ajouter un composer léger plus tard — probablement un appel LLM supplémentaire (~1s) qui produit un plan de réponse avant la synthèse. Mais commençons sans, mesurons, puis décidons.

---

## 8. Dual-use : Chat + Atlas

### 8a. Pour le Chat

Le flow est celui décrit en section 6 : détection de question ouverte → chargement des Perspectives pertinentes → prompt structuré → synthèse.

Le LLM reçoit les bonnes preuves groupées par axe et produit une réponse structurée.

### 8b. Pour Atlas

Une page Atlas pour un sujet affiche **toutes** ses Perspectives :

```
Page Atlas : SAP S/4HANA 2023
├── Vue d'ensemble (métriques globales, reliability score)
├── Sécurité & Authentification (14 claims, 4 docs, 1 tension)
│   ├── Faits clés
│   ├── Sources
│   └── Évolution vs 2022
├── Capacités fonctionnelles (22 claims, 3 docs)
│   ├── Faits clés
│   └── Évolution vs 2022
├── Compatibilité technique (8 claims, 5 docs)
├── Intégrations (11 claims, 3 docs)
└── Zones non couvertes
```

C'est le même objet (Perspective), simplement affiché en entier au lieu d'être filtré par la question.

### 8c. Pour Verify

La vérification de documents (le flow qu'on vient de modifier) peut aussi bénéficier des Perspectives : quand on vérifie une assertion, au lieu de chercher dans tout le corpus, on peut d'abord identifier la Perspective pertinente et restreindre la recherche.

---

## 9. Domain-agnosticism

### 9a. Aucun terme métier dans l'architecture

Les Perspectives sont découvertes, pas définies :
- Les labels viennent du LLM à partir des claims réels
- Les regroupements viennent du clustering (Facets + embeddings)
- Les métriques sont structurelles (claim_count, doc_count, tension_count)
- Les patterns de détection sont linguistiques, pas thématiques

### 9b. Exemples cross-domain

| Corpus | Sujet | Perspectives probables |
|--------|-------|----------------------|
| SAP/IT | S/4HANA 2023 | Sécurité, Fonctionnalités, Compatibilité, Intégrations |
| Médical | Molécule X | Efficacité clinique, Effets indésirables, Posologie, Populations, Méthodologie |
| Juridique | RGPD | Droits des personnes, Obligations du responsable, Sanctions, Transferts internationaux |
| Automobile | Modèle Y 2025 | Motorisation, Sécurité active/passive, Connectivité, Homologation |

Dans chaque cas, les Perspectives émergent des claims et des Facets du corpus — pas d'un catalogue métier.

### 9c. Invariants respectés

| Invariant OSMOSIS | Compatibilité Perspective |
|-------------------|--------------------------|
| INV-3 (Claim mono-document) | ✅ Perspectives regroupent des claims de plusieurs docs, mais chaque claim garde sa provenance |
| INV-6 (Abstention si doute) | ✅ Fallback DIRECT si pas assez de Perspectives, pas de Perspective créée si < 3 claims |
| INV-8 (Scope au Document) | ✅ La Perspective est liée au ComparableSubject, pas au Document. Les claims héritent le scope via leur Document |
| INV-9 (Subject resolution conservative) | ✅ On réutilise les ComparableSubjects existants, pas de nouveau mécanisme de résolution |
| INV-10 (Discriminants discovered) | ✅ Labels, regroupements, métriques : tout est découvert, rien n'est hardcodé |

---

## 10. Interaction avec les Response Modes existants

### 10a. Priorité des modes

```
Détection signal → candidature mode :

1. TENSION (priorité haute)   — si tension forte + paired evidence
2. PERSPECTIVE (priorité moyenne) — si question ouverte + sujet avec perspectives
3. STRUCTURED_FACT            — si question sur valeurs exactes
4. AUGMENTED                  — si KG guide le retrieval sans narratif
5. DIRECT (défaut)            — RAG pur

Note : TENSION peut coexister avec PERSPECTIVE.
Si question ouverte ET tensions fortes → mode PERSPECTIVE avec tension_disclosure activé.
```

### 10b. Coexistence PERSPECTIVE + TENSION

Quand les deux modes sont pertinents (question ouverte avec des tensions détectées), le mode PERSPECTIVE intègre les tensions **dans chaque axe** plutôt qu'en bloc séparé. C'est plus naturel : la tension TLS 1.2 vs 1.3 apparaît dans l'axe "Sécurité", pas dans un bloc "Tensions" générique.

### 10c. Condition de fallback

```
PERSPECTIVE → fallback DIRECT si :
  - Moins de 2 Perspectives scorent > 0.3 contre la question
  - Les Perspectives couvrent < 40% des claims du sujet
  - Le ComparableSubject identifié a < 10 claims au total
  - KG trust score < 0.3
```

---

## 11. Plan d'implémentation

### Phase 1 : Fondations (PerspectiveBuilder batch)

**Nouveaux fichiers :**
- `src/knowbase/perspectives/builder.py` — Construction des Perspectives depuis le KG
- `src/knowbase/perspectives/models.py` — Dataclasses Perspective, PerspectiveSet
- `src/knowbase/perspectives/neo4j_schema.py` — Constraints et indexes Neo4j
- `src/knowbase/perspectives/updater.py` — Update incrémental

**Modification :**
- `src/knowbase/claimfirst/persistence/neo4j_schema.py` — Ajouter le nœud Perspective et ses relations

**Livrable** : Commande `python -m knowbase.perspectives.builder --tenant default` qui construit les Perspectives pour tous les sujets éligibles.

### Phase 2 : Intégration Chat

**Nouveaux fichiers :**
- `src/knowbase/perspectives/scorer.py` — Scoring Perspectives vs question
- `src/knowbase/perspectives/prompt_builder.py` — Construction du prompt structuré

**Modifications :**
- `src/knowbase/api/services/signal_policy.py` — Ajouter ResponseMode.PERSPECTIVE + détection
- `src/knowbase/api/services/search.py` — Insérer l'assemblage Perspective entre expansion et synthèse
- `config/synthesis_prompts.yaml` — Template de prompt PERSPECTIVE

**Livrable** : Le chat utilise les Perspectives quand question ouverte détectée.

### Phase 3 : Intégration Atlas

**Modifications :**
- API endpoints pour servir les Perspectives d'un sujet
- Frontend : page Atlas structurée par Perspectives

### Phase 4 : Évolution cross-version

**Nouveaux fichiers :**
- `src/knowbase/perspectives/evolution.py` — Matching et diff cross-version

**Livrable** : Les Perspectives incluent les données d'évolution.

---

## 12. Métriques de succès

| Métrique | Baseline actuelle | Cible |
|----------|------------------|-------|
| Questions ouvertes avec réponse structurée (vs plate) | ~0% | > 70% |
| Axes thématiques dans les réponses ouvertes | 0-1 | 3-6 |
| Mention d'évolutions cross-version | Rare | Systématique quand applicable |
| Mention de zones non couvertes | Jamais | Systématique |
| Latence additionnelle (mode PERSPECTIVE) | N/A | < 200ms (lookup Neo4j + scoring) |
| Régression questions directes (mode DIRECT) | N/A | 0 (non activé pour questions directes) |

---

## 13. Risques et mitigations

| Risque | Impact | Mitigation |
|--------|--------|------------|
| Perspectives trop génériques (labels vagues) | Moyen | Negative boundary + filtrage qualité (genericité score, cf. facets/clustering.py) |
| Clustering instable (résultats différents à chaque rebuild) | Moyen | Seed fixe + seuils conservateurs + update incrémental plutôt que rebuild total |
| Perspectives stale après ingestion massive | Faible | Update incrémental déclenché automatiquement |
| Surcoût LLM au build (labellisation) | Faible | 1 appel Haiku par Perspective (~90 appels = ~$0.04) |
| Question "ouverte" mal détectée → mode PERSPECTIVE activé à tort | Moyen | Fallback DIRECT si les Perspectives ne scorent pas assez, détection conservative |
| Le LLM ignore la structure fournie et produit quand même du plat | Faible | Template de prompt très directif + post-processing structurel si nécessaire |

---

## 14. Positionnement interne

**Perspective = structure de regroupement persistée, non canonique, révisable, subordonnée aux claims.**

Une Perspective n'est pas une vérité ontologique. C'est un artefact utilitaire, construit à partir des claims et des facets, qui peut être recalculé, scindé ou fusionné sans perte de données. Si toutes les Perspectives d'un sujet étaient supprimées, le KG resterait intact — seule la couche de regroupement serait perdue.

Hiérarchie d'usage :
- **Primaire** : structuration de restitution pour questions ouvertes (chat, mode PERSPECTIVE)
- **Secondaire** : navigation Atlas (pages sujet organisées par axes)
- **Tertiaire** : aide au ciblage pour Verify (restreindre la recherche à la Perspective pertinente)

---

## 15. Gouvernance & Stabilité

### Invariant de stabilité

> Une Perspective existante doit être conservée tant que l'ajout de nouveaux claims ne remet pas substantiellement en cause son identité thématique. En cas de remise en cause, créer une nouvelle Perspective plutôt que remodeler silencieusement l'ancienne.

**Critère de remise en cause** : si > 40% des claims d'une Perspective ont été ajoutés depuis sa dernière labellisation ET que le nouveau centroid a dérivé de > 0.3 en cosine par rapport à l'embedding initial, alors la Perspective est candidate à scission ou relabellisation.

### Règles de gouvernance

| Situation | Action |
|-----------|--------|
| Nouveau claim matche une Perspective existante (score > 0.6) | Ajouter à la Perspective, mettre à jour les métriques |
| Nouveau claim ne matche aucune Perspective | Accumuler dans un buffer. Si buffer ≥ 3 claims → créer nouvelle Perspective |
| Perspective a grossi de > 50% depuis création | Valider que le label est encore pertinent (re-check embedding drift) |
| Perspective n'a plus que < 3 claims (après suppression de documents) | Fusionner avec la plus proche ou supprimer |
| Rebuild complet demandé | Recalculer toutes les Perspectives. Matcher avec les anciennes par embedding similarity. Conserver les IDs des Perspectives stables (drift < 0.2) |

### Versioning des Perspectives

Chaque Perspective porte un `updated_at`. Les pages Atlas et les réponses chat ne sont pas affectées par des mises à jour incrémentales tant que le label et les representative_claims ne changent pas substantiellement.

---

## 16. Instrumentation

### Logs obligatoires (chaque activation du mode PERSPECTIVE)

| Log | Contenu | Usage |
|-----|---------|-------|
| `[PERSPECTIVE:DETECT]` | Question, facet_diversity, has_open_pattern, subject_ids | Évaluer la qualité de la détection |
| `[PERSPECTIVE:SELECT]` | Perspectives sélectionnées (ids, labels, scores), total disponibles | Comprendre la sélection |
| `[PERSPECTIVE:INJECT]` | Nombre de claims injectés par Perspective, nombre de hints, total tokens | Surveiller la charge cognitive |
| `[PERSPECTIVE:FALLBACK]` | Raison du fallback vers DIRECT (si applicable) | Diagnostiquer les faux positifs |
| `[PERSPECTIVE:SYNTHESIS]` | Nombre d'axes dans la réponse, nombre de sources citées | Mesurer la structuration effective |

### Métriques persistées (pour analyse batch)

- `perspective_activation_rate` : % de questions qui activent le mode PERSPECTIVE
- `perspective_fallback_rate` : % d'activations qui tombent en fallback DIRECT
- `perspective_axis_count_avg` : nombre moyen d'axes dans les réponses structurées
- `perspective_coverage_avg` : % moyen de claims du sujet couverts par les Perspectives sélectionnées

La détection "question ouverte" (section 6a) est traitée comme une **heuristique provisoire**. L'instrumentation ci-dessus permet de l'évaluer sur un lot de questions réelles et de l'ajuster sans changer l'architecture.

---

## 17. Validation expérimentale

### Protocole de benchmark avant généralisation

**Objectif** : prouver que le mode PERSPECTIVE améliore la qualité des réponses ouvertes sans régresser sur les questions directes.

**Lot de test** : 30 questions humaines réparties en :
- 15 questions ouvertes (ex: "Qu'apporte la version 2023 ?", "Vue d'ensemble sécurité S/4HANA", "Comparez les éditions Cloud vs On-Premise")
- 15 questions directes (ex: "Quel objet d'autorisation contrôle X ?", "Quelle version de TLS est requise ?")

**Protocole** :
1. Exécuter les 30 questions en mode DIRECT (baseline)
2. Exécuter les 30 questions avec mode PERSPECTIVE activé
3. Évaluer chaque réponse sur 4 dimensions (note 0-3) :

| Dimension | 0 | 1 | 2 | 3 |
|-----------|---|---|---|---|
| **Structure utile** | Liste plate | Quelques regroupements | Axes clairs | Axes clairs + logiques |
| **Fidélité aux preuves** | Hallucinations | Quelques inventions | Fidèle avec imprécisions | Strictement fidèle |
| **Couverture** | Manque des axes majeurs | Couverture partielle | Bon mais manque 1 axe | Complète |
| **Stabilité inter-runs** | Différent à chaque fois | Structure varie, contenu stable | Minor variations | Reproductible |

**Critères de validation** :
- Questions ouvertes : score moyen ≥ 2.0 sur les 4 dimensions (vs baseline)
- Questions directes : aucune régression (score ≥ baseline sur chaque dimension)
- Stabilité : sur 3 runs de la même question, structure identique dans ≥ 80% des cas

**Critères de rejet** :
- Si le mode PERSPECTIVE dégrade les questions directes → bug de détection, corriger avant re-test
- Si la stabilité < 60% → les hints sont insuffisants, ajouter des contraintes
- Si la fidélité aux preuves baisse → le prompt laisse trop de liberté au LLM, resserrer

Ce benchmark doit être exécuté **avant** de considérer l'architecture comme validée en production.

---

## 18. Ce que cette architecture ne fait PAS

- **Pas de taxonomie de questions** : la détection est linguistique + structurelle, pas thématique
- **Pas de résumés pré-générés** : les Perspectives sont des structures, pas du contenu
- **Pas de modification du retrieval existant** : le RAG + KG expansion reste identique. Les Perspectives interviennent APRÈS
- **Pas de nouveau pipeline d'ingestion** : les Perspectives sont construites à partir des claims et facets existants
- **Pas de rupture avec l'architecture V3** : les Perspectives s'ajoutent comme un 5e ResponseMode, avec le même pattern (Stage A candidature → Stage B validation → fallback DIRECT)
