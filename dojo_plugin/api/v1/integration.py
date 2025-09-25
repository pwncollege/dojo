import logging
import docker

from flask import request, session
from flask_restx import Namespace, Resource

from CTFd.plugins import bypass_csrf_protection

logger = logging.getLogger(__name__)

integrations_namespace = Namespace(
    "integrations", description="Endpoints for external integrations",
    decorators=[bypass_csrf_protection]
)

