from celery import shared_task
from django.utils import timezone
from datetime import datetime, timedelta
import logging

from analytics.services import AnalyticsService

logger = logging.getLogger(__name__)


@shared_task
def run_daily_aggregations_task(date_str=None):
    """
    Main Celery task to run all analytics aggregates for a specific date.
    Called daily by Celery Beat or manually triggered.
    """
    if date_str:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        target_date = timezone.now().date() - timedelta(days=1)
        
    logger.info(f"Starting Celery analytics aggregation task for date: {target_date}")
    
    try:
        # Run daily core analytics aggregates
        AnalyticsService.aggregate_daily_analytics(target_date)
        AnalyticsService.aggregate_merchant_analytics(target_date)
        AnalyticsService.aggregate_branch_analytics(target_date)
        AnalyticsService.aggregate_device_analytics(target_date)
        AnalyticsService.aggregate_customer_analytics(target_date)
        AnalyticsService.aggregate_risk_analytics(target_date)
        AnalyticsService.aggregate_executive_analytics(target_date)
        AnalyticsService.aggregate_collection_analytics(target_date)
        AnalyticsService.aggregate_dashboard_summary(target_date)
        
        logger.info(f"Completed Celery analytics aggregation task for date: {target_date}")
        return f"Successfully processed aggregations for {target_date}"
    except Exception as e:
        logger.error(f"Error executing daily aggregations: {str(e)}", exc_info=True)
        raise e


@shared_task
def update_daily_analytics_task(date_str):
    """Task to trigger specific daily core metrics updates"""
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    AnalyticsService.aggregate_daily_analytics(target_date)
    AnalyticsService.aggregate_dashboard_summary(target_date)
    return f"Daily metrics updated for {target_date}"


@shared_task
def update_merchant_analytics_task(date_str):
    """Task to update specific merchant metric aggregates"""
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    AnalyticsService.aggregate_merchant_analytics(target_date)
    return f"Merchant metrics updated for {target_date}"


@shared_task
def update_branch_analytics_task(date_str):
    """Task to update specific branch metric aggregates"""
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    AnalyticsService.aggregate_branch_analytics(target_date)
    return f"Branch metrics updated for {target_date}"


@shared_task
def update_device_analytics_task(date_str):
    """Task to update specific device metric aggregates"""
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    AnalyticsService.aggregate_device_analytics(target_date)
    return f"Device metrics updated for {target_date}"


@shared_task
def update_customer_analytics_task(date_str):
    """Task to update specific customer metric aggregates"""
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    AnalyticsService.aggregate_customer_analytics(target_date)
    return f"Customer metrics updated for {target_date}"


@shared_task
def update_risk_analytics_task(date_str):
    """Task to update specific risk metric aggregates"""
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    AnalyticsService.aggregate_risk_analytics(target_date)
    return f"Risk metrics updated for {target_date}"


@shared_task
def update_executive_analytics_task(date_str):
    """Task to update specific sales executive metrics"""
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    AnalyticsService.aggregate_executive_analytics(target_date)
    return f"Executive metrics updated for {target_date}"


@shared_task
def update_collection_analytics_task(date_str):
    """Task to update specific collections metric aggregates"""
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    AnalyticsService.aggregate_collection_analytics(target_date)
    return f"Collections metrics updated for {target_date}"
