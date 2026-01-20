from datetime import date, datetime
import logging
from typing import Dict, Optional

logger = logging.getLogger("agentic_tools.datetime")

def get_date(input_date: Optional[str] = None) -> Dict[str, str]:
    """
    Get date or retrieves the current server date and time.
    
    Use this tool when the user asks questions involving "today", "now", 
    or requires the current date to calculate relative dates (e.g., "next Friday").

    Args:
        input_date: An optional reference date string in 'YYYY-MM-DD' format. 
            If not provided, the function defaults to the current date. 
            Example: "2023-12-25"

    Returns:
        A dictionary containing current_date, timestamp, day_of_week, and resolved_date.
    """
    today_obj = date.today()
    now_obj = datetime.now()
    
    today_str = str(today_obj)
    
    # Logic to handle the optional input
    resolved_input = input_date if input_date else today_str

    return {
        "current_date": today_str,
        "timestamp": now_obj.strftime("%Y-%m-%d %H:%M:%S"),
        "day_of_week": now_obj.strftime("%A"),
        "resolved_date": resolved_input,
    }