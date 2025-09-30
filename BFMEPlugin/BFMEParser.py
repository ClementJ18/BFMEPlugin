import sublime
import sublime_plugin
import os
import re
import csv
import threading

# Holds { symbol_name: (file_path, line_number) }
bfme_index = {}
bfme_strings_index = {}

# Regex for definitions
bfme_pattern = re.compile(r'^(AudioEvent|MappedImage|Object|ChildObject|ObjectCreationList|ModifierList|FXList|FXParticleSystem|Locomotor|Upgrade|Science|StanceTemplate|CommandSet|CommandButton|Weapon|Armor|SpecialPower)\s+([\w+\-]+)', re.I)
macro_pattern = re.compile(r'^\s*#define\s+([\w+\-]+)\s+([^;]+)', re.I)
include_pattern = re.compile(r'#include\s+"([^"]+)"', re.I)

def read_string_names(path):
    global bfme_strings_index
    bfme_strings_index.clear()
    try:
        with open(path, "r", encoding="latin-1", errors="ignore") as f:
            reader = csv.reader(f, delimiter=";")
            for i, row in enumerate(reader):
                if row:
                    name = row[0].strip().lower()  # first column = string name
                    if name:
                        bfme_strings_index[name] = (path, i+1, "string", tuple())
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
                                # Normal definitions
                                m = bfme_pattern.match(line)
                                if m:
                                    kind, name = m.groups()
                                    if name in bfme_index:
                                        # Store multiple locations for duplicates
                                        existing = bfme_index[name]
                                        if isinstance(existing[0], list):
                                            # Already a list of locations
                                            existing[0].append(path)
                                            existing[1].append(i+1)
                                        else:
                                            # Convert to list format
                                            bfme_index[name] = ([existing[0], path], [existing[1], i+1], kind.lower(), tuple())
                                        print("[BFME Plugin] Duplicate symbol found: {name} (now has {count} definitions)".format(name=name, count=len(bfme_index[name][0])))
                                    else:
                                        bfme_index[name] = (path, i+1, kind.lower(), tuple())

                                # Macros
                                mm = macro_pattern.match(line)
                                if mm:
                                    macro_name = mm.group(1)
                                    if macro_name in bfme_index:
                                        # Store multiple locations for duplicates
                                        existing = bfme_index[macro_name]
                                        if isinstance(existing[0], list):
                                            # Already a list of locations
                                            existing[0].append(path)
                                            existing[1].append(i+1)
                                            existing[3] = existing[3] + (mm.group(2),)
                                        else:
                                            # Convert to list format
                                            bfme_index[macro_name] = ([existing[0], path], [existing[1], i+1], "macro", existing[3] + (mm.group(2),))
                                        print("[BFME Plugin] Duplicate macro found: {macro_name} (now has {count} definitions)".format(macro_name=macro_name, count=len(bfme_index[macro_name][0])))
                                    else:
                                        bfme_index[macro_name] = (path, i+1, "macro", (mm.group(2),))
                    except Exception as e:
                        print("[BFME Plugin] Failed to read {path}: {e}".format(path=path, e=e))
                if fn == "lotr.csv":
                    read_string_names(os.path.join(root, fn))

    print("[BFME Plugin] Indexed {index} symbols".format(index=len(bfme_index)))

def index_bfme_files_async(window):
    def worker():
        index_bfme_files(window)  # your existing function
        sublime.set_timeout(lambda: sublime.status_message("BFME: Indexing complete"), 0)

    threading.Thread(target=worker, daemon=True).start()

class BfmeIndexProjectCommand(sublime_plugin.WindowCommand):
    def run(self):
        index_bfme_files_async(self.window)
        sublime.status_message("BFME: Indexing complete")

class GotoBfmeDefinitionCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if not bfme_index and not bfme_strings_index:
            index_bfme_files_async(self.view.window())

        sel = self.view.sel()[0]
        
        # First check if we're on an #include line
        line_region = self.view.line(sel)
        line_text = self.view.substr(line_region)
        include_match = include_pattern.search(line_text)
        
        if include_match:
            # Handle #include statement
            include_path = include_match.group(1)
            current_file = self.view.file_name()
            
            if current_file:
                # Include paths are always relative to the current file's directory
                current_dir = os.path.dirname(current_file)
                # Normalize path separators and treat as relative to current directory
                include_path_normalized = include_path.replace('\\', os.sep)
                # Remove leading separator if present since it's always relative
                if include_path_normalized.startswith(os.sep):
                    include_path_normalized = include_path_normalized[1:]
                
                full_include_path = os.path.normpath(os.path.join(current_dir, include_path_normalized))
                
                if os.path.exists(full_include_path):
                    self.view.window().open_file(full_include_path)
                    sublime.status_message("BFME: Opened include file {path}".format(path=os.path.basename(include_path)))
                    return
                else:
                    sublime.status_message("BFME: Include file not found: {path}".format(path=full_include_path))
                    return
            else:
                sublime.status_message("BFME: Cannot resolve include path - current file not saved")
                return

        # Expand region to include full colon-separated token
        word_region = self.view.word(sel)
        begin = word_region.begin()
        end = word_region.end()

        # Expand left while we see valid chars (letters, digits, underscore, colon)
        while begin > 0 and re.match(r'[\w:]', self.view.substr(begin - 1)):
            begin -= 1

        # Expand right
        while end < self.view.size() and re.match(r'[\w:]', self.view.substr(end)):
            end += 1

        full_region = sublime.Region(begin, end)
        lookup = self.view.substr(full_region)

        if lookup:
            # Try exact match (symbols/macros are case-sensitive)
            if lookup in bfme_index:
                path, line, kind, _ = bfme_index[lookup]
                
                # Handle multiple definitions
                if isinstance(path, list):
                    if len(path) == 1:
                        # Only one definition after all
                        self.view.window().open_file("{path}:{line}".format(path=path[0], line=line[0]), sublime.ENCODED_POSITION)
                        sublime.status_message("BFME: Jumped to {lookup}".format(lookup=lookup))
                    else:
                        # Multiple definitions - show quick panel to choose
                        items = []
                        for i, (p, line_num) in enumerate(zip(path, line)):
                            items.append("{lookup} in {fullpath} (line {line})".format(lookup=lookup, fullpath=p, line=line_num))
                        
                        def on_done(index):
                            if index >= 0:
                                self.view.window().open_file("{path}:{line}".format(path=path[index], line=line[index]), sublime.ENCODED_POSITION)
                        
                        self.view.window().show_quick_panel(items, on_done)
                        sublime.status_message("BFME: Multiple definitions found for {lookup}".format(lookup=lookup))
                else:
                    # Single definition
                    self.view.window().open_file("{path}:{line}".format(path=path, line=line), sublime.ENCODED_POSITION)
                    sublime.status_message("BFME: Jumped to {lookup}".format(lookup=lookup))
                return

            # Try lowercase match (strings are case-insensitive)
            if lookup.lower() in bfme_strings_index:
                path, line, _, _ = bfme_strings_index[lookup.lower()]
                self.view.window().open_file("{path}:{line}".format(path=path, line=line), sublime.ENCODED_POSITION)
                sublime.status_message("BFME: Jumped to {lookup}".format(lookup=lookup))
                return

        sublime.status_message("BFME: No definition found for {lookup}".format(lookup=lookup))

class BfmeHoverListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        syntax = settings.get("syntax") or ""
        return any(ext in syntax.lower() for ext in ["ini", "inc", "bfmehighlighter", "plain text"])

    def on_hover(self, point, hover_zone):
        if not bfme_index and not bfme_strings_index:
            index_bfme_files_async(self.view.window())

        if hover_zone != sublime.HOVER_TEXT:
            return

        # Check if we're hovering over an #include line
        line_region = self.view.line(point)
        line_text = self.view.substr(line_region)
        include_match = include_pattern.search(line_text)
        
        if include_match:
            include_path = include_match.group(1)
            current_file = self.view.file_name()
            
            if current_file:
                # Include paths are always relative to the current file's directory
                current_dir = os.path.dirname(current_file)
                include_path_normalized = include_path.replace('\\', os.sep)
                # Remove leading separator if present since it's always relative
                if include_path_normalized.startswith(os.sep):
                    include_path_normalized = include_path_normalized[1:]
                
                full_include_path = os.path.normpath(os.path.join(current_dir, include_path_normalized))
                
                popup_text = "<b>Include:</b> {path}<br/>".format(path=include_path)
                
                if os.path.exists(full_include_path):
                    popup_text += "<i>Found:</i> {full_path}".format(full_path=full_include_path)
                else:
                    popup_text += "<i style='color: red;'>File not found:</i> {full_path}".format(full_path=full_include_path)
                
                self.view.show_popup(
                    popup_text,
                    flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                    location=point,
                    max_width=600,
                )
                return

        # Get the word under the cursor
        word_region = self.view.word(point)
        word = self.view.substr(word_region)

        # Check if it's a macro
        if word in bfme_index:
            path, line, kind, extra = bfme_index[word]
            if kind == "macro":
                try:
                    if isinstance(path, list):
                        # Multiple macro definitions - show all values
                        popup_text = "<b>{word}</b><br/>".format(word=word)
                        for i, value in enumerate(extra):
                            popup_text += "• {fullpath}: {value}<br/>".format(fullpath=path[i], value=value)
                    else:
                        # Single macro definition
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

        # Combine all symbols, macros, and strings into a single list for selection
        self.items = []
        for name, (path, line, kind, *_) in bfme_index.items():
            if isinstance(path, list):
                # Multiple definitions - add each one separately
                for i, (p, line_num) in enumerate(zip(path, line)):
                    display = "{name} [{kind}] - {fullpath}".format(name=name, kind=kind, fullpath=p)
                    self.items.append((display, p, line_num))
            else:
                # Single definition
                display = "{name} [{kind}]".format(name=name, kind=kind)
                self.items.append((display, path, line))

        for name, (path, line, kind, *_) in bfme_strings_index.items():
            display = "{name} [string]".format(name=name)
            self.items.append((display, path, line))

        # Sort alphabetically
        self.items.sort(key=lambda x: x[0].lower())

        # Show quick panel
        self.window.show_quick_panel(
            [item[0] for item in self.items],
            self.on_done,
            sublime.KEEP_OPEN_ON_FOCUS_LOST,
            0,
            self.on_highlight
        )

    def on_done(self, index):
        if index == -1:
            return
        display, path, line = self.items[index]
        self.window.open_file("{path}:{line}".format(path=path, line=line), sublime.ENCODED_POSITION)

    def on_highlight(self, index):
        # Optional: show a preview while navigating the list
        if 0 <= index < len(self.items):
            display, path, line = self.items[index]
            self.window.open_file("{path}:{line}".format(path=path, line=line), sublime.ENCODED_POSITION | sublime.TRANSIENT)

class BfmeSymbolBrowserCommand(sublime_plugin.WindowCommand):
    def run(self):
        if not bfme_index and not bfme_strings_index:
            index_bfme_files_async(self.window)

        self.items = []

        # Add normal symbols and macros
        for name, (path, line, kind, *_) in bfme_index.items():
            if isinstance(path, list):
                # Multiple definitions - add each one separately
                for i, (p, line_num) in enumerate(zip(path, line)):
                    display = "{name}   ⟶   [{kind}] - {fullpath}".format(name=name, kind=kind, fullpath=p)
                    self.items.append((display, p, line_num))
            else:
                # Single definition
                display = "{name}   ⟶   [{kind}]".format(name=name, kind=kind)
                self.items.append((display, path, line))

        # Add strings
        for name, (path, line, kind, *_) in bfme_strings_index.items():
            display = "{name}   ⟶   [string]".format(name=name)
            self.items.append((display, path, line))

        # Sort alphabetically
        self.items.sort(key=lambda x: x[0].lower())

        # Show quick panel
        self.window.show_quick_panel(
            [item[0] for item in self.items],
            self.on_done,
            sublime.KEEP_OPEN_ON_FOCUS_LOST,
            0,
            self.on_highlight
        )

    def on_done(self, index):
        if index == -1:
            return
        display, path, line = self.items[index]
        self.window.open_file(
            "{path}:{line}".format(path=path, line=line),
            sublime.ENCODED_POSITION
        )

    def on_highlight(self, index):
        if 0 <= index < len(self.items):
            display, path, line = self.items[index]
            self.window.open_file(
                "{path}:{line}".format(path=path, line=line),
                sublime.ENCODED_POSITION | sublime.TRANSIENT
            )
