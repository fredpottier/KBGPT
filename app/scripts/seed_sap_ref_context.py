"""One-shot : seed le contexte domaine SAP sous tenant 'sap_ref' depuis le pack enterprise_sap.
But : baseline SAP fidèle pour le protocole non-régression (le backup ne contenait que le
contexte aéro). N'affecte PAS le tenant 'default' (aéro)."""
import json
from pathlib import Path
from knowbase.ontology.domain_context import DomainContextProfile
from knowbase.ontology.domain_context_store import get_domain_context_store

PACK = Path("/app/src/knowbase/domain_packs/enterprise_sap/context_defaults.json")
d = json.loads(PACK.read_text(encoding="utf-8"))

store = get_domain_context_store()
# garde-fou : aéro intact
aero = store.get_profile("default")
print("AVANT — default(aéro) industry:", getattr(aero, "industry", None))

prof = DomainContextProfile(
    tenant_id="sap_ref",
    domain_summary=(d.get("domain_summary") or "")[:500],
    industry=(d.get("industry") or "enterprise_software")[:100],
    common_acronyms=d.get("common_acronyms") or {},
    key_concepts=d.get("key_concepts") or [],
    active_packs=["enterprise_sap"],
    context_priority="high",
    llm_injection_prompt="Domaine SAP (ERP S/4HANA, BTP, cloud, integration, analytics). Preserver les identifiants exacts : transactions, SAP Notes, versions/SPS, codes objets.",
)
store.save_profile(prof)

got = store.get_profile("sap_ref")
print("APRÈS — sap_ref industry:", got.industry, "| acronyms:", len(got.common_acronyms or {}), "| concepts:", len(got.key_concepts or []))
aero2 = store.get_profile("default")
print("VÉRIF — default(aéro) industry:", getattr(aero2, "industry", None), "(doit être aerospace_export_control, INCHANGÉ)")
