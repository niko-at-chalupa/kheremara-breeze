from endstone import ColorFormat, scheduler
from endstone.event import event_handler, PlayerJoinEvent, PlayerChatEvent, PlayerQuitEvent, EventPriority
from endstone.plugin import Plugin
import endstone
import importlib.resources as resources
from importlib.resources import files

from .utils.profanity_utils import ProfanityCheck, ProfanityLonglist, ProfanityExtralist
pc = ProfanityCheck()
pl = ProfanityLonglist()
pe = ProfanityExtralist()
from .utils.general_utils import to_hash_mask, split_into_tokens

from enum import Enum
from random import randint
import os, time, asyncio, inspect, importlib.util, sys, threading
from collections import defaultdict
from pathlib import Path
from typing import TypedDict, cast

class PlayerData(TypedDict):
    latest_time_a_message_was_sent: float
    last_message: str

class PlayerDataManager:
    player_data: defaultdict[str, PlayerData]

    def __init__(self):
        self.player_data = defaultdict(lambda: cast(PlayerData, {
            "latest_time_a_message_was_sent": time.monotonic() - 10,
            "last_message": ""
        }))
    
    def update_player_data(self, name, message) -> None:
        self.player_data[name]["latest_time_a_message_was_sent"] = time.monotonic()
        self.player_data[name]["last_message"] = message

    def get_player_data(self, name) -> PlayerData:
        return self.player_data[name]

    def remove_player_data(self, name) -> None:
        if name in self.player_data:
            del self.player_data[name]

class BreezeTextProcessing:
    def check_and_censor(self, text: str, checks: dict | None = None) -> tuple[str, bool, list]:
        finished_message = text
        defaults = {
            "Profanity-check": True,
            "Extralist": True,
            "Longlist": True,
        }
        if checks is not None:
            checks = {**defaults, **checks}
        else:
            checks = defaults
    

        caught = []
        is_bad = False
        
        # profanity check
        if pc.is_profane(text) and checks["Profanity-check"]:
            is_bad = True
            caught.append("Profanity-check")

            finished_message = pc.censor(finished_message, neighbors=2, window_size=1)
                
        # profanity extralist
        if pe.is_profane(text) and checks["Extralist"]:
            is_bad = True
            caught.append("Extralist")

            finished_message = pe.censor(finished_message, neighbors=2)
            
        # profanity longlist
        if pl.is_profane(text) and checks["Longlist"]:
            is_bad = True
            caught.append("Longlist")

            finished_message = pl.censor(finished_message, neighbors=1)

        return (finished_message, is_bad, caught)

class BreezeExtensionAPI(): # For extensions to use to interact with Breeze
    class _EventBus:
        def __init__(self, logger: endstone.Logger):
            self.listeners = {}
            self.logger = logger

        def on(self, event_name, func):
            self.listeners.setdefault(event_name, []).append(func)

        def _emit(self, event_name, *args, **kwargs):
            for func in list(self.listeners.get(event_name, [])):
                try:
                    if inspect.iscoroutinefunction(func):
                        asyncio.run(func(*args, **kwargs))
                    else:
                        func(*args, **kwargs)
                except Exception as e:
                    self.logger.error(f"Error in event listener for {event_name}: {e}")
                self.logger.info(f"[BreezeExtensionAPI] Emitted to {str(func)}")

    class HandlerInput(TypedDict):
        message: str
        player: endstone.Player
        chat_format: str
        recipients: list[endstone.Player]

    class HandlerOutput(TypedDict):
        """
        message (str): The processed message to be sent.
        fully_cancel_message (bool): Wether to fully cancel the message. (i.e. not send anything)
        finished_message (str): The final message after processing. (e.g. "[tag] <player> i #### you!")
        original_message (str): The original message before processing. (e.g. "[tag] <player> i hate you!")
        """
        is_bad: bool
        fully_cancel_message: bool
        finished_message: str
        original_message: str

    def __init__(self, logger: endstone.Logger, pdm: "PlayerDataManager | None" = None, btp: "BreezeTextProcessing | None" = None):
        self.plugin = None
        self.ready = False
        self.logger = logger

        self.pdm = pdm
        self.btp = btp

        self._event_bus = self._EventBus(logger)

    @property
    def eventbus(self):
        return self._event_bus

    def on_breeze_chat_event(self, event:PlayerChatEvent, plugin):
        """Called when a chat event is processed by Breeze. 
        
        Extensions can hook into this to do extra functions but they can NOT modify management."""
        if not self.ready:
            return

        self._event_bus._emit("on_breeze_chat_event", event, plugin); self.logger.info("[BreezeExtensionAPI] on_breeze_chat_event")

        return event, plugin

    def on_breeze_chat_processed(self, event:PlayerChatEvent, handler_output: "BreezeExtensionAPI.HandlerOutput", is_bad:bool, plugin:Plugin):
        """Called after Breeze has processed a chat event. Breeze is a dictionary of values from Breeze's message evaluation and stuff. 
        
        Extensions can hook into this to do extra functions but they can NOT modify management."""
        if not self.ready:
            return

        self._event_bus._emit("on_breeze_chat_processed", event, handler_output, is_bad, plugin); self.logger.info("[BreezeExtensionAPI] on_breeze_chat_processed")

        return event, handler_output, is_bad, plugin
    
    def initialize(self, plugin_instance: Plugin):
        self.plugin = plugin_instance
        self.ready = True

class BreezeModuleManager():
    """internal infrasturcture for managing Breeze modules like extensions and handlers"""
    bea: BreezeExtensionAPI
    pdm: PlayerDataManager
    btp: BreezeTextProcessing

    class HandlerState(Enum):
            NONE = 0
            DEFAULT = 1
            CUSTOM = 2

    def __init__(self, logger: endstone.Logger, pdm: PlayerDataManager, btp: BreezeTextProcessing, use_cwd_for_extra=False):
        self.use_cwd_for_extra = use_cwd_for_extra
        self.is_breeze_installed = False
        self.breeze_installation_path = None
        self.extension_files = []
        self.logger = logger
        self.pdm = pdm
        self.btp = btp
        
        self.handler_state = self.HandlerState.NONE
        self.handler = None

    def _default_handler(self, handler_input: BreezeExtensionAPI.HandlerInput, player_data_manager: PlayerDataManager, breeze_text_processing: BreezeTextProcessing) -> BreezeExtensionAPI.HandlerOutput:
        sender_uuid = str(handler_input["player"].unique_id)
        finished_message = handler_input["message"]

        local_player_data = player_data_manager.get_player_data(handler_input["player"].name)
        is_bad = False
        fully_cancel_message = (False, "")
        caught = []
        should_check_message = True
        worthy_to_log = False

        # spam check
        if time.monotonic() - local_player_data["latest_time_a_message_was_sent"] < 0.5:
            fully_cancel_message = (True, "spam, gave displayed cancel")
            should_check_message = False
            handler_input["player"].send_message("You're sending messages too fast!")

        if fully_cancel_message[0]:
            should_check_message = False
        
        if should_check_message: 
            finished_message, is_bad, caught = breeze_text_processing.check_and_censor(handler_input["message"])

        # finally, after checking send the message and some extra stuff
        if is_bad:
            worthy_to_log = True

        if not fully_cancel_message[0]:
            pass
        else:
            if randint(1, 3) == 1:
                worthy_to_log = True

        player_data_manager.update_player_data(handler_input["player"].name, handler_input["message"])

        return {
            "is_bad": is_bad,
            "fully_cancel_message": fully_cancel_message[0],
            "finished_message": finished_message,
            "original_message": handler_input["message"]
        }
            
    def _install_breeze(self, path: Path):
        self.breeze_installation_path = Path(path).resolve()

        if not path.is_dir():
            os.makedirs(path / "extensions", exist_ok=True)
            os.makedirs(path / "types", exist_ok=True)
            self.is_breeze_installed = True
        else:
            os.makedirs(path / "extensions", exist_ok=True)
            os.makedirs(path / "types", exist_ok=True)
            self.is_breeze_installed = True

        try:
            # import & write resource files
            resource_files = files("endstone_breeze").joinpath("resources")
            
            types_pyi_content = resource_files.joinpath("types.pyi").read_text()
            types_output_path = self.breeze_installation_path / "types" / "types.pyi"
            
            with open(types_output_path, "w") as f:
                f.write(types_pyi_content)
            
            self.logger.info(f"[BreezeModuleManager] Installed types.pyi to {types_output_path}")
            
            init_pyi_content = resource_files.joinpath("__init__.pyi").read_text()
            init_output_path = self.breeze_installation_path / "extensions" / "__init__.pyi"
            
            with open(init_output_path, "w") as f:
                f.write(init_pyi_content)
            
            self.logger.info(f"[BreezeModuleManager] Installed __init__.pyi to {init_output_path}")
        except Exception as e:
            self.logger.error(f"[BreezeModuleManager] Failed to install type resources: {e}")

            
    def _find_extensions(self):
        if self.is_breeze_installed and self.breeze_installation_path is not None:
            extensions_path = self.breeze_installation_path / "extensions"
            extension_files = [f for f in os.listdir(extensions_path) if Path(f).suffix == ".py" and not f.startswith("__") and not Path(f).suffix == ".pyi"]

            if "handler.py" in extension_files:
                module_name = "handler"
                handler_path = extensions_path / "handler.py"
                handler_func = None
                extension_files.remove("handler.py")

                self.logger.info(f"[BreezeModuleManager] Found a custom handler...")

                spec = importlib.util.spec_from_file_location(module_name, handler_path)
                if spec is None or spec.loader is None:
                    self.logger.error("[BreezeModuleManager] Failed to create spec for handler.py")
                    return
                    
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                handler_func = getattr(module, "handler", None)

                if handler_func is None:
                    self.logger.warning("[BreezeModuleManager] Custom handler found but no 'handler' function defined. Falling back to the default handler.")
                    self.handler_state = self.HandlerState.NONE
                    self.handler = self._default_handler
                else:
                    self.logger.info("[BreezeModuleManager] The custom handler will now override Breeze's default handler.")
                    self.handler_state = self.HandlerState.CUSTOM
                    self.handler = handler_func
            else:
                self.handler = self._default_handler
                self.handler_state = self.HandlerState.DEFAULT

            self.logger.info(f"[BreezeModuleManager] Found {len(extension_files)} extensions in {extensions_path}: {extension_files}")
            # later on, we can load these extensions dynamically
            self.extension_files = extension_files

    def _load_extension(self, extension_filename: str):
        if not self.is_breeze_installed or self.breeze_installation_path is None:
            self.logger.warning("BreezeModuleManager: Cannot load extension because Breeze is not installed.")
            return
    
        ext_path = self.breeze_installation_path / "extensions" / extension_filename
        if not ext_path.is_file():
            self.logger.error(f"BreezeModuleManager: Extension file not found: {ext_path}")
            return

        module_name = extension_filename.removesuffix(".py")

        try:
            spec = importlib.util.spec_from_file_location(module_name, str(ext_path))
            if spec is None or spec.loader is None:
                self.logger.error(f"BreezeModuleManager: Failed to create spec for {module_name}")
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            self.logger.info(f"BreezeModuleManager: Loaded extension module: {module_name}")

            if hasattr(module, "on_load"):
                try:
                    # pdm and btp re-passed for extensions if they use BreezeExtensionAPI
                    module.on_load(BreezeExtensionAPI(self.logger, self.pdm, self.btp)) 
                    self.logger.info(f"BreezeModuleManager: Extension {module_name} initialized via on_load()")
                except Exception as e:
                    self.logger.error(f"BreezeModuleManager: Error in on_load() of {module_name}: {e}")
            else:
                self.logger.warning(f"BreezeModuleManager: Extension {module_name} has no on_load() function.")

        except Exception as e:
            self.logger.error(f"BreezeModuleManager: Failed to load extension {extension_filename}: {e}")

    def start(self, path):
        self._install_breeze(path)

        # Extensions
        if self.is_breeze_installed:
            self._find_extensions()
            for extension_file in self.extension_files:
                self.logger.info(f"[BreezeModuleManager] Loading extension: {extension_file}")
                self._load_extension(extension_file)
        else:
            self.logger.error("[BreezeModuleManager] Features like extensions will NOT be loaded because Breeze is not installed.")

        # Handler
        if self.handler_state == self.HandlerState.NONE:
            self.logger.warning("[BreezeModuleManager] No handler was loaded! Loading in the default handler instead...")
            self.handler_state = self.HandlerState.DEFAULT

        if self.handler_state == self.HandlerState.DEFAULT:
            pass
        else:
            self.logger.info("[BreezeModuleManager] Using custom handler.") 

class Breeze(Plugin): #PLUGIN
    bea: BreezeExtensionAPI
    bmm: BreezeModuleManager
    pdm: PlayerDataManager
    btp: BreezeTextProcessing

    def on_enable(self) -> None:
        self.logger.info("Enabling Breeze")
        self.installation_path = Path(self.data_folder).resolve()
        self.register_events(self)
        current_directory = os.getcwd()
        self.server.logger.info(f"{current_directory}, {__file__}")

        # pdm and btp are re-passed to the extension API
        self.logger.info('extensionapiing'); self.bea = BreezeExtensionAPI(self.logger, pdm=self.pdm, btp=self.btp); self.bea.initialize(self)

        self.logger.info('modulemanagering'); self.bmm = BreezeModuleManager(logger=self.logger, pdm=self.pdm, btp=self.btp); self.bmm.start(self.installation_path)

        

    def __init__(self):
        super().__init__()
        self.pdm = PlayerDataManager()
        self.btp = BreezeTextProcessing()

    def handle(self, handler_input: BreezeExtensionAPI.HandlerInput) -> BreezeExtensionAPI.HandlerOutput:
        raw = None
        try:
            if self.bmm.handler is None:
                self.logger.warning("No handler found, using default handler")
                raw = self.bmm._default_handler(handler_input=handler_input, player_data_manager=self.pdm, breeze_text_processing=self.btp)
            else:
                raw = self.bmm.handler(handler_input=handler_input, player_data_manager=self.pdm, breeze_text_processing=self.btp)
        except Exception as e:
            self.logger.error(f"Exception while handling message: {e}")
            raw = self.bmm._default_handler(handler_input=handler_input, player_data_manager=self.pdm, breeze_text_processing=self.btp)
        
        if not isinstance(raw, dict):
            self.logger.warning("handler returned non-dict, falling back to default")
            raw = self.bmm._default_handler(handler_input=handler_input, player_data_manager=self.pdm, breeze_text_processing=self.btp)

        for key in ["is_bad", "fully_cancel_message", "finished_message", "original_message"]:
            if key not in raw:
                self.logger.warning(f"handler output missing key '{key}', filling default")
                raw[key] = None  # or some sane default
        
        return cast(BreezeExtensionAPI.HandlerOutput, raw)
    
    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent):
        player = event.player
        self.pdm.remove_player_data(player.name)

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent):
        pdata = self.pdm.get_player_data(event.player.name)
        pdata["latest_time_a_message_was_sent"] = time.monotonic() - 10
        pdata["last_message"] = ""
      
    @event_handler(priority=EventPriority(1))
    def on_chat_sent_by_player(self, event: PlayerChatEvent):
        event.cancel()
        self.bea.eventbus._emit("on_breeze_chat_event", event, self)

        h_input: BreezeExtensionAPI.HandlerInput = {
            "message": event.message,
            "player": event.player,
            "chat_format": event.format,
            "recipients": event.recipients
        }

        handled = self.handle(h_input)

        self.bea.eventbus._emit("on_breeze_chat_processed", event, handled, handled["is_bad"], self)

        if handled["fully_cancel_message"]:
            return
        self.server.broadcast_message(f"<{event.player.name}> {handled["finished_message"]}")