# Publishing to the MCP Registry

The MCP Registry only hosts metadata; the package itself must live on PyPI
first. One-time setup, then every release is two commands.

## One-time setup

1. Create a [PyPI](https://pypi.org/account/register/) account and an API
   token (`Account settings → API tokens`, scope: whole account or the
   `profili-mcp` project).
2. Tell uv about it — either `$env:UV_PUBLISH_TOKEN = "<token>"` per session,
   or persist it in `%APPDATA%/uv/uv.toml`:

   ```toml
   [[index]]
   name = "pypi"
   url = "https://pypi.org/simple/"
   publish-url = "https://upload.pypi.org/legacy/"
   ```

## Release flow

```bash
# bump version in pyproject.toml and CHANGELOG.md, commit, tag
git tag v0.1.1 && python tools_api_push.py     # or git push when reachable

# publish package + registry metadata
uv build
uv publish                       # uploads the PyPI artifacts
npx mcp-publisher publish        # publishes server.json to the MCP Registry
```

`mcp-publisher` asks for GitHub sign-in the first time; afterwards the
registry verifies the `io.github.GaillumXc/` namespace against this
repository automatically.

> Note: `uv publish` and `npx` need network access to pypi.org and
> registry.modelcontextprotocol.io. On networks where github.com itself is
> blocked, both still work through a local HTTPS proxy.
