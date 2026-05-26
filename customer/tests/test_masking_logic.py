import pytest
from finance.utils.masking import mask_sensitive_data

def test_mask_sensitive_data_recursive():
    data = {
        "id": 1,
        "document_number": "123456789",
        "email": "test@example.com",
        "customer": {
            "name": "John Doe",
            "phone": "50712345678"
        },
        "plans": [
            {"id": 10, "installment_amount": 50.0},
            {"id": 11, "installment_amount": 75.0}
        ],
        "non_sensitive": "public_info"
    }
    
    # Test for privileged role (no masking)
    admin_result = mask_sensitive_data(data, 'admin')
    assert admin_result == data
    
    # Test for non-privileged role (masking)
    user_result = mask_sensitive_data(data, 'salesperson')
    
    # Check top-level masking
    assert user_result["document_number"] == "*****6789"
    assert user_result["email"] == "********@***.***"
    assert user_result["non_sensitive"] == "public_info"
    
    # Check nested dict masking
    assert user_result["customer"]["name"] == "****"
    assert user_result["customer"]["phone"] == "*******5678"
    
    # Check nested list masking
    assert user_result["plans"][0]["installment_amount"] == "****"
    assert user_result["plans"][1]["installment_amount"] == "****"

def test_mask_sensitive_data_none_values():
    data = {"email": None, "phone": None}
    result = mask_sensitive_data(data, 'salesperson')
    assert result["email"] is None
    assert result["phone"] is None

def test_mask_sensitive_data_short_values():
    data = {"document_number": "123"}
    result = mask_sensitive_data(data, 'salesperson')
    assert result["document_number"] == "****"
