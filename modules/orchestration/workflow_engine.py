"""
Workflow Orchestrator - System-driven conversation flow
Replaces prompt-driven chatbot with state machine-based orchestration
"""

from typing import Dict, Any, Optional, Tuple
from .conversation_state import ConversationStateManager, STAGE_QUALIFICATION, STAGE_BOOKING, STAGE_RECOMMENDATION
from .intent_detector import IntentDetector, UserIntent
from modules.common.logger import get_logger

logger = get_logger(__name__)


class WorkflowOrchestrator:
    """
    Controls conversation flow based on:
    1. Current stage
    2. Completed fields
    3. Detected intent
    4. Memory context
    
    NOT based on LLM prompts.
    """

    def __init__(self, state_manager: ConversationStateManager):
        self.state = state_manager

    async def get_next_action(
        self,
        conversation_id: str,
        user_message: str,
        memory_context: Dict[str, Any],
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Determine next action WITHOUT asking LLM.
        
        Returns:
        {
            "action": "ask_field" | "show_recommendation" | "create_booking" | "send_followup",
            "action_data": {...},
            "ai_context": "data for LLM to generate language only",
            "should_update_stage": bool,
            "next_stage": str
        }
        """

        # Get current state
        state = await self.state.get_state(conversation_id)
        stage = state.get("stage")
        completed_fields = state.get("completed_fields", {})

        # Detect intent
        intent = IntentDetector.detect(user_message)
        entities = IntentDetector.extract_entities(user_message, intent)

        # Check for repetition prevention
        last_intent = state.get("last_intent")
        if last_intent == intent.value and intent in [
            UserIntent.QUESTION,
            UserIntent.UNCLEAR,
        ]:
            logger.debug(f"User repeating intent: {intent.value}, providing context instead of re-asking")

        await self.state.set_last_intent(conversation_id, intent.value)

        # ===================== GREETING STAGE =====================
        if stage == "greeting":
            return {
                "action": "respond_greeting",
                "ai_context": {
                    "customer_name": memory_context.get("customer_name", ""),
                    "previous_interactions": len(memory_context.get("interaction_history", [])),
                },
                "should_update_stage": True,
                "next_stage": STAGE_QUALIFICATION,
                "message_type": "greeting_response",
            }

        # ===================== QUALIFICATION STAGE =====================
        elif stage == STAGE_QUALIFICATION:
            # Determine which field to ask next
            required_fields = self._get_required_fields(organization_id)
            missing_fields = [f for f in required_fields if f not in completed_fields]

            if not missing_fields:
                # All fields collected, move to recommendation
                return {
                    "action": "stage_transition",
                    "should_update_stage": True,
                    "next_stage": STAGE_RECOMMENDATION,
                    "message_type": "qualification_complete",
                }

            # Ask next missing field
            next_field = missing_fields[0]

            if intent == UserIntent.CONFIRMATION:
                # User is confirming answer to previous question
                await self.state.mark_field_completed(
                    conversation_id,
                    next_field,
                    entities.get(next_field, user_message)
                )
                logger.info(f"Field completed: {next_field}")

                # Move to next field
                remaining = [f for f in required_fields if f not in completed_fields]
                if remaining:
                    return {
                        "action": "ask_field",
                        "field_name": remaining[0],
                        "ai_context": {"field_description": self._get_field_description(remaining[0])},
                        "should_update_stage": False,
                        "message_type": "qualification_continue",
                    }
                else:
                    return {
                        "action": "stage_transition",
                        "should_update_stage": True,
                        "next_stage": STAGE_RECOMMENDATION,
                        "message_type": "qualification_complete",
                    }
            else:
                return {
                    "action": "ask_field",
                    "field_name": next_field,
                    "ai_context": {"field_description": self._get_field_description(next_field)},
                    "should_update_stage": False,
                    "message_type": "qualification_question",
                }

        # ===================== RECOMMENDATION STAGE =====================
        elif stage == STAGE_RECOMMENDATION:
            if intent == UserIntent.RECOMMENDATION_REQUEST or intent == UserIntent.QUESTION:
                if not state.get("recommendation_shown"):
                    return {
                        "action": "show_recommendation",
                        "ai_context": {
                            "budget": completed_fields.get("budget", {}).get("value"),
                            "requirements": completed_fields.get("requirements", {}).get("value"),
                            "preferences": memory_context.get("preferences", {}),
                        },
                        "should_update_stage": False,
                        "message_type": "show_recommendation",
                    }

            elif intent == UserIntent.BOOKING_REQUEST:
                return {
                    "action": "stage_transition",
                    "should_update_stage": True,
                    "next_stage": STAGE_BOOKING,
                    "message_type": "moving_to_booking",
                }

            else:
                return {
                    "action": "provide_context",
                    "ai_context": {"recommendation_status": state.get("recommendation_shown")},
                    "message_type": "recommendation_context",
                }

        # ===================== BOOKING STAGE =====================
        elif stage == STAGE_BOOKING:
            if intent == UserIntent.BOOKING_REQUEST:
                return {
                    "action": "create_booking",
                    "action_data": {
                        "date": entities.get("date_reference"),
                        "time": entities.get("time"),
                        "message": user_message,
                    },
                    "should_update_stage": True,
                    "next_stage": "followup",
                    "message_type": "booking_created",
                }

            elif intent == UserIntent.OBJECTION:
                return {
                    "action": "handle_objection",
                    "ai_context": {"objection": user_message},
                    "message_type": "objection_handling",
                    "should_update_stage": False,
                }

        # ===================== FOLLOW-UP STAGE =====================
        elif stage == "followup":
            return {
                "action": "send_followup",
                "ai_context": {"completed_booking": state.get("booking_status")},
                "message_type": "followup",
                "should_update_stage": False,
            }

        # Default: return context action
        return {
            "action": "provide_context",
            "ai_context": {"current_stage": stage},
            "message_type": "generic",
            "should_update_stage": False,
        }

    async def execute_action(
        self,
        action_plan: Dict[str, Any],
        conversation_id: str,
        customer_phone: str,
        org_id: str,
    ) -> Dict[str, Any]:
        """Execute the planned action and return result for AI response generation."""

        action = action_plan.get("action")
        logger.info(f"Executing action: {action}")

        if action == "ask_field":
            return {
                "status": "success",
                "field_to_ask": action_plan.get("field_name"),
                "context": action_plan.get("ai_context"),
            }

        elif action == "create_booking":
            # Booking will be created by tool executor, not here
            return {
                "status": "pending_booking_creation",
                "booking_data": action_plan.get("action_data"),
            }

        elif action == "show_recommendation":
            # Recommendation will be fetched by recommendation engine
            return {
                "status": "show_recommendation_pending",
                "context": action_plan.get("ai_context"),
            }

        elif action == "stage_transition":
            # Stage update will be done by state sync layer
            return {
                "status": "success",
                "message": f"Moving to {action_plan.get('next_stage')} stage",
            }

        return {"status": "success", "context": action_plan.get("ai_context")}

    @staticmethod
    def _get_required_fields(organization_id: str) -> list:
        """Get required qualification fields for organization."""
        # This should fetch from organization settings or industry config
        # For now, return defaults
        return ["budget", "requirements", "timeline"]

    @staticmethod
    def _get_field_description(field_name: str) -> str:
        """Get AI-friendly description of field to ask."""
        descriptions = {
            "budget": "What is your budget range?",
            "requirements": "What are your specific requirements?",
            "timeline": "When do you plan to make this purchase?",
            "property_type": "What type of property are you looking for?",
            "location": "Which location interests you?",
        }
        return descriptions.get(field_name, f"Tell me more about your {field_name}")
