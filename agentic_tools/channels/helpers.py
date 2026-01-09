import logging
from typing import Any, Dict, List

# Initialize logger for this module
logger = logging.getLogger(__name__)

# ============================================================
# HTML Templates
# ============================================================
PRODUCT_RECOMMENDATION_TEMPLATE = """<!doctype html>
<html>
  <head>
    <meta name="viewport" content="width=device-width" />
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <title>Product Recommendation Email</title>
    <style>
      body { background-color: #f6f6f6; font-family: sans-serif; font-size: 14px; line-height: 1.4; margin: 0; padding: 0; -ms-text-size-adjust: 100%; -webkit-text-size-adjust: 100%; }
      .container { display: block; margin: 0 auto !important; max-width: 580px; padding: 10px; width: 580px; }
      .content { box-sizing: border-box; display: block; margin: 0 auto; max-width: 580px; padding: 10px; }
      .main { background: #ffffff; border-radius: 3px; width: 100%; }
      .wrapper { box-sizing: border-box; padding: 20px; }
      .footer { clear: both; margin-top: 10px; text-align: center; width: 100%; }
      .footer td, .footer p, .footer span, .footer a { color: #999999; font-size: 12px; text-align: center; }
      a { color: #3498db; text-decoration: underline; }
    </style>
  </head>
  <body>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" class="body">
      <tr>
        <td>&nbsp;</td>
        <td class="container">
          <div class="content">
            <table role="presentation" class="main">
              <tr>
                <td class="wrapper">
                  <table role="presentation" border="0" cellpadding="0" cellspacing="0">
                    <tr>
                      <td>
                        <p>Hi {{profile.firstName}},</p>
                        <p>Many thanks for submitting the customer research form! We will use your personal information carefully to improve our customer service and product recommendation.</p>
                        <p>Thank you.</p>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
            <div class="footer">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0">
                <tr>
                  <td class="content-block">
                    <span class="apple-link">Your company address</span>
                    <br> Don't like these emails? <a href="#">Unsubscribe</a>.
                  </td>
                </tr>
                <tr>
                  <td class="content-block powered-by">
                    Powered by <a href="https://leocdp.net">CDP</a>.
                  </td>
                </tr>
              </table>
            </div>
          </div>
        </td>
        <td>&nbsp;</td>
      </tr>
    </table>
  </body>
</html>
"""

# ============================================================
# Helper Functions
# ============================================================

def get_recipients_from_arango(db_connection: Any, segment_name: str) -> List[Dict[str, str]]:
    """
    Fetches a list of profiles belonging to a specific segment.
    Returns: [{'email': '...', 'firstName': '...'}, ...]
    """
    if not db_connection:
        logger.error("[EmailHelper] Database connection is not available.")
        return []

    try:
        # 1. Resolve Segment Name to ID
        segment_query = "FOR s IN cdp_segment FILTER s.name == @segment_name RETURN s._key"
        cursor_seg = db_connection.aql.execute(segment_query, bind_vars={'segment_name': segment_name})
        found_ids = [s for s in cursor_seg]

        if not found_ids:
            logger.warning(f"[ArangoDB] Segment '{segment_name}' not found.")
            return []
        
        target_segment_id = found_ids[0]
        logger.info(f"[ArangoDB] Resolving recipients for Segment ID: {target_segment_id}")

        # 2. Fetch Profile Data (Email + First Name)
        profile_query = """
        FOR p IN cdp_profile
            FILTER @segment_id IN p.inSegments[*].id
            FILTER p.primaryEmail != null AND p.primaryEmail != ""
            RETURN {
                "email": p.primaryEmail,
                "firstName": p.firstName
            }
        """
        
        cursor_prof = db_connection.aql.execute(profile_query, bind_vars={'segment_id': target_segment_id})
        recipients = [r for r in cursor_prof]
        
        logger.info(f"[ArangoDB] Found {len(recipients)} profiles for personalization.")
        return recipients

    except Exception as e:
        logger.error(f"[ArangoDB] Query failed: {e}")
        return []


def render_email_template(html_template: str, profile_data: Dict[str, Any]) -> str:
    """
    Replaces placeholders in the template with profile data.
    """
    first_name = profile_data.get('firstName') or "Customer"
    
    # You can add more replacement logic here in the future
    return html_template.replace("{{profile.firstName}}", first_name)