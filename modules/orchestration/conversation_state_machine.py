"""
Conversation State Machine - Enforces valid state transitions and prevents repeated questions.

This module provides deterministic conversation flow control, ensuring:
- Valid stage transitions
- Required field validation
- No repeated questions
- Automatic stage advancement based on collected data
"""

from enum import Enum
from typing import Dict, Optional, Tuple, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ConversationStage(str, Enum):
    """Valid conversation stages"""
    GREETING = "greeting"
    QUALIFICATION = "qualification"
    RECOMMENDATION = "recommendation"
    BOOKING = "booking"
    FOLLOWUP = "followup"
    SUPPORT = "support"
    CLOSED = "closed"


class ConversationStateMachine:
    """
    Enforces valid conversation state transitions.
    
    Prevents:
    - Invalid stage sequences
    - Skipping stages
    - Missing required fields
    - Backwards transitions (except support)
    """
    
    # Valid transitions from each stage
    VALID_TRANSITIONS: Dict[ConversationStage, List[ConversationStage]] = {
        ConversationStage.GREETING: [ConversationStage.QUALIFICATION],
        ConversationStage.QUALIFICATION: [
            ConversationStage.RECOMMENDATION,
            ConversationStage.BOOKING,
            ConversationStage.SUPPORT,
        ],
        ConversationStage.RECOMMENDATION: [
            ConversationStage.BOOKING,
            ConversationStage.QUALIFICATION,  # User rejected, retry qualification
            ConversationStage.SUPPORT,
        ],
        ConversationStage.BOOKING: [
            ConversationStage.FOLLOWUP,
            ConversationStage.SUPPORT,
            ConversationStage.CLOSED,
        ],
        ConversationStage.FOLLOWUP: [
            ConversationStage.SUPPORT,
            ConversationStage.CLOSED,
        ],
        ConversationStage.SUPPORT: [
            ConversationStage.BOOKING,
            ConversationStage.QUALIFICATION,
            ConversationStage.CLOSED,
        ],
        ConversationStage.CLOSED: [],  # Terminal state
    }
    
    # Required fields per stage
    STAGE_REQUIREMENTS: Dict[ConversationStage, Dict] = {
        ConversationStage.GREETING: {
            "required_fields": ["name", "phone"],
            "timeout_seconds": 300,
        },
        ConversationStage.QUALIFICATION: {
            "required_fields": [],  # Industry-specific
            "timeout_seconds": 1800,
        },
        ConversationStage.RECOMMENDATION: {
            "required_fields": [],
            "timeout_seconds": 600,
        },
        ConversationStage.BOOKING: {
            "required_fields": ["booking_date", "booking_time"],
            "timeout_seconds": 1200,
        },
        ConversationStage.FOLLOWUP: {
            "required_fields": [],
            "timeout_seconds": 86400,
        },
        ConversationStage.SUPPORT: {
            "required_fields": [],
            "timeout_seconds": 3600,
        },
        ConversationStage.CLOSED: {
            "required_fields": [],
            "timeout_seconds": 0,
        },
    }
    
    def __init__(self, industry: str = "default"):
        self.industry = industry
    
    def validate_stage(
        self,
        current_stage: ConversationStage,
        completed_fields: Dict[str, dict]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate if current stage requirements are met.
        
        Args:
            current_stage: Current conversation stage
            completed_fields: Fields that have been collected
        
        Returns:
            (is_valid, error_message)
        """
        requirements = self.STAGE_REQUIREMENTS.get(current_stage, {})
        required_fields = requirements.get("required_fields", [])
        
        for field in required_fields:
            if field not in completed_fields:
                return False, f"Missing required field: {field}"
        
        return True, None
    
    def is_valid_transition(
        self,
        from_stage: ConversationStage,
        to_stage: ConversationStage
    ) -> bool:
        """Check if transition from -> to is allowed"""
        allowed = self.VALID_TRANSITIONS.get(from_stage, [])
        return to_stage in allowed
    
    def get_allowed_transitions(
        self,
        current_stage: ConversationStage
    ) -> List[ConversationStage]:
        """Get list of allowed transitions from current stage"""
        return self.VALID_TRANSITIONS.get(current_stage, [])
    
    async def try_advance_stage(
        self,
        conversation,
        user_message: str,
        intent: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Determine if conversation should advance to next stage.
        
        Args:
            conversation: Conversation object (must have stage, completed_fields, last_intent)
            user_message: The user's message (unused in current logic but kept for signature)
            intent: Detected intent from the message
        
        Returns:
            (new_stage_value, reason) where new_stage_value is a string or None
        """
        # Extract state from conversation object
        current_stage_str = getattr(conversation, "conversation_stage", "greeting")
        try:
            current_stage = ConversationStage(current_stage_str)
        except ValueError:
            current_stage = ConversationStage.GREETING
        
        completed_fields = getattr(conversation, "completed_fields", {}) or {}
        last_intent = getattr(conversation, "last_intent", None)
        
        # Greeting -> Qualification
        if current_stage == ConversationStage.GREETING:
            if "name" in completed_fields and "phone" in completed_fields:
                if self.is_valid_transition(
                    ConversationStage.GREETING,
                    ConversationStage.QUALIFICATION
                ):
                    return ConversationStage.QUALIFICATION.value, "Collected name and phone"
            return None, "Missing name or phone"
        
        # Qualification -> Recommendation or Booking or Support
        elif current_stage == ConversationStage.QUALIFICATION:
            if last_intent == "ready_to_book":
                if self.is_valid_transition(
                    ConversationStage.QUALIFICATION,
                    ConversationStage.BOOKING
                ):
                    return ConversationStage.BOOKING.value, "User ready to book"
            
            elif last_intent == "need_recommendation":
                if self.is_valid_transition(
                    ConversationStage.QUALIFICATION,
                    ConversationStage.RECOMMENDATION
                ):
                    return ConversationStage.RECOMMENDATION.value, "User needs recommendation"
            
            if "budget" in completed_fields or "requirements" in completed_fields:
                if self.is_valid_transition(
                    ConversationStage.QUALIFICATION,
                    ConversationStage.RECOMMENDATION
                ):
                    return ConversationStage.RECOMMENDATION.value, "Collected qualification data"
            
            return None, "Need more qualification information"
        
        # Recommendation -> Booking
        elif current_stage == ConversationStage.RECOMMENDATION:
            if last_intent == "accepted_recommendation":
                if self.is_valid_transition(
                    ConversationStage.RECOMMENDATION,
                    ConversationStage.BOOKING
                ):
                    return ConversationStage.BOOKING.value, "User accepted recommendation"
            
            if last_intent == "rejected_recommendation":
                if self.is_valid_transition(
                    ConversationStage.RECOMMENDATION,
                    ConversationStage.QUALIFICATION
                ):
                    return ConversationStage.QUALIFICATION.value, "User rejected, retry qualification"
            
            return None, "Waiting for recommendation feedback"
        
        # Booking -> Followup
        elif current_stage == ConversationStage.BOOKING:
            if "booking_date" in completed_fields and "booking_time" in completed_fields:
                if last_intent == "booking_confirmed":
                    if self.is_valid_transition(
                        ConversationStage.BOOKING,
                        ConversationStage.FOLLOWUP
                    ):
                        return ConversationStage.FOLLOWUP.value, "Booking confirmed"
            return None, "Waiting for booking confirmation"
        
        # Followup -> Closed
        elif current_stage == ConversationStage.FOLLOWUP:
            if last_intent == "conversation_closed":
                if self.is_valid_transition(
                    ConversationStage.FOLLOWUP,
                    ConversationStage.CLOSED
                ):
                    return ConversationStage.CLOSED.value, "Conversation completed"
            return None, "In followup stage"
        
        # Support -> Closed or Booking
        elif current_stage == ConversationStage.SUPPORT:
            if last_intent == "resolved":
                if self.is_valid_transition(
                    ConversationStage.SUPPORT,
                    ConversationStage.CLOSED
                ):
                    return ConversationStage.CLOSED.value, "Issue resolved"
            return None, "In support stage"
        
        # No transition possible
        return None, f"Cannot advance from {current_stage.value}"
    
    def get_missing_fields(
        self,
        stage: ConversationStage,
        completed_fields: Dict[str, dict]
    ) -> List[str]:
        """Get list of required fields not yet collected"""
        requirements = self.STAGE_REQUIREMENTS.get(stage, {})
        required_fields = requirements.get("required_fields", [])
        
        missing = []
        for field in required_fields:
            if field not in completed_fields:
                missing.append(field)
        
        return missing