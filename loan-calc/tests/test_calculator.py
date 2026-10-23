"""Tests for loan_calc.calculator, including edge cases.

Edge cases explicitly covered:
- 0% interest rate (no compounding, simple division paths)
- 1-month tenure (shortest possible loan)
- very large principal (precision / scaling sanity)
- prepayment larger than the outstanding balance (loan fully cleared early)

Run with:
    pytest --cov=loan_calc --cov-report=term-missing
"""
import os
from datetime import date

import pytest

from loan_calc import (
    amortisation_schedule,
    compare_offers,
    eligible_amount,
    emi,
    format_inr,
    outstanding_after,
    prepayment_savings,
    remaining_tenure,
    schedule_to_csv,
    summary,
    total_interest,
    total_payment,
)


# ---------------------------------------------------------------------------
# emi()
# ---------------------------------------------------------------------------

class TestEmi:
    def test_known_reference_value(self):
        # Standard reducing-balance EMI reference value.
        # 1,000,000 principal, 9% p.a., 240 months -> ~8997.26
        assert emi(1_000_000, 9, 240) == pytest.approx(8997.26, abs=0.5)

    def test_edge_zero_interest_rate_is_simple_division(self):
        # EDGE CASE: 0% interest -> EMI is just principal / tenure_months.
        assert emi(120_000, 0, 12) == pytest.approx(10_000.0)

    def test_edge_one_month_tenure(self):
        # EDGE CASE: 1-month tenure -> EMI repays principal + 1 month interest.
        result = emi(10_000, 12, 1)
        assert result == pytest.approx(10_100.0, abs=0.5)

    def test_edge_one_month_tenure_zero_interest(self):
        # EDGE CASE: 1-month tenure + 0% interest -> EMI == principal exactly.
        assert emi(10_000, 0, 1) == pytest.approx(10_000.0)

    def test_edge_very_large_principal(self):
        # EDGE CASE: very large principal should scale ~linearly and not
        # raise, overflow, or lose meaningful precision.
        small = emi(1_000_000, 9, 240)
        large = emi(1_000_000_000, 9, 240)
        assert large == pytest.approx(small * 1000, rel=1e-6)

    def test_zero_or_negative_principal_raises(self):
        with pytest.raises(ValueError):
            emi(0, 9, 240)
        with pytest.raises(ValueError):
            emi(-1000, 9, 240)

    def test_zero_or_negative_tenure_raises(self):
        with pytest.raises(ValueError):
            emi(10_000, 9, 0)
        with pytest.raises(ValueError):
            emi(10_000, 9, -5)


# ---------------------------------------------------------------------------
# total_payment() / total_interest()
# ---------------------------------------------------------------------------

class TestTotalPaymentAndInterest:
    def test_total_payment_matches_emi_times_tenure(self):
        p, r, n = 500_000, 10, 60
        assert total_payment(p, r, n) == pytest.approx(emi(p, r, n) * n, abs=0.01)

    def test_total_interest_is_total_payment_minus_principal(self):
        p, r, n = 500_000, 10, 60
        assert total_interest(p, r, n) == pytest.approx(
            total_payment(p, r, n) - p, abs=0.01
        )

    def test_edge_zero_interest_total_interest_is_zero(self):
        # EDGE CASE: 0% interest -> no interest should ever be charged.
        # Tolerance is relaxed to account for legitimate cent-level rounding
        # when the principal doesn't divide evenly across tenure_months
        # (e.g. 100_000 / 24 = 4166.666..., rounded to 4166.67 per month).
        assert total_interest(100_000, 0, 24) == pytest.approx(0.0, abs=0.5)

    def test_edge_one_month_tenure_total_payment_equals_emi(self):
        # EDGE CASE: 1-month tenure -> total payment equals the single EMI.
        p, r, n = 50_000, 8, 1
        assert total_payment(p, r, n) == pytest.approx(emi(p, r, n))

    def test_edge_very_large_principal_total_interest_scales(self):
        # EDGE CASE: very large principal -> total interest should scale
        # ~linearly with principal for the same rate/tenure.
        small = total_interest(1_000_000, 9, 240)
        large = total_interest(1_000_000_000, 9, 240)
        assert large == pytest.approx(small * 1000, rel=1e-6)


# ---------------------------------------------------------------------------
# amortisation_schedule()
# ---------------------------------------------------------------------------

class TestAmortisationSchedule:
    def test_schedule_length_matches_tenure(self):
        sched = amortisation_schedule(100_000, 9, 12)
        assert len(sched) == 12

    def test_schedule_final_balance_is_zero(self):
        # The loan must be fully repaid by the last row of the schedule.
        sched = amortisation_schedule(100_000, 9, 12)
        assert sched[-1]["balance"] == pytest.approx(0.0, abs=0.01)

    def test_schedule_month_numbers_are_sequential(self):
        sched = amortisation_schedule(100_000, 9, 12)
        assert [row["month"] for row in sched] == list(range(1, 13))

    def test_edge_one_month_tenure_schedule(self):
        # EDGE CASE: a 1-month loan should produce exactly one row that
        # clears the full balance.
        sched = amortisation_schedule(10_000, 12, 1)
        assert len(sched) == 1
        assert sched[0]["balance"] == pytest.approx(0.0, abs=0.01)

    def test_edge_zero_interest_schedule_sums_to_principal(self):
        # EDGE CASE: 0% interest -> sum of all principal portions equals
        # the original principal, and interest is always zero.
        principal = 120_000
        sched = amortisation_schedule(principal, 0, 12)
        assert sum(row["interest"] for row in sched) == pytest.approx(0.0, abs=0.01)
        assert sum(row["principal"] for row in sched) == pytest.approx(
            principal, abs=0.1
        )

    def test_edge_very_large_principal_schedule_clears_balance(self):
        # EDGE CASE: very large principal -> schedule should still fully
        # clear the balance by the final month.
        sched = amortisation_schedule(1_000_000_000, 9, 240)
        assert sched[-1]["balance"] == pytest.approx(0.0, abs=1.0)


# ---------------------------------------------------------------------------
# outstanding_after()
# ---------------------------------------------------------------------------

class TestOutstandingAfter:
    def test_no_months_paid_returns_full_principal(self):
        assert outstanding_after(100_000, 9, 12, 0) == pytest.approx(100_000)

    def test_after_all_months_paid_balance_is_zero(self):
        assert outstanding_after(100_000, 9, 12, 12) == pytest.approx(0.0, abs=0.01)

    def test_months_paid_beyond_tenure_returns_zero(self):
        assert outstanding_after(100_000, 9, 12, 999) == 0.0

    def test_edge_one_month_tenure(self):
        # EDGE CASE: 1-month tenure -> fully paid off after month 1.
        assert outstanding_after(10_000, 12, 1, 1) == pytest.approx(0.0, abs=0.01)

    def test_edge_very_large_principal(self):
        # EDGE CASE: very large principal -> outstanding balance after 0
        # months paid should equal the full principal.
        assert outstanding_after(1_000_000_000, 9, 240, 0) == pytest.approx(
            1_000_000_000
        )


# ---------------------------------------------------------------------------
# remaining_tenure()
# ---------------------------------------------------------------------------

class TestRemainingTenure:
    def test_zero_balance_returns_zero_months(self):
        assert remaining_tenure(0, 9, 1000) == 0
        assert remaining_tenure(-50, 9, 1000) == 0

    def test_edge_zero_interest_rate_simple_division(self):
        # EDGE CASE: 0% interest -> months needed = ceil(balance / instalment).
        assert remaining_tenure(10_000, 0, 2_000) == 5
        assert remaining_tenure(10_001, 0, 2_000) == 6

    def test_instalment_too_small_raises(self):
        # If the instalment can't even cover the monthly interest, the
        # loan would never be paid off.
        with pytest.raises(ValueError):
            remaining_tenure(1_000_000, 24, 100)


# ---------------------------------------------------------------------------
# prepayment_savings()
# ---------------------------------------------------------------------------

class TestPrepaymentSavings:
    def test_basic_prepayment_shortens_tenure(self):
        result = prepayment_savings(1_000_000, 9, 240, 24, 200_000)
        assert result["new_tenure"] < 240
        assert result["months_saved"] > 0
        assert result["interest_saved"] > 0

    def test_edge_prepayment_larger_than_balance_clears_loan_immediately(self):
        # EDGE CASE: prepayment amount exceeds the outstanding balance at
        # that point -> loan should be considered fully paid off with 0
        # months remaining after the prepayment month.
        principal, rate, tenure, prepay_month = 100_000, 9, 24, 12
        balance_before = outstanding_after(principal, rate, tenure, prepay_month)
        huge_prepayment = balance_before + 1_000_000  # far more than owed
        result = prepayment_savings(
            principal, rate, tenure, prepay_month, huge_prepayment
        )
        assert result["new_tenure"] == prepay_month
        assert result["months_saved"] == tenure - prepay_month

    def test_edge_one_month_tenure_prepayment(self):
        # EDGE CASE: prepaying on a loan with only 1-month tenure. The
        # "prepayment" effectively happens on the only month there is.
        result = prepayment_savings(10_000, 12, 1, 1, 10_100)
        assert result["new_tenure"] == 1
        assert result["months_saved"] == 0

    def test_edge_zero_interest_prepayment(self):
        # EDGE CASE: 0% interest loan -> no interest should ever be saved,
        # but tenure should still shorten.
        result = prepayment_savings(120_000, 0, 12, 6, 30_000)
        assert result["interest_saved"] == pytest.approx(0.0, abs=0.01)
        assert result["new_tenure"] < 12

    def test_edge_very_large_principal_prepayment(self):
        # EDGE CASE: very large principal -> prepayment math should still
        # complete without errors and produce sane savings.
        result = prepayment_savings(1_000_000_000, 9, 240, 24, 200_000_000)
        assert result["new_tenure"] < 240
        assert result["interest_saved"] > 0


# ---------------------------------------------------------------------------
# compare_offers()
# ---------------------------------------------------------------------------

class TestCompareOffers:
    def test_offers_sorted_by_total_cost_ascending(self):
        offers = [
            {"bank": "A", "rate": 10, "tenure": 60, "processing_fee_pct": 1},
            {"bank": "B", "rate": 9, "tenure": 60, "processing_fee_pct": 0.5},
            {"bank": "C", "rate": 11, "tenure": 60},
        ]
        result = compare_offers(500_000, offers)
        costs = [o["total_cost"] for o in result]
        assert costs == sorted(costs)

    def test_missing_processing_fee_defaults_to_zero(self):
        offers = [{"bank": "NoFee", "rate": 9, "tenure": 60}]
        result = compare_offers(500_000, offers)
        assert result[0]["processing_fee"] == 0.0

    def test_empty_offers_list_returns_empty(self):
        assert compare_offers(500_000, []) == []

    def test_edge_zero_interest_offer(self):
        # EDGE CASE: an offer with 0% interest should still be comparable
        # alongside normal offers, with total_interest == 0.
        offers = [
            {"bank": "ZeroRate", "rate": 0, "tenure": 60},
            {"bank": "Normal", "rate": 9, "tenure": 60},
        ]
        result = compare_offers(500_000, offers)
        zero_rate_offer = next(o for o in result if o["bank"] == "ZeroRate")
        # Tolerance relaxed slightly to account for legitimate cent-level
        # rounding when 500_000 doesn't divide evenly across 60 months.
        assert zero_rate_offer["total_interest"] == pytest.approx(0.0, abs=0.5)

    def test_edge_one_month_tenure_offer(self):
        # EDGE CASE: an offer with a 1-month tenure.
        offers = [{"bank": "ShortTerm", "rate": 12, "tenure": 1}]
        result = compare_offers(10_000, offers)
        assert result[0]["emi"] == pytest.approx(10_100.0, abs=0.5)

    def test_edge_very_large_principal_offer(self):
        # EDGE CASE: very large principal should not raise or overflow.
        offers = [{"bank": "BigLoan", "rate": 9, "tenure": 240}]
        result = compare_offers(1_000_000_000, offers)
        assert result[0]["total_cost"] > 0


# ---------------------------------------------------------------------------
# eligible_amount()
# ---------------------------------------------------------------------------

class TestEligibleAmount:
    def test_no_available_capacity_returns_zero(self):
        # Existing EMIs consume the entire FOIR-capped budget.
        assert eligible_amount(50_000, 25_000, 9, 240, foir=0.5) == 0.0

    def test_edge_zero_interest_rate(self):
        # EDGE CASE: 0% interest -> eligible amount = available * tenure.
        available = 50_000 * 0.5 - 10_000  # 15,000
        expected = available * 240
        assert eligible_amount(50_000, 10_000, 0, 240, foir=0.5) == pytest.approx(
            expected
        )

    def test_edge_one_month_tenure(self):
        # EDGE CASE: 1-month tenure -> eligible principal should be close
        # to the available monthly EMI capacity (minus one month interest).
        result = eligible_amount(100_000, 0, 12, 1, foir=0.5)
        assert result == pytest.approx(50_000, rel=0.01)

    def test_eligible_amount_increases_with_tenure(self):
        short = eligible_amount(100_000, 0, 9, 60)
        long = eligible_amount(100_000, 0, 9, 240)
        assert long > short

    def test_edge_very_large_income(self):
        # EDGE CASE: very large monthly income should not raise or overflow.
        result = eligible_amount(1_000_000_000, 0, 9, 240, foir=0.5)
        assert result > 0


# ---------------------------------------------------------------------------
# format_inr()
# ---------------------------------------------------------------------------

class TestFormatInr:
    def test_small_amount_no_grouping_needed(self):
        assert format_inr(500) == "₹500.00"

    def test_thousands_grouping(self):
        assert format_inr(10_000) == "₹10,000.00"

    def test_lakhs_grouping(self):
        # Indian-style grouping: groups of 2 after the first group of 3.
        assert format_inr(1_000_000) == "₹10,00,000.00"

    def test_crores_grouping(self):
        assert format_inr(100_000_000) == "₹10,00,00,000.00"

    def test_negative_amount(self):
        assert format_inr(-500) == "-₹500.00"

    def test_edge_very_large_amount(self):
        # EDGE CASE: very large amount should still format without error.
        assert format_inr(1_000_000_000) == "₹1,00,00,00,000.00"

    def test_rounds_to_two_decimals(self):
        assert format_inr(999.995) == "₹1,000.00"


# ---------------------------------------------------------------------------
# schedule_to_csv()
# ---------------------------------------------------------------------------

class TestScheduleToCsv:
    def test_writes_header_and_rows(self, tmp_path):
        rows = amortisation_schedule(100_000, 9, 12)
        out_path = tmp_path / "schedule.csv"
        schedule_to_csv(rows, str(out_path))

        assert out_path.exists()
        with open(out_path) as fh:
            lines = fh.read().splitlines()

        assert lines[0] == "month,emi,interest,principal,balance"
        # One header line + one line per schedule row.
        assert len(lines) == 1 + len(rows)

    def test_edge_one_month_tenure_csv(self, tmp_path):
        # EDGE CASE: a 1-month schedule should still produce a valid CSV
        # with exactly one data row.
        rows = amortisation_schedule(10_000, 12, 1)
        out_path = tmp_path / "one_month.csv"
        schedule_to_csv(rows, str(out_path))

        with open(out_path) as fh:
            lines = fh.read().splitlines()
        assert len(lines) == 2  # header + 1 row


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_contains_expected_keys(self):
        result = summary(1_000_000, 9, 240, start=date(2024, 1, 1))
        expected_keys = {
            "principal",
            "rate",
            "tenure",
            "emi",
            "total_interest",
            "total_payment",
            "last_emi",
            "currency",
        }
        assert set(result.keys()) == expected_keys

    def test_summary_last_emi_date_rolls_over_year(self):
        # Starting Jan 2024 with a 12-month tenure should land on Jan 2025.
        result = summary(100_000, 9, 12, start=date(2024, 1, 1))
        assert result["last_emi"] == "2025-01"

    def test_summary_defaults_to_today_when_start_not_given(self):
        # Just make sure it runs without error and returns a sane dict when
        # no explicit start date is given (defaults to date.today()).
        result = summary(100_000, 9, 12)
        assert "last_emi" in result
        assert result["currency"] == "INR"

    def test_edge_one_month_tenure_summary(self):
        # EDGE CASE: a 1-month tenure summary should still compute cleanly.
        result = summary(10_000, 12, 1, start=date(2024, 1, 1))
        assert result["tenure"] == "1 months"
        assert result["last_emi"] == "2024-02"

    def test_edge_zero_interest_summary(self):
        # EDGE CASE: 0% interest summary should show zero total interest.
        result = summary(120_000, 0, 12, start=date(2024, 1, 1))
        assert result["total_interest"] == "₹0.00"
