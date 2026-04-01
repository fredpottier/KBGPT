# ADR — Gestion d'un corpus documentaire vivant

**Date** : 1er avril 2026
**Statut** : Decision de principe — pas d'implementation immediate
**Contexte** : Reflexion sur le fonctionnement d'OSMOSIS avec un corpus qui evolue (documents modifies, corriges, remplaces). Issu d'une analyse collaborative entre l'equipe, Claude Code et ChatGPT.

---

## 1. Probleme

Aujourd'hui, OSMOSIS ingere un corpus de documents statique. Mais en production reelle :
- Les documents sont modifies frequemment (SharePoint, OneDrive, Google Drive creent des dizaines de versions/jour)
- Un document peut etre corrige (erreur factuelle), mis a jour (nouvelle version produit), ou remplace
- Le corpus actif doit rester coherent sans exploser en volume

**Question centrale** : Comment OSMOSIS gere-t-il un document qui change ?

---

## 2. Decision

### Principe fondateur

> **OSMOSIS ne gere pas l'histoire editoriale des documents. Il maintient une representation fidele du corpus que l'organisation reconnait comme actif et representatif.**

### Regles

1. **Un document = une verite**. Le corpus actif est la seule realite qu'OSMOSIS connait. Il n'y a pas de "versions" dans OSMOSIS.

2. **Remplacement, pas versioning**. Quand un document (meme origine, meme identifiant logique) est modifie et re-depose, la nouvelle version **remplace** l'ancienne. L'ancienne est purgee du KG et de Qdrant.

3. **Responsabilite humaine**. Si l'utilisateur veut conserver deux versions comme deux realites distinctes (ex: guide 2022 ET guide 2023), il les depose comme deux documents distincts. OSMOSIS ne devine pas cette intention.

4. **Pas d'historique par defaut**. L'ancienne version n'est pas conservee sauf journal minimal de remplacement (date, checksum, nb claims ajoutes/retires). Pas de timeline de claims, pas d'archive des etats passes.

5. **Detection de changement a deux niveaux**. Hash global pour savoir si le document a change. Hash par section pour savoir *ou* ca a change. Le diff est structurel (hash), pas semantique (pas de LLM, pas d'embedding).

6. **Reingestion ciblee privilegiee, reconstruction complete en fallback**. Quand un document change :
   - Cas courant (< 5% modifie) : purger les claims/chunks des sections changees + re-extraire ces sections
   - Cas rare (> 50% modifie ou diff non fiable) : purge complete du document + reingestion depuis zero
   - Contexte Office 365 : un document est modifie des dizaines de fois par jour. La reingestion complete a chaque modification est insoutenable. Le diff par section est indispensable.

---

## 3. Ce que ca implique (a implementer plus tard)

### A. Purge ciblee par document
Aujourd'hui : purge totale du corpus ou rien.
Necessaire : `DELETE /api/documents/{doc_id}` qui supprime :
- Tous les chunks Qdrant de ce document
- Toutes les claims Neo4j de ce document
- Toutes les relations impliquant ces claims
- Les entites orphelines resultantes

### B. Empreinte d'ingestion
Au lieu de garder le cache complet (.knowcache.json) indefiniment :
- Stocker un fingerprint minimal : hash fichier, **hash par section/page/slide**, date ingestion, nb claims extraites par section
- Le hash par section est essentiel pour le diff structurel (niveau 2) qui permet la reingestion partielle
- Suffisant pour decider "a change ou pas" ET "ou ca a change" sans stocker le contenu
- Compatible avec les contraintes legales (pas de duplication du contenu source)

### C. Pipeline de re-ingestion
Quand un document modifie est detecte :
1. Comparer le hash avec le fingerprint stocke
2. Si identique → skip (aucun changement)
3. Si different → purge ciblee du document + reingestion normale
4. Les steps post-import (C4, C6, canonicalization) se relancent sur le document concerne

### D. Connecteurs source (futur)
Pour les sources type OneDrive/SharePoint/Google Drive :
- Webhook ou polling pour detecter les modifications
- Filtrage : ignorer les modifications triviales (meme hash apres normalisation)
- Cooldown : ne pas reingerer si le document a ete modifie il y a moins de N heures (eviter les versions intermediaires d'edition en cours)

---

## 4. Gestion des sources mouvantes (Office 365, SharePoint, Google Drive)

### Probleme

Un document Word sur OneDrive est modifie des dizaines de fois par jour. On ne peut pas purger + reingerer un document complet a chaque modification. Cela mettrait le systeme a terre.

### Solution : 3 niveaux de filtrage

**Niveau 1 — Cooldown temporel**
- Ne jamais reagir en temps reel aux modifications source
- Verifier les changements toutes les N heures (configurable, ex: 4h, 12h, 24h)
- Si le doc a ete modifie 15 fois depuis la derniere verification, ne regarder que l'etat actuel vs le dernier etat ingere
- Un doc en cours d'edition (modifie il y a < 1h) est considere instable → skip

**Niveau 2 — Diff structurel leger (sans LLM)**
- Comparer l'etat actuel avec l'empreinte d'ingestion stockee
- Hash par section/page/slide (pas embedding, pas LLM)
- Si 100% identique → skip total (cas le plus frequent)
- Si > 95% identique → identifier les sections changees seulement
- Si < 50% identique → considerer comme document reecrit → reingestion complete

**Niveau 3 — Reingestion ciblee**
- Purger uniquement les claims/chunks des sections modifiees
- Re-extraire ces sections via le pipeline ClaimFirst
- Recalculer les relations impliquees (C4/C6 sur les claims touches)
- Avantage : ne retraite que 5-10% du document au lieu de 100%

### Prerequis techniques (a implementer plus tard)
- Empreinte par section stockee (hash par page/slide, pas juste hash global)
- Ancrage des claims sur leur section source (deja partiellement fait via charspan)
- Purge ciblee par section (pas seulement par document entier)

### Fallback
Si le diff structurel n'est pas fiable ou si trop de sections ont change :
→ purge complete du document + reingestion complete. Plus lent mais toujours correct.

---

## 5. Ce que ca N'implique PAS

- ❌ Pas de versioning des claims (ClaimKey + timeline)
- ❌ Pas de conservation des anciennes versions de documents
- ❌ Pas de diff semantique par embedding (trop couteux pour le volume Office 365)
- ❌ Pas de classification automatique du type de changement (correction vs evolution)
- ❌ Pas de "desactivation" soft des anciennes claims (suppression franche)

Rejetees pour cette phase : complexite disproportionnee vs valeur produit.

---

## 5. Philosophie resume

> OSMOSIS n'est pas la pour faire la baby-sitter des utilisateurs. Il dessine une realite documentaire a partir des documents que les utilisateurs estiment etre representatifs de cette realite.

> Quand un document est remplace, OSMOSIS doit remplacer sa projection, pas conserver ses etats passes comme si l'outil devait arbitrer a la place de l'organisation.

> Le corpus actif decide de la realite que voit OSMOSIS.

---

## 6. Invariants associes

- **INV-CORPUS-01** : Un document dans OSMOSIS = un etat actif unique. Pas de versions multiples du meme document logique.
- **INV-CORPUS-02** : Remplacement = purge + reingestion. Jamais de patch incremental sur les claims.
- **INV-CORPUS-03** : L'utilisateur est responsable de la composition du corpus. OSMOSIS ne devine pas les intentions de versioning.
- **INV-CORPUS-04** : Les caches d'extraction sont ephemeres. Seules les empreintes d'ingestion sont conservees a long terme.

---

*Document de reference pour le design futur. Pas d'implementation dans la phase actuelle (Phase 3-4).*
*Issu d'une reflexion collaborative equipe + Claude Code + ChatGPT (1er avril 2026).*
