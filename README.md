# zeal-dotnet-docsets

Offline [Zeal](https://zealdocs.org/) / [Dash](https://kapeli.com/dash) docsets for modern .NET, built from Microsoft's official documentation sources.

Zeal's built-in catalog only has an old .NET Framework docset. It has nothing for .NET 8+, ASP.NET Core, EF Core or the C# language reference. This script builds all four from the same sources that power learn.microsoft.com.

| Docset | Search prefix | Source |
|---|---|---|
| .NET (class library + `Microsoft.Extensions.*`) | `dotnet:` | [dotnet/dotnet-api-docs](https://github.com/dotnet/dotnet-api-docs) |
| ASP.NET Core | `aspnet:` | [dotnet/AspNetApiDocs](https://github.com/dotnet/AspNetApiDocs) |
| EF Core | `efcore:` | [dotnet/EntityFramework.ApiDocs](https://github.com/dotnet/EntityFramework.ApiDocs) |
| C# language (reference, fundamentals, async, LINQ, what's new) | `csharp:` | [dotnet/docs](https://github.com/dotnet/docs) (`docs/csharp`) |

Examples: `dotnet:TimeProvider`, `aspnet:WebApplication`, `efcore:DbContext.SaveChangesAsync`, `csharp:record`, `csharp:??=`.

## What you get

- **API docsets:** types, constructors, methods, properties, fields, events and operators, filtered to the selected .NET version. Each member has its signature, summary, parameters, return value, exceptions and remarks. The .NET docset also includes C# code examples from the docs' snippet files.
- **C# docset:** about 800 articles. Keywords (`required`, `init`, `yield`…) and operators (`??=`, `?.`, `=>`, `..`) are indexed separately, and there are about 3,000 C# code examples.
- Light and dark theme (follows the system setting).
- Cross-references between types work offline. Links to conceptual articles outside the docset open learn.microsoft.com.

## Requirements

- `git`
- Python 3.10+
- Python packages: `markdown`, `lxml`, `pyyaml`. `pillow` is optional and only used for the docset icons.

```bash
# Arch / CachyOS
sudo pacman -S python-markdown python-lxml python-yaml python-pillow

# any distro, in a virtual environment
python -m venv .venv && .venv/bin/pip install markdown lxml pyyaml pillow
```

## Usage

```bash
./zeal_dotnet_docsets.py                        # all four docsets for .NET 10, installed into Zeal
./zeal_dotnet_docsets.py --only efcore csharp   # selected docsets only
./zeal_dotnet_docsets.py --version 11           # a different .NET version
./zeal_dotnet_docsets.py --tgz ~/docsets        # write .tgz archives instead of installing
```

Zeal loads docsets only at startup, and closing its window just hides it in the tray. Restart it fully after installing:

```bash
pkill zeal; zeal &
```

### Options

| Option | Default | Description |
|---|---|---|
| `--version` | `10` | .NET version (`net-X.0`, `aspnetcore-X.0`, `efcore-X.0`) |
| `--only` | all | Any of `dotnet`, `aspnetcore`, `efcore`, `csharp` |
| `--install-dir` | auto-detected | Zeal docset folder. Detects the Flatpak location (`~/.var/app/org.zealdocs.Zeal/...`) and otherwise uses `~/.local/share/Zeal/Zeal/docsets` |
| `--tgz DIR` | – | Write `.tgz` archives to `DIR` instead of installing |
| `--cache` | `~/.cache/zeal-dotnet-docsets` | Where the source repositories are kept |
| `--no-update` | off | Use the cached repositories without fetching from GitHub |

The first run downloads about 1 GB (shallow, sparse clones) and takes a few minutes. Later runs only fetch changes. Generating all four docsets takes under a minute.

If a version is not available in the source repositories yet, that docset is skipped with a message.

## How it works

1. **Fetch.** Shallow, sparse `git` clones of the four repositories. Only the XML API files, the C# snippets and `docs/csharp` are checked out.
2. **API docsets.** Microsoft publishes API docs as [ECMA XML](https://github.com/dotnet/dotnet-api-docs/wiki). The `FrameworksIndex/<moniker>.xml` file for the chosen version decides which types and members are included. Each type becomes one HTML page. XML doc tags (`<see cref>`, `<paramref>`, `<list>`…) and the Markdown in remarks are converted to HTML, and `:::code` snippet references are resolved from the repository.
3. **C# docset.** The Markdown articles are rendered with includes, snippets and links resolved. Keywords and operators are indexed from the keyword list and from section headings.
4. **Package.** Each docset gets a standard Dash structure: `Info.plist`, a `docSet.dsidx` SQLite search index, `Documents/` and icons.

## Limitations

- **API docsets are reference only.** Conceptual guides for ASP.NET Core and EF Core (tutorials, fundamentals) are not included.
- **EF Core internal APIs are left out on purpose.** That means `*.Internal` namespaces and members marked "This is an internal API".
- **The C# docset is not versioned.** It is always built from the current documentation.
- **Excluded from the C# docset:** compiler error pages (CS0001…) and the Roslyn SDK.
- **Some documentation text is empty upstream.** For example, many explicit interface implementations say "To be added." on learn.microsoft.com too.

## License

The script is released under the MIT License.

The generated docsets contain Microsoft documentation licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), with code samples under the MIT License. Every page links back to its original on learn.microsoft.com. This project is not affiliated with Microsoft.
