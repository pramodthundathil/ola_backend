"""
Mask sensitive fields for non-admin roles in Ola Backend.
"""

def mask_sensitive_data(data, role):
    """
    Recursively masks sensitive fields for non-privileged roles.
    """
    privileged_roles = ['admin', 'global_manager', 'financial_manager']
    
    if isinstance(data, list):
        return [mask_sensitive_data(item, role) for item in data]
    
    if isinstance(data, dict):
        if role in privileged_roles:
            return data
            
        masked_data = {}
        for key, value in data.items():
            # Recursively handle nested dictionaries and lists
            if isinstance(value, (dict, list)):
                masked_data[key] = mask_sensitive_data(value, role)
            
            # Mask sensitive keys
            elif key in ['document_number', 'email', 'phone_number', 'phone', 'first_name', 'last_name', 'name', 'apc_score', 'income_amount', 'installment_amount']:
                if value is None:
                    masked_data[key] = None
                elif key == 'email':
                    masked_data[key] = "********@***.***"
                elif key in ['phone_number', 'phone', 'document_number']:
                    s_val = str(value)
                    masked_data[key] = "*" * (max(0, len(s_val) - 4)) + s_val[-4:] if len(s_val) > 4 else "****"
                else:
                    masked_data[key] = "****"
            else:
                masked_data[key] = value
        return masked_data
        
    return data
