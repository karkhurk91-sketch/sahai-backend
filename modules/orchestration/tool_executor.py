"""
Tool Executor - Handles structured tool execution for bookings, follow-ups, recommendations
Replaces unstructured LLM tool use with deterministic tool execution
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta, date, time
from uuid import UUID
import uuid
from modules.common.logger import get_logger
from modules.ai.booking_helper import save_booking_generic
from modules.message.sender import send_whatsapp_text
import re

logger = get_logger(__name__)


class ToolExecutor:
    """
    Executes tools deterministically based on orchestrator decision.
    No LLM decides which tool to use - orchestrator decides.
    """

    @staticmethod
    async def create_booking(
        org_id: str,
        lead_id: str,
        customer_phone: str,
        customer_name: str,
        service: str,
        booking_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a booking deterministically."""
        try:
            # Parse date
            date_reference = booking_data.get("date")
            if date_reference == "tomorrow":
                booking_date = (datetime.now() + timedelta(days=1)).date()
            else:
                booking_date = datetime.now().date()

            # Parse time
            booking_time = time(hour=14, minute=0)  # Default 2 PM
            if booking_data.get("time"):
                time_match = re.search(r"(\d{2}):(\d{2})", booking_data.get("time", ""))
                if time_match:
                    booking_time = time(
                        hour=int(time_match.group(1)),
                        minute=int(time_match.group(2))
                    )

            # Create booking
            booking_state = {
                "customer_phone": customer_phone,
                "customer_name": customer_name,
                "booking_date": booking_date,
                "booking_time": booking_time,
                "service": service or "site visit",
                "lead_id": lead_id,
            }

            booking = await save_booking_generic(
                org_id=org_id,
                state=booking_state,
                industry="default"
            )

            if booking:
                logger.info(f"✅ Booking created: {booking.id}")
                return {
                    "status": "success",
                    "booking_id": str(booking.id),
                    "booking_date": booking.booking_date.isoformat(),
                    "booking_time": str(booking.booking_time),
                    "message": f"Booking confirmed for {booking.booking_date} at {booking.booking_time}",
                }
            else:
                logger.error("Booking creation returned None")
                return {
                    "status": "error",
                    "message": "Failed to create booking",
                }
        except Exception as e:
            logger.error(f"Booking creation failed: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Booking error: {str(e)}",
            }

    @staticmethod
    async def send_followup(
        org_id: str,
        customer_phone: str,
        followup_type: str,
        followup_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send follow-up message deterministically."""
        try:
            messages = {
                "booking_confirmation": f"Thank you for booking with us! We'll confirm your appointment shortly.",
                "recommendation_followup": f"Based on your requirements, we have some great options for you.",
                "checkout_reminder": f"Just checking in - are you still interested? Let me know if you have questions!",
            }

            message = messages.get(followup_type, "Just following up!")

            success, wamid = await send_whatsapp_text(
                to_number=customer_phone,
                text=message,
                org_id=org_id
            )

            if success:
                logger.info(f"✅ Follow-up sent: {wamid}")
                return {
                    "status": "success",
                    "message_id": wamid,
                    "message": message,
                }
            else:
                return {
                    "status": "error",
                    "message": "Failed to send follow-up",
                }
        except Exception as e:
            logger.error(f"Follow-up send failed: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Follow-up error: {str(e)}",
            }

    @staticmethod
    async def get_recommendation(
        org_id: str,
        industry: str,
        requirements: Dict[str, Any],
        budget: str,
    ) -> Dict[str, Any]:
        """
        Fetch recommendation from industry-specific engine.
        Placeholder - to be implemented by industry SDK.
        """
        try:
            # This will be replaced by industry-specific recommendation engines
            logger.debug(f"Fetching recommendation for {industry}")

            # Placeholder response
            return {
                "status": "success",
                "recommendation": {
                    "type": "property" if industry == "real_estate" else "service",
                    "description": "Top recommended option based on your requirements",
                    "budget_range": budget,
                    "match_score": 0.85,
                },
            }
        except Exception as e:
            logger.error(f"Recommendation fetch failed: {e}")
            return {
                "status": "error",
                "message": "Could not generate recommendation",
            }

    @staticmethod
    async def handle_objection(
        objection: str,
        completed_fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Handle customer objections deterministically.
        Map objection to handler logic.
        """
        try:
            objection_lower = objection.lower()

            if "expensive" in objection_lower or "price" in objection_lower:
                return {
                    "status": "success",
                    "objection_type": "price",
                    "response_type": "offer_alternatives",
                    "message": "I understand budget is important. Let me show you options in different price ranges.",
                }

            elif "interested" in objection_lower or "no" in objection_lower:
                return {
                    "status": "success",
                    "objection_type": "disinterest",
                    "response_type": "reschedule_followup",
                    "message": "No problem! I'll reach out in a few days with updates.",
                }

            elif "time" in objection_lower or "busy" in objection_lower:
                return {
                    "status": "success",
                    "objection_type": "timing",
                    "response_type": "suggest_later",
                    "message": "Perfect! Let's schedule a better time that works for you.",
                }

            else:
                return {
                    "status": "success",
                    "objection_type": "generic",
                    "response_type": "ask_clarification",
                    "message": "I understand your concern. Can you tell me more about what matters most to you?",
                }
        except Exception as e:
            logger.error(f"Objection handling failed: {e}")
            return {
                "status": "error",
                "message": "Could not handle objection",
            }

    @staticmethod
    def validate_tool_input(
        tool_name: str,
        tool_input: Dict[str, Any],
    ) -> tuple[bool, str]:
        """
        Validate tool input before execution.
        Prevents invalid tool calls.
        """
        validators = {
            "create_booking": ToolExecutor._validate_booking_input,
            "send_followup": ToolExecutor._validate_followup_input,
            "get_recommendation": ToolExecutor._validate_recommendation_input,
        }

        validator = validators.get(tool_name)
        if validator:
            return validator(tool_input)

        return True, "No validation needed"

    @staticmethod
    def _validate_booking_input(booking_input: Dict[str, Any]) -> tuple[bool, str]:
        """Validate booking input."""
        if not booking_input.get("customer_phone"):
            return False, "Missing customer_phone"
        if not booking_input.get("booking_date"):
            return False, "Missing booking_date"
        return True, "Valid"

    @staticmethod
    def _validate_followup_input(followup_input: Dict[str, Any]) -> tuple[bool, str]:
        """Validate follow-up input."""
        if not followup_input.get("customer_phone"):
            return False, "Missing customer_phone"
        return True, "Valid"

    @staticmethod
    def _validate_recommendation_input(rec_input: Dict[str, Any]) -> tuple[bool, str]:
        """Validate recommendation input."""
        if not rec_input.get("requirements"):
            return False, "Missing requirements"
        return True, "Valid"
