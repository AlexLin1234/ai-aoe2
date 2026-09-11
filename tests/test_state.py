from aoe2bot.perception.state import GameState, EntityObservation


def test_game_state_unknowns_and_serialization():
    state = GameState(age=None, notes=["unknown"], known_units=[EntityObservation(kind="villager")])
    restored = GameState.model_validate_json(state.model_dump_json())
    assert restored.food is None and restored.known_units[0].kind == "villager"
