# ================================================
#  FINANCE FILTER HELPER CLASS 
# ================================================

class FinancePlanFilter:
    """
    for filter finance plan
    """

    @staticmethod
    def apply_filters(queryset, params):
        """Apply all FinancePlan filters cleanly."""

        # ---------------- BASIC FILTERS ----------------
        emi_id = params.get("emi_id")
        customer_id = params.get("customer_id")
        product_id = params.get("product_id")
        apc_score = params.get("apc_score")

        if emi_id:
            queryset = queryset.filter(emi_schedule__id=emi_id)

        if customer_id:
            queryset = queryset.filter(credit_application__customer__id=customer_id)

        if product_id:
            queryset = queryset.filter(device__id=product_id)

        if apc_score:
            queryset = queryset.filter(apc_score=apc_score)

        # ---------------- FINANCEPLAN FILTERS ----------------
        mappings = {
            "status": "status",
            "risk_tier": "risk_tier",
            "selected_term": "selected_term",
            "installment_frequency_days": "installment_frequency_days",
            "score_status": "score_status",
            "disbursement_status": "disbursement_status",
        }

        for param, field in mappings.items():
            value = params.get(param)
            if value:
            # convert to upper for enum fields
                if param == "risk_tier":
                    value = value.upper()
                queryset = queryset.filter(**{field: value})
            # if value:
            #     queryset = queryset.filter(**{field: value})

        # Boolean filters
        bool_fields = [
            ("is_active", "is_active"),
            ("is_high_end_device", "is_high_end_device"),
            ("payment_capacity_passed", "payment_capacity_passed"),
            ("conditions_met", "conditions_met"),
            ("requires_adjustment", "requires_adjustment"),
        ]

        for param, field in bool_fields:
            val = params.get(param)
            if val is not None:
                queryset = queryset.filter(**{field: val.lower() == "true"})

        # Amount ranges
        ranges = [
            ("min_amount_to_finance", "amount_to_finance__gte"),
            ("max_amount_to_finance", "amount_to_finance__lte"),
            ("min_monthly_installment", "monthly_installment__gte"),
            ("max_monthly_installment", "monthly_installment__lte"),
            ("min_device_price", "device_price__gte"),
            ("max_device_price", "device_price__lte"),
        ]

        for param, field in ranges:
            value = params.get(param)
            if value:
                queryset = queryset.filter(**{field: value})

        # ---------------- CUSTOMER FILTERS ----------------
        if params.get("customer_document_number"):
            queryset = queryset.filter(
                credit_application__customer__document_number=params["customer_document_number"]
            )

        if params.get("customer_phone"):
            queryset = queryset.filter(
                credit_application__customer__phone_number=params["customer_phone"]
            )

        if params.get("customer_email"):
            queryset = queryset.filter(
                credit_application__customer__email=params["customer_email"]
            )

        if params.get("customer_status"):
            queryset = queryset.filter(
                credit_application__customer__status=params["customer_status"]
            )

        if params.get("customer_created_by"):
            queryset = queryset.filter(
                credit_application__customer__created_by_id=params["customer_created_by"]
            )

        # ---------------- STORE FILTERS ----------------
        store_filters = {
            "store_id": "store_id",
            "region_id": "store__region_id",
            "province_id": "store__province_id",
            "district_id": "store__district_id",
            "corregimiento_id": "store__corregimiento_id",
            "store_channel": "store__channel",
        }

        for p, f in store_filters.items():
            v = params.get(p)
            if v:
                queryset = queryset.filter(**{f: v})

        # ---------------- PRODUCT FILTERS ----------------
        product_filters = {
            "brand_id": "device__brand_id",
            "category_id": "device__brand__category_id",
            "model_name": "device__model_name__icontains",
            "ram": "device__ram__icontains",
            "storage": "device__storage__icontains",
            "processor": "device__processor__icontains",
            "condition": "device__condition",
            "color": "device__color__icontains",
            "release_year": "device__release_year",
        }

        for param, field in product_filters.items():
            value = params.get(param)
            if value:
                queryset = queryset.filter(**{field: value})

        # Suggested price range
        if params.get("device_min_price"):
            queryset = queryset.filter(device__suggested_price__gte=params["device_min_price"])

        if params.get("device_max_price"):
            queryset = queryset.filter(device__suggested_price__lte=params["device_max_price"])

        return queryset.distinct()
