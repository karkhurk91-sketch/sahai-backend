import os
import sys
import pytest
import asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from modules.common.database import Base
from modules.common import models
from modules.common.models import Lead, Organization, User
from modules.common.database import get_db

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from main import app
import uuid

@pytest.fixture(scope='module')
async def async_engine():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest.fixture
async def session(async_engine):
    AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)
    async with AsyncSessionLocal() as session:
        yield session

@pytest.fixture(autouse=True)
def override_get_db(session):
    async def _get_db():
        try:
            yield session
        finally:
            pass
    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)

@pytest.mark.asyncio
async def test_schedule_and_cancel_followup(session):
    # create org and lead
    org = Organization(id=uuid.uuid4(), name='Test Org')
    session.add(org)
    await session.commit()

    lead = Lead(id=uuid.uuid4(), organization_id=org.id, customer_phone='+1234567890')
    session.add(lead)
    await session.commit()

    async with AsyncClient(app=app, base_url='http://test') as ac:
        # schedule
        res = await ac.post(f'/api/leads/{lead.id}/followup/schedule', json={'scheduled_at': '2030-01-01T12:00:00Z'})
        assert res.status_code == 200
        data = res.json()
        assert data['status'] == 'scheduled'

        # list followups
        res = await ac.get('/api/leads/followups')
        assert res.status_code == 200
        arr = res.json()
        assert any(item['id'] == str(lead.id) for item in arr)

        # cancel
        res = await ac.post(f'/api/leads/{lead.id}/followup/cancel')
        assert res.status_code == 200
        data = res.json()
        assert data['status'] == 'cancelled'