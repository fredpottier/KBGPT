"""
Facts Governance Layer

Ce module implémente la gouvernance intelligente des facts métier.

Composants:
- service.py: FactsService (CRUD, gouvernance, workflow)
- conflict_detector.py: ConflictDetector (détection contradictions)
- timeline.py: TimelineService (historique temporel)
- schemas.py: Pydantic models (FactCreate, FactResponse, ConflictDetail)
- validators.py: Validateurs business rules (temporalité, cohérence)

Workflow:
1. Extraction → Fact proposé (status="proposed")
2. Détection conflits automatique
3. Review expert (UI Admin)
4. Approval/Rejection (status="approved"/"rejected")
5. Timeline update (valid_from/until)
"""

__version__ = "1.0.0"
