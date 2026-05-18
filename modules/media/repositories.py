"""
Media repository using the core BaseRepository.
"""

from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy import delete

from core.repository import BaseRepository
from modules.common.models import Media  # adjust to your actual Media model location


class MediaRepository(BaseRepository[Media]):
    """
    Repository for media file metadata.
    Inherits all CRUD operations from BaseRepository.
    """

    def __init__(self, session):
        # Pass the session and the Media model class to the base repository
        super().__init__(session, Media)

    async def find_one_by_hash(self, organization_id: UUID, file_hash: str) -> Optional[Media]:
        """
        Find a media record by organization and file hash (deduplication).
        Uses the base class's `find_one` method with multiple filters.
        """
        return await self.find_one(
            organization_id=organization_id,
            file_hash=file_hash
        )

    async def delete_old(self, days: int = 30) -> int:
        """
        Delete media records older than a given number of days.
        Returns the number of deleted rows.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = delete(Media).where(Media.uploaded_at < cutoff)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount

    async def update_status(self, media_id: UUID, status: str) -> Optional[Media]:
        """
        Update the upload status of a media record.
        """
        return await self.update(media_id, upload_status=status)