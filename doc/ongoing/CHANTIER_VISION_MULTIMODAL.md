# CHANTIER — Vision / Multimodal : intégrer les schémas (PPTX SAP) SANS polluer le graphe

> **Statut : TRACÉ, non démarré.** Vrai chantier futur (décision Fred, 12/06/2026 — ne pas
> traiter maintenant). Ce document capitalise l'analyse littérature + le modèle proposé pour
> ne pas le perdre. Indexé depuis `ETAT_DES_CHANTIERS.md`.

## 1. Le problème / l'opportunité

Les documents (surtout les **.pptx SAP**) contiennent **énormément d'information dans les
schémas / diagrammes / graphiques**. Aujourd'hui OSMOSIS a un branchement vision (GPT-4o)
**désactivé pour raison de coût**.

**Mais le vrai blocage n'est pas le coût** (il se règle comme pour le texte : des VLM compétents
et bon marché — Qwen-VL, DeepSeek-VL — remplacent GPT-4o). **Le vrai blocage est ÉPISTÉMIQUE** :
ce qu'un VLM « dit avoir vu » dans un schéma est une **interprétation générative hallucinable**,
**pas un verbatim**. Or le différenciateur d'OSMOSIS est que chaque claim est ancré sur un
verbatim vérifiable (garde grounding NLI, abstention plutôt qu'hallucination). Donc :
- on ne peut **pas** traiter une lecture VLM au **même niveau de preuve** qu'un claim ancré ;
- une lecture VLM ne peut **pas** passer honnêtement la garde NLI (vérification circulaire) ;
- **mais** jeter les schémas = perdre une part majeure de l'information SAP.

**La bonne question (Fred)** : les traiter **mais à un niveau de preuve DIFFÉRENT (inférieur)**.

## 2. Ce que dit la littérature (recherche 12/06/2026, 3 facettes)

### A. La lecture VLM de schémas est non fiable — et c'est quantifié
- **CharXiv** : 47 % (meilleurs modèles) vs **80 % humain**.
- **ChartHal** : ~34 % d'hallucination même sur GPT-5 ; taxonomie de 5 modes (fabrication de
  valeur, mauvaise tendance, confusion d'entité, hallucination de raisonnement, drift chart→table).
- **CHOCOLATE (ACL 2024)** : jusqu'à **81 % de légendes non-factuelles** même avec GPT-4V.
- **FlowVQA / Losing-the-Plot** : effondrement sur diagrammes complexes/dégradés, **échec
  silencieux et confiant** (pas d'abstention).
- Conclusion : sortie VLM = **reconstruction générative ≠ verbatim**.

### B. Séparer ce qui est LU de ce qui est INFÉRÉ (la nuance décisive)
- **LU** = labels d'axes, légendes, **texte des boîtes/nœuds**, annotations → **verbatim visuel
  vrai**, récupérable par OCR. Pour **.pptx born-digital, déjà dans le XML (python-pptx) →
  extractible SANS VLM**, zéro hallucination. **Ancrage le plus fort.**
- **INFÉRÉ** = relations, flèches (« A remplace B »), tendances → **interprétation**, preuve faible.
- Recette ancrée : ne **jamais** prendre la description libre du VLM ; extraire d'abord un
  **intermédiaire structuré récupérable** puis **vérifier** l'assertion contre lui :
  - chart→table : **DePlot, UniChart, SIMPLOT, ChartOCR** (la table devient la preuve cliquable ;
    ancrer un claim numérique à une **cellule**). Fiable barres/courbes ; faible camembert/scatter.
  - flowchart→graphe : **TEXTFLOW** (Mermaid/GraphViz), **Follow-the-Flow** (attribution nœud/arête).
  - vérif de fidélité : **ChartVE** (entailment visuel) — l'analogue visuel de la garde NLI.
- ⚠️ Le **bbox prédit par un VLM n'est PAS une preuve fiable** (reasoning-grounding gap ;
  VISA IoU>0.5 = 27,8 % sur docs scientifiques). Pour un .pptx, surligner la **boîte connue
  déterministiquement via le XML** suffit.

### C. La « preuve à niveaux » (evidence tiers) est validée par la littérature
- KG **provenance-aware** : **Knowledge Vault** type l'extracteur (texte / HTML-tree / table /
  humain) comme **entrée de confiance de première classe**.
- Vérification de claims : distingue **perception directe** vs **inférence** (couches
  observation/contexte/interprétation).
- Précédent : **hiérarchie des preuves** médicale (EBM/GRADE), portée dans des LLM (Med-R²) —
  **mais heuristique, un prior pondérateur, PAS un veto** (parfois le visuel *est* nécessaire,
  cf. AMuFC « Visual Evidence Necessity »).
- L'incertitude **se propage** dans embeddings + raisonnement aval (néfaste en contexte
  sensible) → besoin d'une garde de propagation.

## 3. Modèle proposé pour OSMOSIS (à instruire + consensus octopus le moment venu)

Ajouter au modèle de claim **une dimension de provenance**, pas une refonte :
- `provenance_type ∈ {verbatim_text, table_cell, ocr, vision_inferred}`
- `evidence_tier` : **T1** verbatim texte / **T2** table structurée ou label OCR exact /
  **T3** relation vision-inférée.
- **Confiance** = `base_extraction × poids_fiabilité_du_type` (T3 prior strictement inférieur).
- **Propagation weakest-link** : une conclusion hérite du **tier minimum** de ses supports.
- **🔒 Garde anti-contamination (cardinale)** : une **CONTRADICTS / adjudication / SUPERSEDES
  ne peut PAS être fondée sur un T2/T3 seul** avec l'autorité d'un verbatim. Le visuel peut
  **corroborer** (monter la confiance d'un T1 aligné, façon BayesRAG) ou **flaguer pour revue**,
  **jamais trancher**. → extension directe de la leçon OSMOSIS « seule la lecture en contexte
  juge une contradiction » → ici « seule une preuve T1 peut trancher ».
- **Runtime** : un T3 seul à fort enjeu → **abstention** ou réponse explicitement marquée
  « issu d'un schéma, interprété » — la fiabilité qu'on vend.

## 4. Quick-win actionnable (le vrai morceau à fort ROI / risque nul)

**Extraire le texte des formes des .pptx SAP depuis le XML (python-pptx), SANS VLM, comme
claims T1 verbatim.** Titres de boîtes, labels, légendes, annotations = verbatim visuel le plus
ancré, la garde NLI s'applique telle quelle. Récupère une grosse part de l'info des schémas SAP
au plus haut niveau de preuve, zéro hallucination. **C'est le meilleur rapport gain/risque de
tout le sujet** et il ne nécessite aucun VLM.

## 5. Phasage proposé (le jour où on le traite)
1. **Quick-win pptx-XML** (texte des formes → T1 verbatim, sans VLM). Faible effort, fort gain.
2. **Modèle de tiers** (`provenance_type` + `evidence_tier` + propagation weakest-link + garde
   adjudication T1-only). Consensus octopus d'abord (curseur tier = prior vs veto).
3. **VLM seulement pour les schémas rasterisés** (images collées, pas de XML) → intermédiaire
   structuré (chart→table / flowchart→graphe) + vérif entailment → T2/T3 marqués, jamais
   d'autorité d'adjudication.
4. **À écarter** : vision-sur-page généralisée / ColPali pour l'extraction (gain LOW, effort
   LARGE, coût ×10-100, et le gain ColPali est sur le *retrieval*, pas l'extraction) ; bbox
   prédit comme preuve.

## 6. Pourquoi ça renforce le moat
On intègre l'info visuelle **sans** polluer le graphe de faux faits : le texte des schémas
devient du verbatim T1, les relations inférées restent T3 incapables de trancher. C'est une
**extension propre** du différenciateur fiabilité/provenance, pas un pari multimodal risqué.

## Sources clés
CharXiv ; ChartHal (arXiv 2509.17481) ; CHOCOLATE (ACL 2024, arXiv 2312.10160) ; DePlot
(arXiv 2212.10505) ; UniChart (2305.14761) ; SIMPLOT (2405.00021) ; ChartOCR (WACV 2021) ;
TEXTFLOW (NAACL 2025) ; Follow-the-Flow (2506.01344) ; VISA (2412.14457) ; Knowledge Vault ;
Med-R² (2501.11885) ; AMuFC (2604.04692) ; BayesRAG (2601.07329).

*(Mémoires de référence détaillées des agents : `reference_vlm_chart_hallucination_2026`,
`reference_grounded_visual_extraction_2026`, `reference_evidence_tiering_visual_provenance_2026`.)*

---
*Créé le 12/06/2026 — analyse littérature + cadrage. À reprendre avec consensus octopus avant
implémentation.*
