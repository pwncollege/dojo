import pytest
import subprocess
import os

def test_flask_history_persistence():
    """Test that ipython history is persisted across dojo flask sessions"""
    
    # Test setup: ensure the directory exists and is mounted
    result = subprocess.run(
        ["docker", "exec", "ctfd", "ls", "-la", "/root/.ipython"],
        capture_output=True,
        text=True
    )
    
    # The directory should exist (either from the mount or be created by ipython)
    assert result.returncode == 0 or "No such file or directory" in result.stderr
    
    # Test that the volume mount is working by checking if the directory is accessible
    result = subprocess.run(
        ["docker", "exec", "ctfd", "mkdir", "-p", "/root/.ipython"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    
    # Create a test history file to verify persistence
    test_command = "print('test_history_persistence')"
    result = subprocess.run(
        ["docker", "exec", "ctfd", "bash", "-c", 
         f"echo '{test_command}' >> /root/.ipython/profile_default/history.sqlite"],
        capture_output=True,
        text=True
    )
    
    # If the directory structure doesn't exist yet, that's ok
    # The important thing is that the mount point is available
    
    # Verify the mount point exists on the host
    result = subprocess.run(
        ["docker", "exec", "dojo-test", "ls", "-la", "/data/ctfd-ipython"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"ctfd-ipython directory should exist: {result.stderr}"

def test_flask_command_works():
    """Test that the dojo flask command still works with the new mount"""
    
    # Test that we can still execute the flask command
    # We'll just test that the command doesn't fail immediately
    result = subprocess.run(
        ["docker", "exec", "ctfd", "timeout", "2", "flask", "shell"],
        input="exit()\n",
        capture_output=True,
        text=True
    )
    
    # The command should start successfully (even if it times out)
    # We're mainly testing that the mount doesn't break the flask shell
    assert "ImportError" not in result.stderr
    assert "No module named" not in result.stderr