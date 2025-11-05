import requests
import base64
import json
from django.conf import settings


def send_sms(recipient_number, message):
    """
    Send an SMS using LabsMobile API
    """
    user_token = settings.LAB_MOBILES_TOKEN 
    
    if not user_token:
        return {"error": "Missing LABSMOBILE_TOKEN"} 
    credentials = base64.b64encode(user_token.encode()).decode()


    url = "https://api.labsmobile.com/json/send"

    payload = json.dumps({
        "message": message,
        "tpoa": "ola-credits",
        "recipient": [{"msisdn": recipient_number}]
    })

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {credentials}",
        "Cache-Control": "no-cache"
    }

    try:
        response = requests.post(url, headers=headers, data=payload)
        return response.json()
    except Exception as e:
        return {"error": str(e)}
