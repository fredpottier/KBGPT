# Specification — Verify V2 : Document Review

**Date** : 2 avril 2026
**Statut** : Draft pour validation
**Objectif** : L'utilisateur uploade un document Word, OSMOSIS l'analyse phrase par phrase et retourne le meme document avec des annotations de type "review" sur tout ce qu'il a decouvert.

---

## 1. Vision produit

### Use case principal

L'utilisateur travaille sur un document (guide technique, proposition commerciale, rapport d'audit, note de synthese). Il veut savoir si ce document est coherent avec le corpus documentaire de reference de son organisation.

Il uploade le document. OSMOSIS l'analyse et retourne le **meme document** avec des commentaires dans la marge, exactement comme si un expert humain l'avait relu.

### Exemples de commentaires OSMOSIS

```
[OSMOSIS - Confirme] ✅
Ce point est confirme par le Security Guide 2023 (p.41).

[OSMOSIS - Contredit] ❌
Attention : le Security Guide 2023 indique "TLS 1.3" et non "TLS 1.2".
Source : SAP S/4HANA Security Guide 2023, section 14.

[OSMOSIS - Complete] ➕
Le corpus ajoute une precision importante : cette fonctionnalite
necessite egalement l'activation de SNC. Source : Operations Guide 2023.

[OSMOSIS - Nuance] ⚠️
Cette affirmation est correcte pour l'edition On-Premise mais le
Cloud Private Edition utilise un mecanisme different (SAML au lieu de SSO tickets).

[OSMOSIS - Non verifiable] ❓
Aucune information dans le corpus sur ce point. Verification manuelle recommandee.
```

### Differenciateur

Aucun outil RAG ne fait ca. ChatGPT/Copilot repondent a des questions. OSMOSIS **verifie des documents entiers** contre un corpus de reference. C'est le positionnement "Documentation Verification Platform".

---

## 2. Ce qui existe deja

### Backend (fonctionnel, a adapter)

| Composant | Fichier | Etat | A adapter |
|---|---|---|---|
| AssertionSplitter | `verification/assertion_splitter.py` | Fonctionnel | Limite 20 assertions / 15K chars → chunking par pages |
| EvidenceMatcher | `verification/evidence_matcher.py` | Fonctionnel | Ajouter exploitation C4/C6 relations |
| ComparisonEngine | `verification/comparison/` | Fonctionnel | OK tel quel |
| VerificationService | `api/services/verification_service.py` | Fonctionnel | Ajouter workflow Word |
| API /api/verify/analyze | `api/routers/verify.py` | Fonctionnel | Ajouter endpoint /upload-docx |
| API /api/verify/correct | `api/routers/verify.py` | Fonctionnel | OK |

### Frontend (existant, a refondre)

| Composant | Fichier | Etat |
|---|---|---|
| Page /verify | `app/verify/page.tsx` | Textarea + annotation HTML. Pas d'upload fichier. |
| AnnotatedText | `components/verify/AnnotatedText.tsx` | Highlights colores — garder |
| VerificationSummary | `components/verify/VerificationSummary.tsx` | Stats progress — garder |
| EvidencePopover | `components/verify/EvidencePopover.tsx` | Tooltip evidence — garder |

### Statuts existants (a conserver)

- ✅ `confirmed` — assertion confirmee par le corpus
- ❌ `contradicted` — assertion contredite avec preuve
- ⚠️ `incomplete` — information partielle (nuance, qualification)
- 📄 `fallback` — trouve dans Qdrant seulement (pas de claim structure)
- ❓ `unknown` — aucune information dans le corpus

---

## 3. Nouvelles fonctionnalites a implementer

### 3.1 Upload et traitement de documents Word

**Endpoint** : `POST /api/verify/upload-docx`

**Input** : fichier `.docx` (multipart/form-data)

**Processus** :
1. Extraire le texte du document avec `python-docx` (paragraphes avec positions)
2. Decouper en pages/sections (max 15K chars par batch pour le LLM)
3. Pour chaque batch : `AssertionSplitter.split()` → `EvidenceMatcher.find_evidence()`
4. Agreger les resultats
5. Generer le document Word annote avec commentaires

**Output** : fichier `.docx` annotated (download)

### 3.2 Annotation Word avec python-docx

**Librairie** : `python-docx >= 1.2.0` (supporte `document.add_comment()` natif)

**Code type** :
```python
from docx import Document

doc = Document("uploaded.docx")

for paragraph in doc.paragraphs:
    # Pour chaque assertion verifiee dans ce paragraphe
    for assertion in assertions_for_paragraph:
        if assertion.status == "contradicted":
            doc.add_comment(
                runs=find_runs_for_text(paragraph, assertion.text),
                text=f"[OSMOSIS - Contredit] ❌\n{assertion.evidence[0].explanation}\nSource : {assertion.evidence[0].source_doc}",
                author="OSMOSIS",
                initials="OS",
            )
        elif assertion.status == "confirmed":
            doc.add_comment(
                runs=find_runs_for_text(paragraph, assertion.text),
                text=f"[OSMOSIS - Confirme] ✅\nConfirme par {assertion.evidence[0].source_doc}",
                author="OSMOSIS",
                initials="OS",
            )
        # etc. pour incomplete, fallback, unknown

doc.save("annotated.docx")
```

**Le resultat** : un fichier Word standard avec des commentaires dans la marge, exactement comme si un humain avait fait une review. Ouvrable dans Word, Google Docs, LibreOffice.

### 3.3 Ameliorations du pipeline Verify

**a) Chunking par pages** : Le splitter actuel est limite a 15K chars / 20 assertions. Pour un document de 50 pages, il faut :
- Decouper le document en sections/pages
- Traiter chaque section independamment
- Fusionner les resultats

**b) Exploitation des relations C4/C6** : L'evidence_matcher cherche dans Neo4j claims puis fallback Qdrant. Il devrait aussi :
- Suivre les CONTRADICTS pour detecter les tensions connues
- Suivre les REFINES/QUALIFIES pour nuancer les verdicts
- Suivre les EVOLVES_TO pour signaler les evolutions entre versions

**c) Provider-aware** : Utiliser le meme LLM de synthese configure (GPT-4o-mini via OSMOSIS_SYNTHESIS_PROVIDER) au lieu de router par defaut.

### 3.4 Frontend — refonte page /verify

**Deux modes** :
1. **Mode texte** (existant, ameliore) : Coller un texte → annotation inline + evidence
2. **Mode document** (nouveau) : Upload .docx → traitement → download .docx annote

**Upload** :
- Drag & drop ou bouton "Choisir un fichier"
- Formats acceptes : .docx (Word), .txt (texte brut)
- Limite : 100 pages / 200K caracteres
- Progress bar pendant l'analyse
- Bouton "Telecharger le document annote" quand c'est fini

**Vue resultats** (en plus du download) :
- Resume : X confirmees, Y contredites, Z non verifiables
- Score de fiabilite global du document
- Liste des assertions par statut (filtrable)
- Clic sur une assertion → voir l'evidence et la source

---

## 4. Plugin Word (phase future)

### Architecture

Un **Office Add-in** (web-based, React + TypeScript + Office.js) qui s'affiche comme un panneau lateral dans Word.

### Fonctionnalites envisagees

1. **Verification de selection** : L'utilisateur selectionne un paragraphe, clique "Verifier" → OSMOSIS analyse et insere un commentaire directement dans le document
2. **Verification du document entier** : Un bouton "Analyser tout le document" qui fait le meme traitement que l'upload web
3. **Navigation des resultats** : Le panneau lateral liste toutes les assertions avec leur statut, cliquer sur une navigue vers l'endroit du document

### Stack technique

| Composant | Technologie |
|---|---|
| UI panneau | React + TypeScript (meme stack que le frontend OSMOSIS) |
| Interaction Word | Office.js (API JavaScript Word) |
| Appels API | fetch() vers l'API OSMOSIS existante |
| Build | Webpack (template Yeoman) |
| Distribution | Sideloading (dev) → Admin Center M365 (entreprise) |

### Scaffolding

```bash
npm install -g yo generator-office
yo office --projectType taskpane --name OsmosisVerify \
  --host word --ts true --framework react
```

### APIs Office.js utiles

```typescript
// Recuperer la selection
const selection = context.document.getSelection()
selection.load("text")
await context.sync()

// Inserer un commentaire
selection.insertComment("[OSMOSIS] Ce point est contredit par...")

// Surligner du texte
selection.font.highlightColor = Word.HighlightColor.yellow

// Rechercher du texte
const results = context.document.body.search("TLS 1.2")
results.load("text")
await context.sync()
```

### Effort estime

- MVP (selection + verification) : **2-3 jours**
- Version complete (document entier + navigation) : **1-2 semaines**
- Prerequis : API OSMOSIS accessible avec CORS configure

### Distribution

- **Dev/test** : sideloading (copier le manifest, zero friction)
- **Equipe** : Admin Center M365 (l'admin deploie pour le tenant)
- **Public** : Office Store AppSource (process Microsoft ~2-4 semaines)

---

## 5. Plan d'implementation

### Phase A — Backend Word processing (1 jour)

1. Ajouter `python-docx >= 1.2.0` dans requirements.txt
2. Creer `src/knowbase/verification/docx_processor.py`
   - Extraction texte par paragraphe avec mapping positions
   - Annotation du document avec commentaires
   - Mapping assertion → paragraphe → runs
3. Creer endpoint `POST /api/verify/upload-docx`
   - Accept multipart/form-data
   - Return fichier .docx annote (StreamingResponse)

### Phase B — Ameliorations pipeline (1 jour)

1. Chunking par sections pour documents longs
2. Exploitation relations C4/C6 dans evidence_matcher
3. Provider-aware (GPT-4o-mini au lieu de Qwen par defaut)

### Phase C — Frontend (1 jour)

1. Ajouter zone upload dans /verify (drag & drop)
2. Progress bar pendant l'analyse
3. Bouton download du document annote
4. Vue resultats en parallele (optionnel)

### Phase D — Plugin Word (futur, 1-2 semaines)

1. Scaffolding Office Add-in
2. Task pane React avec bouton "Verifier"
3. Integration API OSMOSIS
4. Distribution sideloading puis Admin Center

---

## 6. Questions ouvertes

1. Faut-il annoter TOUTES les assertions (y compris les confirmees) ou seulement les problematiques ?
   - Option A : tout annoter → document tres charge mais exhaustif
   - Option B : annoter seulement contredit + incomplete + unknown → plus lisible
   - Recommandation : Option B par defaut avec checkbox "Afficher aussi les confirmations"

2. Faut-il supporter le .pdf en plus du .docx ?
   - PDF est plus difficile (pas de commentaires natifs, layout complexe)
   - On pourrait generer un rapport PDF separe avec les annotations
   - Recommandation : .docx en V1, PDF en V2

3. Quelle limite de taille de document ?
   - Chaque assertion = 1 appel LLM (splitter) + 1 recherche KG/Qdrant
   - Un document de 100 pages = ~500 assertions = ~500 appels
   - Avec GPT-4o-mini : ~$0.50 par document de 100 pages
   - Recommandation : limite a 100 pages en V1, queue asynchrone pour les gros docs

---

*Specification pour validation. Implementation apres accord sur le scope.*
