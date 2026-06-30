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

class AutoDecisionEngine:
    """
    Adapter class for temporary finance plan logic. Uses database configurations to
    determine risk tier and allowed terms/multipliers.
    """

    def __init__(self, temp_plan):
        self.plan = temp_plan

    def run(self):
        ensure_risk_tiers()
        
        # 1. Determine Risk Tier
        score_val = self.plan.credit_score.apc_score if self.plan.credit_score else None
        
        risk_tier_obj = None
        if score_val is not None:
            risk_tier_obj = RiskTier.objects.filter(
                min_score__lte=score_val,
                max_score__gte=score_val,
                is_active=True
            ).first()
            
        if not risk_tier_obj:
            if score_val is None:
                risk_tier_obj = RiskTier.objects.filter(code='TIER_E', is_active=True).first()
            else:
                risk_tier_obj = RiskTier.objects.filter(code='TIER_D', is_active=True).first()
                
        if not risk_tier_obj:
            risk_tier_obj = RiskTier.objects.filter(code='TIER_D').first()

        # If monthly income is None, default to Decimal('350.00')
        if self.plan.customer_monthly_income is None:
            self.plan.customer_monthly_income = Decimal('350.00')

        # If income is below minimum salary or is the fallback default, override risk tier to TIER_F (No Salario)
        min_salary = risk_tier_obj.min_salary if risk_tier_obj else Decimal('500.00')
        if self.plan.customer_monthly_income < min_salary:
            tier_f_obj = RiskTier.objects.filter(code='TIER_F', is_active=True).first()
            if tier_f_obj:
                risk_tier_obj = tier_f_obj

        # Hard reject if TIER_F (No Salario) and score drops below 600
        if risk_tier_obj and risk_tier_obj.code == 'TIER_F':
            if score_val is None or score_val < 600:
                risk_tier_obj = RiskTier.objects.filter(code='TIER_D').first()

        self.plan.risk_tier = risk_tier_obj.code if risk_tier_obj else 'TIER_D'
        self.plan.payment_capacity_factor = risk_tier_obj.max_debt_ratio_pct / Decimal('100.00') if risk_tier_obj else Decimal('0.20')
        self.plan.minimum_down_payment_percentage = risk_tier_obj.min_down_payment_pct if risk_tier_obj else Decimal('20.00')
        
        # 2. Capacity Check
        self.plan.maximum_allowed_installment = (
            self.plan.customer_monthly_income * self.plan.payment_capacity_factor
        )

        # 3. Allowed Terms and Multipliers from DB configurations
        allowed_plans = []
        terms = LoanTerm.objects.filter(is_active=True).order_by('months')
        for t in terms:
            allowed_plans.append({
                "months": t.months,
                "interval_days": 30,  # default monthly
                "multiple": float(t.multiplier)
            })
            allowed_plans.append({
                "months": t.months,
                "interval_days": 15,  # fortnightly
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
        
        score_val = self.plan.apc_score
        customer = self.plan.credit_application.customer
        
        # Gather references
        references = list(PersonalReference.objects.filter(customer=customer))
        
        # 1. Run eligibility rules from new services
        eligibility = DecisionEngineService.evaluate_eligibility(
            customer=customer,
            income=self.plan.customer_monthly_income,
            existing_obligations=Decimal('150.00'),  # standard panama average
            score_val=score_val,
            employer_name=getattr(customer, 'employer', None),
            references=references,
            exclude_application_id=self.plan.credit_application.id
        )
        
        self.plan.risk_tier = eligibility['risk_tier']
        
        # Get matching RiskTier model parameters
        tier_obj = RiskTier.objects.filter(code=self.plan.risk_tier).first()
        
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
        
        # Calculate pricing details
        self.plan.cash_price = (self.plan.device.minimum_price_to_sell if (self.plan.device and self.plan.device.minimum_price_to_sell is not None) else self.plan.device_price)
        self.plan.selling_price = (self.plan.device.maximum_price if (self.plan.device and self.plan.device.maximum_price is not None) else self.plan.device_price)
        
        # Compute total price including fees/insurance/accessories/warranty
        insurance = self.plan.insurance or Decimal('0.00')
        accessories = self.plan.accessories or Decimal('0.00')
        warranty = self.plan.warranty or Decimal('0.00')
        selling_price = self.plan.selling_price or Decimal('0.00')
        
        self.plan.total_price = Decimal(str(selling_price)) + Decimal(str(insurance)) + Decimal(str(accessories)) + Decimal(str(warranty))
        self.plan.amount_to_finance = self.plan.total_price - Decimal(str(self.plan.actual_down_payment or Decimal('0.00')))
        
        # Capacity validation (direct max debt cap formula: max_emi_allowed = Endeudamiento × Salario)
        self.plan.max_emi_allowed = self.plan.customer_monthly_income * self.plan.payment_capacity_factor
        self.plan.available_capacity = self.plan.customer_monthly_income - Decimal('150.00')  # less existing obligations

        # 3. Calculate EMI
        term_obj = LoanTerm.objects.filter(months=self.plan.selected_term).first()
        multiplier = term_obj.multiplier if term_obj else None
        
        plan_obj = InterestPlan.objects.filter(loan_term=term_obj, is_active=True).first()
        if plan_obj and plan_obj.risk_multiplier:
            multiplier = plan_obj.risk_multiplier
            
        res = FinancingEngineService.calculate_emi(
            principal=self.plan.amount_to_finance,
            term_months=self.plan.selected_term,
            rate_pct=Decimal('10.00'),  # 10% default flat rate
            method='FLAT',
            multiplier=multiplier
        )
        
        freq_days = self.plan.installment_frequency_days or 30
        if freq_days == 30:
            total_installments = self.plan.selected_term
        elif freq_days == 15:
            total_installments = self.plan.selected_term * 2
        elif freq_days == 7:
            total_installments = self.plan.selected_term * 4
        elif freq_days == 3:
            total_installments = self.plan.selected_term * 8
        else:
            total_installments = int(self.plan.selected_term * 30 / freq_days)

        if multiplier is None or multiplier <= 0:
            multiplier = Decimal('1.2')
        total_repayment = self.plan.amount_to_finance * Decimal(str(multiplier))
        
        # Save actual per-installment amount in monthly_installment field
        self.plan.monthly_installment = (total_repayment / Decimal(str(total_installments))).quantize(Decimal('0.01'), rounding=ROUND_UP)
        self.plan.total_amount_payable = self.plan.actual_down_payment + total_repayment
        
        # Check Capacity limits based on monthly equivalent emi
        monthly_emi = res['monthly_emi'].quantize(Decimal('1'), rounding=ROUND_UP)
        self.plan.installment_to_income_ratio = (monthly_emi / self.plan.customer_monthly_income) * Decimal('100.00')
        self.plan.payment_capacity_passed = monthly_emi <= self.plan.max_emi_allowed

        # 4. Final approval decision and counter-offer cure lever logic
        if not self.plan.payment_capacity_passed:
            # Lever 1: Check if another Loan Term Naturally Passes
            passing_terms = []
            all_terms = LoanTerm.objects.filter(is_active=True).order_by('months')
            for t in all_terms:
                t_mult = t.multiplier
                t_plan = InterestPlan.objects.filter(loan_term=t, is_active=True).first()
                if t_plan and t_plan.risk_multiplier:
                    t_mult = t_plan.risk_multiplier
                    
                t_res = FinancingEngineService.calculate_emi(
                    principal=self.plan.amount_to_finance,
                    term_months=t.months,
                    rate_pct=Decimal('10.00'),
                    method='FLAT',
                    multiplier=t_mult
                )
                t_emi = t_res['monthly_emi'].quantize(Decimal('1'), rounding=ROUND_UP)
                if t_emi <= self.plan.max_emi_allowed:
                    passing_terms.append(t.months)
            
            if passing_terms:
                self.plan.conditions_met = True
                self.plan.requires_adjustment = True
                self.plan.score_status = 'CONDITIONAL'
                self.plan.adjustment_notes = f"EMI exceeds cap. Approved counter-offer terms: {', '.join(map(str, passing_terms))} months."
            else:
                # Lever 2: Solve for Down Payment Cure Strategy
                if multiplier and multiplier > 0:
                    monto_max_fin = (self.plan.max_emi_allowed * self.plan.selected_term) / Decimal(str(multiplier))
                    monto_max_fin = monto_max_fin.quantize(Decimal('0.01'))
                    
                    abono_req = self.plan.total_price - monto_max_fin
                    abono_pct_req = (abono_req / self.plan.total_price) * Decimal('100.00')
                    
                    max_cure_limit = Decimal('55.00') if self.plan.risk_tier == 'TIER_C' else Decimal('50.00')
                    
                    if abono_pct_req <= max_cure_limit:
                        self.plan.conditions_met = True
                        self.plan.requires_adjustment = True
                        self.plan.score_status = 'CONDITIONAL'
                        self.plan.adjustment_notes = f"Approved counter-offer with increased down payment of ${abono_req:.2f} ({abono_pct_req:.1f}%)."
                        
                        # Gather other cured term combinations for choices
                        other_cures = []
                        for t in all_terms:
                            if t.months == self.plan.selected_term:
                                continue
                            t_mult = t.multiplier
                            t_plan = InterestPlan.objects.filter(loan_term=t, is_active=True).first()
                            if t_plan and t_plan.risk_multiplier:
                                t_mult = t_plan.risk_multiplier
                            if t_mult and t_mult > 0:
                                t_max_fin = (self.plan.max_emi_allowed * t.months) / Decimal(str(t_mult))
                                t_abono = self.plan.total_price - t_max_fin
                                t_abono_pct = (t_abono / self.plan.total_price) * Decimal('100.00')
                                t_max_limit = Decimal('55.00') if self.plan.risk_tier == 'TIER_C' else Decimal('50.00')
                                if t_abono_pct <= t_max_limit:
                                    other_cures.append(f"{t.months}mo with ${t_abono:.2f} DP")
                        if other_cures:
                            self.plan.adjustment_notes += f" Alternatives: {', '.join(other_cures)}."
                    else:
                        self.plan.conditions_met = False
                        self.plan.score_status = 'REJECTED'
                        self.plan.adjustment_notes = f"EMI exceeds cap. Down payment cure of {abono_pct_req:.1f}% exceeds max allowed threshold."
                else:
                    self.plan.conditions_met = False
                    self.plan.score_status = 'REJECTED'
                    self.plan.adjustment_notes = "EMI exceeds allowed capacity (no valid term multiplier found)"
        else:
            self.plan.conditions_met = eligibility['eligible']
            
            # Map approval levels based on Risk Tier
            if tier_obj:
                level = tier_obj.approval_level
                if level == 'AUTO' and eligibility['eligible']:
                    self.plan.score_status = 'APPROVED'
                else:
                    self.plan.score_status = 'CONDITIONAL'
                    self.plan.adjustment_notes = f'Requires approval level: {level}'
            else:
                self.plan.score_status = 'REJECTED'

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
