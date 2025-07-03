import pytest
import subprocess
import os
import yaml

def test_docker_compose_ctfd_ipython_mount():
    """Test that the docker-compose.yml contains the correct volume mount for ipython persistence"""
    
    # Load and parse the docker-compose.yml file
    with open('/home/runner/work/dojo/dojo/docker-compose.yml', 'r') as f:
        compose_config = yaml.safe_load(f)
    
    # Check that the ctfd service exists
    assert 'ctfd' in compose_config['services'], "ctfd service should exist in docker-compose.yml"
    
    # Check that the ctfd service has volumes
    ctfd_service = compose_config['services']['ctfd']
    assert 'volumes' in ctfd_service, "ctfd service should have volumes"
    
    # Check that the ipython volume mount is present
    volumes = ctfd_service['volumes']
    ipython_mount = "/data/ctfd-ipython:/root/.ipython"
    assert ipython_mount in volumes, f"ctfd service should have ipython volume mount: {ipython_mount}"

def test_dojo_init_creates_ctfd_ipython_directory():
    """Test that the dojo-init script creates the ctfd-ipython directory"""
    
    # Read the dojo-init script
    with open('/home/runner/work/dojo/dojo/dojo/dojo-init', 'r') as f:
        init_script = f.read()
    
    # Check that the script creates the ctfd-ipython directory
    assert "mkdir -p /data/ctfd-ipython" in init_script, "dojo-init should create /data/ctfd-ipython directory"

def test_flask_command_exists():
    """Test that the dojo flask command exists and has correct implementation"""
    
    # Read the dojo script
    with open('/home/runner/work/dojo/dojo/dojo/dojo', 'r') as f:
        dojo_script = f.read()
    
    # Check that the flask command exists
    assert '"flask")' in dojo_script, "dojo script should have flask command"
    assert 'docker exec $DOCKER_ARGS ctfd flask shell' in dojo_script, "flask command should execute flask shell in ctfd container"