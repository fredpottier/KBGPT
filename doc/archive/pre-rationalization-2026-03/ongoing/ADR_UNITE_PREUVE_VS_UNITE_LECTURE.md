# ADR — Unite de Preuve vs Unite de Lecture

**Date** : 25 mars 2026
**Statut** : Accepte
**Auteurs** : Fred Pottier, Claude Code, Claude Web, ChatGPT (consensus)
**Prerequis** : ADR-20260126 (Vision Out of Knowledge Path)

---

## 1. Contexte

Le pipeline ClaimFirst utilise les DocItems atomiques comme unite unique pour le KG (claims) ET pour le retrieval (chunks Qdrant). Cette decision est optimale pour l'extraction de claims (atomicite = precision) mais catastrophique pour le retrieval (atomicite = chunks de 30-70 chars inutilisables par le LLM).

Diagnostic Sprint 2 (25 mars 2026) : 70% des chunks Qdrant font moins de 100 chars. Le factual_correctness est a 43% non pas a cause du LLM ou de l'architecture mais parce que les chunks ne contiennent pas les faits recherches.

## 2. Decision

**Separer formellement l'unite de preuve et l'unite de lecture.**

| Concept | Definition | Usage | Invariant |
|---------|-----------|-------|-----------|
| **Unite de preuve** | DocItem/Claim : atomique, verbatim, ancrable | KG (Neo4j) | Pas d'assertion sans preuve localisable (ADR-20260126) |
| **Unite de lecture** | Chunk Qdrant : contextuel, autonome, lisible | Retrieval (Qdrant) | Un expert humain doit pouvoir repondre a une question factuelle avec ce chunk seul |

Les deux coexistent. Le lien est preserve via `item_ids` dans les chunks et `chunk_ids` dans les claims.

## 3. Invariant reformule

**Ancien** :
> "OSMOSIS ne deduit pas de verite des documents — il n'exploite que ce qui est clairement indique."

**Nouveau** :
> "OSMOSIS ne produit pas d'affirmation sans source documentaire tracable. Les metadonnees structurelles du document (titre, section, position, notes orateur) sont des faits documentaires — pas des inferences. L'unite de preuve (Claim, KG) reste atomique et verbatim. L'unite de lecture (chunk Qdrant) peut etre enrichie par reconstruction contextuelle a partir de metadonnees structurelles sans appel LLM."

## 4. Ce qui est autorise

- Prefixe contextuel deterministe (doc_title + section_title + page) dans les chunks Qdrant
- Fusion des notes orateur avec le contenu visible des slides (contenu auteur verbatim)
- Relations structurelles Docling (`contains`, `grouping`) comme verbatim : "SAP Business Suite contient : AI, Data Cloud, Applications"
- Filtrage des chunks non-autonomes (< 100 chars narratif, < 50 chars table)
- Utilisation des TypeAwareChunks du cache au lieu des DocItems pour Qdrant

## 5. Ce qui reste interdit

- Descriptions interpretatives Vision dans le chemin de connaissance (ADR-20260126 maintenu)
- Prefixe contextuel genere par LLM (inference, non-deterministe)
- Inference de flux directionnels dans les schemas ("A cause B" a partir de "A → B")
- Tout contenu ajoute au chunk qui ne provient pas du document source ou de ses metadonnees structurelles

## 6. Limite documentee

Les flux directionnels dans les schemas PPTX (fleches A → B → C) ne sont pas captures par Docling. Seules les relations de containment spatial (`contains`) et de groupement (`grouping`) sont disponibles. Cette limite est acceptee — la description structurelle partielle ("Element A contient B, C, D") apporte deja de la valeur sans inferer de semantique.

## 7. Architecture cible

```
Document brut
    |
[Extraction] Docling + Speaker Notes
    |
    +--- DocItems atomiques → ClaimFirst → Claims → KG
    |    (unite de preuve, verbatim, inchange)
    |
    +--- TypeAwareChunks → Prefixe contextuel deterministe → Qdrant
         (unite de lecture, enrichie, autonome)
```
