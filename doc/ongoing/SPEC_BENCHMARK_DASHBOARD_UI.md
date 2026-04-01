# OSMOSIS Benchmark Dashboard — UI Specification

**Version:** 1.0
**Date:** 2026-03-31
**Cible:** `frontend/src/app/admin/benchmarks/page.tsx`
**Stack:** Next.js 14, Chakra UI, D3.js, Recharts

---

## Design rationale

### Sources de données design

Les décisions visuelles sont fondées sur trois patterns issus des bases de données de design :

1. **Data-Dense Dashboard** (styles.csv) — grille 12 colonnes, gap 8px, card padding 12-16px, table row height 36px. Priorité à la densité d'information sans sacrifier la lisibilité.
2. **Drill-Down Analytics** (styles.csv) — breadcrumb navigation, expand à 300ms, level-indent 24px. Justifie la structure "score card → liste questions → détail question".
3. **Dark Mode OLED** (styles.csv) + **Financial Dashboard** (colors.csv) — fond #0F172A (pas #000000 pur), cards sur fond distinct, texte #F8FAFC, accents vifs avec usage parcimonieux.

**Typographie retenue :** Fira Code (données numériques, scores) + Fira Sans (labels, texte) — "Dashboard Data" pairing, cohésion de famille Fira, code pour les données, sans pour les labels.

**Radar chart :** validé par le pattern "Multi-Variable Comparison" (charts.csv) — limite 5-8 axes, fill 20% opacity, toujours accompagné d'un tableau de données alternatif pour l'accessibilité.

---

## Design tokens

```css
/* Backgrounds */
--bg-base:       #0a0a1a;   /* fond page */
--bg-card:       #12122a;   /* cards, panels */
--bg-elevated:   #1a1a35;   /* hover état, popovers */
--bg-input:      #0f0f24;   /* inputs, selects */

/* Borders */
--border-subtle:  #1e1e3a;  /* séparations par défaut */
--border-active:  #2e2e5a;  /* focus, hover */
--border-strong:  #3e3e7a;  /* accents forts */

/* Accent par benchmark type */
--accent-ragas:       #5B7FFF;  /* bleu — RAGAS */
--accent-ragas-dim:   #5B7FFF22;
--accent-contra:      #7C3AED;  /* violet — Contradictions */
--accent-contra-dim:  #7C3AED22;
--accent-robust:      #f97316;  /* orange — Robustesse */
--accent-robust-dim:  #f9731622;

/* Status */
--status-ok:      #22c55e;  /* > seuil, healthy */
--status-warn:    #eab308;  /* proche seuil */
--status-error:   #ef4444;  /* sous seuil, critical */
--status-neutral: #64748b;  /* pas encore évalué, N/A */

/* Texte */
--text-primary:   #f8fafc;
--text-secondary: #94a3b8;
--text-muted:     #475569;
--text-mono:      'Fira Code', monospace;  /* scores, chiffres */
--text-sans:      'Fira Sans', sans-serif; /* labels, prose */

/* Sizing */
--card-radius:    8px;
--chip-radius:    4px;
--gap-dense:      8px;
--gap-standard:   16px;
--gap-loose:      24px;
--header-height:  56px;
--tab-height:     44px;
--row-height:     36px;     /* tables denses */
--row-height-exp: 48px;     /* lignes expandables */
```

---

## Structure des onglets

### Avant (problèmes actuels)
- Résultats / Comparaison / RAGAS / T2/T5 — nommage ambigu, Robustesse absente, pas de vue d'ensemble

### Après — 5 onglets

| # | Nom | Icône | Rôle |
|---|-----|-------|------|
| 1 | **Vue d'ensemble** | `FiActivity` | Santé globale, latest scores tous benchmarks, quick launch |
| 2 | **RAGAS** | `FiBarChart2` | Faithfulness + Context Relevance, pires échantillons, historique |
| 3 | **Contradictions** | `FiAlertTriangle` | T2/T5, catégories, historique |
| 4 | **Robustesse** | `FiShield` | 10 catégories, drill-down par question, filtres |
| 5 | **Comparaison** | `FiGitMerge` | Diff entre runs, régressions, améliorations |

**Règle de nommage :** noms fonctionnels ("ce que je cherche"), pas techniques ("T2/T5" était opaque pour quiconque rejoignant le projet).

---

## Onglet 1 — Vue d'ensemble

### Layout (1400px desktop)

```
┌─────────────────────────────────────────────────────────────────┐
│ HEADER — "Benchmark Dashboard" + System Health Pill + Timestamp  │
├───────────┬───────────┬───────────┬─────────────────────────────┤
│ RAGAS     │ Contradic.│ Robustesse│   SYSTEM HEALTH             │
│ Score Card│ Score Card│ Score Card│   Donut ou pill 3-color     │
│ (bleu)    │ (violet)  │ (orange)  │                             │
├───────────┴───────────┴───────────┴─────────────────────────────┤
│ MINI TRENDS — sparklines 3 benchmarks côte à côte               │
│ [RAGAS Faithfulness ——∿—] [Contra tension ——∿—] [Robust avg ——∿—]│
├──────────────────────────────┬──────────────────────────────────┤
│ RECENT RUNS                  │ QUICK LAUNCH                     │
│ Table 5 derniers runs        │ Profile selector                 │
│ Type | Tag | Score | Delta   │ Tag input + description          │
│                              │ [▶ RAGAS] [▶ Contra] [▶ Robust] │
└──────────────────────────────┴──────────────────────────────────┘
```

### Composant : Score Card (Overview)

```
┌─────────────────────────────────┐
│  ● RAGAS                  [i]   │  ← accent-color dot + info tooltip
│                                 │
│  [◕74] Faith  [◕58] Ctx Rel    │  ← Cercles remplissage /100
│                                 │     D3 gauge circulaire, accent color
│                                 │
│  ▲ +0.021 vs baseline  ●●●○○   │  ← delta badge + mini sparkline 5pts
│                                 │
│  Dernière run: 31 mar 14:22     │  ← text-muted 11px
└─────────────────────────────────┘
```

- Largeur : 280px min, `flex: 1` dans un HStack avec gap 16px
- Hauteur : 140px fixe
- Fond : `--bg-card`, bordure gauche 3px couleur accent du benchmark
- Delta badge : fond `--status-ok`/`--status-error` selon direction, texte mono 11px
- Info icon `[i]` : tooltip au hover, 200ms delay, fond `--bg-elevated`

### Composant : System Health Pill

Un indicateur global composite calculé comme suit :
- Vert (Healthy) : tous les scores principaux > 0.65
- Jaune (Dégradé) : au moins 1 score entre 0.50 et 0.65
- Rouge (Critique) : au moins 1 score < 0.50 ou pas de run depuis > 7 jours

```
┌────────────────────────────────┐
│  ◉ SYSTÈME HEALTHY             │  ← pill 12px fond status-ok 15%
│  3/3 benchmarks dans les cibles│
│  RAGAS · Contradictions · Rob. │  ← 3 petits dots colorés
└────────────────────────────────┘
```

Taille : 200px × 80px, coins radius 8px, dans la 4e colonne du header grid.

### Composant : Mini Sparkline

- Librairie : Recharts `<LineChart>` minimal (pas d'axes, pas de grille)
- Dimensions : 120px × 32px
- Stroke 1.5px couleur accent, pas de dots sauf dernier point (dot 4px)
- 8-10 derniers runs maximum
- Au hover de la zone : tooltip avec date + valeur

### Section : Recent Runs Table

Colonnes : Type (badge coloré) | Tag | Score principal | Delta | Date | Actions

```
Type         Tag              Score    Delta    Date          Actions
──────────────────────────────────────────────────────────────────
● RAGAS      v2.1-rechunker   0.743   ▲+0.021  31/03 14:22   [Voir]
● Contra     baseline         0.612   ▲+0.008  30/03 11:05   [Voir]
● Robust     sprint2-fix      0.534   ▼-0.012  29/03 16:44   [Voir]
```

- Row height : 36px, fond alternant `--bg-card` / `--bg-base`
- Type badge : 8px dot + texte 11px, fond accent-dim, texte accent
- Score : Fira Code 13px
- Delta : couleur status-ok/error selon direction, symbole ▲/▼/–
- Hover row : `--bg-elevated`, cursor pointer → navigue vers l'onglet concerné

### Section : Quick Launch Panel

```
┌───────────────────────────────────────────────────┐
│ Lancer un benchmark                               │
│                                                   │
│ Profil    [osmosis_v3              ▼]             │
│ Tag       [sprint2-rechunker      ]               │
│ Description [optionnel...         ]               │
│                                                   │
│ [▶ RAGAS]          [▶ Contradictions]             │
│ [▶ Robustesse]     [▶ Complet (3 benchmarks)]     │
│                                                   │
│ ████████████░░░░░ 47% — RAGAS en cours…           │  ← si running
└───────────────────────────────────────────────────┘
```

- Fond `--bg-card`, padding 20px, bordure `--border-subtle`
- Boutons de lancement : variante "outline" avec couleur accent du type correspondant
- Progress bar : fond `--border-subtle`, fill couleur accent du benchmark actif, hauteur 4px, radius 2px
- Status text sous la bar : Fira Sans 12px `--text-secondary`

---

## Onglet 2 — RAGAS

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ GAUGES ROW                                                        │
│ [Faithfulness Gauge 0.743] [Context Relevance Gauge 0.580]       │
│  + targets lines              + targets lines                    │
├──────────────────────────────────────────────────────────────────┤
│ HISTORY TABLE avec deltas                                        │
├──────────────────────────────────────────────────────────────────┤
│ WORST SAMPLES (expandable list)                                  │
├──────────────────────────────────────────────────────────────────┤
│ LAUNCH PANEL (identique Overview mais RAGAS only)                │
└──────────────────────────────────────────────────────────────────┘
```

### Composant : Score Gauge (Arc/Semicircle)

Implémentation D3.js (cohérent avec l'existant) :

- **Forme :** demi-cercle (arc 200° — de 190° à 350°), pas de full circle
- **Dimensions :** 200px × 120px SVG
- **Arc de fond :** stroke `--border-subtle`, strokeWidth 14px
- **Arc de valeur :** stroke couleur accent, strokeWidth 14px, strokeLinecap "round"
- **Ligne de cible :** tick blanc 2px à la position cible (ex: 0.70), label "cible: 0.70" 10px `--text-muted`
- **Valeur centrale :** Fira Code 32px bold, fond aucun, centré sous l'arc
- **Zones colorées** (sous l'arc principal) :
  - < 0.50 : zone rouge subtile (opacity 0.15)
  - 0.50–0.70 : zone jaune subtile
  - > 0.70 : zone verte subtile
- **Animation :** arc se dessine en 800ms `ease-out` au montage et à chaque nouveau résultat
- **Au hover :** tooltip avec historique last 3 runs

### Composant : History Table (RAGAS)

```
Run                  Tag               Faithfulness  Ctx Relevance  Questions  Durée    Détails
──────────────────────────────────────────────────────────────────────────────────────────────
31/03 14:22  [v2.1]  rechunker-sprint  0.743 ▲+.021  0.580 ▲+.012   100        4m32s    [→]
30/03 09:15  [v2.0]  baseline          0.722 ▲+.005  0.568 ▼-.003   100        4m18s    [→]
29/03 11:30  [v1.9]  pass9-test        0.717          0.571          98         4m05s    [→]
```

- Première colonne sticky gauche (position: sticky, z-index 2)
- Deltas affichés uniquement si run précédent existe
- Clic sur [→] → ouvre le détail complet du run dans un drawer latéral (ou scroll vers Worst Samples filtré)
- Header row : fond `--bg-base`, position sticky top
- Highlight current run (le plus récent) avec fond `--bg-elevated`

### Composant : Worst Samples List

```
┌─────────────────────────────────────────────────────────────────┐
│ 15 pires échantillons — Run 31/03 14:22            [Tout voir]  │
├─────────────────────────────────────────────────────────────────┤
│ ▼ [0.12]  Q: What are the role-based security controls for...   │
│           ─────────────────────────────────────────────────     │
│           Faithfulness: 0.12  Context Relevance: 0.45           │
│           Réponse: "I cannot find specific information about..." │
│           Sources citées: [SAP S4H Security Guide p.12]         │
│           Comportement attendu: Réponse factuelle sur les rôles  │
└─────────────────────────────────────────────────────────────────┤
│ ► [0.18]  Q: How does SAP RISE handle data residency across...  │
│ ► [0.23]  Q: What is the encryption standard for data at...     │
│ ► [0.31]  Q: Describe the audit trail capabilities in...        │
└─────────────────────────────────────────────────────────────────┘
```

- Liste verticale, chaque item collapsé par défaut
- Header item : score badge (fond status-color 20%, texte status-color), question tronquée à 80 chars, chevron
- Corps expandé (300ms ease) : grille 2 colonnes
  - Gauche : métriques (Faithfulness, Context Relevance)
  - Droite : réponse tronquée 200 chars + bouton "Voir tout", sources citées en chips, comportement attendu
- Score badge : `[0.12]` en Fira Code, fond `--status-error`15%, texte `--status-error`, bordure 1px
- Hover item fermé : `--bg-elevated`

---

## Onglet 3 — Contradictions

### Layout

```
┌────────────────────────────────────────────────────────────────┐
│ METRIC GRID — 2 lignes                                          │
│ T2: [tension] [both_sides] [correct_type] [both_sourced]       │
│ T5: [chain_cov] [multi_doc] [proactive] [cross_doc_chain]      │
├────────────────────────────────────────────────────────────────┤
│ CATEGORY BREAKDOWN — Barres horizontales                        │
├────────────────────────────────────────────────────────────────┤
│ HISTORY TABLE avec deltas                                       │
├────────────────────────────────────────────────────────────────┤
│ LAUNCH PANEL                                                    │
└────────────────────────────────────────────────────────────────┘
```

### Composant : Metric Grid Card (Contradictions)

8 cards disposées en `grid-template-columns: repeat(4, 1fr)` avec gap 8px.

```
┌──────────────────┐
│ Tension détectée │  ← label 11px text-secondary
│                  │
│    0.847         │  ← Fira Code 28px, couleur selon valeur
│                  │
│  T2 · CORE       │  ← badge catégorie 10px
│  ▲ +0.12 vs ref  │  ← delta
└──────────────────┘
```

- Dimensions : `flex: 1`, hauteur 96px
- Fond `--bg-card`, bordure bottom 2px couleur accent-contra (violet)
- Si score > 0.80 : texte `--status-ok`
- Si score 0.60–0.80 : texte `--status-warn`
- Si score < 0.60 : texte `--status-error`
- Hover : tooltip avec description complète de la métrique (texte from `METRIC_EXPLANATIONS`)

### Composant : Category Breakdown

```
cross_doc_chain    ████████████████░░░░  78%   ▲+5%
proactive          ██████████░░░░░░░░░░  52%   ▼-3%
multi_source       ████████████░░░░░░░░  61%   ──
single_doc         █████████████████░░░  84%   ▲+2%
```

- Barres horizontales, hauteur 8px, radius 4px
- Label : Fira Sans 12px, largeur fixe 160px (colonne gauche)
- Barre : `--border-subtle` fond, fill selon valeur (status colors)
- Pourcentage : Fira Code 12px, 40px colonne droite
- Delta badge : 48px colonne extrême droite

---

## Onglet 4 — Robustesse (NOUVEAU)

C'est l'onglet le plus riche — aucun équivalent n'existe encore dans le code actuel.

### Layout complet

```
┌──────────────────────────────────────────────────────────────────┐
│ TOP ROW                                                           │
│ [Score global: 0.61 / Robuste] [N questions: 246] [Seuil: 0.70] │
├─────────────────────┬────────────────────────────────────────────┤
│ RADAR CHART         │ CATEGORY SCORE BARS                        │
│ 10 axes             │ 10 catégories avec % + color + count        │
│ 200×200px           │                                            │
├─────────────────────┴────────────────────────────────────────────┤
│ FILTER BAR                                                        │
│ [Catégorie ▼] [Résultat: Tous/Réussi/Échoué ▼] [Score: 0-1 ⟷]   │
├──────────────────────────────────────────────────────────────────┤
│ QUESTION LIST (filtrable, expandable)                            │
│ 246 questions · 147 réussies (60%) · 99 échouées (40%)          │
│                                                                  │
│ ▼ [0.12] false_premise  Q: SAP S/4HANA supporte le...  [ÉCHOUÉ] │
│          ─────────────────────────────────────────────────────  │
│          Comportement attendu: refuser la prémisse fausse        │
│          Réponse obtenue: "Oui, SAP S/4HANA supporte..."         │
│          Score: 0.12 / Seuil: 0.50                               │
│                                                                  │
│ ► [0.88] temporal       Q: Quelle est la version actuelle...     │
│ ► [0.73] negation       Q: SAP ne supporte pas...                │
└──────────────────────────────────────────────────────────────────┘
```

### Composant : Radar Chart (10 axes — Robustesse)

Fondé sur le pattern "Multi-Variable Comparison" (charts.csv, Recharts/D3) :

- **Axes (10) :** false_premise | unanswerable | temporal | causal | hypothetical | negation | synthesis | conditional | set_list | multi_hop
- **Dimensions SVG :** 240px × 240px, centré dans sa colonne
- **Polygone de fond :** fond `--accent-robust` 8% opacity, stroke none
- **Polygone de valeur :** stroke `--accent-robust` 2px, fill `--accent-robust` 25% opacity
- **Ligne de cible (0.70) :** polygone de référence, stroke blanc 1px dashed, opacity 40%
- **Labels axes :** Fira Sans 10px, `--text-secondary`, positionnés à r+12px de l'axe
- **Dots sur le polygone :** 5px radius, fill `--accent-robust`, stroke `--bg-card` 2px
- **Hover dot :** tooltip 160px avec catégorie, score, N questions, N passes
- **Tableau alternatif d3 accessible :** affiché sous le radar, togglé par `[Voir tableau]` button, pour l'accessibilité (WCAG)
- **Animation montage :** polygone se dessine 600ms ease-out depuis le centre

**Limites des labels (shortcodes) :**
```
false_premise → "Prémisse"
unanswerable  → "Réfus"
temporal      → "Temporel"
causal        → "Causal"
hypothetical  → "Hypothèse"
negation      → "Négation"
synthesis     → "Synthèse"
conditional   → "Conditionnel"
set_list      → "Listes"
multi_hop     → "Multi-hop"
```

### Composant : Category Score Bars (Robustesse)

```
Prémisse fausse  ████░░░░░░░░░░  0.28  24/48 (50%)  ● CRITIQUE
Unanswerable     ██████████░░░░  0.71  36/45 (80%)  ● OK
Temporal         ████████░░░░░░  0.54  27/40 (67%)  ● DÉGRADÉ
Causal           ███████░░░░░░░  0.48  22/38 (58%)  ● DÉGRADÉ
Hypothetical     ██████████████  0.82  28/28 (100%) ● OK
Négation         █████░░░░░░░░░  0.36  12/25 (48%)  ● CRITIQUE
Synthèse         ████████░░░░░░  0.55  18/30 (60%)  ● DÉGRADÉ
Conditionnel     ████████████░░  0.74  22/25 (88%)  ● OK
Listes           ████████░░░░░░  0.58  14/20 (70%)  ● DÉGRADÉ
Multi-hop        ███████░░░░░░░  0.47  18/28 (64%)  ● CRITIQUE
```

- Barre : hauteur 6px, radius 3px, max-width 140px
- Couleur barre : vert si > 0.70, jaune si 0.50–0.70, rouge si < 0.50
- Fond barre : `--border-subtle`
- Clic sur une ligne → filtre automatiquement la Question List vers cette catégorie

### Composant : Filter Bar (Robustesse)

```
┌─────────────────────────────────────────────────────────────────┐
│ [Catégorie: Toutes ▼] [Résultat: Tous ▼] [Score: 0.00 ──── 1.00]│
│                          [← Réinitialiser les filtres]          │
└─────────────────────────────────────────────────────────────────┘
```

- Fond `--bg-card`, padding 12px 16px, bordure bas `--border-subtle`
- Select catégorie : multi-select avec checkboxes (ex: "false_premise + temporal")
- Select résultat : radio Tous / Réussi / Échoué
- Slider score : double-thumb range slider, track `--border-active`, thumbs `--accent-robust`
- État "filtres actifs" : badge avec le nombre de filtres actifs `[2 filtres actifs × reset]`
- Résultats filtrés : counter mis à jour `"47 questions affichées / 246"`

### Composant : Question Detail Row (Robustesse — et réutilisé partout)

État fermé (hauteur 36px) :
```
[SCORE] CATÉGORIE   Q: texte tronqué…                    [STATUS]  ▼
```

État ouvert (hauteur variable, animation 300ms ease) :
```
┌─────────────────────────────────────────────────────────────────┐
│ QUESTION COMPLÈTE                                               │
│ "SAP S/4HANA Cloud Private Edition supporte le multi-tenancy..."│
├────────────────────────┬────────────────────────────────────────┤
│ COMPORTEMENT ATTENDU   │ RÉPONSE OBTENUE                        │
│ Refuser la prémisse    │ "Oui, SAP RISE supporte le mode..."    │
│ fausse et expliquer    │ [tronqué — bouton "Voir tout"]          │
│ pourquoi               │                                        │
├────────────────────────┴────────────────────────────────────────┤
│ Sources citées: [RISE Security Guide ×] [S4H Admin Guide ×]    │
│ Score détaillé: factual 0.08 · relevant 0.45 · total: 0.12     │
│ Juge principal: Qwen2.5-14B   Juge secondaire: Claude (absent) │
└─────────────────────────────────────────────────────────────────┘
```

Spécifications du corps expandé :
- Grille 2 colonnes égales, gap 16px, padding 16px
- "Comportement attendu" : fond `--accent-contra-dim`, bordure gauche 2px `--accent-contra`, texte 13px
- "Réponse obtenue" : fond `--status-error`15% si score < 0.50, `--status-warn`15% si 0.50–0.70, `--status-ok`15% si > 0.70
- Sources : chips avec `×` pour info (hover = path du document), fond `--bg-elevated`
- Score détaillé : Fira Code 12px, séparés par `·`, fond `--bg-base`
- Juge info : Fira Sans 11px `--text-muted`, en bas

**Champ SCORE badge :**
- `[0.12]` : fond `--status-error`20%, texte `--status-error`, border 1px, radius 4px, Fira Code 12px bold
- `[0.65]` : fond `--status-warn`20%, texte `--status-warn`
- `[0.88]` : fond `--status-ok`20%, texte `--status-ok`

**Champ STATUS pill :**
- `[ÉCHOUÉ]` : fond `--status-error`15%, texte `--status-error`, uppercase 10px
- `[RÉUSSI]` : fond `--status-ok`15%, texte `--status-ok`

---

## Onglet 5 — Comparaison

### Layout

```
┌────────────────────────────────────────────────────────────────┐
│ RUN SELECTOR                                                    │
│ Run A: [31/03 14:22 — v2.1 rechunker ▼]                        │
│ Run B: [30/03 09:15 — v2.0 baseline  ▼]                        │
│ Type:  [RAGAS ▼]                              [Comparer →]      │
├─────────────────────────────┬──────────────────────────────────┤
│ METRIC DELTAS TABLE         │ DELTA BARS (visualisation)       │
│ Métrique  Run A  Run B  Δ   │ Faithfulness  ▶████  +0.021      │
│ Faith.    0.743  0.722  ▲+.021│ Ctx Rel.     ◀██   -0.003      │
│ CtxRel.   0.580  0.583  ▼-.003│                               │
├─────────────────────────────┴──────────────────────────────────┤
│ TOP RÉGRESSIONS                 TOP AMÉLIORATIONS              │
│ Q: Les protocoles de...  ▼-.18  Q: Quelle est la politique...▲+.24│
│ Q: SAP RISE supporte...  ▼-.14  Q: Comment configurer...   ▲+.19  │
└────────────────────────────────────────────────────────────────┘
```

### Composant : Delta Badge

- Couleur fond + texte selon `delta > 0 → status-ok`, `< 0 → status-error`, `= 0 → neutral`
- Symbole ▲ / ▼ / – préfixé
- Format : `▲ +0.021` — Fira Code 12px

### Composant : Delta Bar (Visualisation)

```
Faithfulness   ████████████│░░░░   +0.021
               ─────────── center baseline
Ctx Relevance  ░░░░░│████████████  -0.003
```

- Barre centrée (zéro au milieu)
- Fill vert vers la droite (amélioration), rouge vers la gauche (régression)
- Hauteur 8px, radius 4px
- Label à gauche 120px, valeur à droite 48px (Fira Code)

---

## Comportements interactifs globaux

### Navigation drill-down

Fil de navigation (breadcrumb) quand on est dans un contexte filtré :

```
Robustesse > false_premise > 24 questions > [Question #12]
            ─── clic remonte au niveau supérieur ───
```

- Fond `--bg-card`, hauteur 32px, padding 0 16px
- Séparateur ` › ` texte `--text-muted`
- Chaque niveau cliquable (underline au hover)
- Le niveau courant : texte `--text-primary` (non cliquable)

### Expand/collapse animation

Toutes les sections expandables (Worst Samples, Question rows) :

```css
/* CSS token */
--expand-duration: 300ms;
--expand-timing: ease-in-out;

/* Pattern : height: 0 → height: auto via max-height trick */
.expandable-body {
  overflow: hidden;
  max-height: 0;
  transition: max-height var(--expand-duration) var(--expand-timing);
}
.expandable-body.open {
  max-height: 800px; /* suffisamment grand */
}
```

### Launch panel — Progress states

```
État idle:
[▶ Lancer RAGAS] — fond --accent-ragas 15%, texte --accent-ragas, border 1px

État running:
[■ Arrêter]      — fond --status-error 15%, texte --status-error
████████████░░░░░░ 64/100 questions · 2m18s écoulé
Phase: api_call · Question en cours: "How does SAP RISE handle..."
Spinner (Chakra Spinner, size sm, couleur accent)

État completed:
[✓ Terminé — Voir résultats →]  — fond --status-ok 15%, couleur ok
Score: faithfulness 0.743 (▲+0.021 vs précédent)

État failed:
[⚠ Erreur — Relancer]  — fond --status-error 15%
Message: "Timeout sur question 47: API vLLM non disponible"
```

### Tooltips et info icons

Chaque métrique avec `[i]` icon :
- Tooltip largeur 280px, fond `--bg-elevated`, bordure `--border-active`, shadow `0 8px 24px #00000060`
- Contenu : nom complet, description, sens (↑ meilleur / ↓ meilleur), frameworks de référence (RAGAS, AI Act, NIST)
- Delay apparition : 200ms hover
- Delay disparition : 100ms (pour permettre hover du tooltip lui-même)

---

## Tab bar — Spécification du composant

```
┌────────────────────────────────────────────────────────────────┐
│ [◎ Vue d'ensemble] [≡ RAGAS] [⚠ Contradictions] [⛊ Robustesse] [⊞ Comparaison] │
└────────────────────────────────────────────────────────────────┘
```

- Fond `--bg-card`, hauteur 44px, bordure bas `--border-subtle`
- Tab inactive : texte `--text-secondary` 13px Fira Sans
- Tab active : texte `--text-primary` 13px, indicateur bas 2px solide couleur accent du tab
- Icône : 14px, `--text-muted` inactive, accent active
- Si benchmark en cours dans un onglet : indicateur spinner 6px pulsant (keyframe opacity 1→0.3) adjacent au label
- Badge count (si des alertes) : `●3` en `--status-error` 10px sur l'onglet concerné

**Couleurs d'accent par onglet :**
- Vue d'ensemble : `--accent-ragas` (#5B7FFF) — bleu neutre
- RAGAS : `--accent-ragas` (#5B7FFF)
- Contradictions : `--accent-contra` (#7C3AED)
- Robustesse : `--accent-robust` (#f97316)
- Comparaison : #64748b (neutre)

---

## Responsive breakpoints

| Breakpoint | Comportement |
|------------|-------------|
| < 768px (mobile) | Tabs en carousel horizontal scrollable. Score cards empilés. Radar chart remplacé par tableau. |
| 768–1024px (tablet) | Score cards 2 colonnes. History table avec horizontal scroll. Launch panel sous les graphs. |
| 1024–1280px | Layout principal, certaines colonnes compressées. |
| > 1280px | Layout complet, toutes colonnes visibles. |

---

## Accessibilité

1. **Contraste couleurs :** toutes les combinaisons texte/fond > 4.5:1 (WCAG AA). Texte primaire (#f8fafc) sur fond card (#12122a) = ratio 13.6:1.
2. **Radar chart :** table de données alternative togglable (`[Voir tableau]`) — cf. recommandation charts.csv.
3. **Scores numériques :** toujours accompagnés d'un label textuel (pas seulement couleur).
4. **Touch targets :** boutons min 40×40px, lignes de tableau min 36px hauteur.
5. **Focus visible :** outline 2px `--accent-ragas` sur tous les éléments interactifs, offset 2px.
6. **ARIA :** tabpanels avec `role="tabpanel"`, expandables avec `aria-expanded`, progress bars avec `aria-valuenow`.

---

## Implémentation — ordre de priorité

### Priorité 1 (fondations)
1. Design tokens CSS variables dans `:root`
2. Tab bar avec les 5 onglets + couleurs accent
3. Score Card Overview (réutilisé partout)
4. Launch Panel avec états idle/running/completed/failed

### Priorité 2 (onglets principaux)
5. Onglet RAGAS complet (gauges D3 + history table + worst samples)
6. Onglet Contradictions (metric grid + category bars + history)

### Priorité 3 (nouveaux composants)
7. Onglet Robustesse — radar + bars + filter bar
8. Question Detail Row expandable (composant générique)
9. Filter bar avec range slider

### Priorité 4 (polish et transversal)
10. Onglet Comparaison — delta bars
11. Breadcrumb drill-down navigation
12. Tooltips avec descriptions métriques (METRIC_EXPLANATIONS existant)
13. Animations (expand 300ms, radar 600ms, gauge arc 800ms)

---

## Notes pour le développeur frontend

### Réutilisation du code existant

- `METRIC_EXPLANATIONS` dans `page.tsx` (ligne 143+) — alimenter directement les tooltips
- Types `BenchmarkRun`, `RagasReport`, `T2T5Report` déjà définis — étendre pour Robustesse
- D3.js déjà importé — utiliser pour les gauges semi-circulaires ET le radar
- Chakra UI déjà en place — `Tabs`, `Tooltip`, `Progress`, `Select` natifs

### Nouveau type à créer : RobustesseReport

```typescript
interface RobustnessCategory {
  name: string
  score: number
  total: number
  passed: number
  questions: RobustnessQuestion[]
}

interface RobustnessQuestion {
  id: string
  category: string
  question: string
  expected_behavior: string
  actual_answer: string
  score: number
  passed: boolean
  sources_cited: string[]
  judge: string
}

interface RobustnessReport {
  filename: string
  timestamp: string
  tag?: string
  description?: string
  profile: string
  total_evaluated: number
  categories: Record<string, RobustnessCategory>
  global_score: number
}
```

### API endpoint à créer côté backend

```
GET  /api/benchmarks/robustesse/reports          → liste des reports
GET  /api/benchmarks/robustesse/reports/{id}     → détail complet
POST /api/benchmarks/robustesse/run              → lancer
GET  /api/benchmarks/robustesse/progress         → WebSocket ou polling
```

### Police Google Fonts

Ajouter dans `layout.tsx` :

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
<link
  href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap"
  rel="stylesheet"
/>
```

Fira Code uniquement pour les valeurs numériques (scores, chiffres, Fira Mono) — Fira Sans pour le reste. Ne pas surcharger le layout de polices inutilement.
