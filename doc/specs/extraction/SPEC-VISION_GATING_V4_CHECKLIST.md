# Vision Gating v4 — Checklist d'implémentation

**Date: 2026-01-02**
**Status: Prêt pour implémentation**

---

## 0. Préambule (à lire avant de coder)

☑ Le gating **ne fait pas de vision**
☑ Le gating **ne fait pas de LLM**
☑ Le gating **ne dépend pas du format**
☑ Le gating **produit une décision explicable**

Si une étape introduit :

* du raisonnement métier,
* une inférence sémantique,
* une dépendance GPT,

👉 **elle est hors scope**.

---

## 1. Modélisation des données (fondation)

### 1.1 Définir l'unité de décision

☐ Créer un type `VisionUnit`

* id (`PDF_PAGE_6`, `PPTX_SLIDE_12`, …)
* format (`PDF`, `PPTX`)
* dimensions (width, height)
* index (page / slide)

☐ Garantir **1 unit = 1 décision**

---

### 1.2 Normaliser la sortie Docling

☐ Créer un adaptateur `DoclingUnitAdapter`

* `blocks[]`

  * type
  * text_length
  * bbox (x1,y1,x2,y2)
* `tables[]`
* `visual_elements[]`

  * kind (`raster_image`, `vector_drawing`)
  * bbox

☐ Aucune logique métier ici
☐ Uniquement mapping + nettoyage

---

## 2. Implémentation des signaux (features)

> Chaque signal = une fonction pure, testable, sans effet de bord

---

### 2.1 Raster Image Signal (RIS)

☐ Implémenter `compute_raster_image_signal(unit)`

* calcul surface image / surface page
* identifier la plus grande image

☐ Vérifier :

* image décorative ≠ image dominante
* OCR simple (optionnel) ne déclenche rien à lui seul

☐ Tests :

* 1 grande image → RIS = 1.0
* icône/logo → RIS = 0.0

---

### 2.2 Vector Drawing Signal (VDS)

☐ Implémenter `compute_vector_drawing_signal(unit)`

* compter drawings
* détecter connecteurs (lignes fines / flèches)
* calculer aire cumulée des drawings

☐ Gérer :

* PDF (`get_drawings`)
* PPTX (`shape.type != PICTURE`)

☐ Tests :

* diagramme SAP → VDS ≥ 0.7
* slide texte → VDS = 0.0

---

### 2.3 Text Fragmentation Signal (TFS)

☐ Implémenter `compute_text_fragmentation_signal(unit)`

* compter blocs texte
* calculer longueur moyenne
* ratio blocs courts (<200 chars)

☐ Ne PAS :

* utiliser le contenu sémantique
* regarder les mots

☐ Tests :

* paragraphes longs → TFS = 0.0
* boîtes multiples → TFS ≥ 0.6

---

### 2.4 Spatial Dispersion Signal (SDS)

☐ Implémenter `compute_spatial_dispersion_signal(unit)`

* centres `(cx, cy)`
* variance ou entropie spatiale

☐ Vérifier :

* texte en colonne → SDS faible
* texte réparti → SDS élevé

☐ Tests :

* page Word → SDS = 0.0
* slide diagramme → SDS ≥ 0.5

---

### 2.5 Visual Table Signal (VTS)

☐ Implémenter `compute_visual_table_signal(unit)`

* détection grilles / alignements
* exclure tables Docling déjà structurées

☐ Tests :

* table dessinée → VTS = 1.0
* table Docling → VTS = 0.0

---

## 3. Scoring et pondération

### 3.1 Implémenter le score global

☐ Implémenter `compute_vision_need_score(signals, weights)`

☐ Vérifier :

* poids = config
* somme pondérée correcte

---

### 3.2 Domain Context (pondération uniquement)

☐ Implémenter `adjust_weights(weights, domain_context)`

* ±10% max
* jamais modifier seuils

☐ Tests :

* sans domain context → poids par défaut
* avec SAP context → pondération légère

---

## 4. Décision finale

### 4.1 Implémenter la règle de sécurité

☐ Si `RIS == 1.0 OR VDS == 1.0`
→ `VISION_REQUIRED`

---

### 4.2 Implémenter les seuils

☐ ≥ 0.60 → REQUIRED
☐ ≥ 0.40 → RECOMMENDED
☐ < 0.40 → NO_VISION

☐ Aucun if "au feeling"

---

## 5. Sortie explicable (critique)

☐ Créer un objet `VisionGatingResult`

* decision
* vision_need_score
* signals
* reasons (humain lisible)

☐ Toujours fournir :

* les scores
* les raisons

☐ Jamais retourner juste un booléen

---

## 6. Intégration pipeline

### 6.1 Position correcte dans le pipeline

☐ Vision Gating **après Docling**
☐ Vision Gating **avant tout LLM**

☐ Interdiction :

* d'appeler GPT avant gating
* d'appeler Vision sur document brut

---

### 6.2 Appel Vision conditionnel

☐ Implémenter :

```python
if gating.decision == "VISION_REQUIRED":
    run_vision()
elif gating.decision == "VISION_RECOMMENDED":
    run_vision_if_budget_allows()
```

☐ Jamais appeler Vision si `NO_VISION`

---

## 7. Robustesse & sécurité

☐ Timeout Vision ≠ fallback automatique
☐ Échec Vision → marquer `vision_failed`, pas réinterpréter
☐ Log explicite de chaque décision

---

## 8. Tests obligatoires (non optionnels)

### 8.1 Jeux de documents

☐ PDF texte long (500+ pages)
☐ PPTX diagramme SAP
☐ PDF issu de PPTX (shapes)
☐ PDF avec image scannée
☐ Document mixte (texte + schéma)

---

### 8.2 Tests unitaires

☐ Chaque signal testé isolément
☐ Score global testé
☐ Décision testée aux seuils

---

### 8.3 Tests de non-régression

☐ Un document texte ne déclenche jamais Vision
☐ Un diagramme en shapes déclenche Vision
☐ Une image décorative ne déclenche pas Vision

---

## 9. Observabilité (indispensable)

☐ Log par unit :

* format
* scores
* décision

☐ Export JSON pour audit ultérieur

☐ Possibilité de rejouer gating sur un doc existant

---

## 10. Critères de "DONE"

Vision Gating v4 est **DONE** si :

☑ Aucun LLM utilisé
☑ Tous les signaux sont mesurables
☑ Chaque décision est expliquée
☑ Les faux positifs sont rares
☑ Les faux négatifs sur diagrammes sont quasi nuls
☑ Claude Code peut maintenir le code sans contexte oral

---

## 11. Message final à Claude Code

> Si une décision Vision n'est pas **justifiable par des signaux structurels**,
> alors le gating est **incorrect**, même s'il "marche".
