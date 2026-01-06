
from abc import ABC, abstractmethod
from typing import Any, Dict


class NotificationChannel(ABC):
    """Base strategy for all activation channels."""

    @abstractmethod
    def send(self, recipient_segment: str, message: str, **kwargs: Any) -> Dict[str, Any]:
        """Send a message to a recipient segment.

        Returns a dict with at least a `status` key.
        """
        pass
    
    


