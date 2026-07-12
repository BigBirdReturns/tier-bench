# encode/httpx @ ae1b9f66238f75ced3ced5e4485408435de10768
# Curated allowlisted excerpts derived from httpx/_client.py.
# Unrelated lines and some prose are elided; this packet is not a byte slice.
# The complete delivered PROMPT hash, not this upstream blob hash, is the subject authority.
# 13cd9336732a0854dae25b53b34e4b2e749b5897

class BaseClient:
    def _enforce_trailing_slash(self, url: URL) -> URL:
        if url.raw_path.endswith(b"/"):
            return url
        return url.copy_with(raw_path=url.raw_path + b"/")

    @property
    def base_url(self) -> URL:
        """Base URL to use when sending requests with relative URLs."""
        return self._base_url

    @base_url.setter
    def base_url(self, url: URL | str) -> None:
        self._base_url = self._enforce_trailing_slash(URL(url))

    def build_request(
        self,
        method: str,
        url: URL | str,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Request:
        """Build and return a request instance."""
        url = self._merge_url(url)
        headers = self._merge_headers(headers)
        cookies = self._merge_cookies(cookies)
        params = self._merge_queryparams(params)
        extensions = {} if extensions is None else extensions
        if "timeout" not in extensions:
            timeout = (
                self.timeout
                if isinstance(timeout, UseClientDefault)
                else Timeout(timeout)
            )
            extensions = dict(**extensions, timeout=timeout.as_dict())
        return Request(
            method,
            url,
            content=content,
            data=data,
            files=files,
            json=json,
            params=params,
            headers=headers,
            cookies=cookies,
            extensions=extensions,
        )

    def _merge_url(self, url: URL | str) -> URL:
        """
        Merge a URL argument together with any 'base_url' on the client,
        to create the URL used for the outgoing request.
        """
        merge_url = URL(url)
        if merge_url.is_relative_url:
            # To merge URLs we always append to the base URL. To get this
            # behaviour correct we always ensure the base URL ends in a '/'
            # separator, and strip any leading '/' from the merge URL.
            merge_raw_path = self.base_url.raw_path + merge_url.raw_path.lstrip(b"/")
            return self.base_url.copy_with(raw_path=merge_raw_path)
        return merge_url


# Curated existing behavior derived from tests/client/test_client.py.
# 657839018ab3ded203937f970eeeb23f26561775
def test_merge_absolute_url():
    client = httpx.Client(base_url="https://www.example.com/")
    request = client.build_request("GET", "http://www.example.com/")
    assert request.url == "http://www.example.com/"


def test_merge_relative_url():
    client = httpx.Client(base_url="https://www.example.com/")
    request = client.build_request("GET", "/testing/123")
    assert request.url == "https://www.example.com/testing/123"


def test_merge_relative_url_with_path():
    client = httpx.Client(base_url="https://www.example.com/some/path")
    request = client.build_request("GET", "/testing/123")
    assert request.url == "https://www.example.com/some/path/testing/123"


def test_merge_relative_url_with_dotted_path():
    client = httpx.Client(base_url="https://www.example.com/some/path")
    request = client.build_request("GET", "../testing/123")
    assert request.url == "https://www.example.com/some/testing/123"


def test_merge_relative_url_with_path_including_colon():
    client = httpx.Client(base_url="https://www.example.com/some/path")
    request = client.build_request("GET", "/testing:123")
    assert request.url == "https://www.example.com/some/path/testing:123"


def test_merge_relative_url_with_encoded_slashes():
    client = httpx.Client(base_url="https://www.example.com/")
    request = client.build_request("GET", "/testing%2F123")
    assert request.url == "https://www.example.com/testing%2F123"

    client = httpx.Client(base_url="https://www.example.com/base%2Fpath")
    request = client.build_request("GET", "/testing")
    assert request.url == "https://www.example.com/base%2Fpath/testing"
