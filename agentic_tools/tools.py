
from typing import Dict, Any

from agentic_tools.alert_center_tools import get_alert_types
from agentic_tools.customer_data_tools import manage_cdp_segment, show_all_segments
from agentic_tools.data_enrichment_tools import analyze_segment
from agentic_tools.datetime_tools import get_date
from agentic_tools.marketing_tools import activate_channel, get_marketing_events
from agentic_tools.weather_tools import get_current_weather


# =====================================================
# LLM-CALLABLE TOOLS (With Mandatory Docstrings)
# =====================================================

AVAILABLE_TOOLS: Dict[str, Any] = {
    "get_date": get_date,
    "get_current_weather": get_current_weather,
    "get_marketing_events": get_marketing_events,
    "get_alert_types": get_alert_types,
    "manage_cdp_segment": manage_cdp_segment,
    "analyze_segment": analyze_segment,
    "show_all_segments": show_all_segments,
    "activate_channel": activate_channel,
}