"""Remote GUI fixture: records actual text insertion and key release state."""
import tkinter as tk
import json
from pathlib import Path

root = tk.Tk()
root.title('Clipboard integration fixture')
root.geometry('1000x730+0+0')
entry = tk.Text(root, font=('monospace', 18))
entry.pack(fill='both', expand=True)
entry.focus_force()

def terminal_paste(event):
    entry.event_generate('<<Paste>>')
    return 'break'

entry.bind('<Control-Shift-V>', terminal_paste)
entry.bind('<Control-Shift-v>', terminal_paste)
def select_all(event):
    entry.tag_add('sel', '1.0', 'end-1c')
    return 'break'

entry.bind('<Control-a>', select_all)

def report():
    Path('/opt/test/results/clipboard-app.json').write_text(json.dumps({
        'text': entry.get('1.0', 'end-1c'),
        'cursor': len(entry.get('1.0', 'insert')),
    }))
    root.after(50, report)

report()
root.mainloop()
