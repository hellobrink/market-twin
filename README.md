# Market twin: NoFire in São Paulo

A prototype "digital twin" of a market, built by Brink to help venture teams test pricing, sales and timing decisions before they spend money in the field. The first case is NoFire, a fire-retardant gel from the Frontier Tech Hub [Stop the Spread](https://www.frontiertechhub.org/pilot-portfolio/stop-the-spread) pilot, sold to farms in the Brazilian state of São Paulo.

**Live app:** [market-twin.streamlit.app](https://market-twin-bfvkxgcpeutewnzyr7kjmt.streamlit.app/). It may take 30 seconds to wake up if nobody has used it for a while.

**Status:** working prototype. The farm population, fire history and crop values come from public data. Most numbers about how farmers behave are still placeholders that need replacing with NoFire's own interview and sales data. Treat the outputs as a way to explore assumptions, and don't quote them as forecasts.

## Contents

1. [What it is](#what-it-is)
2. [How it's designed to be used](#how-its-designed-to-be-used)
3. [The app, tab by tab](#the-app-tab-by-tab)
4. [How the model works](#how-the-model-works)
5. [Data sources](#data-sources)
6. [Assumptions and how to change them](#assumptions-and-how-to-change-them)
7. [What it shows so far](#what-it-shows-so-far)
8. [What's missing and needs doing](#whats-missing-and-needs-doing)
9. [Reusing it for other Brink twins](#reusing-it-for-other-brink-twins)
10. [Running it yourself](#running-it-yourself)
11. [Project layout](#project-layout)

## What it is

The Stop the Spread pilot found that farmers valued NoFire's gel, especially for the water it saves, but hesitated to pay because nobody could show them a clear return on investment. It also found that ground application beats drones wherever farms already own water trucks. Those findings raise questions a coach would want to explore with the team: which farms will pay, at what price, how fast word spreads, and what a bad fire year or a new rival does to the business.

The twin answers those questions with a simulated version of the market. It builds one synthetic farm for each of the 181,072 crop and livestock farms in São Paulo's 2017 agricultural census. Each farm gets a size, a crop, a truck or not, a fire risk based on what has really burned in its municipality, and a value at risk. The model then works out whether NoFire pays for itself on each farm, and simulates which farms buy, season by season, as fires, prices, neighbours and other events play out.

It runs as a web app with 5 tabs. The first, **Scenario**, lets a team set a plan, choose a world of events, and watch the seasons unfold one at a time.

## How it's designed to be used

The twin is a coaching tool. A session works best with a coach driving the app and the venture team discussing what they see. A typical 60 to 90 minute session runs like this:

1. **Open on the Assumptions tab.** It lists every number in the model and whether it comes from the pilot, public data or a placeholder. Agree with the team which placeholders matter most and what they believe instead. A coach can change the main ones from the sidebar during the session.
2. **Play a scenario step by step.** On the Scenario tab, pick a world (start with "Replay 2015-2024" or "Normal") and set the team's current plan. Before each **Next season** click, ask the team what they expect to happen and whether they'd change anything.
3. **Compare 2 plans with the same luck.** Tick "Compare with an alternative plan" and enter a different price, a cooperative partnership or more sales effort. Both plans see exactly the same fires and the same random draws, so any gap between the lines comes from the decision alone.
4. **Stress-test the plan.** Switch to the "Hard" world and play again, or use "Custom" to place a severe fire in year 2 and a rival in year 4. Ask how the business would survive and what the team would do differently.
5. **Step back to the range.** The Adoption over time tab runs hundreds of simulations to show the spread of outcomes and which assumptions drive it most. That tells the team which field test or interview question would reduce their uncertainty fastest.
6. **Close on what to find out.** The point of the session is a short list of facts the team needs to check, such as what their product really costs per hectare or how many target farms belong to a cooperative.

Some cautions for sessions:

- One storyline is one possible future. The shaded band behind each chart shows where most runs land, and it's worth pointing to it whenever a single story looks dramatic.
- Shocks such as subsidies, sales suspensions and rivals have illustrative sizes. They're there to prompt discussion about resilience, not to predict policy.
- Numbers marked "placeholder" can move results a lot. The app shows which ones on the Assumptions tab, and the Farm ROI tab shows how much each one swings a typical farm's return.

## The app, tab by tab

| Tab | What it shows | Use it to |
| --- | --- | --- |
| Scenario | One storyline, season by season, under a plan you set and a world of events you choose | Rehearse decisions and talk through what could happen |
| Market today | Which farms would buy in a normal, severe or long-run fire year, by segment, with a map | See where the market is and how big it could be |
| Adoption over time | Users and revenue each year across many simulations, with the range and the main drivers | Understand uncertainty and what to test next |
| Farm ROI | One typical farm per segment and which inputs swing its return most | Explain the economics of a single sale |
| Assumptions | Every input with its range, source status and note | See what's evidence and what's a guess |

The sidebar holds model settings that apply across tabs: price, treatment strategy, containment rate, the return a farmer needs before buying, and the adoption settings. Moving a setting fixes it at that value. Anything left alone keeps its full range of uncertainty in the simulations, and the sidebar lists what's fixed. On the Scenario tab, price and strategy come from the plan table instead.

### The Scenario tab in more detail

You set 2 things.

**The world** comes in 5 modes:

| Mode | What happens |
| --- | --- |
| Easy, Normal, Hard | Each season has a chance of a severe fire and of shocks. Hard has more of both. "New random world" draws a different sequence. |
| Replay 2015-2024 | The real fire seasons of the last decade, using each year's measured burn rates. No shocks. |
| Custom | You place each fire and shock yourself. |

The shocks are a state prevention subsidy, a season with sales suspended by a regulator, a cheaper rival, a drought and tax relief on agricultural inputs. You also set how long ago the last severe fire season was, because a recent bad year makes farmers feel more at risk.

**Your plan** is a table with a row per season: price per hectare per treatment, treatment strategy, sales effort and whether a cooperative partnership runs. You also choose which farm segments to sell to. Edit any row to change the plan from that season.

Then choose **Step by step**, which pauses after each season until you click **Next season**, or **Automatic**, which plays the seasons on its own. A strip of years fills in with icons for each season's fire and events, each season adds a coloured card to the timeline, and the metrics, charts and map update beside it. **Restart** goes back to the start.

## How the model works

The model has 5 layers. Each builds on the one before.

```
Public data  ->  Synthetic farms  ->  Fire risk  ->  Farm ROI  ->  Adoption over time  ->  Scenarios
(IBGE, INPE,     (one per census      (MapBiomas      (cost vs       (Bass diffusion,       (plans, worlds,
 MapBiomas)       farm, 4 segments)    burn rates)     avoided loss)   cooperatives)          storylines)
```

### 1. Synthetic farms

Each census cell (municipality x activity x farm-size band) becomes that many farms, with areas drawn to match the census average for the cell. Where IBGE hides a cell's area for confidentiality, the twin estimates it from the municipality's published total, so total farmland lands within 2% of the census. Each farm gets a truck or not, drawn from the share of farms that size in its municipality that own one.

Farms fall into 4 segments:

| Segment | Rule | Delivery |
| --- | --- | --- |
| Sugarcane, ground | Temporary-crop farms of 100 ha or more, with a chance equal to cane's share of the municipality's crop area | Own truck |
| Smallholder, own truck | Crop farms of 5 to 100 ha with a truck | Own truck |
| Smallholder, drone | Crop farms of 5 to 100 ha without a truck | Drone service |
| Large ranch, drone | Livestock farms of 500 ha or more | Drone service |

That puts 54,189 farms in the modelled market. The rest are under 5 ha, large non-cane crop farms or smaller livestock farms.

### 2. Fire risk

A farm's expected burned share each year is its municipality's burn rate for its land cover: cane for sugarcane farms, pasture for ranches, other crops for smallholders. The burn rate is MapBiomas burned hectares divided by MapBiomas hectares of that land cover. Where a municipality has little of a land cover, the rate leans towards the state average.

| Fire scenario | Years | Typical cane farm, burned a year |
| --- | --- | --- |
| Normal | Mean of 2015 to 2023 | 0.40% |
| Severe | 2024 | 3.86% |
| Long run | 90% normal, 10% severe | 0.86% |

2024 sits apart because it burned 458,000 ha of cane, more than 2015 to 2023 combined. INPE satellite hotspots act as a cross-check: they rank municipalities much as MapBiomas does, with rank correlations of 0.66 for normal years and 0.58 for 2024.

An earlier version used a hotspot formula for fire risk. Calibrating it against MapBiomas showed that it piled almost all the burning onto the very largest farms, so it was dropped. [twin/calibration.py](twin/calibration.py) keeps the record.

### 3. Farm ROI

For each farm and season:

```
cost          = treatments x treated hectares x (product price + application cost)
avoided loss  = expected burned hectares x containment rate x share of fires met by a treatment x value at risk per ha
water value   = water the farm already spends on prevention x share saved by the gel x water cost
ROI           = (avoided loss + water value - cost) / cost
```

Treatment strategy matters a lot. The gel lasts about 24 hours, so "scheduled" farms treat on every high-risk day, while "alert" farms treat only when a fire is reported nearby. Alert treatment means fewer treatments, and a better chance that the gel is fresh when a fire arrives.

### 4. Adoption over time

Each season, a farm considers buying only if its ROI, judged on its perceived fire risk, clears its own hurdle. Perceived risk jumps after a severe season and then fades. Farms that would profit adopt with the Bass diffusion chance:

```
chance = 1 - (1 - outside push) x (1 - imitation x share of peers who have adopted)
```

A cooperative member's peers are fellow members in its municipality. A non-member feels its whole municipality, more weakly. Adopters whose perceived ROI falls below their hurdle may stop. Each Monte Carlo run draws every uncertain input from its range.

### 5. Scenarios

The scenario engine plays one plan through one world. It adds 3 things to the adoption model:

- Each adopter's farm meets a fire or doesn't. A treated farm that holds its fire line becomes a story its neighbours hear, which raises their chance of buying. This mirrors the pilot's sugarcane farmer, who became a paying customer and advocate after seeing a fire contained.
- Perceived risk follows the actual seasons.
- Shocks change what farmers pay, whether NoFire can sell, or how many customers leave.

Two plans played through the same world with the same seed see identical random draws, so comparisons isolate the effect of the plan.

## Data sources

| Data | Source | Used for |
| --- | --- | --- |
| Farm counts and area by municipality, activity and size band | IBGE Censo Agropecuário 2017, table 6754 | One synthetic farm per establishment |
| Farms with trucks by municipality and size band | Censo Agropecuário 2017, table 6877 | Ground application or drone service |
| Sugarcane area and production value | IBGE Produção Agrícola Municipal 2024, table 5457 | Which large crop farms grow cane, and cane value at risk |
| Burned area by land cover, about 30 m | MapBiomas Fogo collection 5.1, 2015 to 2024 | Fire risk by municipality and year |
| Land cover, about 30 m | MapBiomas collection 11, 2020 | Hectares of cane, pasture and other crops per municipality |
| Fire hotspots, reference satellite | INPE BDQueimadas, 2015 to 2024 | Cross-check on where fires happen |
| Municipal boundaries | IBGE | Map points and clipping MapBiomas rasters |

The processed tables in `data/processed/sp/` are committed, so the app runs without downloading anything. `data/processed/sp/build_info.json` records the years and tables used.

## Assumptions and how to change them

Every input lives in [assumptions/nofire_brazil.yaml](assumptions/nofire_brazil.yaml) as a low, base and high value, with a `status` and a note:

| Status | Meaning | Count today |
| --- | --- | --- |
| `pilot` | From the Stop the Spread pilot page | 2 |
| `public` | From a public dataset | 1 |
| `placeholder` | A Brink estimate waiting for real data | 59 |
| `interview` | From NoFire's interviews | 0 |

The pilot supplies the containment rate (up to 85%) and the water saving (up to 63%). Fire risk, farm sizes and cane values come from the data files directly. The placeholders that move results most are the product price, the number of treatments per season, the share of fires met by a treatment, the return farmers need before buying, and cooperative membership.

To change an assumption, edit its range in the YAML file, update its `status` and note when it comes from real data, and restart the app. The file also holds the fire scenarios, the adoption settings and the scenario-mode event sizes and chances.

## What it shows so far

With today's placeholders, so these are directions to test, not findings:

- At R$700 per hectare per treatment, the product pays for itself mainly in bad fire years. In a normal year almost no farm clears its hurdle, and in a 2024-type year more than half of large cane farms do.
- Treating on fire alerts beats treating on a schedule for every segment, because each treatment is more likely to be in place when a fire arrives.
- Large sugarcane farms in the north-east cane belt are the core market: Pitangueiras, Jaboticabal, Olímpia, Sertãozinho and Morro Agudo. Smallholders rarely see a fire on their land, so the product rarely pays for them, and most lack the truck that makes application cheap.
- A lower price widens reach more than it grows revenue. At R$300, roughly 3 times as many farms adopt over 10 years, for about the same revenue.
- Whether a severe season happens matters more than any decision. That points towards pricing that fits a product people value most after a bad year, such as a subscription or a payment linked to insurance.
- Cooperative and neighbour effects add roughly a third to a half more adopters, which supports selling through cooperatives.

## What's missing and needs doing

In rough order of priority:

1. **Replace the main placeholders with NoFire data.** The most valuable are product cost and price per hectare, treatments per season, how farms decide when to treat, the payback farmers expect, cooperative membership among target farms, and the numbers from the sugarcane farm that contained a fire. That farm would also be the first real check on the model.
2. **Fill cooperative membership from the census.** Censo Agropecuário table 6846 has membership by municipality and farm size. IBGE's API refused connections while this was built, so it's still a placeholder.
3. **Have someone with Brazilian policy knowledge size the shocks.** Subsidy, sales suspension, rival, drought and tax relief sizes are illustrative. The tax reform (EC 132/2023 and LC 214/2025), state fire policy (Lei 14.944/2024) and IBAMA rules on retardants all need checking.
4. **Add NoFire's costs.** The model tracks revenue but not margin, sales cost or cash flow, so it can't yet say whether a plan makes money for NoFire.
5. **Add pricing models.** Today the only option is a price per hectare per treatment. A season subscription, a payment that only applies in bad years, or a bundle with crop insurance look promising and need modelling.
6. **Turn-based play.** Let the team change the plan between seasons in step-by-step mode, so the scenario becomes a planning game.
7. **Validate.** Back-test adoption against a comparable product, such as spraying-drone uptake in Brazil after the 2021 rules, and have an economist review the model.
8. **Refresh the data.** The census is from 2017 and land cover is fixed at 2020. Use the next census when it's published, and land cover for each year.
9. **Smaller gaps.** Smallholders use the burn rate for non-cane crops even where cane surrounds them. Only sugarcane gets value at risk from data. Seasons are a year long, though MapBiomas also publishes monthly burned area.
10. **Access control for the live app.** The repo and a Community Cloud app are public by default. If the assumptions or client details become sensitive, make the repo private and limit who can view the app.

## Reusing it for other Brink twins

Most of the code is generic. What changes per product is the data and the decision rules.

| Layer | Built once | Rebuilt per product |
| --- | --- | --- |
| Assumptions file format, overrides, Monte Carlo | All of it | The numbers |
| Synthetic population from census cells | Sampling, suppressed-area estimates | Data adapters, segment rules |
| ROI model | Structure | Equations for the product's value |
| Adoption, scenarios, storylines | All of it | Event types and sizes |
| App | Tabs, charts, maps, playback | Labels and wording |

A second Brazilian state needs a new entry in `twin/data/codes.py` and a data rebuild. A new country needs new data adapters for its census, crop and fire data.

## Running it yourself

You need Python 3.12 or later.

```bash
git clone https://github.com/hellobrink/market-twin.git
cd market-twin
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Then open http://localhost:8501.

For the tests and the data rebuild, install the development requirements, which add pytest, geopandas and rasterio:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Command-line reports:

```bash
.venv/bin/python -m twin.report                  # ROI for each segment
.venv/bin/python -m twin.population_report       # who buys, by fire scenario and strategy
.venv/bin/python -m twin.adoption_report --price 300 --runs 500
.venv/bin/python -m twin.calibration             # why the hotspot formula was dropped
```

To rebuild `data/processed/sp/` from the original sources:

```bash
.venv/bin/python -m twin.data.build --state SP --crop-year 2024 --hotspot-years 2015-2024 --land-cover-year 2020
```

The rebuild downloads about 760 MB of MapBiomas rasters into `data/raw/`, which is not committed, and streams the São Paulo part of the land-cover raster.

### Deploying the live app

The app runs on Streamlit Community Cloud straight from this repo:

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with a GitHub account that can see `hellobrink/market-twin`.
2. Choose **Create app**, then **Deploy a public app from GitHub**.
3. Set the repository to `hellobrink/market-twin`, the branch to `main` and the main file to `app.py`.
4. Under **Advanced settings**, choose Python 3.13.
5. Press **Deploy**. Later pushes to `main` update the app automatically.

## Project layout

| Path | What it holds |
| --- | --- |
| `app.py` | The Streamlit app |
| `twin/scenario.py`, `twin/scenario_view.py` | Scenario engine and the Scenario tab |
| `twin/adoption.py` | Adoption over time, Monte Carlo |
| `twin/population.py` | Synthetic farms, segments, fire risk |
| `twin/roi.py` | Per-farm ROI model |
| `twin/assumptions.py`, `twin/overrides.py` | Loading assumptions and fixing them for what-ifs |
| `twin/calibration.py` | The hotspot calibration, kept as a record |
| `twin/data/` | Downloads and processing for IBGE, INPE and MapBiomas |
| `twin/*_report.py`, `twin/report.py` | Command-line reports |
| `assumptions/nofire_brazil.yaml` | Every input, with ranges and sources |
| `data/processed/sp/` | Processed São Paulo data the app reads |
| `tests/` | 42 tests, including headless runs of the app |

The original design note for the project is the [Market Digital Twin: Prototype Spec](https://claude.ai/artifact/6hn6GXpxTLsz9Q56Yx15y6).
