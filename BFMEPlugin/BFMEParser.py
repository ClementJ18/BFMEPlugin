import sublime
import sublime_plugin
import os
import re
import csv
import threading
from .behaviors_data import behaviors

bfme_index = {}
bfme_strings_index = {}
_indexing_in_progress = False
_pending_operations = []

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
                                        if not is_duplicate_location(existing, path, i + 1):
                                            if isinstance(existing[0], list):
                                                existing[0].append(path)
                                                existing[1].append(i + 1)
                                                definition_count = len(existing[0])
                                            else:
                                                bfme_index[name] = (
                                                    [existing[0], path],
                                                    [existing[1], i + 1],
                                                    kind.lower(),
                                                    tuple(),
                                                )
                                                definition_count = 2
                                            print(
                                                "[BFME Plugin] Duplicate symbol found: {name} (now has {count} definitions)".format(
                                                    name=name, count=definition_count
                                                )
                                            )
                                    else:
                                        bfme_index[name] = (path, i + 1, kind.lower(), tuple())

                                mm = macro_pattern.match(line)
                                if mm:
                                    macro_name = mm.group(1)
                                    if macro_name in bfme_index:
                                        existing = bfme_index[macro_name]
                                        if not is_duplicate_location(existing, path, i + 1):
                                            if isinstance(existing[0], list):
                                                existing[0].append(path)
                                                existing[1].append(i + 1)
                                                existing[3] = existing[3] + (mm.group(2),)
                                                definition_count = len(existing[0])
                                            else:
                                                bfme_index[macro_name] = (
                                                    [existing[0], path],
                                                    [existing[1], i + 1],
                                                    "macro",
                                                    existing[3] + (mm.group(2),),
                                                )
                                                definition_count = 2
                                            print(
                                                "[BFME Plugin] Duplicate macro found: {macro_name} (now has {count} definitions)".format(
                                                    macro_name=macro_name,
                                                    count=definition_count,
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
    global _indexing_in_progress, _pending_operations
    
    if _indexing_in_progress:
        sublime.status_message("BFME: Indexing already in progress")
        return
    
    _indexing_in_progress = True
    sublime.status_message("BFME: Indexing started...")
    
    def worker():
        global _indexing_in_progress, _pending_operations
        try:
            index_bfme_files(window)
        finally:
            _indexing_in_progress = False
            
        def on_complete():
            sublime.status_message("BFME: Indexing complete")
            # Process any pending operations that were blocked during indexing
            if _pending_operations:
                pending = _pending_operations[:]
                _pending_operations.clear()
                for operation in pending:
                    operation()
                    
        sublime.set_timeout(on_complete, 0)

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


def can_perform_index_operation(operation=None):
    """Check if index-dependent operations can proceed."""
    global _indexing_in_progress, _pending_operations
    
    if _indexing_in_progress:
        if operation:
            _pending_operations.append(operation)
            sublime.status_message("BFME: Operation queued - indexing in progress")
        else:
            sublime.status_message("BFME: Please wait - indexing in progress")
        return False
        
    if not bfme_index and not bfme_strings_index:
        sublime.status_message("BFME: Index is empty - please run 'BFME: Reindex project' first")
        return False
        
    return True


def is_duplicate_location(existing_entry, new_path, new_line):
    existing_path, existing_line = existing_entry[0], existing_entry[1]
    
    if isinstance(existing_path, list):
        for ep, el in zip(existing_path, existing_line):
            if ep == new_path and el == new_line:
                return True
        return False
    else:
        return existing_path == new_path and existing_line == new_line


class BfmeIndexProjectCommand(sublime_plugin.WindowCommand):
    def run(self):
        index_bfme_files_async(self.window)


class ShowBehaviorDocCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        sel = self.view.sel()[0]
        
        if sel.empty():
            word_region = self.view.word(sel)
            behavior_name = self.view.substr(word_region)
        else:
            behavior_name = self.view.substr(sel)
        
        behavior_name = behavior_name.strip()
        
        if not behavior_name:
            sublime.status_message("BFME: No behavior name selected")
            return
            
        if behavior_name not in behaviors:
            sublime.status_message("BFME: Unknown behavior '{behavior_name}'".format(behavior_name=behavior_name))
            return
            
        self.show_behavior_documentation(behavior_name)
    


    def show_behavior_documentation(self, behavior_name):
        behavior_params = behaviors[behavior_name]
        
        html_content = """
        <body id="behavior-doc">
            <style>
                body {{
                    font-family: system;
                    margin: 0;
                    padding: 20px;
                    background-color: var(--background);
                    color: var(--foreground);
                    line-height: 1.4;
                }}
                h1 {{
                    color: var(--orangish);
                    margin: 0 0 15px 0;
                    font-size: 18px;
                    border-bottom: 2px solid var(--orangish);
                    padding-bottom: 8px;
                }}
                .param-count {{
                    color: var(--orangish);
                    font-size: 14px;
                    margin-bottom: 20px;
                    font-style: italic;
                    background-color: color(var(--background) blend(var(--bluish) 10%));
                    padding: 8px 12px;
                    border-radius: 4px;
                    border: 1px solid var(--bluish);
                }}
                .param-list {{
                    width: 100%;
                }}
                .param-item {{
                    display: flex;
                    padding: 4px 0;
                    border-bottom: 1px solid color(var(--background) blend(var(--foreground) 15%));
                    margin-bottom: 2px;
                    line-height: 1.3;
                    white-space: nowrap;
                }}
                .param-name {{
                    font-weight: bold;
                    color: var(--bluish);
                    font-family: monospace;
                    font-size: 13px;
                    flex: 0 0 250px;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }}
                .param-type {{
                    color: var(--greenish);
                    font-family: monospace;
                    font-size: 13px;
                    flex: 1;
                    margin-left: 10px;
                }}
                .param-row:hover {{
                    background-color: color(var(--background) blend(var(--foreground) 5%));
                }}
                .no-params {{
                    color: var(--foreground);
                    font-style: italic;
                    text-align: center;
                    padding: 20px;
                }}
                .common-params {{
                    margin-bottom: 20px;
                }}
                .section-header {{
                    color: var(--orangish);
                    font-weight: bold;
                    margin: 20px 0 10px 0;
                    font-size: 14px;
                }}
            </style>
            <h1>Behavior: {behavior_name}</h1>
        """.format(behavior_name=behavior_name)
        
        if behavior_params:
            html_content += '<div class="param-count">📋 {count} parameters available</div>'.format(count=len(behavior_params))    
            sorted_params = sorted(behavior_params.items())            
            html_content += '<div class="param-list">'
            
            for param_name, param_type in sorted_params:
                html_content += '<div class="param-item">'
                html_content += '<span class="param-name">{param_name}\t\t</span>'.format(param_name=param_name)
                html_content += '<span class="param-type">{param_type}</span>'.format(param_type=param_type)
                html_content += '</div>'
            
            html_content += '</div>'
        else:
            html_content += '<div class="no-params">No parameters defined for this behavior.</div>'
        
        html_content += """
        </body>
        """
        
        self.view.show_popup(
            html_content,
            flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY | sublime.COOPERATE_WITH_AUTO_COMPLETE,
            location=-1,
            max_width=1000,
            max_height=600,
            on_navigate=None
        )
        
        sublime.status_message("BFME: Showing documentation for {behavior_name}".format(behavior_name=behavior_name))
    
    def is_enabled(self):
        return True
    
    def is_visible(self):
        syntax = self.view.settings().get("syntax") or ""
        return any(
            ext in syntax.lower() for ext in ["ini", "inc", "bfmehighlighter", "plain text"]
        )


class GotoBfmeDefinitionCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if not can_perform_index_operation(lambda: self.run(edit)):
            return

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
            # Try to find the symbol with the original lookup
            found_entry = None
            if lookup in bfme_index:
                found_entry = bfme_index[lookup]
            elif ":" in lookup and lookup.replace(":", "") in bfme_index:
                # If not found and contains colon, try without the colon
                lookup = lookup.replace(":", "")
                found_entry = bfme_index[lookup]
            
            if found_entry:
                path, line, kind, _ = found_entry

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
                    max_width=1200,
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
        if not can_perform_index_operation(lambda: self.run()):
            return

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
    def on_modified(self, view):
        syntax = view.settings().get("syntax") or ""
        if not any(ext in syntax.lower() for ext in ["ini", "inc", "bfmehighlighter", "plain text"]):
            return
        sel = view.sel()
        if not sel:
            return
        location = sel[0].begin()
        line_text_before = view.substr(sublime.Region(view.line(location).begin(), location))
        if re.match(r'#include\s+"[^"]*[/\\]$', line_text_before, re.I):
            sublime.set_timeout(lambda: view.run_command("auto_complete", {
                "disable_auto_insert": True,
                "next_completion_if_showing": False,
            }), 0)

    def _include_path_completions(self, view, partial_path, prefix):
        current_file = view.file_name()
        if not current_file:
            return None

        current_dir = os.path.dirname(current_file)
        norm_partial = partial_path.replace('\\', '/')

        if '/' in norm_partial:
            dir_rel = norm_partial.rsplit('/', 1)[0]
            search_dir = os.path.normpath(os.path.join(current_dir, dir_rel))
        else:
            dir_rel = ''
            search_dir = current_dir

        if not os.path.isdir(search_dir):
            return None

        try:
            raw_entries = os.listdir(search_dir)
        except OSError:
            return None

        entries = sorted(
            raw_entries,
            key=lambda e: (not os.path.isdir(os.path.join(search_dir, e)), e.lower()),
        )

        rel_dir = os.path.relpath(search_dir, current_dir).replace('\\', '/')
        context = rel_dir if rel_dir != '.' else '(current directory)'

        completions = []
        prefix_lower = prefix.lower()

        for entry in entries:
            entry_lower = entry.lower()
            if prefix_lower and not entry_lower.startswith(prefix_lower):
                continue

            entry_full = os.path.join(search_dir, entry)
            if os.path.isdir(entry_full):
                completion = sublime.CompletionItem(
                    trigger=entry,
                    completion=entry + '\\',
                    kind=sublime.KIND_NAVIGATION,
                    details='<i>[dir] in {}</i>'.format(context),
                )
                completions.append(completion)
            elif entry_lower.endswith(('.ini', '.inc')):
                completion = sublime.CompletionItem(
                    trigger=entry,
                    completion=entry,
                    kind=sublime.KIND_SNIPPET,
                    details='<i>[file] in {}</i>'.format(context),
                )
                completions.append(completion)

        return sublime.CompletionList(
            completions,
            flags=sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS,
        )

    def on_query_completions(self, view, prefix, locations):
        syntax = view.settings().get("syntax") or ""
        if not any(
            ext in syntax.lower() for ext in ["ini", "inc", "bfmehighlighter", "plain text"]
        ):
            return None

        location = locations[0]
        line_region = view.line(location)
        line_text_before_cursor = view.substr(sublime.Region(line_region.begin(), location))

        include_typing_match = re.match(r'#include\s+"([^"]*)', line_text_before_cursor, re.I)
        if include_typing_match:
            return self._include_path_completions(view, include_typing_match.group(1), prefix)

        scope = view.scope_name(locations[0])
        if any(s in scope for s in ["string", "comment"]):
            return None

        if not bfme_index and not bfme_strings_index:
            index_bfme_files_async(view.window())
            return None

        line_text = view.substr(line_region)

        if len(prefix) == 0:
            return None

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
            
            completions.sort(key=lambda c: c.trigger.lower())
            return sublime.CompletionList(
                completions,
                flags=sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS,
            )

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


class BfmeCurrentFileSymbolsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        current_file = self.view.file_name()
        if not current_file:
            sublime.status_message("No file currently open")
            return
            
        if not can_perform_index_operation(lambda: self.run(edit)):
            return

        current_file_symbols = []
        for name, (path, line, kind, *_) in bfme_index.items():
            if isinstance(path, list):
                for i, (p, line_num) in enumerate(zip(path, line)):
                    if p == current_file:
                        current_file_symbols.append((name, line_num, kind))
            else:
                if path == current_file:
                    current_file_symbols.append((name, line, kind))
        
        for name, (path, line, kind, *_) in bfme_strings_index.items():
            if path == current_file:
                current_file_symbols.append((name, line, kind))
        
        if not current_file_symbols:
            sublime.status_message("No symbols found in current file")
            return
        
        current_file_symbols.sort(key=lambda x: (x[2], x[0].lower()))
        
        self.items = []
        for symbol_name, line_num, kind in current_file_symbols:
            display = "{name}   ⟶   [{kind}] (line {line})".format(
                name=symbol_name, kind=kind, line=line_num
            )
            self.items.append((display, current_file, line_num))
        
        self.view.window().show_quick_panel(
            [item[0] for item in self.items],
            self.on_done,
            sublime.KEEP_OPEN_ON_FOCUS_LOST,
            0,
            self.on_highlight,
        )

    def on_done(self, index):
        if index == -1:
            return
        display, file_path, line_num = self.items[index]
        self.view.window().open_file(
            "{path}:{line}".format(path=file_path, line=line_num), 
            sublime.ENCODED_POSITION
        )

    def on_highlight(self, index):
        if 0 <= index < len(self.items):
            display, file_path, line_num = self.items[index]
            self.view.window().open_file(
                "{path}:{line}".format(path=file_path, line=line_num),
                sublime.ENCODED_POSITION | sublime.TRANSIENT,
            )


class BfmeUsedSymbolsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        current_file = self.view.file_name()
        if not current_file:
            sublime.status_message("No file currently open")
            return
            
        if not can_perform_index_operation(lambda: self.run(edit)):
            return

        file_content = self.view.substr(sublime.Region(0, self.view.size()))
        lines = file_content.split('\n')
        
        external_symbols = {}
        for symbol_name, (symbol_path, symbol_line, symbol_kind, *_) in bfme_index.items():
            if isinstance(symbol_path, list):
                if current_file in symbol_path:
                    continue
            elif symbol_path == current_file:
                continue
            
            if isinstance(symbol_path, list):
                def_path = symbol_path[0]
                def_line = symbol_line[0] if isinstance(symbol_line, list) else symbol_line
            else:
                def_path = symbol_path
                def_line = symbol_line
            
            external_symbols[symbol_name] = (symbol_kind, def_path, def_line)
        
        for symbol_name, (symbol_path, symbol_line, symbol_kind, *_) in bfme_strings_index.items():
            if symbol_path != current_file:
                external_symbols[symbol_name] = (symbol_kind, symbol_path, symbol_line)
        
        used_symbols = []
        symbol_patterns = {}
        
        for line_num, line in enumerate(lines, 1):
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith(';') or stripped_line.startswith('//'):
                continue
            
            for symbol_name, (symbol_kind, def_path, def_line) in external_symbols.items():
                if symbol_name in line:
                    if symbol_name not in symbol_patterns:
                        symbol_patterns[symbol_name] = re.compile(r'\b' + re.escape(symbol_name) + r'\b', re.IGNORECASE)
                    
                    if symbol_patterns[symbol_name].search(line):
                        used_symbols.append((
                            symbol_name, 
                            line_num, 
                            symbol_kind, 
                            def_path, 
                            def_line,
                            stripped_line
                        ))
                        del external_symbols[symbol_name]
                        break
        
        if not used_symbols:
            sublime.status_message("No external symbols used in current file")
            return
        
        used_symbols.sort(key=lambda x: x[1])
        
        self.items = []
        for symbol_name, used_line, symbol_kind, def_path, def_line, context in used_symbols:
            def_file = os.path.basename(def_path)
            display = "{name} [{kind}] used on line {used_line} → defined in {file}:{def_line}".format(
                name=symbol_name,
                kind=symbol_kind, 
                used_line=used_line,
                file=def_file,
                def_line=def_line
            )
            self.items.append((display, current_file, used_line, def_path, def_line))
        
        self.view.window().show_quick_panel(
            [item[0] for item in self.items],
            self.on_done,
            sublime.KEEP_OPEN_ON_FOCUS_LOST,
            0,
            self.on_highlight,
        )

    def on_done(self, index):
        if index == -1:
            return
        display, current_file, used_line, def_path, def_line = self.items[index]
        
        self.selected_item = self.items[index]
        choices = [
            "Go to usage (line {} in current file)".format(used_line),
            "Go to definition (line {} in {})".format(def_line, os.path.basename(def_path))
        ]
        
        self.view.window().show_quick_panel(
            choices,
            self.on_location_choice,
            sublime.KEEP_OPEN_ON_FOCUS_LOST
        )

    def on_location_choice(self, index):
        if index == -1:
            return
            
        display, current_file, used_line, def_path, def_line = self.selected_item
        
        if index == 0:
            self.view.window().open_file(
                "{}:{}".format(current_file, used_line), 
                sublime.ENCODED_POSITION
            )
        elif index == 1:
            self.view.window().open_file(
                "{}:{}".format(def_path, def_line), 
                sublime.ENCODED_POSITION
            )

    def on_highlight(self, index):
        if 0 <= index < len(self.items):
            display, current_file, used_line, def_path, def_line = self.items[index]
            self.view.window().open_file(
                "{}:{}".format(current_file, used_line),
                sublime.ENCODED_POSITION | sublime.TRANSIENT,
            )


class BfmeSymbolBrowserCommand(sublime_plugin.WindowCommand):
    def run(self):
        if not can_perform_index_operation(lambda: self.run()):
            return

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

class EditBfmeDefineCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        region = self.view.line(self.view.sel()[0])
        line = self.view.substr(region)

        match = re.match(r'#define\s+(\w+)\s+(.+)', line)
        if not match:
            sublime.message_dialog("Cursor must be on a valid #define line.")
            return

        self.region = region
        self.macro_name = match.group(1)
        self.values = re.findall(r'\+\S+', match.group(2))

        self.show_main_menu()

    # ---------- UI ----------

    def show_main_menu(self):
        items = [
            "Add value",
            "Subtract value",
            "Remove value",
            "List values"
        ]
        self.view.window().show_quick_panel(items, self.handle_main_selection)

    def handle_main_selection(self, index):
        if index == -1:
            return

        if index == 0:
            # Add value: show quick panel from index or allow freehand
            all_symbols = sorted(bfme_index.keys()) if bfme_index else []
            items = [v for v in all_symbols if "+" + v not in self.values]
            items.append("[Manual entry]")
            def on_done_add(idx):
                if idx == -1:
                    return
                if idx == len(items) - 1:
                    # Manual entry
                    self.view.window().show_input_panel("Enter value to add (+):", "", lambda val: self.add_value(val), None, None)
                else:
                    self.add_value(items[idx])
            self.view.window().show_quick_panel(items if items else ["[Manual entry]"], on_done_add, sublime.KEEP_OPEN_ON_FOCUS_LOST, 0)
        elif index == 1:
            # Subtract value: show quick panel from index or allow freehand
            all_symbols = sorted(bfme_index.keys()) if bfme_index else []
            items = [v for v in all_symbols if "-" + v not in self.values]
            items.append("[Manual entry]")
            def on_done_subtract(idx):
                if idx == -1:
                    return
                if idx == len(items) - 1:
                    self.view.window().show_input_panel("Enter value to subtract (-):", "", lambda val: self.add_value(val, subtract=True), None, None)
                else:
                    self.add_value(items[idx], subtract=True)
            self.view.window().show_quick_panel(items if items else ["[Manual entry]"], on_done_subtract, sublime.KEEP_OPEN_ON_FOCUS_LOST, 0)
        elif index == 2:
            # Remove value: show quick panel of current values or allow freehand
            if not self.values:
                self.view.window().show_input_panel("Enter value to remove:", "", self.remove_value_freehand, None, None)
                return
            def on_done_remove(idx):
                if idx == -1:
                    return
                self.remove_value(idx)
            self.view.window().show_quick_panel(self.values, on_done_remove, sublime.KEEP_OPEN_ON_FOCUS_LOST, 0)
        elif index == 3:
            # List values: show searchable quick panel of all values
            def on_done_list(idx):
                pass  # No action needed, just for viewing
            self.view.window().show_quick_panel(self.values if self.values else ["(No values)"] , on_done_list, sublime.KEEP_OPEN_ON_FOCUS_LOST, 0)
    def remove_value_freehand(self, value):
        value = value.strip()
        if not value:
            return
        # Remove matching value (with + or - prefix)
        for i, v in enumerate(self.values):
            if v.lstrip("+-") == value.lstrip("+-"):
                self.remove_value(i)
                return
        sublime.message_dialog("Value not found.")

    # ---------- Logic ----------

    def add_value(self, value, subtract=False):
        if not value:
            return

        token = ("-" if subtract else "+") + value.strip()

        if token in self.values:
            sublime.message_dialog("Value already exists.")
            return

        self.values.append(token)
        self.rewrite_line()
        self.refresh_values()

    def remove_value(self, index):
        if index == -1:
            return

        del self.values[index]
        self.rewrite_line()
        self.refresh_values()
    
    def refresh_values(self):
        region = self.region
        line = self.view.substr(region)
        match = re.match(r'#define\s+(\w+)\s+(.+)', line)
        if match:
            self.values = re.findall(r'[+-]\S+', match.group(2))

    def rewrite_line(self):
        new_line = "#define {} {}".format(
            self.macro_name,
            " ".join(self.values)
        )

        self.view.run_command("bfme_replace_define_line", {
            "region_start": self.region.begin(),
            "region_end": self.region.end(),
            "text": new_line
        })


class BfmeReplaceDefineLineCommand(sublime_plugin.TextCommand):
    def run(self, edit, region_start, region_end, text):
        region = sublime.Region(region_start, region_end)
        self.view.replace(edit, region, text)
