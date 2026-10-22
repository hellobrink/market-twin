# Market twin

A prototype market digital twin for Brink. The first case is the NoFire Stop the Spread pilot in Brazil. The design is in the [Market Digital Twin: Prototype Spec](https://claude.ai/artifact/6hn6GXpxTLsz9Q56Yx15y6).

This first piece is the per-farm ROI model. For each type of farm, it estimates:

- what preventive treatment costs per dry season
- the fire loss and water cost it avoids
- how confident we can be in the result, given the ranges in the assumptions file

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python -m twin.report
.venv/bin/python -m twin.report --strategy alert
.venv/bin/pytest
```

## How it works

[assumptions/nofire_brazil.yaml](assumptions/nofire_brazil.yaml) holds every input as a low, base and high value. Each input also has a `status` that says where the number came from. Most are still placeholders, so replace them as NoFire's interview data and the public datasets come in, and update `status` when you do.

The file also lists treatment strategies, which describe how a farm decides when to treat. `scheduled` means treating on high-risk days all season, and `alert` means treating only when a fire alert comes in nearby. The gel lasts about 24 hours, so the strategy changes two things: how many treatments a farm pays for, and how many fires arrive while a treatment is still active. Each segment gives its own `applications_per_season` and `timing_coverage` for every strategy. A strategy can then reflect, for example, how long a drone operator takes to reach that kind of farm.

[twin/roi.py](twin/roi.py) contains the model, and its docstring sets out the equations. For each farm segment, the report puts the strategies side by side and prints:

- a base case that uses the middle value of every range
- the spread of ROI across 10,000 Monte Carlo runs, and the share of runs that clear the farmer's ROI hurdle
- the 5 inputs that move ROI most, which shows the team what to ask farmers about next
- the break-even product price per hectare per application

## Known simplifications

- The model looks at one season at a time. It doesn't calculate multi-year payback or apply discounting.
- It assumes a treated strip protects the whole area that would otherwise burn.
- Inputs are sampled independently. In reality, fire probability and burned area rise together in a drought year.
- Water savings only count where the farm already spends water on fire prevention.

## Farm population (step 2)

The twin builds one synthetic farm for every crop and livestock farm in the 2017 census for São Paulo (181,072 farms). It then runs the ROI model on each farm in the modelled market, under each fire scenario and treatment strategy.

```bash
.venv/bin/python -m twin.population_report
.venv/bin/python -m twin.population_report --scenario severe --strategy alert --top 15
```

The processed data in `data/processed/sp/` is committed, so the report runs offline. To download it again, or to pick different years:

```bash
.venv/bin/python -m twin.data.build --state SP --crop-year 2024 --hotspot-years 2015-2024 --land-cover-year 2020
```

The build caches about 760 MB of MapBiomas burned-area rasters in `data/raw/`, which is not committed. It streams only the São Paulo window of the land-cover raster.

| Data | Source | Used for |
| --- | --- | --- |
| Farm counts and area by municipality, activity and size group | IBGE Censo Agropecuário 2017, table 6754 | One synthetic farm per establishment, with an area drawn to match the census |
| Farms with trucks by municipality and size group | Censo Agropecuário 2017, table 6877 | Whether a small farm applies from the ground or needs a drone service |
| Sugarcane planted area and production value | IBGE PAM 2024, table 5457 | Which large crop farms grow cane, and cane value at risk per hectare |
| Burned area by land cover, about 30 m | MapBiomas Fogo collection 5.1, 2015 to 2024 | Each farm's fire risk |
| Land cover, about 30 m | MapBiomas collection 11, 2020 | Hectares of cane, pasture and other crops per municipality, to turn burned area into burn rates |
| Fire hotspots, reference satellite | INPE BDQueimadas, 2015 to 2024 | A cross-check on where MapBiomas says fires happen |

[twin/population.py](twin/population.py) explains each step. Farms are assigned to segments by these rules:

- Crop farms of 5 to 100 ha go to `smallholder_ground` if they have a truck, otherwise to `smallholder_drone`.
- Temporary-crop farms of 100 ha or more go to `sugarcane_ground`, with a probability equal to sugarcane's share of the municipality's crop area.
- Livestock farms of 500 ha or more go to `remote_ranch_drone`.
- Every other farm sits outside the modelled market.

IBGE suppresses area in census cells with few farms. The twin estimates those areas from each municipality's published total, so total synthetic farmland comes within 2% of the census.

### Fire risk

A farm's expected burned share each year is its municipality's burn rate for its land cover: cane for sugarcane farms, pasture for ranches, and other crops for smallholders. The burn rate is MapBiomas burned hectares divided by MapBiomas hectares of that land cover. Where a municipality has little of a land cover, the rate leans towards the state rate.

The ROI model splits that expected share into a chance of fire and a share burned when fire comes. The share is the segment's base value, so only the chance changes with the data.

The `fire_scenarios` section of the assumptions file sets which years the burn rates come from:

| Scenario | Years | Typical cane farm, burned a year |
| --- | --- | --- |
| `normal` | Mean of 2015 to 2023 | 0.40% |
| `severe` | 2024 | 3.86% |
| `long_run` | 90% normal, 10% severe | 0.86% |

2024 sits apart because it burned 458,000 ha of cane, more than 2015 to 2023 combined. At R$700/ha with alert treatment, 3 cane farms clear the ROI hurdle in a normal year, 2,663 in a severe year and 268 over the long run. At this price the product pays for itself in bad years, which points the NoFire team towards pricing it like insurance.

INPE hotspots stay in as a cross-check. They rank municipalities much as MapBiomas does, with rank correlations of 0.66 for normal years and 0.58 for 2024.

### Why the hotspot formula was dropped

The first version set fire probability to 1 - exp(-fires_per_hotspot x hotspot rate x farm area). [twin/calibration.py](twin/calibration.py) fits `fires_per_hotspot` against MapBiomas burned farmland, and it comes out at 0.07 for the mean year, against a placeholder of 3:

```bash
.venv/bin/python -m twin.calibration
```

The fit showed that the formula makes burning per hectare grow with farm size. Calibrated, farms over 2,500 ha held 32% of farmland but got 90% of predicted burning, at 2.2% a year. Farms of 100 to 500 ha got 0.06%. Burn rates from MapBiomas avoid that, because a farm's expected burned area scales with its area alone.

### Simplifications

- The census is from 2017, and the next one is not out yet.
- Land cover is from 2020 for every year, so it misses cane expanding or shrinking over the decade.
- Smallholders use the burn rate for crops other than cane, even where they are surrounded by cane.
- Only sugarcane farms get value at risk from data. The other segments use the segment's base value.
- Every input except area, fire risk and cane value uses the segment's base value, so the population report has no Monte Carlo ranges yet.

## Adoption over time (step 3)

```bash
.venv/bin/python -m twin.adoption_report
.venv/bin/python -m twin.adoption_report --price 300 --runs 500
```

[twin/adoption.py](twin/adoption.py) follows every farm in the modelled market through 10 seasons from 2027, 200 times. Each run draws every uncertain input from its range, gives each farm its own ROI hurdle, and decides which farms belong to a cooperative. Then, each season:

1. A farm judges its ROI on its perceived fire risk. That sits between its municipality's normal-year and severe-year burn rates: it jumps to the severe rate after a severe season and fades with `risk_memory_half_life`.
2. Farms whose perceived ROI clears their hurdle adopt with the Bass chance 1 - (1 - p) x (1 - q x peer share). A cooperative member's peers are the other members in its municipality. A non-member feels the whole municipality, weighted by `non_member_peer_weight`.
3. Adopters whose perceived ROI falls below their hurdle may stop.
4. The season turns out severe with `severe_year_probability`, which is 10% by default because 1 of the 10 seasons from 2015 to 2024 was.

The report shows the P10, median and P90 of adopters and revenue each year. It also shows how many adopters cooperative and neighbour effects add, which drawn inputs move the result most, and where adopters cluster. `--price` fixes the product price, so pricing options can be compared.

With the current assumptions and alert treatment:

| Price per ha per application | Median adopters, 2036 | P90 adopters, 2036 | Median revenue, 2036 | Added by peer effects |
| --- | --- | --- | --- | --- |
| Drawn from R$300 to R$1,500 (base R$700) | 86 | 406 | R$5.1m | 86 against 64 without |
| R$300 | 274 | 956 | R$4.7m | 274 against 180 without |

Nearly all adopters are sugarcane farms around Pitangueiras, Olímpia, Jaboticabal and Sertãozinho. The biggest single driver is whether a severe season happens during the run. Price, containment rate and how long farmers remember a bad year come next. At R$300, about 3 times as many farms adopt, but revenue stays about the same, so a lower price widens reach without growing the business.

Cooperative membership shares, the Bass rates, risk memory and churn are all placeholders. Membership by municipality and farm size can come from Censo Agropecuário table 6846, but IBGE was unreachable when this was built.

## Next

- Fill cooperative membership from census table 6846.
- Add pricing models beyond a price per hectare, such as a season subscription or a payment linked to insurance, and compare them with `--price`.
- Show adoption on a map for coaching sessions, for example in a Streamlit app.
