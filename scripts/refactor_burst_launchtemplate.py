"""Refactore burst-spot.yaml : LaunchSpecifications (4x UserData dupliqué, 65 Ko,
> limite 51200 octets de CloudFormation TemplateBody) -> LaunchTemplate + Overrides
(UN seul UserData, ~22 Ko, validable via l'API AWS).

Constat : les 4 blocs LaunchSpecification portaient chacun ~12-20 Ko de UserData.
Le bloc g6.2xlarge était l'ANCIENNE version verbeuse ; les 3 autres (g6.xlarge +
mes copies g5) la version COMPACTE et récente — fonctionnellement identiques
(Docker + NVIDIA + vLLM AWQ Marlin + TEI + health endpoint avec détection spot).

Le refactor :
  - 1 AWS::EC2::LaunchTemplate = config commune (AMI, EBS 200Go, ENI+SG, IAM,
    tags) + l'UserData COMPACT unique (extrait verbatim du bloc g6.xlarge).
  - SpotFleet : LaunchTemplateConfigs avec Overrides = les 4 InstanceType
    (g6.2xlarge, g6.xlarge, g5.2xlarge, g5.xlarge). Ajouter un type = 1 ligne.

Idempotent : ne fait rien si LaunchTemplate est déjà présent.
"""
from pathlib import Path

F = Path("src/knowbase/ingestion/burst/cloudformation/burst-spot.yaml")
lines = F.read_text(encoding="utf-8").split("\n")

if any("AWS::EC2::LaunchTemplate" in l for l in lines):
    print("LaunchTemplate déjà présent — rien à faire.")
    raise SystemExit(0)

idx = [i for i, l in enumerate(lines) if l.strip().startswith("- InstanceType:")]
outs = next(i for i, l in enumerate(lines) if l.startswith("Outputs:"))
assert len(idx) >= 2, "structure inattendue"

# --- Extraire l'UserData COMPACT (bloc g6.xlarge = idx[1]..idx[2]) ---
g6x = lines[idx[1]:idx[2]]
u = next(j for j, l in enumerate(g6x) if l.strip() == "Fn::Base64: !Sub |")
content = g6x[u + 1:]
while content and content[-1].strip() == "":
    content.pop()
# Contenu à 16 espaces -> on retire 16, on remettra 12 (préserve l'indentation relative)
stripped = [(l[16:] if l.startswith(" " * 16) else l.lstrip()) if l.strip() else "" for l in content]
# Echo générique (le type réel vient des metadata, puisque l'UserData est partagé)
stripped = [
    l.replace(
        'echo "=== OSMOSE Burst Bootstrap (g6.xlarge) ==="',
        'echo "=== OSMOSE Burst Bootstrap ($(curl -s http://169.254.169.254/latest/meta-data/instance-type)) ==="',
    )
    for l in stripped
]
ud = ["            " + l if l else "" for l in stripped]  # contenu à 12 espaces

launch_template = [
    "",
    "  # ============================================================================",
    "  # Launch Template - config commune (g6 L4 / g5 A10G, 24GB). UN seul UserData.",
    "  # ============================================================================",
    "  BurstLaunchTemplate:",
    "    Type: AWS::EC2::LaunchTemplate",
    "    Properties:",
    '      LaunchTemplateName: !Sub "knowwhere-burst-lt-${BatchId}"',
    "      LaunchTemplateData:",
    "        ImageId: !Ref AmiId",
    "        KeyName: !Ref KeyName",
    "        BlockDeviceMappings:",
    "          - DeviceName: /dev/sda1",
    "            Ebs:",
    "              VolumeSize: 200",
    "              VolumeType: gp3",
    "              DeleteOnTermination: true",
    "        NetworkInterfaces:",
    "          - DeviceIndex: 0",
    "            SubnetId: subnet-3320d458",
    "            Groups:",
    "              - !GetAtt SecurityGroup.GroupId",
    "            AssociatePublicIpAddress: true",
    "            DeleteOnTermination: true",
    "        IamInstanceProfile:",
    "          Arn: !GetAtt InstanceProfile.Arn",
    "        TagSpecifications:",
    "          - ResourceType: instance",
    "            Tags:",
    "              - Key: Name",
    '                Value: !Sub "knowwhere-burst-${BatchId}"',
    "              - Key: Project",
    "                Value: KnowWhere",
    "        UserData:",
    "          Fn::Base64: !Sub |",
] + ud

spot_fleet = [
    "",
    "  # ============================================================================",
    "  # Spot Fleet - 4 pools de capacité (g6.2xlarge, g6.xlarge, g5.2xlarge, g5.xlarge)",
    "  # priceCapacityOptimized : meilleur compromis prix/dispo entre les pools.",
    "  # ============================================================================",
    "  SpotFleet:",
    "    Type: AWS::EC2::SpotFleet",
    "    Properties:",
    "      SpotFleetRequestConfigData:",
    "        IamFleetRole: !GetAtt SpotFleetRole.Arn",
    "        TargetCapacity: 1",
    "        AllocationStrategy: priceCapacityOptimized",
    "        Type: maintain",
    "        TerminateInstancesWithExpiration: true",
    "        SpotPrice: !Ref SpotMaxPrice",
    "        ReplaceUnhealthyInstances: true",
    "        LaunchTemplateConfigs:",
    "          - LaunchTemplateSpecification:",
    "              LaunchTemplateId: !Ref BurstLaunchTemplate",
    "              Version: !GetAtt BurstLaunchTemplate.LatestVersionNumber",
    "            Overrides:",
    "              - InstanceType: g6.2xlarge",
    "              - InstanceType: g6.xlarge",
    "              - InstanceType: g5.2xlarge",
    "              - InstanceType: g5.xlarge",
]

# --- Remplacer l'ancien resource SpotFleet (+ son bandeau de commentaire) ---
sf_start = next(i for i, l in enumerate(lines) if l.rstrip() == "  SpotFleet:")
hdr = sf_start
while hdr - 1 >= 0 and (lines[hdr - 1].startswith("  #") or lines[hdr - 1].strip() == ""):
    hdr -= 1

new = lines[:hdr] + launch_template + spot_fleet + ["", ""] + lines[outs:]
F.write_text("\n".join(new), encoding="utf-8")

nbytes = len("\n".join(new).encode("utf-8"))
print(f"OK — refactor LaunchTemplate appliqué. Taille : {nbytes} octets (limite 51200).")
print("UserData partagé :", len(ud), "lignes.")
