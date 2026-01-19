# Prompt pour ChatGPT - Implémentation Option C

*À copier-coller dans ChatGPT pour obtenir les spécifications détaillées*

---

## Contexte

Claude a analysé en profondeur ta proposition "Option C - Structural Graph from DoclingDocument" et confirmé sa faisabilité. Voici ce que nous avons découvert dans notre codebase :

### Ce que nous avons DÉJÀ

1. **Accès à DoclingDocument** (`docling_extractor.py:269-271`):
```python
from docling.datamodel.document import DoclingDocument
doc: DoclingDocument = docling_result.document
```

2. **Export disponible** (`docling_extractor.py:567`):
```python
json_struct = result.document.export_to_dict()
```

3. **Types Docling confirmés** - `DocItemLabel` enum avec :
   - TEXT, PARAGRAPH, TITLE, SECTION_HEADER
   - TABLE, CHART
   - LIST_ITEM
   - PICTURE, CAPTION
   - CODE, FORMULA, FOOTNOTE
   - PAGE_HEADER, PAGE_FOOTER
   - etc.

4. **Structure des items Docling** :
```python
TextItem:
  - self_ref: str  # ID unique stable
  - label: DocItemLabel  # Type structurel
  - text: str  # Contenu
  - prov: List[ProvenanceItem]  # page_no, bbox, charspan
  - parent/children: RefItem  # Hiérarchie

ProvenanceItem:
  - page_no: int
  - bbox: BoundingBox  # x0, y0, x1, y1
  - charspan: Tuple[int, int]
```

5. **Infrastructure existante** :
   - `NavigationLayerBuilder` pour créer DocumentContext, SectionContext
   - `hybrid_anchor_chunker.py` pour le chunking
   - `semantic_consolidation_pass3.py` pour la relation extraction
   - Neo4j + Qdrant configurés

### Ce que nous devons CRÉER

1. **DocItem nodes** dans Neo4j (nouveau label)
2. **PageContext nodes** dans Neo4j
3. **structural_profile** sur SectionContext
4. **Type-aware Chunker** (NARRATIVE/TABLE/FIGURE)
5. **DERIVED_FROM** relation (Chunk → DocItem)
6. **Persistance** de DoclingDocument comme artefact

---

## Questions pour ChatGPT

### 1. Mapping DoclingDocument → DocItem

J'ai besoin du **mapping exact** entre les types Docling et notre modèle DocItem :

a) Pour chaque `DocItemLabel`, quel `item_type` dois-je assigner ?

b) Comment déterminer `is_relation_bearing` pour chaque type ?

c) Comment gérer les cas spéciaux :
   - `LIST_ITEM` dans une liste ordonnée vs non-ordonnée ?
   - `CAPTION` lié à une TABLE vs PICTURE ?
   - `KEY_VALUE_REGION` et `FORM` ?

d) Comment reconstruire le `reading_order_index` depuis DoclingDocument ?
   - Docling expose-t-il un ordre de lecture explicite ?
   - Sinon, quelle heuristique recommandes-tu ?

### 2. Gestion de la Hiérarchie

DoclingDocument a :
- `body: GroupItem` (arbre hiérarchique)
- `groups: List[GroupItem]`
- `parent/children` sur chaque item

a) Comment exploiter cette hiérarchie pour construire les SectionContext ?

b) Faut-il créer un `DocItem` pour les `GroupItem` aussi, ou seulement pour les items "leaf" ?

c) Comment déterminer les frontières de section (quand un `SECTION_HEADER` commence une nouvelle section) ?

### 3. Tables - Traitement Spécial

Docling fournit `TableItem` avec :
- `data.table_cells` (structure cellulaire)
- `self_ref`, `prov`, etc.

a) Comment représenter une table comme `DocItem.text` ?
   - Markdown (`| col | col |`) ?
   - JSON stringifié ?
   - Autre format ?

b) Faut-il créer des DocItems pour les cellules individuelles, ou seulement pour la table entière ?

c) Comment gérer les tables multi-pages ?

### 4. Pictures/Figures

Pour `PictureItem` :

a) Que mettre dans `DocItem.text` pour une figure (pas de texte natif) ?
   - Caption si disponible ?
   - Description vide ?

b) Comment lier une CAPTION à son PICTURE parent ?

### 5. Chunking Type-Aware

a) Quelles sont les **règles de segmentation** pour les chunks NARRATIVE ?
   - Fenêtre de tokens fixe ?
   - Respect des frontières de paragraphe ?
   - Respect des frontières de section ?

b) Pour les chunks TABLE/FIGURE :
   - Un chunk = une table/figure ?
   - Ou regrouper plusieurs petites tables consécutives ?

c) Comment gérer les **captions** :
   - Dans le chunk de la table/figure ?
   - Ou dans le chunk narrative environnant ?

### 6. SectionContext.structural_profile

Tu proposes de calculer :
```
dominant_types: Set[str]
is_relation_bearing: bool
is_structure_bearing: bool
table_ratio, list_ratio, figure_ratio, text_ratio: float
```

a) Comment calculer ces ratios ?
   - Par nombre d'items ?
   - Par volume de texte ?
   - Par surface bbox ?

b) Seuils pour `is_relation_bearing` vs `is_structure_bearing` ?

c) Faut-il recalculer à chaque modification ou stocker comme snapshot ?

### 7. Evidence et Provenance

Pour la relation `(c1)-[r:REQUIRES]->(c2)` avec evidence :

a) Format recommandé pour `evidence_item_ids` ?
   - Liste de self_ref Docling ?
   - Liste d'IDs internes ?

b) Comment stocker `evidence_bbox` ?
   - JSON stringifié ?
   - Propriétés séparées (x0, y0, x1, y1) ?

c) Si une relation a des preuves sur plusieurs pages, comment représenter ?

### 8. Migration et Rétrocompatibilité

Nous avons des documents déjà ingérés (sans DocItem).

a) Stratégie de migration recommandée ?
   - Réingestion complète ?
   - Migration incrémentale ?

b) Comment gérer la coexistence ancien/nouveau format pendant la transition ?

c) Faut-il versionner le schéma Neo4j ?

### 9. Performance et Indexes

Avec potentiellement des milliers de DocItems par document :

a) Quels indexes sont **critiques** pour les requêtes fréquentes ?

b) Faut-il partitionner les DocItems par document (préfixer les IDs) ?

c) Estimation de l'overhead Neo4j pour un corpus de 100 documents ?

### 10. Edge Cases

a) Documents sans structure (PDF scannés, images OCR) ?

b) Documents avec structure corrompue/incomplète de Docling ?

c) Très longs documents (>1000 pages) ?

---

## Livrables Attendus

1. **Table de mapping** : DocItemLabel → item_type + is_relation_bearing

2. **Pseudo-code** : Construction du reading_order depuis DoclingDocument

3. **Règles de chunking** : Algorithme type-aware avec exemples

4. **Schema Neo4j** : Labels, relations, indexes (Cypher complet)

5. **Formules** : Calcul structural_profile

6. **Stratégie migration** : Étapes concrètes

---

## Contraintes à Respecter

1. **100% agnostique métier** : Aucune référence à SAP ou à un domaine spécifique

2. **Production-grade** : Pas de solutions temporaires ou de hacks

3. **Traçabilité** : Toute information doit avoir une provenance

4. **Performance** : Doit fonctionner sur corpus de 500+ documents

5. **Compatibilité Docling** : Utiliser l'API officielle, pas de parsing interne
