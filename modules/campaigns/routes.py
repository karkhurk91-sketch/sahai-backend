import uuid
import urllib.parse
import asyncio
import os
import json
import httpx
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from groq import Groq

from modules.common.database import get_db
from modules.common.models import Campaign, CampaignCreative, CampaignMeta, Organization, OrganizationChannel
from modules.auth.jwt import get_current_user
from modules.common.logger import get_logger
from modules.common.config import GROQ_API_KEY, API_BASE_URL
from modules.social.factory import SocialFactory
from modules.common.models import SocialAccount, SocialAdCampaign


logger = get_logger(__name__)
router = APIRouter(prefix="/api/campaign", tags=["Campaign"])

# ---------- Groq client ----------
_groq_client = Groq(api_key=GROQ_API_KEY)
DEFAULT_MODEL = "llama-3.3-70b-versatile"

# ---------- Prohibited phrases ----------
PROHIBITED_PHRASES = [
    "guaranteed", "miracle", "no risk", "100% safe", "instant results",
    "cure", "free money", "get rich quick", "you will", "everyone"
]

def clean_caption(caption: str) -> str:
    for phrase in PROHIBITED_PHRASES:
        caption = caption.replace(phrase, "")
    return caption.strip()

# ---------- Pydantic schemas ----------
class CampaignCreate(BaseModel):
    name: str
    product_name: str
    price: str
    location: str
    description: Optional[str] = None

class CampaignResponse(BaseModel):
    id: UUID
    name: str
    product_name: str
    status: str
    created_at: datetime
    class Config: from_attributes = True

class CreativeResponse(BaseModel):
    id: UUID
    type: str
    content: str
    is_selected: bool
    media_url: Optional[str] = None
    class Config: from_attributes = True

class SelectCreativeRequest(BaseModel):
    creative_id: UUID

class GenerateContentRequest(BaseModel):
    content_types: List[str]

class PostToFacebookRequest(BaseModel):
    message: str
    media_url: Optional[str] = None

class AdKitGenRequest(BaseModel):
    product_name: str
    price: str
    location: str
    description: Optional[str] = None

class SuggestTagsRequest(BaseModel):
    text: str
    product_name: str
    location: str
    industry: Optional[str] = None

class AdCampaignCreate(BaseModel):
    platform: str = "facebook"
    name: str
    daily_budget: int
    targeting: dict
    lead_form_questions: list
    story_spec: dict
    start_time: Optional[str] = None

# ---------- Text caption generator ----------
def _generate_captions_sync(product_name: str, price: str, location: str, description: str = "") -> list[str]:
    system_prompt = """
You are an expert social media copywriter for Meta ads. Generate 4 short, engaging captions.
Rules: no banned words, include emojis, include CTA (Tap to chat / Learn more).
Output one caption per line.
"""
    user_prompt = f"Product: {product_name}, Price: {price}, Location: {location}, Info: {description}"
    try:
        response = _groq_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=600
        )
        output = response.choices[0].message.content.strip()
        captions = [line.strip() for line in output.split('\n') if line.strip()]
        captions = [clean_caption(c) for c in captions]
        if len(captions) < 4:
            captions = [
                f"✨ Discover {product_name} – {price}. Located in {location}. Tap to chat!",
                f"🔥 Looking for {product_name}? Contact us today.",
                f"💖 Limited offer on {product_name} at {price}. Learn more.",
                f"🚀 Elevate your experience with {product_name}. In {location} now."
            ]
        return captions[:6]
    except Exception as e:
        logger.error(f"Text generation failed: {e}")
        return [
            f"✨ Discover {product_name} – {price}. Located in {location}. Tap to chat!",
            f"🔥 Interested in {product_name}? Contact us today.",
            f"💖 Special offer on {product_name} at {price}. Learn more.",
            f"🚀 Try {product_name} in {location}. Get in touch!"
        ]

# ---------- Image prompt generator ----------
def _generate_media_prompt_sync(product_name: str, price: str, location: str, description: str, media_type: str = "image") -> str:
    """Generate a prompt that creates an image optimized for lead conversion."""
    system_prompt = f"""
You are an expert conversion copywriter and image prompt engineer for social media ads.
Your task: create an image prompt for an ad that generates leads/sales for a product.

Rules:
- Focus on human emotions, social proof, or a clear benefit.
- Include one of these elements:
    * A happy person using the product (e.g., smiling, holding it)
    * A before/after transformation (if relevant)
    * A scarcity or urgency cue (e.g., limited stock, timer)
    * Social proof (e.g., "Loved by 1000s", group of people)
- DO NOT include text, logos, or watermarks (the image will be paired with a caption).
- Keep the scene realistic, bright, and high-quality.
- Mention the location {location} if it adds trust (e.g., a local cafe, street).

Output a single, detailed prompt under 200 words.
"""
    user_prompt = f"""
Product: {product_name}
Price: {price}
Location: {location}
Extra info: {description if description else "Not provided"}

Generate a lead‑focused image prompt for a social media ad.
"""
    try:
        response = _groq_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Lead prompt generation failed: {e}")
        return f"A happy customer holding {product_name} and smiling, in a bright {location} shop, inviting atmosphere, high resolution, warm lighting."

# ---------- Image generator (Pollinations.ai, saves locally) ----------
def _generate_image_sync(prompt: str, campaign_id: str) -> Optional[str]:
    try:
        encoded_prompt = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=768&model=flux"
        response = httpx.get(url, timeout=30)
        if response.status_code == 200 and response.headers.get('content-type', '').startswith('image/'):
            os.makedirs("uploads/campaigns", exist_ok=True)
            filename = f"campaign_{campaign_id}_{uuid.uuid4()}.png"
            filepath = f"uploads/campaigns/{filename}"
            with open(filepath, "wb") as f:
                f.write(response.content)
            return f"{API_BASE_URL}/static/campaigns/{filename}"
        else:
            logger.error(f"Pollinations returned status {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        return None

# ---------- AI ad‑kit suggestion generator ----------
async def generate_ad_kit_suggestions(product_name: str, price: str, location: str, description: str = ""):
    """Call Groq to generate dynamic ad kit suggestions."""
    prompt = f"""
You are a marketing expert for Meta (Facebook/Instagram) ads.
Generate a short JSON object with three fields: audience, budget, platforms.

Product: {product_name}
Price: {price}
Location: {location}
Description: {description if description else "None"}

Example output format:
{{"audience": "Women 25-35, interested in fitness, location Hyderabad", "budget": "₹300/day", "platforms": "Facebook & Instagram"}}

Do not include any extra text outside the JSON.
"""
    try:
        response = _groq_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content.strip()
        return json.loads(content)
    except Exception as e:
        logger.error(f"AI ad‑kit generation failed: {e}")
        return None

# ---------- Endpoints ----------
@router.post("/", response_model=CampaignResponse)
async def create_campaign(data: CampaignCreate, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    campaign = Campaign(
        id=uuid.uuid4(),
        organization_id=current_user["org_id"],
        name=data.name,
        product_name=data.product_name,
        price=data.price,
        location=data.location,
        description=data.description,
        status="draft"
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign

@router.get("/", response_model=List[CampaignResponse])
async def list_campaigns(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    stmt = select(Campaign).where(Campaign.organization_id == current_user["org_id"])
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    stmt = select(Campaign).where(Campaign.id == campaign_id, Campaign.organization_id == current_user["org_id"])
    campaign = (await db.execute(stmt)).scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    return campaign

@router.post("/{campaign_id}/generate-content")
async def generate_ai_content(
    campaign_id: UUID,
    req: GenerateContentRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    stmt = select(Campaign).where(Campaign.id == campaign_id, Campaign.organization_id == current_user["org_id"])
    campaign = (await db.execute(stmt)).scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    await db.execute(delete(CampaignCreative).where(CampaignCreative.campaign_id == campaign_id))
    loop = asyncio.get_running_loop()

    if "text" in req.content_types:
        captions = await loop.run_in_executor(
            None, _generate_captions_sync,
            campaign.product_name, campaign.price, campaign.location, campaign.description or ""
        )
        for text in captions:
            db.add(CampaignCreative(
                id=uuid.uuid4(), campaign_id=campaign_id, type="text", content=text, is_selected=False
            ))

    if "image" in req.content_types:
        image_prompt = await loop.run_in_executor(
            None, _generate_media_prompt_sync,
            campaign.product_name, campaign.price, campaign.location, campaign.description or "", "image"
        )
        image_url = await loop.run_in_executor(None, _generate_image_sync, image_prompt, str(campaign_id))
        if image_url:
            db.add(CampaignCreative(
                id=uuid.uuid4(), campaign_id=campaign_id, type="image", content=image_prompt, media_url=image_url, is_selected=False
            ))
        else:
            logger.warning(f"Image generation failed for campaign {campaign_id}")

    await db.commit()
    return {"message": "Content generated", "types": req.content_types}

@router.get("/{campaign_id}/creatives", response_model=List[CreativeResponse])
async def get_creatives(campaign_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    stmt = select(CampaignCreative).where(CampaignCreative.campaign_id == campaign_id)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/{campaign_id}/select-creative")
async def select_creative(campaign_id: UUID, req: SelectCreativeRequest, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    await db.execute(update(CampaignCreative).where(CampaignCreative.campaign_id == campaign_id).values(is_selected=False))
    creative = (await db.execute(select(CampaignCreative).where(CampaignCreative.id == req.creative_id, CampaignCreative.campaign_id == campaign_id))).scalar_one_or_none()
    if not creative:
        raise HTTPException(404, "Creative not found")
    creative.is_selected = True
    await db.commit()
    return {"message": "Creative selected"}

@router.get("/{campaign_id}/whatsapp-link")
async def generate_whatsapp_link(campaign_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    campaign = (await db.execute(select(Campaign).where(Campaign.id == campaign_id, Campaign.organization_id == current_user["org_id"]))).scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    org = (await db.execute(select(Organization).where(Organization.id == current_user["org_id"]))).scalar_one_or_none()
    if not org or not org.whatsapp_phone_number:
        raise HTTPException(400, "Organization WhatsApp number not configured")
    wa_number = org.whatsapp_phone_number.replace("+", "").replace(" ", "")
    msg = f"Hi, I am interested in {campaign.product_name} | CID:{campaign_id}"
    encoded = urllib.parse.quote(msg)
    link = f"https://wa.me/{wa_number}?text={encoded}"
    campaign.whatsapp_link = link
    campaign.status = "active"
    await db.commit()
    return {"whatsapp_link": link}

@router.get("/{campaign_id}/ad-kit")
async def get_ad_kit(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Get campaign
    stmt = select(Campaign).where(
        Campaign.id == campaign_id,
        Campaign.organization_id == current_user["org_id"]
    )
    campaign = (await db.execute(stmt)).scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # Get selected creative
    creative_stmt = select(CampaignCreative).where(
        CampaignCreative.campaign_id == campaign_id,
        CampaignCreative.is_selected == True
    )
    selected_creative = (await db.execute(creative_stmt)).scalar_one_or_none()

    # Get or create meta suggestions
    meta_stmt = select(CampaignMeta).where(CampaignMeta.campaign_id == campaign_id)
    meta = (await db.execute(meta_stmt)).scalar_one_or_none()

    if not meta:
        # Try to generate AI suggestions
        ai_suggestions = await generate_ad_kit_suggestions(
            campaign.product_name,
            campaign.price,
            campaign.location,
            campaign.description or ""
        )
        if ai_suggestions:
            audience = ai_suggestions.get("audience", "Women 20-35, Location based")
            budget = ai_suggestions.get("budget", "₹200/day")
            platforms = ai_suggestions.get("platforms", "Facebook & Instagram")
        else:
            # Fallback static suggestions
            audience = "Women 20-35, Location based"
            budget = "₹200/day"
            platforms = "Facebook & Instagram"

        meta = CampaignMeta(
            id=uuid.uuid4(),
            campaign_id=campaign_id,
            audience_suggestion=audience,
            budget_suggestion=budget,
            platform_suggestion=platforms
        )
        db.add(meta)
        await db.commit()
        await db.refresh(meta)

    return {
        "product_name": campaign.product_name,
        "price": campaign.price,
        "location": campaign.location,
        "caption": selected_creative.content if selected_creative else "",
        "whatsapp_link": campaign.whatsapp_link,
        "suggested_budget": meta.budget_suggestion,
        "audience": meta.audience_suggestion,
        "platform": meta.platform_suggestion,
    }

@router.post("/{campaign_id}/post-to-facebook")
async def post_to_facebook(
    campaign_id: UUID,
    req: PostToFacebookRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Verify campaign exists and belongs to the organization
    stmt = select(Campaign).where(
        Campaign.id == campaign_id,
        Campaign.organization_id == current_user["org_id"]
    )
    campaign = (await db.execute(stmt)).scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # Get the selected creative (optional)
    creative_stmt = select(CampaignCreative).where(
        CampaignCreative.campaign_id == campaign_id,
        CampaignCreative.is_selected == True
    )
    selected = (await db.execute(creative_stmt)).scalar_one_or_none()
    if not selected and not req.message:
        raise HTTPException(400, "No creative selected and no message provided")

    # Retrieve Facebook channel configuration
    channel_stmt = select(OrganizationChannel).where(
        OrganizationChannel.organization_id == current_user["org_id"],
        OrganizationChannel.channel_type == "facebook",
        OrganizationChannel.enabled == True
    )
    channel = (await db.execute(channel_stmt)).scalar_one_or_none()
    if not channel:
        raise HTTPException(400, "Facebook channel not configured. Please add your Facebook page in Settings → Channels.")
    
    config = channel.config
    page_access_token = config.get("page_access_token")
    page_id = config.get("page_id")
    if not page_access_token or not page_id:
        raise HTTPException(400, "Facebook page access token or page ID missing. Please reconnect your Facebook page.")

    message = req.message
    media_url = req.media_url

    async with httpx.AsyncClient(timeout=30.0) as client:
        if media_url:
            # Download or read the image
            image_content = None
            if media_url.startswith("/static/"):
                local_path = media_url.replace("/static/", "uploads/")
                if os.path.exists(local_path):
                    with open(local_path, "rb") as f:
                        image_content = f.read()
                else:
                    raise HTTPException(400, f"Image file not found: {local_path}")
            else:
                img_resp = await client.get(media_url)
                if img_resp.status_code == 200:
                    image_content = img_resp.content
                else:
                    raise HTTPException(400, f"Failed to download image from {media_url}")

            upload_url = f"https://graph.facebook.com/v18.0/{page_id}/photos"
            files = {"source": ("image.jpg", image_content, "image/jpeg")}
            data = {"access_token": page_access_token, "published": True}
            if message:
                data["caption"] = message
            resp = await client.post(upload_url, files=files, data=data)
            if resp.status_code != 200:
                logger.error(f"Facebook photo upload failed: {resp.text}")
                raise HTTPException(400, f"Failed to post image: {resp.text}")
            result = resp.json()
            return {"post_id": result.get("id"), "message": "Image post published successfully"}
        else:
            feed_url = f"https://graph.facebook.com/v18.0/{page_id}/feed"
            payload = {"message": message, "access_token": page_access_token}
            resp = await client.post(feed_url, data=payload)
            if resp.status_code != 200:
                logger.error(f"Facebook text post failed: {resp.text}")
                raise HTTPException(400, f"Failed to post text: {resp.text}")
            result = resp.json()
            return {"post_id": result.get("id"), "message": "Text post published successfully"}

@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    result = await db.execute(delete(Campaign).where(Campaign.id == campaign_id, Campaign.organization_id == current_user["org_id"]))
    if result.rowcount == 0:
        raise HTTPException(404, "Campaign not found")
    await db.commit()
    return {"message": "Campaign deleted"}

# ---------- Additional helper endpoints ----------
@router.post("/suggest-tags")
async def suggest_tags(data: SuggestTagsRequest):
    prompt = f"""
    Generate 5-10 relevant hashtags (starting with #) for a social media post about:
    Text: {data.text}
    Product: {data.product_name}
    Location: {data.location}
    Industry: {data.industry or "general"}
    Return comma-separated hashtags without numbers. Example: "#summer, #sale, #hydrabad"
    """
    response = _groq_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=150
    )
    tags = response.choices[0].message.content.strip()
    return {"tags": tags}

@router.post("/generate-ad-kit")
async def generate_ad_kit_endpoint(data: AdKitGenRequest):
    prompt = f"""
    You are a marketing expert. Suggest Meta ad targeting, budget, and platforms for a product:
    Product: {data.product_name}
    Price: {data.price}
    Location: {data.location}
    Description: {data.description or "N/A"}
    Return JSON only: {{"audience": "...", "budget": "...", "platforms": "..."}}
    """
    response = _groq_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=150,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

@router.post("/{campaign_id}/create-ad-campaign")
async def create_ad_campaign(
    campaign_id: UUID,
    data: AdCampaignCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Verify campaign exists
    stmt = select(Campaign).where(Campaign.id == campaign_id, Campaign.organization_id == current_user["org_id"])
    campaign = (await db.execute(stmt)).scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    
    # Get social account
    social_stmt = select(SocialAccount).where(
        SocialAccount.organization_id == current_user["org_id"],
        SocialAccount.platform == data.platform,
        SocialAccount.is_active == True
    )
    social_account = (await db.execute(social_stmt)).scalar_one_or_none()
    if not social_account:
        raise HTTPException(400, f"{data.platform} account not configured")
    
    ad_account_id = social_account.settings.get("ad_account_id")
    if not ad_account_id:
        raise HTTPException(400, "Ad account ID not configured")
    
    platform_data = data.dict()
    platform_data["ad_account_id"] = ad_account_id
    
    client = SocialFactory.get_platform(
        platform=data.platform,
        organization_id=str(current_user["org_id"]),
        account_id=social_account.account_id,
        access_token=social_account.access_token
    )
    
    result = await client.create_ad_campaign(platform_data)
    
    # Store in DB
    ad_campaign = SocialAdCampaign(
        organization_id=current_user["org_id"],
        platform=data.platform,
        campaign_id=result["campaign_id"],
        adset_id=result["adset_id"],
        ad_id=result["ad_id"],
        lead_form_id=result["lead_form_id"],
        name=data.name,
        objective="OUTCOME_LEADS",
        status="ACTIVE",
        daily_budget=data.daily_budget,
        targeting=data.targeting
    )
    db.add(ad_campaign)
    await db.commit()
    
    return result
