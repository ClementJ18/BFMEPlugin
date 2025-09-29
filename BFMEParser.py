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
bfme_pattern = re.compile(r'^(Object|ChildObject|ObjectCreationList|ModifierList|FXList|FXParticleSystem|Locomotor|Upgrade|Science|StanceTemplate|CommandSet|CommandButton|Weapon|Armor|SpecialPower)\s+(\w+)', re.I)
macro_pattern = re.compile(r'^\s*#define\s+(\w+)\s+([^;]+)', re.I)

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
                                        print("[BFME Plugin] Duplicate symbol found: {name}".format(name=name))
                                    bfme_index[name] = (path, i+1, kind.lower(), tuple())

                                # Macros
                                mm = macro_pattern.match(line)
                                if mm:
                                    macro_name = mm.group(1)
                                    if macro_name in bfme_index:
                                        print("[BFME Plugin] Duplicate macro found: {macro_name}".format(macro_name=macro_name))
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
                path, line, _, _ = bfme_index[lookup]
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

        # Get the word under the cursor
        word_region = self.view.word(point)
        word = self.view.substr(word_region)

        # Check if it's a macro
        if word in bfme_index:
            path, line, kind, extra = bfme_index[word]
            if kind == "macro":
                try:
                    self.view.show_popup(
                        "<b>{word}</b> = {extra[0]}".format(word=word, extra=extra),
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
