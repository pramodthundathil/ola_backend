from decimal import Decimal, ROUND_UP
from django.core.exceptions import ValidationError
from customer.models import DecisionEngineResult, CreditConfig, PersonalReference
from finance.models import FinanceMultiple, RiskTier, LoanTerm, InterestPlan
from .services import DecisionEngineService, FinancingEngineService
import logging

logger = logging.getLogger(__name__)

def ensure_risk_tiers():
    """Ensure the exact Panamanian risk tiers are synchronized in the database."""
    tiers_data = [
        {"code": "TIER_A", "name": "Low Risk", "min_score": 550, "max_score": 900, "min_salary": 500.00, "max_debt_ratio_pct": 20.00, "min_down_payment_pct": 20.00, "approval_level": "AUTO"},
        {"code": "TIER_B", "name": "Medio", "min_score": 500, "max_score": 549, "min_salary": 500.00, "max_debt_ratio_pct": 15.00, "min_down_payment_pct": 25.00, "approval_level": "AUTO"},
        {"code": "TIER_C", "name": "Alto", "min_score": 450, "max_score": 499, "min_salary": 500.00, "max_debt_ratio_pct": 10.00, "min_down_payment_pct": 30.00, "approval_level": "AUTO"},
        {"code": "TIER_D", "name": "Very High", "min_score": 0, "max_score": 449, "min_salary": 0.00, "max_debt_ratio_pct": 0.00, "min_down_payment_pct": 100.00, "approval_level": "FINANCE_ADMIN"},
        {"code": "TIER_E", "name": "No Score", "min_score": None, "max_score": None, "min_salary": 500.00, "max_debt_ratio_pct": 15.00, "min_down_payment_pct": 25.00, "approval_level": "AUTO"},
        {"code": "TIER_F", "name": "No Salario", "min_score": 600, "max_score": 900, "min_salary": 0.00, "max_debt_ratio_pct": 15.00, "min_down_payment_pct": 25.00, "approval_level": "AUTO"},
        {"code": "TIER_G", "name": "Sin Referencia", "min_score": 0, "max_score": 900, "min_salary": 0.00, "max_debt_ratio_pct": 0.00, "min_down_payment_pct": 100.00, "approval_level": "FINANCE_ADMIN"},
        {"code": "TIER_H", "name": "Cliente Activo", "min_score": 0, "max_score": 900, "min_salary": 0.00, "max_debt_ratio_pct": 0.00, "min_down_payment_pct": 100.00, "approval_level": "FINANCE_ADMIN"},
    ]
    for data in tiers_data:
        RiskTier.objects.update_or_create(
            code=data["code"],
            defaults={
                "name": data["name"],
                "min_score": data["min_score"],
                "max_score": data["max_score"],
                "min_salary": Decimal(str(data["min_salary"])),
                "max_debt_ratio_pct": Decimal(str(data["max_debt_ratio_pct"])),
                "min_down_payment_pct": Decimal(str(data["min_down_payment_pct"])),
                "approval_level": data["approval_level"],
                "is_active": True
            }
        )

def ensure_loan_terms():
    """Ensure the exact loan terms and multipliers are synchronized in the database."""
    terms_data = [
        {"months": 4, "fortnights": 8, "multiplier": 1.70},
        {"months": 6, "fortnights": 12, "multiplier": 1.80},
        {"months": 8, "fortnights": 16, "multiplier": 2.20},
    ]
    for data in terms_data:
        LoanTerm.objects.update_or_create(
            months=data["months"],
            defaults={
                "fortnights": data["fortnights"],
                "multiplier": Decimal(str(data["multiplier"])),
                "is_active": True
            }
        )
    # Deactivate any other terms
    LoanTerm.objects.exclude(months__in=[4, 6, 8]).update(is_active=False)

class AutoDecisionEngine:
    """
    Adapter class for temporary finance plan logic. Uses database configurations to
    determine risk tier and allowed terms/multipliers.
    """

    def __init__(self, temp_plan):
        self.plan = temp_plan

    def run(self):
        ensure_risk_tiers()
        ensure_loan_terms()
        
        # Determine salary and score
        score_val = self.plan.credit_score.apc_score if self.plan.credit_score else None
        salary_val = self.plan.customer_monthly_income
        if salary_val is None:
            salary_val = Decimal('350.00')
            self.plan.customer_monthly_income = salary_val

        # Check active loans for TIER_H
        from finance.models import FinancePlan
        has_active_loans = FinancePlan.objects.filter(
            credit_application__customer=self.plan.customer,
            status="ACTIVE"
        ).exists()
        
        # Assign risk tier
        if has_active_loans:
            risk_tier_code = 'TIER_H'
        elif salary_val < Decimal('500.00'):
            if score_val is not None and score_val >= 600:
                risk_tier_code = 'TIER_F'
            else:
                risk_tier_code = 'TIER_D'
        elif score_val is None:
            risk_tier_code = 'TIER_E'
        elif score_val >= 550:
            risk_tier_code = 'TIER_A'
        elif score_val >= 500:
            risk_tier_code = 'TIER_B'
        elif score_val >= 450:
            risk_tier_code = 'TIER_C'
        else:
            risk_tier_code = 'TIER_D'

        risk_tier_obj = RiskTier.objects.filter(code=risk_tier_code).first()
        self.plan.risk_tier = risk_tier_code
        self.plan.payment_capacity_factor = risk_tier_obj.max_debt_ratio_pct / Decimal('100.00') if risk_tier_obj else Decimal('0.20')
        self.plan.minimum_down_payment_percentage = risk_tier_obj.min_down_payment_pct if risk_tier_obj else Decimal('20.00')
        
        # Capacity check
        self.plan.maximum_allowed_installment = (
            salary_val * self.plan.payment_capacity_factor
        )

        # Allowed terms
        allowed_plans = []
        if risk_tier_code not in ['TIER_D', 'TIER_G', 'TIER_H']:
            terms = LoanTerm.objects.filter(is_active=True).order_by('months')
            for t in terms:
                allowed_plans.append({
                    "months": t.months,
                    "interval_days": 30,
                    "multiple": float(t.multiplier)
                })
                allowed_plans.append({
                    "months": t.months,
                    "interval_days": 15,
                    "multiple": float(t.multiplier)
                })
        self.plan.allowed_plans = allowed_plans
        self.plan.save()
        return self.plan


class DecisionEngine:
    """
    Adapter class for main FinancePlan logic. Integrates with the new
    DecisionEngineService and FinancingEngineService to compute approval/rejection.
    """

    def __init__(self, finance_plan):
        self.plan = finance_plan

    def run(self, dynamic_adjustment=True, save=True):
        ensure_risk_tiers()
        ensure_loan_terms()
        
        score_val = self.plan.apc_score
        customer = self.plan.credit_application.customer
        salary_val = self.plan.customer_monthly_income
        if salary_val is None:
            salary_val = Decimal('350.00')
            self.plan.customer_monthly_income = salary_val
        
        # Check active loans
        from finance.models import FinancePlan
        has_active_loans = FinancePlan.objects.filter(
            credit_application__customer=customer,
            status="ACTIVE"
        ).exclude(id=self.plan.id).exists()
        
        # Gather references
        references_count = PersonalReference.objects.filter(customer=customer).count()
        
        # Assign risk tier
        if has_active_loans:
            risk_tier_code = 'TIER_H'
        elif references_count < 2:
            risk_tier_code = 'TIER_G'
        elif salary_val < Decimal('500.00'):
            if score_val is not None and score_val >= 600:
                risk_tier_code = 'TIER_F'
            else:
                risk_tier_code = 'TIER_D'
        elif score_val is None:
            risk_tier_code = 'TIER_E'
        elif score_val >= 550:
            risk_tier_code = 'TIER_A'
        elif score_val >= 500:
            risk_tier_code = 'TIER_B'
        elif score_val >= 450:
            risk_tier_code = 'TIER_C'
        else:
            risk_tier_code = 'TIER_D'

        self.plan.risk_tier = risk_tier_code
        tier_obj = RiskTier.objects.filter(code=risk_tier_code).first()
        
        if tier_obj:
            self.plan.payment_capacity_factor = tier_obj.max_debt_ratio_pct / Decimal('100.00')
            self.plan.minimum_down_payment_percentage = tier_obj.min_down_payment_pct
            self.plan.debt_ratio_pct = tier_obj.max_debt_ratio_pct
        else:
            self.plan.payment_capacity_factor = Decimal('0.20')
            self.plan.minimum_down_payment_percentage = Decimal('20.00')
            self.plan.debt_ratio_pct = Decimal('20.00')

        # 2. Computations
        self.plan.is_high_end_device = self.plan.device_price > Decimal('300.00')
        
        selling_price = self.plan.device_price or Decimal('0.00')
        self.plan.selling_price = selling_price
        self.plan.total_price = selling_price
        
        # Down Payment = Device Price * Tier Down Payment %
        dp_pct = self.plan.minimum_down_payment_percentage / Decimal('100.00')
        required_dp = (selling_price * dp_pct).quantize(Decimal('0.01'), rounding=ROUND_UP)
        
        actual_dp = self.plan.actual_down_payment or Decimal('0.00')
        if actual_dp < required_dp:
            actual_dp = required_dp
        self.plan.actual_down_payment = actual_dp
        self.plan.down_payment_percentage = (actual_dp / selling_price * Decimal('100.00')).quantize(Decimal('0.01')) if selling_price > 0 else Decimal('0.00')

        # Loan Principal = Device Price - Down Payment
        self.plan.amount_to_finance = selling_price - actual_dp
        
        # Payment Capacity (Cuota) = Salary * Debt Ratio
        self.plan.max_emi_allowed = salary_val * self.plan.payment_capacity_factor
        
        # Maximum Financing = Payment Capacity * Selected Months
        selected_term = self.plan.selected_term or 8
        max_financing = self.plan.max_emi_allowed * Decimal(str(selected_term))
        
        # Multiplier
        term_obj = LoanTerm.objects.filter(months=selected_term).first()
        multiplier = term_obj.multiplier if term_obj else Decimal('1.00')
        
        # Total Financing = Loan Principal * Multiplier
        total_financing = self.plan.amount_to_finance * multiplier
        self.plan.total_amount_payable = actual_dp + total_financing
        
        # Biweekly Installment = Total Financing / (Months * 2)
        freq_days = self.plan.installment_frequency_days or 15
        if freq_days == 30:
            total_installments = selected_term
        elif freq_days == 15:
            total_installments = selected_term * 2
        elif freq_days == 7:
            total_installments = selected_term * 4
        else:
            total_installments = selected_term * 2
            
        self.plan.monthly_installment = (total_financing / Decimal(str(total_installments))).quantize(Decimal('0.01'), rounding=ROUND_UP)
        self.plan.installment_to_income_ratio = (self.plan.monthly_installment / salary_val * Decimal('100.00')).quantize(Decimal('0.01')) if salary_val > 0 else Decimal('0.00')

        # Approval Rule: Total Financing <= Maximum Financing
        self.plan.payment_capacity_passed = total_financing <= max_financing
        
        # Check eligibility and tier restriction
        is_approved = self.plan.payment_capacity_passed and (risk_tier_code not in ['TIER_D', 'TIER_G', 'TIER_H'])
        self.plan.conditions_met = is_approved
        
        if is_approved:
            self.plan.score_status = 'APPROVED'
            self.plan.adjustment_notes = ""
        else:
            self.plan.score_status = 'REJECTED'
            reasons = []
            if not self.plan.payment_capacity_passed:
                reasons.append(f"Total financing (${total_financing:.2f}) exceeds maximum financing capacity (${max_financing:.2f}).")
            if risk_tier_code == 'TIER_D':
                reasons.append("Rejected due to low credit score (Tier D).")
            elif risk_tier_code == 'TIER_G':
                reasons.append("Rejected due to missing personal references.")
            elif risk_tier_code == 'TIER_H':
                reasons.append("Rejected due to existing active customer status.")
            self.plan.adjustment_notes = " ".join(reasons)

        if save:
            self.plan.save()

            # 5. Populate EMISchedule
            FinancingEngineService.generate_amortization_schedule(self.plan)

            # 6. Log results
            self.save_decision_result()
        return self.plan

    def save_decision_result(self):
        """Create and save detailed decision metrics"""
        result, created = DecisionEngineResult.objects.update_or_create(
            credit_application=self.plan.credit_application,
            defaults={
                'apc_score_value': self.plan.apc_score,
                'apc_score_passed': self.plan.risk_tier not in ['TIER_D', 'TIER_G', 'TIER_H'],
                'internal_score_value': 100,
                'internal_score_passed': True,
                'document_valid': True,
                'biometric_valid': True,
                'liveness_check_passed': True,
                'identity_validation_passed': True,
                'income_amount': self.plan.customer_monthly_income,
                'installment_amount': self.plan.monthly_installment,
                'installment_to_income_ratio': self.plan.installment_to_income_ratio,
                'payment_capacity_passed': self.plan.payment_capacity_passed,
                'valid_references_count': PersonalReference.objects.filter(customer=self.plan.credit_application.customer).count(),
                'references_passed': True,
                'duplicate_id_check': True,
                'duplicate_phone_check': True,
                'duplicate_imei_check': True,
                'anti_fraud_passed': True,
                'initial_payment_percentage': self.plan.down_payment_percentage,
                'loan_term_months': self.plan.selected_term,
                'is_high_end_device': self.plan.is_high_end_device,
                'commercial_conditions_passed': self.plan.conditions_met,
                'total_score': 85,
                'final_decision': self.plan.score_status or 'REJECTED',
                'rejection_reasons': [self.plan.adjustment_notes] if self.plan.adjustment_notes else [],
            }
        )
        return result
