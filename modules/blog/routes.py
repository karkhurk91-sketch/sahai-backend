from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from modules.common.database import get_db
from modules.common.models import Blog
from modules.auth.jwt import get_current_super_admin
from pydantic import BaseModel
from uuid import UUID
from typing import Optional, List
from slugify import slugify

router = APIRouter(prefix="/api/blogs", tags=["Blogs"])

class BlogCreate(BaseModel):
    title: str
    description: Optional[str] = None
    content: str
    image_url: Optional[str] = None
    published: bool = False

class BlogUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    image_url: Optional[str] = None
    published: Optional[bool] = None

class BlogOut(BaseModel):
    id: UUID
    title: str
    slug: str
    description: Optional[str]
    content: str
    image_url: Optional[str]
    published: bool
    created_at: str
    updated_at: Optional[str] = None

# Public endpoints (no auth)
@router.get("", response_model=List[BlogOut])
async def list_blogs(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 20
):
    result = await db.execute(
        select(Blog).where(Blog.published == True)
        .order_by(Blog.created_at.desc())
        .offset(skip).limit(limit)
    )
    blogs = result.scalars().all()
    return [
        BlogOut(
            id=b.id,
            title=b.title,
            slug=b.slug,
            description=b.description,
            content=b.content,
            image_url=b.image_url,
            published=b.published,
            created_at=b.created_at.isoformat(),
            updated_at=b.updated_at.isoformat() if b.updated_at else None
        )
        for b in blogs
    ]

@router.get("/{slug}", response_model=BlogOut)
async def get_blog_by_slug(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Blog).where(Blog.slug == slug))
    blog = result.scalar_one_or_none()
    if not blog or not blog.published:
        raise HTTPException(404, "Blog not found")
    return BlogOut(
        id=blog.id,
        title=blog.title,
        slug=blog.slug,
        description=blog.description,
        content=blog.content,
        image_url=blog.image_url,
        published=blog.published,
        created_at=blog.created_at.isoformat(),
        updated_at=blog.updated_at.isoformat() if blog.updated_at else None
    )

# Super admin only endpoints (can see all blogs)
@router.get("/admin/all", response_model=List[BlogOut])
async def list_all_blogs(
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    result = await db.execute(select(Blog).order_by(Blog.created_at.desc()))
    blogs = result.scalars().all()
    return [
        BlogOut(
            id=b.id,
            title=b.title,
            slug=b.slug,
            description=b.description,
            content=b.content,
            image_url=b.image_url,
            published=b.published,
            created_at=b.created_at.isoformat(),
            updated_at=b.updated_at.isoformat() if b.updated_at else None
        )
        for b in blogs
    ]

@router.post("", response_model=BlogOut)
async def create_blog(
    data: BlogCreate,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    slug = slugify(data.title)
    # ensure unique slug
    exist = await db.execute(select(Blog).where(Blog.slug == slug))
    if exist.scalar_one_or_none():
        slug = f"{slug}-{UUID(int=0).hex[:8]}"
    new_blog = Blog(
        title=data.title,
        slug=slug,
        description=data.description,
        content=data.content,
        image_url=data.image_url,
        published=data.published
    )
    db.add(new_blog)
    await db.commit()
    await db.refresh(new_blog)
    return BlogOut(
        id=new_blog.id,
        title=new_blog.title,
        slug=new_blog.slug,
        description=new_blog.description,
        content=new_blog.content,
        image_url=new_blog.image_url,
        published=new_blog.published,
        created_at=new_blog.created_at.isoformat(),
        updated_at=new_blog.updated_at.isoformat() if new_blog.updated_at else None
    )

@router.put("/{blog_id}", response_model=BlogOut)
async def update_blog(
    blog_id: UUID,
    data: BlogUpdate,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    result = await db.execute(select(Blog).where(Blog.id == blog_id))
    blog = result.scalar_one_or_none()
    if not blog:
        raise HTTPException(404, "Blog not found")
    update_data = data.dict(exclude_unset=True)
    if "title" in update_data:
        update_data["slug"] = slugify(update_data["title"])
    for key, value in update_data.items():
        setattr(blog, key, value)
    await db.commit()
    await db.refresh(blog)
    return BlogOut(
        id=blog.id,
        title=blog.title,
        slug=blog.slug,
        description=blog.description,
        content=blog.content,
        image_url=blog.image_url,
        published=blog.published,
        created_at=blog.created_at.isoformat(),
        updated_at=blog.updated_at.isoformat() if blog.updated_at else None
    )

@router.delete("/{blog_id}")
async def delete_blog(
    blog_id: UUID,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    result = await db.execute(select(Blog).where(Blog.id == blog_id))
    blog = result.scalar_one_or_none()
    if not blog:
        raise HTTPException(404, "Blog not found")
    await db.execute(delete(Blog).where(Blog.id == blog_id))
    await db.commit()
    return {"status": "deleted"}