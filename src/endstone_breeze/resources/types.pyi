# stub for extensions

from typing import TypedDict, Callable, Any
from endstone import Logger, Player
from endstone.event import PlayerChatEvent
from endstone.plugin import Plugin

class PlayerData(TypedDict):
    """Player data structure for tracking message history and timing."""
    latest_time_a_message_was_sent: float
    last_message: str

class PlayerDataManager:
    """Manages player data including message timestamps and content."""
    player_data: dict[str, PlayerData]
    
    def __init__(self) -> None: ...
    def update_player_data(self, name: str, message: str) -> None: ...
    def get_player_data(self, name: str) -> PlayerData: ...
    def remove_player_data(self, name: str) -> None: ...

class BreezeTextProcessing:
    """Handles text processing including profanity checking and censoring."""
    
    def check_and_censor(
        self, 
        text: str, 
        checks: dict[str, bool] | None = None
    ) -> tuple[str, bool, list[str]]:
        """
        Check and censor text for profanity.
        
        Returns:
            tuple of (censored_message, is_bad, caught_checks)
        """
        ...

class BreezeExtensionAPI:
    """Public API for Breeze extensions to interact with the system."""
    
    class _EventBus:
        """Internal event bus for extension hooks."""
        def on(self, event_name: str, func: Callable[..., Any]) -> None: ...
    
    class HandlerInput(TypedDict):
        """Input data for message handlers."""
        message: str
        player: Player
        chat_format: str
        recipients: list[Player]
    
    class HandlerOutput(TypedDict):
        """Output data returned by message handlers."""
        is_bad: bool
        fully_cancel_message: bool
        finished_message: str
        original_message: str
    
    ready: bool
    logger: Logger
    pdm: PlayerDataManager | None
    btp: BreezeTextProcessing | None
    
    def __init__(
        self, 
        logger: Logger, 
        pdm: PlayerDataManager | None = None, 
        btp: BreezeTextProcessing | None = None
    ) -> None: ...
    
    @property
    def eventbus(self) -> _EventBus: ...
    
    def on_breeze_chat_event(
        self, 
        event: PlayerChatEvent, 
        plugin: Plugin
    ) -> tuple[PlayerChatEvent, Plugin]: ...
    
    def on_breeze_chat_processed(
        self, 
        event: PlayerChatEvent, 
        handler_output: HandlerOutput, 
        is_bad: bool, 
        plugin: Plugin
    ) -> tuple[PlayerChatEvent, HandlerOutput, bool, Plugin]: ...
    
    def initialize(self, plugin_instance: Plugin) -> None: ...
