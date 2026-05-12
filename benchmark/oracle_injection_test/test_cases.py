"""
20 cas ABSTENTION_FAUX_NEG sélectionnés depuis l'oracle Claude.

Pour chaque question, on fournit :
- question (texte verbatim du bench)
- expected_answer (issu de l'oracle Claude / ground truth)
- doc_ids (liste des docs où l'info se trouve, vérifié via grep)
- search_terms (keywords pour extraire les chunks pertinents du cache full_text)
- bench_source (origine : ragas / robustness)

Hypothèse testée : si on injecte ces chunks dans la synthèse, OSMOSIS répond-il correctement ?
- Si OUI → le pipeline retrieval/filter laisse passer ces chunks aux oubliettes (bug retrieval)
- Si NON → la synthèse même bien nourrie produit une mauvaise réponse (bug synthèse)
"""

TEST_CASES = [
    # ─── RAGAS T1 Provenance — questions factuelles précises ────────────────
    {
        "qid": "rag_T1_3",
        "bench_source": "ragas",
        "question": "Combien de jours ouvrables est l'extension maximale du délai d'évaluation prévue par le règlement 2021/821 ?",
        "expected": "30 jours ouvrables",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["30 days", "thirty days", "extension", "evaluation"],
    },
    {
        "qid": "rag_T1_6",
        "bench_source": "ragas",
        "question": "Comment le règlement 2021/821 définit-il la 'global export authorisation' ?",
        "expected": "individual export authorisation or a global export authorisation granted to one specific exporter for a type or category of dual-use items",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["global export authorisation", "global authorisation"],
    },
    {
        "qid": "rag_T1_10",
        "bench_source": "ragas",
        "question": "Quels règlements de protection des données personnelles sont référencés dans le règlement 2021/821 ?",
        "expected": "Reg 2016/679 (RGPD) et 2018/1725",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["2016/679", "2018/1725", "personal data"],
    },
    {
        "qid": "rag_T1_14",
        "bench_source": "ragas",
        "question": "Selon l'Article 3 du règlement 2021/821, qu'est-ce qui est requis pour exporter un item dual-use ?",
        "expected": "Une autorisation est requise pour l'exportation des items dual-use listés en Annex I",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["Article 3", "authorisation shall be required", "An authorisation"],
    },
    {
        "qid": "rag_T1_25",
        "bench_source": "ragas",
        "question": "Selon l'Article 8 du règlement 2021/821, quelle autorité est compétente pour les services de courtage et l'assistance technique ?",
        "expected": "L'autorité de l'État membre où le courtier ou fournisseur d'assistance technique est résident/établi",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["Article 8", "broker", "technical assistance", "Member State where"],
    },

    # ─── Robustness temporal_evolution — questions de mapping date→version ─
    {
        "qid": "rob_q_25",
        "bench_source": "robustness",
        "question": "Quelle régulation EU dual-use était applicable en mars 2020 ?",
        "expected": "Le règlement 428/2009 (encore en vigueur jusqu'à septembre 2021, où il a été remplacé par le règlement 2021/821)",
        "doc_ids": ["dualuse_reg_428_2009_original_372b7ac3", "dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["428/2009", "Council Regulation", "5 May 2009", "repeal"],
    },
    {
        "qid": "rob_q_30",
        "bench_source": "robustness",
        "question": "Le règlement 428/2009 était-il en vigueur le 1er janvier 2022 ?",
        "expected": "Non — le 428/2009 a été abrogé par le 2021/821 entré en vigueur le 9 septembre 2021",
        "doc_ids": ["dualuse_reg_428_2009_original_372b7ac3", "dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["428/2009", "Regulation (EC) No 428/2009 is repealed", "shall be repealed", "9 September 2021", "entry into force"],
    },
    {
        "qid": "rob_q_29",
        "bench_source": "robustness",
        "question": "Quel CS-25 amdt s'applique à un dossier ouvert le 31 décembre 2023 ?",
        "expected": "Amendment 28 (entré en vigueur le 15 décembre 2023)",
        "doc_ids": ["cs25_amdt_28_32f1a9ac"],
        "search_terms": ["Amendment 28", "ED Decision 2023/021/R", "15 December 2023", "entry into force"],
    },
    {
        "qid": "rob_q_34",
        "bench_source": "robustness",
        "question": "Quel délégué dual-use était applicable juste avant la publication du 2024/2547 ?",
        "expected": "Le règlement délégué 2023/996 du 23 février 2023",
        "doc_ids": ["dualuse_del_2023_996_3616a044", "dualuse_del_2024_2547_cb08f84b"],
        "search_terms": ["2023/996", "23 February 2023", "Commission Delegated Regulation"],
    },

    # ─── Robustness causal_why — pourquoi questions ─────────────────────────
    {
        "qid": "rob_q_36",
        "bench_source": "robustness",
        "question": "Pourquoi le règlement 2021/821 a-t-il abrogé le 428/2009 ?",
        "expected": "Pour moderniser et renforcer le contrôle (élargir le scope, inclure tech assistance, surveillance digitale)",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["should be replaced", "modernise", "Regulation (EC) No 428/2009 should be replaced", "experience gained", "developments"],
    },
    {
        "qid": "rob_q_40",
        "bench_source": "robustness",
        "question": "Pourquoi le règlement 2021/821 exige-t-il que la terminologie soit cohérente avec celle du règlement 952/2013 (Code des douanes) ?",
        "expected": "Pour assurer la cohérence avec le code douanier de l'Union utilisé par les autorités douanières lors des contrôles",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["952/2013", "Union Customs Code", "consistent with the definitions"],
    },
    {
        "qid": "rob_q_45",
        "bench_source": "robustness",
        "question": "Pourquoi le règlement 2021/821 limite-t-il l'extension du délai d'évaluation à 30 jours ouvrables ?",
        "expected": "Pour équilibrer rapidité et possibilité d'investigation approfondie",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["30 days", "extension", "additional period", "thirty days", "additional 30"],
    },

    # ─── Robustness conditional ─────────────────────────────────────────────
    {
        "qid": "rob_q_109",
        "bench_source": "robustness",
        "question": "Si un courtier basé hors UE veut fournir des services de courtage dual-use, quelle juridiction est compétente ?",
        "expected": "Article 6 — l'État membre où l'item est physiquement situé ou destiné",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["broker", "brokering services", "Article 6", "natural or legal person", "third country"],
    },
    {
        "qid": "rob_q_114",
        "bench_source": "robustness",
        "question": "Si un fournisseur de technical assistance est aware que le receveur va utiliser l'aide pour produire un item de l'Annex I, que doit-il faire ?",
        "expected": "Obtenir une autorisation auprès de l'autorité compétente avant de fournir l'assistance technique",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["technical assistance", "is aware", "intended", "shall be required", "authorisation"],
    },

    # ─── Robustness multi_hop ───────────────────────────────────────────────
    {
        "qid": "rob_q_85",
        "bench_source": "robustness",
        "question": "Un fournisseur de technical assistance basé en Allemagne s'aperçoit que son client en pays tiers utilise les conseils pour produire un item de l'Annex I dual-use. Quelle est sa cascade d'obligations ?",
        "expected": "Article 8 — informer l'autorité compétente allemande, obtenir une autorisation",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["Article 8", "technical assistance", "is aware", "shall inform", "competent authority"],
    },
    {
        "qid": "rob_q_88",
        "bench_source": "robustness",
        "question": "Pour répondre 'Quelle est la valeur d'énergie d'impact à appliquer aujourd'hui pour un grand item en verre, et pourquoi une valeur plus faible apparaît dans le KG ?', quel raisonnement OSMOSIS V2 doit-il dérouler ?",
        "expected": "Aujourd'hui = 21J (CS-25 amdt 28 actif). 3.5J dans amdt 26 = lifecycle EVOLVES_FROM, pas contradiction",
        "doc_ids": ["cs25_amdt_28_32f1a9ac", "cs25_amdt_26_6450b31e"],
        "search_terms": ["21 J", "3.5 J", "large glass", "impact energy", "51mm", "ball"],
    },

    # ─── Robustness anchor_scope_hierarchy ──────────────────────────────────
    {
        "qid": "rob_q_132",
        "bench_source": "robustness",
        "question": "L'Annex I du règlement 2021/821 et l'Annex IV (transferts intra-Union) ont-ils le même périmètre de couverture des items ?",
        "expected": "Non — Annex I = tous items dual-use export pays tiers (large), Annex IV = sous-ensemble pour transferts intra-Union (restreint)",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["Annex I", "Annex IV", "intra-Union transfer", "list of dual-use items"],
    },
    {
        "qid": "rob_q_137",
        "bench_source": "robustness",
        "question": "L'AMC 25.1322 et la CS 25.1322 ont-elles la même portée normative ?",
        "expected": "Non — CS = exigence normative obligatoire, AMC = méthode acceptable de conformité (non obligatoire)",
        "doc_ids": ["cs25_amdt_26_6450b31e", "cs25_amdt_28_32f1a9ac"],
        "search_terms": ["AMC", "CS 25.1322", "Acceptable Means of Compliance", "Certification Specification"],
    },

    # ─── Robustness lifecycle_supersedes ────────────────────────────────────
    {
        "qid": "rob_q_120",
        "bench_source": "robustness",
        "question": "Quel règlement a remplacé le règlement (CE) n° 428/2009 du Conseil ?",
        "expected": "Le règlement (UE) 2021/821 du Parlement européen et du Conseil du 20 mai 2021",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["Regulation (EC) No 428/2009 is repealed", "shall be repealed", "replaced", "428/2009"],
    },
    {
        "qid": "rob_q_153",
        "bench_source": "robustness",
        "question": "Le règlement (UE) 2021/821 abroge-t-il en totalité ou partiellement le règlement 428/2009 ?",
        "expected": "Totalement (Article 41 — repeal complet)",
        "doc_ids": ["dualuse_reg_2021_821_original_65eef5dc"],
        "search_terms": ["Article 41", "Repeal", "Regulation (EC) No 428/2009 is repealed", "shall be repealed"],
    },
]

assert len(TEST_CASES) == 20, f"Expected 20 cases, got {len(TEST_CASES)}"
