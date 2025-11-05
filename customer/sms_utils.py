import requests
import base64
import json
from django.conf import settings


def send_sms(recipient_number, message):
    """
    Send an SMS using LabsMobile API
    """
    user_token = settings.LAB_MOBILES_TOKEN  
    credentials = base64.b64encode(user_token.encode()).decode()

    if not user_token:
        print("❌ [SMS ERROR] LABSMOBILE_API_TOKEN is missing or not loaded from settings.py")
        return {"error": "Missing LABSMOBILE_API_TOKEN"}

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

    print("📤 Sending SMS via LabsMobile:")
    print("URL:", url)
    print("Recipient:", recipient_number)
    print("Message:", message)
    print("Headers:", headers)

    try:
        response = requests.post(url, headers=headers, data=payload)
        print("✅ [SMS Response Status]:", response.status_code)
        print("✅ [SMS Response Body]:", response.text)
        return response.json()
    except Exception as e:
        print("❌ [SMS Exception]:", str(e))
        return {"error": str(e)}
