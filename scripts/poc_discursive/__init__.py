"""
POC Discursive Relation Discrimination

Ce package contient le POC pour tester la capacite a distinguer
les relations discursivement determinees (Type 1) des relations
deduites par raisonnement externe (Type 2).

ATTENTION: Code jetable, non destine a la production.

Voir doc/ongoing/ADR_POC_DISCURSIVE_RELATION_DISCRIMINATION.md pour le cadrage.
"""

from models import (
    Verdict, RejectReason, AbstainReason, TestCaseCategory,
    TestCase, DiscriminationResult, TestSuiteResult,
    POCVerdict, POCConclusion
)
from discriminator import DiscursiveDiscriminator
from runner import POCRunner, POCAnalyzer

__all__ = [
    # Enums
    'Verdict', 'RejectReason', 'AbstainReason', 'TestCaseCategory', 'POCVerdict',
    # Models
    'TestCase', 'DiscriminationResult', 'TestSuiteResult', 'POCConclusion',
    # Classes
    'DiscursiveDiscriminator', 'POCRunner', 'POCAnalyzer'
]
