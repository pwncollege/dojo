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
    
    # First test: verify the volume mount is working by creating a simple test file
    test_file_result = dojo_run("exec", "ctfd", "bash", "-c", "echo 'test' > /root/.ipython/test_file && cat /root/.ipython/test_file", check=False)
    print(f"Test file creation in container: {test_file_result.stdout}")
    print(f"Test file error: {test_file_result.stderr}")
    
    # Check if the test file appears on host
    if os.path.exists("/data/ctfd-ipython/test_file"):
        print("Volume mount is working - test file exists on host")
        with open("/data/ctfd-ipython/test_file", "r") as f:
            print(f"Test file content: {f.read()}")
    else:
        print("ERROR: Volume mount is not working - test file does not exist on host")
        # This is a fundamental issue, so let's investigate further
        if os.path.exists("/data/ctfd-ipython"):
            print(f"Directory exists but empty: {os.listdir('/data/ctfd-ipython')}")
        else:
            print("/data/ctfd-ipython directory does not exist")
        
        # Let's check if /data exists at all
        if os.path.exists("/data"):
            print(f"Contents of /data: {os.listdir('/data')}")
        else:
            print("/data directory does not exist")
    
    # Test if flask shell runs at all and what shell it uses
    simple_test = dojo_run("flask", input="print('Hello from flask shell')\nexit()\n", timeout=30, check=False)
    print(f"Simple flask test stdout: {simple_test.stdout}")
    print(f"Simple flask test stderr: {simple_test.stderr}")
    print(f"Simple flask test returncode: {simple_test.returncode}")
    
    # Test if IPython is available and what happens when we try to use it
    ipython_test_commands = [
        "import sys",
        "print('Python executable:', sys.executable)",
        "print('Python version:', sys.version)",
        "print('IPython available:', 'IPython' in sys.modules)",
        "try:",
        "    import IPython",
        "    print('IPython version:', IPython.__version__)",
        "    ipython_instance = IPython.get_ipython()",
        "    if ipython_instance:",
        "        print('IPython instance found')",
        "        print('Profile dir:', ipython_instance.profile_dir.location)",
        "        print('History manager:', type(ipython_instance.history_manager))",
        "    else:",
        "        print('No IPython instance - using regular Python shell')",
        "except ImportError as e:",
        "    print('IPython import failed:', e)",
        "exit()"
    ]
    
    ipython_test_input = "\n".join(ipython_test_commands) + "\n"
    ipython_result = dojo_run("flask", input=ipython_test_input, timeout=30, check=False)
    print(f"IPython test stdout: {ipython_result.stdout}")
    print(f"IPython test stderr: {ipython_result.stderr}")
    
    # Set up paths for the test
    history_dir = "/data/ctfd-ipython/profile_default"
    history_file = f"{history_dir}/history.sqlite"
    
    # Clean up any existing history to start fresh
    if os.path.exists(history_file):
        os.remove(history_file)
    
    # Now try to run some commands that should create history
    history_test_commands = [
        "x = 42",
        "y = x * 2", 
        "print(f'The answer is {x}, double is {y}')",
        "exit()"
    ]
    
    history_input = "\n".join(history_test_commands) + "\n"
    history_result = dojo_run("flask", input=history_input, timeout=30, check=False)
    print(f"History test stdout: {history_result.stdout}")
    print(f"History test stderr: {history_result.stderr}")
    
    # Allow some time for IPython to write the history file
    time.sleep(3)
    
    # Check what was created in the container
    container_files = dojo_run("exec", "ctfd", "find", "/root/.ipython", "-type", "f", check=False)
    print(f"All files in container /root/.ipython: {container_files.stdout}")
    
    # Check what's in the host directory
    if os.path.exists("/data/ctfd-ipython"):
        print(f"Contents of /data/ctfd-ipython: {os.listdir('/data/ctfd-ipython')}")
        if os.path.exists("/data/ctfd-ipython/profile_default"):
            print(f"Contents of /data/ctfd-ipython/profile_default: {os.listdir('/data/ctfd-ipython/profile_default')}")
    else:
        print("/data/ctfd-ipython does not exist")
    
    # Check if there are any sqlite files anywhere in /data
    if os.path.exists("/data"):
        host_find = subprocess.run(["find", "/data", "-name", "*.sqlite"], capture_output=True, text=True)
        print(f"All sqlite files in /data: {host_find.stdout}")
    
    # The actual test - this will fail if the implementation is wrong
    if os.path.exists(history_file):
        print(f"SUCCESS: History file exists at {history_file}")
        file_size = os.path.getsize(history_file)
        print(f"History file size: {file_size} bytes")
        assert file_size > 0, f"IPython history file is empty: {history_file}"
    else:
        print(f"FAILURE: History file not created at {history_file}")
        print("This indicates the implementation is not working correctly")
        # Let's fail with a clear message about what's wrong
        assert False, f"IPython history file not created at {history_file} - flask shell may not be using IPython or volume mount is broken"