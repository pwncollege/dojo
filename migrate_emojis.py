from dojo_plugin.models import Emojis
from CTFd.models import db

def migrate():
    for award in Emojis.query.all():
        if len(award.name) == 1: # Emojis with an emoji as the name, change to be CUSTOM and set icon.
            award.icon = award.name
            award.name = "CUSTOM"
            if ":CUSTOM_AWARD:" in award.description: # Set category (origin) for custom awards that were granted.
                dojo_id, description = award.description.split(":CUSTOM_AWARD:")
                award.description = description
                award.category = dojo_id
    db.session.commit()
