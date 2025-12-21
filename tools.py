import os
import requests
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Dict, Any, Type

# =====================================================
# 1. ACTIVATION CHANNEL STRATEGY LAYER (OOP)
# =====================================================

class NotificationChannel(ABC):
    """Base strategy for all activation channels."""
    @abstractmethod
    def send(self, recipient_segment: str, message: str, **kwargs) -> Dict[str, Any]:
        pass

class EmailChannel(NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs):
        print(f"[Email] Segment={recipient_segment} | Message={message}")
        return {"status": "success", "channel": "email", "sent": 120}

class ZaloOAChannel(NotificationChannel):
    def __init__(self):
        self.api_url = "https://openapi.zalo.me/v3.0/oa/message/cs"
        self.access_token = os.getenv("ZALO_OA_TOKEN")

    def send(self, recipient_segment: str, message: str, **kwargs):
        print(f"[Zalo OA] Segment={recipient_segment}")
        return {"status": "success", "channel": "zalo_oa", "delivered": True}

class MobilePushChannel(NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs):
        title = kwargs.get("title", "Notification")
        print(f"[Mobile Push] Segment={recipient_segment} | Title={title}")
        return {"status": "success", "channel": "mobile_push"}

class WebPushChannel(NotificationChannel):
    def send(self, recipient_segment: str, message: str, **kwargs):
        print(f"[Web Push] Segment={recipient_segment}")
        return {"status": "success", "channel": "web_push"}

class ActivationManager:
    """Factory + registry for activation channels."""
    _channels: Dict[str, Type[NotificationChannel]] = {
        "email": EmailChannel,
        "zalo": ZaloOAChannel,
        "mobile_push": MobilePushChannel,
        "web_push": WebPushChannel,
    }

    @classmethod
    def execute(cls, channel_key: str, segment: str, message: str, **kwargs) -> Dict[str, Any]:
        channel_class = cls._channels.get(channel_key.lower())
        if not channel_class:
            raise ValueError(f"Unsupported channel: {channel_key}")
        return channel_class().send(segment, message, **kwargs)

# =====================================================
# 2. LLM-CALLABLE TOOLS (With Mandatory Docstrings)
# =====================================================

def get_date(input_date: str = str(date.today())) -> Dict[str, str]:
    """
    Return current date/time and echo input date.

    Args:
        input_date: The date string to process or echo.
    """
    now = datetime.now()
    return {
        "current_date": str(date.today()),
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "input_date": input_date,
    }

def get_current_weather(location: str, unit: str = "celsius") -> Dict[str, Any]:
    """
    Get real-time weather using Open-Meteo API.

    Args:
        location: The city or location name (e.g., 'Saigon').
        unit: Temperature unit, either 'celsius' or 'fahrenheit'.
    """
    locations = {
        "saigon": {"lat": 10.8231, "lon": 106.6297},
        "ho chi minh city": {"lat": 10.8231, "lon": 106.6297},
        "hanoi": {"lat": 21.0285, "lon": 105.8542},
        "tokyo": {"lat": 35.6895, "lon": 139.6917},
    }
    loc_key = location.lower().split(",")[0].strip()
    coords = locations.get(loc_key, locations["saigon"])
    url = f"https://api.open-meteo.com/v1/forecast?latitude={coords['lat']}&longitude={coords['lon']}&current_weather=true"

    try:
        response = requests.get(url, timeout=10).json()
        current = response.get("current_weather", {})
        return {
            "location": location,
            "temperature": f"{current.get('temperature', 'N/A')}°{unit[0].upper()}",
            "condition_code": current.get("weathercode"),
            "source": "Open-Meteo",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def manage_leo_segment(segment_name: str, action: str = "create") -> Dict[str, str]:
    """
    Create, update, or delete a LEO CDP segment.

    Args:
        segment_name: The name of the target segment.
        action: The management action (create, update, or delete).
    """
    return {"status": "success", "segment": segment_name, "action": action}

def activate_channel(channel: str, segment_name: str, message: str, title: str = "Notification") -> Dict[str, Any]:
    """
    LEO CDP activation tool for sending messages.

    Args:
        channel: Channel type (email, zalo, mobile_push, or web_push).
        segment_name: The target segment for activation.
        message: The content message to send.
        title: Optional title for push notifications.
    """
    try:
        return ActivationManager.execute(
            channel_key=channel,
            segment=segment_name,
            message=message,
            title=title,
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}

AVAILABLE_TOOLS: Dict[str, Any] = {
    "get_date": get_date,
    "get_current_weather": get_current_weather,
    "get_current_marketing_event": get_current_weather,
    "manage_leo_segment": manage_leo_segment,
    "activate_channel": activate_channel,
}