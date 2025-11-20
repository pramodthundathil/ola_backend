"""
Unified Management Command for Analytics Dashboard
File: analytics/management/commands/aggregate_analytics.py

Combines all analytics aggregation into one comprehensive command
Run daily via cron: python manage.py aggregate_analytics
"""

from django.core.management.base import BaseCommand
from django.db.models import Sum, Avg, Count, Q, F, Max, Min
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal

from analytics.models import (
    # Existing Models
    SalesAnalytics, ApplicationFunnelAnalytics, DeviceEnrollmentAnalytics,
    BrandModelAnalytics, GeographicAnalytics, FPDAnalytics,
    FinancialMetrics, ClerkPerformanceAnalytics, HourlyAnalytics,
    # New Comprehensive Models
    DailyFinanceMetrics, BrandPerformanceMetrics, ProductPerformanceMetrics,
    SalespersonPerformance, PaymentCollectionMetrics, RiskAnalysisMetrics,
    GeographicPerformanceMetrics, DeviceLockPerformanceMetrics
)
from finance.models import FinancePlan, EMISchedule, PaymentRecord
from customer.models import CreditApplication, Customer, CreditScore
from store.models import Store, Region, Province, District
from home.models import CustomUser
from customer_device.models import DeviceEnrollmentCustomer
from products.models import Brand, ProductModel


class Command(BaseCommand):
    help = 'Aggregate all analytics data for comprehensive dashboard'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Date to aggregate (YYYY-MM-DD). Default is yesterday.',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Number of days to aggregate backwards from date',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-aggregation even if data exists',
        )
        parser.add_argument(
            '--type',
            type=str,
            choices=['all', 'sales', 'funnel', 'devices', 'brands', 'geographic', 
                    'fpd', 'financial', 'clerks', 'hourly', 'daily', 'risk', 'payment'],
            default='all',
            help='Type of analytics to aggregate',
        )
    
    def handle(self, *args, **options):
        # Determine date range
        if options['date']:
            end_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
        else:
            end_date = timezone.now().date() - timedelta(days=1)
        
        start_date = end_date - timedelta(days=options['days'] - 1)
        force = options['force']
        agg_type = options['type']
        
        self.stdout.write(self.style.WARNING(
            f"\n{'='*60}\n"
            f"ANALYTICS AGGREGATION - {timezone.now()}\n"
            f"{'='*60}\n"
            f"Date Range: {start_date} to {end_date}\n"
            f"Days: {options['days']}\n"
            f"Type: {agg_type}\n"
            f"Force: {force}\n"
            f"{'='*60}\n"
        ))
        
        total_processed = 0
        total_errors = 0
        
        for single_date in self.daterange(start_date, end_date):
            self.stdout.write(f"\n📅 Processing {single_date}...")
            
            try:
                if agg_type in ['all', 'sales']:
                    self.aggregate_sales_analytics(single_date, force)
                    
                if agg_type in ['all', 'funnel']:
                    self.aggregate_funnel_analytics(single_date, force)
                    
                if agg_type in ['all', 'devices']:
                    self.aggregate_device_analytics(single_date, force)
                    
                if agg_type in ['all', 'brands']:
                    self.aggregate_brand_analytics(single_date, force)
                    
                if agg_type in ['all', 'geographic']:
                    self.aggregate_geographic_analytics(single_date, force)
                    
                if agg_type in ['all', 'fpd']:
                    self.aggregate_fpd_analytics(single_date, force)
                    
                if agg_type in ['all', 'financial']:
                    self.aggregate_financial_metrics(single_date, force)
                    
                if agg_type in ['all', 'clerks']:
                    self.aggregate_clerk_performance(single_date, force)
                    
                if agg_type in ['all', 'hourly']:
                    self.aggregate_hourly_analytics(single_date, force)
                    
                # New comprehensive aggregations
                if agg_type in ['all', 'daily']:
                    self.aggregate_daily_finance_metrics(single_date, force)
                    
                if agg_type in ['all', 'risk']:
                    self.aggregate_risk_analysis(single_date, force)
                    
                if agg_type in ['all', 'payment']:
                    self.aggregate_payment_collection(single_date, force)
                
                self.stdout.write(self.style.SUCCESS(f"✅ Completed {single_date}"))
                total_processed += 1
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Error on {single_date}: {str(e)}"))
                import traceback
                self.stdout.write(traceback.format_exc())
                total_errors += 1
        
        # Summary
        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*60}\n"
            f"AGGREGATION SUMMARY\n"
            f"{'='*60}\n"
            f"✅ Successfully processed: {total_processed} days\n"
            f"❌ Errors: {total_errors} days\n"
            f"{'='*60}\n"
        ))
    
    def daterange(self, start_date, end_date):
        """Generate date range"""
        for n in range(int((end_date - start_date).days) + 1):
            yield start_date + timedelta(n)
    
    # ========================================
    # SALES ANALYTICS
    # ========================================
    
    def aggregate_sales_analytics(self, date, force=False):
        """Aggregate sales metrics by store and salesperson"""
        self.stdout.write("  📊 Aggregating sales analytics...")
        
        finance_plans = FinancePlan.objects.filter(
            created_at__date=date,
            status='ACTIVE'
        )
        
        if not finance_plans.exists():
            self.stdout.write("    ⚠️  No finance plans found")
            return
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            store_plans = finance_plans.filter(store=store)
            
            if store_plans.exists():
                total_sales = store_plans.count()
                total_amount = store_plans.aggregate(Sum('device_price'))['device_price__sum'] or Decimal('0.00')
                avg_retail = store_plans.aggregate(Avg('device_price'))['device_price__avg'] or Decimal('0.00')
                avg_finance = store_plans.aggregate(Avg('amount_to_finance'))['amount_to_finance__avg'] or Decimal('0.00')
                avg_down_pct = store_plans.aggregate(Avg('down_payment_percentage'))['down_payment_percentage__avg'] or Decimal('0.00')
                
                # Store-level aggregate
                SalesAnalytics.objects.update_or_create(
                    date=date,
                    store=store,
                    salesperson=None,
                    defaults={
                        'total_sales': total_sales,
                        'total_sales_amount': total_amount,
                        'active_stores_count': 1,
                        'avg_retail_price': avg_retail,
                        'avg_finance_amount': avg_finance,
                        'avg_down_payment_pct': avg_down_pct,
                        'sales_per_active_store': total_sales
                    }
                )
                count += 1
                
                # Salesperson-level aggregate
                salespersons = store_plans.values_list('created_by', flat=True).distinct()
                
                for sp_id in salespersons:
                    if sp_id:
                        sp_plans = store_plans.filter(created_by_id=sp_id)
                        sp_sales = sp_plans.count()
                        sp_amount = sp_plans.aggregate(Sum('device_price'))['device_price__sum'] or Decimal('0.00')
                        sp_avg_retail = sp_plans.aggregate(Avg('device_price'))['device_price__avg'] or Decimal('0.00')
                        sp_avg_finance = sp_plans.aggregate(Avg('amount_to_finance'))['amount_to_finance__avg'] or Decimal('0.00')
                        sp_avg_down = sp_plans.aggregate(Avg('down_payment_percentage'))['down_payment_percentage__avg'] or Decimal('0.00')
                        
                        SalesAnalytics.objects.update_or_create(
                            date=date,
                            store=store,
                            salesperson_id=sp_id,
                            defaults={
                                'total_sales': sp_sales,
                                'total_sales_amount': sp_amount,
                                'active_stores_count': 1,
                                'avg_retail_price': sp_avg_retail,
                                'avg_finance_amount': sp_avg_finance,
                                'avg_down_payment_pct': sp_avg_down,
                                'sales_per_active_store': sp_sales
                            }
                        )
                        count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} sales records")
    
    # ========================================
    # FUNNEL ANALYTICS
    # ========================================
    
    def aggregate_funnel_analytics(self, date, force=False):
        """Aggregate application funnel metrics"""
        self.stdout.write("  🔄 Aggregating funnel analytics...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            applications = CreditApplication.objects.filter(
                created_at__date=date,
                sales_person__store=store
            )
            
            if applications.exists():
                total_apps = applications.count()
                
                # KYC completed
                kyc_completed = applications.filter(
                    customer__identity_verification__overall_status='VERIFIED'
                ).count()
                
                # Approved applications
                approved = applications.filter(status='APPROVED').count()
                
                # Actual sales (finance plans created)
                sales = FinancePlan.objects.filter(
                    credit_application__in=applications,
                    status='ACTIVE'
                ).count()
                
                # Customers
                unique_customers = applications.values('customer').distinct().count()
                
                # Calculate rates
                kyc_rate = (kyc_completed / total_apps * 100) if total_apps > 0 else 0
                approval_rate = (approved / total_apps * 100) if total_apps > 0 else 0
                take_rate = (sales / approved * 100) if approved > 0 else 0
                conversion_rate = (sales / total_apps * 100) if total_apps > 0 else 0
                
                ApplicationFunnelAnalytics.objects.update_or_create(
                    date=date,
                    store=store,
                    salesperson=None,
                    defaults={
                        'applications': total_apps,
                        'customers': unique_customers,
                        'kyc_completed': kyc_completed,
                        'approved': approved,
                        'sales': sales,
                        'kyc_success_rate': Decimal(str(round(kyc_rate, 2))),
                        'approval_rate': Decimal(str(round(approval_rate, 2))),
                        'take_rate': Decimal(str(round(take_rate, 2))),
                        'conversion_rate': Decimal(str(round(conversion_rate, 2)))
                    }
                )
                count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} funnel records")
    
    # ========================================
    # DEVICE ANALYTICS
    # ========================================
    
   
    def aggregate_device_analytics(self, date, force=False):
        """Aggregate device enrollment by lock type"""
        self.stdout.write("  📱 Aggregating device analytics...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            devices = DeviceEnrollmentCustomer.objects.filter(
                created_at__date=date,
                finance_plan__store=store
            )
            
            if devices.exists():
                # Count by lock system - MATCH THE MODEL FIELDS
                base_android = devices.filter(locking_system='NUOVOPAY').count()
                android_dlc = devices.filter(locking_system='ANDROID_DLC').count()
                kpe = devices.filter(locking_system='KPE').count()
                kg = devices.filter(locking_system='KG').count()
                knox = devices.filter(locking_system='KNOX').count()
                base_android_frp = devices.filter(locking_system='BASEANDROID_FRP').count()
                access = devices.filter(locking_system='ACCESS').count()
                
                total = devices.count()
                
                DeviceEnrollmentAnalytics.objects.update_or_create(
                    date=date,
                    store=store,
                    defaults={
                        'lock_base_android': base_android,
                        'lock_android_dlc': android_dlc,
                        'lock_kpe': kpe,
                        'lock_kg': kg,
                        'lock_knox': knox,  # Now this field exists
                        'lock_base_android_frp': base_android_frp,
                        'lock_access': access,
                        'total_devices_enrolled': total
                    }
                )
                count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} device records")

    # ========================================
    # BRAND ANALYTICS
    # ========================================
    
# Updated aggregation function
    def aggregate_brand_analytics(self, date, force=False):
        """Aggregate sales by brand and model"""
        self.stdout.write("  🏷️  Aggregating brand/model analytics...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                store=store,
                device__isnull=False
            )
            
            if finance_plans.exists():
                # Group by brand and device
                brands = finance_plans.values(
                    'device__brand',
                    'device__brand__name',
                    'device',
                    'device__model_name'
                ).annotate(
                    sales_count=Count('id'),
                    total_amount=Sum('device_price')
                )
                
                for brand_data in brands:
                    BrandModelAnalytics.objects.update_or_create(
                        date=date,
                        store=store,
                        brand_id=brand_data['device__brand'],
                        device_id=brand_data['device'],
                        defaults={
                            'brand_name': brand_data['device__brand__name'] or 'Unknown',
                            'model_name': brand_data['device__model_name'] or 'Unknown',
                            'sales_count': brand_data['sales_count'],
                            'total_amount': brand_data['total_amount'] or Decimal('0.00')
                        }
                    )
                    count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} brand/model records")
    # ========================================
    # GEOGRAPHIC ANALYTICS
    # ========================================
    
    def aggregate_geographic_analytics(self, date, force=False):
        """Aggregate sales by geographic location"""
        self.stdout.write("  🗺️  Aggregating geographic analytics...")
        
        finance_plans = FinancePlan.objects.filter(
            created_at__date=date,
            store__isnull=False
        )
        
        if not finance_plans.exists():
            self.stdout.write("    ⚠️  No finance plans with stores found")
            return
        
        # Group by region/province/district
        geo_groups = finance_plans.values(
            'store__region',
            'store__province__name',
            'store__district__name'
        ).annotate(
            sales_count=Count('id'),
            total_amount=Sum('device_price'),
            avg_amount=Avg('device_price')  # Calculate average
        )
        
        count = 0
        for geo_data in geo_groups:
            if geo_data['store__region']:
                GeographicAnalytics.objects.update_or_create(
                    date=date,
                    region_id=geo_data['store__region'],
                    province_name=geo_data['store__province__name'] or 'N/A',
                    district_name=geo_data['store__district__name'] or 'N/A',
                    defaults={
                        'sales_count': geo_data['sales_count'],
                        'total_amount': geo_data['total_amount'] or Decimal('0.00'),
                        'avg_amount': geo_data['avg_amount'] or Decimal('0.00')  # Now included
                    }
                )
                count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} geographic records")
    # ========================================
    # FPD ANALYTICS
    # ========================================
    
    def aggregate_fpd_analytics(self, date, force=False):
        """Aggregate First Payment Default metrics"""
        self.stdout.write("  ⚠️  Aggregating FPD analytics...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            # Contracts from 3, 7, 15 days ago
            date_3 = date - timedelta(days=3)
            date_7 = date - timedelta(days=7)
            date_15 = date - timedelta(days=15)
            
            def calc_fpd(target_date):
                """Calculate FPD rate for contracts created on target_date"""
                contracts = FinancePlan.objects.filter(
                    created_at__date=target_date,
                    store=store,
                    status='ACTIVE'
                )
                
                if not contracts.exists():
                    return 0, 0, 0
                
                total = contracts.count()
                overdue = 0
                
                for contract in contracts:
                    first_emi = contract.emi_schedule.filter(installment_number=1).first()
                    if first_emi and first_emi.status in ['OVERDUE', 'PARTIALLY_PAID']:
                        overdue += 1
                
                fpd_rate = (overdue / total * 100) if total > 0 else 0
                return fpd_rate, overdue, total
            
            fpd_3, overdue_3, total_3 = calc_fpd(date_3)
            fpd_7, overdue_7, total_7 = calc_fpd(date_7)
            fpd_15, overdue_15, total_15 = calc_fpd(date_15)
            
            # Total active contracts
            total_contracts = FinancePlan.objects.filter(
                store=store,
                status='ACTIVE'
            ).count()
            
            # Early inactive (contracts with less than 40% payment at 60 days)
            date_60 = date - timedelta(days=60)
            contracts_60 = FinancePlan.objects.filter(
                created_at__date__lte=date_60,
                store=store,
                status='ACTIVE'
            )
            
            early_inactive = 0
            early_inactive_total = contracts_60.count()
            
            for contract in contracts_60:
                paid_count = contract.emi_schedule.filter(status='PAID').count()
                total_emis = contract.emi_schedule.count()
                if total_emis > 0:
                    payment_rate = (paid_count / total_emis) * 100
                    if payment_rate < 40:
                        early_inactive += 1
            
            early_inactive_rate = (early_inactive / early_inactive_total * 100) if early_inactive_total > 0 else 0
            
            # Pay 40 at 60 days rate (contracts that paid at least 40% by day 60)
            pay_40_at_60_count = early_inactive_total - early_inactive if early_inactive_total > 0 else 0
            pay_40_at_60_rate = (pay_40_at_60_count / early_inactive_total * 100) if early_inactive_total > 0 else 0
            
            # FIXED: Only use fields that exist in the model
            FPDAnalytics.objects.update_or_create(
                date=date,
                store=store,
                defaults={
                    'fpd_3_rate': Decimal(str(round(fpd_3, 2))),
                    'fpd_7_rate': Decimal(str(round(fpd_7, 2))),
                    'fpd_15_rate': Decimal(str(round(fpd_15, 2))),
                    'early_inactive_rate': Decimal(str(round(early_inactive_rate, 2))),
                    'pay_40_at_60_rate': Decimal(str(round(pay_40_at_60_rate, 2))),
                    'total_contracts': total_contracts
                }
            )
            count += 1
    
            self.stdout.write(f"    ✓ Created/updated {count} FPD records")
    # ========================================
    # FINANCIAL METRICS
    # ========================================
    
    def aggregate_financial_metrics(self, date, force=False):
        """Aggregate financial metrics"""
        self.stdout.write("  💰 Aggregating financial metrics...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                store=store
            )
            
            if finance_plans.exists():
                metrics = finance_plans.aggregate(
                    total_revenue=Sum('device_price'),
                    total_financed=Sum('amount_to_finance'),
                    total_down=Sum('actual_down_payment'),
                    avg_term=Avg('selected_term'),
                    avg_installment=Avg('monthly_installment')
                )
                
                # Calculate average multiple
                multiples = []
                for plan in finance_plans:
                    if plan.amount_to_finance and plan.monthly_installment and plan.selected_term:
                        multiple = (plan.monthly_installment * plan.selected_term) / plan.amount_to_finance
                        multiples.append(float(multiple))
                
                avg_multiple = Decimal(str(sum(multiples) / len(multiples))) if multiples else Decimal('0.00')
                
                # Collections for this date
                collections = PaymentRecord.objects.filter(
                    payment_date__date=date,
                    finance_plan__store=store,
                    payment_status='COMPLETED'
                ).aggregate(Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')
                
                # Outstanding balance
                outstanding = EMISchedule.objects.filter(
                    finance_plan__store=store,
                    status__in=['DUE', 'OVERDUE', 'UPCOMING']
                ).aggregate(Sum('balance_remaining'))['balance_remaining__sum'] or Decimal('0.00')
                
                FinancialMetrics.objects.update_or_create(
                    date=date,
                    store=store,
                    salesperson=None,
                    defaults={
                        'total_revenue': metrics['total_revenue'] or Decimal('0.00'),
                        'total_financed_amount': metrics['total_financed'] or Decimal('0.00'),
                        'total_down_payment': metrics['total_down'] or Decimal('0.00'),
                        'avg_multiple': avg_multiple,
                        'avg_term_months': metrics['avg_term'] or Decimal('0.00'),
                        'collections_received': collections,
                        'outstanding_amount': outstanding
                    }
                )
                count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} financial records")
    
    # ========================================
    # CLERK/SALESPERSON PERFORMANCE
    # ========================================
    
    def aggregate_clerk_performance(self, date, force=False):
        """Aggregate salesperson performance"""
        self.stdout.write("  👤 Aggregating clerk/salesperson performance...")
        
        salespersons = CustomUser.objects.filter(
            role='salesperson',
            is_active=True
        )
        
        count = 0
        for sp in salespersons:
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                created_by=sp
            )
            
            if finance_plans.exists():
                applications = CreditApplication.objects.filter(
                    sales_person=sp,
                    created_at__date=date
                )
                
                total_sales = finance_plans.count()
                total_amount = finance_plans.aggregate(Sum('device_price'))['device_price__sum'] or Decimal('0.00')
                
                apps_created = applications.count()
                apps_approved = applications.filter(status='APPROVED').count()
                approval_rate = (apps_approved / apps_created * 100) if apps_created > 0 else 0
                
                ClerkPerformanceAnalytics.objects.update_or_create(
                    date=date,
                    salesperson=sp,
                    store=sp.store,
                    defaults={
                        'total_sales': total_sales,
                        'total_sales_amount': total_amount,
                        'applications_created': apps_created,
                        'applications_approved': apps_approved,
                        'approval_rate': Decimal(str(round(approval_rate, 2)))
                    }
                )
                count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} clerk performance records")
    
    # ========================================
    # HOURLY ANALYTICS
    # ========================================
    
    def aggregate_hourly_analytics(self, date, force=False):
        """Aggregate sales by hour and day of week"""
        self.stdout.write("  🕐 Aggregating hourly analytics...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                store=store
            )
            
            if finance_plans.exists():
                day_of_week = date.strftime('%A')
                
                # Group by hour
                for hour in range(24):
                    hour_plans = finance_plans.filter(created_at__hour=hour)
                    
                    if hour_plans.exists():
                        HourlyAnalytics.objects.update_or_create(
                            date=date,
                            store=store,
                            hour=hour,
                            day_of_week=day_of_week,
                            defaults={
                                'sales_count': hour_plans.count()
                            }
                        )
                        count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} hourly records")
    
    # ========================================
    # COMPREHENSIVE DAILY METRICS
    # ========================================
    
    def aggregate_daily_finance_metrics(self, date, force=False):
        """Aggregate comprehensive daily finance metrics"""
        self.stdout.write("  📈 Aggregating comprehensive daily metrics...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                store=store
            )
            
            if not finance_plans.exists():
                continue
            
            # Application metrics
            applications = CreditApplication.objects.filter(
                created_at__date=date,
                sales_person__store=store
            )
            
            total_apps = applications.count()
            approved = applications.filter(status='APPROVED').count()
            rejected = applications.filter(status='REJECTED').count()
            pending = total_apps - approved - rejected
            
            # Customer metrics
            customers = Customer.objects.filter(
                credit_applications__in=applications
            ).distinct()
            
            new_customers = customers.filter(created_at__date=date).count()
            returning_customers = customers.filter(created_at__date__lt=date).count()
            
            # KYC metrics
            kyc_completed = applications.filter(
                customer__identity_verification__overall_status='VERIFIED'
            ).count()
            kyc_rate = (kyc_completed / total_apps * 100) if total_apps > 0 else 0
            
            # Financial metrics
            financials = finance_plans.aggregate(
                total_sales=Sum('device_price'),
                total_financed=Sum('amount_to_finance'),
                total_down=Sum('actual_down_payment'),
                avg_ticket=Avg('device_price'),
                avg_finance=Avg('amount_to_finance'),
                avg_down_pct=Avg('down_payment_percentage')
            )
            
            # Risk tiers
            tier_a = finance_plans.filter(risk_tier='TIER_A').count()
            tier_b = finance_plans.filter(risk_tier='TIER_B').count()
            tier_c = finance_plans.filter(risk_tier='TIER_C').count()
            tier_d = finance_plans.filter(risk_tier='TIER_D').count()
            
            # Payment metrics
            payments = PaymentRecord.objects.filter(
                payment_date__date=date,
                finance_plan__store=store,
                payment_status='COMPLETED'
            )
            total_payments = payments.aggregate(Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')
            
            # Overdue payments
            overdue_emis = EMISchedule.objects.filter(
                finance_plan__store=store,
                status='OVERDUE',
                due_date__lte=date
            )
            total_overdue = overdue_emis.aggregate(Sum('balance_remaining'))['balance_remaining__sum'] or Decimal('0.00')
            
            # Device enrollment
            devices = DeviceEnrollmentCustomer.objects.filter(
                finance_plan__in=finance_plans
            )
            devices_enrolled = devices.count()
            devices_locked = devices.filter(is_locked=True).count()
            
            # Rates
            approval_rate = (approved / total_apps * 100) if total_apps > 0 else 0
            sales_count = finance_plans.count()
            take_rate = (sales_count / approved * 100) if approved > 0 else 0
            conversion_rate = (sales_count / total_apps * 100) if total_apps > 0 else 0
            
            DailyFinanceMetrics.objects.update_or_create(
                date=date,
                store=store,
                region=store.region,
                defaults={
                    'province': store.province,
                    'district': store.district,
                    'total_applications': total_apps,
                    'approved_applications': approved,
                    'rejected_applications': rejected,
                    'pending_applications': pending,
                    'new_customers': new_customers,
                    'returning_customers': returning_customers,
                    'unique_customers': customers.count(),
                    'kyc_completed': kyc_completed,
                    'kyc_success_rate': Decimal(str(round(kyc_rate, 2))),
                    'total_sales_value': financials['total_sales'] or Decimal('0.00'),
                    'total_financed_amount': financials['total_financed'] or Decimal('0.00'),
                    'total_down_payment': financials['total_down'] or Decimal('0.00'),
                    'average_ticket_size': financials['avg_ticket'] or Decimal('0.00'),
                    'average_finance_amount': financials['avg_finance'] or Decimal('0.00'),
                    'average_down_payment_pct': financials['avg_down_pct'] or Decimal('0.00'),
                    'tier_a_count': tier_a,
                    'tier_b_count': tier_b,
                    'tier_c_count': tier_c,
                    'tier_d_count': tier_d,
                    'total_payments_received': total_payments,
                    'total_payments_overdue': total_overdue,
                    'approval_rate': Decimal(str(round(approval_rate, 2))),
                    'take_rate': Decimal(str(round(take_rate, 2))),
                    'conversion_rate': Decimal(str(round(conversion_rate, 2))),
                    'devices_enrolled': devices_enrolled,
                    'devices_locked': devices_locked,
                }
            )
            count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} daily finance metric records")
    
    # ========================================
    # RISK ANALYSIS METRICS
    # ========================================
    
    def aggregate_risk_analysis(self, date, force=False):
        """Aggregate risk tier analysis"""
        self.stdout.write("  ⚡ Aggregating risk analysis...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            risk_tiers = ['TIER_A', 'TIER_B', 'TIER_C', 'TIER_D']
            
            for tier in risk_tiers:
                # Get all active accounts in this tier
                active_accounts = FinancePlan.objects.filter(
                    store=store,
                    risk_tier=tier,
                    status='ACTIVE'
                )
                
                # New accounts created today
                new_accounts = active_accounts.filter(created_at__date=date)
                
                if not active_accounts.exists():
                    continue
                
                # Portfolio value
                portfolio_value = active_accounts.aggregate(
                    Sum('device_price')
                )['device_price__sum'] or Decimal('0.00')
                
                # Outstanding amount
                outstanding = EMISchedule.objects.filter(
                    finance_plan__in=active_accounts,
                    status__in=['DUE', 'OVERDUE', 'UPCOMING']
                ).aggregate(Sum('balance_remaining'))['balance_remaining__sum'] or Decimal('0.00')
                
                # Accounts in default (>30 days overdue)
                date_30_days_ago = date - timedelta(days=30)
                overdue_emis = EMISchedule.objects.filter(
                    finance_plan__in=active_accounts,
                    status='OVERDUE',
                    due_date__lte=date_30_days_ago
                )
                accounts_in_default = overdue_emis.values('finance_plan').distinct().count()
                
                # Default rate
                default_rate = (accounts_in_default / active_accounts.count() * 100) if active_accounts.count() > 0 else 0
                
                # Average days overdue
                avg_days_overdue = Decimal('0.00')
                if overdue_emis.exists():
                    total_days = sum([(date - emi.due_date).days for emi in overdue_emis])
                    avg_days_overdue = Decimal(str(total_days / overdue_emis.count()))
                
                # FPD counts for this tier
                date_3 = date - timedelta(days=3)
                date_7 = date - timedelta(days=7)
                date_15 = date - timedelta(days=15)
                
                def count_fpd(target_date):
                    contracts = active_accounts.filter(created_at__date=target_date)
                    overdue = 0
                    for contract in contracts:
                        first_emi = contract.emi_schedule.filter(installment_number=1).first()
                        if first_emi and first_emi.status in ['OVERDUE', 'PARTIALLY_PAID']:
                            overdue += 1
                    return overdue
                
                fpd_3_count = count_fpd(date_3)
                fpd_7_count = count_fpd(date_7)
                fpd_15_count = count_fpd(date_15)
                
                RiskAnalysisMetrics.objects.update_or_create(
                    date=date,
                    risk_tier=tier,
                    store=store,
                    region=store.region,
                    defaults={
                        'total_accounts': active_accounts.count(),
                        'new_accounts': new_accounts.count(),
                        'active_accounts': active_accounts.count(),
                        'total_portfolio_value': portfolio_value,
                        'total_outstanding': outstanding,
                        'accounts_in_default': accounts_in_default,
                        'default_rate': Decimal(str(round(default_rate, 2))),
                        'average_days_overdue': avg_days_overdue,
                        'fpd_3_count': fpd_3_count,
                        'fpd_7_count': fpd_7_count,
                        'fpd_15_count': fpd_15_count,
                    }
                )
                count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} risk analysis records")
    
    # ========================================
    # PAYMENT COLLECTION METRICS
    # ========================================
    
    def aggregate_payment_collection(self, date, force=False):
        """Aggregate payment collection metrics"""
        self.stdout.write("  💳 Aggregating payment collection...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            # EMIs due on this date
            emis_due = EMISchedule.objects.filter(
                finance_plan__store=store,
                due_date=date
            )
            
            total_due = emis_due.aggregate(Sum('installment_amount'))['installment_amount__sum'] or Decimal('0.00')
            
            # Payments collected on this date
            payments = PaymentRecord.objects.filter(
                payment_date__date=date,
                finance_plan__store=store
            )
            
            total_collected = payments.filter(
                payment_status='COMPLETED'
            ).aggregate(Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')
            
            # Overdue amount
            overdue_emis = EMISchedule.objects.filter(
                finance_plan__store=store,
                status='OVERDUE',
                due_date__lte=date
            )
            
            total_overdue = overdue_emis.aggregate(Sum('balance_remaining'))['balance_remaining__sum'] or Decimal('0.00')
            
            # Payment methods breakdown
            cash = payments.filter(payment_method='CASH', payment_status='COMPLETED').aggregate(
                Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')
            
            yappy = payments.filter(payment_method='YAPPY', payment_status='COMPLETED').aggregate(
                Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')
            
            punto_pago = payments.filter(payment_method='PUNTO_PAGO', payment_status='COMPLETED').aggregate(
                Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')
            
            western_union = payments.filter(payment_method='WESTERN_UNION', payment_status='COMPLETED').aggregate(
                Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')
            
            bank_transfer = payments.filter(payment_method='BANK_TRANSFER', payment_status='COMPLETED').aggregate(
                Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')
            
            # Collection rate
            collection_rate = (total_collected / total_due * 100) if total_due > 0 else 0
            
            # On-time payment rate
            on_time_payments = EMISchedule.objects.filter(
                finance_plan__store=store,
                due_date=date,
                status='PAID',
                paid_date=date
            ).count()
            
            on_time_rate = (on_time_payments / emis_due.count() * 100) if emis_due.exists() else 0
            
            # Delinquency aging
            accounts_overdue = overdue_emis.values('finance_plan').distinct().count()
            
            date_30 = date - timedelta(days=30)
            date_60 = date - timedelta(days=60)
            date_90 = date - timedelta(days=90)
            
            accounts_30 = EMISchedule.objects.filter(
                finance_plan__store=store,
                status='OVERDUE',
                due_date__lte=date,
                due_date__gt=date_30
            ).values('finance_plan').distinct().count()
            
            accounts_60 = EMISchedule.objects.filter(
                finance_plan__store=store,
                status='OVERDUE',
                due_date__lte=date_30,
                due_date__gt=date_60
            ).values('finance_plan').distinct().count()
            
            accounts_90_plus = EMISchedule.objects.filter(
                finance_plan__store=store,
                status='OVERDUE',
                due_date__lte=date_60
            ).values('finance_plan').distinct().count()
            
            PaymentCollectionMetrics.objects.update_or_create(
                date=date,
                store=store,
                region=store.region,
                defaults={
                    'total_due': total_due,
                    'total_collected': total_collected,
                    'total_overdue': total_overdue,
                    'cash_collected': cash,
                    'yappy_collected': yappy,
                    'punto_pago_collected': punto_pago,
                    'western_union_collected': western_union,
                    'bank_transfer_collected': bank_transfer,
                    'collection_rate': Decimal(str(round(collection_rate, 2))),
                    'on_time_payment_rate': Decimal(str(round(on_time_rate, 2))),
                    'accounts_overdue': accounts_overdue,
                    'accounts_30_days_overdue': accounts_30,
                    'accounts_60_days_overdue': accounts_60,
                    'accounts_90_days_plus_overdue': accounts_90_plus,
                }
            )
            count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} payment collection records")
    
    # ========================================
    # BRAND & PRODUCT PERFORMANCE
    # ========================================
    
    def aggregate_brand_performance(self, date, force=False):
        """Aggregate brand-level performance metrics"""
        self.stdout.write("  🏷️  Aggregating brand performance...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                store=store,
                device__isnull=False
            )
            
            if not finance_plans.exists():
                continue
            
            # Group by brand
            brands = finance_plans.values('device__brand').annotate(
                units=Count('id'),
                revenue=Sum('device_price'),
                avg_price=Avg('device_price')
            )
            
            for brand_data in brands:
                if brand_data['device__brand']:
                    brand = Brand.objects.get(id=brand_data['device__brand'])
                    
                    # Get top 5 models for this brand
                    top_models = finance_plans.filter(
                        device__brand=brand
                    ).values('device__model_name').annotate(
                        units=Count('id')
                    ).order_by('-units')[:5]
                    
                    top_models_list = [
                        {'model': m['device__model_name'], 'units': m['units']}
                        for m in top_models
                    ]
                    
                    BrandPerformanceMetrics.objects.update_or_create(
                        date=date,
                        brand=brand,
                        store=store,
                        region=store.region,
                        defaults={
                            'total_units_sold': brand_data['units'],
                            'total_revenue': brand_data['revenue'] or Decimal('0.00'),
                            'average_price': brand_data['avg_price'] or Decimal('0.00'),
                            'top_models': top_models_list,
                        }
                    )
                    count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} brand performance records")
    
    def aggregate_product_performance(self, date, force=False):
        """Aggregate product-level performance metrics"""
        self.stdout.write("  📦 Aggregating product performance...")
        
        stores = Store.objects.filter(is_active=True)
        count = 0
        
        for store in stores:
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                store=store,
                device__isnull=False
            )
            
            if not finance_plans.exists():
                continue
            
            # Group by product
            products = finance_plans.values('device').annotate(
                units=Count('id'),
                revenue=Sum('device_price'),
                avg_term=Avg('selected_term'),
                avg_down=Avg('actual_down_payment')
            )
            
            for product_data in products:
                if product_data['device']:
                    product = ProductModel.objects.get(id=product_data['device'])
                    
                    ProductPerformanceMetrics.objects.update_or_create(
                        date=date,
                        product=product,
                        store=store,
                        region=store.region,
                        defaults={
                            'units_sold': product_data['units'],
                            'revenue': product_data['revenue'] or Decimal('0.00'),
                            'average_finance_term': product_data['avg_term'] or Decimal('0.00'),
                            'average_down_payment': product_data['avg_down'] or Decimal('0.00'),
                        }
                    )
                    count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} product performance records")
    
    # ========================================
    # SALESPERSON PERFORMANCE
    # ========================================
    
    def aggregate_salesperson_performance(self, date, force=False):
        """Aggregate salesperson performance metrics"""
        self.stdout.write("  👨‍💼 Aggregating salesperson performance...")
        
        salespersons = CustomUser.objects.filter(
            role='salesperson',
            is_active=True
        )
        
        count = 0
        for sp in salespersons:
            applications = CreditApplication.objects.filter(
                created_at__date=date,
                sales_person=sp
            )
            
            if not applications.exists():
                continue
            
            apps_created = applications.count()
            apps_approved = applications.filter(status='APPROVED').count()
            apps_rejected = applications.filter(status='REJECTED').count()
            
            # Finance plans (actual sales)
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                created_by=sp
            )
            
            total_sales = finance_plans.aggregate(Sum('device_price'))['device_price__sum'] or Decimal('0.00')
            total_financed = finance_plans.aggregate(Sum('amount_to_finance'))['amount_to_finance__sum'] or Decimal('0.00')
            
            # Commission calculation (example: 2% of sales)
            commission = total_sales * Decimal('0.02')
            
            # Approval rate
            approval_rate = (apps_approved / apps_created * 100) if apps_created > 0 else 0
            
            # Average processing time (example calculation)
            avg_processing_time = 45  # Minutes - placeholder
            
            # New customers acquired
            new_customers = Customer.objects.filter(
                created_at__date=date,
                created_by=sp
            ).count()
            
            SalespersonPerformance.objects.update_or_create(
                date=date,
                salesperson=sp,
                store=sp.store,
                defaults={
                    'applications_created': apps_created,
                    'applications_approved': apps_approved,
                    'applications_rejected': apps_rejected,
                    'total_sales': total_sales,
                    'total_financed': total_financed,
                    'commission_earned': commission,
                    'approval_rate': Decimal(str(round(approval_rate, 2))),
                    'average_processing_time': avg_processing_time,
                    'new_customers_acquired': new_customers,
                }
            )
            count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} salesperson performance records")
    
    # ========================================
    # GEOGRAPHIC PERFORMANCE
    # ========================================
    
    def aggregate_geographic_performance(self, date, force=False):
        """Aggregate geographic performance metrics"""
        self.stdout.write("  🌍 Aggregating geographic performance...")
        
        regions = Region.objects.filter(is_active=True)
        count = 0
        
        for region in regions:
            stores_in_region = Store.objects.filter(region=region, is_active=True)
            active_stores = stores_in_region.filter(
                sales_analytics__date=date
            ).distinct().count()
            
            # Applications in this region
            applications = CreditApplication.objects.filter(
                created_at__date=date,
                sales_person__store__region=region
            )
            
            total_apps = applications.count()
            if total_apps == 0:
                continue
            
            # Finance plans (sales)
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                store__region=region
            )
            
            total_sales = finance_plans.aggregate(Sum('device_price'))['device_price__sum'] or Decimal('0.00')
            avg_ticket = finance_plans.aggregate(Avg('device_price'))['device_price__avg'] or Decimal('0.00')
            
            # Approval rate
            approved = applications.filter(status='APPROVED').count()
            approval_rate = (approved / total_apps * 100) if total_apps > 0 else 0
            
            # Collection rate
            payments_due = EMISchedule.objects.filter(
                finance_plan__store__region=region,
                due_date=date
            ).aggregate(Sum('installment_amount'))['installment_amount__sum'] or Decimal('0.00')
            
            payments_collected = PaymentRecord.objects.filter(
                payment_date__date=date,
                finance_plan__store__region=region,
                payment_status='COMPLETED'
            ).aggregate(Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')
            
            collection_rate = (payments_collected / payments_due * 100) if payments_due > 0 else 0
            
            # Market share (placeholder calculation)
            market_share = Decimal('15.5')
            
            GeographicPerformanceMetrics.objects.update_or_create(
                date=date,
                region=region,
                province=None,
                district=None,
                defaults={
                    'active_stores': active_stores,
                    'total_stores': stores_in_region.count(),
                    'total_applications': total_apps,
                    'total_sales': total_sales,
                    'average_ticket_size': avg_ticket,
                    'approval_rate': Decimal(str(round(approval_rate, 2))),
                    'collection_rate': Decimal(str(round(collection_rate, 2))),
                    'market_share_percentage': market_share,
                }
            )
            count += 1
            
            # Also aggregate by province and district
            provinces = Province.objects.filter(region=region)
            for province in provinces:
                # Similar aggregation for province level
                pass
        
        self.stdout.write(f"    ✓ Created/updated {count} geographic performance records")
    
    # ========================================
    # DEVICE LOCK PERFORMANCE
    # ========================================
    
    def aggregate_device_lock_performance(self, date, force=False):
        """Aggregate device lock system performance"""
        self.stdout.write("  🔒 Aggregating device lock performance...")
        
        stores = Store.objects.filter(is_active=True)
        lock_systems = ['KNOX', 'NUOVOPAY', 'BASEANDROID', 'ACCESS', 'BASEANDROID_FRP', 'KG']
        
        count = 0
        for store in stores:
            for lock_system in lock_systems:
                devices = DeviceEnrollmentCustomer.objects.filter(
                    created_at__date=date,
                    finance_plan__store=store,
                    locking_system=lock_system
                )
                
                if not devices.exists():
                    continue
                
                total_enrolled = devices.count()
                successful = devices.filter(enrollment_status='COMPLETED').count()
                failed = devices.filter(enrollment_status='FAILED').count()
                
                enrollment_success_rate = (successful / total_enrolled * 100) if total_enrolled > 0 else 0
                
                devices_locked = devices.filter(is_locked=True).count()
                devices_unlocked = devices.filter(is_locked=False, enrollment_status='COMPLETED').count()
                devices_active = devices.filter(enrollment_status='COMPLETED').count()
                
                # Unlock requests (placeholder)
                unlock_requests = 0
                
                DeviceLockPerformanceMetrics.objects.update_or_create(
                    date=date,
                    lock_system=lock_system,
                    store=store,
                    region=store.region,
                    defaults={
                        'devices_enrolled': total_enrolled,
                        'enrollment_success_rate': Decimal(str(round(enrollment_success_rate, 2))),
                        'devices_locked': devices_locked,
                        'devices_unlocked': devices_unlocked,
                        'devices_active': devices_active,
                        'lock_failures': failed,
                        'unlock_requests': unlock_requests,
                    }
                )
                count += 1
        
        self.stdout.write(f"    ✓ Created/updated {count} device lock performance records")

# ========================================
# HELPER COMMAND FOR TESTING
# ========================================

"""
Usage Examples:

# Aggregate yesterday's data
python manage.py aggregate_analytics

# Aggregate specific date
python manage.py aggregate_analytics --date=2025-01-15

# Aggregate last 30 days
python manage.py aggregate_analytics --days=30

# Force re-aggregation
python manage.py aggregate_analytics --days=7 --force

# Aggregate specific type only
python manage.py aggregate_analytics --type=sales
python manage.py aggregate_analytics --type=fpd
python manage.py aggregate_analytics --type=payment

# Cron job setup (run daily at 2 AM)
0 2 * * * cd /path/to/project && python manage.py aggregate_analytics >> /var/log/analytics.log 2>&1
"""