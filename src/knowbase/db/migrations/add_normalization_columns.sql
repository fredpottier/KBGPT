-- Migration: Ajout colonnes workflow normalisation
-- Phase 5B - Entity Types Normalization Status
-- Date: 2025-10-08

-- Ajouter colonnes normalisation au registry
ALTER TABLE entity_types_registry ADD COLUMN normalization_status VARCHAR(20);
ALTER TABLE entity_types_registry ADD COLUMN normalization_job_id VARCHAR(50);
ALTER TABLE entity_types_registry ADD COLUMN normalization_started_at TIMESTAMP;

-- Commentaires
COMMENT ON COLUMN entity_types_registry.normalization_status IS 'Statut normalisation: generating | pending_review | NULL (none)';
COMMENT ON COLUMN entity_types_registry.normalization_job_id IS 'Job ID RQ de la génération d''ontologie en cours';
COMMENT ON COLUMN entity_types_registry.normalization_started_at IS 'Date lancement dernière normalisation';
