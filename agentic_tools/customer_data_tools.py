

from typing import Dict


def manage_leo_segment(recipient_segment: str, action: str = "create") -> Dict[str, str]:
    """
    Create, update, or delete a LEO CDP segment.

    Args:
        recipient_segment: The name or the ID of the target segment.
        action: The management action (create, update, or delete).
    """
    return {"status": "success", "segment": recipient_segment, "action": action}
