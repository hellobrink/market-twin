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

## Coaching app (step 4)

```bash
.venv/bin/streamlit run app.py
```

This opens the app at http://localhost:8501. The sidebar holds the levers: treatment strategy, price, containment rate and the farmer's ROI hurdle, plus an "Adoption over time" panel with the chance of a severe season, how long farmers remember one, the Bass rates, cooperative membership for cane farms and the number of runs. A lever moved away from its default is fixed at that value, and every other input keeps its range in the Monte Carlo runs. The sidebar lists what is fixed.

The app has 4 tabs:

- **Market today**: who would buy under a chosen fire scenario, by segment, with a map of buyers by municipality.
- **Adoption over time**: users and revenue each year as a median with a P10 to P90 band, how many users cooperatives and neighbours add, which inputs move the outcome most, and a map of where users are by the final year.
- **Farm ROI**: one typical farm per segment, with the inputs that swing its ROI most.
- **Assumptions**: every input with its range, status and note, filterable by status, so a session can see which numbers are still guesses.

[twin/overrides.py](twin/overrides.py) applies the levers, and `--price` in the adoption report uses it too. A 200-run adoption simulation takes about 5 seconds, and results are cached for each combination of levers. The app needs `data/processed/sp/municipality_points.csv` for its maps, which the build step writes.

To share the app beyond your laptop, push the repo and deploy `app.py` on Streamlit Community Cloud.

## Scenario mode (first tab of the app)

The Scenario tab plays one storyline season by season. [twin/scenario.py](twin/scenario.py) runs it, and [twin/scenario_view.py](twin/scenario_view.py) draws it.

**Your plan** is a table with a row per season: price, treatment strategy, sales effort and whether a cooperative partnership runs. You also choose which segments to sell to. Edit any row to change the plan from that season, for example a lower launch price or a partnership from year 3.

**The world** comes in 5 modes:

| Mode | What happens |
| --- | --- |
| Easy, normal, hard | Each season draws a fire (normal or severe) and shocks at the preset's chances. "New random world" draws another. |
| Replay 2015-2024 | The real fire seasons, using each year's MapBiomas burn rates, with no shocks |
| Custom | You place fires and shocks season by season |

The shocks are a state prevention subsidy, a season's sales suspension, a cheaper rival, a drought and tax relief on agricultural inputs. Their sizes and the presets' chances sit in the `scenario` section of the assumptions file. They are illustrative; only the fire seasons rest on data. You also set how long ago the last severe season was, because recent fires make farmers feel more at risk.

The storyline adds 3 things to the adoption model:

- Each adopter's farm meets a fire or doesn't. A treated farm that holds its fire line counts as `testimonial_weight` extra adopters for its neighbours, fading over `testimonial_memory` seasons. That mirrors the pilot's sugarcane farmer, who became a customer and advocate after seeing a fire contained.
- Perceived fire risk follows the real seasons. It rises to at least what the latest season burned, then fades.
- Shocks change what farmers pay, whether NoFire can sell, and churn.

The results show users and revenue each season for your plan, with event markers and a shaded P10 to P90 range from 60 other runs. "Compare with an alternative plan" replays the same world with the same luck, so the gap between the 2 lines comes from the plan alone. A log tells the story season by season, including where treated farms held fires.

In the 2015-2024 replay with alert treatment, a constant R$700 price ends with 8 users. R$400 ends with 35 users and about R$3m more revenue over the decade.

## Next

- Turn-based play: pause after each season so the team can respond before the next.
- Fill cooperative membership from Censo Agropecuário table 6846. IBGE's API refused connections when this was built, and its backup API sits behind a bot check.
- Replace the placeholders with NoFire's interview and sales data, starting with product price, treatments per season, the ROI hurdle and cooperative membership.
- Add pricing models beyond a price per hectare, such as a season subscription or a payment linked to insurance.
