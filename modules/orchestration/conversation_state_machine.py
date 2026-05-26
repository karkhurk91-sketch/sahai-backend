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
from dataclasses import dataclass
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


@dataclass
class StageTransition:
    """Result of stage transition attempt"""
    success: bool
    new_stage: Optional[ConversationStage]
    reason: str
    required_fields: List[str]


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
            "required_fields": [],  # Industry-specific, handled by rules engine
            "timeout_seconds": 1800,
        },
        ConversationStage.RECOMMENDATION: {
            "required_fields": [],  # Determined by search results
            "timeout_seconds": 600,
        },
        ConversationStage.BOOKING: {
            "required_fields": ["booking_date", "booking_time"],
            "timeout_seconds": 1200,
        },
        ConversationStage.FOLLOWUP: {
            "required_fields": [],
            "timeout_seconds": 86400,  # 24 hours
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
        current_stage: ConversationStage,
        completed_fields: Dict[str, dict],
        last_intent: Optional[str],
        user_message: str
    ) -> StageTransition:
        """
        Attempt to advance conversation stage based on collected data.
        
        Returns:
            StageTransition with new stage if possible
        """
        
        # Greeting -> Qualification
        if current_stage == ConversationStage.GREETING:
            if "name" in completed_fields and "phone" in completed_fields:
                if self.is_valid_transition(
                    ConversationStage.GREETING,
                    ConversationStage.QUALIFICATION
                ):
                    return StageTransition(
                        success=True,
                        new_stage=ConversationStage.QUALIFICATION,
                        reason="Collected name and phone",
                        required_fields=[]
                    )
            return StageTransition(
                success=False,
                new_stage=None,
                reason="Missing name or phone",
                required_fields=["name", "phone"]
            )
        
        # Qualification -> Recommendation or Booking or Support
        elif current_stage == ConversationStage.QUALIFICATION:
            # Check intent to decide next stage
            if last_intent == "ready_to_book":
                if self.is_valid_transition(
                    ConversationStage.QUALIFICATION,
                    ConversationStage.BOOKING
                ):
                    return StageTransition(
                        success=True,
                        new_stage=ConversationStage.BOOKING,
                        reason="User ready to book",
                        required_fields=[]
                    )
            
            elif last_intent == "need_recommendation":
                if self.is_valid_transition(
                    ConversationStage.QUALIFICATION,
                    ConversationStage.RECOMMENDATION
                ):
                    return StageTransition(
                        success=True,
                        new_stage=ConversationStage.RECOMMENDATION,
                        reason="User needs recommendation",
                        required_fields=[]
                    )
            
            # If enough qualification data, move to recommendation
            if "budget" in completed_fields or "requirements" in completed_fields:
                if self.is_valid_transition(
                    ConversationStage.QUALIFICATION,
                    ConversationStage.RECOMMENDATION
                ):
                    return StageTransition(
                        success=True,
                        new_stage=ConversationStage.RECOMMENDATION,
                        reason="Collected qualification data",
                        required_fields=[]
                    )
            
            return StageTransition(
                success=False,
                new_stage=None,
                reason="Need more qualification information",
                required_fields=["budget", "requirements"]
            )
        
        # Recommendation -> Booking
        elif current_stage == ConversationStage.RECOMMENDATION:
            if last_intent == "accepted_recommendation":
                if self.is_valid_transition(
                    ConversationStage.RECOMMENDATION,
                    ConversationStage.BOOKING
                ):
                    return StageTransition(
                        success=True,
                        new_stage=ConversationStage.BOOKING,
                        reason="User accepted recommendation",
                        required_fields=[]
                    )
            
            # If user rejected, go back to qualification
            if last_intent == "rejected_recommendation":
                if self.is_valid_transition(
                    ConversationStage.RECOMMENDATION,
                    ConversationStage.QUALIFICATION
                ):
                    return StageTransition(
                        success=True,
                        new_stage=ConversationStage.QUALIFICATION,
                        reason="User rejected recommendation, retry qualification",
                        required_fields=[]
                    )
            
            return StageTransition(
                success=False,
                new_stage=None,
                reason="Waiting for recommendation feedback",
                required_fields=[]
            )
        
        # Booking -> Followup
        elif current_stage == ConversationStage.BOOKING:
            if "booking_date" in completed_fields and "booking_time" in completed_fields:
                if last_intent == "booking_confirmed":
                    if self.is_valid_transition(
                        ConversationStage.BOOKING,
                        ConversationStage.FOLLOWUP
                    ):
                        return StageTransition(
                            success=True,
                            new_stage=ConversationStage.FOLLOWUP,
                            reason="Booking confirmed",
                            required_fields=[]
                        )
            
            return StageTransition(
                success=False,
                new_stage=None,
                reason="Waiting for booking confirmation",
                required_fields=["booking_date", "booking_time"]
            )
        
        # Followup -> Closed
        elif current_stage == ConversationStage.FOLLOWUP:
            if last_intent == "conversation_closed":
                if self.is_valid_transition(
                    ConversationStage.FOLLOWUP,
                    ConversationStage.CLOSED
                ):
                    return StageTransition(
                        success=True,
                        new_stage=ConversationStage.CLOSED,
                        reason="Conversation completed",
                        required_fields=[]
                    )
            
            return StageTransition(
                success=False,
                new_stage=None,
                reason="In followup stage",
                required_fields=[]
            )
        
        # Support can go to many places
        elif current_stage == ConversationStage.SUPPORT:
            if last_intent == "resolved":
                if self.is_valid_transition(
                    ConversationStage.SUPPORT,
                    ConversationStage.CLOSED
                ):
                    return StageTransition(
                        success=True,
                        new_stage=ConversationStage.CLOSED,
                        reason="Issue resolved",
                        required_fields=[]
                    )
            
            return StageTransition(
                success=False,
                new_stage=None,
                reason="In support stage",
                required_fields=[]
            )
        
        # No transition possible
        return StageTransition(
            success=False,
            new_stage=None,
            reason=f"Cannot advance from {current_stage.value}",
            required_fields=[]
        )
    
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
