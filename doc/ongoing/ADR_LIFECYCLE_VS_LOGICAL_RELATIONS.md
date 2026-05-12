# ADR : Séparation Logical (Claim→Claim) vs Lifecycle (Doc→Doc)

*Date : 30 avril 2026*
*Statut : **Resserrée le 30/04/2026** — version stricte alignée sur VISION_RECENTREE_OSMOSIS_2026-04-30*
*Contexte : échec de S3.F itérations 1 & 2 (HyDE-inversé) sur la détection SUPERSEDES + recentrage stratégique imposant la séparation KG (faits) / runtime (inférences)*

> **Amendement majeur (30/04/2026)** : suite à la validation de la vision recentrée, cette ADR est resserrée sur le principe « **le KG ne porte que des faits documentés, pas des inférences** ». Le score hybride 4-features initialement proposé est ramené à un seul critère de persistence : la **déclaration textuelle explicite**. Les autres signaux (structural, KG, temporal) deviennent des **indices runtime** consultés par le Current Resolver, sans être fossilisés dans le KG. Voir §4 amendée.

## TL;DR

Le V3.3 actuel persiste les 12 types de `LOGICAL_RELATION` exclusivement au niveau Claim→Claim. Cette uniformité est **incorrecte** pour 3 types : `SUPERSEDES`, `EVOLVES_FROM`, `REAFFIRMS`. Ces relations sont des **propriétés du document** (artefact), pas des assertions. Cette ADR :

1. Réaffirme le principe **domain-agnostic core, domain-specific via Domain Pack uniquement**
2. Sépare la typologie en deux familles : **Logical** (Claim→Claim, 9 types) et **Lifecycle** (Doc→Doc, 3 types)
3. Définit la **règle de composition runtime** entre les deux niveaux (la Lifecycle ne supprime pas la Logical, elle la **requalifie**)
4. Spécifie la migration des relations `SUPERSEDES` Claim→Claim existantes

---

## Contexte et constat

### S3.F : 2 tentatives, 2 échecs

Le 12-class classifier V3.3 a été appliqué au corpus aerospace_compliance avec l'objectif de détecter les successions régulatoires (SUPERSEDES). Deux approches ont été testées :

| Itération | Approche | Résultat |
|---|---|---|
| 1 | HyDE-inversé "smallest claim with identifier" | 21 SUPERSEDES, **précision ~38%** |
| 2 | HyDE-inversé sémantique (LLM Article 1) | 14 SUPERSEDES, **précision ~7%** |

**Diagnostic commun** : les deux approches projettent une relation **document-document** (« doc2 abroge doc1 ») sur un couple **claim-claim** (« claim_b de doc2 succède à claim_a de doc1 »). Cette projection fabrique une approximation fragile :

- Le top-1 sémantique ramène souvent une **citation préambulaire** (« Council Common Position 2008/944/CFSP… ») qui parle de portée mais référence un autre document
- Les heuristiques structurelles (« plus petit claim avec identifiant ») renvoient des entrées de control list (« 1A005… »), pas l'Article 1
- Aucune des deux approches n'est domain-agnostic robuste

### Pourquoi c'est structurellement faux

**SUPERSEDES, EVOLVES_FROM, REAFFIRMS sont des relations entre artefacts**, pas entre assertions :

- « Règlement 2021/821 abroge Règlement 428/2009 » est une propriété **du document 2021/821** (clause d'abrogation, intention éditoriale, date d'effectivité)
- « Article 5 de 2021/821 contredit Article 12 de 428/2009 » est une propriété **des claims** (opposition logique entre deux assertions normatives)

Les deux niveaux co-existent et **portent une information différente**. Forcer SUPERSEDES en Claim→Claim oblige à choisir un claim "représentatif" — ce qui n'est ni nécessaire ni utile pour la sémantique de succession.

Les 9 autres types (`SUBSET, SUPERSET, EQUIVALENT, OVERLAP, DISJOINT, CONFLICT, EXCEPTION, DEFINITION_OF, UNRELATED`) sont bien Claim→Claim — ils décrivent des oppositions ou inclusions d'assertions, indépendamment des artefacts qui les portent.

### Cohérence avec V3.3

V3.3 §3 définit explicitement Lifecycle comme **axe orthogonal** au Scope (axe applicatif) et à la Temporality (axe temporel). On l'avait simplement pas matérialisé dans le schéma de persistence.

---

## Principe directeur (rappel)

> **Le core d'OSMOSIS doit être domain-agnostic. Toute spécificité (réglementaire, biomédical, IT, aerospace…) passe uniquement par le Domain Pack actif.**

Cette ADR formalise une autre conséquence du même principe : **aucune approximation forcée d'un niveau d'abstraction sur un autre niveau** sous prétexte que le schéma actuel ne le supporte pas. Si SUPERSEDES est doc-doc, on persiste doc-doc.

---

## Décision

### 1. Scission de la typologie en deux familles

| Famille | Niveau | Types | Discovery |
|---|---|---|---|
| **Logical** | Claim → Claim | SUBSET, SUPERSET, EQUIVALENT, OVERLAP, DISJOINT, CONFLICT, EXCEPTION, DEFINITION_OF, UNRELATED | Pair selection multi-signal + classifier sémantique LLM |
| **Lifecycle** | DocumentContext → DocumentContext | SUPERSEDES, EVOLVES_FROM, REAFFIRMS | Score hybride doc-doc (structural + KG + temporal + explicit) + LLM evidence-locked |

`UNRELATED` reste dans Logical (skip persistence). Aucun équivalent Lifecycle car l'absence de relation = pas de persistence.

### 2. Schéma de persistence

#### LOGICAL_RELATION (existant, conservé pour 9 types)
```cypher
(:Claim)-[:LOGICAL_RELATION {
  type: 'CONFLICT' | 'SUBSET' | ... ,  // 9 types Logical uniquement
  confidence: float,
  strength: 'strong' | 'moderate' | 'weak' | 'uncertain',
  scope_alignment: string,
  temporal_relation: string,
  is_contradiction: bool,
  reasoning: string,
  derivation_path: string,
  model_id: string,
  extracted_at: datetime
}]->(:Claim)
```

#### LIFECYCLE_RELATION (nouveau, version stricte)
```cypher
(:DocumentContext)-[:LIFECYCLE_RELATION {
  type: 'SUPERSEDES' | 'EVOLVES_FROM' | 'REAFFIRMS',
  confidence: float,
  evidence_quote: string,         // verbatim de la déclaration textuelle (obligatoire)
  evidence_claim_ids: [string],   // claim_ids contenant la quote (preuve traçable)
  source_doc_section: string,     // section_id ou page_no où la clause apparaît
  reasoning: string,
  derivation_path: string,        // 'lifecycle_extractor.v1.evidence_locked'
  model_id: string,               // 'qwen2.5-14b-awq'
  extracted_at: datetime
}]->(:DocumentContext)
```

**Important** :
- `evidence_quote` est **obligatoire** et doit être substring du full_text source (validator post-LLM)
- `evidence_claim_ids` permet l'explicabilité au runtime (drill-down user) — pointer vers les claims réels qui contiennent la quote
- **Aucun champ `*_score` n'est persisté** : les signaux structural/KG/temporal ne sont pas des conditions d'écriture, ils sont consultés runtime par le Current Resolver
- La relation existe **uniquement** au niveau doc, et **uniquement** sur preuve textuelle

### 3. Règle de composition runtime

**Les deux niveaux sont persistés indépendamment. Leur composition est calculée au runtime** par les modes `CONFLICT_RISK`, `SNAPSHOT_TEMPORAL`, `DIFF_EVOLUTION`, et `SUCCESSION_QUERY`. **Aucun des deux niveaux ne supprime ou n'inhibe l'autre dans le KG.**

Matrice de résolution :

| Logical Claim→Claim | Lifecycle Doc→Doc | Interprétation runtime |
|---|---|---|
| `CONFLICT(a∈doc1, b∈doc2)` | `doc2 SUPERSEDES doc1` | ✅ Succession normative — claim_a obsolète, claim_b prévaut. **PAS un vrai conflict** |
| `CONFLICT(a∈doc1, b∈doc2)` | `doc2 EVOLVES_FROM doc1` | ✅ Évolution de règle (cas laser pulse Amdt 27→28). **PAS un vrai conflict** |
| `CONFLICT(a∈doc1, b∈doc2)` | `doc2 REAFFIRMS doc1` | ⚠️ **Incohérence éditoriale** — doc2 prétend réaffirmer mais contredit. Vrai CONFLICT, plus grave |
| `CONFLICT(a∈doc1, b∈doc2)` | **Aucune** Lifecycle | 🔥 **VRAI CONFLICT cross-document** — l'USP d'OSMOSIS |
| `EXCEPTION(a∈doc1, b∈doc2)` | `doc2 SUPERSEDES doc1` | Évolution avec exception préservée — affichage normal |
| `SUBSET / OVERLAP / EQUIVALENT` | n'importe quoi | Pas affecté (relations de portée, pas d'opposition) |

Comportement par persona :
- `compliance_officer` (STRICT) : tous les CONFLICT remontent, ceux résolus par Lifecycle sont taggés `resolved_by_lifecycle: true` (drill-down)
- `explorer` (PERMISSIVE) : CONFLICT résolus filtrés des résultats principaux, drill-down disponible
- `reader` : CONFLICT résolus filtrés totalement

### 4. Discovery doc-doc — version stricte (déclaration explicite uniquement)

> **Amendement 30/04/2026 — version stricte** : conformément à VISION_RECENTREE §1bis, le KG ne porte que des faits documentés, pas des inférences. Le score hybride 4-features initialement proposé est rétrogradé. **Seule la déclaration textuelle explicite déclenche persistence** d'une LIFECYCLE_RELATION.

#### Critère unique de persistence

Une LIFECYCLE_RELATION Doc→Doc est persistée **si et seulement si** :

1. Le full_text d'un document contient une **clause de succession sémantiquement explicite** (« This Regulation repeals X », « This Amendment supersedes Y », « Cette directive abroge Z »)
2. La clause est **extraite par LLM Qwen2.5-14B AWQ** (sémantique pure, pas de regex, multilingue par construction)
3. La quote textuelle extraite est **substring du full_text source** (validator evidence-locked obligatoire)
4. La cible de la clause est **identifiable** (reference à un doc présent dans le KG, par identifiant canonique extrait sémantiquement)

Si l'un de ces 4 critères échoue → **pas de persistence**. La succession éventuelle sera gérée au runtime par le Current Resolver, ou remontée au user comme ambiguïté.

#### Cas explicitement écartés de la persistence

| Cas | Pourquoi pas persisté | Que fait le runtime ? |
|---|---|---|
| Doc B est plus récent que Doc A et traite du même sujet | Inférence (pas un fait documenté) | Current Resolver applique tri date + filtrage validity_dates. Si plusieurs candidats restent → remonte au user |
| Doc B contient des claims qui contredisent Doc A | Inférence sémantique (couvre par les 9 Logical Claim→Claim) | Conflict Detector intra-anchor signale les CONFLICT |
| Convention de versioning implicite (CS-25 Amdt 28 > Amdt 27) | Pas une déclaration textuelle | Current Resolver applique tri date → si CS-25 Amdt 28 valide à today, il est retourné |
| Score KG élevé entre Doc A et Doc B (entity overlap) | Indice de proximité, pas une succession | Indice runtime utilisable par le Current Resolver pour la disambiguation, **non persisté** |

#### Indices runtime (non persistés)

Les signaux suivants restent **calculables à la volée** par le Current Resolver pour aider à trancher en cas d'ambiguïté, mais **ne sont jamais écrits dans le KG** :

- Centralité dans le graphe cross-doc (ABOUT overlap, Cluster overlap)
- Distance temporelle (gap entre publication_dates)
- Trust score / autorité de la source

Si ces indices ne suffisent pas à trancher de manière non ambiguë → **remontée au user**, conformément à VISION_RECENTREE §4 (Posture face à l'ambiguïté).

#### Implémentation

Le LLM extracteur reçoit :
- Le full_text du doc candidat (ou les 5000 premiers chars + sections de clôture où se trouvent typiquement les clauses d'abrogation/effectivité, sélectionnées par section_id)
- Prompt sémantique pur : « Identify any sentence stating that this document repeals, supersedes, modifies, evolves from, or reaffirms another document. Extract the cited document reference and the verbatim quote. »
- Hints Domain Pack si actifs (prose contextuelle, **pas de regex**) : « EU regulations typically state repeal clauses in their final articles »

Output :
```json
{
  "found": true | false,
  "type": "SUPERSEDES" | "EVOLVES_FROM" | "REAFFIRMS" | null,
  "target_doc_reference": "Regulation (EC) No 428/2009",
  "evidence_quote": "This Regulation repeals Regulation (EC) No 428/2009.",
  "confidence": 0.95
}
```

Validator post-LLM :
1. `evidence_quote` ∈ `full_text` (substring match insensible aux espaces multiples) — sinon reject
2. `target_doc_reference` doit matcher un DocumentContext du KG via SubjectResolver — sinon log warning + non-persistence (la cible n'est pas dans le corpus)

Si validation OK → persistence LIFECYCLE_RELATION avec `evidence_claim_ids` peuplé par les claim_ids contenant la quote (preuve traçable au runtime).

### 5. Migration

#### Suppression des Lifecycle Claim→Claim existantes

Les 14 SUPERSEDES Claim→Claim créées par S3.F itération 2 (et toute SUPERSEDES/EVOLVES_FROM/REAFFIRMS pré-existante au niveau Claim) sont **incorrectes par construction** et doivent être supprimées :

```cypher
MATCH ()-[r:LOGICAL_RELATION]->()
WHERE r.type IN ['SUPERSEDES', 'EVOLVES_FROM', 'REAFFIRMS']
DELETE r
```

Aucun dump legacy nécessaire : ces relations sont récentes (S3.F-4) et leur précision a été mesurée < 40%. Les nouvelles relations Lifecycle Doc→Doc seront créées par le pipeline S3.F redémarré.

#### Constraints additifs (pas de drop)

```cypher
CREATE INDEX lifecycle_relation_type IF NOT EXISTS
  FOR ()-[r:LIFECYCLE_RELATION]-() ON (r.type);

CREATE INDEX lifecycle_relation_confidence IF NOT EXISTS
  FOR ()-[r:LIFECYCLE_RELATION]-() ON (r.confidence);
```

#### Logical reste intact

Les 9 types Logical Claim→Claim ne sont **pas affectés**. Le classifier 12-class actuel est simplement réduit à 9-class côté LOGICAL_RELATION. Aucune réingestion, aucun re-run global.

---

## Conséquences

### Impact sur les composants existants

| Composant | Impact |
|---|---|
| `logical_relation_classifier.py` | Retirer les 3 types Lifecycle de la typologie 12-class → 9-class. Output identique pour les 9 types restants |
| `relation_persister_c4.py` | Pas de changement (n'écrit que LOGICAL_RELATION pour les 9 types) |
| Nouveau `lifecycle_relation_classifier.py` | À créer en S3.F redémarré — score hybride + LLM judge |
| Nouveau `lifecycle_relation_persister.py` | À créer — écrit LIFECYCLE_RELATION |
| `runtime/orchestrator.py` mode `SUCCESSION_QUERY` | Re-router sur LIFECYCLE_RELATION Doc→Doc (était sur LOGICAL_RELATION SUPERSEDES Claim→Claim) |
| `runtime/orchestrator.py` mode `CONFLICT_RISK` | Ajouter consultation OPTIONAL MATCH LIFECYCLE_RELATION pour requalification (matrice §3) |
| `runtime/response_composer.py` | Section "Conditions" peut afficher tag `resolved_by_lifecycle: true` selon persona |

### Impact UX

Le compliance officer obtient **deux types de listes distinctes** :

1. **Vrais conflicts cross-document** (CONFLICT sans Lifecycle résolutif) — l'USP d'OSMOSIS, haute valeur
2. **Successions régulatoires documentées** (LIFECYCLE_RELATION) — navigation chronologique inter-versions

Avec une zone grise affichée séparément :
3. **Incohérences éditoriales** (CONFLICT sous REAFFIRMS) — alertes de qualité documentaire

Cette segmentation est claire pour le user final, ce qui n'était pas le cas avec un mix CONFLICT + SUPERSEDES tous Claim→Claim.

### Reproductibilité du raisonnement (preuve d'audit)

Avec le bundle `evidence_claim_ids` attaché à chaque LIFECYCLE_RELATION, on peut afficher au compliance officer :

> « Le doc 2021/821 abroge le doc 428/2009 (confidence 0.92). Preuves textuelles : [claim_a citant clause d'abrogation, claim_b citant date d'effectivité, claim_c citant Article 27 'This Regulation repeals…']. »

Beaucoup plus puissant qu'une SUPERSEDES Claim→Claim entre un Article 1 du nouveau et un Article 1 de l'ancien (qui n'est ni nécessaire ni explicatif).

---

## Alternatives rejetées

### A. Garder SUPERSEDES Claim→Claim et améliorer le HyDE
Pourquoi rejeté : on continuerait à projeter une relation doc-doc sur claim-claim. Les améliorations type "centralité KG", "structural-aware" ou "résumé LLM" sont des palliatifs qui ne résolvent pas le problème conceptuel. La précision plafonnera car on cherche un objet qui n'existe pas (un claim "représentatif" qui synthétise une intention éditoriale doc-level).

### B. SUPERSEDES en Logical avec un attribut "doc_level: true"
Pourquoi rejeté : pollue le schéma Logical avec une exception conditionnelle. Le runtime devrait constamment vérifier l'attribut. Les queries Cypher deviennent verbeuses. Pas plus simple que la séparation propre proposée.

### C. Supprimer SUPERSEDES de la typologie (déférer à plus tard)
Pourquoi rejeté : SUPERSEDES est central pour le mode `SUCCESSION_QUERY` runtime et pour la requalification CONFLICT (matrice §3). Sans Lifecycle, le mode CONFLICT_RISK affiche tous les CONFLICT comme égaux, alors que beaucoup sont des évolutions normales — c'est exactement le bruit que V3.3 cherche à éliminer.

---

## Validation

### Critères d'acceptation pour S3.F redémarré (post-ADR, version stricte)

1. **Aucune relation SUPERSEDES/EVOLVES_FROM/REAFFIRMS Claim→Claim** ne subsiste dans le KG (cleanup S3.F-4 itération 2)
2. **Les paires avec déclaration textuelle explicite** sont détectées :
   - Règlement 2021/821 SUPERSEDES Règlement 428/2009 (clause d'abrogation textuelle attendue dans le 2021/821)
   - Règlement 2023/66 EVOLVES_FROM Règlement 2021/821 (si déclaration textuelle de modification)
3. **Les paires sans déclaration textuelle** ne sont **PAS** persistées (et c'est normal) :
   - CS-25 Amdt 28 vs Amdt 27 si la déclaration n'est pas textuelle → laissé au Current Resolver runtime
   - CS-25 Change Information Amdt 28 vs Amdt 28 → idem
4. **Précision LIFECYCLE_RELATION ≥ 0.95** sur les paires détectées (haute précision attendue car evidence-locked stricte)
5. **Recall mesuré séparément** : sur les paires sans déclaration textuelle, le Current Resolver runtime applique le tri date + remontée d'ambiguïté. Métrique : pas de hiérarchisation implicite incorrecte.
6. **Aucun keyword/regex domain-specific** dans le code core (audit grep sur le pipeline lifecycle)
7. **Aucun champ `*_score` persisté** sur les LIFECYCLE_RELATION (validator schéma)

### Validation user requise avant implémentation

- ✅ Distinction Logical / Lifecycle conceptuellement validée (cette ADR)
- ⏳ Schéma de persistence LIFECYCLE_RELATION validé
- ⏳ Score hybride 4-features validé
- ⏳ Migration suppression SUPERSEDES Claim→Claim validée

---

## Annexe — Cohérence avec les invariants V3.3 et VISION_RECENTREE

| Invariant | Respect (version stricte) |
|---|---|
| Domain-agnostic core | ✅ Aucun composant doc-doc utilise regex/keywords/dataset domain-specific |
| Anti-pattern lexical (V3.3 §0) | ✅ LLM extracteur sémantique pur, evidence-locked |
| **KG porte des faits, pas des inférences (VISION_RECENTREE §1bis)** | ✅ Persistence uniquement sur déclaration textuelle. Aucune inférence persistée |
| **Pas de hiérarchisation implicite (VISION_RECENTREE §11)** | ✅ Pas de score hybride. Le runtime tranche ou remonte au user |
| Evidence-locked validator | ✅ `evidence_quote` obligatoire, doit être substring du full_text |
| Échappatoire Domain Pack | ✅ classifier_hints sémantiques (prose) en input prompt — pas de regex |
| Schéma additif (pas de drop destructif) | ✅ LIFECYCLE_RELATION est ajouté, LOGICAL_RELATION reste sur 9 types |
| Provenance immutable | ✅ Pas de droit de réécriture sur les claims source |

---

*Cette ADR remplace toute approche antérieure de SUPERSEDES Claim→Claim documentée dans CONTRADICTION_DETECTION_ARCHITECTURE.md V3.3 §3.G. Le document V3.3 sera mis à jour en conséquence après validation.*
