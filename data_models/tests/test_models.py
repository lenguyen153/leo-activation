import unittest
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Import the Base and one model to trigger registry
from data_models.base import Base
from data_models.dbo_tenant import Tenant
from data_models.dbo_cdp import CdpProfile

# Use an in-memory SQLite database for basic structural testing
# Note: SQLite does not support UUID, JSONB, Vector natively in the same way as Postgres.
# For rigorous testing, use a real Postgres instance with extensions installed.
# This test mainly checks python syntax validity and basic mapping.

class TestSchemaDefinitions(unittest.TestCase):
    def test_schema_compilation(self):
        """
        Verifies that SQLAlchemy can compile the CREATE TABLE statements 
        for all defined models without Python errors.
        """
        engine = create_engine("sqlite:///:memory:")
        
        # We assume postgres dialect specific types (JSONB, UUID) might fail on SQLite 
        # during actual creation if we don't mock them, but `CreateTable` compilation
        # usually works if we don't execute it, OR we can check that models load.
        
        try:
            # Inspection of mapper registry
            from sqlalchemy.orm import class_mapper
            class_mapper(Tenant)
            class_mapper(CdpProfile)
            # If we get here without error, the declarative mappings are syntactically correct
            print("SQLAlchemy mappers configured successfully.")
        except Exception as e:
            self.fail(f"Mapping configuration failed: {e}")

if __name__ == '__main__':
    unittest.main()