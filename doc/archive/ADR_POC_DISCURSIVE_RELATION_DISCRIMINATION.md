# ADR-POC: Discursive Relation Discrimination

**Status:** DRAFT (Cadrage POC)
**Date:** 2026-01-20
**Authors:** Architecture Team (Claude + ChatGPT + Human validation)
**Type:** POC Framing (NOT an architecture decision)

---

## 0. Nature de ce Document

> **Ce document n'est PAS un ADR d'architecture.**
> **C'est un cadrage de POC exploratoire, jetable, et falsifiable.**

Son objectif est de définir :
- Ce que le POC teste exactement
- Les critères de succès et d'échec (pré-définis)
- Le périmètre strict des expérimentations

**Le POC ne produit pas une feature. Il éclaire une décision.**

---

## 1. Contexte et Problème

### 1.1 Constat Initial

OSMOSIS repose sur un invariant fondamental :

> **Aucune relation ne doit être inscrite dans le Knowledge Graph si elle n'est pas explicitement affirmée dans un document.**

Cet invariant garantit une forte fiabilité épistémique. Cependant, il a conduit à un résultat bloquant sur les corpus procéduraux/normatifs (documentation SAP) :

| Observation | Résultat |
|-------------|----------|
| Concepts correctement identifiés | ✅ Nombreux |
| Relations explicites trouvées | ❌ Quasi-nulles |
| Pass 3 (extraction relations) | 97% d'abstention |
| KG exploitable pour raisonnement | ❌ Non |

### 1.2 Cause Racine Identifiée

Les documents normatifs sont écrits pour des **humains** capables de :
- Maintenir un référent sur plusieurs paragraphes
- Comprendre qu'une propriété s'applique au sujet global du document
- Reconstruire des relations implicitement déterminées par le texte

**Exemple canonique :**
```
Document : "SAP S/4HANA Cloud, Private Edition"
[...]
Section 5.3 : "Le SLA de disponibilité est de 99.7%"
```

- Aucune phrase n'affirme explicitement : "S/4HANA Cloud PCE has a SLA of 99.7%"
- Pourtant, pour un humain, le lien est **contraint par le texte**
- OSMOSIS, par prudence, traite ce cas comme une supposition

### 1.3 Pivot Evidence Graph

Un pivot vers une architecture **Decision Defense / Evidence Graph** a été exploré et validé par POC (voir `ADR_DECISION_DEFENSE_ARCHITECTURE.md`).

**Cependant**, avant d'abandonner définitivement l'ambition initiale de KG, nous voulons tester une **hypothèse intermédiaire**, de manière strictement bornée.

---

## 2. Hypothèse à Tester

### 2.1 Question Centrale (et uniquement celle-ci)

> **Un système peut-il distinguer de manière fiable et reproductible :**
> - une **relation implicitement déterminée par le texte** (Type 1)
> - d'une **relation déduite par raisonnement externe** (Type 2) ?

### 2.2 Ce que le POC NE teste PAS

| Non-objectif | Raison |
|--------------|--------|
| "Le LLM peut-il trouver des liens ?" | Réponse connue : oui, toujours |
| "Les liens trouvés sont-ils utiles ?" | Hors périmètre (question générative) |
| "Peut-on enrichir le KG ?" | Prématuré |
| "Cette couche doit-elle exister dans le produit ?" | Décision post-POC |

### 2.3 Formulation Précise

Le POC teste une **capacité discriminative**, pas générative :

> **Le LLM est-il capable de refuser correctement les relations de Type 2,
> tout en acceptant correctement les relations de Type 1 ?**

---

## 3. Distinction Type 1 / Type 2

### 3.1 Type 1 — Relations Discursivement Déterminées (Candidates)

Une relation A → B est de Type 1 si et seulement si :

| Critère | Description |
|---------|-------------|
| **C1** | Le lien est entièrement contenu dans le document |
| **C2** | Il repose sur la continuité discursive (maintien du référent) |
| **C3** | L'absence de sujet alternatif explicite le rend non-ambigu |
| **C4** | Il ne nécessite aucun concept intermédiaire |
| **C5** | Il ne nécessite aucune connaissance externe au texte |
| **C6** | Il ne repose pas sur une chaîne transitive (A→C→B) |

**Caractéristique clé :** Ce n'est pas une supposition, c'est une **reconstruction discursive**.

**Exemple Type 1 :**
```
Document : "S/4HANA Cloud PCE - Service Description"
Section 1 : "Ce document décrit S/4HANA Cloud, Private Edition"
[...]
Section 5 : "Le SLA de disponibilité est de 99.7%"

→ Relation : S/4HANA Cloud PCE ──[HAS_SLA]──> 99.7%
→ Justification : Le référent "S/4HANA Cloud PCE" est maintenu,
                  aucun autre produit n'est introduit,
                  le SLA s'applique au sujet du document.
```

### 3.2 Type 2 — Relations Déduites par Raisonnement (À Rejeter)

Une relation est de Type 2 si elle nécessite :

| Pattern | Description |
|---------|-------------|
| **Transitivité** | A → C et C → B donc A → B |
| **Causalité implicite** | A cause B (non affirmé) |
| **Connaissance externe** | Savoir du domaine non textuel |
| **Concept intermédiaire** | Un concept non mentionné est requis |

**Exemple canonique Type 2 (à rejeter systématiquement) :**
```
Extrait 1 : "Un incendie produit de la fumée"
Extrait 2 : "La fumée déclenche les détecteurs d'incendie"

→ Relation proposée : Incendie ──[TRIGGERS]──> Détecteur
→ Verdict : TYPE 2 - REJECTED
→ Raison : Chaîne transitive (incendie → fumée → détecteur)
           Le lien direct n'est pas affirmé.
```

**Autre exemple Type 2 :**
```
Extrait : "SUM est l'outil standard pour les upgrades SAP"
Contexte : Document sur l'upgrade S/4HANA 2021 → 2023

→ Relation proposée : S/4HANA 2021→2023 ──[REQUIRES]──> SUM
→ Verdict : TYPE 2 - REJECTED
→ Raison : Connaissance externe requise (savoir que SUM s'applique ici)
           Le document ne dit pas explicitement "utilisez SUM pour cet upgrade"
```

### 3.3 Sorties Autorisées du Système

Le POC **doit** produire exclusivement l'une de ces trois sorties :

| Sortie | Signification |
|--------|---------------|
| **ACCEPT (Type 1)** | Relation discursive, référent résolu, justifiable par le texte seul |
| **REJECT (Type 2)** | Relation déduite, transitive, causale ou nécessitant connaissance externe |
| **ABSTAIN** | Référent rompu, contexte insuffisant, texte non contraignant |

**Règle critique :**
> **Forcer une décision ACCEPT ou REJECT sur un cas ambigu = échec du POC.**

---

## 4. Critère Discriminant Formel

### 4.1 Conditions d'Acceptation (toutes requises)

Une relation A → B est **acceptable (Type 1)** si et seulement si sa justification :

1. ✅ Ne fait intervenir **aucun concept absent du texte**
2. ✅ Ne fait intervenir **aucun mécanisme absent du texte**
3. ✅ Ne repose pas sur une **chaîne transitive** (A → C → B)
4. ✅ Ne nécessite **aucune connaissance du monde externe**
5. ✅ Repose **uniquement** sur la résolution de référent et le périmètre discursif
6. ✅ Est justifiable par **citation textuelle exclusive**

### 4.2 Opérationnalisation de la Condition 4

La condition "aucune connaissance externe" est difficile à tester directement (un LLM ne peut pas "désapprendre").

**Solution retenue :**

> Le LLM n'est autorisé à justifier une relation qu'en **citant exclusivement les extraits fournis**.

- On ne contrôle pas ce qu'il *pense*
- On contrôle ce qu'il *peut invoquer*

Si une relation ne peut pas être justifiée par citation textuelle, elle est rejetée, **même si elle est "évidente" pour un expert du domaine**.

---

## 5. Jeu de Tests

### 5.1 Structure des Cas de Test

Chaque cas de test comprend :

```yaml
test_case:
  id: "TC-001"
  document_context:
    title: "..."
    scope: "..."  # 1 extrait de contexte global
  concept_a:
    name: "..."
    extracts: [...]  # 1-2 extraits max
  concept_b:
    name: "..."
    extracts: [...]  # 1-2 extraits max
  expected_output: ACCEPT | REJECT | ABSTAIN
  rationale: "..."  # Pourquoi cette sortie est attendue
  category: CANONICAL_TYPE1 | CANONICAL_TYPE2 | FRONTIER
```

### 5.2 Cas Canoniques Type 1 (à accepter)

**Source:** `020_RISE_with_SAP_Cloud_ERP_Private_full.pdf`

| ID | Scénario | Pourquoi Type 1 |
|----|----------|-----------------|
| TC-T1-01 | PCE Business Continuity: PROD SLA 99.7 | Référent explicite dans titre de slide |
| TC-T1-02 | Autoscaling "not applicable" dans RISE | Assertion explicite FAQ |
| TC-T1-03 | WAF sécurise internet inbound | Relation textuelle directe |
| TC-T1-04 | Coréférence "this managed cloud service" → PCE | Résolution de référent discursive |

### 5.3 Cas Canoniques Type 2 (à rejeter)

| ID | Scénario | Pourquoi Type 2 |
|----|----------|-----------------|
| TC-T2-01 | Active-Active AZ → PROD SLA 99.7 | Causalité mécanistique non affirmée |
| TC-T2-02 | "ALWAYS internal/trusted" vs exception "unless" | Quantificateur plus fort que le texte |
| TC-T2-03 | Reserved Instances → autoscaling support | Conclusion causale inversée |
| TC-T2-04 | End-to-end SLA = 99.7 | Consolidation cross-extraits sans pont |
| TC-T2-05 | S/4HANA → HANA Database | Connaissance externe latente (même dans le nom) |

### 5.4 Cas Frontières (critiques pour le POC)

| ID | Scénario | Difficulté |
|----|----------|------------|
| TC-FR-01 | CDC Option a-t-il le SLA 99.7 ? | Périmètre multi-contexte (hyperscaler vs CDC) |
| TC-FR-02 | RTO = 12h ou 4h Enhanced ? | Valeurs alternatives, ne pas trancher |
| TC-FR-03 | RPO = 0 ou 30 minutes ? | Valeurs alternatives, ne pas trancher |
| TC-FR-04 | "not recommended" ≠ "not supported" | Nuance normative (REJECT aussi acceptable) |
| TC-FR-05 | RISE "ALWAYS" uses WAF ? | Conditionalité "In such cases" |

**Règle pour les cas frontières :**
> Le système doit répondre ABSTAIN dans **au moins 60%** des cas frontières.
> S'il tranche systématiquement, il est sur-confiant.

---

## 6. Critères d'Échec (Pré-définis, Non Négociables)

### 6.1 Échecs Quantitatifs

| Critère | Seuil | Conséquence |
|---------|-------|-------------|
| Faux positifs Type 2 | > 10% des Type 2 acceptés | ❌ POC en échec |
| Sur-décision frontières | < 40% ABSTAIN sur frontières | ❌ POC en échec |
| Justification non textuelle | > 0 cas | ❌ POC en échec |

### 6.2 Échecs Qualitatifs

| Critère | Description | Conséquence |
|---------|-------------|-------------|
| Relation acceptée sans citation | Justification "évidente" mais non textuelle | ❌ POC en échec |
| Pattern "oui mais..." | Acceptation avec réserves non tracées | ❌ POC en échec |
| Transitivité masquée | A→B accepté via C non mentionné dans justification | ❌ POC en échec |

### 6.3 Ce qui N'est PAS un Échec

| Observation | Interprétation |
|-------------|----------------|
| Beaucoup de REJECT | Système conservateur (acceptable) |
| Beaucoup d'ABSTAIN | Système prudent (acceptable) |
| Peu d'ACCEPT | Non problématique si les ACCEPT sont corrects |

> **Le POC peut échouer "par excès de prudence".**
> **Il ne peut pas réussir "par excès d'audace".**

---

## 7. Protocole d'Exécution

### 7.1 Construction des Evidence Bundles

Pour chaque paire de concepts (A, B) :

```
Evidence Bundle
├── Scope (optionnel)
│   └── 0-1 extrait de contexte global (titre, intro)
├── Concept A
│   └── 1-2 extraits max (les plus représentatifs)
└── Concept B
    └── 1-2 extraits max (les plus représentatifs)

Total : 4-5 extraits MAXIMUM
```

**Règle :** Jamais "tous les chunks" d'un concept.

### 7.2 Prompt Système (Contrainte Stricte)

```markdown
Tu dois analyser si une relation entre deux concepts est DISCURSIVEMENT
DÉTERMINÉE par le texte ou si elle nécessite un RAISONNEMENT EXTERNE.

RÈGLES ABSOLUES :
1. Tu ne peux justifier une relation qu'en CITANT les extraits fournis
2. Tu dois IGNORER toute connaissance que tu pourrais avoir sur le domaine
3. Si tu ne peux pas justifier par citation textuelle → REJECT ou ABSTAIN
4. Si le référent est ambigu ou rompu → ABSTAIN
5. Si une chaîne transitive est requise → REJECT

SORTIES AUTORISÉES :
- ACCEPT : Relation discursive, justifiable par le texte seul
- REJECT : Relation nécessitant raisonnement externe ou transitivité
- ABSTAIN : Contexte insuffisant ou ambigu

Pour chaque décision, tu DOIS fournir :
1. La sortie (ACCEPT/REJECT/ABSTAIN)
2. Les citations textuelles exactes utilisées
3. Le raisonnement de résolution de référent (si ACCEPT)
4. La raison du rejet (si REJECT) : TRANSITIVE | EXTERNAL_KNOWLEDGE | CAUSAL | OTHER
5. La raison de l'abstention (si ABSTAIN) : BROKEN_REFERENT | AMBIGUOUS | INSUFFICIENT
```

### 7.3 Format de Sortie Attendu

```json
{
  "test_case_id": "TC-001",
  "verdict": "ACCEPT | REJECT | ABSTAIN",
  "citations": [
    {"extract_id": "A1", "quote": "..."},
    {"extract_id": "B2", "quote": "..."}
  ],
  "referent_resolution": "Le document établit que... donc le SLA s'applique à...",
  "reject_reason": null | "TRANSITIVE" | "EXTERNAL_KNOWLEDGE" | "CAUSAL",
  "abstain_reason": null | "BROKEN_REFERENT" | "AMBIGUOUS" | "INSUFFICIENT",
  "confidence_self_assessment": "HIGH | MEDIUM | LOW"
}
```

---

## 8. Analyse des Résultats

### 8.1 Ce que le POC Produit

**PAS un score global.**

Une analyse qualitative structurée :

| Catégorie | Métriques |
|-----------|-----------|
| Type 1 correctement acceptés | N / total Type 1 |
| Type 2 correctement rejetés | N / total Type 2 |
| Frontières avec ABSTAIN | N / total frontières |
| Justifications valides (citation) | N / total ACCEPT |
| Erreurs critiques | Liste détaillée |

### 8.2 Grille de Décision Post-POC

| Résultat | Interprétation | Action |
|----------|----------------|--------|
| Critères d'échec atteints | Distinction non opérable | Abandon piste, pivot Evidence Graph confirmé |
| Critères OK mais ABSTAIN >80% | Système trop conservateur | Piste techniquement valide mais peu utile |
| Critères OK, équilibre raisonnable | Distinction opérable | Piste à approfondir (nouvel ADR requis) |

---

## 9. Contraintes d'Implémentation

### 9.1 Ce que le POC DOIT être

| Contrainte | Raison |
|------------|--------|
| ✅ Jetable | Pas de dette technique |
| ✅ Sans persistance | Pas de pollution du KG |
| ✅ Sans modification du pipeline | Isolation totale |
| ✅ Reproductible | Même input → même analyse |
| ✅ Documenté | Chaque décision traçable |

### 9.2 Ce que le POC NE DOIT PAS être

| Interdit | Raison |
|----------|--------|
| ❌ Une feature | Prématuré |
| ❌ Une orientation produit | Décision post-POC |
| ❌ Intégré au système | Risque de contamination |
| ❌ Utilisé en production | POC exploratoire uniquement |

---

## 10. Décision Attendue

À l'issue du POC, exactement l'une de ces conclusions :

### Conclusion A : Échec → Abandon

> La distinction Type 1 / Type 2 n'est pas opérable de manière fiable.
> Le pivot Evidence Graph est définitivement justifié.
> Cette piste est abandonnée sans regret.

### Conclusion B : Succès partiel → Investigation limitée

> La distinction est techniquement possible mais le système est trop conservateur.
> Valeur ajoutée incertaine. Investigation optionnelle.

### Conclusion C : Succès → Nouvelle phase

> La distinction est opérable et produit des résultats exploitables.
> Un nouvel ADR doit définir si/comment cette capacité s'intègre au produit.
> **Cette capacité ne doit JAMAIS contaminer la couche Evidence.**

---

## 11. Références

- `doc/ongoing/ADR_DECISION_DEFENSE_ARCHITECTURE.md` — Paradigme Evidence Graph
- `doc/adr/ADR-20260106-graph-first-architecture.md` — Architecture Graph-First
- `src/knowbase/relations/evidence_bundle_models.py` — Modèles Evidence Bundle
- `src/knowbase/semantic/models.py` — Modèles Concepts

---

*Ce document constitue le cadrage du POC "Discursive Relation Discrimination".
Il sera archivé avec les résultats du POC, quelle que soit la conclusion.*
