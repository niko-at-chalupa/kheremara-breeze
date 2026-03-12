from endstone import ColorFormat
from endstone.command import Command, CommandSender
from endstone.event import (
    event_handler,
    PlayerJoinEvent,
    PlayerChatEvent,
    PlayerQuitEvent,
    EventPriority,
    PlayerCommandEvent,
)
import concurrent.futures
from typing import Awaitable, Optional
from endstone.plugin import Plugin
import endstone
from importlib.resources import files
from .utils.profanity_utils import ProfanityCheck, ProfanityList, ProfanityExtraList
from .utils.general_utils import to_hash_mask, split_into_tokens
from enum import Enum
from random import randint
import os
import time
import inspect
import importlib.util
import sys
from collections import defaultdict
from pathlib import Path
from typing import TypedDict, cast, Callable
import yaml
from endstone import asyncio
import typing

_T = typing.TypeVar("_T")

pc = ProfanityCheck()
pl = ProfanityList()
pe = ProfanityExtraList()


class PlayerData(TypedDict):
    latest_time_a_message_was_sent: float
    last_message: str


class PlayerDataManager:
    player_data: defaultdict[str, PlayerData]

    def __init__(self):
        self.player_data = defaultdict(
            lambda: cast(
                PlayerData,
                {
                    "latest_time_a_message_was_sent": time.monotonic() - 10,
                    "last_message": "",
                },
            )
        )

    def update_player_data(self, name, message) -> None:
        self.player_data[name]["latest_time_a_message_was_sent"] = time.monotonic()
        self.player_data[name]["last_message"] = message

    def get_player_data(self, name) -> PlayerData:
        return self.player_data[name]

    def remove_player_data(self, name) -> None:
        if name in self.player_data:
            del self.player_data[name]


class BreezeTextProcessing:
    def censor_with_word_list(
        self,
        text: str,
        word_list: set[str],
        allowed_words_list: set[str] = set(),
        replacement_char: str = "#",
    ) -> tuple[str, bool]:
        """
        Censors a given text with a custom word list.

        Args:
            text (str): The text to censor
        Returns:
            tuple[str, bool]: A tuple containing:
                - The censored text (str)
                - Boolean indicating if any profanity was found (bool)
        """

        finished_message = text
        is_bad = False

        if pe.is_profane(finished_message, word_list=word_list):
            is_bad = True
            finished_message = pe.censor(
                text,
                replacement=replacement_char,
                word_list=word_list,
                allowed_words_list=allowed_words_list,
            )

        if pl.is_profane(finished_message, word_list=word_list):
            is_bad = True
            finished_message = pl.censor(
                text,
                replacement=replacement_char,
                word_list=word_list,
                allowed_words_list=allowed_words_list,
            )

        return (finished_message, is_bad)

    def mask_text(self, text: str):
        """
        Masks text by replacing each alphabetical character into a '#' *(or other char, is specified)*
        """
        return to_hash_mask(text)

    def check_and_censor(
        self, text: str, checks: dict | None = None
    ) -> tuple[str, bool, list]:
        """
        Checks and censors a given text with multiple profanity checkers. You can not customize its wordlist

        Args:
            text (str): The text to check and censor
            checks (dict | None, optional): A dictionary specifying which checks to perform. Defaults to None. The possible keys are:
                - "Profanity-check" (bool): Whether to use the basic profanity check
                - "Extralist" (bool): Whether to use the extralist profanity check
                - "Longlist" (bool): Whether to use the longlist profanity check (only censors misspellings of bad words)
        Returns:
            tuple[str, bool, list]: A tuple containing:
                - The censored text (str)
                - A boolean indicating if any profanity was found (bool)
                - A list of the checks that caught profanity (list)
        """
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


class BreezeModuleManager:
    """internal infrasturcture for managing Breeze modules like extensions and handlers"""

    pdm: PlayerDataManager
    btp: BreezeTextProcessing
    extension_files: list[str]

    class HandlerState(Enum):
        NONE = 0
        DEFAULT = 1
        CUSTOM = 2

    def __init__(self, logger: endstone.Logger, pdm: PlayerDataManager, btp: BreezeTextProcessing, plugin: "Breeze"):
        self.is_breeze_installed = False
        self.breeze_installation_path = None
        self.extension_files = []
        self.logger = logger
        self.pdm = pdm
        self.btp = btp

        self.plugin = plugin
        
        self.handler_state = self.HandlerState.NONE
        self.handler = None

    def _default_handler(
        self,
        handler_input: "BreezeExtensionAPI.HandlerInput",
        player_data_manager: PlayerDataManager,
        breeze_text_processing: BreezeTextProcessing,
        handler_api: "BreezeHandlerAPI | None" = None
    ) -> "BreezeExtensionAPI.HandlerOutput":
        finished_message = handler_input["message"]

        local_player_data = player_data_manager.get_player_data(
            handler_input["player"].name
        )
        is_bad = False
        fully_cancel_message = (False, "")
        should_check_message = True

        # spam check
        if time.monotonic() - local_player_data["latest_time_a_message_was_sent"] < 0.5:
            fully_cancel_message = (True, "spam, gave displayed cancel")
            should_check_message = False
            handler_input["player"].send_message("You're sending messages too fast!")

        if fully_cancel_message[0]:
            should_check_message = False

        if should_check_message:
            finished_message, is_bad, _ = breeze_text_processing.check_and_censor(
                handler_input["message"]
            )

        player_data_manager.update_player_data(
            handler_input["player"].name, handler_input["message"]
        )

        return {
            "is_bad": is_bad,
            "fully_cancel_message": fully_cancel_message[0],
            "finished_message": finished_message,
            "original_message": handler_input["message"],
        }

    def _install_breeze(self, path: Path):
        self.breeze_installation_path = Path(path).resolve()

        os.makedirs(path / "extensions" / "handlers", exist_ok=True)
        os.makedirs(path / "types", exist_ok=True)
        os.makedirs(path / "storage", exist_ok=True)
        self.is_breeze_installed = True

        try:  # write resource files
            resource_files = files("endstone_breeze").joinpath("resources")

            types_pyi_content = resource_files.joinpath("types.pyi").read_text()
            types_output_path = self.breeze_installation_path / "types" / "types.pyi"

            with open(types_output_path, "w") as f:
                f.write(types_pyi_content)

            init_pyi_content = resource_files.joinpath("__init__.pyi").read_text()
            init_output_path = (
                self.breeze_installation_path / "extensions" / "__init__.pyi"
            )

            with open(init_output_path, "w") as f:
                f.write(init_pyi_content)

            handlers_init_pyi_content = (
                resource_files.joinpath("handlers").joinpath("__init__.pyi").read_text()
            )
            handlers_init_output_path = (
                self.breeze_installation_path
                / "extensions"
                / "handlers"
                / "__init__.pyi"
            )

            with open(handlers_init_output_path, "w") as f:
                f.write(handlers_init_pyi_content)
        except Exception as e:
            self.logger.error(
                f"[BreezeModuleManager] Failed to install type resources: {e}"
            )

        if not Path(self.breeze_installation_path / "config.yaml").resolve().is_file():
            try:  # write default config
                resource_files = files("endstone_breeze").joinpath("resources")

                default_config_content = resource_files.joinpath(
                    "config.yaml"
                ).read_text()
                config_output_path = self.breeze_installation_path / "config.yaml"

                with open(config_output_path, "w") as f:
                    f.write(default_config_content)

                self.logger.info("[BreezeModuleManager] Installed config successfully")
            except Exception as e:
                self.logger.error(
                    f"[BreezeModuleManager] Failed to install config: {e}"
                )

        with open(self.breeze_installation_path / "config.yaml", "r") as f:
            breeze_config = yaml.safe_load(f)

        self._breeze_config = breeze_config

        try:  # write handlers
            resource_files = (
                files("endstone_breeze").joinpath("resources").joinpath("handlers")
            )
            default_handler_content = resource_files.joinpath(
                "default_handler.py"
            ).read_text()

            default_handler_output_path = (
                self.breeze_installation_path
                / "extensions"
                / "handlers"
                / "default_handler.py"
            )

            with open(default_handler_output_path, "w") as f:
                f.write(default_handler_content)
        except Exception as e:
            self.logger.error(f"[BreezeModuleManager] Failed to install handlers: {e}")
            self.plugin.set_load_failed()
            
    def _find_extensions(self):
        if self.is_breeze_installed and self.breeze_installation_path is not None:
            extensions_path = self.breeze_installation_path / "extensions"
            extension_files = [
                f
                for f in os.listdir(extensions_path)
                if Path(f).suffix == ".py"
                and not f.startswith("__")
                and not Path(f).suffix == ".pyi"
            ]

            self.logger.info(
                f"[BreezeModuleManager] Found {len(extension_files)} extensions in {extensions_path}: {extension_files}"
            )
            self.extension_files = extension_files

            handler_from_config = self._breeze_config.get("handler")
            if handler_from_config:
                handler_path = extensions_path / "handlers" / handler_from_config
                if handler_path.is_file():
                    self.logger.info(
                        f"[BreezeModuleManager] Loading handler from config: {handler_from_config}"
                    )

                    module_name = f"breeze.extensions.handlers.{handler_from_config.removesuffix('.py')}"
                    handler_func = None
                    handler_path = extensions_path / "handlers" / handler_from_config

                    spec = importlib.util.spec_from_file_location(
                        module_name, handler_path
                    )
                    if not spec:
                        self.logger.error(
                            f"[BreezeModuleManager] Failed to create spec for handler {handler_from_config}, falling back to default handler."
                        )
                        self.handler = self._default_handler
                        self.handler_state = self.HandlerState.DEFAULT
                        return
                    if not spec.loader:
                        self.logger.error(
                            f"[BreezeModuleManager] Failed to create spec for handler {handler_from_config}, falling back to default handler."
                        )
                        self.handler = self._default_handler
                        self.handler_state = self.HandlerState.DEFAULT
                        return

                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    handler_dir = str(extensions_path / "handlers") 
                    if handler_dir not in sys.path:                   
                        sys.path.insert(0, handler_dir)               
                    spec.loader.exec_module(module)
                    handler_func = getattr(module, "handler", None)

                    if handler_func is None:
                        self.logger.warning(
                            "[BreezeModuleManager] Custom handler found but no 'handler' function defined. Falling back to the default handler."
                        )
                        self.handler_state = self.HandlerState.NONE
                        self.handler = self._default_handler
                    else:
                        self.logger.info(
                            "[BreezeModuleManager] The custom handler will now override Breeze's default handler."
                        )
                        self.handler_state = self.HandlerState.CUSTOM
                        self.handler = handler_func
                else:
                    self.logger.warning(
                        f"[BreezeModuleManager] Handler from config not found: {handler_from_config}, falling back to default handler."
                    )
                    self.handler = self._default_handler
                    self.handler_state = self.HandlerState.DEFAULT
            else:
                self.logger.info(
                    "[BreezeModuleManager] No handler specified in config, falling back to default handler."
                )
                self.handler = self._default_handler
                self.handler_state = self.HandlerState.DEFAULT

    def _load_extension(self, extension_filename: str, bea: "BreezeExtensionAPI"):
        """load extension manually, must be simple str of filename and must be in extensions/ directory"""
        if not self.is_breeze_installed or self.breeze_installation_path is None:
            self.logger.warning(
                "[BreezeModuleManager] Cannot load extension because Breeze is not installed."
            )
            return

        ext_path = self.breeze_installation_path / "extensions" / extension_filename
        if not ext_path.is_file():
            self.logger.error(f"[BreezeModuleManager] Extension file not found: {ext_path}")
            self.plugin.set_load_failed()
            return

        module_name = extension_filename.removesuffix(".py")

        try:
            module_name = f"breeze.extensions.{extension_filename.removesuffix('.py')}"
            spec = importlib.util.spec_from_file_location(module_name, str(ext_path))

            if spec is None or spec.loader is None:
                self.logger.error(f"[BreezeModuleManager] Failed to create spec for {module_name}")
                self.plugin.set_load_failed()
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            self.logger.info(
                f"[BreezeModuleManager] Loaded extension module: {module_name}"
            )

            if hasattr(module, "on_load"):
                try:
                    # pdm and btp re-passed for extensions if they use BreezeExtensionAPI
                    module.on_load(bea)
                    self.logger.info(
                        f"[BreezeModuleManager] Extension {module_name} initialized via on_load()"
                    )
                except Exception as e:
                    self.logger.error(f"BreezeModuleManager: Error in on_load() of {module_name}: {e}")
                    self.plugin.set_load_failed()
            else:
                self.logger.warning(
                    f"[BreezeModuleManager] Extension {module_name} has no on_load() function."
                )

        except Exception as e:
            self.logger.error(f"[BreezeModuleManager] Failed to load extension {extension_filename}: {e}")
            self.plugin.set_load_failed()

    def start(self, path):
        self._install_breeze(path)

        # Extensions
        if self.is_breeze_installed:
            self._find_extensions()
        else:
            self.logger.error("[BreezeModuleManager] Features like extensions will NOT be loaded because Breeze is not installed.")
            self.plugin.set_load_failed()

        # Handler
        if self.handler_state == self.HandlerState.NONE:
            self.logger.warning(
                "[BreezeModuleManager] No handler was loaded! Loading in the default handler instead..."
            )
            self.handler_state = self.HandlerState.DEFAULT

        if self.handler_state == self.HandlerState.DEFAULT:
            pass
        else:
            self.logger.info("[BreezeModuleManager] Using custom handler.")


class BreezeExtensionAPI:
    """For extensions to interact with Breeze, and for Breeze to interact with extensions"""

    class _EventBus:
        def __init__(self, logger: endstone.Logger):
            self.listeners = {}
            self.logger = logger

        def on(self, event_name, func):
            self.listeners.setdefault(event_name, []).append(func)
            self.logger.debug(f"[BreezeExtensionAPI] new listener {func.__name__}")

        def _emit(self, event_name, *args, **kwargs):
            for func in list(self.listeners.get(event_name, [])):
                try:
                    if inspect.iscoroutinefunction(func):
                        asyncio.submit(func(*args, **kwargs))
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

    def __init__(
        self,
        logger: endstone.Logger,
        bmm: BreezeModuleManager,
        pdm: PlayerDataManager,
        btp: BreezeTextProcessing,
        plugin: Plugin,
    ):
        self.plugin = plugin
        self.logger = logger

        self.pdm = pdm
        self.btp = btp
        self.bmm = bmm

        self._event_bus = self._EventBus(logger)

    plugin: Plugin
    logger: endstone.Logger

    def _load_extensions(self):
        """
        Loads extensions found by BreezeModuleManager

        Should not be included in stub for extensions
        """
        for extension in self.bmm.extension_files:
            self.logger.info(f"[BreezeModuleManager] Loading extension: {extension}")
            self.bmm._load_extension(extension, self)

    @property
    def eventbus(self):
        return self._event_bus

    def on_breeze_chat_event(self, event: PlayerChatEvent, plugin):
        """Called when a chat event is processed by Breeze.

        Extensions can hook into this to do extra functions but they can NOT modify management."""

        self._event_bus._emit("on_breeze_chat_event", event, plugin)
        self.logger.info("[BreezeExtensionAPI] on_breeze_chat_event")

        return event, plugin

    def on_breeze_chat_processed(
        self,
        event: PlayerChatEvent,
        handler_output: "BreezeExtensionAPI.HandlerOutput",
        is_bad: bool,
        plugin: Plugin,
    ):
        """Called after Breeze has processed a chat event. Breeze is a dictionary of values from Breeze's message evaluation and stuff.

        Extensions can hook into this to do extra functions but they can NOT modify management."""

        self._event_bus._emit(
            "on_breeze_chat_processed", event, handler_output, is_bad, plugin
        )
        self.logger.info("[BreezeExtensionAPI] on_breeze_chat_processed")

        return event, handler_output, is_bad, plugin

    def run_task(self, task: Callable[[], None], delay: int = 0, period: int = 0):
        """Wrapper for the task scheduler's run_task method. Use this to run things in the server's thread."""

        self.plugin.server.scheduler.run_task(self.plugin, task, delay, period)

    def submit(self, coro: Awaitable[_T]) -> concurrent.futures.Future[_T]:
        """
        Submit an awaitable to the background loop, returns a concurrent.futures.Future.

        Wrapper for Endstone's asyncio.submit()
        """
        return asyncio.submit(coro)
    
class BreezeHandlerAPI:
    def __init__(self, bea: BreezeExtensionAPI):
        self._bea = bea

    def submit(self, coro: Awaitable[_T]) -> concurrent.futures.Future[_T]:
        """
        Submit an awaitable to the background loop, returns a concurrent.futures.Future.

        Wrapper for Endstone's asyncio.submit()
        """
        return self._bea.submit(coro)

    def run_task(self, task: Callable[[], None], delay: int = 0, period: int = 0):
        """Wrapper for the task scheduler's run_task method. Use this to run things in the server's thread."""
        self._bea.run_task(task, delay, period)

class Breeze(Plugin):  # PLUGIN
    def on_enable(self) -> None:
        self.logger.info("Enabling Breeze")
        self.installation_path = Path(self.data_folder).resolve()
        self.register_events(self)
        current_directory = os.getcwd()
        self.server.logger.info(f"{current_directory}, {__file__}")

        self.bmm = BreezeModuleManager(logger=self.logger, pdm=self.pdm, btp=self.btp, plugin=self); self.bmm.start(self.installation_path)
        self.bea = BreezeExtensionAPI(self.logger, pdm=self.pdm, btp=self.btp, bmm=self.bmm, plugin=self); self.bea._load_extensions() 
        self.bha = BreezeHandlerAPI(self.bea)

        self._has_load_failed = False

        with open(self.installation_path / "config.yaml", "r") as f:
            config = yaml.safe_load(f)
        self.breeze_config = config

        if config.get("use_message_handling", True) is not True:
            self.logger.info(
                "Automatic message handling is disabled, Breeze will not modify or process messages."
            )        

    def __init__(self):
        super().__init__()
        self.pdm = PlayerDataManager()
        self.btp = BreezeTextProcessing()

    def set_load_failed(self):
        """Call method to tell Breeze that plugin load has failed"""
        self.logger.error("Extension load failed!")
        self._has_load_failed = True
        if self.breeze_config.get("disable_chat_on_extension_load_error", False):
            self.server.broadcast_message(f"{ColorFormat.RED}Chat is temporarily disabled for technical reasons")
            self.logger.error("Since certain handlers, extensions may not work, and disable_chat_on_extension_load_error is set to true in the config, chat is now disabled")

    def handle(self, handler_input: BreezeExtensionAPI.HandlerInput) -> BreezeExtensionAPI.HandlerOutput:
        bha = BreezeHandlerAPI(self.bea)
        raw = None

        def call_default():
            return self.bmm._default_handler(
                handler_input=handler_input,
                player_data_manager=self.pdm,
                breeze_text_processing=self.btp,
                handler_api=bha,
            )

        try:
            if self.bmm.handler is None:
                self.logger.warning("No handler found, using default handler")
                raw = call_default()
            else:
                sig = inspect.signature(self.bmm.handler)
                if "handler_api" in sig.parameters:
                    raw = self.bmm.handler(
                        handler_input=handler_input,
                        player_data_manager=self.pdm,
                        breeze_text_processing=self.btp,
                        handler_api=bha,
                    )
                else:
                    raw = self.bmm.handler(
                        handler_input=handler_input,
                        player_data_manager=self.pdm,
                        breeze_text_processing=self.btp,
                    )
        except Exception as e:
            self.logger.error(f"Exception while handling message: {e}")
            raw = call_default()

        if not isinstance(raw, dict):
            self.logger.warning("handler returned non-dict, falling back to default")
            raw = call_default()

        for key in ["is_bad", "fully_cancel_message", "finished_message", "original_message"]:
            if key not in raw:
                self.logger.warning(f"handler output missing key '{key}', filling default")
                raw[key] = None

        return cast(BreezeExtensionAPI.HandlerOutput, raw)

    @event_handler
    def on_private_message(self, event: PlayerCommandEvent):
        if self.breeze_config.get("use_message_handling", True) is not True:
            return
        parts = event.command.split(' ', 2)
        if parts[0] in ['/msg', '/tell', '/whisper', '/w']:
            if self._has_load_failed and self.breeze_config.get("disable_chat_on_extension_load_error", False):
                event.player.send_message(f"{ColorFormat.RED}Chat is temporarily disabled for technical reasons")
                event.cancel()
                return
            # ["/msg", "recipient", "message"]
            if len(parts) < 2:
                return  # command would have errored anyways

            h_input: BreezeExtensionAPI.HandlerInput = {
                "message": parts[2] if len(parts) > 2 else "",
                "player": event.player,
                "chat_format": "",
                "recipients": [],
            }

            handled = self.handle(h_input)

            self.bea.eventbus._emit(
                "on_breeze_chat_processed", event, handled, handled["is_bad"], self
            )

            if handled["fully_cancel_message"]:
                event.cancel()
                return

            event.command = f"{parts[0]} {parts[1]} {handled['finished_message']}"

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent):
        player = event.player
        self.pdm.remove_player_data(player.name)

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent):
        pdata = self.pdm.get_player_data(event.player.name)
        pdata["latest_time_a_message_was_sent"] = time.monotonic() - 10
        pdata["last_message"] = ""
        if self._has_load_failed and self.breeze_config.get("disable_chat_on_extension_load_error", False):
            event.player.send_message(f"{ColorFormat.RED}Chat is temporarily disabled for technical reasons")
      
    @event_handler(priority=EventPriority.HIGHEST) #type: ignore
    def on_chat_sent_by_player(self, event: PlayerChatEvent):
        if self.breeze_config.get("use_message_handling", True) is not True:
            return
        event.cancel()
        if self._has_load_failed and self.breeze_config.get("disable_chat_on_extension_load_error", False):
            event.player.send_message(f"{ColorFormat.RED}Chat is temporarily disabled for technical reasons")
            return
        
        self.bea.eventbus._emit("on_breeze_chat_event", event, self)

        h_input: BreezeExtensionAPI.HandlerInput = {
            "message": event.message,
            "player": event.player,
            "chat_format": event.format,
            "recipients": event.recipients,
        }

        handled = self.handle(h_input)

        self.bea.eventbus._emit(
            "on_breeze_chat_processed", event, handled, handled["is_bad"], self
        )

        if handled["fully_cancel_message"]:
            return
        self.server.broadcast_message(
            f"<{event.player.name}> {handled['finished_message']}"
        )
