# Plan d'implementation — 3 use cases demo (2026-03-20)

**Objectif** : 3 nouvelles pages fonctionnelles pour une demo ce soir
**Corpus** : Biomedical pre-eclampsie (37 docs, 5692 claims, 43 contradictions, 64 articles)

---

## Use Case 1 — Corpus Audit Report

### URL : `/admin/corpus-audit`

### Ce que ca montre
Une "radiographie" du corpus documentaire en une seule page. L'utilisateur voit immediatement la sante de sa base de connaissances sans avoir a naviguer dans plusieurs pages.

### Contenu de la page

**Section 1 — Score de sante global**
- Jauge circulaire ou score sur 100 calcule depuis :
  - Couverture (% entites avec article) — poids 20%
  - Taux de contradiction (contradictions / claims) — poids 30% (inverse : moins = mieux)
  - Diversite des sources (nb docs par concept moyen) — poids 25%
  - Qualite des claims (% claims avec verbatim) — poids 25%
- Couleur : vert (>70), orange (40-70), rouge (<40)

**Section 2 — Chiffres cles (4 cards)**
- Documents analyses
- Claims extraites
- Entites identifiees
- Contradictions detectees

**Section 3 — Top contradictions (5 max)**
- Pour chaque : les 2 claims face-a-face (texte tronque)
- Type de tension (value_conflict, scope_conflict, etc.) en badge colore
- Sources (doc_id) en lien
- Bouton "Explorer" → lien vers le Contradiction Explorer

**Section 4 — Zones a risque**
- Concepts avec le plus de contradictions (top 5) — badge rouge
- Concepts les plus documentes mais sans article (top 5) — badge orange
- Domaines/facettes avec couverture faible (< 3 docs) — badge jaune

**Section 5 — Recommandations (genere dynamiquement)**
- "5 articles prioritaires a ecrire" (tier 1 sans article)
- "3 contradictions critiques a resoudre" (value_conflict + hard)
- "2 domaines sous-documentes a enrichir"

### Backend
- **Endpoint** : `GET /api/admin/corpus-audit`
- **Donnees** : assemblage de donnees existantes :
  - `_get_corpus_stats()` de persistence.py
  - `_get_blind_spots()` de persistence.py
  - Requete Neo4j pour top contradictions avec texte des 2 claims
  - Requete Neo4j pour concepts avec le plus de contradictions
  - `_get_tier1_concepts()` filtres has_article=false
- **Pas de nouveau modele Pydantic complexe** — un dict suffit

### Frontend
- Page dans `frontend/src/app/admin/corpus-audit/page.tsx`
- Ajouter le lien dans le layout admin (`frontend/src/app/admin/layout.tsx`)
- Composants Chakra : StatCard, Table, Badge, Progress

---

## Use Case 2 — Contradiction Explorer

### URL : `/admin/contradictions`

### Ce que ca montre
Navigation interactive dans les contradictions du corpus. L'utilisateur explore les tensions entre sources, comprend leur nature, et peut agir.

### Contenu de la page

**Barre de filtres (en haut)**
- Filtre par type de tension : `value_conflict` | `scope_conflict` | `temporal_conflict` | `methodological` | `complementary` | tous
- Filtre par severite : `hard` | `soft` | tous
- Filtre par concept/entite (search autocomplete)
- Tri : par date | par severite | par concept

**Liste des contradictions**
Chaque contradiction = une card avec :
- **Claim A** (texte complet) + source (doc_id, page) + badge type claim
- **vs** (separateur visuel avec icone)
- **Claim B** (texte complet) + source (doc_id, page) + badge type claim
- **Badges** : tension_nature (colore), tension_level (hard=rouge, soft=orange)
- **Entites communes** : les Entity liees aux deux claims (chips cliquables → Atlas)
- **Verbatim quotes** : expandable, les citations exactes des sources

**Stats en haut de page**
- Total contradictions
- Repartition par type (pie chart ou barres)
- Repartition par severite

### Backend
- **Endpoint** : `GET /api/admin/contradictions?nature=value_conflict&level=hard&entity=&limit=20&offset=0`
- **Requete Neo4j** :
```cypher
MATCH (c1:Claim {tenant_id: $tid})-[r:CONTRADICTS]-(c2:Claim)
WHERE c1.claim_id < c2.claim_id
// filtres optionnels sur r.tension_nature, r.tension_level
OPTIONAL MATCH (c1)-[:ABOUT]->(e1:Entity)
OPTIONAL MATCH (c2)-[:ABOUT]->(e2:Entity)
RETURN c1, c2, r,
       collect(DISTINCT e1.name) AS entities1,
       collect(DISTINCT e2.name) AS entities2
ORDER BY r.tension_level DESC, r.tension_nature
SKIP $offset LIMIT $limit
```
- **Schema Pydantic** : `ContradictionItem` (claim1, claim2, tension_nature, tension_level, entities, sources)

### Frontend
- Page dans `frontend/src/app/admin/contradictions/page.tsx`
- Ajouter le lien dans le layout admin
- Design : cards avec deux colonnes (claim A | claim B), separateur central
- Couleurs : value_conflict=rouge, scope_conflict=bleu, temporal=orange, methodological=violet, complementary=vert

---

## Use Case 3 — Corpus Intelligence (Heatmap + Bubble Chart)

### URL : `/admin/corpus-intelligence`

### Ce que ca montre
Deux visualisations complementaires du meme corpus :
- **Onglet Heatmap** : "De quoi parle mon corpus ?" — matrice sujets x documents
- **Onglet Bubble Chart** : "Ou sont les risques ?" — couverture vs contradictions vs importance

### Onglet 1 — Heatmap

**Axes**
- Y (lignes) : Top 20 entites par claim_count (dedup canonical, filtres stoplist)
- X (colonnes) : Top 15 documents (par claim_count total)
- Cellule : nombre de claims de cette entite dans ce document
- Couleur : gradient blanc → bleu fonce (0 → max)

**Labels documents** : noms courts (extraire du doc_id : "PMC12452302..." → "Understanding PE cardiovascular...")

**Interactions**
- Hover sur cellule : tooltip avec le nombre exact
- Click sur entite (ligne) : lien vers l'article Atlas si existant
- Click sur document (colonne) : lien vers les claims du document

**Legende**
- Gradient de couleur avec echelle
- Texte : "Densite de claims par concept et document source"

### Onglet 2 — Bubble Chart

**Axes**
- X : Nombre de sources (doc_count) — couverture
- Y : Nombre de contradictions — tension
- Taille bulle : nombre de claims — importance
- Couleur : has_article (vert) vs no_article (gris)

**Donnees** : top 30 entites (claims >= 10, filtres stoplist/actor/other)

**Interactions**
- Hover sur bulle : tooltip avec nom, claims, docs, contradictions
- Click sur bulle : lien vers l'article Atlas ou page entite

**Zones interpretatives (optionnel, si le temps le permet)**
- Quadrant haut-droite : "Sujets bien couverts mais controverses" (rouge)
- Quadrant bas-droite : "Sujets bien couverts et stables" (vert)
- Quadrant haut-gauche : "Alertes — peu de sources mais contradictions" (orange)
- Quadrant bas-gauche : "Sujets mineurs" (gris)

### Backend

**Endpoint heatmap** : `GET /api/admin/corpus-intelligence/heatmap`
```cypher
MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)
WHERE e._hygiene_status IS NULL
  AND NOT e.entity_type IN ['actor', 'other']
  AND size(e.name) >= 4 AND size(e.name) <= 60
WITH e, c.doc_id AS doc, count(c) AS cnt
WITH e, sum(cnt) AS total, collect({doc: doc, cnt: cnt}) AS docs
ORDER BY total DESC LIMIT 20
UNWIND docs AS d
RETURN e.name AS entity, d.doc AS doc_id, d.cnt AS claims
ORDER BY total DESC
```
+ stoplist domain pack en filtrage Python

Reponse : `{ entities: [...], documents: [...], matrix: [[...]] }`

**Endpoint bubble** : `GET /api/admin/corpus-intelligence/bubble`
```cypher
MATCH (e:Entity {tenant_id: $tid})
WHERE e._hygiene_status IS NULL
  AND NOT e.entity_type IN ['actor', 'other']
  AND size(e.name) >= 4 AND size(e.name) <= 60
OPTIONAL MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e)
WITH e, count(DISTINCT c) AS claims, count(DISTINCT c.doc_id) AS docs
WHERE claims >= 10
OPTIONAL MATCH (c1:Claim)-[:ABOUT]->(e), (c1)-[r:CONTRADICTS]-(c2:Claim)
WITH e.name AS name, claims, docs, count(DISTINCT r)/2 AS contradictions
OPTIONAL MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})-[:ABOUT]->(e2:Entity {name: name})
RETURN name, claims, docs, contradictions, wa.slug IS NOT NULL AS has_article, wa.slug AS slug
ORDER BY claims DESC LIMIT 30
```
+ dedup canonical + stoplist domain pack en Python

Reponse : `{ bubbles: [{name, claims, docs, contradictions, has_article, slug}, ...] }`

### Frontend
- Page dans `frontend/src/app/admin/corpus-intelligence/page.tsx`
- Ajouter le lien dans le layout admin
- **Librairie graphique** : recharts (deja dans le projet ?) ou nivo (heatmap native)
  - Verifier : `frontend/package.json` pour les deps existantes
  - Si rien : `npm install recharts` (leger, bien integre React)
- Onglets Chakra `Tabs` pour switcher Heatmap / Bubble
- Heatmap : composant custom avec grille CSS ou recharts `<HeatMap>`
- Bubble : recharts `<ScatterChart>` avec `<ZAxis>` pour la taille

---

## Modifications communes

### Layout Admin
**Fichier** : `frontend/src/app/admin/layout.tsx`

Ajouter 3 liens dans la navigation admin :
```
{ label: 'Audit Corpus', href: '/admin/corpus-audit', icon: FiClipboard }
{ label: 'Contradictions', href: '/admin/contradictions', icon: FiAlertTriangle }
{ label: 'Intelligence', href: '/admin/corpus-intelligence', icon: FiBarChart2 }
```

### Router Backend
**Fichier** : `src/knowbase/api/routers/analytics.py` (ou nouveau fichier si analytics.py est trop different)

Ajouter les 4 endpoints :
- `GET /api/admin/corpus-audit`
- `GET /api/admin/contradictions`
- `GET /api/admin/corpus-intelligence/heatmap`
- `GET /api/admin/corpus-intelligence/bubble`

### Verification pre-dev
- [ ] Verifier les deps frontend (recharts ou alternative)
- [ ] Verifier que le router est monte dans main.py
- [ ] Verifier le layout admin pour la structure des liens

---

## Ordre d'implementation

1. **Backend** : les 4 endpoints (rapide, queries Neo4j directes)
2. **Corpus Audit Report** (le plus simple, cards + liste)
3. **Contradiction Explorer** (cards avec deux colonnes)
4. **Corpus Intelligence** (le plus complexe, graphiques)

## Ce qu'on NE fait PAS
- Pas de nouveau pipeline d'ingestion
- Pas de modification du KG existant
- Pas de generation LLM (tout est lu depuis Neo4j)
- Pas de persistance de nouveaux noeuds
- Pas de tests unitaires (demo, pas production)
