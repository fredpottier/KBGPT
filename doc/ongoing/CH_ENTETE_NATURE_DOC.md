# Chantier — En-tête de nature documentaire (pré-filtrage des sources)

> **Statut** : **B1+B2 + surface codés** (10/06). Reste B3 (peuplement) = ré-ingestion.
>   - B1+B2 (ingestion) : `claimfirst/document_profile.py` + orchestrateur Phase 7.7
>     (commit `e187039`). Worker à rebuilder pour charger le module.
>   - Surface (runtime+UI) : `runtime_v6.py` (`_hydrate_citation_sources` + `CitedClaimRef`
>     `source_role`/`source_summary`) + `RuntimeA3Panel.tsx` (citations groupées par doc,
>     en-tête `[tag rôle] + titre + résumé`). App monte `./src` → live au restart `app`
>     (pas de rebuild) ; dégrade en simple titre tant que les profils ne sont pas peuplés.
>   - B3 (peuplement) : à la ré-ingestion PURPOSE/lifecycle (les profils `role`/`summary`
>     restent vides d'ici là — l'UI dégrade proprement).
> **Date** : 2026-06-10 — Branche : feat/phase-b-augmentee.
> **Origine** : session produit du 10/06. Fred, en utilisant le chat sur le corpus
> aéro (sièges 9g), constate qu'il ouvre les documents un par un pour découvrir *de
> quoi ils parlent et quelle est leur nature*. Besoin : un **en-tête par document**
> dans le panneau de sources du chat — « ce doc est une **réglementation** sur X, cet
> autre est la **spécification** de la norme Y » — pour **pré-filtrer sans ouvrir**.
> **Famille** : « révéler un lien/statut que l'utilisateur aurait raté » (même ADN que
> la Carte du Référentiel et la traçabilité Phase C). Voir `CATALOGUE_FONCTIONNEL.md`.

---

## 1. Principe directeur

Le système a déjà « lu » chaque document à l'ingestion. Restituer **sa nature et son
rôle** au point d'usage (la citation), c'est faire faire au moteur le pré-tri qu'un
non-expert du domaine doit aujourd'hui faire à la main, fichier après fichier.

**Contrainte de design forte (INV-10, domain-agnostic)** : le vocabulaire de rôles
(`Réglementation`, `Norme/Standard`, `Spécification`, `Guidance/Advisory`…) donné en
exemple est **NON exhaustif** et **propre au corpus aéro courant**. Le classifieur ne
doit **jamais** être un enum figé hardcodé : il **découvre** les rôles du corpus et les
**normalise** via un registre par tenant (même philosophie que `entity_types` /
domain context / living ontology). Un corpus juridique, médical ou financier doit faire
émerger ses propres rôles sans modification de code.

---

## 2. État des lieux — VÉRIFIÉ (code + KG aéro, 10/06)

### 2.1 Ce qui existe mais n'est pas exploitable en l'état
| Élément | Réalité vérifiée | Réf. |
|---|---|---|
| Résumé de document | **Généré puis jeté** au runtime de persistance | `extraction_v2/pipeline.py:739` (`_, _, ctx = await generate_document_summary(...)`), fonction `ingestion/osmose_enrichment.py:199` |
| `document_type` (regex) | Vocabulaire **100 % SAP-logiciel** (« Operations Guide », « Release Notes », « Legal Document »…) → ne matche **jamais** un doc réglementaire | `claimfirst/extractors/context_extractor.py:55` (`DOCUMENT_TYPE_PATTERNS`), inféré en `:662` `_infer_document_type` — **hardcode contredisant le commentaire INV-10 juste au-dessus** |
| `doc_type` via resolver | `SubjectResolverV2.doc_type.label`, **défaut `"unknown"`**, seulement loggé/enrichi dans `doc_context`, non fiabilisé sur aéro | `claimfirst/orchestrator.py:2586-2593` |
| `DocumentContext` (porteur de `document_type`) | Persisté via `Document-[:HAS_CONTEXT]->DocumentContext` **mais inexistant sur aéro** | `claimfirst/persistence/claim_persister.py:385-405` |

### 2.2 Mesures empiriques sur le tenant `aero` (Neo4j, 10/06)
- Nœuds `Document` aéro : **14**, propriétés = `{doc_id, reg_key, ingested, created_at, tenant_id}` — **ni `title`, ni `document_type`, ni `summary`**.
- `Claim.document_type` : **null sur les 17 455 claims**.
- Nœuds `DocumentContext` aéro : **0** (relation `HAS_CONTEXT` absente).

### 2.3 Signal doc-level réellement disponible aujourd'hui
- `Document.reg_key` (ex. `AC_25.562-1B`) — identifiant réglementaire.
- `SUPERSEDES_DOC` (lignée doc→doc) — déjà surfacé en chat (#443).
- `regulatory_authority` (FAA/EASA) — porté par les **claims** (#440).

**Conclusion** : le label de nature/rôle et le résumé ne sont **ni stockés ni
calculés** pour ce corpus. Ce chantier **ajoute une brique d'ingestion légère**, ce
n'est pas un simple affichage de l'existant.

---

## 3. Briques à construire

### B1 — Classifieur de rôle doc-level, ouvert et domain-agnostic
- **Entrée** : `title` (ou titre enrichi `orchestrator._enrich_title_from_passages`) + 1ʳᵉ page + `reg_key` + `regulatory_authority` agrégée.
- **Sortie** : un **label de rôle concis** (1-3 mots) + confiance + 1 phrase de justification. **Pas d'enum fermé.**
- **Normalisation** : confronter le label proposé à un **registre de rôles par tenant**
  (créer/réutiliser un store type `entity_types`) pour collapser les variantes
  (« Regulation » / « Regulatory document » → un canonical) et **éviter la dérive** de
  libellés. Nouveau rôle inédit → ajouté au registre (découverte), pas rejeté.
- **Implémentation** : 1 appel LLM (tâche `classification`/`metadata` du `llm_router`),
  prompt générique. **Remplace** le regex SAP `DOCUMENT_TYPE_PATTERNS` (corrige le
  hardcode pour TOUS les corpus). Réutiliser le signal `SubjectResolverV2.doc_type` s'il
  s'avère fiable, sinon le supplanter.
- **Effort** : petit.

### B2 — Persistance rôle + résumé sur le nœud `Document`
- Cesser de jeter le résumé : récupérer le 1ᵉʳ tuple de `generate_document_summary` dans
  `extraction_v2/pipeline.py:739`.
- À la persistance du Document (worker ClaimFirst) : `SET d.role = …`,
  `d.role_confidence = …`, `d.summary = …`, `d.title = …` (le titre enrichi n'est pas
  persisté aujourd'hui non plus).
- **Effort** : petit.

### B3 — Peuplement
- **Option recommandée** : intégrer B1+B2 au pipeline d'ingestion **avant** la
  ré-ingestion PURPOSE/lifecycle **déjà au backlog** → les 14 docs aéro (et les futurs)
  sont peuplés « gratuitement », sans run jetable.
- **Option de repli** : script de backfill doc-level sur les docs existants (lit
  `reg_key` + texte cache `.v5cache.json`, applique B1, écrit B2) — utile si la
  ré-ingestion tarde, mais à éviter si elle est imminente.

---

## 4. Surface (≈90 % prête grâce à Phase C)

| Couche | Action | Point de branchement |
|---|---|---|
| Retrieval | Side-effect `_attach_doc_profiles(doc_ids)` → `{role, summary, title}` par doc | `runtime_a3/execute.py` — **calquer** sur `CYPHER_DOC_LINEAGE` (`:209`) / `_attach_lineage` / `_attach_authority_conflicts` |
| Schéma réponse | Ajouter `source_role`, `source_summary`, `source_title` à `CitedClaimRef` (additifs, `extra="forbid"`) | `routers/runtime_v6.py` — `CitedClaimRef` (`:~102`), peuplés dans `_build_response`, hydratés via `_hydrate_citation_sources` (`:313`) — **même geste que les champs Phase C** (verbatim/dates) |
| UI | **Grouper les citations par document** et coiffer chaque groupe d'un en-tête `[tag rôle] + titre + 1 ligne résumé` | `frontend/src/components/chat/RuntimeA3Panel.tsx` — seul vrai travail UI (aujourd'hui : liste plate de citations) ; le viewer source Phase C reste inchangé |

---

## 5. Effort & dépendances

- **Backend** B1+B2 : petit-moyen. **Runtime + UI** : petit (réutilise Phase C + pattern side-effect).
- **Dépendance bloquante du peuplement** : la **ré-ingestion PURPOSE/lifecycle** (backlog).
  → coder B1+B2 **dans le pipeline AVANT** de relancer, sinon double passe.
- **Risque** : qualité/stabilité des labels de rôle (mitigé par le registre de
  normalisation B1) ; résumé de 500 car. parfois trop générique pour discriminer
  (le **rôle** discrimine, le résumé contextualise — c'est le tag qui porte la valeur de pré-filtrage).

---

## 6. Critère de succès

Sur une question multi-doc (ex. « sièges 9g »), le panneau de sources affiche, **sans
ouvrir aucun fichier**, pour chaque document cité : son **rôle** (tag) + son titre + une
ligne de résumé — permettant à l'utilisateur de dire « je veux la réglementation, pas la
norme » et d'ignorer le reste. Validé d'abord sur 1-2 docs aéro re-ingérés.

---

*Lié à : `CATALOGUE_FONCTIONNEL.md` (principe de sélection), Phase C (traçabilité,
#467), ré-ingestion PURPOSE/lifecycle (backlog), #443 lignée, #440 authority.*
