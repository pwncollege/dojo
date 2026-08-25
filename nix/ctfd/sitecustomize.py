from werkzeug.utils import safe_join

import flask.helpers

flask.helpers.safe_join = safe_join
