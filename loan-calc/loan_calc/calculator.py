import math
from datetime import date


DEFAULT_CURRENCY = "INR"


def _monthly_rate(annual_rate):
    # BUG FIX: previously rounded the monthly rate to 4 decimal places here,
    # before it was ever used in any calculation. That premature rounding
    # introduced small precision errors into every EMI, interest, schedule,
    # and eligibility calculation downstream (e.g. 0% loans showing a tiny
    # non-zero interest due to floating point rounding artifacts). Now the
    # full-precision rate is returned and only the final results are rounded.
    r = annual_rate / 1200
    return r


def emi(principal: float, annual_rate: float, tenure_months: int) -> float:
    """Compute the Equated Monthly Instalment (EMI) for a reducing-balance loan.

    Args:
        principal: Loan principal amount (must be positive).
        annual_rate: Nominal annual interest rate as a percentage (e.g. 9 for 9%).
        tenure_months: Loan tenure in months (must be positive).

    Returns:
        The EMI amount, rounded to 2 decimal places.

    Raises:
        ValueError: If principal or tenure_months is not positive.
    """
    if tenure_months <= 0:
        raise ValueError("tenure must be positive")
    if principal <= 0:
        raise ValueError("principal must be positive")
    r = _monthly_rate(annual_rate)
    if r == 0:
        return round(principal / tenure_months, 2)
    f = (1 + r) ** tenure_months
    return round(principal * r * f / (f - 1), 2)


def total_payment(principal: float, annual_rate: float, tenure_months: int) -> float:
    """Compute the total amount repaid over the life of the loan (EMI x tenure).
    
    Returns:
        Total amount repaid, rounded to 2 decimal places.
    """
    return round(emi(principal, annual_rate, tenure_months) * tenure_months, 2)


def total_interest(principal: float, annual_rate: float, tenure_months: int) -> float:
    """Compute the total interest paid over the life of the loan.

    Returns:
        Total interest paid (total payment minus principal), rounded to 2 decimal places.
    """
    return round(total_payment(principal, annual_rate, tenure_months) - principal, 2)


def amortisation_schedule(
    principal: float, annual_rate: float, tenure_months: int
) -> list[dict[str, float]]:
    """Build a month-by-month amortisation schedule for the loan.

    In the for loop, step by step:
    - Goes through the loan one month at a time.
    - Each month, works out the interest owed on whatever balance is left.
    - Works out how much of that month's payment goes toward the principal
      (payment minus interest).
    - Reduces the balance by that principal amount.
    - On the very last month, instead of using the usual formula, it just
      pays off whatever balance is left exactly, so the loan doesn't end
      with a tiny leftover amount due to rounding.

    Returns:
        A list of dicts, one per month, each with keys:
        "month", "emi", "interest", "principal", "balance".
    """
    r = _monthly_rate(annual_rate)
    instalment = emi(principal, annual_rate, tenure_months)
    balance = principal
    rows = []
    for month in range(1, tenure_months):
        interest = round(balance * r, 2)
        principal_part = round(instalment - interest, 2)
        if month == tenure_months:
            principal_part = round(balance, 2)
            instalment_amt = round(principal_part + interest, 2)
        else:
            instalment_amt = instalment
        balance = round(balance - principal_part, 2)
        rows.append({
            "month": month,
            "emi": instalment_amt,
            "interest": interest,
            "principal": principal_part,
            "balance": max(balance, 0.0),
        })
    return rows


def outstanding_after(
    principal: float, annual_rate: float, tenure_months: int, months_paid: int
) -> float:
    """Return the outstanding loan balance after a given number of months paid.

    Returns:
        Outstanding balance, rounded to 2 decimal places. Returns the full
        principal if months_paid <= 0, and 0.0 if months_paid exceeds tenure.
    """
    if months_paid <= 0:
        return round(principal, 2)
    sched = amortisation_schedule(principal, annual_rate, tenure_months)
    if months_paid > len(sched):
        return 0.0
    return sched[months_paid - 1]["balance"]


def remaining_tenure(balance: float, annual_rate: float, instalment: float) -> int:
    """Compute how many more months are needed to clear a balance at a fixed EMI.

    Returns:
        Number of remaining months (rounded up), or 0 if balance <= 0.

    Raises:
        ValueError: If instalment is too small to ever cover the balance's interest.
    """
    # BUG FIX: previously used `annual_rate / 100`, which is the annual rate
    # expressed as a decimal, but the amortisation-inversion formula below
    # expects a monthly rate (consistent with _monthly_rate(), i.e.
    # annual_rate / 1200). Using the annual rate here was off by a factor of
    # 12, causing wildly wrong (or spuriously invalid) results whenever this
    # function was called from prepayment_savings().
    r = _monthly_rate(annual_rate)
    if balance <= 0:
        return 0
    if r == 0:
        return math.ceil(balance / instalment)
    if instalment <= balance * r:
        raise ValueError("instalment too small to repay the loan")
    n = -math.log(1 - balance * r / instalment) / math.log(1 + r)
    return math.ceil(n)


def prepayment_savings(
    principal: float,
    annual_rate: float,
    tenure_months: int,
    prepay_month: int,
    prepay_amount: float,
) -> dict[str, float]:
    """Model a one-time lump-sum prepayment (same EMI, shorter tenure) and work out how many months and how much interest it saves.

    What each variable is doing:
    - instalment: the original EMI amount, unchanged by the prepayment.
    - sched: the full original amortisation schedule (before any prepayment),
      used to look up the balance right before the prepayment is made.
    - balance: the outstanding balance at the end of the month just before
      the prepayment (i.e. what's left to pay off at that point).
    - new_balance: the balance after subtracting the lump-sum prepayment.
    - months_left: how many more months are needed to clear new_balance,
      still paying the same instalment each month (0 if new_balance is
      already paid off).
    - original_left: how many months would have remained if no prepayment
      had been made at all - used to measure months saved.
    - interest_paid_so_far: total interest paid in the months leading up to
      (and including) the prepayment month, from the original schedule.
    - original_interest: total interest that would have been paid over the
      entire original loan, with no prepayment.
    - new_total: total amount actually paid under the new plan - the
      instalments paid before the prepayment, plus the prepayment itself,
      plus the instalments paid afterwards until the loan is cleared.
    - new_interest: total interest paid under the new plan (new_total minus
      the original principal).

    Returns:
        A dict with keys: "emi", "months_saved", "new_tenure",
        "interest_saved", "interest_paid_before_prepayment".
    """
    instalment = emi(principal, annual_rate, tenure_months)
    sched = amortisation_schedule(principal, annual_rate, tenure_months)
    balance = sched[prepay_month - 1]["balance"]
    new_balance = balance - prepay_amount
    if new_balance <= 0:
        months_left = 0
    else:
        months_left = remaining_tenure(new_balance, annual_rate, instalment)
    original_left = tenure_months - prepay_month
    interest_paid_so_far = sum(row["interest"] for row in sched[:prepay_month])
    original_interest = total_interest(principal, annual_rate, tenure_months)
    new_total = instalment * prepay_month + prepay_amount + instalment * months_left
    new_interest = new_total - principal
    return {
        "emi": instalment,
        "months_saved": original_left - months_left,
        "new_tenure": prepay_month + months_left,
        "interest_saved": round(original_interest - new_interest, 2),
        "interest_paid_before_prepayment": round(interest_paid_so_far, 2),
    }


def compare_offers(principal: float, offers: list[dict]) -> list[dict]:
    """Compare multiple loan offers for the same principal and rank by total cost.

    Given the same principal amount, this evaluates several competing loan
    offers (e.g. from different banks) side by side. For each offer it
    computes the EMI, total interest, and any processing fee, then combines
    interest and fees into a single "total_cost" figure so offers can be
    ranked fairly even if one has a lower rate but a higher fee.

    Returns:
        A list of dicts (one per offer) with keys "bank", "emi",
        "total_interest", "processing_fee", "total_cost", sorted ascending
        by "total_cost".
    """
    out = []
    for o in offers:
        e = emi(principal, o["rate"], o["tenure"])
        ti = total_interest(principal, o["rate"], o["tenure"])
        fee = o.get("processing_fee_pct", 0) * principal / 100
        out.append({
            "bank": o["bank"],
            "emi": e,
            "total_interest": ti,
            "processing_fee": round(fee, 2),
            "total_cost": round(ti + fee, 2),
        })
    out.sort(key=lambda x: x["total_cost"])
    return out


def eligible_amount(
    monthly_income: float,
    existing_emis: float,
    annual_rate: float,
    tenure_months: int,
    foir: float = 0.5,
) -> float:
    """Estimate the maximum loan principal a borrower is eligible for.

    Lenders typically cap a borrower's total EMI obligations at a fixed
    percentage of their monthly income, known as the Fixed Obligation to
    Income Ratio (FOIR). This works out how much spare EMI capacity the
    borrower has after their existing EMIs, then inverts the EMI formula
    to figure out the largest principal that capacity could support.

    Returns:
        The maximum eligible principal, rounded to 2 decimal places, or 0.0
        if the borrower has no available EMI capacity.
    """
    available = monthly_income * foir - existing_emis
    if available <= 0:
        return 0.0
    r = _monthly_rate(annual_rate)
    if r == 0:
        return round(available * tenure_months, 2)
    f = (1 + r) ** tenure_months
    return round(available * (f - 1) / (r * f), 2)


def format_inr(amount: float) -> str:
    """Format a number as an Indian-Rupee currency string.

    Applies Indian-style digit grouping (lakhs/crores, i.e. groups of 2
    digits after the first group of 3) instead of the usual thousands
    grouping, and prefixes the result with the rupee symbol.

    Returns:
        A formatted string, e.g. "₹10,00,000.00" or "-₹500.00".
    """
    neg = amount < 0
    amount = abs(round(amount, 2))
    whole, frac = f"{amount:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    return ("-" if neg else "") + "₹" + whole + "." + frac


def schedule_to_csv(rows: list[dict], path: str) -> None:
    """Write a schedule to a CSV file.

    Takes the list of row dicts produced by amortisation_schedule() and
    writes them out as a plain CSV file with one row per month, so the
    schedule can be opened in a spreadsheet or shared outside Python.

    Returns:
        None.
    """
    with open(path, "w") as fh:
        fh.write("month,emi,interest,principal,balance\n")
        for r in rows:
            fh.write(f'{r["month"]},{r["emi"]},{r["interest"]},{r["principal"]},{r["balance"]}\n')


def summary(
    principal: float,
    annual_rate: float,
    tenure_months: int,
    start: date | None = None,
) -> dict[str, str]:
    """Produce a summary of a loan.

    Pulls together the key loan figures (EMI, total interest, total
    payment) and formats them as display-ready strings, along with the
    projected date of the final EMI, so they can be shown directly to a
    user without further processing.

    Returns:
        A dict of formatted strings with keys: "principal", "rate", "tenure",
        "emi", "total_interest", "total_payment", "last_emi", "currency".
    """
    start = start or date.today()
    e = emi(principal, annual_rate, tenure_months)
    end_year = start.year + (start.month - 1 + tenure_months) // 12
    end_month = (start.month - 1 + tenure_months) % 12 + 1
    return {
        "principal": format_inr(principal),
        "rate": f"{annual_rate}% p.a.",
        "tenure": f"{tenure_months} months",
        "emi": format_inr(e),
        "total_interest": format_inr(total_interest(principal, annual_rate, tenure_months)),
        "total_payment": format_inr(total_payment(principal, annual_rate, tenure_months)),
        "last_emi": f"{end_year}-{end_month:02d}",
        "currency": DEFAULT_CURRENCY,
    }
