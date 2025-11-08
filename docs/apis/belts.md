*belts*

This namespace is responsible for returning all users with belts (not including white belts).

***/***


Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/belts.py#L8
Accepted Methods: `GET`.
Required Parameters: None.
Optional Parameters: None.
Description: This endpoint is responsible for returning all users with belts (not including white belts).

****1. Return****

```
return get_belts()
```

This part returns the result of `get_belts`. Because this is the only thing this namespace does, we'll also
look at the `get_belts` function.

***get_belts***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/utils/awards.py#L30
Required Parameters: None.
Optional Parameters: None.
Description: This function returns all users with belts (not including white belts).

****1. Initialize the result dictionary****

```
result = dict(dates={}, users={}, ranks={})
for color in reversed(BELT_ORDER):
    result["dates"][color] = {}
    result["ranks"][color] = []
```

This part creates a dictionary called `result`, with 3 keys:

1. dates - a dictionary containing an empty dictionary for each belt color.
2. users - an empty dictionary.
3. ranks - a dictionary containing an empty list for each belt color.

****2. get belts****

```
belts = (
    Belts.query
    .join(Users)
    .filter(Belts.name.in_(BELT_ORDER), ~Users.hidden)
    .with_entities(
        Belts.date,
        Belts.name.label("color"),
        Users.id.label("user_id"),
        Users.name.label("handle"),
        Users.website.label("site"),
    )
).all()
belts.sort(key=lambda belt: (-BELT_ORDER.index(belt.color), belt.date))
```

This part is responsible for querying the database to get the belts. It returns all non hidden users with a
belt that is in this list:

`[ "orange", "yellow", "green", "purple", "blue", "brown", "red", "black" ]`

Each belt will have the following properties:

1. date - the date when it was earned.
2. color - the belt's color.
3. user_id - the id of the user who earned it.
4. handle - the username of the user who earned it.
5. site - the site of the user who earned it.

After that, we sort the belts from highest to lowest (black to orange), and from oldest to newest.

****3. Update result****

```
for belt in belts:
    result["dates"][belt.color][belt.user_id] = str(belt.date)
    if belt.user_id not in result["users"]:
        result["users"][belt.user_id] = dict(
            handle=belt.handle,
            site=belt.site,
            color=belt.color,
            date=str(belt.date)
        )
        result["ranks"][belt.color].append(belt.user_id)
``` 

This part is responsible for updating the `result` dictionary with our new belt data. We first assign
`result["dates"][belt.color][belt.user_id]` to `belt.date`, and then we check whether we already have an
entry in the `users` dictionary for the current belt's owner. If we don't, we create a new dictionary in the
`users` dictionary with `belt.user_id` as the name. That dictionary will contain `belt.handle`, `belt.site`,
`belt.color` and `belt.date`. After that (we're still in the if statement regarding whether the user is
already in the `users` dictionary or not), we append to `result["ranks"][belt.color]` the id of the belt's
owner.

****4. Return****

```
return result
```

This part returns the result dictionary.
