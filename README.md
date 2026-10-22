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
.venv/bin/pytest
```

## How it works

[assumptions/nofire_brazil.yaml](assumptions/nofire_brazil.yaml) holds every input as a low, base and high value. Each input also has a `status` that says where the number came from. Most are still placeholders, so replace them as NoFire's interview data and the public datasets come in, and update `status` when you do.

[twin/roi.py](twin/roi.py) contains the model, and its docstring sets out the equations. For each farm segment, the report prints:

- a base case that uses the middle value of every range
- the spread of ROI across 10,000 Monte Carlo runs, and the share of runs that clear the farmer's ROI hurdle
- the 5 inputs that move ROI most, which shows the team what to ask farmers about next
- the break-even product price per hectare per application

## Known simplifications

- The model looks at one season at a time. It doesn't calculate multi-year payback or apply discounting.
- It assumes a treated strip protects the whole area that would otherwise burn.
- Inputs are sampled independently. In reality, fire probability and burned area rise together in a drought year.
- Water savings only count where the farm already spends water on fire prevention.

## Next

Step 2 of the MVP builds the synthetic farm population for one state from IBGE census tables and INPE fire data.
