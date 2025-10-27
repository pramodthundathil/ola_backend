from decimal import Decimal
from .models import FinancePlan
from customer. models import DecisionEngineResult



class DecisionEngine:
    """
    Calculates financing options for all allowed terms without saving to DB.
    Returns a list of dicts with all fields of the temp finance plan.
    """
    interval_options = [15, 30]

    def __init__(self, temp_plan):
        self.plan = temp_plan
        self.results = []

    def run(self, dynamic_adjustment=True):
        # 1️⃣ Determine risk tier
        self.plan.determine_risk_tier()

        # 2️⃣ Check high-end device
        self.plan.is_high_end_device = self.plan.device_price > Decimal('300.00')

        # 3️⃣ Calculate minimum down payment
        self.plan.calculate_minimum_down_payment()

        # 4️⃣ Get allowed terms
        allowed_terms = self.plan.get_tier_rules()['allowed_terms']

        # fetch  scores of geo_behavior,references_score,biometric_confidence

        biometric_conf = getattr(
            getattr(self.credit_application.customer, "identity_verification", None),
            "face_match_score",
            0
        )

        # reference_score = getattr(
        #     getattr(getattr(self.plan, 'credit_application', None), 'user', None),
        #     'reference_score',
        #     0
        # )
        # geo_behavior = getattr(
        #     getattr(getattr(self.plan, 'credit_application', None), 'user', None),
        #     'geo_behavior_score',
        #     0
        # )
        reference_score = 0
        geo_behavior = 0

        for term in allowed_terms:
            for interval in self.interval_options:
                # Temporarily assign term and interval to the plan
                self.plan.selected_term = term
                self.plan.installment_frequency_days = interval

                # Calculate EMI, capacity, conditions, final score
                self.plan.calculate_emi()
                self.plan.check_payment_capacity()
                self.plan.validate_conditions()
                self.plan.calculate_final_score(
                    biometric_confidence=biometric_conf,
                    references_score=reference_score,
                    geo_behavior=geo_behavior
                )

                # Handle dynamic adjustment
                if dynamic_adjustment and self.plan.score_status == 'CONDITIONAL':
                    self.plan.dynamic_adjustment()

                # Convert plan to dict with **all fields**
                term_result = {
                    field.name: getattr(self.plan, field.name)
                    for field in self.plan._meta.get_fields()
                    if hasattr(self.plan, field.name)
                }

                # Ensure interval is included explicitly
                term_result['installment_frequency_days'] = interval

                # Add to results
                self.results.append(term_result)

        # Prepare output
        output = list(self.results)
        self.results.clear()  

        return output



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
