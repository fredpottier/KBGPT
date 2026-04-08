"""
Verifie si la meme compression des reponses se produit sur Robustness.
Compare V17_PREMISE_VERIF (02/04 pre-B7) vs POST_PerspectiveLayer (07/04 post-B7).
"""
import json
from statistics import mean, median

PRE_PATH = "/app/data/benchmark/results/robustness_run_20260402_140940_V17_PREMISE_VERIF.json"
POST_PATH = "/app/data/benchmark/results/robustness_run_20260407_131617_POST_PerspectiveLayer.json"


def get_samples(d):
    # try several keys
    for k in ("per_sample", "samples", "results"):
        if k in d and isinstance(d[k], list):
            return d[k]
    return []


def get_answer_length(s):
    for k in ("answer_length", "answer_len", "response_length"):
        if k in s and isinstance(s[k], (int, float)):
            return int(s[k])
    # fallback to len of answer field
    for k in ("answer", "response", "osmosis_answer"):
        if k in s and isinstance(s[k], str):
            return len(s[k])
    return None


def main():
    pre = json.load(open(PRE_PATH))
    post = json.load(open(POST_PATH))

    print("=== Structure ===")
    print(f"PRE top keys: {list(pre.keys())}")
    print(f"POST top keys: {list(post.keys())}")

    pre_samples = get_samples(pre)
    post_samples = get_samples(post)
    print(f"PRE samples: {len(pre_samples)}")
    print(f"POST samples: {len(post_samples)}")

    if pre_samples:
        print(f"Sample key example: {list(pre_samples[0].keys())[:15]}")

    # Try to match by question_id or question text
    def key_of(s):
        return s.get("question_id") or s.get("qid") or s.get("id") or s.get("question", "")[:80]

    pre_by = {key_of(s): s for s in pre_samples}
    post_by = {key_of(s): s for s in post_samples}

    common = sorted(set(pre_by.keys()) & set(post_by.keys()))
    print(f"Common: {len(common)}")

    if not common:
        # Print a few keys from each to diagnose
        print("No common keys. PRE sample keys:")
        for s in pre_samples[:3]:
            print(f"  {key_of(s)}")
        print("POST sample keys:")
        for s in post_samples[:3]:
            print(f"  {key_of(s)}")
        return

    pre_lens, post_lens = [], []
    for q in common:
        a = get_answer_length(pre_by[q])
        b = get_answer_length(post_by[q])
        if a is not None and b is not None:
            pre_lens.append(a)
            post_lens.append(b)

    print(f"Questions with valid lengths: {len(pre_lens)}")
    if not pre_lens:
        return

    print()
    print(f"{'':<12} {'PRE':>10} {'POST':>10} {'Delta':>10}")
    print(f"{'mean':<12} {mean(pre_lens):>10.0f} {mean(post_lens):>10.0f} {mean(post_lens)-mean(pre_lens):>+10.0f}")
    print(f"{'median':<12} {median(pre_lens):>10.0f} {median(post_lens):>10.0f} {median(post_lens)-median(pre_lens):>+10.0f}")
    print(f"{'min':<12} {min(pre_lens):>10} {min(post_lens):>10}")
    print(f"{'max':<12} {max(pre_lens):>10} {max(post_lens):>10}")
    ratio = mean(post_lens) / mean(pre_lens) if mean(pre_lens) > 0 else 0
    print()
    print(f"Ratio POST/PRE : {ratio:.3f} ({(1-ratio)*100:+.1f}% de compression)")

    shorter = sum(1 for a, b in zip(pre_lens, post_lens) if b < a)
    longer = sum(1 for a, b in zip(pre_lens, post_lens) if b > a)
    print(f"Questions plus courtes POST : {shorter} ({100*shorter/len(pre_lens):.1f}%)")
    print(f"Questions plus longues POST : {longer} ({100*longer/len(pre_lens):.1f}%)")

    # Par categorie si disponible
    cats = set()
    for s in pre_samples:
        cat = s.get("category") or s.get("question_type") or s.get("task_type") or s.get("type")
        if cat:
            cats.add(cat)
    if cats:
        print()
        print("=== Par categorie ===")
        for cat in sorted(cats):
            cat_keys = [
                key_of(s) for s in pre_samples
                if (s.get("category") or s.get("question_type") or s.get("task_type") or s.get("type")) == cat
            ]
            pre_c = [get_answer_length(pre_by[k]) for k in cat_keys if k in pre_by]
            post_c = [get_answer_length(post_by[k]) for k in cat_keys if k in post_by]
            pre_c = [x for x in pre_c if x is not None]
            post_c = [x for x in post_c if x is not None]
            if pre_c and post_c:
                delta = mean(post_c) - mean(pre_c)
                print(f"  {cat:<30} n={len(cat_keys):>3} PRE={mean(pre_c):>6.0f} POST={mean(post_c):>6.0f} delta={delta:>+6.0f}")


if __name__ == "__main__":
    main()
