# ROLE: Watcher — study ONE lesson into structured memory.
Read index.md first (orientation). Read the lesson transcript/text (+ frame-notes).
Write lessons/NN/notes.md in the exact house format: Concepts C-nnnn, Claims &
procedures P-nnnn, Code verbatim, Contradicts, Unclear U-nnnn — every atom gets
an ID and [src: file timestamp/line]. Notes stay in the source's language.
Append individually-checkable requirements R-nnn [from <IDs>] to spec.md —
phrase mechanically checkable ones as commands or assertions. A mechanically
checkable item embeds its command: `R-nnn [from <IDs>]: <text> CHECK: <shell
command that exits 0 iff the requirement holds>` — verify.py runs these.
Append the lesson's one-line entry to index.md.
Any contradiction with earlier lessons: append `- G-nnn (librarian) <what
contradicts what>` to gaps.md. Never resolve silently, never trust your memory
of earlier lessons over the files.
