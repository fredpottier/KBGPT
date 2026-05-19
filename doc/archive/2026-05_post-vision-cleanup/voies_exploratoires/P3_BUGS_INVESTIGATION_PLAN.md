# Phase 3 — Plan d'attaque bugs critiques

*Date : 30 avril 2026*
*Statut : Investigation initiale complétée, plan de fix détaillé*

## Vue d'ensemble

4 bugs identifiés en mémoire, chacun bloque un pipeline d'ingestion ou réduit la qualité du KG. Investigation effectuée pendant la session de finalisation V2 ; les fixes sont planifiés en sessions dédiées (chaque bug = 1-3 jours).

---

## P3.1 — Cache markdown full_text vide

### Symptôme
Caches `.v5cache.json` produits depuis fichiers `.md` ont `extraction.full_text = ''` (0 chars). Les PDF marchent normalement.

### Investigation effectuée
- `src/knowbase/ingestion/folder_watcher.py:151` route les `.md` vers `enqueue_document_v2`
- `enqueue_document_v2` utilise le pipeline V2 unifié (Stratified Reading Model)
- Pipeline V2 délègue à un extracteur via `pipeline.py` mais aucun MarkdownExtractor explicite n'a été identifié dans les modules `extraction_v2/extractors/`
- Hypothèse : le pipeline V2 essaie d'utiliser le DoclingExtractor qui ne gère pas le markdown brut

### Plan de fix
1. Créer `src/knowbase/extraction_v2/extractors/markdown_extractor.py` :
   - Lit le fichier `.md` (UTF-8)
   - Parse en sections via headers `#` `##`
   - Produit un `ExtractionResult` avec full_text non-vide + structure (pages, paragraphs)
2. Brancher dans `pipeline.py` la sélection extracteur par file_type :
   - `.md` → `MarkdownExtractor`
   - `.pdf` → `DoclingExtractor`
   - `.pptx` → `PptxExtractor`
   - `.docx` → `DoclingExtractor` (déjà géré ?)
3. Test régression sur 1 fichier `.md` test

### Effort estimé : 1 jour

### Acceptation
- Cache `.v5cache.json` d'un `.md` a `full_text` non-vide (> 100 chars)
- Pipeline V2 ne crash pas sur `.md`

---

## P3.2 — Dispatcher /docs_in route vers Stratified V2 obsolète

### Symptôme
Le folder-watcher + jobs_v2.py routent les nouveaux documents vers Stratified V2 (un ancien pipeline) au lieu de ClaimFirst (pipeline cible). Conséquence : documents importés via /watch ont concepts=0 et osmose_s=0.

### Investigation effectuée
Mémoire `project_dispatcher_docs_in_stale.md` :
- ClaimFirst est invoqué via `/api/claimfirst/trigger/{doc_id}` mais pas par défaut
- enqueue_document_v2 dispatche vers le pipeline V2 unifié, qui peut être configuré pour faire ClaimFirst en aval mais ce n'est pas systématique
- Stratified V2 est l'ancien pipeline (peut être retiré si non utilisé)

### Plan de fix
1. Auditer `src/knowbase/ingestion/queue/dispatcher.py` et confirmer où vont les docs
2. Si Stratified V2 dispatché → modifier la route vers ClaimFirst directement
3. Décider du sort de Stratified V2 : suppression complète si plus utilisé
4. Tester import via /watch → vérifier post-import claims créés (Cypher MATCH (c:Claim) WHERE c.doc_id=$new_id RETURN count(c))

### Effort estimé : 0.5-1 jour

### Acceptation
- Drop de fichier dans /docs_in → ClaimFirst processé automatiquement
- Claims présents dans Neo4j après import auto

---

## P3.3 — Qwen2.5-14B dégénérescence ClaimFirst

### Symptôme
Sur le doc WEF Presidio :
- 148 batches LLM
- 433 erreurs JSON / format
- 0 claims persisté (corpus complet ou presque)
- Hallucinations cross-corpus (le LLM génère des claims SAP alors que le doc est WEF)

### Investigation effectuée
Mémoire `project_bug_qwen_degeneration_claimfirst.md` :
- Suspect 1 : prompt ClaimFirst trop long ou ambigu → Qwen "perd le fil"
- Suspect 2 : context bleed entre batches (cache vLLM ?)
- Suspect 3 : modèle Qwen2.5-14B en limite cognitive

### Plan de fix (3 voies)
1. **Audit prompt** : isoler le prompt ClaimFirst, le passer à Qwen3-235B en bench, voir si le problème persiste
2. **Si prompt OK** : suspecter cache prefix vLLM → flush prefix cache entre batches
3. **Si toujours problème** : migration extracteur vers Qwen3-235B (plus stable, déjà budget validé via memory `project_llm_model_optimization.md`)

### Effort estimé : 2-3 jours (investigation + bench + fix)

### Acceptation
- ClaimFirst sur WEF Presidio retourne ≥ 100 claims
- 0 hallucination cross-corpus (validation manuelle 20 claims sample)

---

## P3.4 — Facet linkage bloqué à 27%

### Symptôme
Mémoire `project_facet_linkage_chantier.md` :
- 3 tentatives d'amélioration ont empiré (15.4%, 21.2%)
- État actuel : ~27% des claims ont une relation BELONGS_TO_FACET

### Investigation effectuée
- Le code actuel utilise un matching lexical/embedding mixte qui foire
- Recommandation pré-existante : passer à embedding similarity sur facet.canonical_question

### Plan de fix
1. Étudier `src/knowbase/facets/` et localiser le module de linkage
2. Implémenter linker basé sur cosine similarity entre embedding(claim) et embedding(facet.canonical_question), seuil 0.65
3. Backfill rétroactif sur les 40K claims actuels
4. Mesurer linkage rate cible ≥ 60%

### Effort estimé : 2-3 jours

### Acceptation
- Linkage rate ≥ 60% sur le corpus complet
- Pas de régression sur les facets existantes (échantillon manuel 30 facets)

---

## P3.5 — Bench Qwen3-235B sur extraction claims

### But
Si P3.3 ne résout pas Qwen2.5-14B → migration vers Qwen3-235B comme extracteur. Économie potentielle ~80% sur poste extraction (coût DeepInfra).

### Plan
1. Échantillon 5 docs représentatifs (CS-25, dual-use, SAP, médical, WEF Presidio)
2. Lancer ClaimFirst extraction sur chaque doc avec Qwen2.5-14B (baseline) puis Qwen3-235B
3. Mesurer : nb claims, taux JSON valide, hallucination cross-corpus, qualité claim (échantillon manuel)
4. Décision migration si Qwen3-235B ≥ Qwen2.5-14B + plus stable

### Effort estimé : 1 jour bench + 0.5 jour analyse

### Acceptation
- Rapport bench dans `data/forensics/qwen3_extraction_bench_<ts>.json`
- Décision documentée dans memory `project_llm_model_optimization.md`

---

## Ordonnancement P3

Ordre d'attaque recommandé (dépendances + valeur immédiate) :

1. **P3.2 dispatcher /docs_in** (0.5-1 jour) — débloque les imports auto, simple
2. **P3.1 cache markdown** (1 jour) — débloque format `.md` qui sera utile
3. **P3.4 facet linkage** (2-3 jours) — améliore qualité KG mesurable
4. **P3.3 Qwen dégénérescence** (2-3 jours) — investigation bug, peut révéler P3.5
5. **P3.5 bench Qwen3-235B** (1.5 jours) — conditionnel à P3.3

**Total P3** : 7-10 jours.
