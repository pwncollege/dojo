import pytest
import subprocess
import os
import time

from utils import dojo_run


def is_dojo_environment_available():
    """Check if the dojo environment is available for testing"""
    try:
        # Try to run a simple dojo command to check if containers are running
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=ctfd", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10
        )
        return "ctfd" in result.stdout
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        return False


def test_flask_ipython_history_persistence():
    """
    Functional test: Check that you can run `dojo flask`, enter a command, 
    and have a resulting /data/ctfd-ipython/profile_default/history.sqlite file created.
    
    This tests the actual functionality of IPython history persistence rather than 
    just checking configuration files.
    """
    
    # Check if the dojo environment is available
    if not is_dojo_environment_available():
        pytest.skip("Dojo environment (ctfd container) not running - skipping functional test")
    
    # Set up paths for the test
    history_dir = "/data/ctfd-ipython/profile_default"
    history_file = f"{history_dir}/history.sqlite"
    
    # Clean up any existing history to start fresh
    if os.path.exists(history_file):
        os.remove(history_file)
    
    # Ensure the directory exists (should be created by dojo-init)
    os.makedirs(history_dir, exist_ok=True)
    
    # Test commands to run in the flask shell
    # These are simple Python commands that should create IPython history
    test_commands = [
        "# Testing IPython history persistence",
        "x = 42", 
        "print(f'The answer is {x}')",
        "exit()"
    ]
    
    command_input = "\n".join(test_commands) + "\n"
    
    try:
        # Run the flask shell with commands that will create history
        result = dojo_run(
            "flask", 
            input=command_input,
            timeout=60,
            check=False  # Don't fail if flask exits with non-zero (normal for interactive shells)
        )
        
        # Allow some time for IPython to write the history file
        # IPython may write history on exit, so we need to wait
        time.sleep(3)
        
        # Verify that the history file was created
        assert os.path.exists(history_file), (
            f"IPython history file should be created at {history_file} after running flask commands. "
            f"This indicates the volume mount /data/ctfd-ipython:/root/.ipython is working correctly."
        )
        
        # Verify the file has content (should not be empty for a real SQLite database)
        file_size = os.path.getsize(history_file)
        assert file_size > 0, (
            f"IPython history file should not be empty: {history_file} (size: {file_size} bytes). "
            f"This suggests IPython successfully wrote command history to the persistent volume."
        )
        
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
            timeout=60,
            check=False
        )
        
        time.sleep(3)
        
        # Verify that the history file was updated (size should have grown or stayed same)
        final_size = os.path.getsize(history_file)
        assert final_size >= file_size, (
            f"IPython history file should maintain or grow in size after second session. "
            f"Initial: {file_size} bytes, Final: {final_size} bytes. "
            f"This confirms history persistence across flask shell sessions."
        )
        
        print(f"✓ IPython history persistence test passed")
        print(f"  History file: {history_file}")
        print(f"  Final size: {final_size} bytes")
        print(f"  Volume mount /data/ctfd-ipython:/root/.ipython is working correctly")
        
    except subprocess.TimeoutExpired:
        pytest.fail(
            "Flask shell command timed out. This may indicate:\n"
            "1. The ctfd container is not responding\n"
            "2. IPython is hanging waiting for input\n" 
            "3. The flask shell setup has issues"
        )
    except subprocess.CalledProcessError as e:
        pytest.fail(
            f"Flask command failed with exit code {e.returncode}:\n"
            f"stdout: {e.stdout}\n"
            f"stderr: {e.stderr}\n"
            f"This may indicate issues with the ctfd container or flask setup"
        )
    except Exception as e:
        pytest.fail(f"Flask history persistence test failed: {e}")