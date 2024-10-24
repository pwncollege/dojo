source /opt/pwndbg/gdbinit.py
source /opt/splitmind/gdbinit.py

python
import splitmind
(splitmind.Mind()
  .tell_splitter(show_titles=True)
  .tell_splitter(set_title="Main")
  .right(display="backtrace", size="25%")
  .above(of="main", display="disasm", size="80%", banner="top")
  .show("code", on="disasm", banner="none")
  .right(cmd='tty; tail -f /dev/null', size="65%", clearing=False)
  .tell_splitter(set_title='Input / Output')
  .above(display="stack", size="75%")
  .above(display="legend", size="25%")
  .show("regs", on="legend")
  .below(of="backtrace", cmd="ipython", size="30%")
  .show("expressions", on="backtrace")
  .show("args", on="backtrace")
  .show("ghidra", on="backtrace")
).build(nobanner=True)
end

set context-clear-screen on
set follow-fork-mode parent
set context-code-lines 30
set context-source-code-lines 30
# set context-ghidra always
set context-sections  "regs code disasm stack backtrace expressions args ghidra"

shell echo tty $(tmux list-panes -F '#P #{pane_tty}' | grep '^3 ' | cut -d' ' -f2) > /tmp/gdb_tmux
source /tmp/gdb_tmux
