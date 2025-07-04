import subprocess
import os
import time

from utils import dojo_run


def test_flask_ipython_history_persistence():
    """
    Functional test: Check that you can run `dojo flask`, enter a command, 
    and have a resulting /data/ctfd-ipython/profile_default/history.sqlite file created.
    
    This tests the actual functionality of IPython history persistence rather than 
    just checking configuration files.
    """
    
    # Set up paths for the test
    history_dir = "/data/ctfd-ipython/profile_default"
    history_file = f"{history_dir}/history.sqlite"
    
    # Clean up any existing history to start fresh
    if os.path.exists(history_file):
        os.remove(history_file)
    
    # Test commands to run in the flask shell
    # These are simple Python commands that should create IPython history
    test_commands = [
        "# Testing IPython history persistence",
        "x = 42", 
        "print(f'The answer is {x}')",
        "exit()"
    ]
    
    command_input = "\n".join(test_commands) + "\n"
    
    # Run the flask shell with commands that will create history
    result = dojo_run(
        "flask", 
        input=command_input,
        timeout=60
    )
    
    # Allow some time for IPython to write the history file
    # IPython may write history on exit, so we need to wait
    time.sleep(3)
    
    # Verify that the history file was created
    assert os.path.exists(history_file), f"IPython history file not created at {history_file}"
    
    # Verify the file has content (should not be empty for a real SQLite database)
    file_size = os.path.getsize(history_file)
    assert file_size > 0, f"IPython history file is empty: {history_file}"
    
    # Test persistence by running another command and checking the file grows
    second_commands = [
        "# Second session to test persistence",
        "y = 24",
        "print(f'Half the answer is {y}')",
        "exit()"
    ]
    
    second_input = "\n".join(second_commands) + "\n"
    
    dojo_run(
        "flask",
        input=second_input, 
        timeout=60
    )
    
    time.sleep(3)
    
    # Verify that the history file was updated (size should have grown or stayed same)
    final_size = os.path.getsize(history_file)
    assert final_size >= file_size, f"IPython history file should maintain or grow in size after second session"