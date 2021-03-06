# This code was originally taken from https://github.com/zeuxisoo/python-pluginplot
import asyncio
import imp
import os
import sys
import threading
import traceback
from os.path import isfile

import hues
import types

try:
    from settings import TOKEN, LOGIN, PASSWORD
except ImportError:
    TOKEN, LOGIN, PASSWORD = None, None, None


class Plugin(object):
    def __init__(self, name: str = "Example", usage: list = None):
        self.deferred_events = []  # события, на которые подписан плагин
        self.scheduled_funcs = []
        self.name = name
        if usage is None:
            usage = []
        if isinstance(usage, str):
            usage = [usage]
        self.usage = usage
        self.first_command = ''
        hues.warn(self.name)

    def log(self, message: str):
        hues.info(f'Плагин {self.name} -> {message}')

    def schedule(self, seconds):
        def decor(func):
            async def wrapper(*args, **kwargs):
                while True:
                    # Спим указанное кол-во секунд
                    # При этом другие корутины могут работать
                    await asyncio.sleep(seconds)
                    # Выполняем саму функцию
                    await func(*args, **kwargs)

            return wrapper

        return decor

    # Декоратор события (запускается при первом запуске)
    def on_command(self, *commands, all_commands=False, group=True):
        def wrapper(func):
            if TOKEN and not group:
                # Если бот работает от токена, и плагин не работает от имени группы
                # мы не добавляем эту команду
                # Убираем usage, чтобы команда не отображалась в помощи
                self.usage = []
                return func
            if commands:  # Если написали, какие команды используются
                # Первая команда - отображается в списке команд (чтобы не было много команд не было)
                self.first_command = commands[0]
                # Если хоть в 1 команде есть пробел - она состоит из двух слов
                if any(' ' in cmd.strip() for cmd in commands):
                    hues.error(f'В плагине {self.name} была '
                               'использована команда из двух слов')
                for command in commands:
                    self.add_func(command, func)
            elif not all_commands:  # Если нет - используем имя плагина в качестве команды (в нижнем регистре)
                self.add_func(self.name.lower(), func)
            # Если нужно, реагируем на все команды
            else:
                self.add_func('', func)
            return func

        return wrapper

    def add_func(self, command, func):
        if command is None:
            raise ValueError("Command can not be None")

        def event(system: PluginSystem):
            system.add_command(command, func)

        self.deferred_events.append(event)

    # Register events for plugin
    def register(self, system):
        for deferred_event in self.deferred_events:
            deferred_event(system)
        system.scheduled_events += self.scheduled_funcs


local_data = threading.local()

shared_space = types.ModuleType(__name__ + '.shared_space')
shared_space.__path__ = []
sys.modules[shared_space.__name__] = shared_space


class PluginSystem(object):
    def __init__(self, folder=None):
        self.commands = {}
        self.any_commands = []
        self.folder = folder
        self.plugins = set()
        self.scheduled_events = []

    def get_plugins(self) -> set:
        return self.plugins

    def add_command(self, name, func):
        if name == '':
            self.any_commands.append(name)
            return
        # если уже есть хоть 1 команда, добавляем к списку
        if name in self.commands:
            self.commands[name].append(func)
        # если нет, создаём новый кортеж
        else:
            self.commands[name] = [func]

    async def call_command(self, command_name: str, *args, **kwargs):
        # Получаем функции команд для этой команды
        # Несколько плагинов МОГУТ обрабатывать одну команду

        commands_ = self.commands.get(command_name)

        if not commands_:
            # Если нет функций, которые могут обработать команду
            # То выполняем функции с all_commands=True
            for func in self.any_commands:
                await func(*args, **kwargs)

        # Если есть плагины, которые могут обработать нашу команду
        for command_function in commands_:
            await command_function(*args, **kwargs)

    def register_plugin(self, plugin_object: Plugin):
        plugin_object.register(self)

    def register_commands(self):
        if not self.folder:
            raise ValueError("Plugin.folder can not be None")
        else:
            self._init_plugin_files()

    def _init_plugin_files(self):
        for folder_path, folder_names, filenames in os.walk(self.folder):
            for filename in filenames:
                if filename.endswith('.py') and filename != "__init__.py":
                    # path/to/plugins/plugin/foo.py
                    # > plugin/foo.py
                    # > plugin.foo
                    # > shared_space.plugin.foo
                    full_plugin_path = os.path.join(folder_path, filename)
                    base_plugin_path = os.path.relpath(full_plugin_path, self.folder)
                    base_plugin_name = os.path.splitext(base_plugin_path)[0].replace(os.path.sep, '.')
                    module_source_name = "{0}.file_{1}".format(shared_space.__name__, base_plugin_name)
                    try:
                        loaded_module = imp.load_module(
                            module_source_name,
                            *imp.find_module(os.path.splitext(filename)[0], [folder_path])
                        )
                    # Если при загрузке плагина произошла какая-либо ошибка
                    except Exception:
                        result = traceback.format_exc()
                        # если файла нет - создаём
                        if not isfile('log.txt'):
                            open('log.txt', 'w').close()

                        with open('log.txt', 'a') as log:
                            log.write(result)
                        continue
                    try:
                        self.plugins.add(loaded_module.plugin)
                        self.register_plugin(loaded_module.plugin)
                    # Если возникла ошибка - значит плагин не имеет атрибута plugin
                    except AttributeError:
                        continue

    def __enter__(self):
        local_data.plugin_stacks = [self]
        return self

    def __exit__(self, exc_type, exc_value, tbc):
        try:
            local_data.plugin_stacks.pop()
        except Exception:
            pass
