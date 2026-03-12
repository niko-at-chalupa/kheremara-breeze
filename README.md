<div align="center">
<img src="images/breeze2.png" alt="breeze"/>

# breeze - Automated moderation & moderation tool for Endstone
</div>

> [!NOTE]
> This is still being worked on! Breeze's API may change significantly, so don't assume your stuff will continue working after an update

- [introduction](#introduction)
- [setup](#setup)
- [config](#config)
- [extension system](#extension-system)

## introduction
Breeze is a moderation system meant to both provide tools for moderators to moderate their server and to automatically block certain words in the chat.

While Breeze comes with its own automatic word blocking handler *(which blocks profane words)*, Breeze comes with an extension system so you can write your own code **to make it adapt to *your* rules**.

# setup
1. Download the latest .whl from [releases](https://github.com/niko-at-chalupa/kheremara-breeze/releases/tag/v1.0.0)

2. Copy the downloaded .whl into the plugins/ folder of your server, and breeze does the rest

<br />

# config

Soon!

# documentation

> ## BreezeExtensionAPI
> `BreezeExtensionAPI` is mostly for extensions, not handlers.
>
> **More information on what extensions may use this for in the extensions section**
>
> The plugin's `BreezeExtensionAPI` object can be accessed through `plugin.bea`, and the `bea` parameter of `on_load` in extensions. **Handlers cannot access the plugin’s `BreezeExtensionAPI` object directly**. *This keeps handlers isolated from extension hooks and internal event flows. Instead, use BreezeHandlerAPI*
>
> *Handlers **do** use `BreezeExtensionAPI` for its `HandlerInput` and `HandlerOutput` `TypedDicts`.*
>
> ### Event Bus
> This is used by extensions to register their events. Allows your extension to listen for events emitted by Breeze.
> <details><summary>Events</summary>
>
> Event | Invokes When | Parameters
> --- | --- | ---
> on_breeze_chat_event | When a player sends a chat message, before processing | `event: PlayerChatEvent`, `plugin: Plugin`
> on_breeze_chat_processed | After Breeze processes a message (censoring, blocking, etc.) | `event: endstone.event.PlayerChatEvent`, `handler_output: BreezeExtensionAPI.HandlerOutput`, `is_bad: bool`, `plugin: Plugin`
>
> </details>
>
> 
> <code><h3>HandlerInput</h3></code>
> Input for handlers.
>
> Key | Type | Description
> :---: | :---: | :---
> message | `str` | The raw message sent by the player
> player | `endstone.Player` | The player who sent the message
> chat_format | `str` | The chat format string *(e.g., how the message is displayed)*
> recipients | `list[endstone.Player]` | List of players who will receive the message
>
> <code><h3>HandlerOutput</h3></code>
> Output of handlers.
> Key | Type | Description
> :---: | :---: | :---
> is_bad | `bool` | Whether the message contained censored or blocked content
> fully_cancel_message | `bool` | Whether the message should be fully blocked from sending
> finished_message | `str` | The processed message after censoring or formatting *(e.g., "[tag] <player> i #### you!")*
> original_message | `str` | The original message before any processing *(e.g., "[tag] <player> i hate you!")*
>
> <code><h3>run_task</h3></code>
> Runs a task in the server's main thread with the plugin. Must be ran from the plugin's instance of `BreezeExtensionAPI`.
>
> <details><summary>Example code</summary>
>
> ```python
> from typing import TYPE_CHECKING
> 
> if TYPE_CHECKING: # The following are only stubs for typehints. They should only be imported for type checking
>     from . import BreezeExtensionAPI #type: ignore
>     from endstone.plugin import Plugin
> 
> def broadcast_message(plugin: "Plugin", message: str = "Hello!!"):
>     plugin.server.broadcast_message(message)
> 
> # on_load runs when Breeze loads your plugin 
> def on_load(bea: 'BreezeExtensionAPI'):
>     bea.logger.info("Basic extension loaded!!")
> 
>     # run once
>     bea.run_task(lambda: broadcast_message(bea.plugin))
> 
>     # run with some delay
>     bea.run_task(lambda: broadcast_message(bea.plugin, "I'm sent 100 ticks after the first message"), delay=100)
> 
>     # run over and over again
>     bea.run_task(lambda: broadcast_message(bea.plugin, "I'm sent every 50 ticks"), period=50)
> ```
> </details>
>
> <code><h3>submit</h3></code>
> Runs a coroutine in the background. Use `run_task` if you're doing anything that needs to be done in the main server thread in a coroutine ran in this scope.

> ## BreezeHandlerAPI
> Like `BreezeExtensionAPI`, but solely for handlers.
>
> <code><h3>run_task</h3></code>
> Runs a task in the server's main thread with the plugin. Must be ran from the plugin's instance of `BreezeHandlerAPI`. Identical to `BreezeExtensionAPI`'s `run_task`.
>
> <code><h3>submit</h3></code>
> Runs a coroutine in the background. Use `run_task` if you're doing anything that needs to be done in the main server thread in a coroutine ran in this scope. Identical to `BreezeExtensionAPI`'s `submit`.

> ## HANDLERS
> Handlers define how messages are *handled*.
>
> Use handlers to **change the way Breeze works with your rules**, so you can make Breeze:
> - Censor only slurs
> - Censor certain names
> - Handle filtered messages differently *(e.g., replace bad words and their neighbors with * instead of #, or choose to not send a messsage at all if it's bad)*
>
> Handlers take in `BreezeExtensionAPI.HandlerInput`, and return `BreezeExtensionAPI.HandlerOutput`
>
> <details><summary>Breeze's default handler</summary>
>
> ```python
>from typing import TYPE_CHECKING
>
>if TYPE_CHECKING: # The following are only stubs for typehints. They should only be imported for type checking
>    from extensions import BreezeTextProcessing, PlayerDataManager, BreezeExtensionAPI, BreezeHandlerAPI #type: ignore
>
>import time
>from random import randint
>
># handlers must have a handler function
>def handler(handler_input: "BreezeExtensionAPI.HandlerInput", player_data_manager: "PlayerDataManager", breeze_text_processing: "BreezeTextProcessing", handler_api: "BreezeHandlerAPI | None" = None) -> "BreezeExtensionAPI.HandlerOutput":
>    # player_data_manager is an instance of PlayerDataManager used by the server. It can be used to get and update player data.
>    # The server will automatically add/remove player data from it
>    
>    # breeze_text_processing is an instance of BreezeTextProcessing used by the server. It can be used to check and censor messages (which removes & censors profane words).
>    sender_uuid = str(handler_input["player"].unique_id)
>    finished_message = handler_input["message"]
>
>    local_player_data = player_data_manager.get_player_data(handler_input["player"].name)
>    is_bad = False # set to true if the message may violate your rules
>    fully_cancel_message = (False, "") # first element is whether to fully cancel the message (i.e., not send it at all), /
>    # second element is the reason. it is unused internally but you can use it yourself. will get stored in the handleroutput
>    should_check_message = True # weather to check the message or not. set to false to skip checking
>    caught = [] # list of what methods to check the message was caught by. great for debugging if you're layering different filtering methods
>
>    # spam check
>    if time.monotonic() - local_player_data["latest_time_a_message_was_sent"] < 0.5:
>        fully_cancel_message = (True, "messages sent too quickly")
>        should_check_message = False
>        handler_input["player"].send_message("You're sending messages too fast!")
>
>    if fully_cancel_message[0]:
>        should_check_message = False
>
>    if should_check_message:
>        finished_message, is_bad, caught = breeze_text_processing.check_and_censor(handler_input["message"])
>
>    player_data_manager.update_player_data(handler_input["player"].name, handler_input["message"])
>
>    return {
>        "is_bad": is_bad,
>        "fully_cancel_message": fully_cancel_message[0],
>        "finished_message": finished_message,
>        "original_message": handler_input["message"]
>    }
> ```
> </details>

> ## EXTENSIONS
> Extensions add on to Breeze using `BreezeExtensionAPI`'s event hook, usually for background tasks.
>
> They interface better with Breeze (on the moderation side), unlike making a whole new Endstone plugin.
>
> You can use extensions to:
> - Log moderator actions
> - Log potentially harmful messages
> - Evaluate user's past messages to see if a user should be moderated (e.g., to mute a player for their past messages, after careful review)
>
> <details><summary>Basic example extension</summary>
>
> ```python
>from typing import TYPE_CHECKING
>
>if TYPE_CHECKING: # The following are only stubs for typehints. They should only be imported for type checking
>    from . import BreezeExtensionAPI #type: ignore
>    from endstone.event import PlayerChatEvent
>
># on_load runs when Breeze loads your plugin 
>def on_load(bea: 'BreezeExtensionAPI'):
>    bea.logger.info("Basic extension loaded!!")
>
>    # note: this method can be renamed or placed whatever you want, as long as it's registered as a listener
>    def on_chat_processed(event: "PlayerChatEvent", handler_output: "BreezeExtensionAPI.HandlerOutput", is_bad, plugin):
>        if is_bad:
>            plugin.logger.info(f"[OutwardsChatRelay] player {event.player.name} sent a censored message: {handler_output['finished_message']}")
>    
>    # register event as a listener
>    bea.eventbus.on("on_breeze_chat_processed", on_chat_processed)
>```
>
> </details>
>
> <details><summary>Chat relay to Discord webhook</summary>
> 
> ```python
> # Run `pip install discord-webhook` before using
> from discord_webhook import DiscordWebhook
>from typing import TYPE_CHECKING
>import threading
>
>if TYPE_CHECKING:
>    from extensions import BreezeExtensionAPI  # type: ignore
>    from endstone.plugin import Plugin  # type: ignore
>    from endstone.event import PlayerChatEvent
>
>WEBHOOK_URL = "YOUR-WEBHOOK-URL"
>
>def send_webhook(content: str, author: str, xuid: str):
>    webhook = DiscordWebhook(url=WEBHOOK_URL)
>    webhook.content = content
>    webhook.rate_limit_retry = False
>    webhook.username = author
>    webhook.execute()
>
>def on_load(bea: "BreezeExtensionAPI"):
>    def on_chat_processed(event: "PlayerChatEvent", handler_output: "BreezeExtensionAPI.HandlerOutput", is_bad, plugin: "Plugin"):
>        if handler_output.get("fully_cancel_message", False):
>            return
>        if handler_output.get("finished_message", "") == "":
>            return
>
>        author = event.player.name
>        content = f"{handler_output.get('finished_message', '(No message)')}"
>
>        threading.Thread(
>            target=send_webhook,
>            args=(content, author, xuid,),
>            daemon=True
>        ).start()
>
>    bea.eventbus.on("on_breeze_chat_processed", on_chat_processed)
>```
>
></details>
