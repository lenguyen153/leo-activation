import logging
from typing import Any, Dict, List
from pathlib import Path

# Initialize logger for this module
logger = logging.getLogger(__name__)

# ============================================================
# HTML Templates
# ============================================================
BASE_DIR = Path(__file__).parent.parent.parent
TEMPLATE_PATH = BASE_DIR / "agentic_resources" / "message_templates" / "thank-you.html"

def load_html_template(file_path: Path) -> str:
    """Safely loads HTML template or returns a fallback string."""
    try:
        if not file_path.exists():
            logger.error(f"Template not found at: {file_path}")
            return "<html><body><p>Default Message (Template Missing)</p></body></html>"
            
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to load template: {e}")
        return "<html><body><p>Error loading template</p></body></html>"
      
PRODUCT_RECOMMENDATION_TEMPLATE = load_html_template(TEMPLATE_PATH)

# ============================================================
# Helper Functions
# ============================================================

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from jinja2 import Environment, BaseLoader, select_autoescape

logger = logging.getLogger(__name__)

# =============================================================================
# 1. The Main Object: UserProfile
# =============================================================================

class UserProfile:
    """
    Wraps raw dictionary data into a structured object.
    Allows for computed properties (like full_name) and safe defaults.
    """
    def __init__(self, data: Dict[str, Any]):
        self._data = data  # Keep raw data if needed for custom access
        self.id = data.get("id") or data.get("uid")
        self.first_name = data.get("firstName", "Customer")
        self.last_name = data.get("lastName", "")
        self.email = data.get("email", "")
        self.phone = data.get("phone", "")
        self.points = data.get("loyalty_points", 0)

    @property
    def full_name(self) -> str:
        """computed property for templates"""
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name

    @property
    def is_vip(self) -> bool:
        """Business logic lives here, not in the HTML"""
        return self.points > 1000

    def to_dict(self) -> Dict[str, Any]:
        """Returns the context for Jinja2"""
        return {
            "id": self.id,
            "firstName": self.first_name,
            "lastName": self.last_name,
            "full_name": self.full_name,
            "email": self.email,
            "is_vip": self.is_vip,
            "raw": self._data,  # Access raw attributes via {{ user.raw.custom_attr }}
        }


# =============================================================================
# 2. The Engine: MessageRenderer
# =============================================================================

class MessageRenderer:
    """
    Centralized rendering engine using Jinja2.
    Handles channel-specific logic while sharing the core engine.
    """
    def __init__(self):
        # BaseLoader allows us to render strings directly (from DB/API)
        # autoescape=True protects against XSS injection in emails
        self.env = Environment(
            loader=BaseLoader(),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Register custom filters (e.g., formatting currency or dates)
        self.env.filters['currency'] = self._format_currency
        self.env.filters['date_fmt'] = self._format_date

    # --- Helper Filters ---
    @staticmethod
    def _format_currency(value):
        return "${:,.2f}".format(float(value or 0))

    @staticmethod
    def _format_date(value, fmt="%Y-%m-%d"):
        if isinstance(value, str):
            return value # Simplified for demo
        return value.strftime(fmt)

    # --- Core Render Logic ---
    def _render(self, template_str: str, context: Dict[str, Any]) -> str:
        """Internal method to compile and render."""
        try:
            template = self.env.from_string(template_str)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            # Fallback to prevent sending broken code to users
            return template_str 

    # --- Public Channel Methods ---

    def render_email_template(self, html_template: str, profile: UserProfile, **kwargs) -> str:
        """
        Renders HTML for email. Injects email-specific globals (like unsubscribe links).
        """
        context = {
            "user": profile,
            "channel": "email",
            "year": datetime.now().year,
            "company_name": "LEO CDP",
            **kwargs
        }
        return self._render(html_template, context)

    def render_zalo_oa_template(self, text_template: str, profile: UserProfile, **kwargs) -> str:
        """
        Renders text for Zalo OA. 
        Note: Zalo often uses plain text or specific JSON structures, not HTML.
        """
        # Zalo specific: Maybe we want to force uppercase for emphasis?
        context = {
            "user": profile,
            "channel": "zalo_oa",
            **kwargs
        }
        return self._render(text_template, context)

    def render_alert_template(self, msg_template: str, profile: UserProfile, level: str = "info") -> str:
        """
        Renders internal system alerts.
        """
        context = {
            "user": profile,
            "alert_level": level.upper(),
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        return self._render(msg_template, context)

# =============================================================================
# 3. Usage Example
# =============================================================================

if __name__ == "__main__":
    # 1. Setup Data
    raw_data = {"uid": "u123", "firstName": "Thomas", "lastName": "Anderson", "loyalty_points": 1500}
    user = UserProfile(raw_data)
    
    # 2. Initialize Renderer
    renderer = MessageRenderer()

    # --- Scenario A: Email ---
    email_html = """
    <h1>Hello {{ user.full_name }},</h1>
    {% if user.is_vip %}
        <p><strong>Status: VIP Member</strong></p>
        <p>Because you have {{ user.raw.loyalty_points }} points, you get 20% off!</p>
    {% else %}
        <p>Keep shopping to reach VIP status!</p>
    {% endif %}
    <small>&copy; {{ year }} {{ company_name }}</small>
    """
    
    print("--- Email Output ---")
    print(renderer.render_email_template(email_html, user))

    # --- Scenario B: Zalo OA ---
    zalo_text = "Chao {{ user.firstName }}, ma don hang cua ban la #12345."
    
    print("\n--- Zalo Output ---")
    print(renderer.render_zalo_oa_template(zalo_text, user))