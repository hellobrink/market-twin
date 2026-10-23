from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from twin.assumptions import load
from twin.overrides import override

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS = ROOT / "assumptions" / "nofire_brazil.yaml"


def test_override_fixes_only_the_named_inputs():
    a = load(ASSUMPTIONS)
    b = override(a, product={"product_cost_per_ha": 300}, adoption_rates={"imitation_rate": 0.1},
                 coop_member_share={"sugarcane_ground": 0.9})
    price = b.product["product_cost_per_ha"]
    assert (price.low, price.base, price.high, price.status) == (300, 300, 300, "scenario")
    assert b.product["containment_rate"] == a.product["containment_rate"]
    assert b.adoption.rates["imitation_rate"].base == 0.1
    assert b.adoption.rates["innovation_rate"] == a.adoption.rates["innovation_rate"]
    assert b.adoption.coop_member_share["sugarcane_ground"].base == 0.9
    assert a.product["product_cost_per_ha"].base == 700  # the original is untouched


def test_override_rejects_unknown_inputs():
    with pytest.raises(KeyError, match="product_price"):
        override(load(ASSUMPTIONS), product={"product_price": 300})


def test_app_runs_and_reruns_after_moving_the_price():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    assert at.title[0].value.startswith("NoFire in São Paulo")
    price = next(s for s in at.sidebar.slider if s.label.startswith("Product price"))
    price.set_value(300).run()
    assert not at.exception
    assert any("Product price" in c.value for c in at.sidebar.caption)  # the caption lists what is fixed


def test_scenario_steps_through_seasons_then_plays_the_rest():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.run()
    assert at.session_state["scenario_shown"] == 0  # waits for Start

    def press(label_start):
        next(b for b in at.button if b.label.startswith(label_start)).click().run()
        assert not at.exception

    press("▶ Start")
    assert at.session_state["scenario_shown"] == 1
    press("Next season")
    press("Next season")
    assert at.session_state["scenario_shown"] == 3
    next(r for r in at.radio if r.label == "How to play").set_value("Automatic").run()
    press("▶ Play the rest")
    assert at.session_state["scenario_shown"] == 10
    assert any("End of the story" in s.value for s in at.success)
    press("↺ Restart")
    assert at.session_state["scenario_shown"] == 0
