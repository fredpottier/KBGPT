# ADR-001: Decision Defense Architecture

**Status:** ACCEPTED
**Date:** 2026-01-19
**Authors:** Architecture Team (avec validation ChatGPT + Claude)
**Supersedes:** Approches KG sémantique précédentes

---

## Phrase Directrice

> **"OSMOSIS is not a system that tries to answer better.
> It is a system that refuses to answer beyond what can be proven — and explains why."**

---

## 0. Ce que cet ADR N'EST PAS (Why This Is Not RAG++)

Avant de lire ce document, il est essentiel de comprendre ce qu'OSMOSIS **n'est pas** :

| OSMOSIS n'est PAS | Parce que |
|-------------------|-----------|
| Un RAG amélioré | La valeur n'est pas dans la réponse textuelle |
| Un chatbot plus précis | L'objectif n'est pas de "mieux répondre" |
| Un KG qui raisonne | Le raisonnement par traversée a échoué empiriquement |
| Un système qui "comprend" les documents | Il ne fait que vérifier des assertions explicites |

**La valeur centrale d'OSMOSIS est l'abstention qualifiée.**

Un système qui répond toujours est un système qui ment parfois.
OSMOSIS choisit de ne jamais mentir, quitte à ne pas conclure.

> **OSMOSIS ne promet pas la connaissance. Il promet la défendabilité.**

---

## 1. Contexte et Problème

### 1.1 Constat sur les Systèmes LLM/RAG

Les systèmes LLM seuls, ou LLM + RAG, **ne peuvent pas garantir** :

- La **complétude** de la réponse
- L'**absence d'inférence abusive**
- La capacité à expliquer **pourquoi une réponse n'est pas possible**

Dans des contextes à risque (technique, réglementaire, industriel, scientifique), **une réponse plausible mais non défendable est plus dangereuse qu'une non-réponse**.

### 1.2 Échec des Approches Précédentes

Les itérations précédentes d'OSMOSIS ont tenté de :

1. Faire émerger un **KG sémantique riche** sans ontologie upfront
2. Permettre un **raisonnement par traversée de relations**
3. Inférer des relations implicites entre concepts

**Résultat observé :** Ces tentatives se sont révélées **structurellement déceptives** sur des corpus procéduraux et normatifs (documentation SAP).

**Evidence empirique :**
- Pass 3 (extraction relations) : **97% d'abstention**
- Cause : les documents SAP décrivent des procédures, pas des assertions relationnelles
- Les relations CO_OCCURS et MENTIONED_IN ne constituent pas des preuves

### 1.3 Question Fondamentale

> Comment construire un système qui soit **honnête sur ses limites** tout en restant **utile pour la prise de décision** ?

---

## 2. Décision Architecturale

### 2.1 Thèse Centrale

> **OSMOSIS ne vise plus à raisonner par traversée sémantique,
> mais à raisonner par obligations de preuve.**

### 2.2 Pivot Explicite

| Avant (KG Sémantique) | Après (Evidence Graph) |
|----------------------|------------------------|
| Graphe de concepts interconnectés | Support de traçabilité des preuves |
| Raisonnement par propagation | Vérification par obligations |
| Relations inférées | Evidence explicite uniquement |
| Réponse = synthèse LLM | Réponse = Decision Package structuré |

### 2.3 Nouvelle Architecture

```
Question → Claim Generator → Evidence Searcher → Gap Qualifier → Decision Package
              ↓                    ↓                  ↓               ↓
         Claims à prouver    Preuves trouvées    Gaps qualifiés   Statut dérivé
```

Le **Knowledge Graph** devient un **Evidence Graph** :
- Support de **traçabilité**
- Structuration de la **preuve**
- Gouvernance de l'**absence**

---

## 3. Invariant Produit (Non Négociable)

> **Pour toute question posée, OSMOSIS produit soit :**
>
> 1. Un ensemble de **claims explicitement prouvés** par des sources documentaires
> 2. Soit une **explication explicite et vérifiable** de pourquoi ces claims ne peuvent pas être prouvés
>
> **Aucune conclusion ne peut dépasser ce que les preuves permettent.**

### Corollaire

> *"Savoir pourquoi on ne peut pas conclure est un résultat de première classe."*

Un gap qualifié (ex: `MECHANISM_ONLY`, `NO_EXPLICIT_ASSERTION`) est une **réponse valide et utile**, pas un échec du système.

### 3.2 L'Échec comme Résultat Documenté

**Principe fondamental :**

> Un résultat non-conclusif n'est acceptable que **s'il est démontrable par le corpus lui-même**.

Le système ne doit pas seulement *qualifier* l'absence, il doit **l'exhiber**.

Dans OSMOSIS, un résultat non-conclusif (`PARTIALLY_SUPPORTED` ou `NOT_SUPPORTED`) n'est **jamais** interprété comme une défaillance du système ou un manque de compréhension.

**Tout résultat non-conclusif DOIT :**

1. Être adossé à **au moins un extrait documentaire observable** démontrant pourquoi le claim ne peut pas être supporté
2. Montrer explicitement ce que les documents **affirment à la place** (ex: mécanisme, procédure, scope)
3. Permettre à un lecteur humain de **vérifier indépendamment** qu'aucune assertion explicite n'existe

> **Un gap sans justification documentaire observable est considéré comme une DÉFAILLANCE SYSTÈME, pas comme un résultat valide.**

### 3.3 Distinction Critique : Système vs Documents

Cette distinction doit être **explicitement maintenue** dans tout le système :

| ❌ Le système ne dit PAS | ✅ Le système dit |
|--------------------------|-------------------|
| "Je ne sais pas" | "Les documents n'affirment pas X" |
| "Je n'ai pas trouvé" | "Aucun document ne contient d'assertion explicite sur X" |
| "Information manquante" | "Le corpus décrit Y mais pas X" |

> **OSMOSIS ne déclare pas son ignorance. Il déclare l'absence d'assertion documentaire.**

Cette formulation doit être reprise dans :
- L'UI (Decision Board)
- Les rapports exportés
- Les logs système
- La documentation utilisateur

---

## 4. Non-Objectifs (Abandons Explicites)

Cette section est **critique** pour éviter toute régression conceptuelle.

### OSMOSIS ne vise PAS à :

| Non-Objectif | Raison de l'Abandon |
|--------------|---------------------|
| Produire un graphe ontologique exhaustif | Impossible sans ontologie upfront |
| Inférer des relations implicites | Source d'hallucinations |
| Raisonner par propagation sémantique | Inadapté aux corpus procéduraux |
| "Compléter" ce que les documents n'affirment pas | Viole l'invariant de preuve |
| Générer des réponses fluides sans traçabilité | Valeur nulle pour la décision |

### Clarification Importante

Les **relations sémantiques riches** ne sont plus un objectif primaire.
Leur absence n'est **pas considérée comme un défaut** du système.

---

## 5. Architecture Cible

### 5.1 Composants Conceptuels

#### Question Type Detection
Détection du type de question pour déterminer les obligations de preuve :

| Type | Exemple | Claims Attendus |
|------|---------|-----------------|
| `upgrade` | "Puis-je upgrader de 2021 vers 2023?" | path_support, prerequisite, tool, compatibility |
| `prerequisite` | "Quels prérequis pour SUM?" | prerequisite, dependency |
| `feature` | "Capacités de Embedded Analytics?" | definition, scope, limitation |
| `limitation` | "Fonctions non disponibles?" | limitation, deprecated |
| `integration` | "Intégration avec Ariba?" | compatibility, prerequisite |
| `compatibility` | "Compatible avec HANA 2.0?" | compatibility, limitation |

**Note sur les questions descriptives (feature, capabilities) :**
> Pour les questions descriptives, `PARTIALLY_SUPPORTED` est le résultat **attendu** sur une documentation procédurale. Cela reflète une **prudence documentaire**, pas une limitation du système. Les documents SAP décrivent des mécanismes et périmètres, rarement des assertions fermées de type "X fait Y".

#### Claim Templates
Structure minimale des claims attendus par type de question.

**Important :** Ce n'est **pas une ontologie métier**. C'est un ensemble de patterns de vérification.

> **Les claim templates ne représentent pas des "vérités attendues".
> Ils représentent les engagements documentaires minimaux requis pour répondre de manière responsable à une question de ce type.**

Cette distinction est critique : les claims ne sont pas dogmatiques, ils définissent le **seuil de preuve** en dessous duquel une conclusion serait irresponsable.

> **La décomposition en claims ne vise pas à refléter comment un expert humain raisonnerait, mais à exposer l'ensemble minimal d'engagements documentaires requis pour conclure de manière responsable.**

Cette formulation protège contre l'objection "vous avez mal découpé la question" — les claims ne sont pas une modélisation du raisonnement expert, mais une grille de vérification minimale.

> **Ce qu'un expert humain saurait répondre n'implique pas que la documentation s'engage sur cette réponse.**

Cette distinction est fondamentale : OSMOSIS ne modélise pas l'expertise humaine, il vérifie les engagements documentaires.

```python
UPGRADE_CLAIMS = [
    "Le chemin {source} → {target} est officiellement supporté",
    "Les prérequis sont documentés",
    "L'outil requis est identifié",
    "Aucune incompatibilité bloquante n'est documentée"
]
```

#### Evidence Typing
Classification des DocItems par type de preuve :

| Type | Description | Exemple |
|------|-------------|---------|
| `requirement` | Exigence explicite | "SUM 2.0 SP15 minimum required" |
| `procedure` | Étape documentée | "Run SI-Check before upgrade" |
| `limitation` | Restriction documentée | "Not supported for systems < 2018" |
| `scope` | Périmètre d'application | "Applies to on-premise only" |
| `definition` | Définition d'un concept | "Embedded Analytics provides..." |
| `mechanism` | Mécanisme de vérification | "SI-Check validates compatibility" |

**Note :** C'est une **micro-ontologie des types de preuve**, assumée comme telle.

#### Gap Qualification
Raisons qualifiées pour l'absence de preuve :

| Gap Type | Signification |
|----------|---------------|
| `NO_EXPLICIT_ASSERTION` | Aucune phrase n'affirme explicitement X |
| `MECHANISM_ONLY` | Un mécanisme existe mais ne garantit pas le résultat |
| `SCOPE_UNSPECIFIED` | L'information existe mais le scope exact n'est pas défini |
| `CONTRADICTION` | Sources contradictoires détectées |

##### Concept Clé : Preuve d'Absence (Proof of Absence)

> **Preuve d'Absence (Proof of Absence)**
> Evidence démontrant qu'une assertion spécifique n'est **pas présente** dans le corpus, malgré la documentation de mécanismes ou procédures connexes.

Ce concept est central à OSMOSIS :
- Ce n'est pas "je n'ai rien trouvé"
- C'est "j'ai trouvé X, et X ne contient pas l'assertion Y"
- La preuve d'absence est **elle-même une preuve documentaire**

##### Exigence de Preuve pour les Gaps (Gap Evidence Requirement)

> **Tout gap_reason DOIT être associé à au moins un élément Evidence qui démontre l'absence de l'assertion attendue.**

Concrètement :
- Un gap n'est **pas** une méta-explication générée par le système
- C'est une **preuve d'absence**, via substitution observable
- Le système montre ce qu'il a trouvé **à la place** de l'assertion attendue

**Structure obligatoire d'un gap :**

```json
{
  "gap_reason": {
    "type": "MECHANISM_ONLY",
    "description": "Le corpus décrit le mécanisme SI-Check mais ne garantit pas de résultat",
    "documentary_evidence": {
      "found_instead": "Procédure de vérification décrite",
      "source": "SAP_Upgrade_Guide_2023",
      "excerpt": "Run SI-Check to validate compatibility...",
      "demonstrates_absence": "Aucune assertion 'compatible' ou 'incompatible' n'est présente"
    }
  }
}
```

#### Decision Status Derivation
Règles **déterministes** (jamais décidées par le LLM) :

```python
def derive_status(claims: List[Claim]) -> DecisionStatus:
    if all(c.status == SUPPORTED for c in claims):
        return SUPPORTED
    if any(c.status == SUPPORTED for c in claims):
        return PARTIALLY_SUPPORTED
    return NOT_SUPPORTED
```

### 5.2 Règles Fondamentales

| Règle | Énoncé |
|-------|--------|
| **R1** | Pas de preuve = Pas de support (jamais d'inférence) |
| **R2** | Navigation suggère, Evidence prouve (CO_OCCURS ≠ preuve) |
| **R3** | Partial est un statut valide (pas un échec) |
| **R4** | Le statut est dérivé, jamais décidé par LLM |
| **R5** | PARTIALLY_SUPPORTED ≠ sécurité partielle |

#### Clarification sur R2 : Navigation Instrumentale

> **Les relations de navigation peuvent influencer où chercher, mais jamais ce qui peut être conclu.**

Cette règle est critique pour éviter toute dérive future :
- `CO_OCCURS` peut guider vers des documents pertinents
- `MENTIONED_IN` peut suggérer des contextes
- **Mais aucune relation de navigation ne peut jamais être comptée comme Evidence**

#### Clarification sur R5 : Sémantique de PARTIALLY_SUPPORTED

> **PARTIALLY_SUPPORTED n'implique pas une sécurité partielle.
> Cela signifie que certaines obligations sont prouvées et d'autres non, et doit être traité comme tel par le propriétaire de la décision.**

| Ce que PARTIAL signifie | Ce que PARTIAL ne signifie PAS |
|-------------------------|-------------------------------|
| Certains claims prouvés, d'autres non | "Presque oui" |
| Zone à examiner attentivement | "Vous pouvez y aller avec réserves" |
| Preuve incomplète | Risque faible |

**Recommandation d'usage responsable :**
> Dans les contextes à haut risque, `PARTIALLY_SUPPORTED` doit être traité comme `NON-ACTIONNABLE` sauf décision explicite du propriétaire de la décision.

Cette recommandation ne force rien, mais cadre l'usage responsable du système.

---

## 6. Artefact Central : Le Decision Package

### 6.1 Définition

> **"The Decision Package is the product."**

Le Decision Package est :
- **Structuré** : Format JSON/Pydantic défini
- **Archivable** : Peut être stocké et versionné
- **Auditable** : Chaque conclusion est traçable jusqu'à la source
- **Déterministe** : Même input = même output

### 6.2 Structure

```json
{
  "decision_id": "DP_abc123",
  "question": "Can I upgrade from S/4HANA 2021 to 2023?",
  "decision_type": "upgrade",
  "status": "PARTIALLY_SUPPORTED",
  "claims": [
    {
      "claim_id": "C1",
      "statement": "Le chemin 2021 → 2023 est supporté",
      "status": "SUPPORTED",
      "evidence": [
        {
          "source": "SAP_Upgrade_Guide_2023",
          "excerpt": "Upgrade from 2021, 2022 to 2023 is supported...",
          "confidence": "HIGH"
        }
      ]
    },
    {
      "claim_id": "C4",
      "statement": "Aucune incompatibilité bloquante",
      "status": "PARTIALLY_SUPPORTED",
      "evidence": [...],
      "gap_reason": {
        "type": "MECHANISM_ONLY",
        "description": "SI-Check existe mais ne garantit pas le résultat"
      }
    }
  ],
  "coverage": {"supported": 3, "partial": 1, "unsupported": 0},
  "corpus_scope": ["doc1", "doc2", ...]
}
```

### 6.3 Usages

| Usage | Description |
|-------|-------------|
| **UI Decision Board** | Visualisation interactive des claims et preuves |
| **Export Rapport** | Génération PDF/DOCX auditable |
| **Piste de Vérité** | Référence ex-post pour justifier une décision |
| **Input pour Résumé** | Base factuelle pour synthèse LLM (optionnelle) |

---

## 7. Rôle du LLM (Borné)

### 7.1 Autorisations

Le LLM est autorisé à :

| Action | Contexte |
|--------|----------|
| Détecter le type de question | Classification initiale |
| Instancier des claim templates | Remplissage des paramètres |
| Classifier des preuves | Typing des DocItems |
| Produire un résumé **non engageant** | Dérivé strictement du Decision Package |

### 7.2 Interdictions

Le LLM n'est **JAMAIS** autorisé à :

| Interdit | Raison |
|----------|--------|
| Conclure en absence de preuve | Viole R1 |
| Combler un gap par inférence | Viole l'invariant produit |
| Transformer PARTIAL en affirmation | Trompeur pour l'utilisateur |
| Générer des "peut-être" ou "probablement" | Non auditable |

### 7.3 Formulation

> Le LLM est un **assistant de structuration**, pas un **décideur**.
> Il aide à formuler les claims et classifier les preuves.
> Il ne décide jamais du statut final.

---

## 8. Validation Empirique (POC)

### 8.1 POC v1 : Questions Proches (9 questions)

| Métrique | Résultat |
|----------|----------|
| Coverage | 92.9% |
| Gaps qualifiés | 7 |
| Gaps génériques | 0 |
| Verdict | ✅ VALIDÉ |

**Observation :** Questions similaires (upgrade) mais claims correctement générés et prouvés.

### 8.2 POC v2 : Questions Diversifiées (13 questions, 7 types)

| Métrique | Résultat |
|----------|----------|
| Coverage | 93.8% |
| Gaps qualifiés | 9 |
| Gaps génériques | 0 |
| Types testés | upgrade, conversion, feature, architecture, limitation, integration, compatibility |
| Verdict | ✅ VALIDÉ |

**Observation :** Le système fonctionne sur des questions variées, pas seulement les upgrades.

### 8.3 Signification

Ces POCs constituent une **preuve empirique que la promesse est atteignable**, contrairement aux approches KG précédentes où Pass 3 montrait 97% d'abstention.

---

## 9. Critères de Succès / Échec

### 9.1 Le Système ÉCHOUE si :

| Critère d'Échec | Description |
|-----------------|-------------|
| Conclusion sans evidence | Le système affirme X sans source explicite |
| Gaps génériques | "Not found" au lieu de qualification |
| Résumé LLM dépasse les claims | Le texte généré affirme plus que le Decision Package |
| Statut non déterministe | Deux runs donnent des statuts différents |

### 9.2 Le Système RÉUSSIT si :

L'utilisateur peut dire :

> *"Je vois exactement pourquoi le système ne peut pas conclure."*

Critères mesurables :
- **100%** des conclusions ont au moins une evidence
- **100%** des gaps sont qualifiés (type + description)
- **100%** des gaps ont une preuve documentaire d'absence
- **0%** de régression Claim Coverage sur re-run

### 9.3 Avertissement sur la Métrique "Claim Coverage"

> **La Claim Coverage est une métrique de complétude interne, pas un indicateur de risque ou de confiance.**

| Ce que Claim Coverage mesure | Ce que Claim Coverage ne mesure PAS |
|------------------------------|-------------------------------------|
| Proportion de claims avec evidence | Sécurité de la décision |
| Complétude de la vérification | Niveau de risque |
| Qualité du travail du système | Feu vert pour agir |

**Mise en garde explicite :**
- Une Claim Coverage de 93% **ne signifie pas** "93% de confiance"
- Elle signifie : "93% des obligations de preuve sont satisfaites, 7% ne le sont pas"
- Les 7% non-satisfaits peuvent être critiques

> **Ne jamais utiliser la Claim Coverage comme indicateur de décision dans un dashboard ou une présentation sans contexte.**

---

## 10. Contrat d'Interprétation Utilisateur

Cette section est **rare dans un ADR**, mais ici **elle est justifiée** pour protéger le projet contre toute dérive future.

### 10.1 Transfert de la Charge d'Interprétation

OSMOSIS transfère explicitement la charge d'interprétation :

| De | Vers |
|----|------|
| Capacité du système | Engagement documentaire |
| "Le système ne comprend pas" | "Les documents n'affirment pas" |

### 10.2 Règle d'Interprétation

> Si un utilisateur perçoit un résultat non-supporté comme une **limitation du système**, cela indique un **échec à exposer l'absence documentaire**, pas un échec de raisonnement.

### 10.3 Protection contre la Dérive

Toute modification UX, narrative, ou API qui obscurcit cette distinction **viole l'invariant produit central**.

**Exemples de dérives interdites :**

| Dérive | Pourquoi c'est interdit |
|--------|------------------------|
| "On pourrait ajouter une réponse quand même" | Viole R1 (pas de preuve = pas de support) |
| "Rendre le message d'échec plus sympa" | Risque d'obscurcir la cause documentaire |
| "Laisser le LLM compléter les gaps" | Viole l'invariant de preuve |
| "Masquer les gaps en UI" | Empêche la vérification indépendante |

### 10.4 Engagement Produit

> **Le produit OSMOSIS est défini par sa capacité à refuser de conclure, pas par sa capacité à toujours répondre.**

Un système qui répond toujours est un système qui ment parfois.
OSMOSIS choisit explicitement de ne jamais mentir.

> **OSMOSIS supporte les décisions ; il n'en prend pas la responsabilité.**

Le Decision Package est une **réponse de niveau décision** (Decision-Grade Answer) — pas une réponse conversationnelle, mais un artefact structuré permettant une prise de décision éclairée et auditable.

### 10.5 Interprétations Erronées Anticipées

Cette sous-section liste explicitement les **mauvaises lectures** que ce document cherche à prévenir :

| Interprétation Erronée | Correction |
|------------------------|------------|
| "PARTIAL = presque oui" | PARTIAL = certaines preuves manquent, zone à risque |
| "NOT_SUPPORTED = erreur système" | NOT_SUPPORTED = le corpus n'affirme pas, c'est une information valide |
| "Claim Coverage élevée = décision sûre" | Claim Coverage mesure la complétude, pas la sécurité de la décision |
| "Le système ne trouve pas = le système est nul" | Le système montre ce que les documents n'affirment pas |
| "On pourrait améliorer en répondant quand même" | Répondre sans preuve viole l'invariant fondamental |
| "C'est juste un RAG plus sophistiqué" | La valeur est dans l'abstention qualifiée, pas la réponse |

> **Si vous lisez cet ADR et pensez "mais on pourrait...", relisez la section 0 et la section 4 (Non-Objectifs).**

---

## 11. Implications Long Terme

### 11.1 Séparation Claire des Responsabilités

| Couche | Rôle | Engagement |
|--------|------|------------|
| **Navigation** | Suggestion de documents pertinents | Non engageant |
| **Evidence** | Preuve explicite des claims | Engageant |
| **Narrative** | Résumé textuel pour l'utilisateur | Non engageant, dérivé |

### 11.2 Extensibilité

L'architecture Decision Defense est applicable à :
- Autres domaines normatifs (réglementaire, médical, juridique)
- Autres corpus procéduraux
- Tout contexte où "ne pas savoir" a de la valeur

### 11.3 Fondation pour :

| Capacité | Description |
|----------|-------------|
| **Auditabilité** | Chaque décision est traçable |
| **Gouvernance** | Politiques de validation définissables |
| **Responsabilité** | Clair sur ce qui est prouvé vs inféré |

---

## 12. Références

### Documents Liés
- `doc/adr/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md` - Architecture DocItem
- `src/knowbase/decision/` - Implémentation POC
- `data/decision_package_poc_results_v2.json` - Résultats POC

### Commits de Référence
- `84edb6b` - feat(decision): Implémenter Decision Package v0 POC
- `698386d` - docs: Réorganiser doc/ongoing vers répertoires appropriés

---

## 13. Décision

**ADOPTÉ** : L'architecture Decision Defense devient le paradigme central d'OSMOSIS.

Les travaux futurs doivent :
1. Respecter l'invariant produit (pas de conclusion sans preuve)
2. Étendre les claim templates par type de question
3. Améliorer la classification des evidence types
4. Construire le Decision Board UI

Tout développement qui viole les non-objectifs ou l'invariant produit doit être **explicitement justifié** par un nouvel ADR.

---

*Ce document constitue l'ADR fondateur de la refondation OSMOSIS vers le paradigme Decision Defense.*
