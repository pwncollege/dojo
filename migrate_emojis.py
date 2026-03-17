from dojo_plugin.models import Emojis
from CTFd.models import db

def migrate():
    for award in Emojis.query.all():
        if len(award.name) == 1:
            award.icon = award.name
            award.name = "CUSTOM"
            if ":CUSTOM_AWARD:" in award.description:
                dojo_id, description = award.description.split(":CUSTOM_AWARD:")
                award.description = description
                award.category = dojo_id