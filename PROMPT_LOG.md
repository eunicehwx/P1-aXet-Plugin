# Prompt Log — AI Mistakes

This log records instances during this assignment where the AI's explanation or generated tests were incorrect, for transparency.

## Mistake 1: Overly strict test tolerances for 0% interest edge cases

**What happened:**
When writing the pytest test suite, two edge-case tests were written with a tolerance of `abs=0.01` asserting that a 0%-interest loan should produce *exactly* zero total interest:

```python
def test_edge_zero_interest_total_interest_is_zero(self):
    assert total_interest(100_000, 0, 24) == pytest.approx(0.0, abs=0.01)
```

```python
def test_edge_zero_interest_offer(self):
    ...
    assert zero_rate_offer["total_interest"] == pytest.approx(0.0, abs=0.01)
```

**Why it was wrong:**
When run, both tests failed:
- `total_interest(100_000, 0, 24)` returned `0.08`, not `0.0`.
- The zero-rate offer's `total_interest` returned `-0.2`, not `0.0`.

This happened because `100_000 / 24` does not divide evenly (`4166.666...`), so the EMI is rounded to the nearest cent (`4166.67`). Multiplying that rounded EMI back out by 24 months introduces a few cents of cumulative rounding drift versus the original principal. This is **expected, legitimate floating-point/currency rounding behavior**, not a bug in the calculator — but the AI's first draft of the test assumed 0% interest would always net out to an *exact* zero, which is only true when the principal divides evenly across the tenure.

**How it was corrected:**
The tolerance on both assertions was relaxed from `abs=0.01` to `abs=0.5`, with a comment added explaining that a few cents of rounding drift is expected when the principal doesn't divide evenly across the number of months:

```python
def test_edge_zero_interest_total_interest_is_zero(self):
    # EDGE CASE: 0% interest -> no interest should ever be charged.
    # Tolerance is relaxed to account for legitimate cent-level rounding
    # when the principal doesn't divide evenly across tenure_months
    # (e.g. 100_000 / 24 = 4166.666..., rounded to 4166.67 per month).
    assert total_interest(100_000, 0, 24) == pytest.approx(0.0, abs=0.5)
```

This was caught by actually running the test suite (`pytest -v`) rather than assuming the assertions were correct, which is why running tests after writing them — rather than trusting the AI's first draft — was an important verification step in this workflow.

## Mistake 2: Edge cases initially missed in the test suite

**What happened:**
The first version of `tests/test_calculator.py` only covered `emi`, `total_payment`, `total_interest`, `amortisation_schedule`, `outstanding_after`, `remaining_tenure`, `prepayment_savings`, `compare_offers`, and `eligible_amount`. It did not include any tests at all for `format_inr()`, `schedule_to_csv()`, or `summary()` — three public functions in the module were left completely untested, including their edge cases (e.g. a 1-month-tenure summary, a 0%-interest summary, very large amounts formatted as currency, negative amounts, and lakh/crore digit-grouping boundaries).

**Why it was wrong:**
Running `pytest --cov=loan_calc --cov-report=term-missing` showed only **80% coverage**, with the missing lines pointing directly at `format_inr`, `schedule_to_csv`, and `summary`. The initial test plan focused on the four edge cases explicitly requested (0% interest, 1-month tenure, very large principal, prepayment larger than balance) but failed to apply that same edge-case thinking to the formatting/export/summary functions, which have their own meaningful edge cases (e.g. does `format_inr` handle negative numbers and crore-level amounts? does `summary` handle a loan so short it rolls over into the next year?).

**How it was corrected:**
Added three new test classes — `TestFormatInr`, `TestScheduleToCsv`, and `TestSummary` — each including both normal cases and edge cases (very large amounts, 1-month tenure, 0% interest, year-rollover dates). Re-running coverage afterward confirmed **100% statement coverage**, closing the gap that the first pass had missed.
