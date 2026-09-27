"""App-scoped key routing BEFORE Tk widget class bindings.

A bind_all handler runs too late: a focused ttk.Button has already invoked
its command for SPACE. This private tag runs first and consumes setup keys,
including ignored/repeated presses, without changing global Tk bindings.
"""
from __future__ import annotations

import tkinter as tk


class KeyboardRouter:
    SEQUENCES = (
        ("<KeyPress-space>", "space"), ("<KeyPress-Escape>", "esc"),
        ("<KeyPress-r>", "r"), ("<KeyPress-R>", "r"),
        ("<KeyPress-b>", "b"), ("<KeyPress-B>", "b"),
        ("<Control-Shift-KeyPress-A>", "space"),
        ("<Control-Shift-KeyPress-a>", "space"),
        ("<Control-Alt-KeyPress-s>", "stop"),
        ("<Control-Alt-KeyPress-S>", "stop"),
        ("<Control-Shift-KeyPress-Q>", "quit"),
        ("<Control-Shift-KeyPress-q>", "quit"),
    )

    def __init__(self, root, dispatch):
        self.root = root
        self.dispatch = dispatch
        self.tag = "WakeGuardKeys_" + str(id(self))
        self.held = set()
        self.release_jobs = {}
        self.closed = False
        self.functions = []
        for sequence, action in self.SEQUENCES:
            function = root.bind_class(self.tag, sequence,
                lambda event, a=action: self._press(event, a))
            self.functions.append((sequence, function))
        function = root.bind_class(self.tag, "<KeyRelease>", self._release)
        self.functions.append(("<KeyRelease>", function))
        self.attach_tree(root)

    def attach_tree(self, widget):
        """Call explicitly for the dashboard and owned alert windows, NOT dialogs."""
        if self.closed:
            return
        tags = widget.bindtags()
        if self.tag not in tags:
            widget.bindtags((self.tag,) + tags)
        for child in widget.winfo_children():
            # Dialogs keep ordinary entry/combobox/SPACE semantics.
            if child.winfo_toplevel() == widget.winfo_toplevel():
                self.attach_tree(child)

    def _press(self, event, action):
        if self.closed:
            return None
        key = event.keysym.lower()
        pending = self.release_jobs.pop(key, None)
        if pending is not None:
            self.root.after_cancel(pending)
        if key in self.held:
            return "break"
        # Latch before dispatch because a callback may enter a modal event loop.
        self.held.add(key)
        result = self.dispatch(event, action)
        if result != "break":
            self.held.discard(key)
        return result

    def _release(self, event):
        key = event.keysym.lower()
        if self.closed or key not in self.held:
            return None
        previous = self.release_jobs.pop(key, None)
        if previous is not None:
            self.root.after_cancel(previous)
        # Deferred release also coalesces the synthetic release/press pairs
        # produced by X11 auto-repeat. A new deliberate press requires key-up.
        self.release_jobs[key] = self.root.after_idle(lambda: self._released(key))
        return "break"

    def _released(self, key):
        self.release_jobs.pop(key, None)
        self.held.discard(key)

    def close(self):
        if self.closed:
            return
        self.closed = True
        for job in list(self.release_jobs.values()):
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self.release_jobs.clear()
        self.held.clear()
        for sequence, function in self.functions:
            try:
                self.root.unbind_class(self.tag, sequence)
                if function:
                    self.root.deletecommand(function)
            except tk.TclError:
                pass
        self.functions.clear()
