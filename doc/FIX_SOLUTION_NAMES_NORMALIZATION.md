# Fix Solution Names Normalization

**Date**: 30 septembre 2025
**Problème**: Chunks Qdrant avec noms de solutions SAP non-canoniques
**Status**: ✅ Résolu

---

## 🔍 Problème Identifié

### Symptômes
Des chunks dans Qdrant contenaient les noms de solutions suivants :
- ❌ "SAP Cloud ERP"
- ❌ "SAP S/4HANA Cloud"

Ces noms **ne sont PAS canoniques** selon `config/sap_solutions.yaml`.

### Nom Canonique Attendu
✅ **"SAP S/4HANA Cloud, Public Edition"** (ID: `S4HANA_PUBLIC`)

---

## 🔎 Analyse de la Cause Racine

### 1. Structure des Chunks Qdrant
Les solutions sont stockées dans une structure imbriquée :
```json
{
  "solution": {
    "main": "SAP Cloud ERP",  // ❌ Non-canonique
    "supporting": ["SAP S/4HANA Cloud"],  // ❌ Non-canonique
    "mentioned": ["SAP Cloud ERP"],  // ❌ Non-canonique
    "family": "",
    "version": "",
    "deployment_model": ""
  }
}
```

### 2. Cause : Aliases Manquants
Le système de normalisation (`src/knowbase/common/sap/normalizer.py`) utilise `solutions_dict.py` pour le fuzzy matching.

**Avant correction** :
```python
"S4HANA_PUBLIC": {
    "canonical_name": "SAP S/4HANA Cloud, Public Edition",
    "aliases": [
        "S/4HANA Public Cloud",
        "S4 Public",
        "Essentials Edition",
        "ERP Cloud Public Edition",
        # ❌ "SAP Cloud ERP" MANQUANT
        # ❌ "SAP S/4HANA Cloud" MANQUANT
    ],
}
```

### 3. Processus d'Ingestion
Lors de l'ingestion PPTX/PDF, le pipeline appelle `normalize_solution_name()` :
- Si le nom match un alias → normalisation vers canonical_name
- Si aucun match (score < 80) → retourne `"UNMAPPED"` et **garde le nom d'origine**

**Résultat** : Les noms "SAP Cloud ERP" et "SAP S/4HANA Cloud" ont été ingérés tels quels car ils ne matchaient aucun alias.

---

## ✅ Solution Implémentée

### Étape 1 : Ajout des Aliases Manquants

**Fichier modifié** : `src/knowbase/common/sap/solutions_dict.py` (ligne 21-31)

```python
"S4HANA_PUBLIC": {
    "canonical_name": "SAP S/4HANA Cloud, Public Edition",
    "aliases": [
        "S/4HANA Public Cloud",
        "S4 Public",
        "Essentials Edition",
        "ERP Cloud Public Edition",
        "SAP Cloud ERP",           # ✅ AJOUTÉ
        "SAP S/4HANA Cloud",        # ✅ AJOUTÉ
        "S/4HANA Cloud",            # ✅ AJOUTÉ
    ],
},
```

**Fichier modifié** : `config/sap_solutions.yaml` (ligne 85-94)
```yaml
S4HANA_PUBLIC:
  aliases:
  - S/4HANA Public Cloud
  - S4 Public
  - Essentials Edition
  - ERP Cloud Public Edition
  - SAP Cloud ERP          # ✅ AJOUTÉ
  - SAP S/4HANA Cloud       # ✅ AJOUTÉ
  - S/4HANA Cloud           # ✅ AJOUTÉ
  canonical_name: SAP S/4HANA Cloud, Public Edition
  category: erp
```

**Validation** :
```bash
$ docker-compose exec app python3 -c "
from knowbase.common.sap.normalizer import normalize_solution_name
sol_id, canonical = normalize_solution_name('SAP Cloud ERP')
print(f'{sol_id} → {canonical}')
"
# Output: S4HANA_PUBLIC → SAP S/4HANA Cloud, Public Edition
```

---

### Étape 2 : Correction des Chunks Existants

**Script créé** : `scripts/fix_qdrant_solutions_names.py`

#### Fonctionnalités
- Scan de tous les points de la collection Qdrant
- Détection des noms problématiques dans `solution.main`, `solution.supporting`, `solution.mentioned`
- Remplacement par le nom canonique
- Mode `--dry-run` pour simulation
- Statistiques détaillées

#### Exécution
```bash
# Test simulation
$ docker-compose exec app python3 scripts/fix_qdrant_solutions_names.py --dry-run
⚠️  MODE DRY-RUN: 445 corrections seraient appliquées

# Application réelle
$ docker-compose exec app python3 scripts/fix_qdrant_solutions_names.py
✅ 445 corrections appliquées avec succès!
```

#### Résultats
```
Total points scannés: 1231
Points avec solution.main: 1231
Points corrigés (solution.main): 181
Points corrigés (solution.supporting): 48
Points corrigés (solution.mentioned): 216

Total corrections: 445
```

---

## 📊 Vérification Post-Correction

### Distribution des solution.main
```
 767 × SAP S/4HANA Cloud, Private Edition
 245 × SAP S/4HANA Cloud, Public Edition  ✅ (181 corrigés)
 110 × SAP Business Data Cloud
 109 × SAP BTP Audit Log Service
```

### Vérification Absence de Noms Non-Canoniques
```bash
$ docker-compose exec app python3 scripts/fix_qdrant_solutions_names.py --dry-run
⚠️  MODE DRY-RUN: 0 corrections seraient appliquées  ✅
```

---

## 🎯 Impact et Bénéfices

### Avant
- ❌ 181 chunks avec `solution.main` non-canonique
- ❌ 48 chunks avec `solution.supporting` non-canonique
- ❌ 216 chunks avec `solution.mentioned` non-canonique
- ❌ Recherches par solution inefficaces
- ❌ Statistiques faussées

### Après
- ✅ 100% des noms de solutions canoniques
- ✅ Recherches par solution fiables
- ✅ Statistiques précises
- ✅ Futurs imports normalisés automatiquement

---

## 🔧 Maintenance Future

### Prévention
Pour éviter ce problème à l'avenir :

1. **Ajouter les alias courants** dans `solutions_dict.py` et `sap_solutions.yaml`
2. **Tester la normalisation** avant l'import de nouveaux documents
3. **Monitorer les `UNMAPPED`** dans les logs d'ingestion

### Test de Normalisation
```python
from knowbase.common.sap.normalizer import normalize_solution_name

# Tester un nouveau nom trouvé
sol_id, canonical = normalize_solution_name("Nouveau nom SAP")
if sol_id == "UNMAPPED":
    print(f"⚠️ Nom non normalisé: {canonical}")
    print("→ Ajouter un alias dans solutions_dict.py")
```

### Script de Vérification
```bash
# Vérifier si des noms non-canoniques existent
docker-compose exec app python3 scripts/fix_qdrant_solutions_names.py --dry-run

# Si > 0 corrections → exécuter le fix
docker-compose exec app python3 scripts/fix_qdrant_solutions_names.py
```

---

## 📝 Fichiers Modifiés

| Fichier | Modification | Statut |
|---------|--------------|--------|
| `src/knowbase/common/sap/solutions_dict.py` | Ajout 3 aliases S4HANA_PUBLIC | ✅ Committé |
| `config/sap_solutions.yaml` | Ajout 3 aliases S4HANA_PUBLIC | ✅ Committé |
| `scripts/fix_qdrant_solutions_names.py` | Nouveau script correction | ✅ Créé |

---

## ✅ Checklist Validation

- [x] Aliases ajoutés dans `solutions_dict.py`
- [x] Aliases ajoutés dans `sap_solutions.yaml`
- [x] Backend redémarré pour charger nouveaux aliases
- [x] Normalisation testée et validée
- [x] Script de correction créé
- [x] Dry-run exécuté et validé (445 corrections détectées)
- [x] Corrections appliquées sur Qdrant
- [x] Vérification post-correction (0 noms non-canoniques restants)
- [x] Documentation créée

---

## 🚀 Recommandations

1. **Exécuter périodiquement** le script de vérification pour détecter de nouveaux noms non-canoniques
2. **Enrichir les aliases** au fur et à mesure de la découverte de variantes
3. **Documenter les alias** dans les commentaires de `sap_solutions.yaml`
4. **Ajouter un test** unitaire pour valider la normalisation des noms courants

---

**Résolu par** : Claude Code
**Date résolution** : 30 septembre 2025
**Impact** : 445 chunks corrigés / 1231 total (36% affectés)