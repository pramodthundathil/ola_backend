from decimal import Decimal
from .models import FinancePlan
from customer. models import DecisionEngineResult, CreditConfig
import logging


logger = logging.getLogger(__name__)




# ==================================================
#  1st step (FOR RUN TEMPERAROY TABLE) 
# ==================================================

class AutoDecisionEngine:
    """
    Handles computation of financing plan details for a given TempFinancePlan.
    """

    def __init__(self, temp_plan):
        self.plan = temp_plan

    def run(self):
        """
        Runs all calculations and updates the TempFinancePlan object fields.
        """
        # Step 1: Determine risk tier
         # 1️ Determine Risk Tier
        try:
            credit_config = CreditConfig.objects.last() 
            tier_a_min_score = credit_config.tier_a_min_score
            tier_b_min_score = credit_config.tier_b_min_score
            tier_c_min_score = credit_config.tier_c_min_score
            self.plan.determine_risk_tier(tier_a_min_score,tier_b_min_score , tier_c_min_score)
        except:
            self.plan.determine_risk_tier()

        rules = self.plan.get_tier_rules() or {}

        self.plan.payment_capacity_factor = Decimal(rules.get("payment_capacity_factor", "0.00"))
        self.plan.minimum_down_payment_percentage = Decimal(rules.get("min_down_payment", "0.00"))
        self.plan.high_end_extra_percentage = Decimal(rules.get("high_end_extra", "0.00"))

        # Optional: log warning if any are missing
        if not rules.get("payment_capacity_factor"):
            logger.warning(f"Missing 'payment_capacity_factor' in tier rules for plan ID {self.plan.id}")


        # Step 3: Calculate maximum allowed installment
        self.plan.maximum_allowed_installment = (
            self.plan.customer_monthly_income * self.plan.payment_capacity_factor
        )

        # Step 4: Allowed plans (with intervals)
        allowed_terms = rules["allowed_terms"]
        intervals = [15, 30]
        plans = [
            {"months": term, "interval_days": interval}
            for term in allowed_terms
            for interval in intervals
        ]
        self.plan.allowed_plans = plans

        # Step 5: Save
        self.plan.save()

        return self.plan 
    

# ==================================================
#  2nd step (FOR FINANCEPLAN)
# ==================================================
class DecisionEngine:
    """
    Engine to make financing decisions based on APC, income, device price, and term.
    Uses helper methods from FinancePlan model.
    """

    def __init__(self, finance_plan):
        self.plan = finance_plan

    def run(self, dynamic_adjustment=True):
        """
        Executes the full decision logic step by step.
        """
        # 1️ Determine Risk Tier
        try:
            credit_config = CreditConfig.objects.last() 
            tier_a_min_score = credit_config.tier_a_min_score
            tier_b_min_score = credit_config.tier_b_min_score
            tier_c_min_score = credit_config.tier_c_min_score
            self.plan.determine_risk_tier(tier_a_min_score,tier_b_min_score , tier_c_min_score)
        except:
            self.plan.determine_risk_tier()

        # 2️ Check if device is high-end
        self.plan.is_high_end_device = self.plan.device_price > Decimal('300.00')

        self.plan.get_tier_rules()

        # 3️ Calculate Minimum Down Payment
        self.plan.calculate_minimum_down_payment()

        # biometric_conf = getattr(
        #     getattr(self.credit_application.customer, "identity_verification", None),
        #     "face_match_score",
        #     0
        # )
        biometric_conf=100
        reference_score = 100
        geo_behavior = 100

        # 4️ Calculate EMI (monthly installment)
        self.plan.calculate_emi()

        # 5️ Check Payment Capacity
        self.plan.check_payment_capacity()

        # 6️ Validate Tier Conditions
        self.plan.validate_conditions()

        # 7️ Calculate Final Score
        self.plan.calculate_final_score(
            biometric_confidence=biometric_conf,
            references_score=reference_score,
            geo_behavior=geo_behavior
        )


        # 8️ Handle Dynamic Adjustment (if needed)
        if dynamic_adjustment and self.plan.score_status == 'CONDITIONAL':
            self.dynamic_adjustment()

        # Save final results
        self.plan.save()
        
        # 9️ Save detailed result in DecisionEngineResult
        self.save_decision_result()

        return self.plan

# ============ DYNAMIC ADJESTMENT===========

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
                #  APC Score
                'apc_score_value': self.plan.apc_score,
                'apc_score_passed': self.plan.risk_tier != 'TIER_D',

                #  Internal Score
                'internal_score_value': getattr(self.plan, 'internal_score', None),
                'internal_score_passed': getattr(self.plan, 'internal_score_passed', False),

                #  Identity Validation
                'document_valid': getattr(self.plan, 'document_valid', False),
                'biometric_valid': getattr(self.plan, 'biometric_valid', False),
                'liveness_check_passed': getattr(self.plan, 'liveness_check_passed', False),
                'identity_validation_passed': getattr(self.plan, 'identity_validation_passed', False),

                #  Payment Capacity
                'income_amount': self.plan.customer_monthly_income,
                'installment_amount': self.plan.monthly_installment,
                'installment_to_income_ratio': self.plan.installment_to_income_ratio,
                'payment_capacity_passed': self.plan.payment_capacity_passed,

                #  Personal References
                'valid_references_count': getattr(self.plan, 'valid_references_count', 0),
                'references_passed': getattr(self.plan, 'references_passed', False),

                #  Anti-fraud
                'duplicate_id_check': getattr(self.plan, 'duplicate_id_check', True),
                'duplicate_phone_check': getattr(self.plan, 'duplicate_phone_check', True),
                'duplicate_imei_check': getattr(self.plan, 'duplicate_imei_check', True),
                'anti_fraud_passed': getattr(self.plan, 'anti_fraud_passed', False),
                'anti_fraud_notes': getattr(self.plan, 'anti_fraud_notes', ''),

                #  Commercial Conditions
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
