# loan-calc architecture

This document explains what each file in the loan-calc project does, and walks through every function in the core module in plain language.

## Project layout

The project is small. Almost all of the actual logic lives in one file: `loan_calc/calculator.py`. The other files just expose or document that logic.

- `loan_calc/calculator.py` — the core module with all the EMI, schedule, prepayment, and formatting logic.
- `loan_calc/__init__.py` — re-exports everything from `calculator.py`, so you can write `from loan_calc import emi` instead of `from loan_calc.calculator import emi`.
- `cli.py` — a simple command-line tool that calls into the module. It prints a loan summary, and optionally the full schedule or prepayment savings, based on command-line flags.
- `README.md` — a short project overview: what the package does, how to set it up, and example commands to try.

## What each function does

### `_monthly_rate(annual_rate)`
Turns a yearly interest rate (given as a percentage, like 9 for 9%) into a monthly decimal rate. For example, 9% per year becomes 0.0075 per month. This is a small shared helper used by almost every other function that needs to do interest math, so they all agree on the same rate.

### `emi(principal, annual_rate, tenure_months)`
Works out the EMI: the fixed amount a borrower pays every month to repay a loan.

Steps:
1. Checks that the principal and tenure are positive numbers, and raises an error if not.
2. Converts the yearly rate into a monthly rate using `_monthly_rate`.
3. If the rate is 0%, it just divides the principal evenly across the months.
4. Otherwise, it uses the standard formula for a fixed monthly payment on a reducing-balance loan.

### `total_payment(principal, annual_rate, tenure_months)`
Multiplies the EMI by the number of months to get the total amount the borrower will pay back over the life of the loan.

### `total_interest(principal, annual_rate, tenure_months)`
Takes the total payment and subtracts the original principal, leaving just the interest portion. This answers: "how much of what I'm paying back is interest, rather than the loan itself?"

### `amortisation_schedule(principal, annual_rate, tenure_months)`
Builds a month-by-month breakdown of the loan. For each month, it works out how much of that month's payment is interest, how much goes toward reducing the principal, and what the remaining balance is afterward. This produces a full table from month 1 to the last month of the loan, with the balance reaching zero exactly on the final month.

### `outstanding_after(principal, annual_rate, tenure_months, months_paid)`
Answers: "if someone has already paid a certain number of EMIs, how much do they still owe?" It looks this up from the full amortisation schedule. If no months have been paid yet, it returns the full principal. If more months are asked for than the loan actually has, it returns zero.

### `remaining_tenure(balance, annual_rate, instalment)`
Answers: "if I keep paying the same EMI on this remaining balance, how many more months will it take to pay off?" This is mainly used after someone makes an early repayment and wants to know how much sooner their loan will finish.

### `prepayment_savings(principal, annual_rate, tenure_months, prepay_month, prepay_amount)`
Models what happens when someone makes a one-time extra payment partway through the loan, while keeping their EMI the same. Because the balance drops but the monthly payment doesn't change, the loan finishes earlier. This function works out how many months are saved and how much interest is saved as a result, along with how much interest was already paid before the extra payment was made.

### `compare_offers(principal, offers)`
Takes a list of loan offers (for example, from different banks) for the same loan amount, and works out the EMI, total interest, and any processing fee for each one. It then combines interest and fees into a single "total cost" figure, and sorts the offers from cheapest to most expensive. This helps compare offers fairly even when one has a lower rate but a bigger fee.

### `eligible_amount(monthly_income, existing_emis, annual_rate, tenure_months, foir=0.5)`
Works out the largest loan a borrower could realistically be approved for, based on their income. Lenders usually cap how much of a borrower's income can go toward EMIs (this cap is called FOIR). This function figures out how much spare EMI capacity someone has after their existing payments, then works backward from that to estimate the maximum loan principal it could support.

### `format_inr(amount)`
Formats a plain number as Indian Rupee text, using the comma style used in India (for example, 1234567.8 becomes "₹12,34,567.80" rather than the Western "₹1,234,567.80"). It also handles negative amounts and always shows two decimal places. This function is purely about how numbers are displayed, not about any financial calculation.

### `schedule_to_csv(rows, path)`
Takes the schedule produced by `amortisation_schedule` and saves it as a CSV file with one row per month, so it can be opened in a spreadsheet or shared outside of Python.

### `summary(principal, annual_rate, tenure_months, start=None)`
Puts together a friendly summary of a loan for display purposes: the principal, interest rate, tenure, EMI, total interest, total payment, the date of the last EMI, and the currency. It uses `format_inr` to make all the money values readable.

## How the functions connect

Several functions build on each other rather than doing their own separate math:

- `_monthly_rate` is used by `emi`, `amortisation_schedule`, `remaining_tenure`, and `eligible_amount`, so they all use the same consistent monthly rate.
- `emi` is used by `total_payment`, `amortisation_schedule`, `compare_offers`, `summary`, and `prepayment_savings`.
- `total_payment` is used by `total_interest`.
- `amortisation_schedule` is used by `outstanding_after` and `prepayment_savings`.
- `remaining_tenure` is used by `prepayment_savings`.

Because so many functions depend on `_monthly_rate`, `emi`, and `amortisation_schedule`, a mistake in any one of those three tends to show up as wrong numbers in several different places at once — which matches the kind of bug reports this project was built to investigate.

## Bugs found and fixed

Three bugs were found in the original code, and all three have been fixed (with explanatory comments left in the code at each fix):

1. **`_monthly_rate` was rounding too early.** It used to round the monthly rate to four decimal places before using it in any calculation. This introduced tiny errors into every EMI, interest, schedule, and eligibility number. Fixed by only rounding the final results, not the rate itself.

2. **`amortisation_schedule` was missing the last month.** Its loop stopped one month too early, so the schedule was always one row short and the loan balance never actually reached zero. Fixed by including the final month in the loop.

3. **`remaining_tenure` was using the yearly rate instead of the monthly rate.** This made it off by a factor of 12, which caused wrong (or sometimes invalid) results whenever `prepayment_savings` tried to work out how much time and interest a prepayment would save. Fixed by using the same monthly rate helper as the rest of the module.

## Testing

A full test suite lives in `tests/test_calculator.py`, covering every function along with edge cases such as 0% interest loans, 1-month loans, very large principals, and prepayments larger than the remaining balance. Running the suite with coverage reporting shows 100% of the statements in `calculator.py` are exercised by tests.
