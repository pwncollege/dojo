# Test Error

The `test_error` namespace is responsible for testing error handling.

***/***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/test_error.py#L12
Accepted Methods: `GET`, `POST`.
Required Parameters: None.
Optional Parameters: None.
Description: This endpoint is responsible for testing the error handler.

****1. Raise Exception (GET)****

```
raise Exception("Test error: This is a deliberate test of the error handler!")
```

This part raises an Exception with the following message: "Test error: This is a deliberate test of the error handler!".

****2. Raise Exception (POST)****

```
raise Exception("Test error: This is a deliberate test of the error handler!")
```

This part raises an Exception with the following message: "Test error: This is a deliberate test of the error handler!".

***/slow_query***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/test_error.py#L25
Accepted Methods: `GET`.
Required Parameters: None.
Optional Parameters: None.
Description: This endpoint is responsible for simulating slow queries.

****1. Query the database****

```
result = db.session.execute(text("SELECT 1, pg_sleep(1)")).fetchone()
```

This part tries to execute the following SQL query on the database:

`"SELECT 1, pg_sleep(1)"`

returns the constant value `1` after sleeping for 1 second.

****2. Return****

```
return {"status": "ok", "result": result[0]}
```

This part returns an `ok` status and the number 1.


***/capped_query***

Location: https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/test_error.py#L33
Accepted Methods: `GET`.
Required Parameters: None.
Optional Parameters: None.
Description: This endpoint is responsible for testing timeouts.

****1. Send request to database****

```
result = query_timeout(Users.query.with_entities(literal(1), func.pg_sleep(5).label("sleep")).all, 500, ["TIMEOUT"])
```

This part of the code waits for half a second, and then times out.

****2. Return****

```
return {"status": "ok", "result": result[0]}
```

This part returns an `ok` status and the word `TIMEOUT`.
