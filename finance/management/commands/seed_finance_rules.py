from django.core.management.base import BaseCommand
from finance.models import (
    RiskTier, LoanTerm, InterestPlan, EmployerRule, ApprovalRule,
    DecisionRule, ReferenceRule, EMIConfiguration, FinanceMultiple
)
from decimal import Decimal

class Command(BaseCommand):
    help = 'Seeds default finance rules, risk tiers, and terms based on the Panama decision table.'

    def handle(self, *args, **options):
        self.stdout.write('Seeding finance rules...')

        # 1. EMI Configuration
        emi_config, created = EMIConfiguration.objects.get_or_create(
            id=1,
            defaults={
                'method': 'FLAT',
                'processing_fee_default': Decimal('15.00'),
                'insurance_fee_default': Decimal('20.00'),
                'tax_rate_pct': Decimal('7.00'),
                'is_active': True
            }
        )
        if not created:
            emi_config.method = 'FLAT'
            emi_config.save()
        self.stdout.write(f'EMI Configuration seeded: {emi_config.method}')

        # 2. Reference Rule
        ref_rule, created = ReferenceRule.objects.get_or_create(
            id=1,
            defaults={
                'min_references': 2,
                'require_verification': True,
                'is_active': True
            }
        )
        self.stdout.write('Reference Rule seeded')

        # Deactivate any existing 12, 18, 24 month loan terms, interest plans, and finance multiples
        LoanTerm.objects.filter(months__in=[12, 18, 24]).update(is_active=False)
        InterestPlan.objects.filter(loan_term__months__in=[12, 18, 24]).update(is_active=False)
        FinanceMultiple.objects.filter(term_months__in=[12, 18, 24]).update(is_active=False)

        # 3. Loan Terms (4, 6, 8 Months)
        # 4 months (8 fortnights) -> multiplier 1.30, interest flat 10%, reducing 15%
        term_4, _ = LoanTerm.objects.update_or_create(
            months=4,
            defaults={
                'fortnights': 8,
                'multiplier': Decimal('1.30'),
                'is_active': True
            }
        )
        # 6 months (12 fortnights) -> multiplier 1.50, interest flat 10%, reducing 15%
        term_6, _ = LoanTerm.objects.update_or_create(
            months=6,
            defaults={
                'fortnights': 12,
                'multiplier': Decimal('1.50'),
                'is_active': True
            }
        )
        # 8 months (16 fortnights) -> multiplier 1.80, interest flat 10%, reducing 15%
        term_8, _ = LoanTerm.objects.update_or_create(
            months=8,
            defaults={
                'fortnights': 16,
                'multiplier': Decimal('1.80'),
                'is_active': True
            }
        )
        self.stdout.write('Loan Terms seeded')

        # 3.5. Finance Multiples
        multiples_to_seed = [
            # 4 Months
            {'term': 4, 'interval': 30, 'mult': Decimal('1.30')},
            {'term': 4, 'interval': 15, 'mult': Decimal('1.20')},
            {'term': 4, 'interval': 7, 'mult': Decimal('1.20')},
            {'term': 4, 'interval': 3, 'mult': Decimal('1.20')},
            # 6 Months
            {'term': 6, 'interval': 30, 'mult': Decimal('1.50')},
            {'term': 6, 'interval': 15, 'mult': Decimal('1.42')},
            {'term': 6, 'interval': 7, 'mult': Decimal('1.42')},
            {'term': 6, 'interval': 3, 'mult': Decimal('1.42')},
            # 8 Months
            {'term': 8, 'interval': 30, 'mult': Decimal('1.80')},
            {'term': 8, 'interval': 15, 'mult': Decimal('1.60')},
            {'term': 8, 'interval': 7, 'mult': Decimal('1.60')},
            {'term': 8, 'interval': 3, 'mult': Decimal('1.60')},
        ]
        for item in multiples_to_seed:
            FinanceMultiple.objects.update_or_create(
                term_months=item['term'],
                interval_days=item['interval'],
                defaults={
                    'multiple': item['mult'],
                    'is_active': True
                }
            )
        self.stdout.write('Finance Multiples seeded')

        # 4. Interest Plans
        for term, rate_flat, rate_red in [(term_4, 10.0, 15.0), (term_6, 10.0, 15.0), (term_8, 10.0, 15.0)]:
            InterestPlan.objects.update_or_create(
                loan_term=term,
                name=f'Flat Interest {term.months}M',
                defaults={
                    'interest_rate_pct': Decimal(str(rate_flat)),
                    'processing_fee': Decimal('15.00'),
                    'insurance_fee': Decimal('20.00'),
                    'risk_multiplier': term.multiplier,
                    'is_active': True
                }
            )
        self.stdout.write('Interest Plans seeded')

        # 5. Risk Tiers
        tiers_data = [
            {
                'code': 'TIER_A',
                'name': 'Tier A (Low Risk)',
                'min_score': 600,
                'max_score': 900,
                'min_salary': Decimal('500.00'),
                'max_debt_ratio_pct': Decimal('20.00'),
                'min_down_payment_pct': Decimal('20.00'),
                'max_device_value': Decimal('1500.00'),
                'approval_level': 'AUTO'
            },
            {
                'code': 'TIER_B',
                'name': 'Tier B (Medium Risk)',
                'min_score': 550,
                'max_score': 599,
                'min_salary': Decimal('500.00'),
                'max_debt_ratio_pct': Decimal('20.00'),
                'min_down_payment_pct': Decimal('25.00'),
                'max_device_value': Decimal('1300.00'),
                'approval_level': 'FINANCE_ADMIN'
            },
            {
                'code': 'TIER_C',
                'name': 'Tier C (High Risk)',
                'min_score': 500,
                'max_score': 549,
                'min_salary': Decimal('500.00'),
                'max_debt_ratio_pct': Decimal('20.00'),
                'min_down_payment_pct': Decimal('30.00'),
                'max_device_value': Decimal('1000.00'),
                'approval_level': 'ADMIN'
            },
            {
                'code': 'TIER_D',
                'name': 'Tier D (Very High)',
                'min_score': 0,
                'max_score': 499,
                'min_salary': Decimal('0.00'),
                'max_debt_ratio_pct': Decimal('0.00'),
                'min_down_payment_pct': Decimal('100.00'),
                'max_device_value': Decimal('0.00'),
                'approval_level': 'GLOBAL_MANAGER'
            },
            {
                'code': 'TIER_E',
                'name': 'Tier E (No Score)',
                'min_score': None,
                'max_score': None,
                'min_salary': Decimal('500.00'),
                'max_debt_ratio_pct': Decimal('20.00'),
                'min_down_payment_pct': Decimal('35.00'),
                'max_device_value': Decimal('800.00'),
                'approval_level': 'ADMIN'
            },
            {
                'code': 'TIER_F',
                'name': 'Tier F (No Salario)',
                'min_score': 500,
                'max_score': 900,
                'min_salary': Decimal('0.00'),
                'max_debt_ratio_pct': Decimal('20.00'),
                'min_down_payment_pct': Decimal('35.00'),
                'max_device_value': Decimal('800.00'),
                'approval_level': 'ADMIN'
            },
            {
                'code': 'TIER_G',
                'name': 'Tier G (Sin Referencia)',
                'min_score': 0,
                'max_score': 900,
                'min_salary': Decimal('0.00'),
                'max_debt_ratio_pct': Decimal('0.00'),
                'min_down_payment_pct': Decimal('100.00'),
                'max_device_value': Decimal('0.00'),
                'approval_level': 'GLOBAL_MANAGER'
            },
            {
                'code': 'TIER_H',
                'name': 'Tier H (Cliente Activo)',
                'min_score': 0,
                'max_score': 900,
                'min_salary': Decimal('0.00'),
                'max_debt_ratio_pct': Decimal('0.00'),
                'min_down_payment_pct': Decimal('100.00'),
                'max_device_value': Decimal('0.00'),
                'approval_level': 'GLOBAL_MANAGER'
            }
        ]

        for tier in tiers_data:
            t_obj, _ = RiskTier.objects.update_or_create(
                code=tier['code'],
                defaults={
                    'name': tier['name'],
                    'min_score': tier['min_score'],
                    'max_score': tier['max_score'],
                    'min_salary': tier['min_salary'],
                    'max_debt_ratio_pct': tier['max_debt_ratio_pct'],
                    'min_down_payment_pct': tier['min_down_payment_pct'],
                    'max_device_value': tier['max_device_value'],
                    'approval_level': tier['approval_level'],
                    'is_active': True
                }
            )
            ApprovalRule.objects.update_or_create(
                risk_tier=t_obj,
                defaults={
                    'min_down_payment_pct': tier['min_down_payment_pct'],
                    'max_loan_amount': tier['max_device_value'] * Decimal('0.8'),
                    'is_active': True
                }
            )

        self.stdout.write('Risk Tiers and Approval Rules seeded')

        # 6. Decision Rules
        decision_rules = [
            {'key': 'min_score_check', 'desc': 'APC Score meets minimum tier score', 'val': 'True', 'mand': True},
            {'key': 'min_salary_check', 'desc': 'Applicant income meets minimum tier salary', 'val': 'True', 'mand': True},
            {'key': 'debt_ratio_check', 'desc': 'EMI remains below allowed monthly debt ratio', 'val': 'True', 'mand': True},
            {'key': 'blacklist_check', 'desc': 'Applicant is not on blacklist', 'val': 'True', 'mand': True},
            {'key': 'active_loan_check', 'desc': 'Applicant does not have another active loan', 'val': 'True', 'mand': True},
            {'key': 'reference_check', 'desc': 'Applicant has verified personal references', 'val': 'True', 'mand': True}
        ]
        for rule in decision_rules:
            DecisionRule.objects.update_or_create(
                rule_key=rule['key'],
                defaults={
                    'description': rule['desc'],
                    'value': rule['val'],
                    'is_mandatory': rule['mand'],
                    'is_active': True
                }
            )
        self.stdout.write('Decision Rules seeded')

        # 7. Default Employer Rules
        employers = ['Caja de Seguro Social', 'Ministerio de Educacion', 'Autoridad del Canal de Panama', 'Generic Private Corp']
        for emp in employers:
            EmployerRule.objects.update_or_create(
                employer_name=emp,
                defaults={
                    'min_employment_duration_months': 6,
                    'is_blacklisted': False,
                    'max_loan_multiplier': Decimal('1.2'),
                    'is_active': True
                }
            )
        self.stdout.write('Default Employer Rules seeded')

        self.stdout.write(self.style.SUCCESS('Successfully seeded all financing rules!'))
