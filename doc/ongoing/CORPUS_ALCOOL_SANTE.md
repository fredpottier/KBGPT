# Corpus de démo « Alcool & santé » — prêt à ingérer

> **Constitué la nuit du 10→11/06/2026.** Objectif : un corpus médical **dense et
> riche en vraies contradictions datées**, grand public, pour démontrer la détection
> de contradictions + la lignée temporelle que le corpus aéro (harmonisé) ne pouvait
> pas porter. Tenant cible : **`alcohol_health`**.
>
> - **24 PDF open-access** téléchargés dans `data/corpus_alcohol_health/` (43 Mo).
> - **Domain context `alcohol_health` installé** (épidémiologie de l'alcool).
> - Script de re-téléchargement : `scripts/fetch_alcohol_corpus.sh`.

---

## 1. Pourquoi ce corpus (vs aéro)

L'aéro est **harmonisé** (FAA/EASA disent la même chose) → 0 vraie contradiction, la
détection ne pouvait que produire du bruit. L'alcool est l'inverse : la littérature est
**célèbrement contradictoire**, sur des décennies, et tout le monde comprend l'enjeu
(« un verre de vin, bon ou mauvais ? »). C'est le véhicule idéal pour le différenciateur.

Trois ressorts présents dans le corpus :
1. **Contradiction de fond** : *protecteur* (observationnel, courbe en J) vs *nocif / aucun
   bénéfice* (génétique/randomisation mendélienne, méta-analyses récentes).
2. **Contradiction de méthode** : observationnel vs Mendelian randomization vs guideline —
   exactement le « scope/méthode » que l'adjudicateur sait désormais nuancer.
3. **Lignée temporelle** : 2006 → 2014 → 2018 → 2023, et des guidelines qui se renversent.

---

## 2. Carte des contradictions (le cœur de la démo)

| Sujet | Affirmation A (protecteur / ancien) | Affirmation B (nocif / récent) |
|---|---|---|
| **GBD (vedette)** | GBD 2016 / **Griswold 2018** : « **aucun niveau d'alcool n'est sûr** », risque min = 0 verre, pour tous | GBD 2020 / **Bryazka 2022** (même consortium !) : « 0 pour les <40 ans, mais **les 40+ peuvent bénéficier** de 1-2 verres/j » |
| **Mortalité toute cause** | Di Castelnuovo 2006 / Ronksley 2011 : RR ≈ **0,80** (modéré protège) | **Zhao & Stockwell 2023** (107 cohortes) : **aucun bénéfice** après correction du biais des ex-buveurs |
| **Cardiovasculaire** | Ronksley 2011 : modéré ↓ mortalité coronarienne | **Holmes 2014 / Biddinger 2022** (génétique) : **tout niveau ↑** le risque (HR 1,4 coronaire) |
| **AVC** | Patra 2010 : protecteur pour l'AVC **ischémique** (faible dose) | Patra 2010 / Larsson 2016 : **monotone nocif** pour l'AVC **hémorragique** (contradiction *interne*) |
| **Démence** | Méta-analyses observationnelles : **−25 à −38 %** (léger/modéré protège) | MR eClinicalMedicine 2024 : **+15 %/dose**, pas de seuil sûr |
| **Cerveau** | (récit « 1 verre fait du bien ») | **Topiwala 2022** (UK Biobank) : « **aucun niveau sûr** » pour le volume cérébral, dès 4 verres/sem. |
| **Diabète T2** | Baliunas 2009 : modéré protège (RR 0,60-0,87) | …mais **spécifique** (femmes / non-asiatiques) → pas universel |
| **Hypertension** | (pas de protection) | Méta-analyse 2023 : association **linéaire sans seuil** (tout alcool ↑ la PA) — contredit le récit cardio-protecteur |
| **Sein** | (« modéré sans danger ») | Sohi 2024 / méta 2023 : **dès <1 verre/j**, RR ↑ (carcinogène IARC groupe 1) |
| **Guidelines** | ancien « 2 verres/j OK » (US/NIAAA) | **CCSA 2023** : « ≤ 2 verres/**semaine** » ; NHMRC 2020 « ≤10/sem » ; WHO 2023 « aucun niveau sûr » |
| **Méta-narratif** | l'industrie finançait la preuve « protectrice »… | **MACH15 2018** : essai NIH à 100 M$ **annulé** pour financement par l'industrie de l'alcool + biais pro-alcool |

> ⚠️ Pièges « scope » que l'adjudicateur (prompt durci + vote multiple) doit
> correctement classer en **DIFFERENT_SCOPE** et NON en contradiction : ischémique vs
> hémorragique (deux outcomes), observationnel vs génétique (deux méthodes sur le même
> outcome = **vraie** tension, à confirmer), comorbidités surprenantes **protectrices**
> (polyarthrite rhumatoïde −17 %, calculs biliaires RR 0,62) qui ne contredisent pas les
> cancers (sujets différents).

---

## 3. Inventaire (24 PDF dans `data/corpus_alcohol_health/`)

**Mortalité / méthodologie** : Zhao 2023 (JAMA Netw Open), Stockwell 2016 (biais ex-buveurs, JSAD), Ronksley 2011 (BMJ).
**Cardiovasculaire / randomisation mendélienne** : Holmes 2014 (BMJ), Biddinger 2022 (JAMA Netw Open), Million Veteran 2024.
**AVC** : Patra 2010, Larsson 2016.
**Cancers** : méta « par niveaux » 2023, Sohi 2024 (sein), pancréas 2016.
**Démence / cerveau** : démence MR 2024 (eClinicalMedicine), Topiwala 2022 (PLOS Med, fer cérébral), matière grise/blanche UK Biobank 2022 (Nature Comms).
**Métabolique** : Baliunas 2009 (diabète), PA dose-réponse 2023 (Hypertension), hypertension 2024.
**Autres comorbidités** : fibrillation atriale 2022, polyarthrite rhumatoïde 2021 (protecteur), calculs biliaires 2022 (protecteur).
**GBD (vedette)** : Griswold 2018, Bryazka 2022.
**Guidelines / position** : CCSA 2023 (Canada), MACH15 2020 (essai annulé).

**À récupérer manuellement** (paywall lors du download auto) : Rumgay 2021 *Lancet Oncology* (cancers attribuables) ; WHO 2023 *Lancet Public Health* (« no safe level », who.int a un communiqué libre) ; NHMRC 2020 (nhmrc.gov.au) ; UK CMO 2016. Non bloquants — substituts déjà présents.

---

## 4. Runbook — lancer l'import demain matin

```bash
# 1. Activer le corpus alcohol_health (Admin → Configuration → Corpus actif,
#    OU directement) :
docker exec knowbase-app python -c "from knowbase.common.active_corpus import set_active_corpus; set_active_corpus('alcohol_health')"

# 2. Vérifier le domain context (déjà installé) :
docker exec knowbase-app python -c "from knowbase.ontology.domain_context_store import get_domain_context_store as g; p=g().get_profile('alcohol_health'); print(p.industry, len(p.key_concepts), 'concepts')"

# 3. Déposer les PDF dans docs_in → le folder_watcher les ingère SOUS LE CORPUS ACTIF
#    (alcohol_health) car il estampille le corpus actif à l'enqueue (CH_CORPUS_SWITCH) :
cp data/corpus_alcohol_health/*.pdf data/docs_in/

# 4. Suivre l'import :
./kw.ps1 logs worker      # ou page admin Suivi imports
```

⚠️ **Vérifier l'étape 1 AVANT l'étape 3** : si le corpus actif est encore `aero`, les PDF
partiraient dans aero. Le watcher estampille le corpus actif au moment du dépôt.

Après ingestion + post-import (relations + **adjudication avec le toggle « forcer »** →
vote multiple), les contradictions du §2 devraient remonter proprement dans le référentiel
et le chat.

---

## 5. Questions de démo (à tester après import)

- *« La consommation modérée d'alcool protège-t-elle le cœur ? »* → le KG doit confronter
  Ronksley 2011 (protège) ET Holmes 2014 / Biddinger 2022 (génétique : non), avec les dates.
- *« Quelle quantité d'alcool est sans risque ? »* → divergence guidelines + GBD 2018 vs 2022.
- *« L'alcool est-il bon ou mauvais pour le cerveau ? »* → Topiwala « aucun niveau sûr ».
- *« L'alcool a-t-il des effets protecteurs ? »* → nuance : oui sur calculs biliaires /
  polyarthrite (sujets précis), non sur la mortalité/cancers (le système distingue les scopes).

*Lié à : [[CH_CORPUS_SWITCH]], domain context `alcohol_health`, le travail adjudication
(prompt durci + vote multiple).*
