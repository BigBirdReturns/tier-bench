Example environment value: `no_proxy=fe11::/16`.

Reproduction:

```console
no_proxy=fe11::/16 python -c 'import httpx; c = httpx.Client()'
```

With HTTPX 0.27.0 this raises while constructing the client's proxy mounts:

```text
ValueError: invalid literal for int() with base 10: ':'
...
httpx.InvalidURL: Invalid port: ':'
```

The intended behavior is that an IPv6 prefix-style `no_proxy` value is accepted
and bypasses the proxy for addresses within that network, without regressing the
existing hostname, IPv4, IPv6-address, wildcard, scheme, port, or mount ordering
behavior.
