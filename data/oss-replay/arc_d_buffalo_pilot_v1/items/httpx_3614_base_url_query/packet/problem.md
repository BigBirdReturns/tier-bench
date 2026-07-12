A client is configured with a `base_url` that contains a query string:

```python
import httpx

client = httpx.Client(base_url="https://httpbingo.org/get?data=1")
print(client.base_url.query)
response = client.get("")
print(response.json()["args"])
```

Acceptable policy A preserves the base query:

```text
b'data=1'
{'data': ['1']}
```

Acceptable policy B deliberately drops base query parameters:

```text
b''
{}
```

The actual behavior silently mutates the query value:

```text
b'data=1/'
{'data': ['1/']}
```

Diagnose every source location needed for a coherent policy across client
construction and later relative-URL merging. Do not assume that matching one
example is sufficient.
