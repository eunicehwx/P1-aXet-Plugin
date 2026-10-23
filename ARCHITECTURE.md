# loan-calc architecture

The `loan-calc` repo is very small. Nearly all business logic lives in `loan-calc/loan_calc/calculator.py`. The other files mainly expose or document that logic.

## What each file contains and what it is trying to do

### `loan-calc/loan_calc/calculator.py`
This is the core module. It implements:
- EMI calculation
- total payment / total interest
- amortisation schedule generation
- outstanding balance lookup
- prepayment savings estimation
- offer comparison
- loan eligibility estimation
- INR formatting
- CSV export
- summary generation

This is the file where the “wrong numbers” bugs are most likely to be.

### `loan-calc/loan_calc/__init__.py`
```python
from .calculator import *  # noqa
```

This re-exports everything from `calculator.py`, so callers can do:

```python
from loan_calc import emi, summary
```

instead of importing from `loan_calc.calculator`.

### `loan-calc/cli.py`
This is a simple command-line interface around the library. It:
- accepts principal, rate, and tenure from terminal arguments
- prints a JSON summary
- optionally prints the amortisation schedule
- optionally prints prepayment savings

So this file is not doing financial math itself; it is only calling functions from the module.

### `loan-calc/README.md`
This explains the project at a high level:
- what the package is for
- how to set it up
- example CLI commands
- where tests should go

It also explicitly says the repo contains wrong-number bugs and lacks tests.

## Function-by-function explanation

### `DEFAULT_CURRENCY = "INR"`
A constant used by `summary()` to label the output currency.

### `_monthly_rate(annual_rate)`
Converts an annual percentage rate into a monthly decimal rate.

Example:
- `9` means 9% per year
- monthly rate should be `9 / 1200 = 0.0075`

It exists as a shared helper so EMI and schedule calculations use the same monthly rate.

### `emi(principal, annual_rate, tenure_months)`
Computes the Equated Monthly Instalment (EMI): the fixed monthly payment needed to repay a loan.

Behavior:
1. Rejects invalid tenure or principal.
2. Converts annual rate to monthly rate using `_monthly_rate`.
3. If rate is zero, returns `principal / tenure_months`.
4. Otherwise uses the standard EMI formula:
   `P * r * (1+r)^n / ((1+r)^n - 1)`

This is trying to produce the standard fixed monthly instalment for a reducing-balance loan.

### `total_payment(principal, annual_rate, tenure_months)`
Returns the total amount paid over the loan:
- one EMI × number of months

This answers: “How much will I pay in total?”

### `total_interest(principal, annual_rate, tenure_months)`
Returns total interest paid:
- total payment − principal

This answers: “How much of my repayment is interest?”

### `amortisation_schedule(principal, annual_rate, tenure_months)`
Builds a month-by-month repayment breakdown.

Each row has:
- `month`
- `emi`
- `interest`
- `principal`
- `balance`

For each month it:
1. calculates interest on current balance
2. computes principal repaid as `EMI - interest`
3. reduces the balance
4. stores the row

This is trying to generate the standard reducing-balance amortisation table.

### `outstanding_after(principal, annual_rate, tenure_months, months_paid)`
Returns remaining balance after a given number of monthly payments.

Behavior:
- if `months_paid <= 0`, returns original principal
- otherwise builds the amortisation schedule and returns the balance at that point
- if months exceed the schedule, returns `0.0`

This answers: “How much loan is still outstanding after X EMIs?”

### `remaining_tenure(balance, annual_rate, instalment)`
Given:
- current balance
- annual rate
- fixed instalment

it estimates how many months remain to repay the loan.

Behavior:
- zero or negative balance → `0`
- zero interest → `ceil(balance / instalment)`
- otherwise uses the rearranged EMI formula to solve for number of months

This answers: “If I keep paying this EMI on the current balance, how many months are left?”

### `prepayment_savings(principal, annual_rate, tenure_months, prepay_month, prepay_amount)`
Estimates the effect of making a lump-sum prepayment while keeping the EMI unchanged and shortening tenure.

Behavior:
1. computes original EMI
2. computes original schedule
3. finds the balance after the chosen month
4. subtracts the prepayment amount
5. computes revised remaining tenure
6. compares original vs new loan length
7. estimates interest saved

Returns:
- `emi`
- `months_saved`
- `new_tenure`
- `interest_saved`
- `interest_paid_before_prepayment`

This answers: “If I prepay this amount in month X, how much sooner do I finish and how much interest do I save?”

### `compare_offers(principal, offers)`
Compares multiple loan offers.

For each offer it computes:
- EMI
- total interest
- processing fee
- total cost

Then sorts by lowest `total_cost`.

This is trying to help users compare lenders on full cost, not just interest rate.

### `eligible_amount(monthly_income, existing_emis, annual_rate, tenure_months, foir=0.5)`
Estimates the maximum loan principal the borrower may be eligible for.

Behavior:
1. computes available EMI capacity from income and FOIR
2. if non-positive, returns `0`
3. if zero interest, eligible principal is `available × tenure`
4. otherwise inverts the EMI formula to solve for principal

This answers: “Given my income and current obligations, how much loan can I support?”

### `format_inr(amount)`
Formats a number as Indian Rupee text, for example:
- `1234567.8` → `₹12,34,567.80`

It handles:
- negatives
- 2-decimal rounding
- Indian comma grouping

This is purely presentation logic.

### `schedule_to_csv(rows, path)`
Writes amortisation schedule rows to a CSV file with header:
- `month,emi,interest,principal,balance`

This is trying to export the schedule for spreadsheets or reporting.

### `summary(principal, annual_rate, tenure_months, start=None)`
Builds a display-friendly summary dictionary.

It returns:
- formatted principal
- interest rate string
- tenure string
- formatted EMI
- formatted total interest
- formatted total payment
- last EMI month
- currency code

This is intended for CLI/UI display rather than raw math use.

## How the module fits together

Core flow:
- `_monthly_rate()` feeds `emi()`, `amortisation_schedule()`, `eligible_amount()`
- `emi()` feeds `total_payment()`, `amortisation_schedule()`, `compare_offers()`, `summary()`, `prepayment_savings()`
- `total_payment()` feeds `total_interest()`
- `amortisation_schedule()` feeds `outstanding_after()` and `prepayment_savings()`
- `remaining_tenure()` feeds `prepayment_savings()`

So a small error in rate handling or schedule generation can cascade into several user-visible wrong numbers.

## Most suspicious numeric areas, without fixing anything yet

The most likely bug locations are:
- `_monthly_rate()`
- `amortisation_schedule()`
- `remaining_tenure()`
- `prepayment_savings()`

Those are the functions most directly involved in precision, monthly compounding, schedule construction, and prepayment math.

No code has been changed.
