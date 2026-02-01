"""
OSMOSE — Diagnostic Localité Macro ↔ Micro
============================================
Étape 1: Vérifier si le désalignement macro/micro est exploitable.

Question: Les assertions mal routées (SINK ou no_concept_match) sont-elles
dans des sections qui correspondent à des concepts aujourd'hui vides ?

Méthode:
1. Charger les DocItems du cache (avec page_no)
2. Charger depuis Neo4j: themes, concepts, informations, assertion_logs
3. Construire la matrice page → theme → concept → informations
4. Analyser le routage: SINK et no_concept_match vs concepts vides
"""

import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


CACHE_PATH = "/data/extraction_cache/363f5357dfe38242a968415f643eff1edca39866d7e714bcb9ea5606cece5359.v5cache.json"


def load_docitems_from_cache():
    """Charge les DocItems du cache v5 avec page_no."""
    with open(CACHE_PATH, "r", encoding="utf-8") as f:
        cache = json.load(f)

    extraction = cache.get("extraction", {})
    stats = extraction.get("stats", {})
    structural = stats.get("structural_graph", {})
    items = structural.get("items", [])

    docitems = {}
    for item in items:
        item_id = item.get("item_id", "")
        docitems[item_id] = {
            "item_id": item_id,
            "item_type": item.get("item_type", ""),
            "text": item.get("text", "")[:100],
            "page_no": item.get("page_no", 0),
            "heading_level": item.get("heading_level"),
        }

    logger.info(f"[Cache] {len(docitems)} DocItems chargés")
    return docitems


def load_neo4j_data():
    """Charge themes, concepts, informations et assertion_logs depuis Neo4j."""
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "graphiti_neo4j_pass"))

    data = {}

    with driver.session() as session:
        # Themes
        result = session.run("MATCH (t:Theme) RETURN t.theme_id AS id, t.name AS name")
        data["themes"] = {r["id"]: r["name"] for r in result}

        # Concepts avec theme_id et infos count
        result = session.run("""
            MATCH (t:Theme)-[:HAS_CONCEPT]->(c:Concept)
            OPTIONAL MATCH (c)-[:HAS_INFORMATION]->(i:Information)
            RETURN c.concept_id AS id, c.name AS name, c.role AS role,
                   t.theme_id AS theme_id, t.name AS theme_name,
                   count(i) AS n_infos
        """)
        data["concepts"] = []
        for r in result:
            data["concepts"].append({
                "id": r["id"], "name": r["name"], "role": r["role"],
                "theme_id": r["theme_id"], "theme_name": r["theme_name"],
                "n_infos": r["n_infos"]
            })

        # Informations avec concept_id et docitem anchor
        result = session.run("""
            MATCH (c:Concept)-[:HAS_INFORMATION]->(i:Information)
            RETURN i.info_id AS info_id, i.text AS text, i.type AS type,
                   c.concept_id AS concept_id, c.name AS concept_name,
                   c.role AS concept_role
        """)
        data["informations"] = []
        for r in result:
            data["informations"].append({
                "info_id": r["info_id"], "text": r["text"], "type": r["type"],
                "concept_id": r["concept_id"], "concept_name": r["concept_name"],
                "concept_role": r["concept_role"]
            })

        # InformationMVP avec anchor_docitem_ids
        result = session.run("""
            MATCH (im:InformationMVP)
            RETURN im.information_id AS id, im.text AS text,
                   im.concept_id AS concept_id,
                   im.anchor_docitem_ids AS anchors
        """)
        data["info_mvp"] = []
        for r in result:
            data["info_mvp"].append({
                "id": r["id"], "text": (r["text"] or "")[:100],
                "concept_id": r["concept_id"],
                "anchors": r["anchors"] or []
            })

        # Assertion logs (REJECTED + ABSTAINED)
        result = session.run("""
            MATCH (al:AssertionLog)
            WHERE al.status IN ['ABSTAINED', 'REJECTED']
            RETURN al.assertion_id AS id, al.text AS text, al.type AS type,
                   al.status AS status, al.reason AS reason,
                   al.concept_id AS concept_id
        """)
        data["failed_assertions"] = []
        for r in result:
            data["failed_assertions"].append({
                "id": r["id"], "text": r["text"], "type": r["type"],
                "status": r["status"], "reason": r["reason"],
                "concept_id": r["concept_id"]
            })

    driver.close()
    logger.info(
        f"[Neo4j] {len(data['themes'])} themes, {len(data['concepts'])} concepts, "
        f"{len(data['informations'])} infos, {len(data['info_mvp'])} info_mvp, "
        f"{len(data['failed_assertions'])} failed assertions"
    )
    return data


def build_page_to_heading_map(docitems):
    """
    Construit une map page → heading le plus récent.
    Simule les "sections" du document par les headings rencontrés.
    """
    # Trier par reading_order (page_no comme proxy)
    sorted_items = sorted(docitems.values(), key=lambda d: (d["page_no"], d.get("item_id", "")))

    page_heading = {}
    current_heading = "(no heading)"

    for item in sorted_items:
        if item["item_type"] == "HEADING" and item.get("heading_level") in (1, 2):
            current_heading = item["text"][:80]
        page_heading[item["page_no"]] = current_heading

    logger.info(f"[Sections] {len(set(page_heading.values()))} headings distincts sur {len(page_heading)} pages")
    return page_heading


def extract_page_from_anchor(anchor_id, docitems):
    """Extrait le page_no depuis un anchor docitem_id composite."""
    # Format: "default:doc_id:item_id" — on veut le item_id
    parts = anchor_id.split(":")
    if len(parts) >= 3:
        item_id = parts[-1]  # Le dernier segment
    else:
        item_id = anchor_id

    item = docitems.get(item_id)
    if item:
        return item["page_no"]
    return None


def main():
    logger.info("=" * 70)
    logger.info("[DIAGNOSTIC LOCALITÉ] Étape 1 — Faisabilité")
    logger.info("=" * 70)

    # 1. Charger les données
    docitems = load_docitems_from_cache()
    neo = load_neo4j_data()
    page_heading = build_page_to_heading_map(docitems)

    # 2. Mapper informations → pages (via InformationMVP anchors)
    info_to_pages = {}
    for imvp in neo["info_mvp"]:
        pages = set()
        for anchor in imvp["anchors"]:
            page = extract_page_from_anchor(anchor, docitems)
            if page is not None:
                pages.add(page)
        if pages:
            info_to_pages[imvp["id"]] = pages

    logger.info(f"[Mapping] {len(info_to_pages)}/{len(neo['info_mvp'])} info_mvp avec pages résolues")

    # 3. Construire concept → pages (via ses informations)
    concept_pages = defaultdict(set)
    for imvp in neo["info_mvp"]:
        cid = imvp.get("concept_id")
        if cid and imvp["id"] in info_to_pages:
            concept_pages[cid].update(info_to_pages[imvp["id"]])

    # 4. Classer les concepts
    concepts_by_id = {c["id"]: c for c in neo["concepts"]}
    empty_concepts = [c for c in neo["concepts"] if c["n_infos"] == 0 and c["role"] != "SINK"]
    populated_concepts = [c for c in neo["concepts"] if c["n_infos"] > 0 and c["role"] != "SINK"]
    sink_concept = next((c for c in neo["concepts"] if c["role"] == "SINK"), None)

    logger.info(f"\n[Concepts] {len(populated_concepts)} peuplés, {len(empty_concepts)} vides, SINK={'oui' if sink_concept else 'non'}")

    # 5. Déterminer les "pages de provenance" des concepts peuplés
    # = pages où sont ancrées les informations de chaque concept
    logger.info("\n" + "=" * 70)
    logger.info("[MATRICE] Theme → Concept → Pages")
    logger.info("=" * 70)

    themes_concepts = defaultdict(list)
    for c in neo["concepts"]:
        if c["role"] != "SINK":
            themes_concepts[c["theme_name"]].append(c)

    for theme_name in sorted(themes_concepts.keys()):
        concepts = themes_concepts[theme_name]
        logger.info(f"\n  📁 {theme_name}")
        for c in sorted(concepts, key=lambda x: -x["n_infos"]):
            pages = sorted(concept_pages.get(c["id"], set()))
            pages_str = ",".join(str(p) for p in pages[:10])
            if len(pages) > 10:
                pages_str += f"... (+{len(pages)-10})"
            status = f"{c['n_infos']} infos" if c["n_infos"] > 0 else "VIDE"
            logger.info(f"    {'✅' if c['n_infos'] > 0 else '❌'} {c['name']:<50s} [{status:>8s}] pages=[{pages_str}]")

    # 6. SINK — pages d'où viennent les assertions SINK
    logger.info("\n" + "=" * 70)
    logger.info("[SINK] Pages des assertions SINK")
    logger.info("=" * 70)

    sink_pages = Counter()
    sink_headings = Counter()
    if sink_concept:
        for imvp in neo["info_mvp"]:
            if imvp.get("concept_id") == sink_concept["id"]:
                pages = info_to_pages.get(imvp["id"], set())
                for p in pages:
                    sink_pages[p] += 1
                    heading = page_heading.get(p, "(unknown)")
                    sink_headings[heading] += 1

    for heading, cnt in sink_headings.most_common(15):
        logger.info(f"  SINK heading: {heading:<60s} ({cnt} infos)")

    # 7. no_concept_match — quelles pages ?
    # On ne peut pas directement mapper les assertion_logs aux pages car ils n'ont
    # pas d'anchor. Mais on peut chercher le texte dans les DocItems.
    logger.info("\n" + "=" * 70)
    logger.info("[NO_CONCEPT_MATCH] Analyse des assertions non liées")
    logger.info("=" * 70)

    no_match = [a for a in neo["failed_assertions"] if a["reason"] == "no_concept_match"]
    logger.info(f"  Total no_concept_match: {len(no_match)}")

    # Chercher chaque assertion dans les DocItems pour trouver sa page
    # (match par substring du texte)
    assertion_page_map = {}
    docitem_texts = {item["item_id"]: item for item in docitems.values() if len(item["text"]) >= 20}

    # Index inversé: premiers mots → docitems (pour accélérer)
    for assertion in no_match:
        atext = (assertion.get("text") or "")[:60].lower()
        if not atext:
            continue
        best_page = None
        for item in docitems.values():
            if atext[:30] in item["text"].lower():
                best_page = item["page_no"]
                break
        if best_page is not None:
            assertion_page_map[assertion["id"]] = best_page

    logger.info(f"  Assertions localisées: {len(assertion_page_map)}/{len(no_match)}")

    no_match_headings = Counter()
    no_match_pages = Counter()
    for aid, page in assertion_page_map.items():
        no_match_pages[page] += 1
        heading = page_heading.get(page, "(unknown)")
        no_match_headings[heading] += 1

    for heading, cnt in no_match_headings.most_common(15):
        logger.info(f"  no_match heading: {heading:<60s} ({cnt} assertions)")

    # 8. QUESTION CLÉ: les assertions mal routées sont-elles dans des pages
    #    qui correspondent à des concepts vides ?
    logger.info("\n" + "=" * 70)
    logger.info("[QUESTION CLÉ] Overlap SINK/no_match ↔ concepts vides")
    logger.info("=" * 70)

    # Pages couvertes par les concepts peuplés
    populated_pages = set()
    for c in populated_concepts:
        populated_pages.update(concept_pages.get(c["id"], set()))

    # Pages des concepts vides: on ne peut pas les déterminer directement
    # (ils n'ont pas d'infos, donc pas de pages)
    # MAIS on peut vérifier si les thèmes des concepts vides
    # correspondent aux headings des assertions mal routées

    # Mapper themes vides → leurs concepts vides
    empty_by_theme = defaultdict(list)
    for c in empty_concepts:
        empty_by_theme[c["theme_name"]].append(c["name"])

    # Compter combien de no_match/SINK sont dans des headings
    # qui "ressemblent" aux thèmes avec concepts vides
    logger.info("\n  Thèmes avec concepts vides:")
    for theme, concepts in sorted(empty_by_theme.items()):
        logger.info(f"    {theme}: {', '.join(concepts)}")

    # Matching textuel simple: heading contient un mot-clé du thème ou du concept vide
    def heading_matches_theme_or_concept(heading, theme_name, concept_names):
        """Check if a heading semantically relates to a theme/concept."""
        h = heading.lower()
        # Check theme keywords
        for word in theme_name.lower().split():
            if len(word) >= 4 and word in h:
                return True
        # Check concept name keywords
        for cname in concept_names:
            for word in cname.lower().split():
                if len(word) >= 4 and word in h:
                    return True
        return False

    # Pour chaque SINK heading, vérifier s'il matche un thème avec concepts vides
    sink_matching_empty = 0
    sink_total = sum(sink_headings.values())
    for heading, cnt in sink_headings.items():
        for theme, concepts in empty_by_theme.items():
            if heading_matches_theme_or_concept(heading, theme, concepts):
                sink_matching_empty += cnt
                logger.info(f"  ✅ SINK '{heading}' ({cnt}) → thème vide '{theme}'")
                break

    # Pour chaque no_match heading, même chose
    nomatch_matching_empty = 0
    nomatch_total = sum(no_match_headings.values())
    for heading, cnt in no_match_headings.items():
        for theme, concepts in empty_by_theme.items():
            if heading_matches_theme_or_concept(heading, theme, concepts):
                nomatch_matching_empty += cnt
                logger.info(f"  ✅ no_match '{heading}' ({cnt}) → thème vide '{theme}'")
                break

    # Concept "aspirateur" — TOM analysis
    logger.info("\n" + "=" * 70)
    logger.info("[ASPIRATEUR] Analyse 'Technical Organisational Measures'")
    logger.info("=" * 70)

    tom_concept = next((c for c in neo["concepts"] if "Technical Organi" in c["name"]), None)
    if tom_concept:
        tom_pages = sorted(concept_pages.get(tom_concept["id"], set()))
        tom_headings = Counter()
        for imvp in neo["info_mvp"]:
            if imvp.get("concept_id") == tom_concept["id"]:
                for p in info_to_pages.get(imvp["id"], set()):
                    tom_headings[page_heading.get(p, "(unknown)")] += 1

        logger.info(f"  TOM: {tom_concept['n_infos']} infos, pages={tom_pages}")
        logger.info(f"  Headings sources:")
        for heading, cnt in tom_headings.most_common():
            logger.info(f"    {heading:<60s} ({cnt} infos)")

        # Combien sont vraiment dans une section "TOM" vs aspirées d'ailleurs ?
        tom_legit = 0
        tom_foreign = 0
        for heading, cnt in tom_headings.items():
            h = heading.lower()
            if any(w in h for w in ["technical", "organi", "measure", "tom"]):
                tom_legit += cnt
            else:
                tom_foreign += cnt
        logger.info(f"\n  TOM precision: {tom_legit}/{tom_legit+tom_foreign} légitimes ({tom_legit/max(1,tom_legit+tom_foreign)*100:.0f}%)")
        logger.info(f"  TOM aspirées d'ailleurs: {tom_foreign}")

    # VERDICT
    logger.info("\n" + "=" * 70)
    logger.info("[VERDICT] Faisabilité localité")
    logger.info("=" * 70)

    logger.info(f"  SINK total: {sink_total}")
    logger.info(f"  SINK dans headings → thèmes vides: {sink_matching_empty} ({sink_matching_empty/max(1,sink_total)*100:.0f}%)")
    logger.info(f"  no_concept_match total localisé: {nomatch_total}")
    logger.info(f"  no_match dans headings → thèmes vides: {nomatch_matching_empty} ({nomatch_matching_empty/max(1,nomatch_total)*100:.0f}%)")

    combined = sink_matching_empty + nomatch_matching_empty
    combined_total = sink_total + nomatch_total
    logger.info(f"\n  COMBINED: {combined}/{combined_total} ({combined/max(1,combined_total)*100:.0f}%) des mal-routées → thèmes avec concepts vides")

    if combined / max(1, combined_total) >= 0.4:
        logger.info("  ✅ LOCALITÉ EXPLOITABLE — un signal de section améliorerait le routage")
    elif combined / max(1, combined_total) >= 0.2:
        logger.info("  ⚠️ LOCALITÉ PARTIELLE — signal utile mais pas suffisant seul")
    else:
        logger.info("  ❌ LOCALITÉ FAIBLE — le problème est ailleurs (linking sémantique, ontologie)")

    # Sauvegarder
    output = {
        "date": datetime.now().isoformat(),
        "metrics": {
            "sink_total": sink_total,
            "sink_matching_empty_themes": sink_matching_empty,
            "nomatch_total": nomatch_total,
            "nomatch_matching_empty_themes": nomatch_matching_empty,
            "combined_ratio": combined / max(1, combined_total),
            "populated_concepts": len(populated_concepts),
            "empty_concepts": len(empty_concepts),
        },
        "sink_headings": dict(sink_headings.most_common()),
        "nomatch_headings": dict(no_match_headings.most_common()),
        "empty_by_theme": {k: v for k, v in empty_by_theme.items()},
    }
    if tom_concept:
        output["tom_analysis"] = {
            "total_infos": tom_concept["n_infos"],
            "legit": tom_legit,
            "foreign": tom_foreign,
            "precision_pct": tom_legit / max(1, tom_legit + tom_foreign) * 100,
            "headings": dict(tom_headings.most_common()),
        }

    with open("/data/diagnostic_locality.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info(f"\n  Résultats sauvegardés: /data/diagnostic_locality.json")


if __name__ == "__main__":
    main()
