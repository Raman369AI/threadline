# Changelog

## 0.2.0

- Bundle the analyzer and review from Threadline 0.2.0b6, plus its narrow-panel layout fixes: a tonal dark design that follows your VS Code theme,
  endpoints grouped by file, command and task cards, a module browser with a folder tree, previous and next
  method in the file, and Called by and Calls menus whose counts agree with the method summary.
- Show a **Threadline** item in the status bar whenever a Python file is active, so a review is one click
  away before you have opened one.
- Show the editor button and right-click item only on Python files. The commands still work from the
  Command Palette anywhere.
- Rename **Open Review** to **Review Function at Cursor**.
- Let **Review Workspace** start on the first page the project has (endpoints, then commands, then modules)
  instead of always on modules.
- Keep the view tabs visible above the review in a narrow panel; the rest of the sidebar opens from the menu button.
- Add a **Get started with Threadline** walkthrough.

## 0.1.1

- Link the Marketplace listing and fill in the extension's metadata.

## 0.1.0

- First preview: review the function at the cursor, the workspace, or Git changes inside VS Code, with
  source jumps, refresh on save, and HTML export.
