

from decimal import Decimal
from .models import FinancePlan
from customer. models import DecisionEngineResult


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
        
        # 9️⃣ Save detailed result in DecisionEngineResult
        self.save_decision_result()

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

    """
    for save decision result in customer/DecisionEngineResult model
    """

    def save_decision_result(self):
        """Create and save a DecisionEngineResult from the FinancePlan"""
        result, created = DecisionEngineResult.objects.update_or_create(
            credit_application=self.plan.credit_application,
            defaults={
                # 1️⃣ APC Score
                'apc_score_value': self.plan.apc_score,
                'apc_score_passed': self.plan.risk_tier != 'TIER_D',

                # 2️⃣ Internal Score
                'internal_score_value': getattr(self.plan, 'internal_score', None),
                'internal_score_passed': getattr(self.plan, 'internal_score_passed', False),

                # 3️⃣ Identity Validation
                'document_valid': getattr(self.plan, 'document_valid', False),
                'biometric_valid': getattr(self.plan, 'biometric_valid', False),
                'liveness_check_passed': getattr(self.plan, 'liveness_check_passed', False),
                'identity_validation_passed': getattr(self.plan, 'identity_validation_passed', False),

                # 4️⃣ Payment Capacity
                'income_amount': self.plan.customer_monthly_income,
                'installment_amount': self.plan.monthly_installment,
                'installment_to_income_ratio': self.plan.installment_to_income_ratio,
                'payment_capacity_passed': self.plan.payment_capacity_passed,

                # 5️⃣ Personal References
                'valid_references_count': getattr(self.plan, 'valid_references_count', 0),
                'references_passed': getattr(self.plan, 'references_passed', False),

                # 6️⃣ Anti-fraud
                'duplicate_id_check': getattr(self.plan, 'duplicate_id_check', True),
                'duplicate_phone_check': getattr(self.plan, 'duplicate_phone_check', True),
                'duplicate_imei_check': getattr(self.plan, 'duplicate_imei_check', True),
                'anti_fraud_passed': getattr(self.plan, 'anti_fraud_passed', False),
                'anti_fraud_notes': getattr(self.plan, 'anti_fraud_notes', ''),

                # 7️⃣ Commercial Conditions
                'initial_payment_percentage': self.plan.down_payment_percentage,
                'loan_term_months': self.plan.selected_term,
                'is_high_end_device': self.plan.is_high_end_device,
                'commercial_conditions_passed': getattr(self.plan, 'conditions_met', False),

                # Final Decision
                'total_score': getattr(self.plan, 'final_score', 0),
                'final_decision': self.plan.score_status or 'REJECTED',
                'rejection_reasons': getattr(self.plan, 'rejection_reasons', []),
            }
        )
        return result
