import sublime
import sublime_plugin
import os
import re
import csv
import threading
from .behaviors_data import behaviors

bfme_index = {}
bfme_strings_index = {}

bfme_pattern = re.compile(
    r"^(AudioEvent|MappedImage|Object|ChildObject|ObjectCreationList|ModifierList|FXList|FXParticleSystem|Locomotor|Upgrade|Science|StanceTemplate|CommandSet|CommandButton|Weapon|Armor|SpecialPower)\s+([\w+\-]+)",
    re.I,
)
macro_pattern = re.compile(r"^\s*#define\s+([\w+\-]+)\s+([^;]+)", re.I)
include_pattern = re.compile(r'#include\s+"([^"]+)"', re.I)
behavior_pattern = re.compile(r'^\s*Behavior\s*=\s*(\w+)', re.I)


def read_string_names(path):
    global bfme_strings_index
    bfme_strings_index.clear()
    try:
        with open(path, "r", encoding="latin-1", errors="ignore") as f:
            reader = csv.reader(f, delimiter=";")
            for i, row in enumerate(reader):
                if row:
                    name = row[0].strip().lower()
                    if name:
                        bfme_strings_index[name] = (path, i + 1, "string", tuple())
        print("[BFME Plugin] Indexed strings from {path}".format(path=path))
    except Exception as e:
        print("[BFME Plugin] Failed to read {path}: {e}".format(path=path, e=e))


def index_bfme_files(window):
    """Index all BFME symbols in the opened folders."""
    global bfme_index
    bfme_index.clear()
    folders = window.folders()

    for folder in folders:
        for root, _, files in os.walk(folder):
            for fn in files:
                fn = fn.lower()
                if fn.endswith((".ini", ".inc")) and fn != "map.ini":
                    path = os.path.join(root, fn)
                    try:
                        with open(path, "r", encoding="latin-1", errors="ignore") as f:
                            for i, line in enumerate(f):
                                m = bfme_pattern.match(line)
                                if m:
                                    kind, name = m.groups()
                                    if name in bfme_index:
                                        existing = bfme_index[name]
                                        if isinstance(existing[0], list):
                                            existing[0].append(path)
                                            existing[1].append(i + 1)
                                        else:
                                            bfme_index[name] = (
                                                [existing[0], path],
                                                [existing[1], i + 1],
                                                kind.lower(),
                                                tuple(),
                                            )
                                        print(
                                            "[BFME Plugin] Duplicate symbol found: {name} (now has {count} definitions)".format(
                                                name=name, count=len(bfme_index[name][0])
                                            )
                                        )
                                    else:
                                        bfme_index[name] = (path, i + 1, kind.lower(), tuple())

                                mm = macro_pattern.match(line)
                                if mm:
                                    macro_name = mm.group(1)
                                    if macro_name in bfme_index:
                                        existing = bfme_index[macro_name]
                                        if isinstance(existing[0], list):
                                            existing[0].append(path)
                                            existing[1].append(i + 1)
                                            existing[3] = existing[3] + (mm.group(2),)
                                        else:
                                            bfme_index[macro_name] = (
                                                [existing[0], path],
                                                [existing[1], i + 1],
                                                "macro",
                                                existing[3] + (mm.group(2),),
                                            )
                                        print(
                                            "[BFME Plugin] Duplicate macro found: {macro_name} (now has {count} definitions)".format(
                                                macro_name=macro_name,
                                                count=len(bfme_index[macro_name][0]),
                                            )
                                        )
                                    else:
                                        bfme_index[macro_name] = (
                                            path,
                                            i + 1,
                                            "macro",
                                            (mm.group(2),),
                                        )
                    except Exception as e:
                        print("[BFME Plugin] Failed to read {path}: {e}".format(path=path, e=e))
                if fn == "lotr.csv":
                    read_string_names(os.path.join(root, fn))

    print("[BFME Plugin] Indexed {index} symbols".format(index=len(bfme_index)))


def index_bfme_files_async(window):
    def worker():
        index_bfme_files(window)
        sublime.set_timeout(lambda: sublime.status_message("BFME: Indexing complete"), 0)

    threading.Thread(target=worker, daemon=True).start()


def get_current_behavior_context(view, location):
    """Find the current behavior block we're in and return behavior name."""
    current_line = view.line(location).begin()
    
    behavior_name = None
    indent_level = None
    
    while current_line > 0:
        line_region = sublime.Region(current_line, view.line(current_line).end())
        line_text = view.substr(line_region)
        
        stripped = line_text.strip()
        if stripped.lower() == 'end':
            end_indent = len(line_text) - len(line_text.lstrip())
            if indent_level is None or end_indent <= indent_level:
                break
        
        behavior_match = behavior_pattern.match(line_text)
        if behavior_match:
            current_indent = len(line_text) - len(line_text.lstrip())
            if indent_level is None:
                target_line = view.line(location)
                target_text = view.substr(target_line)
                target_indent = len(target_text) - len(target_text.lstrip())
                
                if target_indent > current_indent:
                    behavior_name = behavior_match.group(1)
                    indent_level = current_indent
                break
            elif current_indent < indent_level:
                behavior_name = behavior_match.group(1)
                break
        
        if current_line == 0:
            break
        current_line = view.line(current_line - 1).begin()
    
    return behavior_name


def is_behavior_declaration_line(view, location):
    """Check if we're on a line declaring a behavior (Behavior = ...)."""
    line_region = view.line(location)
    line_text = view.substr(line_region)
    
    return re.match(r'^\s*Behavior\s*=\s*', line_text, re.I) is not None


class BfmeIndexProjectCommand(sublime_plugin.WindowCommand):
    def run(self):
        index_bfme_files_async(self.window)
        sublime.status_message("BFME: Indexing complete")


class GotoBfmeDefinitionCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if not bfme_index and not bfme_strings_index:
            index_bfme_files_async(self.view.window())

        sel = self.view.sel()[0]

        line_region = self.view.line(sel)
        line_text = self.view.substr(line_region)
        include_match = include_pattern.search(line_text)

        if include_match:
            include_path = include_match.group(1)
            current_file = self.view.file_name()

            if current_file:
                current_dir = os.path.dirname(current_file)
                include_path_normalized = include_path.replace("\\", os.sep)
                if include_path_normalized.startswith(os.sep):
                    include_path_normalized = include_path_normalized[1:]

                full_include_path = os.path.normpath(
                    os.path.join(current_dir, include_path_normalized)
                )

                if os.path.exists(full_include_path):
                    self.view.window().open_file(full_include_path)
                    sublime.status_message(
                        "BFME: Opened include file {path}".format(
                            path=os.path.basename(include_path)
                        )
                    )
                    return
                else:
                    sublime.status_message(
                        "BFME: Include file not found: {path}".format(path=full_include_path)
                    )
                    return
            else:
                sublime.status_message(
                    "BFME: Cannot resolve include path - current file not saved"
                )
                return

        word_region = self.view.word(sel)
        begin = word_region.begin()
        end = word_region.end()

        while begin > 0 and re.match(r"[\w:]", self.view.substr(begin - 1)):
            begin -= 1

        while end < self.view.size() and re.match(r"[\w:]", self.view.substr(end)):
            end += 1

        full_region = sublime.Region(begin, end)
        lookup = self.view.substr(full_region)

        if lookup:
            if lookup in bfme_index:
                path, line, kind, _ = bfme_index[lookup]

                if isinstance(path, list):
                    if len(path) == 1:
                        self.view.window().open_file(
                            "{path}:{line}".format(path=path[0], line=line[0]),
                            sublime.ENCODED_POSITION,
                        )
                        sublime.status_message("BFME: Jumped to {lookup}".format(lookup=lookup))
                    else:
                        items = []
                        for i, (p, line_num) in enumerate(zip(path, line)):
                            items.append(
                                "{lookup} in {fullpath} (line {line})".format(
                                    lookup=lookup, fullpath=p, line=line_num
                                )
                            )

                        def on_done(index):
                            if index >= 0:
                                self.view.window().open_file(
                                    "{path}:{line}".format(path=path[index], line=line[index]),
                                    sublime.ENCODED_POSITION,
                                )

                        self.view.window().show_quick_panel(items, on_done)
                        sublime.status_message(
                            "BFME: Multiple definitions found for {lookup}".format(lookup=lookup)
                        )
                else:
                    self.view.window().open_file(
                        "{path}:{line}".format(path=path, line=line), sublime.ENCODED_POSITION
                    )
                    sublime.status_message("BFME: Jumped to {lookup}".format(lookup=lookup))
                return

            if lookup.lower() in bfme_strings_index:
                path, line, _, _ = bfme_strings_index[lookup.lower()]
                self.view.window().open_file(
                    "{path}:{line}".format(path=path, line=line), sublime.ENCODED_POSITION
                )
                sublime.status_message("BFME: Jumped to {lookup}".format(lookup=lookup))
                return

        sublime.status_message("BFME: No definition found for {lookup}".format(lookup=lookup))


class BfmeHoverListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        syntax = settings.get("syntax") or ""
        return any(
            ext in syntax.lower() for ext in ["ini", "inc", "bfmehighlighter", "plain text"]
        )

    def on_hover(self, point, hover_zone):
        if not bfme_index and not bfme_strings_index:
            index_bfme_files_async(self.view.window())

        if hover_zone != sublime.HOVER_TEXT:
            return

        line_region = self.view.line(point)
        line_text = self.view.substr(line_region)
        include_match = include_pattern.search(line_text)

        if include_match:
            include_path = include_match.group(1)
            current_file = self.view.file_name()

            if current_file:
                current_dir = os.path.dirname(current_file)
                include_path_normalized = include_path.replace("\\", os.sep)
                if include_path_normalized.startswith(os.sep):
                    include_path_normalized = include_path_normalized[1:]

                full_include_path = os.path.normpath(
                    os.path.join(current_dir, include_path_normalized)
                )

                popup_text = "<b>Include:</b> {path}<br/>".format(path=include_path)

                if os.path.exists(full_include_path):
                    popup_text += "<i>Found:</i> {full_path}".format(full_path=full_include_path)
                else:
                    popup_text += "<i style='color: red;'>File not found:</i> {full_path}".format(
                        full_path=full_include_path
                    )

                self.view.show_popup(
                    popup_text,
                    flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                    location=point,
                    max_width=600,
                )
                return

        word_region = self.view.word(point)
        word = self.view.substr(word_region)

        behavior_match = behavior_pattern.match(line_text)
        if behavior_match:
            behavior_name = behavior_match.group(1)
            if behavior_name in behaviors:
                behavior_params = behaviors[behavior_name]
                popup_text = "<b>Behavior: {name}</b><br/>".format(name=behavior_name)
                popup_text += "<i>Parameters ({count}):</i><br/>".format(count=len(behavior_params))
                
                param_list = list(behavior_params.items())[:8] 
                for param_name, param_type in param_list:
                    popup_text += "• {param} ({type})<br/>".format(param=param_name, type=param_type)
                
                if len(behavior_params) > 8:
                    popup_text += "• ... and {more} more<br/>".format(more=len(behavior_params) - 8)
                
                self.view.show_popup(
                    popup_text,
                    flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                    location=point,
                    max_width=600,
                )
                return

        current_behavior = get_current_behavior_context(self.view, point)
        if current_behavior and current_behavior in behaviors:
            behavior_params = behaviors[current_behavior]
            
            if word in behavior_params:
                param_type = behavior_params[word]
                popup_text = "<b>{param}</b><br/>".format(param=word)
                popup_text += "<i>{behavior} parameter</i><br/>".format(behavior=current_behavior)
                popup_text += "Type: {type}".format(type=param_type)
                
                self.view.show_popup(
                    popup_text,
                    flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                    location=point,
                    max_width=600,
                )
                return

        if word in bfme_index:
            path, line, kind, extra = bfme_index[word]
            if kind == "macro":
                try:
                    if isinstance(path, list):
                        popup_text = "<b>{word}</b><br/>".format(word=word)
                        for i, value in enumerate(extra):
                            popup_text += "• {fullpath}: {value}<br/>".format(
                                fullpath=path[i], value=value
                            )
                    else:
                        popup_text = "<b>{word}</b> = {extra[0]}".format(word=word, extra=extra)

                    self.view.show_popup(
                        popup_text,
                        flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                        location=point,
                        max_width=600,
                    )
                except Exception as e:
                    print("[BFME Plugin] Failed to read macro {word}: {e}".format(word=word, e=e))


class BfmeQuickLookupCommand(sublime_plugin.WindowCommand):
    def run(self):
        if not bfme_index and not bfme_strings_index:
            index_bfme_files_async(self.window)

        self.items = []
        for name, (path, line, kind, *_) in bfme_index.items():
            if isinstance(path, list):
                for i, (p, line_num) in enumerate(zip(path, line)):
                    display = "{name} [{kind}] - {fullpath}".format(
                        name=name, kind=kind, fullpath=p
                    )
                    self.items.append((display, p, line_num))
            else:
                display = "{name} [{kind}]".format(name=name, kind=kind)
                self.items.append((display, path, line))

        for name, (path, line, kind, *_) in bfme_strings_index.items():
            display = "{name} [string]".format(name=name)
            self.items.append((display, path, line))

        self.items.sort(key=lambda x: x[0].lower())

        self.window.show_quick_panel(
            [item[0] for item in self.items],
            self.on_done,
            sublime.KEEP_OPEN_ON_FOCUS_LOST,
            0,
            self.on_highlight,
        )

    def on_done(self, index):
        if index == -1:
            return
        display, path, line = self.items[index]
        self.window.open_file(
            "{path}:{line}".format(path=path, line=line), sublime.ENCODED_POSITION
        )

    def on_highlight(self, index):
        if 0 <= index < len(self.items):
            display, path, line = self.items[index]
            self.window.open_file(
                "{path}:{line}".format(path=path, line=line),
                sublime.ENCODED_POSITION | sublime.TRANSIENT,
            )


class BfmeCompletionListener(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        syntax = view.settings().get("syntax") or ""
        if not any(
            ext in syntax.lower() for ext in ["ini", "inc", "bfmehighlighter", "plain text"]
        ):
            return None

        scope = view.scope_name(locations[0])
        if any(s in scope for s in ["string", "comment"]):
            return None

        if not bfme_index and not bfme_strings_index:
            index_bfme_files_async(view.window())
            return None

        location = locations[0]
        line_region = view.line(location)
        line_text = view.substr(line_region)

        completions = []

        if is_behavior_declaration_line(view, location):
            for behavior_name in behaviors.keys():
                if behavior_name.lower().startswith(prefix.lower()):
                    param_count = len(behaviors[behavior_name])
                    completion = sublime.CompletionItem(
                        trigger=behavior_name,
                        completion=behavior_name,
                        kind=sublime.KIND_TYPE,
                        details="<b>{name}</b><br/><i>Behavior ({count} parameters)</i>".format(
                            name=behavior_name, count=param_count
                        ),
                    )
                    completions.append(completion)
        else:
            current_behavior = get_current_behavior_context(view, location)
            
            if current_behavior and current_behavior in behaviors:
                behavior_params = behaviors[current_behavior]
                for param_name, param_type in behavior_params.items():
                    if param_name.lower().startswith(prefix.lower()):
                        completion = sublime.CompletionItem(
                            trigger=param_name,
                            completion=param_name + " = ",
                            kind=sublime.KIND_VARIABLE,
                            details="<b>{param}</b><br/><i>{behavior} parameter ({type})</i>".format(
                                param=param_name, behavior=current_behavior, type=param_type
                            ),
                        )
                        completions.append(completion)

        context_filter = None

        if any(
            keyword in line_text.lower()
            for keyword in ["primaryweapon", "secondaryweapon", "weapon"]
        ):
            context_filter = "weapon"
        elif any(keyword in line_text.lower() for keyword in ["armor", "armorset"]):
            context_filter = "armor"
        elif any(keyword in line_text.lower() for keyword in ["locomotor", "locomotorset"]):
            context_filter = "locomotor"
        elif any(keyword in line_text.lower() for keyword in ["commandset", "commandbutton"]):
            context_filter = ["commandset", "commandbutton"]
        elif any(keyword in line_text.lower() for keyword in ["audioevent", "sound"]):
            context_filter = "audioevent"
        elif any(keyword in line_text.lower() for keyword in ["upgrade", "science"]):
            context_filter = ["upgrade", "science"]

        for name, (path, line_num, kind, extra) in bfme_index.items():
            if name.lower().startswith(prefix.lower()):
                if context_filter:
                    if isinstance(context_filter, list):
                        if kind not in context_filter:
                            continue
                    else:
                        if kind != context_filter:
                            continue

                if isinstance(path, list):
                    first_file = os.path.basename(path[0])
                    detail = "{kind} ({count} definitions) - {file}...".format(
                        kind=kind.title(), count=len(path), file=first_file
                    )
                else:
                    filename = os.path.basename(path)
                    detail = "{kind} - {file}".format(kind=kind.title(), file=filename)

                completion_kind = sublime.KIND_VARIABLE
                if kind == "audioevent":
                    completion_kind = sublime.KIND_FUNCTION
                elif kind in ["object", "childobject"]:
                    completion_kind = sublime.KIND_TYPE
                elif kind in ["weapon", "armor"]:
                    completion_kind = sublime.KIND_MARKUP
                elif kind == "macro":
                    completion_kind = sublime.KIND_SNIPPET

                completion = sublime.CompletionItem(
                    trigger=name,
                    completion=name,
                    kind=completion_kind,
                    details="<b>{name}</b><br/><i>{detail}</i>".format(name=name, detail=detail),
                )
                completions.append(completion)

        if not context_filter or any(
            keyword in line_text.lower()
            for keyword in ["displayname", "description", "tooltip", "string"]
        ):
            for name, (path, line_num, kind, _) in bfme_strings_index.items():
                if name.lower().startswith(prefix.lower()):
                    filename = os.path.basename(path)
                    completion = sublime.CompletionItem(
                        trigger=name,
                        completion=name,
                        kind=sublime.KIND_MARKUP,
                        details="<b>{name}</b><br/><i>String - {file}</i>".format(
                            name=name, file=filename
                        ),
                    )
                    completions.append(completion)

        def sort_key(completion):
            name = completion.trigger
            if name.lower() == prefix.lower():
                return (0, name.lower())
            elif name.lower().startswith(prefix.lower()):
                return (1, name.lower())
            else:
                return (2, name.lower())

        completions.sort(key=sort_key)

        return sublime.CompletionList(
            completions[:100],
            flags=sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS,
        )


class BfmeSymbolBrowserCommand(sublime_plugin.WindowCommand):
    def run(self):
        if not bfme_index and not bfme_strings_index:
            index_bfme_files_async(self.window)

        self.items = []

        for name, (path, line, kind, *_) in bfme_index.items():
            if isinstance(path, list):
                for i, (p, line_num) in enumerate(zip(path, line)):
                    display = "{name}   ⟶   [{kind}] - {fullpath}".format(
                        name=name, kind=kind, fullpath=p
                    )
                    self.items.append((display, p, line_num))
            else:
                display = "{name}   ⟶   [{kind}]".format(name=name, kind=kind)
                self.items.append((display, path, line))

        for name, (path, line, kind, *_) in bfme_strings_index.items():
            display = "{name}   ⟶   [string]".format(name=name)
            self.items.append((display, path, line))

        self.items.sort(key=lambda x: x[0].lower())

        self.window.show_quick_panel(
            [item[0] for item in self.items],
            self.on_done,
            sublime.KEEP_OPEN_ON_FOCUS_LOST,
            0,
            self.on_highlight,
        )

    def on_done(self, index):
        if index == -1:
            return
        display, path, line = self.items[index]
        self.window.open_file(
            "{path}:{line}".format(path=path, line=line), sublime.ENCODED_POSITION
        )

    def on_highlight(self, index):
        if 0 <= index < len(self.items):
            display, path, line = self.items[index]
            self.window.open_file(
                "{path}:{line}".format(path=path, line=line),
                sublime.ENCODED_POSITION | sublime.TRANSIENT,
            )
