




import logging
from typing import Dict, Optional


logger = logging.getLogger("agentic_tools.alert_center")

def get_alert_types(tenant_id: Optional[str] = None) -> Dict[str, str]:
    """
    show all alert types for the given tenant.

    Args:
        tenant_id: the unique identifier for the tenant. If None, defaults to the current tenant.

    Returns:
        A list of alert types with their IDs and names.
    """

    logger.info("show all alert types for the given tenant_id: %s", tenant_id)

    # TODO: Replace with real API call to fetch alert types
    alert_types = [{"alert_type_id": "at_001", "name": "Low Inventory Alert"},
                   {"alert_type_id": "at_002", "name": "High Traffic Alert"},
                   {"alert_type_id": "at_003", "name": "New User Registration Alert"},
                   {"alert_type_id": "at_004", "name": "Customer Churn Risk Alert"},
                   {"alert_type_id": "at_005", "name": "Marketing Campaign Performance Alert"},
                   {"alert_type_id": "at_006", "name": "System Maintenance Required Alert"}]
    return alert_types