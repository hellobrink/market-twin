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

The twin builds one synthetic farm for every crop and livestock farm in the 2017 census for São Paulo (181,072 farms). It then runs the ROI model on each farm in the modelled market.

```bash
.venv/bin/python -m twin.population_report
.venv/bin/python -m twin.population_report --strategy alert --top 15
```

The processed data in `data/processed/sp/` is committed, so the report runs offline. To download it again, or to pick different years:

```bash
.venv/bin/python -m twin.data.build --state SP --crop-year 2024 --hotspot-years 2015-2024
```

| Data | Source | Used for |
| --- | --- | --- |
| Farm counts and area by municipality, activity and size group | IBGE Censo Agropecuário 2017, table 6754 | One synthetic farm per establishment, with an area drawn to match the census |
| Farms with trucks by municipality and size group | Censo Agropecuário 2017, table 6877 | Whether a small farm applies from the ground or needs a drone service |
| Sugarcane planted area and production value | IBGE PAM 2024, table 5457 | Which large crop farms grow cane, and cane value at risk per hectare |
| Fire hotspots, reference satellite | INPE BDQueimadas, 2015 to 2024 | Each farm's annual fire probability |
| Burned area by land cover, about 30 m | MapBiomas Fogo collection 5.1, 2015 to 2024 | Calibrating `fires_per_hotspot` |

[twin/population.py](twin/population.py) explains each step. Farms are assigned to segments by these rules:

- Crop farms of 5 to 100 ha go to `smallholder_ground` if they have a truck, otherwise to `smallholder_drone`.
- Temporary-crop farms of 100 ha or more go to `sugarcane_ground`, with a probability equal to sugarcane's share of the municipality's crop area.
- Livestock farms of 500 ha or more go to `remote_ranch_drone`.
- Every other farm sits outside the modelled market.

A farm's fire probability is 1 - exp(-fires_per_hotspot x hotspot rate x farm area). The hotspot rate is the municipality's mean annual hotspots per hectare of farmland.

### Calibrating fire risk

```bash
.venv/bin/python -m twin.calibration
```

This finds the `fires_per_hotspot` at which the synthetic farms burn as much farmland as MapBiomas recorded. The build step clips MapBiomas' annual burned-area rasters to each municipality and splits them by land cover, giving sugarcane, pasture, other farmland and native vegetation. The rasters are about 760 MB in `data/raw/`, and the processed table is `data/processed/sp/burned_area.csv`.

Results for São Paulo, 2015 to 2024:

- Farmland burned averaged 115,000 ha a year, about 0.8% of farmland. For sugarcane it was 1.3%, driven by 2024, when 458,000 ha of cane burned.
- In most years, each reference-satellite hotspot matched 14 to 22 ha of burned farmland. In 2024 it matched 74 ha, because large fires produce fewer hotspots for each hectare burned.
- The calibrated `fires_per_hotspot` is 0.07 for the mean year. That's 40 times lower than the placeholder of 3, and the assumptions file now uses it (low 0.03, high 0.47 for 2024).
- Hotspots place burning across municipalities reasonably well, with a correlation of 0.76 between predicted and observed burned farmland.

The calibration also exposes a problem with the formula. Fire probability rises with farm area, and a fire burns a fixed share of the farm, so expected burning per hectare grows with farm size. Once calibrated, farms over 2,500 ha hold 32% of farmland but get 90% of predicted burning, at 2.2% a year. Farms of 100 to 500 ha get 0.06% a year. That leaves almost no fire risk for a typical cane farm, and only 82 of the largest cane farms clear the ROI hurdle. The fix is to drive fire risk from MapBiomas burned fraction per municipality and land cover. Hotspots would then become a cross-check.

IBGE suppresses area in census cells with few farms. The twin estimates those areas from each municipality's published total, so total synthetic farmland comes within 2% of the census.

Further simplifications in the population:

- The census is from 2017, and the next one is not out yet.
- Only sugarcane farms get value at risk from data. The other segments use the segment's base value.
- The burned share applies to the whole farm, which overstates losses on the very largest farms.
- Every input except area, fire probability and cane value uses the segment's base value, so the population report has no Monte Carlo ranges yet.

## Next

Before step 3, replace the hotspot formula with MapBiomas burned fraction, as described under "Calibrating fire risk". Step 3 of the MVP then adds adoption over time, with peer effects through cooperatives and Monte Carlo runs across the whole population.
