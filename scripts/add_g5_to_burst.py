"""Ajoute g5.2xlarge + g5.xlarge (NVIDIA A10G 24GB) aux LaunchSpecifications du
SpotFleet burst, en dupliquant VERBATIM le bloc g6.xlarge (même AMI/UserData :
le driver NVIDIA + vLLM + TEI tournent à l'identique sur A10G et L4).

Motif : le spot g6 (L4) est en pénurie générale (score AWS 3/10 partout) ; en
ajoutant g5 (A10G), le score de fulfillment monte à 7-9/10. g5 ≈ g6 en capacité
(24GB VRAM, bande passante mémoire supérieure), ~30-45% plus cher en spot mais
disponible. Ce N'EST PAS g6e (l'instance chère à éviter).

Idempotent : ne fait rien si g5 est déjà présent.
"""
from pathlib import Path

F = Path("src/knowbase/ingestion/burst/cloudformation/burst-spot.yaml")
text = F.read_text(encoding="utf-8")
lines = text.split("\n")

if any("InstanceType: g5." in l for l in lines):
    print("g5 déjà présent — rien à faire.")
    raise SystemExit(0)

# Bornes du bloc g6.xlarge : de "- InstanceType: g6.xlarge" jusqu'à juste avant "Outputs:"
start = next(i for i, l in enumerate(lines) if l.strip() == "- InstanceType: g6.xlarge")
end = next(i for i, l in enumerate(lines) if l.startswith("Outputs:"))
block = lines[start:end]
while block and block[-1].strip() == "":
    block.pop()  # retire les lignes vides de fin

def variant(itype: str) -> list[str]:
    out = [
        "          # ================================================================",
        f"          # {itype} - NVIDIA A10G 24GB (fallback si g6/L4 en penurie spot)",
        "          # Meme 24GB VRAM que L4, bande passante superieure - ideal vLLM/TEI",
        "          # ================================================================",
    ]
    for l in block:
        # Seules occurrences de g6.xlarge dans le bloc : la ligne InstanceType + l'echo bootstrap
        out.append(l.replace("g6.xlarge", itype))
    return out

g5_2x = variant("g5.2xlarge")
g5_x = variant("g5.xlarge")

new_lines = lines[:end] + [""] + g5_2x + [""] + g5_x + [""] + lines[end:]
F.write_text("\n".join(new_lines), encoding="utf-8")

# Contrôles
n_specs = sum(1 for l in new_lines if l.strip().startswith("- InstanceType:"))
print(f"OK — bloc g6.xlarge dupliqué en g5.2xlarge + g5.xlarge.")
print(f"InstanceType déclarés : {n_specs} (attendu 4 : g6.2xlarge, g6.xlarge, g5.2xlarge, g5.xlarge)")
for l in new_lines:
    if l.strip().startswith("- InstanceType:"):
        print("  ", l.strip())
