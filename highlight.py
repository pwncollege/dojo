import os
from collections import deque

# Add files to look in 
filesToLookIn = ["DESCRIPTION.md"]
# Add words to highlight
wordsToHighlight = ["root", "mv", "rm"]

def highlightWords(file, wordsToHighlight):
    with open(file, "r") as f:
        contents = f.read()

    result = []
    current_word = ""
    for i, ch in enumerate(contents + "0"):
        if ch.isalpha():
            current_word += ch

        if not ch.isalpha():
            if current_word.lower() in wordsToHighlight:
                if ch != "`":
                    current_word = '`' + current_word.lower() + '`'

            result.append(current_word)
            result.append(ch)

            current_word = ""


    with open(file, "w") as f:
        result.pop()
        f.write("".join(result))



queue = deque(os.listdir())

while len(queue) > 0:
    file = queue.pop()
    if os.path.isdir(file):
        for temp_file in os.listdir(file):
            queue.append(os.path.join(file, temp_file))

    elif os.path.basename(file) in filesToLookIn:
        highlightWords(file, wordsToHighlight)

