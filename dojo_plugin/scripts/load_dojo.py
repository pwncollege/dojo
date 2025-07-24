import argparse
import CTFd.utils.user
import sys
import os

from ..utils.dojo import dojo_create, generate_ssh_keypair
from ..models import Users, db

# operate outside of a session
class MockSession:
    def get(self, k, default=None):
        if k == "id":
            return 1
        return default
    __getitem__ = get
CTFd.utils.user.session = MockSession()

parser = argparse.ArgumentParser(description="Load a dojo into the DOJO.")
parser.add_argument(
    '--user', default="1",
    help="the dojo user who will own this dojo, either username or UID (default: UID 1)"
)
parser.add_argument('--private-key', help="private key of the deploy key for the dojo", default="")
parser.add_argument('--public-key', help="public key of the deploy key for the dojo", default="")
parser.add_argument('--official', help="mark the dojo as official", action="store_true")
parser.add_argument('location', type=str, help="the location to load. Can be a yml spec or a github repository URL.")
try:
    args = parser.parse_args()
except SystemExit as e:
    os._exit(e.args[0])

try:
    user = Users.query.where(Users.id == int(args.user)).one()
except ValueError:
    user = Users.query.where(Users.name == args.user).one()

if os.path.isfile(args.location):
    spec = open(args.location).read()
    repository = ""
else:
    spec = ""
    repository = args.location

assert bool(args.public_key) == bool(args.private_key), "Both the private and public key must be provided, or both must be excluded."
if args.public_key:
    public_key, private_key = args.public_key, args.private_key
else:
    public_key, private_key = generate_ssh_keypair()

dojo = dojo_create(user, repository, public_key, private_key, spec)
if args.official:
    dojo.official = True
db.session.commit()
