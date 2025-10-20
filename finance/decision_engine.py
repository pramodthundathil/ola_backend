

from decimal import Decimal
from .models import FinancePlan


class DecisionEngine:
    """
    Engine to make financing decisions based on APC, income, device price, and term.
    Uses helper methods from FinancePlan model.
    """

    def __init__(self, finance_plan: FinancePlan):
        self.plan = finance_plan

    def run(self, dynamic_adjustment=True):
        """
        Executes the full decision logic step by step.
        """
        # 1️⃣ Determine Risk Tier
        self.plan.determine_risk_tier()

        # 2️⃣ Check if device is high-end
        self.plan.is_high_end_device = self.plan.device_price > Decimal('300.00')

        # 3️⃣ Calculate Minimum Down Payment
        self.plan.calculate_minimum_down_payment()

        # 4️⃣ Calculate EMI (monthly installment)
        self.plan.calculate_emi()

        # 5️⃣ Check Payment Capacity
        self.plan.check_payment_capacity()

        # 6️⃣ Validate Tier Conditions
        self.plan.validate_conditions()

        # 7️⃣ Calculate Final Score
        self.plan.calculate_final_score()

        # 8️⃣ Handle Dynamic Adjustment (if needed)
        if dynamic_adjustment and self.plan.score_status == 'CONDITIONAL':
            self.dynamic_adjustment()

        # Save final results
        self.plan.save()
        return self.plan

    def dynamic_adjustment(self):
        """
        Adjust plan if conditionally approved:
        - Increase down payment slightly
        - Reduce term if possible
        - Recalculate all dependent values
        """
        adjusted = False
        rules = self.plan.get_tier_rules()

        # Try increasing down payment by 5%
        if self.plan.down_payment_percentage + Decimal('5') <= Decimal('100'):
            self.plan.actual_down_payment += (self.plan.device_price * Decimal('5') / 100)
            self.plan.down_payment_percentage = (
                self.plan.actual_down_payment / self.plan.device_price * Decimal('100')
            )
            adjusted = True

        # Try reducing term (choose smallest allowed term)
        if rules['allowed_terms']:
            min_term = min(rules['allowed_terms'])
            if self.plan.selected_term > min_term:
                self.plan.selected_term = min_term
                adjusted = True

        # If adjustments were made, recalculate everything
        if adjusted:
            self.plan.amount_to_finance = self.plan.device_price - self.plan.actual_down_payment
            self.plan.calculate_emi()
            self.plan.total_amount_payable = self.plan.actual_down_payment + (
                self.plan.monthly_installment * self.plan.selected_term
            )
            self.plan.check_payment_capacity()
            self.plan.validate_conditions()
            self.plan.calculate_final_score()
