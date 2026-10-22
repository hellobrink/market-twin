"""IBGE category codes used by the population builder."""

STATES = {
    "SP": {"ibge_code": 35, "name": "São Paulo"},
}

# Censo Agropecuário 2017, classification 220 "Grupos de área total": code -> (low ha, high ha).
# The top group has no upper bound.
AREA_GROUPS: dict[int, tuple[float, float | None]] = {
    111543: (0, 0.1),
    111544: (0.1, 0.2),
    111545: (0.2, 0.5),
    111546: (0.5, 1),
    111547: (1, 2),
    111548: (2, 3),
    111549: (3, 4),
    111550: (4, 5),
    111551: (5, 10),
    111552: (10, 20),
    111553: (20, 50),
    111554: (50, 100),
    111555: (100, 200),
    111556: (200, 500),
    111557: (500, 1_000),
    111558: (1_000, 2_500),
    41139: (2_500, 10_000),
    40645: (10_000, None),
}
AREA_GROUP_TOTAL = 110085

# Classification 12517 "Grupos de atividade econômica": the groups the twin can sell to.
ACTIVITIES = {
    111519: "temporary_crops",
    111520: "horticulture",
    111521: "permanent_crops",
    111523: "livestock",
}
ACTIVITY_TOTAL = 113601

# PAM (table 5457), classification 782 product codes.
CROP_ALL = 0
CROP_SUGARCANE = 40106
