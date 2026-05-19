# [futur] Retrieval par décomposition de requête (Query Decomposition)

*Document de réflexion architecturale, avril 2026. Rédigé après une journée de debug sur la régression `temporal_evolution` dans Robustness, qui a révélé que le fix `ComparableSubject` + propagation des `AxisValues` dans Qdrant ne suffit pas seul à répondre correctement aux questions de comparaison cross-version — il manque un composant en amont du retrieval.*

---

## 1. Problème

### Symptôme empirique

Sur une question type *"Quelles sont les différences dans la description des permissions d'accès entre la version 2022 et 2023 du Guide de Sécurité SAP ?"*, le retrieval actuel d'OSMOSIS retourne :

```
Distribution axis_release_id (12 chunks retrieved):
    4 × FPS03
    4 × 2023
    3 × 2025
    1 × None

Zéro chunk release_id=2022.
```

Alors que le `028_SAP_S4HANA_2022_Security_Guide` est bien dans le corpus et que son `axis_release_id=2022` est correctement propagé dans Qdrant (après le fix `resolve_subjects.py` de ce matin).

Le `strategy_analyzer` a pourtant bien **détecté** la nature cross-version de la question :

```json
{
  "resolved_mode": "PERSPECTIVE",
  "reason": "llm_strategy: The question explicitly asks for a comparison
             between two versions (2022 vs 2023)",
  "kg_trust_score": 0.87
}
```

**Mais cette détection reste narrative — elle n'est pas exploitée comme une contrainte structurelle du retrieval.** Le pipeline passe la question entière à un retrieval sémantique qui, via rerank, juge que les chunks 2023/FPS03/2025 sont plus pertinents que ceux de 2022, probablement parce qu'ils contiennent un vocabulaire plus riche ou plus proche de la formulation de la question.

### Cause architecturale

Le retrieval actuel est **mono-requête + filtrage optionnel** :
- Une seule requête sémantique envoyée à Qdrant + rerank
- Filtrages possibles : `axis_release_id` (via `use_latest`), `tenant_id`, types de chunks
- **Aucune logique pour imposer *"retourner N chunks par valeur d'axis distinct"***

Pour une question de comparaison, cette architecture ne peut pas garantir la couverture des deux côtés comparés.

---

## 2. Solution proposée : Query Decomposition

### Principe

Plutôt que d'envoyer la question complète à un seul retrieval, **décomposer la question en sous-questions indépendantes** via un LLM, **lancer un retrieval par sous-question**, puis **réconcilier les résultats** dans un contexte structuré pour le LLM de synthèse.

C'est un pattern bien connu en RAG moderne, nommé selon les variantes :
- **Self-Ask with Search** (Press et al., 2022)
- **IRCoT — Interleaving Retrieval with Chain-of-Thought** (Trivedi et al., 2022)
- **Sub-question Decomposition** (LlamaIndex, LangChain)
- **Least-to-Most Prompting** (Zhou et al., 2022)

OSMOSIS n'implémente actuellement aucune de ces techniques. Le chantier consiste à en ajouter une, adaptée à nos contraintes (domain-agnostic, multilingue, exploitable avec les `ComparableSubject` + `AxisValue` du KG).

### Exemple concret

```
Question utilisateur :
  "Quelles sont les différences entre Security Guide 2022 et 2023 ?"
                              ↓
[Query Decomposer — 1 appel LLM]
                              ↓
QueryPlan :
  {
    "type": "comparison",
    "sub_queries": [
      {
        "id": "q1",
        "text": "Que dit le Security Guide 2022 sur les règles de sécurité ?",
        "scope_filter": { "axis_release_id": "2022" }
      },
      {
        "id": "q2",
        "text": "Que dit le Security Guide 2023 sur les règles de sécurité ?",
        "scope_filter": { "axis_release_id": "2023" }
      }
    ],
    "synthesis_strategy": "compare"
  }
                              ↓
[Retrieval parallèle — N appels à /api/search]
                              ↓
Chunks groupés par sub_query :
  === Chunks pour q1 (axis_release_id=2022) ===
  [chunks du doc 028...]
  === Chunks pour q2 (axis_release_id=2023) ===
  [chunks du doc 027...]
                              ↓
[Context Assembler — structure le prompt]
                              ↓
Prompt LLM synthèse :
  "Voici des extraits groupés par version.
   Compare les deux versions sur les points pertinents.

   === Security Guide 2022 ===
   [chunks...]

   === Security Guide 2023 ===
   [chunks...]"
                              ↓
[Synthesizer LLM — réponse comparative structurée]
```

### Architecture proposée

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. Question utilisateur                                           │
└──────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│ 2. QueryDecomposer (nouveau composant)                            │
│    Input  : question + contexte disponible du KG                  │
│             (liste des ComparableSubject et AxisValues connus)    │
│    Output : QueryPlan typé                                        │
│              - type : comparison | enumeration | simple | …       │
│              - sub_queries : list[SubQuery]                       │
│              - synthesis_strategy : hint pour le synthesizer      │
│                                                                   │
│    Note : le decomposer est un LLM. Il connait les axis du KG     │
│    pour proposer des filtres scope_filter precis, mais reste      │
│    domain-agnostic (aucune liste hardcodee).                      │
└──────────────────────────────────────────────────────────────────┘
                                ↓
                ┌───────────────┴────────────────┐
                ↓                                ↓
┌─────────────────────────┐       ┌─────────────────────────┐
│ 3a. Retrieval sub_q1    │  ...  │ 3n. Retrieval sub_qN    │
│     /api/search         │       │     /api/search         │
│     avec scope_filter   │       │     avec scope_filter   │
└─────────────────────────┘       └─────────────────────────┘
                ↓                                ↓
                └───────────────┬────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│ 4. Context Assembler                                              │
│    - Groupe les chunks par sub_query                              │
│    - Construit un prompt structure qui marque clairement les      │
│      sous-groupes au LLM de synthese                              │
│    - Dedup inter-subqueries si necessaire                         │
└──────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│ 5. Synthesizer (adapte)                                           │
│    - Prompt conditionne par synthesis_strategy :                  │
│      - compare : "compare les groupes ci-dessus point par point"  │
│      - enumeration : "agrege les elements des groupes"            │
│      - chronological : "organise les groupes par ordre temporel"  │
│      - simple : prompt actuel                                     │
└──────────────────────────────────────────────────────────────────┘
```

### Types de décomposition couverts

Une fois qu'on a un `QueryDecomposer`, on peut couvrir plusieurs classes de questions qui sont actuellement mal servies :

| Type | Exemple | Décomposition |
|---|---|---|
| **comparison** | *"Différences entre A et B"* | 2 sub-queries, une par élément, synthèse compare |
| **comparison_n** | *"Compare A, B, C"* | N sub-queries, synthèse compare N-way |
| **enumeration** | *"Liste tous les X du corpus"* | 1 sub-query par valeur d'axe connue, aggrégation |
| **chronological** | *"Evolution de X depuis 2020"* | Sub-queries par année, synthèse chronologique |
| **multi_hop** | *"Qui a acheté la société qui a inventé X ?"* | Séquentiel : Q1 résout → Q2 conditionnée sur la réponse Q1 |
| **causal_decomposition** | *"Pourquoi X implique Y ?"* | 3 sub-queries : *"qu'est-ce que X"*, *"qu'est-ce que Y"*, *"quel lien X/Y"* |
| **perspective** | *"Comment différents acteurs voient le projet ?"* | Sub-queries par acteur/persona si connus, sinon fallback |
| **simple** | *"Quelle est la règle de sécurité pour le login ?"* | Pas de décomposition, retrieval direct |
| **clarification_needed** | *"Compare la version 2022 et 2024"* (et 2024 n'existe pas dans le corpus) | Pas de retrieval. Réponse de clarification avec alternatives valides. Voir section 4bis pour le détail du pattern |

**Note importante** : la distinction entre `simple` et les autres types est la décision critique du `QueryDecomposer`. Sur-décomposer une question simple ajoute du coût et de la latence sans gain. Sous-décomposer une question complexe manque l'opportunité. Le prompt du decomposer doit être **conservateur par défaut** et ne décomposer que si le signal est clair.

---

## 3. Invariants cross-domain

**Ce pattern est intrinsèquement domain-agnostic.** Aucun code ne doit contenir de connaissance SAP, médicale, juridique ou autre. Preuve mentale sur quatre domaines :

| Domaine | Exemple question | Décomposition générique |
|---|---|---|
| **SAP** | *"Différences Security Guide 2022 vs 2023 ?"* | `axis_release_id=2022` et `axis_release_id=2023` |
| **Clinique** | *"Différences entre Phase 2 et Phase 3 du protocole BNT162b2 ?"* | `axis_status=Phase 2` et `axis_status=Phase 3` |
| **Juridique** | *"Différences entre Loi Hadopi 1 et 2 ?"* | `axis_revision=1` et `axis_revision=2` |
| **Marketing** | *"Compare la campagne été et hiver 2024 ?"* | `axis_temporal=été 2024` et `axis_temporal=hiver 2024` |

**Le `QueryDecomposer` LLM peut déduire la décomposition** pour tous ces cas parce qu'il s'appuie uniquement sur :
1. Le texte de la question (multilingue par nature)
2. Les `discriminating_role` génériques d'OSMOSIS (`temporal`, `revision`, `geographic`, `applicability_scope`, `status`)
3. Éventuellement la liste des `AxisValues` déjà connus dans le corpus pour proposer des filtres précis

**Garde-fous cross-domain à respecter lors de l'implémentation** :

1. **Jamais de `if axis == "release_id"`** — toujours itérer sur les `discriminating_role` génériques
2. **Zero liste de mots hardcodée** dans le decomposer — la détection passe par le LLM
3. **Les domain packs peuvent enrichir** le prompt du decomposer (ex: *"dans ce domaine, les axes courants sont…"*) mais pas le remplacer
4. **Tester sur au moins 2 domaines** avant de considérer le chantier "fait" — un petit corpus clinique ou juridique de 10 docs suffit pour validation cross-domain

---

## 4. Place des AxisValues dans cette nouvelle architecture

*Question posée par l'utilisateur pendant la réflexion : "Je me pose la question de l'utilité des AxisValues si la recherche sémantique peut faire le job via la décomposition."*

**Les AxisValues restent utiles même avec la Query Decomposition**, pour plusieurs raisons :

### a) Ils aident le QueryDecomposer à produire des sous-questions précises

Quand le decomposer reçoit *"compare S/4HANA 2022 et 2023"*, il peut interroger le KG :
```cypher
MATCH (dc:DocumentContext)-[:ABOUT_COMPARABLE]->(cs:ComparableSubject)
WHERE cs.canonical_name = "SAP S/4HANA"
RETURN DISTINCT dc.qualifiers_json
```

Et obtenir la liste des `release_id` qui **existent réellement** dans le corpus : `["2021", "2022", "2023", "2025"]`. Il peut alors :
- Vérifier que "2022" et "2023" sont bien présents → générer les 2 sub-queries
- Remarquer que "2020" n'existe pas → reformuler ou abstain

Sans les AxisValues, le decomposer **propose des sub-queries pour des versions qui n'existent pas** dans le corpus, et le retrieval revient vide.

### b) Ils permettent le `scope_filter` structurel

Une sub-query avec `scope_filter: {axis_release_id: "2022"}` est **beaucoup plus précise** qu'une sub-query purement sémantique. Le retrieval peut d'abord filtrer Qdrant par axis, puis rerank sémantique sur le sous-ensemble — garantie de couverture.

Sans les AxisValues :
- La sub-query *"que dit le Security Guide 2022 sur la sécurité ?"* est purement sémantique
- Le rerank peut échouer à matcher les chunks 2022 (exactement le bug qu'on vient de constater)
- Le retrieval revient avec des chunks 2023, 2025, etc.

### c) Ils débloquent les agrégations et diagnostics

Des requêtes structurelles sur le KG dépendent des AxisValues :
- *"Combien de docs avons-nous pour chaque version du produit X ?"*
- *"Quels sont les axes de comparaison déjà couverts pour ce corpus ?"*
- *"Le dernier doc sur Y date de quand ?"* (`use_latest`)
- *"Montre-moi la matrice subject × version pour l'Atlas narratif"*

Ces analyses sont **impossibles sans AxisValues structurés**, ou alors demandent un re-scan complet du corpus via LLM à chaque fois.

### d) Ils découplent "ce qui discrimine" de "comment on cherche"

Le retrieval peut évoluer (Query Decomposition, multi-hop, reasoning agents…) sans que les AxisValues aient besoin de changer. Les AxisValues sont une **structure de données stable** qui capture la sémantique du corpus et que différents retrievers peuvent exploiter différemment.

### Conclusion

Les AxisValues et la Query Decomposition sont **complémentaires, pas redondantes** :
- Les AxisValues = **structure de données** qui reflète ce qui discrimine les documents
- La Query Decomposition = **stratégie de retrieval** qui exploite ces structures pour répondre

Un retrieval sémantique sans AxisValues peut fonctionner dans le cas simple, mais manque de précision et de contrôle structurel. Un retrieval avec AxisValues mais sans décomposition n'exploite pas assez cette structure. Les deux ensemble permettent un retrieval **à la fois sémantique et structurellement contraint**.

---

## 4bis. Comportement face aux requêtes impossibles — principe d'intégrité

### Le principe

OSMOSIS doit respecter un invariant strict : **ne jamais inventer une information, ne jamais induire le lecteur en erreur par une formulation ambiguë**. C'est le pendant utilisateur du principe *evidence-locked* qui régit déjà l'extraction et la synthèse.

Concrètement, quand un utilisateur pose une question qui mentionne explicitement des éléments **qui n'existent pas dans le corpus** (versions, entités, périodes...), OSMOSIS doit :

1. **Détecter l'impossibilité** structurellement, pas la dissimuler
2. **Signaler clairement** ce qui n'est pas disponible
3. **Proposer les alternatives valides** présentes dans le corpus
4. **Ne pas substituer silencieusement** un élément voisin à celui demandé
5. **Permettre à l'utilisateur de reformuler** ou de poursuivre avec ce qui est possible

### Test empirique réalisé (08/04 soir)

Un test sur le prototype a comparé les comportements DECOMPOSED vs MONO-QUERY actuel face à une question de comparaison entre une version existante (2022) et une version inexistante (2024) sur le corpus SAP.

**Question testée** :
```
Quelles sont les principales différences dans la description des permissions
d'accès entre la version 2022 et 2024 du Guide de Sécurité SAP ?
```

**Comportement DECOMPOSED (prototype)** :
```
sub_queries:
  q1 : scope_filter {release_id: 2022} → 11 chunks (10 × 2022)
  q2 : scope_filter {release_id: 2024} → 0 chunks

Synthèse : "les informations pour la version 2024 ne sont pas fournies
            dans les documents fournis. Par conséquent, nous ne pouvons
            pas comparer les descriptions des permissions d'accès entre
            les deux versions. Pour la version 2022, [...]"
```

**Comportement MONO-QUERY (baseline actuelle)** :
```
"## ⚠️ Avertissement préalable... aucun 'Guide de Sécurité SAP 2024' n'est
explicitement disponible..."

Puis, juste après :
"## Éléments comparables : 2022 vs 2023"
[suit une comparaison 2022 vs 2023 alors que l'utilisateur demandait 2024]
```

### Le verdict

| Critère | DECOMPOSED | MONO-QUERY |
|---|:---:|:---:|
| Détecte l'absence de la version | ✅ | ✅ |
| **Ne fabrique pas de comparaison fictive** | **✅** | **❌ substitue 2023 à 2024** |
| Reste utile sur ce qu'il a (2022) | ✅ | ✅ |
| Honnêteté pour un utilisateur qui scanne rapidement | ✅ | ⚠️ avertissement enterré sous une réponse trompeuse |

Le comportement MONO-QUERY actuel **viole le principe d'intégrité** : un utilisateur qui scanne rapidement la réponse y voit une comparaison structurée et peut facilement croire qu'il a la réponse à sa question, alors qu'il lit en fait une réponse à une **autre question** que le système a inventée pour lui faire plaisir. L'avertissement existe mais il est enterré sous une réponse en apparence complète.

Le comportement DECOMPOSED est **fail-honest** : il dit clairement *"je ne peux pas comparer parce que 2024 n'existe pas dans le corpus"*. C'est suffisant pour l'intégrité, mais on peut faire mieux côté UX.

### Comportement cible — Clarification interactive

Le comportement idéal pour ce cas n'est pas juste "refuser honnêtement", c'est **proposer une voie de continuation à l'utilisateur**. Pattern proposé :

```
Question utilisateur :
  "Différences entre Security Guide 2022 et 2024 ?"
                        ↓
[QueryDecomposer]
                        ↓
Pré-validation : 2024 ∉ known_axes → impossible_filter détecté
                        ↓
QueryPlan {
  plan_type: "clarification_needed",
  unavailable_filters: [{ axis: "release_id", value: "2024" }],
  available_alternatives: ["1809", "2021", "2023", "2025", "2023 FPS03", "2023 SPS04"],
  reasoning: "version 2024 not present in corpus"
}
                        ↓
Réponse OSMOSIS (pas un contenu factuel, mais un dialogue) :
  "Je ne peux pas répondre directement à votre question : la version 2024
   du Security Guide n'est pas présente dans le corpus.

   Voici les versions disponibles : 2021, 2022, 2023, 2025.

   Souhaitez-vous :
     [a] Comparer 2022 avec une version disponible (2023, 2025...) ?
     [b] Voir uniquement ce qui est documenté pour la version 2022 ?
     [c] Reformuler votre question ?"
                        ↓
[L'utilisateur répond, ou reformule]
                        ↓
Si choix [b] : fallback automatique en mode DIRECT sur la version 2022
Si choix [a] avec une version : retour en mode comparison avec les bonnes versions
Si choix [c] : nouvelle décomposition sur la nouvelle question
```

Ce pattern :

- **Garantit l'intégrité** : pas d'invention, pas de substitution
- **Garde l'utilisateur engagé** : il reçoit des options claires plutôt qu'un mur de "désolé"
- **Préserve la valeur** : si l'utilisateur ne veut que la version disponible, on n'a pas besoin de relancer un nouveau pipeline complet — on bascule simplement de mode `comparison` vers mode `simple` sur la sub-query qui a fonctionné

### Implications architecturales

Pour supporter ce comportement, le `QueryDecomposer` doit acquérir deux nouvelles capacités :

**1. Validation pré-retrieval contre les axis values connus du KG**

Avant d'émettre les sub-queries, le decomposer interroge le KG (ou utilise le contexte fourni au prompt) pour vérifier que **chaque valeur d'axis mentionnée dans un scope_filter existe réellement dans le corpus**. C'est une simple intersection ensembliste — pas coûteux, pas LLM-based, déterministe.

```python
# Pseudo-code
def validate_query_plan(plan: QueryPlan, known_axes: dict[str, set]) -> ValidationResult:
    impossible = []
    for sq in plan.sub_queries:
        for axis_key, axis_value in sq.scope_filter.items():
            if axis_value not in known_axes.get(axis_key, set()):
                impossible.append((axis_key, axis_value))
    return ValidationResult(
        is_valid=(len(impossible) == 0),
        impossible_filters=impossible,
        available_alternatives={ax: list(known_axes[ax]) for ax in {k for k,_ in impossible}},
    )
```

**2. Nouveau type de QueryPlan : `clarification_needed`**

Ajouter aux 4 types existants (`simple`, `comparison`, `enumeration`, `chronological`) un nouveau type **`clarification_needed`** qui correspond à *"j'ai compris la question mais je ne peux pas l'exécuter telle quelle, voici pourquoi et voici les options"*.

Ce type nécessite un nouveau template de réponse côté synthesizer :

```yaml
CLARIFICATION:
  Tu es un assistant qui aide l'utilisateur à reformuler sa question quand
  elle n'est pas exécutable telle quelle. Ne fabrique JAMAIS de réponse,
  ne substitue JAMAIS un élément à un autre. Présente sobrement :
    - ce qui n'est pas disponible (et pourquoi)
    - les alternatives valides présentes dans le corpus
    - une proposition de reformulation
```

**3. Gestion de l'état conversationnel** (plus ambitieux)

Pour que l'utilisateur puisse répondre *"oui, montre-moi juste pour 2022"*, il faut que le système retienne le `QueryPlan` initial et reconnaisse que la nouvelle requête est une **sélection** parmi les alternatives proposées. C'est plus complexe : ça touche à la session, à la mémoire conversationnelle, à la gestion du dialogue. Ce n'est pas le scope du chantier de retrieval, mais c'est un pré-requis pour offrir un vrai dialogue de clarification fluide.

**Approche pragmatique pour la première implémentation** :

- v1 : produire un `clarification_needed` qui retourne directement la réponse de clarification, sans gérer la suite du dialogue. L'utilisateur reformule manuellement sa question. C'est déjà mieux que le comportement actuel.
- v2 : ajouter la mémoire conversationnelle légère (les 1-2 derniers `QueryPlan` de la session) et la détection d'une "réponse de l'utilisateur à une clarification".

### Pattern généralisable au-delà des versions

Cette logique de clarification interactive vaut pour **n'importe quel scope_filter impossible**, pas juste les versions :

| Cas | Décompose en | Si valeur impossible |
|---|---|---|
| *"Compare la régulation française et japonaise"* | filter par `region` | si `region: "japonaise"` n'existe pas → propose les régions présentes |
| *"Différences entre la phase 2 et phase 4 de l'essai X"* | filter par `status` | si phase 4 n'existe pas → propose les phases présentes |
| *"Entre la campagne 2024 et 2026"* | filter par `temporal` | si 2026 n'existe pas → propose les années présentes |
| *"Différences entre Pfizer et XYZ-Pharma sur l'étude Y"* | filter par entité produit | si XYZ-Pharma absent → propose les entités présentes |

**Aucun de ces cas n'est domain-specific.** La logique est : *"l'utilisateur a explicité un axis value qui n'existe pas, on lui dit lequel, on propose les valeurs présentes pour cet axis."* C'est strictement structurel.

### Question ouverte ajoutée à la liste

**Q3 (révisée)** : Gestion du cas *"décomposer a produit 0 résultat utile sur une sub-query"*. Trois sous-cas à distinguer :

- **Cas A — l'axis value n'existait pas dans le corpus** (ex: version 2024 inexistante) : déclencher le mode `clarification_needed` avec les alternatives. **Détectable pré-retrieval** par validation contre les known_axes.
- **Cas B — l'axis value existe mais aucun chunk pertinent à la sub-question** (ex: la version existe mais ne couvre pas le sujet demandé) : produire une réponse partielle qui dit *"sur 2022 j'ai trouvé X, sur 2023 le corpus ne contient pas d'information spécifique au sujet"*. **Détectable post-retrieval** seulement.
- **Cas C — toutes les sub-queries sont vides** (ex: décomposition complètement hors-corpus) : abstain global avec proposition de reformulation.

Ces trois sous-cas méritent des messages utilisateur différents et un traitement distinct dans le synthesizer.

---

## 5. Plan d'implémentation

### Étape 0 — Prototype de validation (1-2h, sans toucher au pipeline)

Un script Python standalone :
1. Prend une question en input
2. Appelle un LLM (Haiku ou vLLM) avec un prompt de décomposition
3. Parse le QueryPlan
4. Appelle l'API `/api/search` actuelle N fois avec les sub-queries
5. Assemble les résultats en un contexte structuré
6. (Optionnel) appelle un LLM de synthèse avec ce contexte
7. Affiche la réponse finale

**But** : valider que le pattern fonctionne empiriquement sur 5-10 questions comparatives avant de l'intégrer au pipeline. Si le prototype marche, on sait que l'intégration propre en vaut la peine.

**Livrable** : `benchmark/probes/prototype_query_decomposer.py`

### Étape 1 — Composant `QueryDecomposer`

- Nouveau module `src/knowbase/api/services/query_decomposer.py`
- Classes : `QueryPlan`, `SubQuery`, `QueryDecomposer`
- Prompt de décomposition domain-agnostic, avec exemples neutres
- Tests unitaires : couvrir les 7 types de décomposition
- Intégration avec le KG pour lookup des `AxisValues` connus

### Étape 2 — Intégration dans `search.py`

- Nouveau mode dans le pipeline : `DECOMPOSED` (ou pré-traitement avant les modes existants)
- Le `strategy_analyzer` actuel reste en place comme pré-filtre bon marché : il décide si la question va au `QueryDecomposer` (coût +1 LLM) ou directement chez le retriever classique
- Si décomposition, le retriever est appelé N fois en parallèle via `asyncio`
- Context Assembler : fonction qui prend les résultats et produit un prompt structuré

### Étape 3 — Adaptation des prompts de synthèse

- Ajouter une nouvelle section dans `config/synthesis_prompts.yaml` :
  - Nouveau template `COMPARE` avec structure explicite
  - Nouveau template `ENUMERATE` pour les agrégations
  - Nouveau template `CHRONOLOGICAL` pour les évolutions
- Les templates reçoivent le contexte déjà structuré en groupes (pas de nouvelle logique prompt)

### Étape 4 — Observabilité

- Logs structurés à chaque étape : `[DECOMPOSER]`, `[SUB_RETRIEVAL]`, `[CONTEXT_ASSEMBLER]`
- Métriques : taux de décomposition, nombre moyen de sub-queries, latence totale, coût LLM
- Tuile cockpit dédiée : ratio décomposé vs simple, latence p50/p95

### Étape 5 — Validation cross-domain

- Tester sur au moins un second domaine (biomedical, legal, ou autre)
- Mesurer via benchmarks :
  - Robustness `temporal_evolution` doit remonter (objectif ≥ baseline V17)
  - T2/T5 `both_sides_surfaced` doit rester stable ou améliorer
  - Aucune régression sur les catégories simples (mode fallback préservé)

---

## 6. Risques et trade-offs

### Risques connus

1. **Latence** : chaque question décomposée coûte +1 appel LLM (decomposer) + N retrievals. Pour une question à 2 sub-queries, la latence peut doubler. Mitigation : parallélisation des retrievals via asyncio, caching du plan de décomposition
2. **Sur-décomposition** : le LLM peut décomposer des questions simples qui n'en ont pas besoin. Mitigation : prompt conservateur, seuil de confiance, fallback strict sur mode simple
3. **Coût** : +1 LLM call par question décomposée, × N retrievals. Acceptable pour un volume démo, à surveiller en production
4. **Debug complexity** : quand la réponse est mauvaise, il faut remonter la chaîne : plan decomposer → retrieval par sub-query → assemblage → synthèse. Observabilité critique
5. **Fausses comparaisons** : le decomposer peut proposer *"compare A et B"* pour une question qui demandait juste A. Mitigation : règle explicite dans le prompt *"ne décompose que si la question mentionne explicitement plusieurs éléments à comparer"*

### Alternatives écartées (et pourquoi)

| Alternative | Pourquoi écartée |
|---|---|
| **Retrieval dual avec filtre `axis_release_id`** (ma première proposition) | Trop limité : ne marche que sur les comparaisons basées sur un axis structuré. Les comparaisons entre entités (produits, personnes, approches…) ne rentrent pas dans ce pattern |
| **Regex sur la question pour détecter "2022 et 2023"** | Domain-specific et multilingue cassé : "between 2022 and 2023", "de 2022 a 2023", "entre 2022 y 2023", "2022 年 vs 2023 年" |
| **Fine-tuning d'un modèle spécifique pour la décomposition** | Disproportionné vu le volume, et rend OSMOSIS dépendant d'un modèle particulier |
| **Réutilisation du `strategy_analyzer`** | Il fait un classification narrative, pas une décomposition structurée. Le transformer en decomposer changerait complètement son contrat |

---

## 7. Questions ouvertes à traiter lors de l'implémentation

1. **Cache du QueryPlan** : si la même question est posée plusieurs fois (ou très proche), faut-il cacher le plan ? Clé de cache : hash de la question + état du KG (AxisValues disponibles)
2. **Déduplication inter-subqueries** : si deux sub-queries retournent le même chunk, faut-il le compter deux fois ou une fois ? Impacte la taille du contexte et le coût de synthèse
3. **Gestion du cas "décomposer a produit 0 résultat utile sur une sub-query"** : voir section 4bis qui traite ce point en détail. Trois sous-cas distincts (A : axis value inexistante → `clarification_needed` ; B : axis value présente mais sujet non couvert → réponse partielle honnête ; C : décomposition complètement vide → abstain global). Pattern recommandé : **clarification interactive** plutôt que substitution silencieuse, pour respecter le principe d'intégrité d'OSMOSIS (jamais d'invention, jamais d'induction en erreur par formulation ambiguë).
4. **Nombre maximum de sub-queries** : limite hard pour éviter les décompositions pathologiques. Proposition : 5 maximum, au-delà on rejette et on fallback
5. **Profondeur de décomposition** : une sub-query peut-elle être elle-même décomposée ? (multi-level) Proposition : non dans un premier temps, KISS
6. **Interaction avec PERSPECTIVE** : si le decomposer propose 3 sub-queries et que le retriever active PERSPECTIVE sur chacune, on a 3 sets de Perspectives. Comment les agréger dans la synthèse finale ? À définir

---

## 8. Pointeurs vers l'existant à relire avant implémentation

- `src/knowbase/api/services/strategy_analyzer.py` — le classificateur actuel dont le decomposer est une évolution
- `src/knowbase/api/services/search.py` — point d'intégration, sections `resolved_mode` (autour des lignes 1300+)
- `src/knowbase/claimfirst/resolution/subject_resolver_v2.py` — le decomposer peut réutiliser la même structure de prompt (JSON contractuel + exemples domain-agnostic)
- `config/synthesis_prompts.yaml` — les modes existants pour modèle de nouveaux templates
- `doc/ongoing/[futur]_DETTE_COMPARABLE_SUBJECT.md` — le fix ComparableSubject est un prérequis bas niveau
- `doc/ongoing/PREP_DEMO_V0.1.md` — section S5b sur le contexte des régressions Robustness

## 9. Voir aussi

- **Papiers de référence** :
  - Self-Ask with Search — Press et al., 2022
  - IRCoT (Interleaving Retrieval with Chain-of-Thought) — Trivedi et al., 2022
  - Least-to-Most Prompting — Zhou et al., 2022
- **Frameworks d'inspiration** :
  - LlamaIndex — `SubQuestionQueryEngine`
  - LangChain — `MultiQueryRetriever`, `self_query` chain
