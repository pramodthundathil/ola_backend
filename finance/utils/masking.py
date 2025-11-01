
def mask_sensitive_data(data, role):
    """
    Mask sensitive fields for non-admin roles.
    """
    if isinstance(data, list):
        return [mask_sensitive_data(d, role) for d in data]
    elif isinstance(data, dict):
        masked = data.copy()
        if role not in ["Admin", "FinanceManager", "GlobalManager"]:
            if "customer" in masked:
                customer = masked["customer"]
                customer["name"] = customer.get("name", "")[:2] + "****"
                if "email" in customer:
                    customer["email"] = "***@***"
                if "phone" in customer:
                    customer["phone"] = "*******" + customer["phone"][-3:]
                masked["customer"] = customer
            if "apc_score" in masked:
                masked["apc_score"] = "****"
        return masked
    return data
