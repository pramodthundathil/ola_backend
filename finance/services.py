from decimal import Decimal, ROUND_UP
import datetime
from django.utils import timezone
from customer.models import Customer, CreditApplication, CreditScore, PersonalReference
from products.models import ProductModel
from .models import (
    RiskTier, LoanTerm, InterestPlan, EmployerRule, ApprovalRule,
    DecisionRule, ReferenceRule, EMIConfiguration, EMISchedule, FinancePlan
)
import logging

logger = logging.getLogger(__name__)

class DecisionEngineService:
    """
    Evaluates applicant eligibility based on configurable database rules,
    credit bureau reports, and historical financing parameters.
    """

    @staticmethod
    def get_customer_history(customer, exclude_application_id=None):
        """
        Gathers details on existing customer, active loans, blacklist, and history.
        """
        history = {
            'exists': True,
            'is_blocked': customer.status == 'BLOCKED',
            'active_loans_count': 0,
            'previous_loans_count': 0,
            'has_active_loan': False,
            'history': []
        }
        
        apps = CreditApplication.objects.filter(customer=customer)
        if exclude_application_id:
            apps = apps.exclude(id=exclude_application_id)
        apps = apps.order_by('-created_at')
        for app in apps:
            history['history'].append({
                'id': app.id,
                'status': app.status,
                'device_model': app.device_model or 'N/A',
                'device_price': str(app.device_price) if app.device_price else '0.00',
                'application_date': app.application_date.strftime('%Y-%m-%d')
            })
            if app.status in ['APPROVED', 'PENDING_APPROVAL']:
                history['active_loans_count'] += 1
                history['has_active_loan'] = True
            elif app.status == 'COMPLETED':
                history['previous_loans_count'] += 1
                
        return history

    @classmethod
    def evaluate_eligibility(cls, customer, income, existing_obligations, score_val, employer_name, references, exclude_application_id=None):
        """
        Runs Step 5 Eligibility evaluation. Returns a dict of rule checks and status.
        """
        results = {
            'rules': [],
            'eligible': True,
            'reasons': [],
            'risk_tier': 'TIER_D'
        }

        # 1. Determine Risk Tier
        risk_tier_obj = None
        if score_val is not None:
            # Match score range
            risk_tier_obj = RiskTier.objects.filter(
                min_score__lte=score_val,
                max_score__gte=score_val,
                is_active=True
            ).first()
            
        if not risk_tier_obj:
            # Fallback if no score range matched (e.g. None score) -> Tier E (No Score) or Tier D
            if score_val is None:
                risk_tier_obj = RiskTier.objects.filter(code='TIER_E', is_active=True).first()
            else:
                risk_tier_obj = RiskTier.objects.filter(code='TIER_D', is_active=True).first()

        if not risk_tier_obj:
            risk_tier_obj = RiskTier.objects.filter(code='TIER_D').first()
            
        results['risk_tier'] = risk_tier_obj.code if risk_tier_obj else 'TIER_D'

        # Check blacklist
        history = cls.get_customer_history(customer, exclude_application_id=exclude_application_id)
        blacklist_check = not history['is_blocked']
        results['rules'].append({
            'rule_key': 'blacklist_check',
            'name': 'Blacklist Status Check',
            'passed': blacklist_check,
            'message': 'Passed' if blacklist_check else 'Customer is blacklisted'
        })
        if not blacklist_check:
            results['eligible'] = False
            results['reasons'].append('Customer is blacklisted')

        # Check active loans
        active_loans_ok = not history['has_active_loan']
        results['rules'].append({
            'rule_key': 'active_loan_check',
            'name': 'Active Loan Check',
            'passed': active_loans_ok,
            'message': 'Passed' if active_loans_ok else 'Customer has an active loan'
        })
        if not active_loans_ok:
            # In Panama, Tier H is active loan restriction
            results['risk_tier'] = 'TIER_H'
            results['eligible'] = False
            results['reasons'].append('Customer already has an active loan')

        # Check minimum salary
        min_salary = risk_tier_obj.min_salary if risk_tier_obj else Decimal('500.00')
        salary_ok = income >= min_salary
        results['rules'].append({
            'rule_key': 'min_salary_check',
            'name': 'Minimum Salary Check',
            'passed': salary_ok,
            'message': f'Income {income} meets minimum {min_salary}' if salary_ok else f'Income {income} below minimum {min_salary}'
        })
        if not salary_ok:
            results['risk_tier'] = 'TIER_F'  # No Salario
            # Let's check if it violates eligibility completely
            # For Tier F, min salary is 0.00, so it might pass if reassessed under Tier F
            pass

        # Check employer blacklist
        employer_ok = True
        if employer_name:
            emp_rule = EmployerRule.objects.filter(employer_name__iexact=employer_name, is_active=True).first()
            if emp_rule and emp_rule.is_blacklisted:
                employer_ok = False
        results['rules'].append({
            'rule_key': 'employer_check',
            'name': 'Employer Approval Check',
            'passed': employer_ok,
            'message': 'Passed' if employer_ok else f'Employer {employer_name} is blacklisted'
        })
        if not employer_ok:
            results['eligible'] = False
            results['reasons'].append(f'Employer {employer_name} is blacklisted')

        # Check references count
        # Enforce references check (TIER_G) only if the application has reached or passed the references step (step index 7)
        is_references_required = True
        if exclude_application_id:
            app_obj = CreditApplication.objects.filter(id=exclude_application_id).first()
            if app_obj and app_obj.current_step is not None and app_obj.current_step < 7:
                is_references_required = False

        ref_rule = ReferenceRule.objects.first()
        min_ref = ref_rule.min_references if ref_rule else 2
        ref_count = len(references)
        ref_ok = ref_count >= min_ref
        results['rules'].append({
            'rule_key': 'reference_check',
            'name': 'References Count Check',
            'passed': ref_ok or not is_references_required,
            'message': f'Collected {ref_count} references (min {min_ref})' if ref_ok else f'Need at least {min_ref} references, got {ref_count}'
        })
        if is_references_required and not ref_ok:
            results['risk_tier'] = 'TIER_G'  # Sin Referencia
            results['eligible'] = False
            results['reasons'].append('Insufficient references provided')

        # Tier F check (No Salario)
        if results['risk_tier'] == 'TIER_F':
            if score_val is None or score_val < 600:
                results['eligible'] = False
                results['reasons'].append('Bureau credit score must be 600+ for No Salary tier')
                results['risk_tier'] = 'TIER_D'

        # Tier D check
        if results['risk_tier'] == 'TIER_D':
            results['eligible'] = False
            results['reasons'].append('Bureau credit score too low (Tier D)')

        return results


class FinancingEngineService:
    """
    Computes pricing calculations, down payment limits, EMI terms, APR,
    and generates amortization payment schedules.
    """

    @staticmethod
    def calculate_emi(principal, term_months, rate_pct, method='FLAT', multiplier=None):
        """
        Calculates monthly installment and total interest based on flat or reducing rate.
        """
        principal = Decimal(str(principal))
        rate_pct = Decimal(str(rate_pct))
        term_months = Decimal(str(term_months))

        if method == 'FLAT':
            # Use multiplier if configured
            if multiplier is not None and multiplier > 0:
                total_repayment = principal * Decimal(str(multiplier))
                total_interest = total_repayment - principal
                monthly_emi = total_repayment / term_months
            else:
                total_interest = principal * (rate_pct / Decimal('100.00')) * (term_months / Decimal('12.00'))
                total_repayment = principal + total_interest
                monthly_emi = total_repayment / term_months
        else:
            # Reducing Balance EMI formula: EMI = [P * r * (1 + r)^N] / [((1 + r)^N) - 1]
            # r = annual_rate / 12 / 100
            if rate_pct <= 0:
                monthly_emi = principal / term_months
                total_interest = Decimal('0.00')
            else:
                r = rate_pct / Decimal('12.00') / Decimal('100.00')
                r_float = float(r)
                n_float = float(term_months)
                p_float = float(principal)
                emi_float = p_float * r_float * ((1 + r_float) ** n_float) / (((1 + r_float) ** n_float) - 1)
                monthly_emi = Decimal(str(round(emi_float, 2)))
                total_repayment = monthly_emi * term_months
                total_interest = total_repayment - principal

        # Finance Charge / Processing / Insurance estimation
        finance_charge = total_interest
        # Simple APR: (Finance Charge / Principal) / (Time in Years) * 100
        time_years = term_months / Decimal('12.00')
        if principal > 0:
            apr = (finance_charge / principal) / time_years * Decimal('100.00')
        else:
            apr = Decimal('0.00')

        return {
            'monthly_emi': monthly_emi.quantize(Decimal('0.01')),
            'total_interest': total_interest.quantize(Decimal('0.01')),
            'total_repayment': (principal + total_interest).quantize(Decimal('0.01')),
            'apr': apr.quantize(Decimal('0.01')),
            'finance_charge': finance_charge.quantize(Decimal('0.01'))
        }

    @classmethod
    def generate_emi_plans(cls, principal, risk_tier_code):
        """
        Generates comparison plans for 4, 6, 8, 10, 12 months.
        """
        plans = []
        config = EMIConfiguration.objects.first()
        method = config.method if config else 'FLAT'
        proc_fee = config.processing_fee_default if config else Decimal('15.00')
        ins_fee = config.insurance_fee_default if config else Decimal('20.00')
        
        terms = LoanTerm.objects.filter(is_active=True).order_by('months')
        if not terms.exists():
            # Return some static fallback terms if table not loaded
            return []

        for term in terms:
            interest_pct = Decimal('10.00')
            multiplier = term.multiplier

            # Grab customized rate for this term if exists
            plan_obj = InterestPlan.objects.filter(loan_term=term, is_active=True).first()
            if plan_obj:
                interest_pct = plan_obj.interest_rate_pct
                proc_fee = plan_obj.processing_fee
                ins_fee = plan_obj.insurance_fee
                multiplier = plan_obj.risk_multiplier

            res = cls.calculate_emi(
                principal=principal,
                term_months=term.months,
                rate_pct=interest_pct,
                method=method,
                multiplier=multiplier if method == 'FLAT' else None
            )

            plans.append({
                'term_months': term.months,
                'fortnights': term.fortnights,
                'monthly_emi': str(res['monthly_emi']),
                'fortnightly_emi': str((res['total_repayment'] / Decimal(str(term.fortnights))).quantize(Decimal('0.01'))),
                'total_interest': str(res['total_interest']),
                'total_repayment': str(res['total_repayment']),
                'apr': str(res['apr']),
                'processing_fee': str(proc_fee),
                'insurance_fee': str(ins_fee),
                'method': method
            })

        return plans

    @staticmethod
    def generate_amortization_schedule(finance_plan):
        """
        Creates EMISchedule records in the database based on the selected plan parameters.
        """
        # Delete any existing schedule
        EMISchedule.objects.filter(finance_plan=finance_plan).delete()

        frequency_days = finance_plan.installment_frequency_days or 30
        first_due_date = timezone.now().date() + datetime.timedelta(days=frequency_days)

        return EMISchedule.generate_schedule(finance_plan, first_due_date)


class ContractService:
    """
    Generates contract details, agreements, payment schedules, receipts,
    and delivery forms in HTML/Text structure for printing or previewing.
    """

    @staticmethod
    def generate_loan_agreement(plan):
        import datetime
        from customer.models import CreditConfig, DEFAULT_TEMPLATE
        
        config = CreditConfig.objects.first()
        template = config.loan_agreement_template if config and config.loan_agreement_template else DEFAULT_TEMPLATE
        
        customer = plan.credit_application.customer
        device = plan.device
        
        # Format the EMI schedule list
        emi_schedule_text = ContractService.generate_payment_schedule_text(plan)
        
        replacements = {
            "date": datetime.date.today().strftime('%Y-%m-%d'),
            "first_name": customer.first_name or "",
            "last_name": customer.last_name or "",
            "cedula": customer.document_number or "",
            "email": customer.email or "",
            "phone": customer.phone_number or "",
            "device_brand": getattr(device.brand, "name", "N/A") if device and device.brand else "N/A",
            "device_model": device.model_name if device else "N/A",
            "device_imei": plan.credit_application.device_imei or "N/A",
            "selling_price": str(plan.selling_price),
            "cash_price": str(plan.cash_price),
            "accessories": str(plan.accessories),
            "warranty": str(plan.warranty),
            "insurance": str(plan.insurance),
            "total_price": str(plan.total_price),
            "actual_down_payment": str(plan.actual_down_payment),
            "amount_to_finance": str(plan.amount_to_finance),
            "selected_term": str(plan.selected_term),
            "installment_frequency_days": str(plan.installment_frequency_days),
            "monthly_installment": str(plan.monthly_installment),
            "total_amount_payable": str(plan.total_amount_payable),
            "emi_schedule": emi_schedule_text
        }
        
        # Safe substitution to prevent breaking on missing format keys
        for k, v in replacements.items():
            template = template.replace(f"{{{k}}}", str(v))
            
        return template

    @staticmethod
    def generate_pdf_from_text(text):
        import io
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
        )
        styles = getSampleStyleSheet()
        
        # Custom stylesheet
        custom_body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['BodyText'],
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor('#0f172a')
        )
        custom_title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=14,
            leading=18,
            alignment=1, # Center
            textColor=colors.HexColor('#1e3a8a'),
            spaceAfter=15,
            spaceBefore=15
        )
        
        story = []
        
        paragraphs = text.strip().split('\n')
        for p in paragraphs:
            p_strip = p.strip()
            if not p_strip:
                story.append(Spacer(1, 8))
                continue
                
            # If it's a visual separator
            if '===' in p_strip or '___' in p_strip:
                story.append(Spacer(1, 5))
                continue
                
            p_clean = p_strip.replace(' ', '&nbsp;').replace('\t', '&nbsp;'*4)
            
            # Simple header detection
            if p_strip.isupper() and len(p_strip) < 80:
                story.append(Paragraph(p_clean, custom_title_style))
            else:
                story.append(Paragraph(p_clean, custom_body_style))
                
        doc.build(story)
        pdf_content = buffer.getvalue()
        buffer.close()
        return pdf_content

    @staticmethod
    def generate_payment_schedule_text(plan):
        schedules = list(EMISchedule.objects.filter(finance_plan=plan).order_by('installment_number'))
        if not schedules:
            frequency_days = plan.installment_frequency_days or 30
            first_due_date = timezone.now().date() + datetime.timedelta(days=frequency_days)
            schedules = EMISchedule.generate_schedule(plan, first_due_date, save=False)

        output = [
            "================================================================================",
            "                            FORTNIGHTLY/MONTHLY PAYMENT SCHEDULE                ",
            "================================================================================",
            f"Customer: {plan.credit_application.customer.first_name} {plan.credit_application.customer.last_name}",
            f"Document Number (Cedula): {plan.credit_application.customer.document_number}",
            f"Loan Principal: ${plan.amount_to_finance} USD",
            "",
            f"{'Inst #':<8}{'Due Date':<15}{'EMI Amount':<12}{'Principal':<12}{'Interest':<12}{'Balance':<12}{'Status':<10}"
        ]
        
        for s in schedules:
            output.append(
                f"{s.installment_number:<8}"
                f"{s.due_date.strftime('%Y-%m-%d'):<15}"
                f"${s.installment_amount:<11}"
                f"${s.principal:<11}"
                f"${s.interest:<11}"
                f"${s.balance:<11}"
                f"{s.status:<10}"
            )
            
        return "\n".join(output)

    @staticmethod
    def generate_downpayment_receipt(plan):
        customer = plan.credit_application.customer
        return f"""
        ================================================================================
                                 DOWN PAYMENT RECEIPT
        ================================================================================
        Receipt Number: DP-{plan.id}-{int(timezone.now().timestamp())}
        Date: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}
        
        Received From:
        Borrower Name: {customer.first_name} {customer.last_name}
        Cedula ID: {customer.document_number}
        
        Payment Details:
        Amount Paid: ${plan.actual_down_payment} USD
        Method: CASH / DEBIT CARD / BANK TRANSFER
        For Device Model: {plan.device.model_name if plan.device else 'N/A'}
        Financing Application ID: {plan.credit_application.id}
        
        Status: COMPLETED & VERIFIED
        
        Thank you for your business.
        ================================================================================
        """

    @staticmethod
    def generate_delivery_form(plan):
        customer = plan.credit_application.customer
        device = plan.device
        return f"""
        ================================================================================
                                DEVICE DELIVERY & ACCEPTANCE FORM
        ================================================================================
        Customer Name: {customer.first_name} {customer.last_name}
        Cedula ID: {customer.document_number}
        Delivery Date: {timezone.now().strftime('%Y-%m-%d')}
        
        Delivered Device Specifications:
        Brand: {device.brand.name if device and device.brand else 'N/A'}
        Model: {device.model_name if device else 'N/A'}
        Color: {device.color or 'N/A'}
        IMEI: {plan.credit_application.device_imei or 'N/A'}
        
        Borrower Acceptance Statement:
        I, {customer.first_name} {customer.last_name}, confirm that I have inspected
        the physical product listed above and received it in excellent working order
        along with all default accessories. I agree to the Knox lock terms of finance.
        
        Customer Signature: ___________________________
        Delivered By: _________________________________
        """
