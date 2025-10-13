# TODO : Migration Authentification JWT + Correction Pipeline PDF

**Date de création** : 2025-10-11
**Statut** : À faire
**Priorité** : Haute

---

## 📋 Vue d'ensemble

Ce document décrit deux tâches majeures à réaliser :
1. **Migration Frontend** : Centraliser l'authentification JWT avec intercepteur axios (15 fichiers)
2. **Correction Pipeline PDF** : Utiliser MegaParse pour découpage intelligent au lieu du traitement page par page

---

# PARTIE 1 : Migration Authentification JWT Frontend

## 🎯 Objectif

Migrer toutes les pages frontend pour utiliser l'intercepteur axios centralisé (`/lib/axios.ts`) afin de :
- ✅ Injection automatique du JWT token dans toutes les requêtes
- ✅ Auto-refresh du token en cas de 401
- ✅ Gestion centralisée des erreurs d'authentification
- ✅ Code plus propre et maintenable

## ✅ État Actuel

**Déjà migré :**
- ✅ `frontend/src/lib/axios.ts` - Intercepteur créé avec request/response interceptors
- ✅ `frontend/src/app/admin/document-types/new/page.tsx` - Page migrée et testée

**Architecture actuelle problématique :**
- 🔴 2 clients HTTP coexistent : ancien `api.ts` (classe ApiClient) + nouveau `axios.ts`
- 🔴 Beaucoup de `fetch()` manuels avec `authService.getAccessToken()`
- 🔴 Code dupliqué pour gestion JWT dans chaque page
- 🔴 Risque d'oublier le token lors de création de nouvelles fonctionnalités

## 📊 Statistiques

- **Total fichiers à migrer** : 15 fichiers
- **API Routes Next.js** : ~40 fichiers (déjà corrects, pas de migration nécessaire)
- **Temps estimé** : 8-11 heures

---

## 🔴 PHASE 1 : Pages Critiques (Priorité URGENTE)

### 1.1 `frontend/src/app/admin/dynamic-types/[typeName]/page.tsx`
**Priorité** : 🔴 CRITIQUE (plus gros fichier)

**Statistiques** :
- 20+ endpoints différents
- 300+ lignes de code
- Pattern répété : `authService.getAccessToken()` + `fetch()` partout

**Endpoints concernés** :
```typescript
GET    /api/entity-types/:typeName/ontology-proposal
GET    /api/entity-types
GET    /api/entity-types/:typeName/snapshots
GET    /api/entity-types/:typeName
GET    /api/entities?entity_type=...&status=...
POST   /api/entity-types/:typeName/ontology-proposal
POST   /api/entity-types/:typeName/generate-ontology
POST   /api/entity-types/:typeName/normalize-entities
GET    /api/jobs/:id/status
POST   /api/entities/:uuid/approve
POST   /api/entities/:uuid/change-type
POST   /api/entity-types/:typeName/undo-normalization
POST   /api/entity-types/:typeName/merge-into/:targetType
POST   /api/entities/:uuid/merge
POST   /api/entities/bulk-change-type
// ... et bien d'autres
```

**Migration** :
- Remplacer tous les `authService.getAccessToken()` + `fetch()` par `axiosInstance.get/post/put/delete()`
- Supprimer l'import `authService`
- Adapter la gestion des réponses (axios retourne `response.data`)

---

### 1.2 `frontend/src/app/admin/dynamic-types/page.tsx`
**Priorité** : 🔴 CRITIQUE

**Endpoints concernés** :
```typescript
GET    /api/entity-types?status=...
POST   /api/entity-types/:typeName/approve
POST   /api/entity-types/:typeName/reject
POST   /api/entity-types/import-yaml (FormData)
GET    /api/entity-types/export-yaml?status=...
```

**Lignes concernées** : 14, 83, 100, 123, 135, 171, 183, 228, 244, 281, 294

**Migration** :
- Supprimer pattern répété `authService.getAccessToken()` + `fetch()`
- Remplacer par `axiosInstance`

---

### 1.3 `frontend/src/app/documents/import/page.tsx`
**Priorité** : 🔴 CRITIQUE (page d'import principale)

**Endpoints concernés** :
```typescript
GET    /api/document-types?is_active=true
POST   /api/dispatch (FormData - upload de documents)
```

**Lignes concernées** : 30, 116, 131, 172, 174

**Migration** :
- Remplacer fetch manuel par `axiosInstance.post()` pour upload
- FormData géré automatiquement par axios

---

### 1.4 `frontend/src/app/rfp-excel/page.tsx`
**Priorité** : 🔴 CRITIQUE (workflow RFP complet)

**Endpoints concernés** :
```typescript
POST   /api/documents/analyze-excel (FormData)
POST   /api/documents/upload-excel-qa (FormData)
POST   /api/documents/fill-rfp-excel (FormData)
```

**Lignes concernées** : 50, 147, 163, 311, 341

**Migration** :
- Remplacer tous les fetch FormData par `axiosInstance.post()`

---

### 1.5 `frontend/src/app/chat/page.tsx`
**Priorité** : 🔴 CRITIQUE (interface chat principale)

**Endpoints concernés** :
```typescript
GET    /api/solutions
POST   /api/search (body: {question, language, mime, solution})
```

**Lignes concernées** : 23, 47, 111

**Migration** :
- Remplacer `api.search.solutions()` par `axiosInstance.get('/api/solutions')`
- Remplacer `api.chat.send()` par `axiosInstance.post('/api/search', data)`

---

### 1.6 `frontend/src/app/documents/status/page.tsx`
**Priorité** : 🔴 CRITIQUE (suivi des imports)

**Endpoints concernés** :
```typescript
GET    /api/imports/history
GET    /api/imports/active
GET    /api/status/:uid
DELETE /api/imports/:uid
```

**Lignes concernées** : 47, 96, 108, 168, ~250+

**Migration** :
- Remplacer tous les helpers `api.imports.*` et `api.status.*` par `axiosInstance`

---

## 🟡 PHASE 2 : Pages Secondaires (Priorité HAUTE)

### 2.1 `frontend/src/app/admin/document-types/page.tsx`
**Endpoints** : `GET /api/document-types`, `DELETE /api/document-types/:id`
**Lignes** : 29, 53, 60

### 2.2 `frontend/src/app/admin/documents/page.tsx`
**Endpoints** : `GET /api/documents/list?status=...&document_type=...&limit=...&offset=...`
**Lignes** : 44, 62-67

### 2.3 `frontend/src/app/admin/documents/[id]/compare/page.tsx`
**Endpoints** : `GET /api/documents/:id/versions`

### 2.4 `frontend/src/app/admin/documents/[id]/timeline/page.tsx`
**Endpoints** : `GET /api/documents/:id`, `GET /api/documents/:id/versions`

### 2.5 `frontend/src/app/admin/page.tsx`
**Endpoints** : `GET /api/admin/monitoring/stats`

### 2.6 `frontend/src/app/documents/upload/page.tsx`
**Endpoints** : `POST /api/dispatch` (FormData)

### 2.7 `frontend/src/app/documents/[id]/page.tsx`
**Endpoints** : `GET /api/documents/:id`, `DELETE /api/documents/:id`

---

## 🟢 PHASE 3 : Composants UI (Priorité MOYENNE)

### 3.1 `frontend/src/components/ui/SAPSolutionSelector.tsx`
**Endpoints** :
```typescript
GET    /api/sap-solutions
GET    /api/sap-solutions/with-chunks?extend_search=...
POST   /api/sap-solutions/resolve
```

**Lignes** : 30, 72, 91, 143, 156

---

## 🧹 PHASE 4 : Nettoyage Final

1. **Supprimer l'ancien client** : `frontend/src/lib/api.ts` (classe ApiClient)
2. **Mettre à jour CLAUDE.md** : Documenter que `axiosInstance` est le client HTTP unique
3. **Vérifier imports** : S'assurer qu'aucun fichier n'importe encore `api.ts`
4. **Tests de régression** : Tester toutes les pages migrées

---

## 📝 Pattern de Migration Type

### ❌ AVANT (ancien pattern avec api.ts)
```typescript
import { api } from '@/lib/api'

const { data } = useQuery({
  queryKey: ['documents'],
  queryFn: () => api.documents.list({ status: 'active' })
})
```

### ❌ AVANT (fetch manuel avec authService)
```typescript
import { authService } from '@/lib/auth'

const token = authService.getAccessToken()
const response = await fetch('/api/entity-types', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
})
```

### ✅ APRÈS (avec intercepteur centralisé)
```typescript
import axiosInstance from '@/lib/axios'

const { data } = useQuery({
  queryKey: ['documents'],
  queryFn: async () => {
    const response = await axiosInstance.get('/api/documents', {
      params: { status: 'active' }
    })
    return response.data
  }
})
```

**Avantages** :
- ✅ JWT injecté automatiquement
- ✅ Auto-refresh du token si 401
- ✅ Gestion centralisée des erreurs
- ✅ Timeout configurable par requête
- ✅ Code plus propre et maintenable

---

## ⚠️ Points d'Attention

### 1. Gestion des FormData
L'intercepteur axios gère automatiquement le `Content-Type` pour FormData :
```typescript
// Pas besoin de définir Content-Type manuellement
const formData = new FormData()
formData.append('file', file)

await axiosInstance.post('/api/dispatch', formData)
// axios détecte FormData et configure les headers automatiquement
```

### 2. Gestion des Erreurs
L'intercepteur gère déjà les 401 (auto-refresh) :
```typescript
try {
  const response = await axiosInstance.get('/api/data')
  // Si 401, le refresh est automatique
} catch (error) {
  // Gérer uniquement les autres erreurs
}
```

### 3. Contexte AuthContext
Le `AuthContext` utilise toujours `authService` pour login/logout/register - **NE PAS MIGRER** ces appels car ce sont des opérations d'authentification initiales qui ne peuvent pas utiliser l'intercepteur.

---

## ✅ Checklist de Migration par Fichier

Pour chaque fichier :
- [ ] Remplacer `import { api/apiClient } from '@/lib/api'` par `import axiosInstance from '@/lib/axios'`
- [ ] Supprimer `import { authService } from '@/lib/auth'` (sauf pour login/logout)
- [ ] Remplacer tous les `authService.getAccessToken()` + `fetch()` par `axiosInstance.get/post/put/delete()`
- [ ] Remplacer tous les `api.xxx()` ou `apiClient.xxx()` par `axiosInstance.xxx()`
- [ ] Adapter la gestion des réponses (axios retourne `response.data` directement)
- [ ] Tester la page/composant manuellement
- [ ] Vérifier que le JWT est bien injecté (DevTools Network)
- [ ] Vérifier que le refresh automatique fonctionne en cas de token expiré

---

# PARTIE 2 : Correction Pipeline PDF avec MegaParse

## 🚨 Problème Identifié

### Symptômes (logs worker)
```
Page 21 [TEXT-ONLY]: 0 concepts + 0 facts + 16 entities + 0 relations
Page 22 [TEXT-ONLY]: 0 concepts + 0 facts + 19 entities + 0 relations
Page 23 [TEXT-ONLY]: 0 concepts + 0 facts + 17 entities + 0 relations
...
```

### Causes Racines

#### 1. Traitement Page par Page (Anti-Pattern)
**Fichier** : `src/knowbase/ingestion/pipelines/pdf_pipeline.py`
**Lignes** : 420-441

```python
# ❌ PROBLÈME : Boucle sur chaque page individuellement
for page_index, img_path in image_paths.items():
    logger.info(f"Page {page_index}/{len(image_paths)}")

    if use_vision:
        chunks = ask_gpt_slide_analysis(img_path, pdf_text, pdf_path.name, page_index, custom_prompt)
    else:
        # Mode TEXT-ONLY : Analyse page par page sans contexte cohérent
        result = ask_gpt_page_analysis_text_only(pdf_text, pdf_path.name, page_index, custom_prompt)
        concepts = result.get("concepts", [])
```

**Problème** : Une page PDF ne correspond pas à un bloc sémantique cohérent :
- Une page peut contenir plusieurs sections sans rapport
- Un concept peut s'étendre sur plusieurs pages
- Les relations entre entités sont perdues si elles sont sur des pages différentes

#### 2. MegaParse Installé mais Non Utilisé
**MegaParse est disponible** (confirmé par logs startup) :
```
2025-10-11 21:20:48,165 INFO: ✅ MegaParse disponible
```

**Mais jamais utilisé** dans le pipeline PDF !

MegaParse permet de :
- ✅ Découper le PDF en **blocs sémantiques cohérents** (sections, paragraphes, tableaux)
- ✅ Préserver la **structure du document**
- ✅ Identifier les **titres, sous-titres, listes**
- ✅ Extraire les **tableaux structurés**
- ✅ Gérer les **multi-colonnes**

#### 3. Modèle LLM Trop Faible
**Fichier** : `src/knowbase/ingestion/pipelines/pdf_pipeline.py:225`

```python
# Utilise TaskType.LONG_TEXT_SUMMARY qui mappe vers gpt-4o-mini
raw = llm_router.complete(TaskType.LONG_TEXT_SUMMARY, messages, temperature=0.2, max_tokens=8000)
```

**Configuration** : `config/llm_models.yaml:16`
```yaml
long_summary: "gpt-4o-mini"
```

**Problème** :
- `gpt-4o-mini` est un modèle économique mais **moins performant** pour extraction complexe
- Le prompt demande concepts + facts + entities + relations
- Mais le modèle ne trouve que les entités (cas le plus simple)

#### 4. Prompt Non Adapté au Contexte Page-by-Page
**Fichier** : `src/knowbase/ingestion/pipelines/pdf_pipeline.py:189-212`

Le prompt demande :
```
Extract structured knowledge from this page and return a JSON object with 4 keys:
- concepts: Array of concept blocks
- facts: Array of factual statements
- entities: Array of named entities
- relations: Array of relationships between entities
```

**Problème** : Le prompt ne peut pas fonctionner correctement car :
- ❌ Il analyse une **page arbitraire** sans contexte des pages précédentes/suivantes
- ❌ Les concepts qui s'étendent sur plusieurs pages sont fragmentés
- ❌ Les relations entre entités sur différentes pages sont impossibles à détecter
- ❌ Le modèle gpt-4o-mini n'est pas assez puissant pour cette tâche complexe

---

## ✅ Solution Proposée : Pipeline PDF Intelligent avec MegaParse

### Architecture Cible

```
PDF Input
    ↓
MegaParse Parser
    ↓ (découpe en blocs sémantiques)
Blocs Cohérents
    ├─ Sections (avec titres)
    ├─ Paragraphes (texte continu)
    ├─ Tableaux (structurés)
    └─ Listes (ordonnées/non ordonnées)
    ↓
LLM Analysis (par bloc cohérent, pas par page)
    ↓ (extraction concepts/facts/entities/relations)
Knowledge Graph
    ↓
Qdrant Vectorization
```

### Étapes de Refactoring

#### Étape 1 : Intégrer MegaParse pour Découpage Intelligent

**Créer** : `src/knowbase/ingestion/parsers/megaparse_pdf.py`

```python
from megaparse import MegaParse
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def parse_pdf_with_megaparse(pdf_path: Path) -> list[dict]:
    """
    Utilise MegaParse pour découper un PDF en blocs sémantiques cohérents.

    Returns:
        List of semantic blocks with:
        - block_type: "section" | "paragraph" | "table" | "list"
        - title: Optional heading (for sections)
        - content: Text content
        - page_range: (start_page, end_page)
        - metadata: Additional structural info
    """
    logger.info(f"🔍 MegaParse: analyse {pdf_path.name}")

    parser = MegaParse()
    document = parser.parse(str(pdf_path))

    blocks = []
    for elem in document.elements:
        block = {
            "block_type": elem.type,  # section, paragraph, table, list
            "title": getattr(elem, "title", None),
            "content": elem.text,
            "page_range": (elem.start_page, elem.end_page),
            "metadata": {
                "level": getattr(elem, "level", 0),  # Heading level (H1, H2, etc.)
                "style": getattr(elem, "style", None),
            }
        }
        blocks.append(block)

    logger.info(f"✅ MegaParse: {len(blocks)} blocs sémantiques extraits")
    return blocks
```

#### Étape 2 : Refactoriser `process_pdf()` pour Utiliser les Blocs

**Modifier** : `src/knowbase/ingestion/pipelines/pdf_pipeline.py:363-469`

```python
def process_pdf(pdf_path: Path, document_type_id: str | None = None, use_vision: bool = True):
    logger.info(f"🚀 Traitement: {pdf_path.name}")
    logger.info(f"📋 Document Type ID: {document_type_id or 'default'}")
    logger.info(f"🔍 Mode extraction: {'VISION (GPT-4 avec images)' if use_vision else 'TEXT-ONLY (MegaParse + LLM)'}")

    # ... (métadonnées, prompt contextualisé - inchangé)

    if use_vision:
        # ✅ Mode VISION : Conserver traitement page par page avec images
        logger.info("🖼️ Mode VISION: Génération PNG des pages")
        images = convert_from_path(str(pdf_path))
        image_paths = {}
        for i, img in enumerate(images, start=1):
            img_path = SLIDES_PNG / f"{pdf_path.stem}_page_{i}.png"
            img.save(img_path, "PNG")
            image_paths[i] = img_path

        total_chunks = 0
        for page_index, img_path in image_paths.items():
            logger.info(f"Page {page_index}/{len(image_paths)}")
            chunks = ask_gpt_slide_analysis(img_path, pdf_text, pdf_path.name, page_index, custom_prompt)
            logger.info(f"Page {page_index} [VISION]: chunks = {len(chunks)}")
            ingest_chunks(chunks, doc_meta, pdf_path.stem, page_index)
            total_chunks += len(chunks)
    else:
        # ✅ Mode TEXT-ONLY : Utiliser MegaParse pour découpage intelligent
        from knowbase.ingestion.parsers.megaparse_pdf import parse_pdf_with_megaparse

        logger.info("📚 Mode TEXT-ONLY: Découpage MegaParse en blocs sémantiques")
        semantic_blocks = parse_pdf_with_megaparse(pdf_path)

        total_chunks = 0
        for block_index, block in enumerate(semantic_blocks, start=1):
            logger.info(f"Bloc {block_index}/{len(semantic_blocks)} [{block['block_type']}]: {block.get('title', 'Sans titre')}")

            # Analyser chaque bloc sémantique (au lieu de chaque page)
            result = ask_gpt_block_analysis_text_only(
                block_content=block['content'],
                block_type=block['block_type'],
                block_title=block.get('title'),
                source_name=pdf_path.name,
                block_index=block_index,
                custom_prompt=custom_prompt
            )

            concepts = result.get("concepts", [])
            facts = result.get("facts", [])
            entities = result.get("entities", [])
            relations = result.get("relations", [])

            logger.info(f"Bloc {block_index} [TEXT-ONLY]: {len(concepts)} concepts + {len(facts)} facts + {len(entities)} entities + {len(relations)} relations")

            # Ingest avec référence au bloc sémantique (pas à une page)
            chunks_compat = [
                {
                    "text": c.get("full_explanation", ""),
                    "meta": {
                        **c.get("meta", {}),
                        "block_type": block['block_type'],
                        "block_title": block.get('title'),
                        "page_range": block['page_range']
                    }
                }
                for c in concepts
            ]
            ingest_chunks(chunks_compat, doc_meta, pdf_path.stem, block_index)
            total_chunks += len(chunks_compat)

            # Heartbeat tous les 5 blocs
            if block_index % 5 == 0:
                try:
                    from knowbase.ingestion.queue.jobs import send_worker_heartbeat
                    send_worker_heartbeat()
                except Exception:
                    pass

    # ... (déplacement fichier, status - inchangé)
```

#### Étape 3 : Créer `ask_gpt_block_analysis_text_only()`

**Ajouter** : `src/knowbase/ingestion/pipelines/pdf_pipeline.py`

```python
def ask_gpt_block_analysis_text_only(
    block_content: str,
    block_type: str,
    block_title: str | None,
    source_name: str,
    block_index: int,
    custom_prompt: str | None = None,
):
    """
    Analyse un BLOC SÉMANTIQUE (section, paragraph, table, list) extrait par MegaParse.
    Plus intelligent que l'analyse page par page.
    """
    logger.info(f"🧠 GPT [TEXT-ONLY]: analyse bloc #{block_index} [{block_type}]")

    try:
        # Prompt adapté au type de bloc
        if custom_prompt:
            analysis_text = custom_prompt.replace("{slide_content}", block_content).replace("{slide_index}", str(block_index)).replace("{source_name}", source_name)
        else:
            block_context = f"Block type: {block_type}"
            if block_title:
                block_context += f"\nBlock title: {block_title}"

            analysis_text = (
                f"You are analyzing a semantic block (block #{block_index}) from '{source_name}'.\n"
                f"{block_context}\n\n"
                f"Block content:\n{block_content}\n\n"
                "Extract structured knowledge from this semantic block and return a JSON object with 4 keys:\n"
                "- `concepts`: Array of concept blocks (main ideas, explanations)\n"
                "  - `full_explanation`: string (detailed description)\n"
                "  - `meta`: object with `type`, `level`, `topic`\n"
                "- `facts`: Array of factual statements\n"
                "  - `subject`: string\n"
                "  - `predicate`: string\n"
                "  - `value`: string/number\n"
                "  - `confidence`: number (0-1)\n"
                "  - `fact_type`: string (optional)\n"
                "- `entities`: Array of named entities\n"
                "  - `name`: string\n"
                "  - `entity_type`: string (e.g., 'SOLUTION', 'COMPONENT', 'TECHNOLOGY')\n"
                "  - `description`: string (optional)\n"
                "- `relations`: Array of relationships between entities\n"
                "  - `source`: string (entity name)\n"
                "  - `relation_type`: string (e.g., 'PART_OF', 'USES', 'IMPLEMENTS')\n"
                "  - `target`: string (entity name)\n"
                "  - `description`: string (optional)\n\n"
                "Important: This is a SEMANTIC BLOCK, not just a page. "
                "Extract all concepts, facts, entities, and relations that are COMPLETE within this block. "
                "If a concept spans multiple blocks, extract only the part contained in this block.\n\n"
                "Return only valid JSON."
            )

        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": "You are an expert knowledge extraction assistant. Analyze semantic blocks (sections, paragraphs, tables, lists) to extract concepts, facts, entities, and relations. Focus on completeness and accuracy.",
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": analysis_text,
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]

        # ✅ Utiliser un modèle plus puissant pour extraction complexe
        # Option 1: Garder gpt-4o-mini mais avec max_tokens plus élevé
        # Option 2: Utiliser gpt-4o (plus coûteux mais meilleur)
        # Option 3: Utiliser claude-3-haiku (bon compromis coût/qualité)
        raw = llm_router.complete(
            TaskType.LONG_TEXT_SUMMARY,  # Ou créer TaskType.KNOWLEDGE_EXTRACTION
            messages,
            temperature=0.2,
            max_tokens=12000  # Augmenté pour permettre extraction complète
        )

        logger.debug(f"Bloc {block_index} [TEXT-ONLY]: LLM raw response (first 500 chars): {raw[:500] if raw else 'EMPTY'}")

        cleaned = clean_gpt_response(raw)
        response_data = json.loads(cleaned) if cleaned else {}

        # Parser la réponse
        if isinstance(response_data, dict):
            concepts = response_data.get("concepts", [])
            facts_data = response_data.get("facts", [])
            entities_data = response_data.get("entities", [])
            relations_data = response_data.get("relations", [])
        else:
            logger.warning(f"Bloc {block_index} [TEXT-ONLY]: Format JSON inattendu: {type(response_data)}")
            concepts = []
            facts_data = []
            entities_data = []
            relations_data = []

        logger.debug(f"Bloc {block_index} [TEXT-ONLY]: {len(concepts)} concepts + {len(facts_data)} facts + {len(entities_data)} entities + {len(relations_data)} relations")

        # 📊 Ingest facts, entities, relations dans le knowledge graph
        # TODO: Implémenter l'ingestion dans Neo4j/Graphiti si activé

        return {
            "concepts": concepts,
            "facts": facts_data,
            "entities": entities_data,
            "relations": relations_data,
        }
    except Exception as e:
        logger.error(f"❌ GPT bloc {block_index} [TEXT-ONLY] error: {e}")
        return {
            "concepts": [],
            "facts": [],
            "entities": [],
            "relations": [],
        }
```

#### Étape 4 : Optimiser la Configuration LLM

**Option A** : Augmenter les capacités de `long_summary`

Modifier `config/llm_models.yaml:16` :
```yaml
# Avant
long_summary: "gpt-4o-mini"

# Après (meilleur compromis)
long_summary: "claude-3-haiku-20240307"
```

**OU créer une nouvelle tâche spécifique** :

Ajouter dans `config/llm_models.yaml` :
```yaml
task_models:
  # ... (existant)

  # Nouvelle tâche pour extraction de connaissance structurée
  knowledge_extraction: "claude-3-haiku-20240307"  # Ou "gpt-4o" pour qualité max

task_parameters:
  # ... (existant)

  knowledge_extraction:
    temperature: 0.2
    max_tokens: 12000  # Permettre extraction complète de blocs longs
```

Puis ajouter dans `src/knowbase/common/llm_router.py` :
```python
class TaskType(str, Enum):
    # ... (existant)
    KNOWLEDGE_EXTRACTION = "knowledge_extraction"
```

---

## 🎯 Résultats Attendus Après Correction

### Avant (page par page)
```
Page 21 [TEXT-ONLY]: 0 concepts + 0 facts + 16 entities + 0 relations
Page 22 [TEXT-ONLY]: 0 concepts + 0 facts + 19 entities + 0 relations
Page 23 [TEXT-ONLY]: 0 concepts + 0 facts + 17 entities + 0 relations
```

### Après (blocs sémantiques)
```
Bloc 1 [section]: "Introduction to SAP S/4HANA"
  → 3 concepts + 8 facts + 12 entities + 15 relations

Bloc 2 [paragraph]: "Architecture Overview"
  → 2 concepts + 5 facts + 8 entities + 10 relations

Bloc 3 [table]: "Module Comparison Table"
  → 1 concept + 12 facts + 6 entities + 8 relations

Bloc 4 [list]: "Deployment Options"
  → 1 concept + 4 facts + 4 entities + 3 relations
```

**Améliorations** :
- ✅ Concepts et facts extraits correctement
- ✅ Relations entre entités détectées
- ✅ Structuration cohérente du knowledge graph
- ✅ Meilleure qualité de recherche vectorielle

---

## ✅ Checklist d'Implémentation

### Phase 1 : Préparation
- [ ] Vérifier que MegaParse est bien installé dans requirements.txt
- [ ] Tester MegaParse sur un PDF sample pour valider l'API
- [ ] Créer `src/knowbase/ingestion/parsers/megaparse_pdf.py`

### Phase 2 : Refactoring
- [ ] Créer `ask_gpt_block_analysis_text_only()` dans `pdf_pipeline.py`
- [ ] Modifier `process_pdf()` pour utiliser MegaParse en mode TEXT-ONLY
- [ ] Conserver le mode VISION (page par page) inchangé
- [ ] Ajouter `TaskType.KNOWLEDGE_EXTRACTION` dans `llm_router.py`
- [ ] Configurer `knowledge_extraction` dans `llm_models.yaml`

### Phase 3 : Tests
- [ ] Tester import PDF avec `use_vision=False` sur document sample
- [ ] Vérifier logs : concepts + facts + entities + relations > 0
- [ ] Vérifier Qdrant : chunks avec métadonnées de blocs sémantiques
- [ ] Comparer qualité de recherche avant/après

### Phase 4 : Optimisation
- [ ] Ajuster `max_tokens` si besoin
- [ ] Tester différents modèles LLM (gpt-4o-mini vs claude-haiku vs gpt-4o)
- [ ] Optimiser découpage MegaParse si nécessaire

---

## 📊 Comparaison Performance Attendue

| Méthode | Concepts | Facts | Entities | Relations | Coût | Qualité |
|---------|----------|-------|----------|-----------|------|---------|
| **VISION (GPT-4o + images)** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 💰💰💰💰💰 | ⭐⭐⭐⭐⭐ |
| **TEXT-ONLY Page-by-Page (ACTUEL)** | ❌ | ❌ | ⭐⭐⭐ | ❌ | 💰 | ⭐⭐ |
| **TEXT-ONLY MegaParse (PROPOSÉ)** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 💰💰 | ⭐⭐⭐⭐ |

**Conclusion** : MegaParse offre un excellent compromis coût/qualité pour le mode TEXT-ONLY.

---

## 🔗 Références

- **MegaParse Documentation** : https://github.com/quivrhq/megaparse
- **LLM Router** : `src/knowbase/common/llm_router.py`
- **Configuration LLM** : `config/llm_models.yaml`
- **Pipeline PDF Actuel** : `src/knowbase/ingestion/pipelines/pdf_pipeline.py`

---

**Fin du document** - Dernière mise à jour : 2025-10-11
