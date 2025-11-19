"""
Management command to aggregate analytics data
Run daily via cron: python manage.py aggregate_analytics
"""

from django.core.management.base import BaseCommand
from django.db.models import Sum, Avg, Count, Q
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal

from analytics.models import (
    SalesAnalytics, ApplicationFunnelAnalytics, DeviceEnrollmentAnalytics,
    BrandModelAnalytics, GeographicAnalytics, FPDAnalytics,
    FinancialMetrics, ClerkPerformanceAnalytics, HourlyAnalytics
)
from finance.models import FinancePlan, EMISchedule, PaymentRecord
from customer.models import CreditApplication
from store.models import Store
from home.models import CustomUser
from customer_device.models import DeviceEnrollmentCustomer


class Command(BaseCommand):
    help = 'Aggregate analytics data for dashboard'
    
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
    
    def handle(self, *args, **options):
        # Determine date range
        if options['date']:
            end_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
        else:
            end_date = timezone.now().date() - timedelta(days=1)
        
        start_date = end_date - timedelta(days=options['days'] - 1)
        
        self.stdout.write(f"Aggregating analytics from {start_date} to {end_date}")
        
        for single_date in self.daterange(start_date, end_date):
            self.stdout.write(f"\nProcessing {single_date}...")
            
            try:
                self.aggregate_sales_analytics(single_date)
                self.aggregate_funnel_analytics(single_date)
                self.aggregate_device_analytics(single_date)
                self.aggregate_brand_analytics(single_date)
                self.aggregate_geographic_analytics(single_date)
                self.aggregate_fpd_analytics(single_date)
                self.aggregate_financial_metrics(single_date)
                self.aggregate_clerk_performance(single_date)
                self.aggregate_hourly_analytics(single_date)
                
                self.stdout.write(self.style.SUCCESS(f"✓ Completed {single_date}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Error on {single_date}: {str(e)}"))
    
    def daterange(self, start_date, end_date):
        """Generate date range"""
        for n in range(int((end_date - start_date).days) + 1):
            yield start_date + timedelta(n)
    
    def aggregate_sales_analytics(self, date):
        """Aggregate sales metrics by store and salesperson"""
        # Get all finance plans created on this date
        finance_plans = FinancePlan.objects.filter(
            created_at__date=date,
            status='ACTIVE'
        )
        
        # Group by store
        stores = Store.objects.filter(is_active=True)
        
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
    
    def aggregate_funnel_analytics(self, date):
        """Aggregate application funnel metrics"""
        stores = Store.objects.filter(is_active=True)
        
        for store in stores:
            # Get applications for this store on this date
            applications = CreditApplication.objects.filter(
                created_at__date=date,
                sales_person__store=store
            )
            
            if applications.exists():
                total_apps = applications.count()
                
                # Count stages (adjust based on your actual workflow)
                kyc_completed = applications.filter(
                    customer__identity_verification__overall_status='VERIFIED'
                ).count()
                
                approved = applications.filter(status='APPROVED').count()
                
                sales = FinancePlan.objects.filter(
                    credit_application__in=applications,
                    status='ACTIVE'
                ).count()
                
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
                        'kyc_completed': kyc_completed,
                        'approved': approved,
                        'sales': sales,
                        'kyc_success_rate': Decimal(str(round(kyc_rate, 2))),
                        'approval_rate': Decimal(str(round(approval_rate, 2))),
                        'take_rate': Decimal(str(round(take_rate, 2))),
                        'conversion_rate': Decimal(str(round(conversion_rate, 2)))
                    }
                )
    
    def aggregate_device_analytics(self, date):
        """Aggregate device enrollment by lock type"""
        stores = Store.objects.filter(is_active=True)
        
        for store in stores:
            devices = DeviceEnrollmentCustomer.objects.filter(
                created_at__date=date,
                finance_plan__store=store
            )
            
            if devices.exists():
                # Count by lock type (adjust field names based on your model)
                lock_counts = {
                    'base_android': devices.filter(locking_system='NUOVOPAY').count(),
                    'knox': devices.filter(locking_system='KNOX').count(),
                    # Add other lock types as needed
                }
                
                total = devices.count()
                
                DeviceEnrollmentAnalytics.objects.update_or_create(
                    date=date,
                    store=store,
                    defaults={
                        'lock_base_android': lock_counts.get('base_android', 0),
                        'lock_kg': lock_counts.get('knox', 0),
                        'total_devices_enrolled': total
                    }
                )
    
    def aggregate_brand_analytics(self, date):
        """Aggregate sales by brand and model"""
        stores = Store.objects.filter(is_active=True)
        
        for store in stores:
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                store=store,
                device__isnull=False
            )
            
            # Group by brand
            brands = finance_plans.values(
                'device__brand__name',
                'device__model_name'
            ).annotate(
                sales_count=Count('id'),
                total_amount=Sum('device_price')
            )
            
            for brand_data in brands:
                BrandModelAnalytics.objects.update_or_create(
                    date=date,
                    store=store,
                    brand_name=brand_data['device__brand__name'],
                    model_name=brand_data['device__model_name'],
                    defaults={
                        'sales_count': brand_data['sales_count'],
                        'total_amount': brand_data['total_amount'] or Decimal('0.00')
                    }
                )
    
    def aggregate_geographic_analytics(self, date):
        """Aggregate sales by geographic location"""
        finance_plans = FinancePlan.objects.filter(
            created_at__date=date,
            store__isnull=False
        )
        
        # Group by region/province/district
        geo_groups = finance_plans.values(
            'store__region',
            'store__province__name',
            'store__district__name'
        ).annotate(
            sales_count=Count('id'),
            total_amount=Sum('device_price')
        )
        
        for geo_data in geo_groups:
            GeographicAnalytics.objects.update_or_create(
                date=date,
                region_id=geo_data['store__region'],
                province_name=geo_data['store__province__name'],
                district_name=geo_data['store__district__name'],
                defaults={
                    'sales_count': geo_data['sales_count'],
                    'total_amount': geo_data['total_amount'] or Decimal('0.00')
                }
            )
    
    def aggregate_fpd_analytics(self, date):
        """Aggregate FPD metrics"""
        # Calculate FPD for contracts that are 3, 7, 15 days old
        stores = Store.objects.filter(is_active=True)
        
        for store in stores:
            # Get contracts from appropriate dates
            date_3 = date - timedelta(days=3)
            date_7 = date - timedelta(days=7)
            date_15 = date - timedelta(days=15)
            
            contracts_3 = FinancePlan.objects.filter(
                created_at__date=date_3,
                store=store,
                status='ACTIVE'
            )
            
            contracts_7 = FinancePlan.objects.filter(
                created_at__date=date_7,
                store=store,
                status='ACTIVE'
            )
            
            contracts_15 = FinancePlan.objects.filter(
                created_at__date=date_15,
                store=store,
                status='ACTIVE'
            )
            
            # Calculate FPD rates (contracts with overdue first payment)
            def calc_fpd(contracts):
                if not contracts.exists():
                    return 0
                
                total = contracts.count()
                overdue = 0
                
                for contract in contracts:
                    first_emi = contract.emi_schedule.filter(installment_number=1).first()
                    if first_emi and first_emi.status == 'OVERDUE':
                        overdue += 1
                
                return (overdue / total * 100) if total > 0 else 0
            
            fpd_3 = calc_fpd(contracts_3)
            fpd_7 = calc_fpd(contracts_7)
            fpd_15 = calc_fpd(contracts_15)
            
            total_contracts = FinancePlan.objects.filter(
                store=store,
                status='ACTIVE'
            ).count()
            
            FPDAnalytics.objects.update_or_create(
                date=date,
                store=store,
                defaults={
                    'fpd_3_rate': Decimal(str(round(fpd_3, 2))),
                    'fpd_7_rate': Decimal(str(round(fpd_7, 2))),
                    'fpd_15_rate': Decimal(str(round(fpd_15, 2))),
                    'total_contracts': total_contracts
                }
            )
    
    def aggregate_financial_metrics(self, date):
        """Aggregate financial metrics"""
        stores = Store.objects.filter(is_active=True)
        
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
                    avg_multiple=Avg('monthly_installment'),
                    avg_term=Avg('selected_term')
                )
                
                # Get collections for this date
                collections = PaymentRecord.objects.filter(
                    payment_date__date=date,
                    finance_plan__store=store,
                    payment_status='COMPLETED'
                ).aggregate(Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')
                
                # Calculate outstanding
                outstanding = EMISchedule.objects.filter(
                    finance_plan__store=store,
                    status__in=['DUE', 'OVERDUE']
                ).aggregate(Sum('balance_remaining'))['balance_remaining__sum'] or Decimal('0.00')
                
                FinancialMetrics.objects.update_or_create(
                    date=date,
                    store=store,
                    salesperson=None,
                    defaults={
                        'total_revenue': metrics['total_revenue'] or Decimal('0.00'),
                        'total_financed_amount': metrics['total_financed'] or Decimal('0.00'),
                        'total_down_payment': metrics['total_down'] or Decimal('0.00'),
                        'avg_multiple': metrics['avg_multiple'] or Decimal('0.00'),
                        'avg_term_months': metrics['avg_term'] or Decimal('0.00'),
                        'collections_received': collections,
                        'outstanding_amount': outstanding
                    }
                )
    
    def aggregate_clerk_performance(self, date):
        """Aggregate salesperson performance"""
        salespersons = CustomUser.objects.filter(
            role='salesperson',
            is_active=True
        )
        
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
    
    def aggregate_hourly_analytics(self, date):
        """Aggregate sales by hour and day of week"""
        stores = Store.objects.filter(is_active=True)
        
        for store in stores:
            finance_plans = FinancePlan.objects.filter(
                created_at__date=date,
                store=store
            )
            
            # Group by hour
            for hour in range(24):
                hour_plans = finance_plans.filter(created_at__hour=hour)
                
                if hour_plans.exists():
                    day_of_week = date.strftime('%A')
                    
                    HourlyAnalytics.objects.update_or_create(
                        date=date,
                        store=store,
                        hour=hour,
                        day_of_week=day_of_week,
                        defaults={
                            'sales_count': hour_plans.count()
                        }
                    )