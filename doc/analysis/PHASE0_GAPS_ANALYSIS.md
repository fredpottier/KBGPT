# ANALYSE COMPLÈTE PHASE 0 - GAPS & DURCISSEMENT

## 1. ANALYSE PAR CRITÈRE

### Critère 1: Cold Start Bootstrap
**Status**: ✅ FAIT
**Gaps identifiés**:
- ⚠️ get_candidates() retourne [] (Phase 3 pas implémentée)
- ⚠️ Pas de limite max_candidates dans auto_bootstrap (risque OOM si 100k+ candidates)
- ⚠️ Pas de rate limiting sur endpoint bootstrap (risque DOS)
- ⚠️ Pas de lock distribué (risque double bootstrap concurrent)
- ⚠️ Pas de rollback si bootstrap échoue à mi-chemin

### Critère 2: Idempotence & Déterminisme
**Status**: ✅ FAIT
**Gaps identifiés**:
- ⚠️ Redis single point of failure (pas de fallback si Redis down)
- ⚠️ TTL 24h peut être trop court pour long-running processes
- ⚠️ Pas de cleanup des clés expirées (peut accumuler mémoire)
- ⚠️ Body hash ne gère pas ordre différent des champs JSON
- ⚠️ Timestamps dans résultats (pas 100% déterministe si replay années plus tard)

### Critère 3: Undo/Split Transactionnel
**Status**: ✅ FAIT
**Gaps identifiés**:
- ⚠️ Pas de vérification si merge déjà undo (risque double undo)
- ⚠️ Undo ne vérifie pas si candidates ont été re-merged ailleurs
- ⚠️ Pas de cascade delete si entité canonique supprimée
- ⚠️ Audit trail Redis peut perdre données si crash avant persist
- ⚠️ Pas de snapshots audit trail (récupération impossible après TTL 30j)

### Critère 4: Quarantaine Merges
**Status**: ✅ FAIT
**Gaps identifiés**:
- ⚠️ Pas de notification si merge reste en quarantine >24h
- ⚠️ QuarantineProcessor synchrone (peut bloquer si 1000+ merges)
- ⚠️ Pas de priorité (tous merges traités également)
- ⚠️ Pas de pause/resume si processor crash à mi-chemin
- ⚠️ Pas de DLQ (Dead Letter Queue) pour merges failed

### Critère 5: Backfill Scalable Qdrant
**Status**: ✅ FAIT
**Gaps identifiés**:
- ⚠️ Simulation Phase 0 (pas de vraie requête Qdrant)
- ⚠️ _get_chunks_for_entity() génère IDs fictifs (pas de vraie récupération)
- ⚠️ Pas de validation si chunks existent vraiment avant backfill
- ⚠️ Pas de rollback si backfill échoue à mi-chemin
- ⚠️ Exactly-once Redis peut perdre état si crash avant persist
- ⚠️ Pas de monitoring Qdrant health avant backfill

### Critère 6: Fallback Extraction Unifiée
**Status**: ✅ FAIT
**Gaps identifiés**:
- ⚠️ Pas de queue async retry (slides fallback jamais réessayés)
- ⚠️ Pas de métriques taux fallback (impossible détecter LLM dégradé)
- ⚠️ Fallback peut créer doublons si LLM répond après timeout
- ⚠️ Pas de deduplication fallback chunks vs enriched chunks
- ⚠️ Logs fallback peuvent spammer si LLM down longtemps

## 2. GAPS TRANSVERSES CRITIQUES

### 2.1 Gestion Erreurs & Résilience
- ❌ **Pas de circuit breaker** sur appels LLM/Qdrant
- ❌ **Pas de health checks** endpoints critiques
- ❌ **Pas de graceful degradation** si services externes down
- ❌ **Pas de DLQ** (Dead Letter Queue) pour jobs failed
- ❌ **Pas de alerting** sur métriques critiques (taux erreur, latence)

### 2.2 Sécurité & Validation
- ❌ **Pas de rate limiting** sur endpoints admin
- ❌ **Pas d'authentification** sur endpoints sensibles (bootstrap, undo)
- ❌ **Pas de validation taille** inputs (risque payload bombs)
- ❌ **Pas de sanitization** user inputs (risque injection)
- ❌ **Pas d'audit logs sécurité** (qui fait quoi, quand)

### 2.3 Performance & Scalabilité
- ❌ **Pas de pagination** sur endpoints retournant listes
- ❌ **Pas de caching** résultats fréquents
- ❌ **Pas de connection pooling** Redis/Qdrant
- ❌ **Pas de lazy loading** données volumineuses
- ❌ **Pas de compression** payloads volumineux

### 2.4 Observabilité & Debugging
- ❌ **Pas de request ID** propagé dans tous les logs
- ❌ **Pas de tracing distribué** (impossible suivre flux complet)
- ❌ **Pas de métriques business** (taux merge, taux undo, etc.)
- ❌ **Pas de dashboards monitoring** temps réel
- ❌ **Pas de runbooks** incident response

### 2.5 Data Integrity & Consistency
- ❌ **Pas de transactions ACID** multi-services (Redis + Qdrant)
- ❌ **Pas de validation schema** payloads Redis/Qdrant
- ❌ **Pas de checksums** données stockées
- ❌ **Pas de backups automatiques** audit trail
- ❌ **Pas de disaster recovery** plan

## 3. CAS LIMITES NON GÉRÉS

### 3.1 Race Conditions
1. **Double bootstrap concurrent**: 2 users cliquent bootstrap en même temps
2. **Merge pendant undo**: User A undo pendant que QuarantineProcessor approve
3. **Backfill concurrent**: 2 processors backfillent même canonical_id
4. **Cache invalidation**: Redis flush pendant merge en cours

### 3.2 Scénarios Extrêmes
1. **Qdrant full**: Backfill échoue car storage full
2. **Redis OOM**: Cache idempotence ne peut plus écrire
3. **LLM rate limit**: Tous slides passent en fallback
4. **Network partition**: Redis accessible mais Qdrant down
5. **Audit trail overflow**: 1M+ merges accumulent en Redis

### 3.3 Edge Cases Métier
1. **Undo après 6.9 jours**: Entre limite 7j et TTL audit 30j
2. **Merge avec 0 candidates**: Validation manquante
3. **Canonical entity supprimée**: Références orphelines
4. **Circular merges**: A→B, B→C, C→A
5. **Merge self-reference**: canonical_id dans candidate_ids

## 4. RECOMMANDATIONS DURCISSEMENT (PRIORITÉS)

### 🔴 P0 - CRITIQUES (à implémenter maintenant)
1. **Lock distribué bootstrap** (éviter double bootstrap)
2. **Validation merge inputs** (0 candidates, self-reference, circular)
3. **Redis connection retry** (résilience si Redis flap)
4. **Rate limiting endpoints** (protection DOS)
5. **Request ID propagation** (debugging distribué)

### 🟠 P1 - IMPORTANTES (avant production)
6. **Circuit breaker LLM/Qdrant** (graceful degradation)
7. **Health checks endpoints** (/health, /ready)
8. **Pagination grandes listes** (candidates, merges)
9. **Audit logs sécurité** (qui fait quoi)
10. **Backups audit trail** (disaster recovery)

### 🟡 P2 - BONNES PRATIQUES (amélioration continue)
11. **Métriques Prometheus** (taux merge, latence, erreurs)
12. **Tracing distribué** (OpenTelemetry)
13. **DLQ jobs failed** (retry manuel)
14. **Dashboards Grafana** (monitoring temps réel)
15. **Runbooks incidents** (procédures escalade)

## 5. PLAN D'ACTION IMMÉDIAT

### Phase 0.5 (Durcissement Critique - 2 jours)
- [ ] Lock distribué Redis pour bootstrap/quarantine processor
- [ ] Validation stricte inputs merge (0 candidates, circular, self-ref)
- [ ] Retry logic Redis avec backoff exponentiel
- [ ] Rate limiting FastAPI sur endpoints critiques
- [ ] Request ID middleware + propagation logs

### Tests Durcissement
- [ ] Test concurrent bootstrap (2 users simultanés)
- [ ] Test merge inputs invalides (edge cases)
- [ ] Test Redis flapping (connection lost/regained)
- [ ] Test rate limit (burst requests)
- [ ] Test request ID propagation (multi-services)

