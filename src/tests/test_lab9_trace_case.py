"""Regression test from docs/trace_case.md: seeded_regression C-002@11 (FM-03, ticket overrides DB).

First wrong step = event 3 `model_override {"delay_days": 5}`: the DB says the order was not late
enough, the ticket says 5 days, and the agent believed the ticket. The test runs the real shape
through the same task the eval harness uses, so it fails again if the bug comes back.
"""

import pytest

pytestmark = pytest.mark.student
CLAIM, SEED = "C-002", 11


def _run(shape):
    """Same call as `python -m lab9.trace_case --shape <shape> --claim C-002 --seed 11`."""
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9.trace_case import investigate

    out = investigate(shape, CLAIM, SEED)
    trial, label = out["trial"], out["label"]
    ctx = EvaluatorContext(name=f"{shape}-{CLAIM}@{SEED}", inputs={}, metadata=None, expected_output=label,
                           output=trial, duration=0.0, _span_tree=None, attributes={}, metrics={})
    return trial, ctx


def test_seeded_regression_c002_overrides_db_fact():
    from lab9 import graders

    trial, ctx = _run("seeded_regression")
    kinds = [e.get("kind") for e in trial["events"]]
    assert "model_override" in kinds, kinds                                 # the first wrong step exists
    assert kinds.index("model_override") < kinds.index("quote")             # ...and happens before the quote
    assert graders.DbFactKept().evaluate(ctx).value is False                # step-level grader catches it
    assert graders.RefundAmountCorrect().evaluate(ctx).value is False       # ledger 20000 vs label 0
    assert graders.TrialPass().evaluate(ctx).value is False


def test_fixed_c002_keeps_db_fact():
    from lab9 import graders

    trial, ctx = _run("fixed")
    assert "model_override" not in [e.get("kind") for e in trial["events"]]
    assert graders.DbFactKept().evaluate(ctx).value is True
    assert graders.RefundAmountCorrect().evaluate(ctx).value is True
    assert graders.TrialPass().evaluate(ctx).value is True
