from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.common.database import get_db
from modules.common.models import KnowledgeDocument
from modules.auth.jwt import get_current_user
from modules.ai.rag import index_document
from modules.common.logger import get_logger
import os
import shutil
import uuid

logger = get_logger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])

UPLOAD_DIR = "uploads/knowledge"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.get("")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.organization_id == current_user["org_id"]
        ).order_by(KnowledgeDocument.created_at.desc())
    )
    return result.scalars().all()

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(None),
    description: str = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    logger.info("=== UPLOAD STARTED ===")
    original_filename = file.filename
    file_ext = os.path.splitext(original_filename)[1].lower().replace('.', '')
    allowed = ['txt', 'pdf', 'csv', 'docx']
    if file_ext not in allowed:
        raise HTTPException(400, f"Unsupported file type. Allowed: {', '.join(allowed)}")
    
    unique_filename = f"{uuid.uuid4()}_{original_filename}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"File saved to {file_path}")
    except Exception as e:
        logger.error(f"File save error: {e}")
        raise HTTPException(500, "Failed to save file")
    
    doc = KnowledgeDocument(
        id=uuid.uuid4(),
        organization_id=current_user["org_id"],
        title=title or original_filename,
        description=description,
        file_name=original_filename,
        file_url=file_path,
        file_type=file_ext,
        status="processing"
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    logger.info(f"DB record created: {doc.id}, org_id={current_user['org_id']}")
    
    # Log the parameters before calling index_document
    logger.info(f"Calling index_document with doc_id={doc.id}, org_id={str(current_user['org_id'])}, file_path={file_path}, file_type={file_ext}")
    try:
        index_document(doc.id, str(current_user["org_id"]), file_path, file_ext)
        doc.status = "ready"
        await db.commit()
        logger.info(f"Document {doc.id} indexed successfully.")
    except Exception as e:
        logger.error(f"Indexing failed for {doc.id}: {e}", exc_info=True)
        doc.status = "failed"
        await db.commit()
        raise HTTPException(500, "Document indexing failed")
    
    return {"id": doc.id, "file_name": doc.file_name, "status": "ready"}
    
@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Find document
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.organization_id == current_user["org_id"]
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")
    
    # Delete file from disk
    if os.path.exists(doc.file_url):
        os.remove(doc.file_url)
    
    # Delete from database
    await db.delete(doc)
    await db.commit()
    return {"status": "deleted"}