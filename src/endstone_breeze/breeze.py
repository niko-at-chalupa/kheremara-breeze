from endstone import ColorFormat
from endstone.event import event_handler, PlayerJoinEvent, PlayerChatEvent, PlayerQuitEvent, EventPriority
from endstone.plugin import Plugin

from .utils.profanity_utils import ProfanityCheck, ProfanityLonglist, ProfanityExtralist
# pc, pl, pe are okay as common abbreviations in this context
pc = ProfanityCheck()
pl = ProfanityLonglist()
pe = ProfanityExtralist()
from .utils.detox_utils import detoxify_text, round_and_dict_to_list, is_toxic_text
from .utils.general_utils import to_hash_mask, split_into_tokens

from enum import Enum
from random import randint
import os, time, asyncio, inspect, importlib.util, sys, threading
from collections import defaultdict
from pathlib import Path

def is_kherimoya_environment() -> bool: # simply checks if the four folders Kherimoya makes upon creating a server are present. The reason why we check for JUST the folders, is so that people can make Kherimoya-like environments by just making the folders themselves.
    kherimoya_paths = ['../state','../server','../extra','../config']
    for path_str in kherimoya_paths:
        if not Path(path_str).is_dir():
            return False
    return True

class PlayerDataManager:
    def __init__(self):
        self.player_data = defaultdict(lambda: {
            "latest_time_a_message_was_sent": time.monotonic() - 10,  # Allow immediate first message
            "last_message": ""
        })
    
    def update_player_data(self, name, message):
        self.player_data[name]["latest_time_a_message_was_sent"] = time.monotonic()
        self.player_data[name]["last_message"] = message

    def get_player_data(self, name):
        return self.player_data[name]

    def remove_player_data(self, name):
        if name in self.player_data:
            del self.player_data[name]

class BreezeTextProcessing:
    def check_and_censor(self, text: str, checks: dict | None = None) -> tuple[str, bool, list]:
        finished_message = text
        defaults = {
            "Detoxify": True,
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

        # detoxify
        if is_toxic_text(round_and_dict_to_list(detoxify_text(text, 'multilingual'))) and checks["Detoxify"]:
            is_bad = True
            caught.append("Detoxify")
            finished_message = to_hash_mask(text)

            return (finished_message, is_bad, caught)
        
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
        def __init__(self, logger: Plugin.logger):
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

    class HandlerInput:
        def __init__(self):
            pass
    
    def __init__(self, logger: Plugin.logger, pdm: PlayerDataManager, btp: BreezeTextProcessing): # pdm, btp re-added
        self.plugin = None
        self.ready = False
        self.logger = logger

        self.pdm = pdm # added back
        self.btp = btp # added back

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
        
    def on_breeze_chat_processed(self, event:PlayerChatEvent, handler, is_bad:bool, plugin:Plugin):
        """Called after Breeze has processed a chat event. Breeze is a dictionary of values from Breeze's message evaluation and stuff. 
        
        Extensions can hook into this to do extra functions but they can NOT modify management."""
        if not self.ready:
            return

        self._event_bus._emit("on_breeze_chat_processed", event, handler, is_bad, plugin); self.logger.info("[BreezeExtensionAPI] on_breeze_chat_processed")

        return event, handler, is_bad, plugin

    def initialize(self, plugin_instance: Plugin):
        self.plugin = plugin_instance
        self.ready = True


class BreezeModuleManager():
    class HandlerState(Enum):
            NONE = 0
            DEFAULT = 1
            CUSTOM = 2

    def __init__(self, logger: Plugin.logger, use_cwd_for_extra=False):
        self.is_kherimoya = is_kherimoya_environment()
        self.use_cwd_for_extra = use_cwd_for_extra
        self.is_breeze_installed = False
        self.breeze_installation_path = None
        self.extension_files = []
        self.logger = logger
        
        self.handler_state = self.HandlerState.NONE
        self.handler = None

    def _default_handler(self, plugin:Plugin, event:PlayerChatEvent):
        plugin.bea.on_breeze_chat_event(event, plugin)

        sender_uuid = str(event.player.unique_id)
        finished_message = event.message

        event.cancel()

        local_player_data = plugin.pdm.get_player_data(event.player.name)
        is_bad = None
        fully_cancel_message = (False, "")
        caught = []
        should_check_message = True
        worthy_to_log = False

        # spam check
        if time.monotonic() - local_player_data["latest_time_a_message_was_sent"] < 0.5:
            fully_cancel_message = (True, "spam, gave displayed cancel")
            should_check_message = False
            event.player.send_message("You're sending messages too fast!")

        if fully_cancel_message[0]:
            should_check_message = False
        
        if should_check_message: 
            finished_message, is_bad, caught = plugin.btp.check_and_censor(event.message)

        # finally, after checking send the message and some extra stuff
        if is_bad:
            worthy_to_log = True

        if not fully_cancel_message[0]:
            plugin.server.broadcast_message(f"<{event.player.name}> {finished_message}")
        else:
            if randint(1, 3) == 1:
                worthy_to_log = True

        plugin.pdm.update_player_data(event.player.name, event.message)

        plugin.bea.on_breeze_chat_processed(event, {
            "is_bad": is_bad,
            "fully_cancel_message": fully_cancel_message,
            "should_check_message": should_check_message,
            "caught": caught,
            "finished_message": finished_message,
            "worthy_to_log": worthy_to_log,
            "sender_uuid": sender_uuid,
            "sender_name": event.player.name,
            "original_message": event.message
        }, is_bad, plugin)
        
        if worthy_to_log:
            plugin.logger.info(f"""\n
    --- BREEZE LOG OF MESSAGE FROM {sender_uuid} / {event.player.name} ---
    message
    | is_bad = {ColorFormat.BLUE}{is_bad}{ColorFormat.RESET}
    | fully_cancel_message = {ColorFormat.BLUE}{fully_cancel_message}{ColorFormat.RESET}
    | should_check_message = {ColorFormat.BLUE}{should_check_message}{ColorFormat.RESET}

    censoring
    | tokens = {ColorFormat.BLUE}{split_into_tokens(event.message)}{ColorFormat.RESET}
    | caught = {ColorFormat.BLUE}{caught}{ColorFormat.RESET}
    
    input) {ColorFormat.BLUE}{event.message}{ColorFormat.RESET}
    output) {ColorFormat.BLUE}{finished_message}{ColorFormat.RESET}\n
    --- END OF LOG ---
        """)
            
    def _initialize_kherimoya(self):
        if self.is_kherimoya:
            path_str = "../extra/breeze/"
            self.breeze_installation_path = Path(path_str).resolve()
            
            if not Path(path_str).is_dir():
                os.makedirs(Path(path_str) / "extensions", exist_ok=True)
                self.is_breeze_installed = True
            else:
                self.is_breeze_installed = True
                
            print(f"{ColorFormat.LIGHT_PURPLE}Breeze was installed from the Kherimoya path: {path_str}. REMEMBER THIS!!")
        elif self.use_cwd_for_extra:
            cwd_extra_path_str = "./extra/breeze/"
            if not Path(cwd_extra_path_str).is_dir():
                if Path(os.getcwd()) == Path.home():
                    self.logger.warning("BreezeModuleManager: Hey! You're running the server from your home directory, so Breeze will not create the extra/breeze/ folder here for safety reasons. Please run the server from a different directory if you want to use Breeze's extra features.")
                    return
                os.makedirs(Path(cwd_extra_path_str) / "extensions", exist_ok=True)
                self.is_breeze_installed = True
            else:
                self.is_breeze_installed = True
    
            self.breeze_installation_path = Path(cwd_extra_path_str).resolve()
            self.logger.info(f"{ColorFormat.LIGHT_PURPLE}Breeze was installed from the CWD path: {self.breeze_installation_path}. REMEMBER THIS!!")
        
        if self.is_breeze_installed:
            pass
        else:
            self.logger.error("BreezeModuleManager: We're likely not in a Kherimoya-like environment, so extensions and other stuff will not be loaded.")

    def _find_extensions(self):
        if self.is_breeze_installed:
            extensions_path = self.breeze_installation_path / "extensions"
            extension_files = [f for f in os.listdir(extensions_path) if Path(f).suffix == ".py"]

            if "handler.py" in extension_files:
                module_name = "handler"
                handler_path = extensions_path / "handler.py"
                handler_func = None
                extension_files.remove("handler.py")

                self.logger.info(f"[BreezeModuleManager] Found a custom handler...")

                spec = importlib.util.spec_from_file_location(module_name, handler_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # function inside handler.py should be named "handler" or whatever you expect
                handler_func = getattr(module, "handler", None)

                extension_files.remove("handler.py")

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
        if not self.is_breeze_installed:
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

    def start(self):
        self._initialize_kherimoya()

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
            self.logger.warn("[BreezeModuleManager] No handler was loaded! Loading in the default handler instead...")
            self.handler_state = self.HandlerState.DEFAULT

        if self.handler_state == self.HandlerState.DEFAULT:
            self.logger.info("[BreezeModuleManager] We're using Breeze's basic, default handler...")
        else:
            self.logger.info 


class Breeze(Plugin): #PLUGIN
    def on_enable(self) -> None:
        self.logger.info("Enabling Breeze")
        self.register_events(self)
        current_directory = os.getcwd()
        self.server.logger.info(f"{current_directory}, {__file__}")

        # pdm and btp are re-passed to the extension API
        self.logger.info('extensionapiing'); self.bea = BreezeExtensionAPI(self.logger, pdm=self.pdm, btp=self.btp); self.bea.initialize(self)

        self.logger.info('modulemanagering'); self.bmm = BreezeModuleManager(logger=self.logger); self.bmm.start()

        self.is_kherimoya = is_kherimoya_environment()

        if self.is_kherimoya:
            self.logger.info('Full Kherimoya(-like) environment detected! All features are ready!')
        elif self.bmm.use_cwd_for_extra and self.bmm.is_breeze_installed:
            self.logger.info('Breeze was properly installed in the current working directory!! All features ready!')
        else:
            self.logger.warning("Breeze was not installed.")

    def __init__(self):
        super().__init__()
        self.pdm = PlayerDataManager()
        self.btp = BreezeTextProcessing()

    def handle(self, event):
        if not self.bmm.handler == None:
            try:
                self.bmm.handler(plugin=self, event=event)
            except Exception as e:
                self.logger.error(f"Exception while handling message, falling back to default handler: {e}")
                self.bmm._default_handler(plugin=self, event=event)

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
        threading.Thread(target=self.handle, args=(event,)).start()