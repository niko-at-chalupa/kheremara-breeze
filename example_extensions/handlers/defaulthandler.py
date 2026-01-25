# Rename to handler.py in breeze/extensions/ folder!

# Use this as a template for your own handlers, as this is identical to the default one

from extensions import BreezeTextProcessing, PlayerDataManager, BreezeExtensionAPI #type: ignore

import time
from random import randint

def handler(handler_input: "BreezeExtensionAPI.HandlerInput", player_data_manager: "PlayerDataManager", breeze_text_processing: "BreezeTextProcessing") -> "BreezeExtensionAPI.HandlerOutput":
    # player_data_manager is an instance of PlayerDataManager used by the server. It can be used to get and update player data.
    # The server will automatically add/remove player data from it
    
    # breeze_text_processing is an instance of BreezeTextProcessing used by the server. It can be used to check and censor messages (which removes & censors profane words).
    sender_uuid = str(handler_input["player"].unique_id)
    finished_message = handler_input["message"]

    local_player_data = player_data_manager.get_player_data(handler_input["player"].name)
    is_bad = False # set to true if the message may violate your rules
    fully_cancel_message = (False, "") # first element is whether to fully cancel the message (i.e., not send it at all),
    # second element is the reason. it is unused internally but you can use it yourself. will get stored in the handleroutput
    should_check_message = True # weather to check the message or not. set to false to skip checking
    caught = [] # list of what methods to check the message was caught by. great for debugging if you're layering different filtering methods

    # spam check
    if time.monotonic() - local_player_data["latest_time_a_message_was_sent"] < 0.5:
        fully_cancel_message = (True, "messages sent too quickly")
        should_check_message = False
        handler_input["player"].send_message("You're sending messages too fast!")

    if fully_cancel_message[0]:
        should_check_message = False

    if should_check_message:
        finished_message, is_bad, caught = breeze_text_processing.check_and_censor(handler_input["message"])

    player_data_manager.update_player_data(handler_input["player"].name, handler_input["message"])

    return {
        "is_bad": is_bad,
        "fully_cancel_message": fully_cancel_message[0],
        "finished_message": finished_message,
        "original_message": handler_input["message"]
    }
