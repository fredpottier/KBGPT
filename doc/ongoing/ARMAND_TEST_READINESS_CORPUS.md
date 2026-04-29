# Cartographie du corpus de test — Armand / OSMOSIS

**Date** : 2026-04-26
**Statut** : Document de travail (étape 4 du chantier de préparation)
**Auteur** : Fred + Claude Code
**Portée** : Identification et localisation des sources publiques pour le bench OSMOSIS

---

## 1. Stratégie de constitution

**Principe directeur** (issu d'une note explicite de Fred) : ne pas se limiter aux versions récentes. **La valeur d'OSMOSIS éclaire si et seulement si le corpus contient suffisamment de versions distinctes pour générer des tensions inter-versions.**

Conséquence : pour chaque texte source, on vise **au moins 2 versions distantes dans le temps** + idéalement les "change notes" officielles qui listent les modifications. Les change notes serviront de **vérité terrain** pour valider la détection et la classification des tensions par OSMOSIS.

Le corpus couvre **deux référentiels** complémentaires :

- **CS-25** (EASA) — référentiel technique de certification, amendements fréquents, structure stable, idéal pour démontrer le **raisonnement différentiel entre versions** (S1) et la **détection de tensions intra-référentiel**
- **Règlement UE 2021/821 + son prédécesseur 428/2009 + ses délégués Annex I** — référentiel juridique d'export control, recast majeur (2009 → 2021) + amendements annuels d'Annex I, idéal pour démontrer la **détection de tensions inter-versions** et la **temporalité** (S3)

L'**interaction CS-25 ↔ 2021/821** (un siège conforme CS-25 contenant un composant dual-use) est la cible du Should S5 — bonus de démo, pas pilier.

---

## 2. Référentiel CS-25 (EASA — Large Aeroplanes)

### 2.1 Versions à constituer

| Version | Date publication | URL | Note |
|---------|------------------|-----|------|
| Amendment 22 | — | https://www.easa.europa.eu/sites/default/files/dfu/CS-25%20Amendment%2022.pdf | PDF direct |
| Amendment 23 | — | https://www.easa.europa.eu/en/document-library/certification-specifications/cs-25-amendment-23 | Page hub |
| Amendment 24 | — | https://www.easa.europa.eu/en/document-library/certification-specifications/cs-25-amendment-24 | Page hub |
| Amendment 25 | — | https://www.easa.europa.eu/sites/default/files/dfu/cs-25_amendment_25.pdf | PDF direct |
| Amendment 26 | — | (page hub à explorer) | — |
| Amendment 27 | — | https://www.easa.europa.eu/sites/default/files/dfu/CS-25%20Amendment%2027.pdf | PDF direct |
| Amendment 28 | 19 décembre 2023 | https://www.easa.europa.eu/en/document-library/certification-specifications/cs-25-amendment-28 | **Plus récent** |

**Hub principal** : https://www.easa.europa.eu/en/document-library/certification-specifications/group/cs-25-large-aeroplanes

### 2.2 Change Notes (vérité terrain)

EASA publie systématiquement, en parallèle de chaque amendement, un PDF "Change Information" qui détaille **explicitement** ce qui change vs la version précédente. Exemple identifié :

- `change_information_cs-25_amdt_26.pdf` : https://www.easa.europa.eu/sites/default/files/dfu/change_information_cs-25_amdt_26.pdf

**À récupérer pour chaque amendement** disponible. Ces documents constituent la **référence pour la construction du jeu de test M1+M2** (vraies tensions annotées) — on sait ce qu'EASA déclare officiellement comme changement, donc on sait ce qu'OSMOSIS devrait détecter et classer.

### 2.3 Easy Access Rules (consolidé)

EASA publie aussi une version consolidée "Easy Access Rules for Large Aeroplanes (CS-25)" qui regroupe plusieurs amendements en un seul document navigable. **Utile pour la baseline factual (M5)** et pour vérifier la cohérence d'OSMOSIS face à des questions où la réponse est dans une version antérieure mais reste valide.

- Revision from June 2022 (incluant amdts 22-26) : https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-large-aeroplanes-cs-25
- Revision from January 2023 : https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/easy-access-rules-large-aeroplanes-cs-25

### 2.4 Recommandation de priorité de téléchargement

**Minimum viable pour le bench** : Amendments 26, 27, 28 + leurs change notes. Trois versions consécutives suffisent à exercer toutes les capacités M1, M2, S1.

**Cible élargie** : Amendments 22 à 28 + Easy Access Rules consolidé. Permet de tester le raisonnement différentiel sur des sauts de plusieurs versions et de vérifier la robustesse temporelle.

---

## 3. Référentiel Règlement UE 2021/821 (dual-use)

### 3.1 Versions consolidées du règlement

| Version consolidée | Date | URL EUR-Lex |
|--------------------|------|-------------|
| 2021/821 originel | 2021-09-09 | https://eur-lex.europa.eu/eli/reg/2021/821/oj/eng |
| Consolidé | 2023-05-26 | https://eur-lex.europa.eu/eli/reg/2021/821/2023-05-26/eng |
| Consolidé | 2024-11-08 | https://eur-lex.europa.eu/eli/reg/2021/821/2024-11-08/eng |
| Consolidé (le plus récent) | 2025-11-15 | https://eur-lex.europa.eu/eli/reg/2021/821 |

### 3.2 Prédécesseur (très important pour les tensions)

**Règlement (CE) 428/2009** — abrogé par 2021/821 avec effet au 9 septembre 2021.

À récupérer sur EUR-Lex (page de synthèse identifiée) :
- https://eur-lex.europa.eu/EN/legal-content/summary/dual-use-export-controls-until-8-september-2021.html
- Versions consolidées du 428/2009 disponibles sur EUR-Lex (URL CELEX à constituer : `02009R0428-*` selon les amendements antérieurs au recast)

**Pourquoi c'est précieux** : le passage 428/2009 → 2021/821 est un **recast majeur**. Articles renumérotés, concepts élargis (cyber-surveillance), nouveaux contrôles (technologies émergentes), suppression de provisions. C'est exactement le type de tensions que personne ne voit en lecture flottante mais qu'OSMOSIS doit détecter — et c'est aussi un cas où la classification doit fonctionner finement (un article supprimé = pas une contradiction, une renumérotation = pas un changement de fond, une extension de scope = vraie évolution).

### 3.3 Délégués modifiant Annex I (mises à jour annuelles)

L'Annex I (liste des biens dual-use contrôlés) est mise à jour au moins une fois par an via des Délégués de la Commission, basés sur les régimes internationaux (Wassenaar, MTCR, Australia Group, NSG).

Délégués identifiés :
- Délégué (UE) **2024/2547** — 5 septembre 2024, modifie Annex I : https://eur-lex.europa.eu/eli/reg_del/2024/2547/oj/eng
- Délégué (UE) **2024/2025** : https://eur-lex.europa.eu/eli/reg_del/2024/2025/oj

**À chercher en complément** : les délégués de 2022 et 2023 modifiant Annex I (page hub EUR-Lex à explorer pour lister les CELEX correspondants).

### 3.4 Recommandation de priorité de téléchargement

**Minimum viable pour le bench** :
1. 2021/821 version originelle (2021-09-09)
2. 2021/821 version consolidée la plus récente (2025-11-15)
3. 428/2009 dans sa dernière version applicable avant abrogation
4. Au moins 1 Délégué Annex I récent (2024/2547)

**Cible élargie** : ajouter les versions consolidées intermédiaires (2023-05-26, 2024-11-08) et 2-3 Délégués supplémentaires de 2022-2023.

---

## 4. Tensions a priori identifiables (pré-bench)

À partir des sources ci-dessus, voici les **archétypes de tensions** que le corpus permettra d'exposer. Cette liste sert de base pour la construction du jeu de test M1+M2 (les 20 vraies tensions annotées) :

### 4.1 Tensions intra-CS-25 (entre amendements)

- **Évolution temporelle / précision** : un amendement qui clarifie une exigence sans en changer le fond → classe "Évolution / précision"
- **Resserrement d'exigence** : un amendement qui durcit un seuil quantitatif → classe "Évolution"
- **Suppression d'une provision** : retirée par un amendement ultérieur → vraie modification de fond, à ne pas confondre avec une simple omission
- **Renumérotation d'articles** : pas une contradiction, doit être détectée comme telle (classe "non-tension" — fausse contradiction lexicale)

### 4.2 Tensions 428/2009 ↔ 2021/821 (recast)

- **Changement de scope substantiel** : par exemple l'introduction de contrôles cyber-surveillance dans 2021/821 absents de 428/2009 → vraie évolution
- **Renumérotation d'articles** : massif dans le recast — fausse contradiction si un outil naïf compare l'article X de chaque
- **Concept élargi** : la définition d'"intermédiaire" évolue → classe "Évolution avec changement de portée"
- **Régime transitoire** : autorisations délivrées avant le 9 septembre 2021 restent régies par 428/2009 → tension de **temporalité avec coexistence**, sujet typique d'audit rétrospectif (M3)

### 4.3 Tensions intra-Annex I (entre Délégués successifs)

- **Ajout d'une catégorie de biens contrôlés** (ex : technologies émergentes 2024) → vraie nouveauté
- **Modification d'un seuil technique** sur un bien existant → évolution quantitative
- **Suppression d'un contrôle** → modification de fond

### 4.4 Tensions cross-référentiel CS-25 ↔ 2021/821 (S5, bonus)

Plus difficile à construire automatiquement, mais quelques cibles possibles :
- Composants électroniques visés par une exigence CS-25 et par un contrôle dual-use Annex I
- Exigences de documentation technique CS-25 qui peuvent contenir des informations sensibles export

---

## 5. Localisation locale du corpus

Cible proposée :

```
data/docs_in/benchmark_armand/
├── cs-25/
│   ├── amdt_22.pdf
│   ├── amdt_23.pdf
│   ├── amdt_24.pdf
│   ├── amdt_25.pdf
│   ├── amdt_26.pdf
│   ├── amdt_27.pdf
│   ├── amdt_28.pdf
│   ├── easy_access_rules_2023-01.pdf
│   └── change_notes/
│       ├── change_amdt_23.pdf
│       ├── change_amdt_24.pdf
│       └── ... (un par amdt)
│
└── dual-use/
    ├── reg_428_2009_consolidated.pdf
    ├── reg_2021_821_v2021-09-09.pdf
    ├── reg_2021_821_v2023-05-26.pdf
    ├── reg_2021_821_v2024-11-08.pdf
    ├── reg_2021_821_v2025-11-15.pdf
    └── annex_i_delegates/
        ├── del_2024_2547.pdf
        ├── del_2024_2025.pdf
        └── del_2023_*.pdf
```

**Note d'ingestion** : ces documents seront ingérés via le pipeline ClaimFirst standard. Aucun traitement spécifique n'est requis a priori. Le tagging par version (year, regulation, amendment) doit être propagé proprement — c'est précisément ce qui alimente la temporalité d'OSMOSIS.

---

## 6. Action côté Fred

Cette cartographie n'engage aucun téléchargement automatique. Les actions concrètes à mener :

1. **Validation de la stratégie** : la priorité minimum viable (§2.4 + §3.4) suffit-elle pour démarrer le bench, ou viser-on directement la cible élargie ?
2. **Téléchargement** : à effectuer par Fred (les URLs EASA et EUR-Lex sont publiques, simples à wget/curl/navigateur)
3. **Vérification d'ingestion** : passer un document au pipeline ClaimFirst pour vérifier que l'extraction sur PDF juridique anglais se comporte correctement (alerte préalable : potentiel défi pour `EntityExtractor` non-tech-corpus, cf. ADR_ENTITY_EXTRACTION_DOMAIN_AGNOSTIC)
4. **Construction du jeu de test annoté** : en s'appuyant sur les Change Notes EASA (vérité terrain pour CS-25) et sur la note explicative Hogan Lovells / Hughes Hubbard / Sidley Austin pour les divergences 428/2009 → 2021/821 (cf. sources §7)

---

## 7. Sources externes utiles pour annoter le jeu de test

Les analyses de cabinets d'avocats sur les divergences 428/2009 → 2021/821 fournissent une **vérité terrain de qualité** pour construire les annotations de tensions :

- Hogan Lovells — Recast Dual-Use Regulation overview
- Hughes Hubbard & Reed — Main changes overview
- Sidley Austin — New EU Dual-Use Regulation enters into force
- Portolano Cavallo — Adoption analysis
- SIPRI — Implementing the 2021 Recast (PDF académique)

Ces analyses **ne doivent pas être ingérées dans le corpus de bench** (elles ne sont pas le corpus testé), mais peuvent servir de référence à Fred pour annoter ce qui est tension réelle vs simple reformulation.

---

## 8. Articulation avec les autres étapes

- **Carte cible (§ARMAND_TEST_READINESS_TARGET)** : les seuils chiffrés des M et S supposent un corpus comme celui décrit ici. Sans multi-versions, M1, M2 et S1 ne sont pas testables.
- **Audit code (étape 2)** : doit notamment vérifier que le pipeline d'ingestion gère correctement le tagging par version (date publication, date validité), que `ApplicabilityFrame` exploite ces métadonnées, et que la propagation année/version vers SubjectResolverV2 fonctionne (cf. memory `project_sprint1_progress` : chaîne de causalité ApplicabilityAxis = 0 identifiée et fix à valider).
- **Bench préalable (étape 0 implicite)** : c'est sur **ce** corpus que le bench se déroulera, donc téléchargement et ingestion à finaliser **avant** tout chantier code (sinon on optimise contre un corpus de SAP qui n'a rien à voir).
