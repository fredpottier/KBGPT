# Domain Packs — Architecture des Packages Métier OSMOSE

*Date : 2026-03-15*
*Statut : Constat + Étude exploratoire*

---

## 1. Constat : Le problème des claims isolées

### Mesures sur le corpus PMC (biomédical)

| Métrique | Valeur | % |
|----------|--------|---|
| Total claims | 22 433 | 100% |
| Ont structured_form | 2 530 | 11.3% |
| Ont relation ABOUT (liées à une Entity) | 10 411 | 46.4% |
| Ont CHAINS_TO | 505 | 2.3% |
| **Claims isolées** | **11 623** | **51.8%** |

### Comparaison corpus SAP (entreprise)

Pour le corpus SAP (documents techniques, marketing, fonctionnels), le taux de claims isolées est de ~15-20%. L'écart s'explique par la nature des entités :

- **SAP** : noms de produits explicites, acronymes récurrents (BTP, S/4HANA, SAC), termes capitalisés → l'extracteur générique les capture bien.
- **PMC biomédical** : concepts souvent en minuscules ("sepsis", "biomarkers"), nomenclature spécialisée ("SOFA score", "qSOFA"), molécules avec conventions de nommage variées → l'extracteur générique rate ~50% des entités.

### Analyse qualitative des claims isolées

Les claims isolées PMC ne sont **pas** du bruit. Exemples :

- *"Antibiotics should be administered within 60 minutes after the arrival of a patient with suspected sepsis."*
- *"CRP and IL-6 in combination reached 95% positive and 90% negative predictive values for infection."*
- *"IL-6 peaked in the emergency department, whereas CRP and PCT peaked later."*

Ce sont des claims à haute valeur qui mentionnent des concepts biomédicaux non capturés comme entités par l'extracteur générique.

### Diagnostic

Le taux élevé de claims isolées n'est pas un bug — c'est une **limite structurelle de l'extraction d'entités domain-agnostic** face à un corpus spécialisé. L'extracteur actuel repose sur 6 sources déterministes (patterns syntaxiques, acronymes majuscules, termes capitalisés, CamelCase, titres de section, structured_form) qui sont biaisées vers les entités "évidentes" visuellement.

---

## 2. Principe architectural : Domain Packs

### L'invariant OSMOSE

> Le moteur OSMOSE est **domain-agnostic au niveau du code**. Aucun terme métier, aucune ontologie, aucun pattern spécifique à un domaine n'est hardcodé dans le core.

Cet invariant est fondamental et doit être préservé.

### La solution : packages métier activables

Un **Domain Pack** est un bundle de configuration et d'extracteurs spécialisés qu'un administrateur active pour un tenant. Le moteur core ne change pas — le pack injecte de l'expertise domaine aux points d'extension prévus.

```
┌─────────────────────────────────────────────────────────┐
│                    OSMOSE Core Engine                    │
│  (domain-agnostic, invariant, ne change jamais)         │
│                                                         │
│  EntityExtractor → EntityCanonicalizer → EntityLinker   │
│  ClaimExtractor → StructuredFormBuilder → ...           │
│                                                         │
│         ▲              ▲              ▲                 │
│         │              │              │                 │
│    ┌────┴────┐    ┌────┴────┐    ┌────┴────┐           │
│    │ Hook 1  │    │ Hook 2  │    │ Hook 3  │           │
│    │ Post-   │    │ Domain  │    │ QS      │           │
│    │ Entity  │    │ Context │    │ Patterns│           │
└────┴─────────┴────┴─────────┴────┴─────────┴───────────┘
         ▲              ▲              ▲
         │              │              │
┌────────┴──────────────┴──────────────┴─────────────────┐
│              Domain Pack "biomedical"                    │
│                                                         │
│  ✅ DomainContextProfile (acronyms, key_concepts, ...)  │
│  ✅ DomainEntityExtractor (nomenclature biomédicale)    │
│  ✅ QuestionSignature patterns (clinical patterns)      │
│  ✅ Entity stoplist domaine (PubMed, SPSS, ...)         │
│  ✅ Axis hints (study_type, population, ...)            │
└─────────────────────────────────────────────────────────┘
```

### Cycle de vie d'un import avec Domain Pack

```
1. Import document
   │
2. Pipeline Core (domain-agnostic)
   ├── Claim extraction (LLM, générique)
   ├── Entity extraction (patterns génériques : capitalized, acronyms, syntax)
   ├── Entity canonicalization (LLM, groupement variantes)
   └── Entity linking (text matching → ABOUT)
   │
3. Post-processing Domain Pack (activé par l'admin)    ← NOUVEAU
   ├── Domain Entity Extractor PROPOSE des candidats entités
   │   (NER spécialisé sur les claims non couvertes)
   ├── Le core VALIDE les candidats (stoplist, is_valid_entity_name, dedup)
   ├── Le core PERSISTE les entités validées + relations ABOUT
   ├── QS patterns domaine soumis au même pipeline de validation
   └── Axis hints domaine (study_type, population_type, ...)
   │
4. Résultat : couverture entity/claim passe de ~46% à ~80%+
```

### Avantages de cette approche

| Aspect | Bénéfice |
|--------|----------|
| **Core intact** | On ne touche pas à l'EntityExtractor générique qui fonctionne |
| **Additif, pas substitutif** | Le pack complète, il ne remplace rien |
| **Rejouable** | On peut relancer le post-processing sur un corpus existant |
| **Activable/désactivable** | Un admin active un pack dans l'UI, pas de code à déployer |
| **Testable isolément** | Chaque pack a ses propres tests unitaires |
| **Nouveau domaine = nouveau pack** | Pas de modification du core pour un nouveau secteur |

---

## 3. Anatomie d'un Domain Pack

### Structure fichier

```
src/knowbase/domain_packs/
├── __init__.py
├── registry.py              # Registre des packs disponibles
├── base.py                  # Classe abstraite DomainPack
│
├── biomedical/
│   ├── __init__.py
│   ├── pack.py              # BiomedicalPack(DomainPack)
│   ├── entity_extractor.py  # NER biomédical (scispaCy / HuggingFace)
│   ├── qs_patterns.py       # QuestionSignature patterns cliniques
│   ├── stoplist.py          # Termes bruit biomédicaux
│   ├── context.py           # DomainContextProfile pré-rempli
│   ├── requirements.txt     # Dépendances NER (scispacy, en_ner_bc5cdr_md, ...)
│   └── tests/
│       └── test_biomedical_entities.py
│
├── enterprise_sap/
│   ├── __init__.py
│   ├── pack.py              # SAPPack(DomainPack)
│   ├── entity_extractor.py  # NER custom fine-tuné sur corpus SAP
│   ├── context.py           # Acronyms SAP, concepts clés
│   ├── requirements.txt     # Dépendances NER
│   └── tests/
│
└── regulatory/              # Futur
    └── ...
```

### Classe abstraite DomainPack

```python
class DomainPack(ABC):
    """Package métier activable pour un tenant."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifiant unique du pack (ex: 'biomedical')."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Nom affiché dans l'UI (ex: 'Biomédical / Sciences de la vie')."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Description pour l'admin."""

    @property
    def priority(self) -> int:
        """Priorité d'exécution quand plusieurs packs sont actifs.

        Plus le nombre est élevé, plus le pack s'exécute en premier.
        Résout les conflits quand un claim matche plusieurs packs :
        le pack prioritaire a la préférence pour le typage d'entité.

        Valeurs indicatives :
            100 = pack domaine principal (biomedical, enterprise_sap)
             50 = pack transverse (regulatory, compliance)
              0 = pack générique / fallback
        """
        return 50

    def get_domain_context_defaults(self) -> dict:
        """Valeurs par défaut pour DomainContextProfile.

        Pré-remplit common_acronyms, key_concepts, etc.
        L'admin peut ensuite personnaliser.
        """
        return {}

    def get_entity_extractors(self) -> List[DomainEntityExtractor]:
        """Extracteurs d'entités complémentaires.

        Chaque extracteur reçoit les claims et retourne
        des entités + liens ABOUT supplémentaires.
        """
        return []

    def get_qs_patterns(self) -> List[dict]:
        """Patterns QuestionSignature domaine."""
        return []

    def get_entity_stoplist(self) -> List[str]:
        """Termes à exclure spécifiques au domaine."""
        return []

    def get_axis_hints(self) -> dict:
        """Hints pour la détection d'axes d'applicabilité."""
        return {}
```

### Interface DomainEntityExtractor

```python
class DomainEntityExtractor(ABC):
    """Extracteur d'entités spécialisé domaine.

    Opère en post-processing sur les claims non couvertes
    par l'extracteur générique.
    """

    @abstractmethod
    def extract(
        self,
        claims: List[Claim],
        existing_entities: List[Entity],
        domain_context: DomainContextProfile,
    ) -> Tuple[List[Entity], Dict[str, List[str]]]:
        """
        Args:
            claims: Claims à analyser (typiquement les isolées)
            existing_entities: Entités déjà extraites (pour éviter doublons)
            domain_context: Profil domaine du tenant

        Returns:
            (nouvelles_entités, {claim_id: [entity_ids]})
        """
```

---

## 4. Exemple : Domain Pack "biomedical"

### Choix technique : NER spécialisé, pas de regex

#### Pourquoi pas de regex

L'approche regex (listes de patterns, suffixes pharmaceutiques, dictionnaires de termes) est tentante pour un MVP mais **incompatible avec un produit production-grade** :

| Problème | Impact |
|----------|--------|
| **Faux positifs exponentiels** | `r'\b[A-Z][a-z]+\s+[a-z]+\b'` pour les pathogènes matche aussi "Figure shows", "Table presents", etc. |
| **Maintenance non scalable** | Chaque nouveau corpus apporte des cas non couverts → regex toujours en retard |
| **Pas de contexte** | Un regex ne sait pas que "IL-6" est un biomarqueur dans un contexte clinique mais un identifiant dans un contexte technique |
| **Couverture plafonnée** | Un dictionnaire de termes couvre les connus mais rate systématiquement les nouveaux (nouveaux biomarqueurs, nouvelles molécules) |
| **Fragilité aux variantes** | "E. coli", "Escherichia coli", "E coli", "ECOLI" → une regex par variante |

On investirait du temps sur quelque chose qui ne scale pas. Un produit visant la production doit s'appuyer sur des modèles NER pré-entraînés sur le domaine cible.

#### Stratégie NER par pack

Chaque Domain Pack embarque un **modèle NER spécialisé léger** qui détecte les entités domaine avec leur type. L'écosystème des modèles NER open-source est mature et couvre les principaux domaines :

| Pack | Modèle NER candidat | Types détectés | Taille |
|------|---------------------|----------------|--------|
| `biomedical` | `en_ner_bc5cdr_md` (scispaCy) | Chemical, Disease | ~50 MB |
| `biomedical` | `en_ner_bionlp13cg_md` (scispaCy) | Gene, Cell, Organism, ... | ~50 MB |
| `biomedical` | `d4data/biomedical-ner-all` (HF) | 40+ types biomédicaux | ~400 MB |
| `enterprise_sap` | Fine-tuned custom sur corpus SAP | Product, Service, Module, ... | ~100 MB |
| `regulatory` | `Jean-Baptiste/camembert-ner` + fine-tune | Organization, Legal_ref, ... | ~400 MB |
| `cybersecurity` | `CyNER` (HF) | Malware, Vulnerability, Tool | ~100 MB |

#### Architecture d'intégration

```python
class DomainEntityExtractor(ABC):
    """Extracteur NER spécialisé domaine."""

    @abstractmethod
    def load_model(self) -> None:
        """Charge le modèle NER (lazy, une seule fois)."""

    @abstractmethod
    def extract(
        self,
        claims: List[Claim],
        existing_entities: List[Entity],
        domain_context: DomainContextProfile,
    ) -> Tuple[List[Entity], Dict[str, List[str]]]:
        """Extrait les entités domaine via NER."""

    @property
    @abstractmethod
    def entity_type_mapping(self) -> Dict[str, EntityType]:
        """Mapping types NER → EntityType OSMOSE.

        Exemple biomédical :
            'CHEMICAL' → EntityType.CONCEPT
            'DISEASE'  → EntityType.CONCEPT
            'GENE'     → EntityType.CONCEPT
        """
```

```python
class BiomedicalEntityExtractor(DomainEntityExtractor):
    """NER biomédical basé sur scispaCy ou HuggingFace."""

    def __init__(self):
        self._nlp = None  # Lazy loading

    def load_model(self):
        import spacy
        self._nlp = spacy.load("en_ner_bc5cdr_md")

    def extract(self, claims, existing_entities, domain_context):
        if not self._nlp:
            self.load_model()

        existing_norms = {e.normalized_name for e in existing_entities}
        new_entities = []
        claim_entity_map = {}

        for claim in claims:
            doc = self._nlp(claim.text)
            for ent in doc.ents:
                norm = Entity.normalize(ent.text)
                if norm in existing_norms:
                    continue  # Déjà extrait par le core
                if not is_valid_entity_name(ent.text):
                    continue  # Filtré par les gates core
                # ... créer Entity, mapper au claim
        return new_entities, claim_entity_map

    @property
    def entity_type_mapping(self):
        return {
            "CHEMICAL": EntityType.CONCEPT,
            "DISEASE": EntityType.CONCEPT,
            "GENE_OR_GENE_PRODUCT": EntityType.CONCEPT,
            "ORGANISM": EntityType.CONCEPT,
        }
```

#### Cycle de vie du modèle NER

1. **Embarqué dans le pack** : le modèle est une dépendance pip (`scispacy`, `en_ner_bc5cdr_md`) ou un artefact téléchargé au premier usage
2. **Lazy loading** : le modèle n'est chargé en mémoire que quand le pack est actif et qu'un post-processing est lancé
3. **Inference CPU** : les modèles NER spaCy/HuggingFace légers (<500 MB) tournent en CPU sans problème (ms par claim)
4. **Pas de fine-tuning en prod** : le modèle est pré-entraîné. Le fine-tuning sur corpus client est un processus offline séparé (optionnel, hors scope v1)

#### Pourquoi c'est supérieur aux regex dès le jour 1

- **Contexte** : le NER comprend que "resistance" dans "antimicrobial resistance" est un concept biomédical mais que "resistance" seul dans "resistance to change" ne l'est pas
- **Variantes** : le modèle reconnaît "E. coli", "Escherichia coli", "E coli" sans regex explicite
- **Couverture ouverte** : un NER biomédical reconnaît des entités qu'aucun dictionnaire ne contient (nouvelles molécules, nouveaux pathogènes) car il a appris la structure du domaine
- **Maintenance zéro** : pas de liste de patterns à maintenir manuellement
- **Précision élevée** : les modèles scispaCy ont des F1 > 85% sur les benchmarks biomédicaux, vs ~50-60% pour des regex manuelles sur un corpus diversifié

### DomainContext pré-rempli

```python
def get_domain_context_defaults(self) -> dict:
    return {
        "domain_summary": "Biomedical and clinical research literature",
        "industry": "healthcare_life_sciences",
        "common_acronyms": {
            "PCT": "Procalcitonin",
            "CRP": "C-Reactive Protein",
            "IL-6": "Interleukin-6",
            "SOFA": "Sequential Organ Failure Assessment",
            "ICU": "Intensive Care Unit",
            "ED": "Emergency Department",
            "RCT": "Randomized Controlled Trial",
            "AUC": "Area Under the Curve",
            "ROC": "Receiver Operating Characteristic",
            "CI": "Confidence Interval",
            "HR": "Hazard Ratio",
            "OR": "Odds Ratio",
            "NNT": "Number Needed to Treat",
            # ...
        },
        "key_concepts": [
            "antibiotic stewardship", "antimicrobial resistance",
            "point-of-care testing", "biomarker-guided therapy",
            "diagnostic accuracy", "sensitivity", "specificity",
            # ...
        ],
    }
```

### QuestionSignature patterns cliniques

```python
def get_qs_patterns(self) -> List[dict]:
    return [
        # PICO pattern (Population, Intervention, Comparison, Outcome)
        {"pattern": r"(?:In|Among)\s+(.+?),?\s+(?:does|is|can)\s+(.+?)\s+(?:compared?\s+(?:to|with)\s+)?(.+)",
         "type": "clinical_comparison"},
        # Diagnostic accuracy
        {"pattern": r"(?:sensitivity|specificity|PPV|NPV|AUC)\s+(?:of|for)\s+(.+?)\s+(?:was|is|=)",
         "type": "diagnostic_performance"},
        # Prognostic
        {"pattern": r"(.+?)\s+(?:predict(?:s|ed)?|associat(?:ed)?)\s+(?:with\s+)?(.+?)(?:mortality|outcome|survival)",
         "type": "prognostic_marker"},
    ]
```

---

## 5. Intégration dans le pipeline

### Point d'insertion dans l'orchestrateur

Le post-processing domaine s'insère **après** la phase 4 (linking) ou comme phase rejouable indépendante :

```
Phase 4 : Linking (core)
    ↓
Phase 5 : Domain Pack Post-Processing (si pack actif)       ← NOUVEAU
    ├── 5.1 : Pack PROPOSE des candidats entités (NER sur claims sans ABOUT)
    ├── 5.2 : Core VALIDE les candidats (is_valid_entity_name, stoplist, dedup)
    ├── 5.3 : Core CANONICALISE (EntityCanonicalizer, AcronymDedupRule)
    ├── 5.4 : Core PERSISTE entités validées + relations ABOUT
    └── 5.5 : Pack PROPOSE des QS patterns → Core VALIDE et PERSISTE
```

### Rejouabilité

Un point clé : le post-processing domaine est **rejouable** sur un corpus existant. Si l'admin active un pack après avoir déjà importé 30 documents :

1. API : `POST /api/domain-packs/biomedical/reprocess`
2. Le pack re-scanne les claims isolées (sans ABOUT) et **propose** des candidats
3. Le core **valide** les candidats (mêmes gates que le pipeline normal)
4. Le core **persiste** les entités validées + relations ABOUT
5. Le taux d'isolées passe de ~52% à ~15-20%

Aucun ré-import nécessaire.

### Administration UI

Page admin `/admin/domain-packs` :

```
┌─────────────────────────────────────────────────┐
│  Domain Packs                                    │
│                                                  │
│  ┌──────────────────────┐  ┌──────────────────┐ │
│  │ 🧬 Biomédical        │  │ 🏢 Enterprise SAP │ │
│  │ Sciences de la vie   │  │ ERP / Cloud       │ │
│  │                      │  │                   │ │
│  │ Status: Actif ✅     │  │ Status: Inactif   │ │
│  │ Entities: +3,241     │  │                   │ │
│  │ Claims couvertes:    │  │  [Activer]        │ │
│  │   46% → 81% (+35%)  │  │                   │ │
│  │                      │  │                   │ │
│  │ [Configurer] [Relancer] │                   │ │
│  └──────────────────────┘  └──────────────────┘ │
└─────────────────────────────────────────────────┘
```

---

## 6. Autres Domain Packs envisageables

| Pack | Domaine | Patterns spécifiques |
|------|---------|---------------------|
| `biomedical` | Sciences de la vie, clinique | Biomarqueurs, scores, pathogènes, médicaments, PICO |
| `enterprise_sap` | Écosystème SAP | Produits SAP, modules, transactions, Fiori apps |
| `regulatory` | Réglementaire / compliance | Articles de loi, normes ISO, directives EU |
| `cybersecurity` | Sécurité informatique | CVE, CWE, MITRE ATT&CK, protocoles |
| `financial` | Finance / assurance | Instruments financiers, ratios, réglementations |
| `legal` | Juridique / contractuel | Clauses types, termes juridiques, jurisprudence |

Chaque pack = un dossier avec extracteurs + contexte + tests. Développement indépendant, déploiement par simple ajout au registre.

---

## 7. Prochaines étapes

| # | Action | Effort |
|---|--------|--------|
| 1 | Créer la classe abstraite `DomainPack` + `DomainEntityExtractor` + registre | S |
| 2 | Intégrer le hook post-processing dans l'orchestrateur (Phase 5) | M |
| 3 | Implémenter le pack `biomedical` (MVP : extracteur + context defaults) | M |
| 4 | API activation/désactivation + reprocess | M |
| 5 | Page admin `/admin/domain-packs` | M |
| 6 | Mesurer l'impact sur le taux d'isolées PMC | S |
| 7 | Pack `enterprise_sap` (migration du context existant) | S |

---

## 8. Invariant fondamental — Souveraineté épistémique du core

### Le piège : la dérive d'un pack enrichisseur vers un pack décideur

Le risque principal des Domain Packs n'est pas technique — il est **épistémique**. Si un pack commence à influencer non seulement *ce qui est détecté* mais aussi *ce qui est considéré comme vrai*, on ne possède plus un seul OSMOSE mais autant de systèmes que de packs actifs, chacun avec sa propre ontologie implicite de la vérité.

Ce piège est insidieux car il arrive par concessions successives :

1. "On ajoute une stoplist domaine" (OK — détection)
2. "On assouplit un seuil pour le biomédical" (DANGER — politique de promotion)
3. "On promeut automatiquement tel pattern clinique" (DANGER — politique de preuve)
4. "On adapte la canonicalisation à ce domaine" (DANGER — gouvernance)

Au bout de 6 mois, le core est prétendument agnostique mais la logique métier a fui dans les packs.

### Le test décisif

> **Si je désactive le pack et rejoue le corpus, est-ce que j'obtiens moins de couverture... ou une autre définition de la connaissance ?**

- Moins de couverture → sain. Le pack est un producteur de candidats.
- Autre logique de vérité → problème. Le pack est devenu un arbitre silencieux.

### L'invariant

> **INV-PACK : Un Domain Pack est autorisé à augmenter le recall et la précision de détection locale, mais interdit de modifier les politiques de promotion, de preuve, de gouvernance et de traversabilité du core.**

Dit autrement :

> **Un Domain Pack peut proposer plus de matière, mais il ne doit jamais changer les lois de la gravité d'OSMOSE.**

Le pack enrichit les entrées. Le core garde le monopole de la décision.

### Séparation formelle des interfaces

L'interface `DomainPack` doit refléter cette frontière dans son contrat :

**Extensions autorisées** (production de candidats) :

| Méthode | Rôle |
|---------|------|
| `get_entity_extractors()` | Nouveaux candidats entités |
| `get_qs_patterns()` | Patterns de questions supplémentaires |
| `get_axis_hints()` | Indices pour la détection d'axes |
| `get_entity_stoplist()` | Termes bruit spécifiques au domaine |
| `get_domain_context_defaults()` | Acronymes, concepts clés, hints |
| `get_linking_hints()` | Indices de liaison claim→entity |

**Extensions interdites** (le pack ne doit JAMAIS exposer) :

| Politique | Pourquoi c'est interdit |
|-----------|------------------------|
| Politique de promotion | Décide ce qui "monte" dans le KG — souveraineté core |
| Politique de preuve | Décide ce qui constitue une evidence — invariant épistémique |
| Politique de contradiction | Décide quand deux assertions se contredisent — logique core |
| Politique de traversabilité | Décide ce qui est navigable — gouvernance core |
| Politique de résolution de conflits | Arbitrage entre assertions — décision core |
| Seuils de confiance | Modifie les gates de qualité — calibrage core |

### Conséquences concrètes sur l'implémentation

1. **Le `DomainEntityExtractor` retourne des candidats**, pas des entités validées. Les candidats passent par le même pipeline de validation que les entités core (`is_valid_entity_name()`, stoplist, canonicalization).

2. **Pas de `confidence_override`** dans les packs. Un pack ne peut pas dire "cette entité a confiance=1.0, skip les checks". Tous les candidats passent par les mêmes gates.

3. **Pas de `promotion_boost`**. Un pack ne peut pas influer sur le ranking des claims ou la promotion d'assertions. Il peut enrichir les métadonnées (tags domaine), mais le scoring reste dans le core.

4. **Les QS patterns domaine** sont des candidats soumis au même pipeline de validation que les QS core. Pas de fast-track.

5. **La canonicalisation reste globale**. Les entités créées par un pack passent par le même `EntityCanonicalizer` et le même `AcronymDedupRule` que les entités core. Pas de canonicalisation locale au pack.

6. **Traçabilité d'origine**. Chaque entité et relation créée par un pack porte un double marquage :
   - Sur la relation : `method='domain_pack:<pack_name>'` (comme pour les autres méthodes de création)
   - Sur l'entité : `source_pack='<pack_name>'` (propriété Neo4j dédiée)

   Ce double marquage permet :
   - **Rollback propre** : désactivation du pack = suppression ciblée de ses artefacts
   - **Analytics** : quelle proportion du KG vient de quel pack, contribution de chaque pack au recall
   - **Debugging** : identifier rapidement l'origine d'une entité suspecte
   - **Métriques de contribution** : mesurer l'impact de chaque pack (ex: "le pack biomedical a réduit les claims isolées de 52% à 18%")

### Coexistence multi-pack

Quand deux packs sont actifs simultanément (ex: biomedical + regulatory) :

- Chaque pack produit ses candidats indépendamment, dans l'ordre de `priority` décroissant
- Les candidats confluent dans le même pipeline core de validation
- La dédup cross-pack passe par les mécanismes existants (AcronymDedupRule, EntityCanonicalizer)
- Les entités ne sont jamais créées en doublon grâce à la normalisation + dedup au moment de l'insertion

**Invariant de résolution de conflits inter-pack :**

> **INV-CONFLICT : En cas de conflit inter-pack sur le typage ou l'expansion d'une même mention, le core ne choisit pas silencieusement. Il marque l'entité comme ambiguë et déclenche une review admin.**

Exemples concrets :

| Mention | Pack A (biomedical) | Pack B (enterprise) | Résolution core |
|---------|--------------------|--------------------|----------------|
| "HR" | Hazard Ratio | Human Resources | **Ambigu** → PROPOSED, review admin |
| "PCT" | Procalcitonin | (non reconnu) | Pas de conflit → accepté |
| "compliance" | (non reconnu) | Regulatory Compliance | Pas de conflit → accepté |

Le core est l'arbitre. Jamais un pack ne prend le dessus silencieusement sur un autre.

### Invariant de persistance

> **INV-PERSIST : Aucun artefact produit par un Domain Pack n'est persisté dans le KG sans passage par les validateurs, canonicalizers et règles de gouvernance du core.**

Le pack propose. Le core valide et persiste. Cette frontière est absolue et ne souffre aucune exception, même pour des raisons de performance ou de commodité. Un candidat qui bypass les gates core est un bug, pas une optimisation.

### Isolation des dépendances runtime

Un Domain Pack est un **contrat logique** (interfaces `DomainPack` + `DomainEntityExtractor`). Son implémentation runtime (modèle NER, dépendances pip) est une couche séparée :

```
Pack (contrat logique)
  └── Runtime Extractor (implémentation versionnée)
       └── Dépendances (scispacy, modèle NER, ...)
```

Quand plusieurs packs sont actifs, leurs dépendances doivent coexister sans conflit. Stratégies possibles :

- **Image Docker unique** : toutes les dépendances NER dans la même image (simple, adapté à 2-3 packs)
- **Worker dédié par pack** : chaque pack tourne dans son propre container/process (isolation totale, adapté à 5+ packs)
- **Lazy loading avec namespace** : les modèles NER sont chargés à la demande dans des espaces mémoire isolés (compromis)

Le choix dépendra du nombre de packs actifs en pratique. Pour la v1, l'image Docker unique suffit.

---

## 9. Points de vigilance opérationnels

1. **Pas de collision** : les entités domaine ne doivent pas créer de doublons avec les entités core. Normalisation + dedup au moment de l'insertion.
2. **Pas de dépendance** : le core ne doit jamais `import` un domain pack. Le registre utilise le pattern plugin (discovery automatique).
3. **Performance** : le re-scan ne doit porter que sur les claims sans ABOUT, pas sur tout le corpus.
4. **Idempotence** : relancer le post-processing deux fois ne doit pas créer de doublons.
5. **Rollback** : possibilité de désactiver un pack et supprimer les entités qu'il a créées (via `method='domain_pack:<pack_name>'` sur les relations).
6. **Versioning strict** : chaque pack a un numéro de version. Un upgrade de pack ne doit pas casser les artefacts créés par la version précédente.
7. **Tests obligatoires** : un pack sans tests ne peut pas être enregistré. Minimum : tests d'extraction sur un corpus échantillon + test de non-régression sur les invariants core.
8. **NER dès le jour 1** : les Domain Packs utilisent des modèles NER spécialisés pré-entraînés, pas des regex. Ce choix est détaillé en section 4. Les regex ne scalent pas sur un produit production-grade.
