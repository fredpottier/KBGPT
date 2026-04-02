# Specification — Verify V2/V3 : Document Review & Critique Documentaire

**Date** : 2 avril 2026
**Statut** : Draft pour validation
**Objectif** : L'utilisateur uploade un document Word, OSMOSIS l'analyse, le confronte au corpus documentaire et retourne le meme document avec des annotations de type "review" — pas juste des verifications d'assertions mais une vraie critique documentaire structuree.

---

## 1. Vision produit

### Le shift conceptuel

Le Verify actuel verifie des **assertions isolees** : chaque phrase est comparee au corpus independamment. C'est du "spellcheck intelligent".

La cible est un **moteur de critique documentaire** qui :
- **Positionne** chaque affirmation dans le paysage documentaire (qui dit quoi, depuis quand, dans quel contexte)
- **Detecte les tensions** entre le document et le corpus (pas juste "vrai/faux" mais "Doc A dit X, Doc B dit Y, vous dites Z")
- **Detecte les incoherences internes** du document lui-meme
- **Evalue la completude** : ce que le document ne dit pas mais devrait dire

Ce n'est pas un verificateur de faits. C'est un **systeme qui challenge intellectuellement un document**.

### Use case

L'utilisateur travaille sur un document (guide technique, proposition commerciale, rapport d'audit). Il uploade le document. OSMOSIS le confronte au corpus et retourne le **meme document** avec des commentaires dans la marge, comme si un expert du domaine l'avait relu avec acces a toute la documentation de reference.

### Niveaux d'analyse (V1 → V3)

| Niveau | Description | Phase |
|---|---|---|
| **Assertion** | Chaque phrase verifiee contre le corpus | V1 |
| **Position documentaire** | Chaque affirmation situee dans le paysage (Doc A vs Doc B vs Doc C) | V2 |
| **Coherence interne** | Le document se contredit-il lui-meme ? | V3 |
| **Completude** | Que manque-t-il ? Quels sujets connexes ne sont pas couverts ? | V3 |

### Exemples de commentaires par niveau

**Niveau 1 — Assertion (V1)** :
```
[OSMOSIS - Contredit] ❌
Le Security Guide 2023 indique "TLS 1.3" et non "TLS 1.2".
Source : SAP S/4HANA Security Guide 2023, section 14.
```

**Niveau 2 — Position documentaire (V2)** :
```
[OSMOSIS - Position documentaire] ⚖️
Votre affirmation : "TLS 1.2 est requis"

Le corpus montre des positions differentes selon les documents :
• Security Guide 2023 → TLS 1.3 obligatoire (plus recent)
• Security Guide 2022 → TLS 1.2 acceptable
• Operations Guide 2023 → TLS 1.2 uniquement pour backward compatibility

Conclusion : votre affirmation correspond a la position 2022 mais est
obsolete par rapport au Security Guide 2023.
```

**Niveau 3 — Coherence interne (V3)** :
```
[OSMOSIS - Incoherence interne] ⚠️
Votre document affirme "TLS 1.2 requis" (page 3) mais mentionne
"migration vers TLS 1.3 terminee" (page 12). Ces deux affirmations
sont contradictoires. Verifiez quelle version est a jour.
```

**Niveau 3 — Completude (V3)** :
```
[OSMOSIS - Information manquante] 📋
Votre document traite de la securite des connexions RFC mais ne mentionne
pas SNC (Secure Network Communications) qui est systematiquement associe
aux RFC dans la documentation de reference (5 documents sur 5 le mentionnent).
```

### Differenciateur

Aucun outil RAG ne fait ca. ChatGPT/Copilot repondent a des questions. OSMOSIS **critique des documents entiers** en les positionnant dans un espace documentaire structure. C'est le positionnement "Documentation Verification Platform".

Le KG (2400+ relations C4/C6) est le moteur de cette critique — il contient deja les positions contradictoires, les evolutions, les complements. On l'exploite comme **moteur de raisonnement**, pas juste comme source d'evidence.

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

## 5. Plan d'implementation en 3 versions

### V1 — Upload Word + verification assertion-level (3 jours)

Le pipeline existant (AssertionSplitter → EvidenceMatcher → ComparisonEngine) est reutilise. On ajoute l'entree/sortie Word.

**Backend (1 jour)** :
1. Ajouter `python-docx >= 1.2.0` dans requirements.txt
2. Creer `src/knowbase/verification/docx_processor.py`
   - Extraction texte par paragraphe avec mapping positions
   - Annotation du document avec commentaires
   - Mapping assertion → paragraphe → runs
3. Creer endpoint `POST /api/verify/upload-docx`
   - Accept multipart/form-data
   - Return fichier .docx annote (StreamingResponse)

**Pipeline (1 jour)** :
1. Chunking par sections pour documents longs (> 15K chars)
2. Provider-aware (GPT-4o-mini au lieu de Qwen par defaut)
3. Augmenter la limite d'assertions (20 → 50 par section)

**Frontend (1 jour)** :
1. Ajouter zone upload dans /verify (drag & drop)
2. Progress bar pendant l'analyse (WebSocket ou polling)
3. Bouton download du document annote
4. Vue resultats en parallele (existant, ameliore)

**Livrable V1** : Un .docx annote avec des commentaires type "confirme/contredit/incomplet/inconnu" par assertion. Fonctionnel mais basique.

### V2 — Position documentaire + KG-driven (1 semaine)

Le moteur de verification exploite les relations C4/C6 pour positionner chaque affirmation dans le paysage documentaire.

**Enrichissement evidence_matcher** :
1. Pour chaque assertion matchee dans le KG, suivre les relations :
   - CONTRADICTS → trouver les positions contradictoires connues
   - REFINES/QUALIFIES → trouver les nuances et conditions
   - EVOLVES_TO → identifier les evolutions entre versions
   - COMPLEMENTS → trouver les informations complementaires
2. Construire une "position documentaire" structuree :
   ```python
   DocumentaryPosition(
       assertion="TLS 1.2 est requis",
       corpus_positions=[
           Position(doc="Security Guide 2023", claim="TLS 1.3", relation="CONTRADICTS"),
           Position(doc="Security Guide 2022", claim="TLS 1.2", relation="CONFIRMS"),
           Position(doc="Operations Guide", claim="TLS 1.2 backward compat", relation="QUALIFIES"),
       ],
       verdict="obsolete_vs_latest",
       confidence=0.85,
   )
   ```

**Commentaires enrichis** :
- Au lieu de "contredit par source X", montrer toutes les positions du corpus
- Indiquer quelle position est la plus recente
- Mentionner les nuances et conditions

**Livrable V2** : Commentaires de niveau expert avec positionnement documentaire complet.

### V3 — Coherence interne + completude (2 semaines)

Le systeme analyse le document comme un tout, pas juste phrase par phrase.

**Coherence interne** :
1. Apres l'extraction des assertions, les comparer entre elles
2. Detecter les contradictions internes (page 3 vs page 12)
3. Detecter les repetitions et inconsistances terminologiques
4. Generer des commentaires specifiques "incoherence interne"

**Completude** :
1. Identifier les sujets abordes dans le document (via entites KG)
2. Pour chaque sujet, verifier si le corpus contient des informations connexes importantes non mentionnees
3. Generer des commentaires "information manquante" pour les omissions significatives
4. Exemple : document sur la securite RFC qui ne mentionne pas SNC

**Document Model** :
1. Construire une representation structuree du document (sections, sujets, arguments)
2. Analyser la coherence de la structure argumentative
3. Identifier les sauts logiques et les non sequitur

**Livrable V3** : Un systeme qui "challenge intellectuellement" le document — pas juste des verifications mais une vraie critique documentaire.

### Phase future — Plugin Word (1-2 semaines, apres V2)

1. Scaffolding Office Add-in (React + TypeScript + Office.js)
2. Task pane avec :
   - Bouton "Verifier la selection" → appel API + commentaire inline
   - Bouton "Analyser tout le document" → traitement complet
   - Panneau de navigation des resultats (clic → navigue dans le doc)
   - Indicateur de confiance par section
3. Distribution : sideloading (dev) → Admin Center M365 (entreprise)

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
