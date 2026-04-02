# Recherche — Detection des questions "unanswerable" dans OSMOSIS

**Date** : 2 avril 2026
**Contexte** : unanswerable = 44% (V16 LLM-juge). 5 approches testees et eliminees (prompt, gap lexical, dense score, QA-Class, post-keyword).

---

## 1. Approches testees et eliminees (rappel)

| Approche | Score | Pourquoi ca echoue |
|---|---|---|
| Prompt "honesty rule" | 52% | Degrade les autres categories (-18pp false_premise) |
| Gap lexical IDF | 64% | Cross-lingue impossible (FR→EN = gap artificiel) |
| Dense score pre-RRF | ~10% | Ne discrimine pas (ecart 0.04 entre AN et UN) |
| QA-Class Qwen/vLLM | 66% | 62 faux rejets sur 246 questions (31%) |
| Post-keyword | variable | Ne capte que les refus explicites |

## 2. Insight cle de la litterature

**Le paradoxe RAG-abstention** (Google Research + NeurIPS 2024) : RAG REDUIT la capacite d'abstention du LLM car le contexte supplementaire augmente la confiance, meme quand le contexte n'est pas pertinent pour la question. Le prompting seul est structurellement insuffisant pour resoudre le probleme.

→ Nos echecs de prompt tuning ne sont PAS un manque de finesse du prompt. C'est un probleme structurel du RAG.

## 3. Pistes prometteuses (etat de l'art 2024-2025)

### Priorite 1 : HALT / EPR — Logprob Entropy Detection

**Principe** : Analyser l'entropie des logprobs du LLM pendant la generation. Quand le modele est incertain, les probabilites des tokens alternatifs sont instables (spikes d'entropie).

**References** :
- HALT (arXiv 2602.02888) : GRU sur logprob time series
- EPR (arXiv 2509.04492) : Entropy Production Rate pour API black-box

**Avantages** :
- Zero cout supplementaire (utilise les logprobs deja generes)
- Cross-lingue natif (signal statistique, pas lexical)
- Ne degrade pas les reponses (post-hoc)
- Implementable avec GPT-4o-mini (`logprobs=true`) et Qwen/vLLM

**Implementation** :
1. Activer `logprobs=true, top_logprobs=5` dans l'appel de synthese
2. Calculer l'entropie moyenne des top-5 tokens sur la reponse
3. Si entropie > seuil → flag "reponse potentiellement non fondee"
4. Calibrer le seuil sur les 25 questions unanswerable du benchmark

**Effort** : 1-2h (modification de synthesis.py + signal)

### Priorite 2 : CDA — Contrastive Decoding with Abstention

**Principe** : Comparer la reponse AVEC et SANS contexte recupere. Si identique → le modele n'utilise pas les sources → probable hallucination.

**Reference** : ACL 2025 (arXiv 2412.12527)

**Avantages** :
- Repond directement a "est-ce que le contexte a ete utile ?"
- Cross-lingue natif
- Training-free

**Inconvenient** : Cout 2x (double forward pass). Avec GPT-4o-mini : $0.0024/question au lieu de $0.0012.

**Implementation** :
1. Pour chaque question, generer une reponse AVEC contexte (normal)
2. Generer une reponse SANS contexte (juste la question)
3. Comparer les deux (similarite semantique ou keyword overlap)
4. Si trop similaires → flag "reponse non fondee sur les sources"

**Effort** : 2-3h

### Priorite 3 : NLI Post-hoc (HALT-RAG)

**Principe** : Utiliser un modele NLI (mDeBERTa-v3-base-xnli, ~300M params) pour verifier si la reponse est "entailed" par le contexte recupere.

**Reference** : arXiv 2509.07475

**Avantages** : Multilingue (xnli couvre ~100 langues), rapide (~10ms), calibrable.

**Effort** : 3-4h (install mDeBERTa + integration)

### Options futures (si fine-tuning envisage)

- **R-Tuning** (NAACL 2024 Outstanding Paper) : Fine-tuner Qwen pour apprendre a refuser. ~1000 exemples. Resolution a la racine.
- **GRACE** (RL) : Framework RL pour equilibrer reponse fondee et abstention. Etat de l'art mais lourd.

## 4. Recommandation

**HALT/EPR (logprob entropy)** est le meilleur rapport cout/benefice :
- Zero cout supplementaire
- 1-2h d'implementation
- Cross-lingue natif
- Pas de degradation
- Calibrable sur notre benchmark existant

Si insuffisant, **CDA (contrastive decoding)** est le plan B — plus couteux mais plus precis.

---

*Document de reference pour le chantier unanswerable. A mettre a jour apres implementation.*
