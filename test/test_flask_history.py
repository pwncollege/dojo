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
    
    # First, let's verify that the mount point exists and debug what's happening
    debug_result = dojo_run("exec", "ctfd", "ls", "-la", "/root", check=False)
    print(f"Contents of /root in ctfd container: {debug_result.stdout}")
    
    # Check if the .ipython directory exists and what's in it
    ipython_check = dojo_run("exec", "ctfd", "ls", "-la", "/root/.ipython", check=False)
    print(f"Contents of /root/.ipython: {ipython_check.stdout}")
    print(f"Error output: {ipython_check.stderr}")
    
    # Check if the mount is working by creating a test file
    mount_test = dojo_run("exec", "ctfd", "touch", "/root/.ipython/test_mount", check=False)
    print(f"Mount test result: {mount_test.returncode}")
    
    # Set up paths for the test
    history_dir = "/data/ctfd-ipython/profile_default"
    history_file = f"{history_dir}/history.sqlite"
    
    # Clean up any existing history to start fresh
    if os.path.exists(history_file):
        os.remove(history_file)
    
    # Test commands to run in the flask shell
    # These are simple Python commands that should create IPython history
    # First, let's check if IPython is actually being used
    test_commands = [
        "import sys",
        "print('Python shell info:')",
        "print(f'Shell: {sys.ps1 if hasattr(sys, \"ps1\") else \"No ps1\"}')",
        "print(f'IPython: {\"IPython\" in sys.modules}')",
        "try:",
        "    import IPython",
        "    print(f'IPython version: {IPython.__version__}')",
        "    print(f'Profile dir: {IPython.get_ipython().profile_dir if IPython.get_ipython() else \"No IPython instance\"}')",
        "except ImportError:",
        "    print('IPython not available')",
        "x = 42", 
        "print(f'The answer is {x}')",
        "exit()"
    ]
    
    command_input = "\n".join(test_commands) + "\n"
    
    # Run the flask shell with commands that will create history
    result = dojo_run(
        "flask", 
        input=command_input,
        timeout=60,
        check=False  # Don't fail if flask exits with non-zero (normal for interactive shells)
    )
    
    print(f"Flask command stdout: {result.stdout}")
    print(f"Flask command stderr: {result.stderr}")
    print(f"Flask command returncode: {result.returncode}")
    
    # Allow some time for IPython to write the history file
    # IPython may write history on exit, so we need to wait
    time.sleep(3)
    
    # Check what was created in the container
    post_run_check = dojo_run("exec", "ctfd", "find", "/root/.ipython", "-name", "*.sqlite", check=False)
    print(f"SQLite files in /root/.ipython: {post_run_check.stdout}")
    
    # Check the entire .ipython directory structure
    ipython_tree = dojo_run("exec", "ctfd", "find", "/root/.ipython", "-type", "f", check=False)
    print(f"All files in /root/.ipython: {ipython_tree.stdout}")
    
    # Check what's in the host directory 
    if os.path.exists("/data/ctfd-ipython"):
        print(f"Contents of /data/ctfd-ipython: {os.listdir('/data/ctfd-ipython')}")
        if os.path.exists("/data/ctfd-ipython/profile_default"):
            print(f"Contents of /data/ctfd-ipython/profile_default: {os.listdir('/data/ctfd-ipython/profile_default')}")
    else:
        print("/data/ctfd-ipython does not exist")
    
    # Let's also check if there are any other sqlite files that might be the history
    host_find = subprocess.run(["find", "/data", "-name", "*.sqlite"], capture_output=True, text=True)
    print(f"All sqlite files in /data: {host_find.stdout}")
    
    # Check if we can create a simple file in the mount to verify it's working
    test_file_result = dojo_run("exec", "ctfd", "bash", "-c", "echo 'test' > /root/.ipython/test_file && cat /root/.ipython/test_file", check=False)
    print(f"Test file creation: {test_file_result.stdout}")
    
    # Check if the test file appears on host
    if os.path.exists("/data/ctfd-ipython/test_file"):
        print("Test file exists on host - mount is working")
        with open("/data/ctfd-ipython/test_file", "r") as f:
            print(f"Test file content: {f.read()}")
    else:
        print("Test file does not exist on host - mount may not be working")
    
    # Verify that the history file was created
    assert os.path.exists(history_file), f"IPython history file not created at {history_file}"
    
    # Verify the file has content (should not be empty for a real SQLite database)
    file_size = os.path.getsize(history_file)
    assert file_size > 0, f"IPython history file is empty: {history_file}"