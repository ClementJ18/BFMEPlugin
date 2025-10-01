# BFME Plugin
A simple plugin for BFME that allows you to traverse ini code more easily

In order for this to work you should add you entire mod folder to sublime text so that the plugin can crawl it.

When you open Sublime Text or if you've made a lot of changes, you may want to re-index the project to get the correct locations. You can do this from the command palette with `BFME: Reindex project` or from the right click context menu.

## Features
Once you have indexed you mod you have access to the following functionalities:
- Go To Definition: Select a word and then right click -> Go To Definition to go to the source of that reference. E.g Using this on a button a commandset will take you to the commandbutton definition. This also works for strings. Make sure that your text cursor is on the correct word
- Go To Include: Follow an include statement to the correct file
- Symbol Browser: List of all indexed symbols, allows you to filter by type or just search
- Macro Preview: When hovering on a macro, the plugin will display the indexed value of that macro
- Basic Highlighting: Once installed you can select SageIni from the list of file types in the bottom right corner
- Autocomplete symbols: Autocomplete with indexed symbols
- Autocomplete behaviors: Autocomplete behavior creation and parameters

This small plugin is experimental, it will probably change. 

## Installing
- Download `BFMEPlugin.sublime-package`
- Locate your Packages directory:
 - In Sublime Text, go to Preferences → Browse Packages…
- Move up one level into the Installed Packages/ folder (sibling to Packages/).
 - If it doesn’t exist, create it manually.
- Copy your .sublime-package file into Installed Packages/.
- Restart Sublime Text. Your plugin should now load like a normal package.

## Demo
https://www.youtube.com/watch?v=Dj3Kp03-mco
