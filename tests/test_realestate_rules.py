import sys
import pytest

sys.path.insert(0, '.')
from modules.ai.industries.realestate.rules_engine import RulesEngine
from modules.ai.industries.realestate.state import State


def test_detect_intent_exact_confirm_ids():
    engine = RulesEngine()

    assert engine.detect_intent('confirm_yes') == 'confirm_yes'
    assert engine.detect_intent('confirm_no') == 'confirm_no'
    assert engine.detect_intent('Confirm_No') == 'confirm_no'


def test_confirm_no_triggers_correction():
    engine = RulesEngine()
    state = State()
    state.stage = 'confirmation'
    state.confirmation_pending = True
    state.pending_summary = {'name': 'Anil', 'budget': '₹20–50L', 'location': 'Vijay Nagar', 'bhk': '2 BHK', 'possession': '1-2 months'}

    action = engine.process('confirm_no', state)
    assert action['action'] == 'ask_which_field_to_correct'


def test_dynamic_field_selection_for_correction():
    engine = RulesEngine()
    state = State()
    state.flow_steps = [
        {'field': 'preferred_floor', 'action': 'ask_preferred_floor', 'required': True},
        {'field': 'name', 'action': 'ask_name', 'required': True}
    ]
    state.stage = 'confirmation'
    state.confirmation_pending = False
    state.pending_correction_field = None

    action = engine.process('preferred_floor', state)
    assert action['action'] == 'ask_new_value_for_preferred_floor'
    assert state.pending_correction_field == 'preferred_floor'


def test_confirmation_greeting_prompts_continue_or_new_property():
    engine = RulesEngine()
    state = State()
    state.stage = 'recommendation'
    state.pending_summary = {'name': 'Anil', 'budget': '₹20–50L', 'location': 'Vijay Nagar', 'bhk': '2 BHK', 'possession': '1-2 months'}

    action = engine.process('hello', state)
    assert action['action'] == 'ask_continue_or_new_property'


def test_new_property_restarts_lead_capture():
    engine = RulesEngine()
    state = State()
    state.stage = 'recommendation'
    state.pending_summary = {'name': 'Anil', 'budget': '₹20–50L', 'location': 'Vijay Nagar', 'bhk': '2 BHK', 'possession': '1-2 months'}
    state.previous_lead_summary = state.pending_summary.copy()

    action = engine.process('new property', state)
    assert action['action'].startswith('ask_')
    assert state.stage == 'qualification'
    assert state.name is None
    assert state.pending_summary == {}


def test_lead_complete_reply_with_different_previous_summary():
    from modules.ai.industries.realestate.prompts import Prompts

    prompts = Prompts(org_id='test')
    state = State()
    state.previous_lead_summary = {'name': 'Anil', 'budget': '₹20–50L', 'location': 'Vijay Nagar', 'bhk': '2 BHK', 'possession': '1-2 months'}
    data = {'name': 'Anil', 'budget': '> ₹50L', 'location': 'Vijay Nagar', 'bhk': '3 BHK', 'possession': 'Immediate', 'lead_tag': 'warm'}

    reply = prompts._lead_complete_reply(data, state)
    assert 'Previous:' in reply
    assert 'Current:' in reply


def test_lead_complete_reply_with_same_previous_summary():
    from modules.ai.industries.realestate.prompts import Prompts

    prompts = Prompts(org_id='test')
    summary = {'name': 'Anil', 'budget': '₹20–50L', 'location': 'Vijay Nagar', 'bhk': '2 BHK', 'possession': '1-2 months', 'lead_tag': 'warm'}
    state = State()
    state.previous_lead_summary = summary.copy()

    reply = prompts._lead_complete_reply(summary, state)
    assert 'Previous:' not in reply
    assert 'Current:' not in reply
    assert 'Thank you' in reply or 'Thanks' in reply


def test_dynamic_conversation_flow_with_custom_fields():
    engine = RulesEngine()
    state = State()
    state.stage = 'qualification'
    state.flow_steps = [
        {
            'field': 'name',
            'action': 'ask_name',
            'prompt': 'May I know your name?',
            'type': 'text',
            'required': True
        },
        {
            'field': 'property_address',
            'action': 'ask_property_address',
            'prompt': 'What is the address of the property you want to sell?',
            'type': 'text',
            'required': True
        },
        {
            'field': 'property_type',
            'action': 'ask_property_type',
            'prompt': 'What type of property is it?',
            'type': 'button',
            'required': True,
            'options': [
                {'id': 'prop_apartment', 'title': 'Apartment', 'value': 'Apartment'},
                {'id': 'prop_villa', 'title': 'Villa', 'value': 'Villa'}
            ]
        },
        {
            'field': 'confirm',
            'action': 'ask_confirmation',
            'prompt': 'Please confirm your selling details:',
            'type': 'button',
            'required': False,
            'options': [
                {'id': 'confirm_yes', 'title': 'Confirm', 'value': True},
                {'id': 'confirm_no', 'title': 'Change', 'value': False}
            ]
        }
    ]

    state.awaiting_field = 'name'
    action = engine.process('Rita', state)
    assert action['action'] == 'ask_property_address'
    assert state.name == 'Rita'

    state.awaiting_field = 'property_address'
    action = engine.process('123 MG Road, Pune', state)
    assert action['action'] == 'ask_property_type'
    assert state.property_address == '123 MG Road, Pune'

    state.awaiting_field = 'property_type'
    state.interactive_map = {
        'prop_villa': ['property_type', 'Villa'],
        'confirm_yes': ['confirm', True],
        'confirm_no': ['confirm', False]
    }
    action = engine.process('prop_villa', state)
    assert action['action'] == 'ask_confirmation'
    assert state.property_type == 'Villa'

    action = engine.process('confirm_yes', state)
    assert action['action'] == 'lead_complete'
    assert state.stage == 'recommendation'
    assert state.pending_summary['property_type'] == 'Villa'


def test_optional_dynamic_step_is_asked():
    engine = RulesEngine()
    state = State()
    state.stage = 'qualification'
    state.flow_steps = [
        {
            'field': 'name',
            'type': 'text',
            'prompt': 'May I know your name?',
            'required': True
        },
        {
            'field': 'reason_for_selling',
            'type': 'button',
            'prompt': 'What is your reason for selling?',
            'required': False,
            'options': [
                {'id': 'reason_relocation', 'title': 'Relocation', 'value': 'relocation'},
                {'id': 'reason_upgrade', 'title': 'Upgrade', 'value': 'upgrade'}
            ]
        },
        {
            'field': 'confirm',
            'action': 'ask_confirmation',
            'type': 'button',
            'prompt': 'Please confirm your details:',
            'required': True,
            'options': [
                {'id': 'confirm_yes', 'title': 'Confirm', 'value': True},
                {'id': 'confirm_no', 'title': 'Change', 'value': False}
            ]
        }
    ]

    state.awaiting_field = 'name'
    action = engine.process('Rita', state)
    assert action['action'] == 'ask_reason_for_selling'
    assert state.name == 'Rita'

    state.awaiting_field = 'reason_for_selling'
    state.interactive_map = {
        'reason_upgrade': ['reason_for_selling', 'upgrade'],
        'confirm_yes': ['confirm', True],
        'confirm_no': ['confirm', False]
    }
    action = engine.process('reason_upgrade', state)
    assert action['action'] == 'ask_confirmation'
    assert state.reason_for_selling == 'upgrade'


def test_address_input_does_not_match_location_extractor():
    engine = RulesEngine()
    state = State()
    state.stage = 'qualification'
    state.flow_steps = [
        {'field': 'address', 'action': 'ask_property_address', 'required': True, 'type': 'text'},
        {'field': 'budget', 'action': 'ask_budget', 'required': True, 'type': 'button'}
    ]
    state.awaiting_field = 'address'

    action = engine.process('indore', state)
    assert action['action'] == 'ask_budget'
    assert state.address == 'indore'
    assert getattr(state, 'location', None) is None


def test_budget_input_parses_rupee_L_format():
    engine = RulesEngine()
    state = State()
    state.stage = 'qualification'
    state.flow_steps = [
        {'field': 'budget', 'action': 'ask_budget', 'required': True, 'type': 'button'},
        {'field': 'bhk', 'action': 'ask_bhk', 'required': True, 'type': 'button'}
    ]
    state.awaiting_field = 'budget'

    action = engine.process('What is your budget range? < ₹20L', state)
    assert state.budget_amount == 20.0
    assert '<' not in state.budget or '₹20L' not in state.budget
    assert action['action'] == 'ask_bhk'


def test_state_from_dict_preserves_custom_fields():
    state = State()
    state_json = {
        'flow_steps': [
            {'field': 'property', 'action': 'ask_property', 'required': True},
            {'field': 'preferred_floor', 'action': 'ask_floor', 'required': True}
        ],
        'stage': 'qualification',
        'property': 'Buy',
        'preferred_floor': 'lower',
        'interactive_map': {'property_buy': ['property', 'Buy'], 'floor_low': ['preferred_floor', 'lower']}
    }

    state.from_dict(state_json)
    assert state.stage == 'qualification'
    assert state.flow_steps == state_json['flow_steps']
    assert getattr(state, 'property') == 'Buy'
    assert getattr(state, 'preferred_floor') == 'lower'
    assert state.interactive_map == state_json['interactive_map']


def test_prompt_config_matches_step_by_field_name():
    from modules.ai.industries.realestate.prompts import Prompts

    state = State()
    state.flow_steps = [
        {
            'field': 'address',
            'type': 'text',
            'prompt': 'What is the property address?',
            'required': True
        }
    ]
    prompts = Prompts(org_id='test')

    reply = prompts.get_rule_reply('ask_address', {}, state)
    assert reply == 'What is the property address?'


def test_prompt_config_matches_step_by_action_name():
    from modules.ai.industries.realestate.prompts import Prompts

    state = State()
    state.flow_steps = [
        {
            'field': 'property_address',
            'action': 'ask_address',
            'type': 'text',
            'prompt': 'What is the property address?',
            'required': True
        }
    ]
    prompts = Prompts(org_id='test')

    reply = prompts.get_rule_reply('ask_address', {}, state)
    assert reply == 'What is the property address?'


def test_dynamic_db_flow_sequence_with_field_only_steps():
    engine = RulesEngine()
    state = State()
    state.stage = 'qualification'
    state.flow_steps = [
        {
            'field': 'address',
            'type': 'text',
            'prompt': 'What is the property address?',
            'required': True
        },
        {
            'field': 'preferred_floor',
            'type': 'button',
            'prompt': 'Which floor do you prefer?',
            'required': True,
            'options': [
                {'id': 'floor_low', 'title': 'Lower floor', 'value': 'lower'},
                {'id': 'floor_mid', 'title': 'Middle floor', 'value': 'mid'},
                {'id': 'floor_high', 'title': 'Higher floor', 'value': 'high'}
            ]
        }
    ]

    state.awaiting_field = 'address'
    action = engine.process('5 MG Road', state)
    assert action['action'] == 'ask_preferred_floor'
    assert state.address == '5 MG Road'

    state.awaiting_field = 'preferred_floor'
    action = engine.process('floor_low', state)
    assert action['action'] == 'ask_confirmation'
    assert state.preferred_floor == 'lower'
    assert state.stage == 'confirmation'


def test_confirm_yes_before_confirmation_stage_completes_lead():
    engine = RulesEngine()
    state = State()
    state.stage = 'qualification'
    state.confirmation_pending = False
    state.name = 'Anil'
    state.budget = '< ₹20L'
    state.budget_amount = 20.0
    state.location = 'dore'
    state.bhk = '1 BHK'
    state.possession = 'lower'
    state.flow_steps = [
        {'field': 'name', 'required': True},
        {'field': 'budget', 'required': True},
        {'field': 'location', 'required': True},
        {'field': 'bhk', 'required': True},
        {'field': 'possession', 'required': True}
    ]

    action = engine.process('confirm_yes', state)
    assert action['action'] == 'lead_complete'
    assert state.stage == 'recommendation'
    assert state.pending_summary['name'] == 'Anil'


def test_state_flow_type_relaxed_fallback_to_buyer():
    engine = RulesEngine()
    state = State()
    state.flow_type = 'seller'
    state.stage = 'qualification'
    state.flow_steps = []
    state.awaiting_field = None

    action = engine.process('hello', state)
    assert action['action'] == 'ask_name'


def test_correction_flow_full_cycle_from_confirmation_rejection():
    """
    Test the full correction flow:
    1. User in confirmation stage clicks "Change" (confirm_no)
    2. System asks "Which detail would you like to change?"
    3. User says "budget"
    4. System asks for new budget value
    5. User provides new budget
    6. System returns to confirmation with updated budget
    """
    engine = RulesEngine()
    state = State()
    state.stage = 'confirmation'
    state.confirmation_pending = True
    state.name = 'Anil'
    state.budget = '< ₹20L'
    state.budget_amount = 20.0
    state.location = 'Rajendra Nagar'
    state.bhk = '1 BHK'
    state.possession = 'immediate'
    state.pending_summary = {
        'name': 'Anil',
        'budget': '< ₹20L',
        'location': 'Rajendra Nagar',
        'bhk': '1 BHK',
        'possession': 'immediate'
    }
    state.flow_steps = [
        {'field': 'name', 'type': 'text', 'required': True},
        {'field': 'budget', 'type': 'button', 'required': True},
        {'field': 'location', 'type': 'button', 'required': True},
        {'field': 'bhk', 'type': 'button', 'required': True},
        {'field': 'possession', 'type': 'button', 'required': True},
    ]
    state.interactive_map = {
        'confirm_yes': ['confirm', True],
        'confirm_no': ['confirm', False]
    }

    # Step 1: User clicks "Change" (confirm_no)
    action = engine.process('confirm_no', state)
    assert action['action'] == 'ask_which_field_to_correct'
    # After confirm_no, stage should stay in confirmation for correction handling
    assert state.stage == 'confirmation'
    assert state.confirmation_pending == False

    # Step 2: User says "budget" to correct that field
    action = engine.process('budget', state)
    assert action['action'] == 'ask_new_value_for_budget'
    assert state.pending_correction_field == 'budget'
    assert state.awaiting_field == 'budget'

    # Step 3: User provides new budget value
    action = engine.process('₹50L', state)
    assert action['action'] == 'ask_confirmation'
    # Budget should be updated
    assert state.budget == '₹50L'
    assert state.pending_correction_field == None  # Cleared after correction
    assert state.confirmation_pending == True  # Back to confirmation state
    # Updated summary should have new budget
    assert state.pending_summary['budget'] == '₹50L'


def test_correction_flow_with_location_field():
    """
    Test correction for location field (different from budget to ensure field handling is generic)
    """
    engine = RulesEngine()
    state = State()
    state.stage = 'confirmation'
    state.confirmation_pending = True
    state.name = 'Anil'
    state.budget = '< ₹20L'
    state.location = 'Vijay Nagar'
    state.bhk = '1 BHK'
    state.possession = 'immediate'
    state.pending_summary = {
        'name': 'Anil',
        'budget': '< ₹20L',
        'location': 'Vijay Nagar',
        'bhk': '1 BHK',
        'possession': 'immediate'
    }
    state.flow_steps = [
        {'field': 'name', 'type': 'text', 'required': True},
        {'field': 'budget', 'type': 'button', 'required': True},
        {'field': 'location', 'type': 'button', 'required': True},
        {'field': 'bhk', 'type': 'button', 'required': True},
        {'field': 'possession', 'type': 'button', 'required': True},
    ]
    state.interactive_map = {'confirm_no': ['confirm', False]}

    # User rejects confirmation
    action = engine.process('confirm_no', state)
    assert action['action'] == 'ask_which_field_to_correct'
    assert state.stage == 'confirmation'

    # User wants to change location
    action = engine.process('location', state)
    assert action['action'] == 'ask_new_value_for_location'
    assert state.pending_correction_field == 'location'

    # User provides new location
    action = engine.process('Rajendra Nagar', state)
    assert action['action'] == 'ask_confirmation'
    assert state.location == 'Rajendra Nagar'
    assert state.pending_summary['location'] == 'Rajendra Nagar'
    assert state.pending_correction_field == None


# ========== ADDED TEST FOR "CHANGE" BUTTON LOGIC ==========
def test_change_button_triggers_correction_and_field_selection():
    """
    Explicitly test the behaviour when the user clicks the "Change" button.
    This simulates the interactive button reply with id 'confirm_no' and ensures
    the engine correctly transitions to the field selection state.
    """
    engine = RulesEngine()
    state = State()
    state.stage = 'confirmation'
    state.confirmation_pending = True
    state.name = 'Anil'
    state.budget = '< ₹20L'
    state.budget_amount = 20.0
    state.location = 'Vijay Nagar'
    state.bhk = '1 BHK'
    state.possession = 'immediate'
    state.pending_summary = {
        'name': 'Anil',
        'budget': '< ₹20L',
        'location': 'Vijay Nagar',
        'bhk': '1 BHK',
        'possession': 'immediate'
    }
    # Simulate the interactive map containing the confirm button mapping
    state.interactive_map = {
        'confirm_yes': ['confirm', True],
        'confirm_no': ['confirm', False]
    }
    state.flow_steps = [
        {'field': 'name', 'type': 'text', 'required': True},
        {'field': 'budget', 'type': 'button', 'required': True},
        {'field': 'location', 'type': 'button', 'required': True},
        {'field': 'bhk', 'type': 'button', 'required': True},
        {'field': 'possession', 'type': 'button', 'required': True},
    ]

    # 1. User clicks "Change" (the interactive button sends 'confirm_no')
    action = engine.process('confirm_no', state)

    # 2. Assert that the bot asks which field to change
    assert action['action'] == 'ask_which_field_to_correct'
    # The confirmation pending flag should be cleared, and stage remains "confirmation"
    assert state.confirmation_pending is False
    assert state.stage == 'confirmation'
    # No correction field should be pending yet
    assert state.pending_correction_field is None

    # 3. Simulate the user typing a field name (e.g., 'budget')
    # The engine should now treat this as a field selection
    action = engine.process('budget', state)
    assert action['action'] == 'ask_new_value_for_budget'
    assert state.pending_correction_field == 'budget'
    assert state.awaiting_field == 'budget'

    # 4. User provides the new value
    action = engine.process('₹50L', state)
    assert action['action'] == 'ask_confirmation'
    assert state.budget == '₹50L'
    assert state.budget_amount == 50.0
    assert state.pending_correction_field is None
    assert state.confirmation_pending is True
    # The confirmation summary should reflect the updated budget
    assert state.pending_summary['budget'] == '₹50L'