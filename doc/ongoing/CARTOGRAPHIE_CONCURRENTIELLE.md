# Cartographie concurrentielle — OSMOSIS

> **Document vivant** (doc/ongoing). v1 du 2026-05-31, à enrichir/vérifier.
> **But** : sortir du « développement en chambre » — confronter les forces d'OSMOSIS à ce qui
> existe déjà sur le marché, par catégorie ACHETEUR (pas par catégorie techno).
> **Méthode** : recherche web (sources en bas). ⚠️ Les capacités sont déclarées par les éditeurs
> (marketing) — à **vérifier en essai réel** avant toute décision irréversible.

---

## 0. Le constat qui change tout

**Ton hypothèse de départ** : « les verticaux légaux ont des KG sur le légal *institutionnel*
(lois/règlements en vigueur), pas corrélé à MON métier (mes contrats, mes normes). »

**Réalité (vérifiée) : l'hypothèse est FAUSSE pour les contrats.** Plusieurs acteurs très
financés raisonnent déjà profondément sur le **corpus propre du client** — y compris amendements
(= temporel), obligations, contradictions cross-contrats. Et tes capacités différenciantes
(temporel/supersession, contradiction, traçabilité) sont soit **déjà livrées** par des verticaux,
soit en **commoditisation** (GraphRAG + temporel devient le standard 2026).

**Conséquence** : aucune entrée frontale solo possible. La question n'est plus « suis-je différent
techniquement ? » (de moins en moins) mais « existe-t-il un **segment précis** dont la douleur est
à l'**intersection** que personne ne sert, ET avec un acheteur/budget réel ? ».

---

## 1. Carte par catégorie

Légende capacités : ✅ oui · 🟡 partiel/émergent · ❓ non confirmé · ➖ non/hors-scope.
Colonnes clés OSMOSIS : **Own** = raisonne sur le corpus PROPRE du client · **Temp** = temporel/
supersession · **Contra** = contradiction cross-document · **Absten** = abstention honnête /
faux-présupposé · **X-dom** = raisonne à travers des TYPES de docs hétérogènes (contrat+norme+régl.).

### Horizontal — « cerveau d'entreprise » (enterprise AI search)
| Acteur | Échelle | Own | Temp | Contra | Absten | X-dom | Note |
|--------|---------|-----|------|--------|--------|-------|------|
| **Glean** | 7,2 Md$ | ✅ | 🟡 | 🟡 | ❓ | 🟡 | Graphe ORG/permissions ; retrieval permissionné + citations + grounding. Pas un graphe de claims du contenu. Devient plateforme (unified index, MCP). |
| **Microsoft Copilot** | — | ✅ | ❓ | ❓ | ➖ | 🟡 | Distribution M365 imbattable. Optimisé utilité, pas prudence. |
| **Google Gemini Enterprise** | — | ✅ | ❓ | ❓ | ➖ | 🟡 | Idem côté Workspace. |
| Glean/Copilot = **terrain à NE PAS attaquer frontalement** (largeur + distribution). |

### Vertical LÉGAL / contrats — **TRÈS saturé**
| Acteur | Échelle | Own | Temp | Contra | Absten | X-dom | Note |
|--------|---------|-----|------|--------|--------|-------|------|
| **Harvey** | ~11 Md$ (mai 2026) | ✅ | 🟡 | ✅ | 🟡 | 🟡 | Institutionnel (case law) **ET** docs propres de la firme. M&A diligence, « discrepancies between hundreds of contracts », citations sourcées. |
| **Luminance** | revenus ×2 en 2025 | ✅ | ✅ | ✅ | ❓ | 🟡 | « contrats = source vivante du fonctionnement de la boîte » ; query cross-contrats + **amendements** + obligations ; « institutional memory » (janv. 2026). **Recouvre une partie directe de ton pitch.** |
| **Ironclad** | — | ✅ | 🟡 | 🟡 | ❓ | ➖ | Contract intelligence : obligations, renouvellements manqués sur TES contrats. |
| **Robin AI** | — | ✅ | 🟡 | ✅ | ❓ | ➖ | DB de contrats → structuré/requêtable, analyse portefeuille. **Fusionne en partie dans Microsoft Legal Agent** (consolidation). |
| **Legora** | ~150 M$ levés | ✅ | ❓ | 🟡 | ❓ | ➖ | Revue de portefeuille haut volume, intégré Word/SharePoint. |

### Vertical FINANCE / diligence — le modèle « raisonnement » qui marche
| Acteur | Échelle | Own | Temp | Contra | Absten | X-dom | Note |
|--------|---------|-----|------|--------|--------|-------|------|
| **Hebbia** | 33 % des top asset managers ; 1 Md pages | ✅ | ❓ | ✅ | 🟡 | ✅ | « System of record for enterprise reasoning », agent swarm, raisonnement multi-étapes cross-docs hétérogènes (contrats+filings+modèles+transcripts), détecte « loopholes » dans les covenants. **C'est la preuve que ton PATTERN (raisonnement cross-doc profond) est un business défendable — mais verticalisé FINANCE.** |

### Vertical PHARMA / sciences de la vie — entrenché, AI Act comme moteur
| Acteur | Échelle | Own | Temp | Contra | Absten | X-dom | Note |
|--------|---------|-----|------|--------|--------|-------|------|
| **Veeva** | leader cloud life-sciences | ✅ | 🟡 | ❓ | ➖ | 🟡 | AI agents (labeling, regulatory). Relation client profonde. |
| **MasterControl** | QMS établi | ✅ | ✅ | 🟡 | ❓ | 🟡 | ADAPT (ISO 42001), Regulatory Chat, **SOP compliance analyzer (janv. 2026)** : suit MAJ FDA/EMA/ICH → scanne les SOP affectées → alerte révision. **C'est ta proposition temporelle, déjà livrée.** |

### Vertical INDUSTRIEL / qualité-fabrication — **moins saturé par le raisonnement profond**
| Acteur | Échelle | Own | Temp | Contra | Absten | X-dom | Note |
|--------|---------|-----|------|--------|--------|-------|------|
| ComplianceQuest, Qualityze, isoTracker, SciNote… | QMS + AI | 🟡 | ❓ | ➖ | ➖ | ➖ | Surtout détection défauts / contrôle qualité / génération de docs. **Peu de raisonnement cross-document profond.** Mais les QMS possèdent la relation client. EU AI Act (août 2026) classe l'AI de cert. qualité produit en « haut risque » → tailwind traçabilité. |

### Infrastructure / brique technique — **commoditisation**
| Brique | État | Note |
|--------|------|------|
| **Microsoft GraphRAG** (OSS, 2024) | standard | « le standard 2026 du RAG fiable » sur corpus privé. |
| **Temporal Graph RAG** | émergent (2026) | suit l'évolution au lieu d'écraser = ta proposition temporelle, en train de devenir un pattern public. |
| **Neo4j temporal + GraphRAG + MCP**, KnowCosmos… | dispo | les briques (KG de claims, temporel) ne sont PLUS une IP rare. |

---

## 2. Où est (peut-être) l'air gap d'OSMOSIS

Ce que je n'ai **PAS** trouvé productisé commercialement, malgré recherche : **un seul moteur qui
raisonne à travers le corpus HÉTÉROGÈNE et à fort enjeu d'une entreprise** — contrats **+** normes
de fabrication **+** spécifications techniques **+** réglementaire **+** SOP **ensemble** — avec
claim-level traçable + contradiction cross-document + supersession temporelle + **abstention
disciplinée / faux-présupposé**. Les acteurs sont chacun **siloés** : Hebbia=finance,
Luminance=contrats, MasterControl/Veeva=pharma SOP, Harvey=légal. Le sujet existe en **recherche**
(ClaimVer, LegalWiz, HalluGraph, RegGuard) mais pas en produit transverse.

**MAIS — le doute honnête** : si personne ne le fait, deux explications possibles, et il faut
trancher laquelle est vraie :
- (a) **C'est dur** (research-stage) → opportunité réelle si tu sais le faire.
- (b) **Le marché n'achète pas transverse** : chaque département achète SON outil vertical (le
  juridique achète Harvey, la qualité achète MasterControl). Un outil cross-domaine n'aurait alors
  **ni acheteur ni budget clair** — c'est le « piège horizontal » déguisé. *Le fait que TOUS soient
  allés vertical est un signal qu'il faut prendre au sérieux, pas balayer.*

C'est LA question à instruire en découverte client (Armand & co), pas à trancher en chambre.

---

## 3. Conclusions stratégiques (sans complaisance)

1. **Entrée solo frontale = exclue** contre Harvey (11 Md$), Hebbia, Veeva, Luminance. Tu l'as dit ;
   c'est confirmé.
2. **Tes capacités ne sont pas uniques** : temporel (MasterControl, Luminance, Temporal-GraphRAG),
   cross-doc/contradiction (Hebbia, Harvey), traçabilité/citations (Glean, Harvey). Ton seul delta
   *possiblement* peu servi = **abstention disciplinée / faux-présupposé + transverse cross-domaine**.
   À prouver, et à vérifier que les autres ne le font pas (essais réels, pas marketing).
3. **Légal est le pire beachhead** (le plus saturé). ⚠️ Or ton accès réseau (Armand) est légal.
   Résoudre la tension : Armand = excellent pour **apprendre la douleur**, mais le wedge défendable
   est peut-être **industriel/réglementé cross-domaine** (moins saturé par le raisonnement profond).
   L'accès réseau prime souvent sur l'attractivité marché pour un 1er design partner — mais garde
   les yeux ouverts.
4. **Deux postures viables, pas une seule frontale** :
   - **Vertical de niche cross-domaine** (ex. dispositif médical / aéro / EPC industriel) où une
     question croise contrat + norme + réglementation, avec co-innovation/design partner.
   - **Couche complémentaire** (raisonnement + vérification + abstention traçable) *au-dessus* d'un
     index/QMS existant (Glean unified index, MCP…), pas un remplacement.
5. **Méthode à corriger durablement** : veille par catégorie ACHETEUR (Harvey, Hebbia, MasterControl,
   Veeva, Luminance, Ironclad, Robin AI, Legora, Glean…), pas par mot-clé techno (« KG-RAG »).

## 4. Veille v2 (31/05) — abstention des incumbents + vertical industriel

### Axe A — L'abstention disciplinée / faux-présupposé EST l'air gap le plus net

Preuves tierces (pas marketing) :
- **Stanford RegLab (Magesh et al., publié J. Empirical Legal Studies 2025)** : les outils de
  legal RAG DÉDIÉS **hallucinent encore ~1 requête sur 6**. Lexis+ AI 65 % exact, Westlaw 42 %.
  → l'hallucination n'est PAS résolue, même par des verticaux à la pointe avec citations.
- **Harvey** : décompose les réponses en **claims** + cross-référence + flag les incohérences
  (très proche de l'approche OSMOSIS !), revendique 0,2 % d'erreur. **MAIS** « l'accent est sur la
  vérification/grounding, PAS sur un mécanisme explicite d'abstention ». Harvey **converge** vers le
  claim-level → l'écart se réduit, mais l'abstention disciplinée n'est pas son ADN.
- **Hebbia** : citation-first, grounding ; **abstention non documentée** non plus.
- **Consensus SOTA (arxiv 2025-2026)** : la bonne approche du faux-présupposé est **PROACTIVE**
  (transformer la requête en forme logique → vérifier entités/relations contre un KG → flaguer
  AVANT de répondre) — *c'est exactement le PremiseVerifier d'OSMOSIS*. Les méthodes des incumbents
  sont **post-hoc** (citer après avoir répondu). Le tradeoff connu = sur-abstention si seuil trop
  haut (OSMOSIS l'a déjà rencontré → SufficiencyChecker abandonné). Et : « si la requête contient
  un faux présupposé, le retrieval va vers le contenu qui MATCHE la prémisse au lieu de la critiquer
  (confirmation bias) » → exactement pourquoi OSMOSIS fait un **retrieval dédié à la prémisse**.

**Conclusion Axe A** : l'**abstention proactive + faux-présupposé KG-grounded** est (1) reconnue
SOTA comme la bonne approche, (2) **NON productisée** par les leaders (post-hoc citation seulement),
(3) sur un problème **mesurablement non résolu** (Stanford 1/6). **C'est le delta le plus défendable
d'OSMOSIS.** ⚠️ Mais c'est un écart de FEATURE (head-start), pas une forteresse : Harvey décompose
déjà en claims. Défendabilité = abstention **+** temporel **+** vertical cross-domaine combinés.

### Axe B — Vertical industriel/ingénierie réglementée = le moins saturé

- **Dispositif médical** (IEC 62304 Ed.2 sept. 2026, ISO 13485/14971) : besoin STRUCTUREL de
  **matrices de traçabilité** liant exigences → risque → vérification à travers plusieurs normes.
  AI surtout outillage compliance/lifecycle, **pas de raisonnement cross-document profond**.
- **Aéro/défense** (DO-178C, AS9100, ARP) : « les sorties IA doivent rester gouvernées, traçables,
  explicables ; les autorités exigent des **preuves DÉTERMINISTES** — l'IA assiste, ne remplace
  pas ». Incumbents = gestion d'exigences/ALM (Stell, Visure, PTC, Accuris), pas du Q&A claim-level.
  Le besoin de **preuve déterministe** favorise un système traçable qui s'abstient plutôt qu'un
  système qui devine.
- **EPC construction/énergie** : « l'IA cross-référence les pièces vs specs projet + codes du
  bâtiment, détecte les non-conformités tôt ». Émergent (Buildcheck, CaseMark) + cadre de recherche
  Springer (= pas encore productisé). Contrats EPC = « parmi les docs les plus complexes, 20-30 h
  d'avocat ». **Corpus hétérogène (ingénierie + contrat + réglementaire + codes) à fort enjeu,
  PAS verrouillé par un incumbent de raisonnement profond.** → candidat wedge sérieux.
- **EU AI Act (2 août 2026)** : récurrent sur TOUS ces verticaux → traçabilité/transparence/
  supervision humaine **obligatoires** sur l'IA « haut risque ». Tailwind structurel et **timé**
  pour un système traçable, abstenant, auditable.

**Conclusion Axe B** : légal/finance/pharma = saturés. **Industriel/ingénierie réglementée
(EPC, aéro-exigences, dispositif médical) = corpus hétérogènes à fort enjeu, traçabilité
structurelle, AI Act comme moteur, et AUCUN incumbent de raisonnement cross-document profond
ne l'a verrouillé.** C'est le terrain le plus cohérent avec les forces d'OSMOSIS.

### Synthèse v2 (la plus actionnable)
Le couple gagnant possible = **abstention proactive/faux-présupposé + temporel + traçabilité**,
appliqué à un **vertical d'ingénierie réglementée à corpus hétérogène** (EPC en tête), porté par
le tailwind **AI Act**, en **co-innovation** (design partner) ou en **couche de vérification**
au-dessus d'un ALM/QMS — jamais en frontal. Armand (légal) = pour APPRENDRE la douleur d'abstention
(le marché légal est pris par Harvey, mais l'abstention y reste un trou). Reste à instruire en
découverte : le risque « cross-domaine = pas d'acheteur/budget » (chaque département achète son
vertical).

### À faire (v3, terrain)
- Essais réels (pas marketing) : Harvey/Hebbia/Luminance **s'abstiennent-ils** vraiment ? Tester
  des questions à faux présupposé + hors-corpus.
- Sizing + cycle d'achat EPC / dispositif médical ; identifier un design partner accessible.
- Vérifier les ALM/requirements (Visure, Jama, PTC) : ajoutent-ils du Q&A claim-level abstenant ?
