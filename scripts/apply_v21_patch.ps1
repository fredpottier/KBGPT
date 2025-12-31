# Script pour appliquer le patch V2.1 au HybridAnchorChunker
$filePath = "C:\Projects\SAP_KB\src\knowbase\ingestion\hybrid_anchor_chunker.py"
$backupPath = $filePath + ".bak"

# Backup
Copy-Item $filePath $backupPath -Force
Write-Host "Backup created: $backupPath"

# Le nouveau contenu
$newContent = @"
"""
Hybrid Anchor Model - Document-Centric Chunker (Phase 4)

Remplace le TextChunker Phase 1.6 pour le Hybrid Anchor Model:
- Chunking 256 tokens (vs 512) pour meilleure granularite
- SUPPRESSION des concept-focused chunks (source de l'explosion combinatoire)
- Enrichissement payload avec anchored_concepts (liens vers concepts via anchors)

Invariants d'Architecture:
- Les chunks sont decoupes selon des regles fixes (taille, overlap)
- Les concepts sont lies aux chunks via anchors (pas de duplication de contenu)
- Le payload Qdrant ne contient que: concept_id, label, role, span

V2.1 (2024-12): Segment Mapping
- Chaque chunk est mappe vers le segment avec overlap maximal
- Tie-breakers: distance au centre, puis segment le plus ancien
- Validation de couverture segment avec fail-fast optionnel

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

Author: OSMOSE Phase 2
Date: 2024-12
"""
"@

Write-Host "Partial content preview created, manual edit needed for full file"
Write-Host "Please use VS Code or another editor to apply the changes"
