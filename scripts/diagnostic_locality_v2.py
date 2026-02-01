"""
OSMOSE — Diagnostic Localité Macro <-> Micro (V2)
===================================================
Étape 1: Vérifier si le désalignement macro/micro est exploitable.

V2: Corrigé pour utiliser Information.docitem_id (pas InformationMVP.anchor_docitem_ids)
    et tous les HEADING (heading_level=None dans ce PDF = slide deck).
"""

import json
import logging
import math
import os
from collections import Counter, defaultdict
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CACHE_PATH = "/data/extraction_cache/363f5357dfe38242a968415f643eff1edca39866d7e714bcb9ea5606cece5359.v5cache.json"


def load_docitems_from_cache():
    """Charge les DocItems du cache v5 avec page_no."""
    with open(CACHE_PATH, "r", encoding="utf-8") as f:
        cache = json.load(f)

    items = cache.get("extraction", {}).get("stats", {}).get("structural_graph", {}).get("items", [])

    docitems = {}
    for item in items:
        item_id = item.get("item_id", "")
        docitems[item_id] = {
            "item_id": item_id,
            "item_type": item.get("item_type", ""),
            "text": item.get("text", "")[:200],
            "page_no": item.get("page_no", 0),
        }

    logger.info(f"[Cache] {len(docitems)} DocItems chargés")
    return docitems


def load_neo4j_data():
    """Charge themes, concepts, informations depuis Neo4j."""
    from neo4j import GraphDatabase

    neo4j_host = os.environ.get("NEO4J_HOST", "knowbase-neo4j")
    driver = GraphDatabase.driver(f"bolt://{neo4j_host}:7687", auth=("neo4j", "graphiti_neo4j_pass"))

    data = {}

    with driver.session() as session:
        # Themes
        result = session.run("MATCH (t:Theme) RETURN t.theme_id AS id, t.name AS name")
        data["themes"] = {r["id"]: r["name"] for r in result}

        # Concepts avec theme et info count
        result = session.run("""
            MATCH (t:Theme)-[:HAS_CONCEPT]->(c:Concept)
            OPTIONAL MATCH (c)-[:HAS_INFORMATION]->(i:Information)
            RETURN c.concept_id AS id, c.name AS name, c.role AS role,
                   t.theme_id AS theme_id, t.name AS theme_name,
                   count(i) AS n_infos
        """)
        data["concepts"] = [dict(r) for r in result]

        # Informations via Concept -> Information (avec docitem_id pour page)
        result = session.run("""
            MATCH (c:Concept)-[:HAS_INFORMATION]->(i:Information)
            RETURN i.info_id AS info_id, i.text AS text, i.type AS type,
                   i.docitem_id AS docitem_id,
                   c.concept_id AS concept_id, c.name AS concept_name,
                   c.role AS concept_role
        """)
        data["informations"] = [dict(r) for r in result]

        # SINK informations spécifiquement
        result = session.run("""
            MATCH (c:Concept {role: 'SINK'})-[:HAS_INFORMATION]->(i:Information)
            RETURN i.info_id AS info_id, i.text AS text, i.docitem_id AS docitem_id
        """)
        data["sink_infos"] = [dict(r) for r in result]

        # Assertion logs (REJECTED / ABSTAINED)
        result = session.run("""
            MATCH (al:AssertionLog)
            WHERE al.status IN ['ABSTAINED', 'REJECTED']
            RETURN al.assertion_id AS id, al.text AS text, al.type AS type,
                   al.status AS status, al.reason AS reason,
                   al.concept_id AS concept_id
        """)
        data["failed_assertions"] = [dict(r) for r in result]

    driver.close()

    logger.info(
        f"[Neo4j] {len(data['themes'])} themes, {len(data['concepts'])} concepts, "
        f"{len(data['informations'])} infos, {len(data['sink_infos'])} SINK infos, "
        f"{len(data['failed_assertions'])} failed assertions"
    )
    return data


def build_page_heading_map(docitems):
    """
    Construit une map page → heading le plus récent.
    Pour un slide deck, chaque slide a un heading = titre du slide.
    """
    sorted_items = sorted(docitems.values(), key=lambda d: (d["page_no"], d.get("item_id", "")))

    page_heading = {}
    current_heading = "(no heading)"

    for item in sorted_items:
        # Tous les HEADING (pas de filtre heading_level — None dans ce PDF)
        if item["item_type"] == "HEADING":
            text = item["text"].strip()
            if len(text) > 3:  # Ignorer les headings triviaux
                current_heading = text[:80]
        page_heading[item["page_no"]] = current_heading

    unique_headings = len(set(page_heading.values()))
    logger.info(f"[Sections] {unique_headings} headings distincts sur {len(page_heading)} pages")
    return page_heading


def docitem_id_to_page(docitem_id, docitems):
    """
    Extrait le page_no depuis un docitem_id Neo4j.
    Format: 'default:doc_name:#/texts/103' → item_id = '#/texts/103'
    """
    if not docitem_id:
        return None
    # Le item_id dans le cache est la partie après le dernier ':'
    # Format: "default:020_RISE_..._363f5357:#/texts/103"
    # On veut "#/texts/103"
    idx = docitem_id.find("#/")
    if idx >= 0:
        item_id = docitem_id[idx:]
    else:
        item_id = docitem_id.split(":")[-1]

    item = docitems.get(item_id)
    if item:
        return item["page_no"]
    return None


def main():
    logger.info("=" * 70)
    logger.info("[DIAGNOSTIC LOCALITÉ V2] Étape 1 — Faisabilité")
    logger.info("=" * 70)

    # 1. Charger les données
    docitems = load_docitems_from_cache()
    neo = load_neo4j_data()
    page_heading = build_page_heading_map(docitems)

    # 2. Mapper informations → pages (via Information.docitem_id)
    info_page = {}
    for info in neo["informations"]:
        page = docitem_id_to_page(info.get("docitem_id"), docitems)
        if page is not None:
            info_page[info["info_id"]] = page

    logger.info(f"[Mapping] {len(info_page)}/{len(neo['informations'])} infos avec page résolue")

    # 3. Concept → pages (via ses informations)
    concept_pages = defaultdict(set)
    concept_headings = defaultdict(Counter)
    for info in neo["informations"]:
        cid = info.get("concept_id")
        page = info_page.get(info.get("info_id"))
        if cid and page is not None:
            concept_pages[cid].add(page)
            heading = page_heading.get(page, "(unknown)")
            concept_headings[cid][heading] += 1

    # 4. Classer les concepts
    empty_concepts = [c for c in neo["concepts"] if c["n_infos"] == 0 and c["role"] != "SINK"]
    populated_concepts = [c for c in neo["concepts"] if c["n_infos"] > 0 and c["role"] != "SINK"]
    sink_concept = next((c for c in neo["concepts"] if c["role"] == "SINK"), None)

    logger.info(f"[Concepts] {len(populated_concepts)} peuplés, {len(empty_concepts)} vides, SINK={'oui' if sink_concept else 'non'}")

    # 5. MATRICE: Theme → Concept → Pages → Headings
    print()
    print("=" * 70)
    print("[MATRICE] Theme → Concept → Pages/Headings")
    print("=" * 70)

    themes_concepts = defaultdict(list)
    for c in neo["concepts"]:
        if c["role"] != "SINK":
            themes_concepts[c["theme_name"]].append(c)

    for theme_name in sorted(themes_concepts.keys()):
        concepts = themes_concepts[theme_name]
        print(f"\n  THEME: {theme_name}")
        for c in sorted(concepts, key=lambda x: -x["n_infos"]):
            pages = sorted(concept_pages.get(c["id"], set()))
            headings = concept_headings.get(c["id"], Counter())
            top_heading = headings.most_common(1)[0][0] if headings else "-"
            status = f"{c['n_infos']} infos" if c["n_infos"] > 0 else "VIDE"
            page_range = f"p{min(pages)}-{max(pages)}" if pages else "p?"
            marker = "OK" if c["n_infos"] > 0 else "XX"
            print(f"    [{marker}] {c['name']:<55s} [{status:>8s}] {page_range:<10s} → {top_heading[:50]}")

    # 6. SINK — pages et headings sources
    print()
    print("=" * 70)
    print("[SINK] Provenance des assertions SINK")
    print("=" * 70)

    sink_headings = Counter()
    sink_pages = Counter()
    for info in neo["sink_infos"]:
        page = docitem_id_to_page(info.get("docitem_id"), docitems)
        if page is not None:
            sink_pages[page] += 1
            heading = page_heading.get(page, "(unknown)")
            sink_headings[heading] += 1

    print(f"  SINK total avec page: {sum(sink_pages.values())}/{len(neo['sink_infos'])}")
    for heading, cnt in sink_headings.most_common(15):
        print(f"  SINK heading: {heading:<60s} ({cnt} infos)")

    # 7. no_concept_match — localisation par text matching
    print()
    print("=" * 70)
    print("[NO_CONCEPT_MATCH] Assertions non liées")
    print("=" * 70)

    no_match = [a for a in neo["failed_assertions"] if a.get("reason") == "no_concept_match"]
    print(f"  Total no_concept_match: {len(no_match)}")

    # Localiser par recherche de substring dans les DocItems
    assertion_page_map = {}
    for assertion in no_match:
        atext = (assertion.get("text") or "")[:50].lower().strip()
        if not atext or len(atext) < 15:
            continue
        for item in docitems.values():
            if atext[:25] in item["text"][:200].lower():
                assertion_page_map[assertion["id"]] = item["page_no"]
                break

    print(f"  Assertions localisées: {len(assertion_page_map)}/{len(no_match)}")

    no_match_headings = Counter()
    for aid, page in assertion_page_map.items():
        heading = page_heading.get(page, "(unknown)")
        no_match_headings[heading] += 1

    for heading, cnt in no_match_headings.most_common(15):
        print(f"  no_match heading: {heading:<60s} ({cnt} assertions)")

    # 8. QUESTION CLÉ: overlap mal-routées ↔ concepts vides
    print()
    print("=" * 70)
    print("[QUESTION CLÉ] Overlap SINK/no_match ↔ concepts vides")
    print("=" * 70)

    empty_by_theme = defaultdict(list)
    for c in empty_concepts:
        empty_by_theme[c["theme_name"]].append(c["name"])

    print("\n  Thèmes avec concepts vides:")
    for theme, cnames in sorted(empty_by_theme.items()):
        print(f"    {theme}: {', '.join(cnames)}")

    def heading_matches(heading, theme_name, concept_names):
        """Check si un heading correspond à un thème/concept via mots-clés."""
        h = heading.lower()
        for word in theme_name.lower().split():
            if len(word) >= 4 and word in h:
                return True
        for cname in concept_names:
            for word in cname.lower().split():
                if len(word) >= 4 and word in h:
                    return True
        return False

    # SINK → thèmes vides
    print("\n  [SINK → thèmes vides]")
    sink_matching_empty = 0
    sink_total = sum(sink_headings.values())
    for heading, cnt in sink_headings.items():
        for theme, cnames in empty_by_theme.items():
            if heading_matches(heading, theme, cnames):
                sink_matching_empty += cnt
                print(f"  MATCH SINK '{heading}' ({cnt}) → thème vide '{theme}'")
                break

    # no_match → thèmes vides
    print("\n  [no_match → thèmes vides]")
    nomatch_matching_empty = 0
    nomatch_total = sum(no_match_headings.values())
    for heading, cnt in no_match_headings.items():
        for theme, cnames in empty_by_theme.items():
            if heading_matches(heading, theme, cnames):
                nomatch_matching_empty += cnt
                print(f"  MATCH no_match '{heading}' ({cnt}) → thème vide '{theme}'")
                break

    # 9. ASPIRATEUR TOM
    print()
    print("=" * 70)
    print("[ASPIRATEUR] Analyse 'Technical Organisational Measures'")
    print("=" * 70)

    tom_concept = next((c for c in neo["concepts"] if "Technical Organi" in c.get("name", "")), None)
    tom_legit = 0
    tom_foreign = 0
    if tom_concept:
        tom_headings = Counter()
        for info in neo["informations"]:
            if info.get("concept_id") == tom_concept["id"]:
                page = info_page.get(info["info_id"])
                if page is not None:
                    tom_headings[page_heading.get(page, "(unknown)")] += 1

        tom_pages = sorted(concept_pages.get(tom_concept["id"], set()))
        print(f"  TOM: {tom_concept['n_infos']} infos, pages={tom_pages}")
        print(f"  Headings sources:")
        for heading, cnt in tom_headings.most_common():
            print(f"    {heading:<60s} ({cnt} infos)")

        for heading, cnt in tom_headings.items():
            h = heading.lower()
            if any(w in h for w in ["technical", "organi", "measure", "tom "]):
                tom_legit += cnt
            else:
                tom_foreign += cnt
        total_tom = tom_legit + tom_foreign
        print(f"\n  TOM precision: {tom_legit}/{total_tom} légitimes ({tom_legit / max(1, total_tom) * 100:.0f}%)")
        print(f"  TOM aspirées d'ailleurs: {tom_foreign}")

    # 10. DISPERSION: Gini des informations par concept
    print()
    print("=" * 70)
    print("[GINI] Distribution des informations par concept")
    print("=" * 70)

    infos_per_concept = sorted([c["n_infos"] for c in neo["concepts"] if c["role"] != "SINK"], reverse=True)
    total_infos = sum(infos_per_concept)
    n_concepts = len(infos_per_concept)

    print(f"  Top 5: {infos_per_concept[:5]}")
    print(f"  Bottom 5: {infos_per_concept[-5:]}")
    top3_share = sum(infos_per_concept[:3]) / max(1, total_infos)
    print(f"  Top 3 concepts = {top3_share * 100:.0f}% des infos")
    non_zero = sum(1 for x in infos_per_concept if x > 0)
    print(f"  Concepts peuplés: {non_zero}/{n_concepts} ({non_zero / max(1, n_concepts) * 100:.0f}%)")

    # Page spread par concept (nombre de pages uniques)
    print("\n  Page spread (concepts peuplés):")
    for c in sorted(populated_concepts, key=lambda x: -x["n_infos"])[:10]:
        pages = concept_pages.get(c["id"], set())
        print(f"    {c['name']:<55s} {c['n_infos']:>3d} infos, {len(pages):>3d} pages")

    # 11. VERDICT
    print()
    print("=" * 70)
    print("[VERDICT] Faisabilité localité")
    print("=" * 70)

    print(f"  SINK total (avec page): {sink_total}")
    print(f"  SINK → thèmes vides: {sink_matching_empty} ({sink_matching_empty / max(1, sink_total) * 100:.0f}%)")
    print(f"  no_concept_match localisé: {nomatch_total}")
    print(f"  no_match → thèmes vides: {nomatch_matching_empty} ({nomatch_matching_empty / max(1, nomatch_total) * 100:.0f}%)")

    combined = sink_matching_empty + nomatch_matching_empty
    combined_total = sink_total + nomatch_total

    print(f"\n  COMBINED: {combined}/{combined_total} ({combined / max(1, combined_total) * 100:.0f}%) des mal-routées → thèmes avec concepts vides")

    if combined / max(1, combined_total) >= 0.4:
        print("  >>> LOCALITÉ EXPLOITABLE — un signal de section améliorerait le routage")
    elif combined / max(1, combined_total) >= 0.2:
        print("  >>> LOCALITÉ PARTIELLE — signal utile mais pas suffisant seul")
    else:
        print("  >>> LOCALITÉ FAIBLE — le problème est ailleurs (linking sémantique, ontologie)")

    # 12. Sauvegarder
    output = {
        "date": datetime.now().isoformat(),
        "version": "v2",
        "metrics": {
            "sink_total": sink_total,
            "sink_matching_empty_themes": sink_matching_empty,
            "nomatch_total": nomatch_total,
            "nomatch_matching_empty_themes": nomatch_matching_empty,
            "combined_ratio": combined / max(1, combined_total),
            "populated_concepts": len(populated_concepts),
            "empty_concepts": len(empty_concepts),
            "top3_share": top3_share,
            "concepts_non_zero": non_zero,
            "concepts_total": n_concepts,
        },
        "sink_headings": dict(sink_headings.most_common()),
        "nomatch_headings": dict(no_match_headings.most_common()),
        "empty_by_theme": dict(empty_by_theme),
    }
    if tom_concept:
        output["tom_analysis"] = {
            "total_infos": tom_concept["n_infos"],
            "legit": tom_legit,
            "foreign": tom_foreign,
            "precision_pct": tom_legit / max(1, tom_legit + tom_foreign) * 100,
            "headings": dict(tom_headings.most_common()),
        }

    with open("/data/diagnostic_locality_v2.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nRésultats sauvegardés: /data/diagnostic_locality_v2.json")


if __name__ == "__main__":
    main()
