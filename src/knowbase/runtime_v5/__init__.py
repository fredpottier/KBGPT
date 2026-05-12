"""runtime_v5 — POC Reading Agent over Universal Document Structure (CH-51).

Domain-agnostic strict : tous les composants doivent fonctionner sur n'importe
quel corpus (aerospace, SAP, médical, technique) sans modification.

Modules :
  - reading_tools : 7 outils génériques pour navigation documentaire
  - reasoning_agent : agent ReAct DeepSeek-V3.1 + workspace JSON cognitif
  - structure_loader : chargement des structures Document Structure depuis JSON
"""
