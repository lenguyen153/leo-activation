
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_utils.db_factory import get_db_context
from data_utils.settings import DatabaseSettings

from data_models.dbo_cdp import CdpProfile
from sqlalchemy import select

# Load your settings
settings = DatabaseSettings() 

# Use the Context Manager (Recommended)
# It automatically commits on success, rolls back on error, and closes the connection.
with get_db_context(settings) as session:
    
    # Run a query to find a specific user
    stmt = select(CdpProfile).where(CdpProfile.primary_email == 'alice.tech@test.com')
    user = session.execute(stmt).scalar_one_or_none()
    
    if user:
        print(f"Found 1 user: {user.primary_email} \n")
        
    # Run a query to find all users with non-null emails
    stmt = select(CdpProfile).where(CdpProfile.primary_email != None)
    users = session.execute(stmt).scalars().all()
    
    if users:
        print(f"Found {len(users)} users with non-null emails:")
        for user in users:
            print(f"Found user: {user.primary_email}")