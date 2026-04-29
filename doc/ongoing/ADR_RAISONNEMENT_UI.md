# ADR — UI du raisonnement : compléter ce qui existe pour atteindre M6

**Date** : 2026-04-26
**Statut** : Proposition (à valider)
**Auteur** : Fred + Claude Code
**Portée** : Améliorations ciblées de la couche UI pour exposer le raisonnement OSMOSIS, alignée sur la cible M6 d'`ARMAND_TEST_READINESS_TARGET`

---

## 1. Le problème

Le pitch préparé pour Armand promet qu'OSMOSIS « explique pourquoi cette réponse plutôt qu'une autre — quels textes il a retenus, lesquels il a écartés, où il a identifié une tension ». Le M6 de la carte cible exige que cette explication soit lisible **par un utilisateur non-développeur**, sans manipulation technique, sur 5 requêtes représentatives.

Si Fred doit, pendant la phase test, expliquer verbalement à Armand comment OSMOSIS a construit chaque réponse, on est en démo-dépendance. Or le test Armand sera vraisemblablement en autonomie après le déjeuner — Fred ne sera pas à côté pour commenter.

### Ce qui existe déjà — bonne nouvelle

L'audit code (`ARMAND_TEST_READINESS_AUDIT §M6`) avait laissé M6 en 🟡 par prudence. L'exploration a révélé que **l'infrastructure est en place** :

**Backend** :

- `src/knowbase/api/services/reasoning_trace_service.py` — `ReasoningTraceService` qui produit une `ReasoningTrace` structurée
- Modèle de données complet : `ReasoningStep` avec numéro, statement narratif, supports KG, indicateur de conflit, source_refs
- `ReasoningSupport` capture les relations KG (relation_type, source/target concept, edge_confidence, source_refs)
- `coherence_status` : `coherent` / `partial_conflict` / `conflict`
- Approche hybride : KG fournit les supports auditable, LLM rédige les statements narratifs (génération dans la langue de la question, pas de templates hardcodés)

**Frontend** :

- `frontend/src/app/chat/page.tsx` — page chat
- `frontend/src/components/chat/ReasoningTracePanel.tsx` — composant dédié à l'affichage de la trace

**KG infrastructure** :

- Relations sur `CONTRADICTS` enrichies avec `tension_nature`, `tension_level`, `explanation`, `scope_a`, `scope_b`, `show_in_article`, `show_in_chat`, `show_in_homepage` (cf. `contradiction_classifier.py`)
- Flags d'affichage déjà calculés (`derive_full_diffusion_flags`)

### Ce qui manque

L'infrastructure est là. L'enjeu est triple : **couverture des modes**, **qualité de présentation**, **affichage des silences**.

**Manque 1 — Couverture par mode de réponse**

Les Response Modes V3 (`DIRECT`, `AUGMENTED`, `TENSION`, `STRUCTURED_FACT`) sont activés en production. Mais (cf. `ADR_PERSPECTIVE_LAYER_ARCHITECTURE` §1) :

- En mode `DIRECT` et `AUGMENTED` (les deux modes les plus fréquents), `graph_context_text` est **vidé**
- En mode `TENSION`, seules 2-3 lignes de contraintes procédurales sont injectées (~50-80 tokens)

Le `ReasoningTraceService` est probablement appelé sur toutes les modes, mais la **richesse** de la trace dépend de la richesse des supports KG injectés. En mode DIRECT/AUGMENTED, le LLM produit une réponse fondée sur les chunks Qdrant sans injection KG narrative — la trace risque d'être pauvre voire vide. À vérifier en pratique sur le corpus aerospace_compliance après ingestion.

**Manque 2 — Affichage des silences et écartements**

Le `ReasoningTraceService` montre les **étapes** du raisonnement avec leurs **supports**. Il ne semble pas montrer explicitement :

- Les **textes écartés** : quels passages OSMOSIS a vu mais n'a pas retenus, et pourquoi
- Les **zones de silence** : pour cette question, OSMOSIS n'a aucune information dans la couverture X (par exemple : « pas de claim sur l'aspect environnemental dans ce corpus »)

Or pour Armand, les *écartements* et les *silences* sont aussi importants que les retenus. Un juriste senior **vérifie ce qui n'a pas été dit** autant que ce qui a été dit.

**Manque 3 — Lisibilité par non-développeur**

Le format `to_dict()` du `ReasoningTrace` et de ses sous-objets est conçu pour la sérialisation API. Le `ReasoningTracePanel.tsx` doit transformer ces structures en présentation lisible. Sans le voir en action, on ne peut pas savoir si l'UI :

- Distingue visuellement les supports KG forts des supports faibles (`edge_confidence`)
- Met en évidence les `is_conflict: true` (tensions détectées)
- Montre les sources cliquables (source_refs) pour vérification
- Gère gracieusement les cas où `coherence_status` est `partial_conflict`

Cet ADR ne peut pas conclure définitivement sans test d'usage. Mais il peut **cadrer les améliorations probables** que le bench M6 (cf. ADR n°2) révélera.

---

## 2. Approches écartées et pourquoi

### 2a. Tout reconstruire avec un nouveau service de "trace UI"

**Écarté parce que** :

- L'infrastructure existante est solide. Le `ReasoningTraceService` capture l'essentiel (étapes, supports KG, coherence). Reconstruire serait une perte de temps.
- Le frontend a déjà le composant `ReasoningTracePanel.tsx`. Le réécrire détruirait du travail existant.

### 2b. Améliorer le LLM-statement pour qu'il soit "auto-explicatif"

Faire en sorte que la réponse du LLM dans `synthesis.py` inclue elle-même des phrases du type « j'ai retenu X, j'ai écarté Y, je suis silencieux sur Z ». Pas de panneau séparé.

**Écarté parce que** :

- Surcharge la réponse principale avec des méta-informations qui dégradent la lisibilité de la réponse elle-même
- Mélange contenu et méta-contenu — un juriste veut la réponse, **et séparément** la trace
- Ne tire pas parti du KG : la trace KG-supportée est plus auditable qu'un récit LLM

### 2c. Reporter M6 et accepter une démo verbale

**Écarté parce que** :

- Le test Armand sera en autonomie. Pas de Fred à côté.
- Une UI insuffisante en M6 fait basculer le RDV en niveau 1 ("sympa, bonne chance") même si M1-M5 sont impeccables — la démonstrabilité est un facteur de décision distinct

---

## 3. Architecture cible : trois améliorations sur l'existant

### 3a. Amélioration A — Trace minimale en mode DIRECT/AUGMENTED

Pour ne pas avoir un `ReasoningTracePanel` vide en mode DIRECT/AUGMENTED (les plus fréquents), le panneau doit pouvoir afficher au minimum :

- **Liste des chunks retenus** : quels passages Qdrant ont alimenté la réponse (déjà disponible via les sources_refs)
- **Liste des chunks écartés** : top-k retrieval qui n'a pas été retenu après reranking, avec score si possible
- **Couverture par document** : "X chunks de Document A, Y chunks de Document B" — donne une vue d'ensemble
- **Statut KG** : "Aucun signal KG détecté pour cette question (mode DIRECT)" ou "Signal KG: tension détectée, aucun support narratif injecté (mode AUGMENTED)"

Ce contenu existe déjà dans le pipeline (`search.py` produit chunks retenus + écartés en interne). Il faut l'exposer dans `ReasoningTrace` sous forme dégradée mais non vide.

**Implémentation** : étendre `ReasoningTrace` avec une propriété optionnelle `retrieval_summary: RetrievalSummary` qui inclut :
- `retained_chunks`: list of (doc_id, chunk_excerpt, score)
- `discarded_chunks`: top-N chunks écartés
- `coverage_per_doc`: dict[doc_id, count]
- `mode_explanation`: phrase générée selon le response_mode actif

### 3b. Amélioration B — Affichage explicite des silences

Pour les questions où OSMOSIS détecte qu'une dimension de la question n'est pas couverte par le corpus (signal `coverage_gap` ou `question_context_gap` du `kg_signal_detector`), le panneau doit afficher une section **"Zones de silence"** :

> 🔇 **Le corpus ne couvre pas** :
> - L'aspect environnemental de la conformité (aucun document ingéré sur ce sujet)
> - Les réglementations FAA équivalentes (corpus EU uniquement)

C'est précisément le type d'information qu'un juriste senior valorise hautement : `OSMOSIS sait dire ce qu'il ne sait pas`.

**Implémentation** : exploiter les signaux `coverage_gap` et `question_context_gap` déjà calculés par `kg_signal_detector.py`. Les exposer dans le `ReasoningTrace` sous une nouvelle clé `silence_zones`.

### 3c. Amélioration C — Visualisation des tensions détectées dans la trace

Quand une réponse implique une tension (mode `TENSION`), le `ReasoningTracePanel` doit afficher cette tension comme un **élément distinct et visible**, pas comme une étape parmi d'autres :

- **Bandeau visuel** en haut du panneau : "⚠️ Tension détectée entre Document A et Document B"
- Encart détaillé : `tension_nature`, `tension_level`, `scope_a`, `scope_b`, `explanation` — tous déjà persistés sur la relation `CONTRADICTS` (cf. `contradiction_classifier._persist_classification`)
- Boutons cliquables vers les deux claims en tension (vue side-by-side — cf. N5 nice-to-have de la carte cible)

**Implémentation** : enrichir `ReasoningStep` avec un nouveau champ `tension_details: TensionDetails` quand `is_conflict: true`. Frontend rend différemment ce champ vs un step normal.

---

## 4. Plan d'implémentation

### Phase 0 — Test d'usage actuel (0.5 jour, prérequis)

**Avant tout code**, exécuter un test d'usage sur le système actuel post-ingestion corpus aerospace_compliance :

1. Lancer 5 requêtes représentatives via le frontend chat (cf. M6 cible §3 carte cible)
2. Pour chaque requête : Fred regarde le `ReasoningTracePanel.tsx` en se mettant à la place d'Armand
3. Évaluer si le contenu actuel suffit pour atteindre 5/5 sur les 5 requêtes

Si **5/5 sans modification** → l'ADR est annulé, M6 atteint, on passe.

Si **3-4/5** → les améliorations A/B/C peuvent suffire pour atteindre 5/5. Implémenter.

Si **< 3/5** → l'écart est plus profond, retour à la planche à dessin avec le frontend.

### Phase 1 — Amélioration A (1-2 jours, si nécessaire)

1. Étendre `ReasoningTrace` (model + dataclass) avec `retrieval_summary`
2. `search.py` ou `ReasoningTraceService` populent la `retrieval_summary` à partir des chunks retenus/écartés du retrieval
3. Frontend `ReasoningTracePanel.tsx` rend ce nouveau bloc

### Phase 2 — Amélioration B (1 jour, si nécessaire)

1. `kg_signal_detector.py` expose les signaux `coverage_gap` et `question_context_gap` dans la `ReasoningTrace` (champ `silence_zones`)
2. Frontend rend une section dédiée "Zones de silence" quand non vide
3. Mise à jour des prompts synthesis pour ne pas dupliquer le contenu (silence affiché par UI, pas dans la réponse principale)

### Phase 3 — Amélioration C (1-2 jours, si nécessaire)

1. Étendre `ReasoningStep` avec `tension_details: Optional[TensionDetails]`
2. Backend lit la relation `CONTRADICTS` Neo4j pour peupler `tension_details` quand `is_conflict: true`
3. Frontend rend le bandeau visuel et l'encart détaillé
4. Optionnel : route API pour la vue side-by-side claim A vs claim B (déjà partiellement supportée via les services existants)

### Phase 4 — Re-test d'usage (0.5 jour)

Refaire le Phase 0 sur le système modifié. Cible : 5/5 sur les 5 requêtes représentatives.

---

## 5. Risques et points de vigilance

### Risque 1 — Surcharge cognitive

Trop d'informations dans le panneau peut le rendre **moins** lisible que pas assez. Les sections doivent être pliables/dépliables, et la vue par défaut doit montrer l'essentiel : statement, supports principaux, statut de cohérence. Le détail (chunks écartés, silences, retrieval_summary) doit être accessible mais pas imposé.

### Risque 2 — Silence intrusif

Si chaque réponse affiche systématiquement "le corpus ne couvre pas X, Y, Z" pour des sujets non demandés, cela devient du bruit. La détection de silence doit être **liée à la question** (`question_context_gap` plutôt que silence absolu). Le `kg_signal_detector` le fait déjà — il faut juste s'assurer que l'UI ne montre que les silences pertinents.

### Risque 3 — Latence ajoutée

L'enrichissement de la trace (retrieval_summary, silence_zones, tension_details) ajoute des données à transmettre. Acceptable si la trace reste sous quelques KB. À monitorer pendant le développement.

### Risque 4 — Tension mal liée à la réponse

Quand une `CONTRADICTS` est détectée mais ne concerne **pas la question posée**, l'afficher comme tension associée à la réponse est trompeur. La tension doit être affichée seulement si elle a effectivement contribué au raisonnement de la réponse. La logique `show_in_chat` (déjà calculée par `derive_full_diffusion_flags`) fournit ce filtre.

---

## 6. Articulation avec d'autres ADRs

| ADR | Articulation |
|-----|--------------|
| `ADR_PERSPECTIVE_LAYER_ARCHITECTURE` | La couche Perspective vise à structurer la **restitution**. La trace UI rend visible cette structure. Cet ADR est complémentaire — Perspective produit, UI montre. |
| `ADR_KG_INJECTION_ARCHITECTURE_V3` | Les Response Modes V3 conditionnent la richesse des supports KG. L'amélioration A traite spécifiquement le cas DIRECT/AUGMENTED où l'injection KG narrative est délibérément vide. |
| `ADR_TENSION_CLASSIFICATION` (n°1) | Plus la classification est fiable, plus l'amélioration C est utile. ADR n°1 alimente ADR n°3. |
| `ADR_BENCH_PROTOCOL_ARMAND` (n°2) | Le bench M6 (test d'usage 5/5) consomme ce que cet ADR propose |

---

## 7. Décision

**Démarrer par Phase 0 — test d'usage du système actuel après ingestion**. C'est l'action manquante de l'audit code.

Si le test d'usage Phase 0 produit déjà 5/5, **aucune implémentation**, M6 est atteint.

Si le test d'usage produit 3-4/5, **implémenter les améliorations dans l'ordre** : A (couverture par mode), puis B (silences), puis C (tensions visibles). Chaque amélioration est indépendante et peut être livrée séparément. Total estimé : 3 à 5 jours.

Si < 3/5, suspendre et reprendre la conception avec données concrètes du test d'usage.

L'ADR évite de coder à l'aveugle. La donnée d'usage (Phase 0) précède l'implémentation.
