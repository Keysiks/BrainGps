"""FSM state definitions for the BrainGPS bot."""

from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    """Input gathering wizard for strategy nodes."""

    collecting_input = State()
    """Generic state: collecting user inputs for the current strategy's input_fields."""


class Simulation(StatesGroup):
    """Roleplay simulator: AI plays the opponent."""

    active = State()


class Feedback(StatesGroup):
    """Collect optional textual feedback after dislike."""

    comment = State()
