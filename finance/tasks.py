import requests
import base64
import json
import logging
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from finance.models import EMISchedule, AuditLog
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def send_emi_sms(msisdn, message):
    """Send SMS using your SMS API"""
    userToken = settings.LAB_MOBILES_TOKEN
    credentials = base64.b64encode(userToken.encode()).decode()
    url = settings.SMS_API_URL

    payload = json.dumps({
        "message": message,
        "tpoa": settings.SENDER,
        "recipient": [{"msisdn": msisdn}]
    })

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Basic {credentials}',
        'Cache-Control': "no-cache"
    }

    try:
        response = requests.post(url, headers=headers, data=payload)
        return {"status": response.status_code, "response": response.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@shared_task
def send_emi_reminders():
    today = timezone.now().date()
    
    reminder_offsets = {
        '5_days_before': 5,
        '1_day_before': 1,
        'due_today': 0,
    }

    for reminder_type, offset in reminder_offsets.items():
        reminder_date = today + timedelta(days=offset)

        emis = EMISchedule.objects.filter(
            due_date=reminder_date,
            status__in=['UPCOMING', 'DUE']
        ).select_related('finance_plan__credit_application__customer')

        if not emis.exists():
            continue

        emi_ids = [emi.id for emi in emis]
        sent_logs = AuditLog.objects.filter(
            action_type='FINANCE_COLLECTIONS_VIEWED',
            metadata__emi_schedule_id__in=emi_ids,
            metadata__reminder_type=reminder_type
        ).values_list('metadata__emi_schedule_id', flat=True)

        sent_emi_ids = set(sent_logs)
        emis_to_send = [emi for emi in emis if emi.id not in sent_emi_ids]

        if not emis_to_send:
            logger.info(f"No new EMI reminders for {reminder_type} on {reminder_date}")
            continue

        for emi in emis_to_send:
            customer = emi.finance_plan.credit_application.customer
            phone_number = customer.phone_number

            message_text = f"Reminder: Your EMI #{emi.installment_number} of amount {emi.installment_amount} is due on {emi.due_date}."

            success, response_text = send_emi_sms(phone_number, message_text)

            AuditLog.objects.create(
                action_type='FINANCE_COLLECTIONS_VIEWED',
                user=None,
                customer=customer,
                credit_application=emi.finance_plan.credit_application,
                description=f"EMI Reminder ({reminder_type}) sent to {phone_number} for EMI #{emi.installment_number} of FinancePlan {emi.finance_plan.id}",
                metadata={
                    "emi_schedule_id": emi.id,
                    "installment_number": emi.installment_number,
                    "reminder_type": reminder_type,
                    "emi_amount": str(emi.installment_amount),
                    "due_date": str(emi.due_date),
                    "sms_status": "SENT" if success else "FAILED",
                    "sms_response": response_text
                },
                ip_address=None
            )
            logger.info(f"EMI reminder ({reminder_type}) sent to {phone_number} for EMI #{emi.installment_number}")
