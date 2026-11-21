#!/usr/bin/env python3
"""
zeal-dotnet-docsets: build Dash/Zeal docsets from Microsoft's official .NET documentation.

Docsets:
  dotnet      .NET (class library + Microsoft.Extensions)    repo: dotnet/dotnet-api-docs
  aspnetcore  ASP.NET Core                                  repo: dotnet/AspNetApiDocs
  efcore      EF Core                                       repo: dotnet/EntityFramework.ApiDocs
  csharp      C# language (reference, fundamentals...)      repo: dotnet/docs

Requirements:
  git, Python 3.10+, pip install markdown lxml pyyaml   (optional: pillow for icons)

Examples:
  ./zeal_dotnet_docsets.py                       # all docsets, .NET 10, install into Zeal
  ./zeal_dotnet_docsets.py --version 11          # another .NET version
  ./zeal_dotnet_docsets.py --only efcore csharp  # selected docsets only
  ./zeal_dotnet_docsets.py --tgz ~/docsets       # write .tgz archives instead of installing

Source repositories are cached in ~/.cache/zeal-dotnet-docsets. The first download
is about 1 GB, later runs only fetch changes. Restart Zeal after installing
(pkill zeal), because it loads docsets only at startup.
"""
import argparse
import html
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
from collections import defaultdict
from pathlib import Path

try:
    import markdown
    import yaml
    from lxml import etree
except ImportError as e:  # pragma: no cover
    sys.exit(f"Missing module: {e.name}. Install it with: pip install markdown lxml pyyaml")

# --------------------------------------------------------------------------- repos

REPOS = {
    "apidocs": ("https://github.com/dotnet/dotnet-api-docs.git", ["/xml/", "/snippets/csharp/"]),
    "aspnet": ("https://github.com/dotnet/AspNetApiDocs.git", ["/aspnet-core/xml/"]),
    "ef": ("https://github.com/dotnet/EntityFramework.ApiDocs.git", ["/dotnet/xml/"]),
    "docs": ("https://github.com/dotnet/docs.git",
             ["/docs/csharp/", "!/docs/csharp/language-reference/compiler-messages/", "/includes/"]),
}
NEEDS = {"dotnet": ["apidocs"], "aspnetcore": ["aspnet", "apidocs"],
         "efcore": ["ef", "apidocs"], "csharp": ["docs"]}

PATHS = {}  # name -> local checkout


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def sync_repo(name, cache):
    url, sparse = REPOS[name]
    d = cache / name
    if not (d / ".git").is_dir():
        log(f"[{name}] cloning {url} (the first run takes a few minutes)...")
        if d.exists():
            shutil.rmtree(d)
        git("clone", "--depth", "1", "--filter=blob:none", "--sparse", url, str(d))
        git("sparse-checkout", "set", "--no-cone", *sparse, cwd=d)
    else:
        log(f"[{name}] updating...")
        git("sparse-checkout", "set", "--no-cone", *sparse, cwd=d)
        git("fetch", "--depth", "1", "origin", cwd=d)
        git("reset", "--hard", "FETCH_HEAD", cwd=d)
    PATHS[name] = d


def make_configs(v):
    return {
        "dotnet": dict(name=f".NET {v}", ident=f"NET_{v}", keyword="dotnet", moniker=f"net-{v}.0",
                       index=[PATHS["apidocs"] / f"xml/FrameworksIndex/net-{v}.0.xml",
                              PATHS["apidocs"] / f"xml/FrameworksIndex/net-{v}.0-pp.xml"],
                       roots=[PATHS["apidocs"]]),
        "aspnetcore": dict(name=f"ASP.NET Core {v}", ident=f"ASPNET_Core_{v}", keyword="aspnet",
                           moniker=f"aspnetcore-{v}.0",
                           index=[PATHS["aspnet"] / f"aspnet-core/xml/FrameworksIndex/aspnetcore-{v}.0.xml"],
                           roots=[PATHS["aspnet"] / "aspnet-core", PATHS["apidocs"]]),
        "efcore": dict(name=f"EF Core {v}", ident=f"EF_Core_{v}", keyword="efcore", moniker=f"efcore-{v}.0",
                       index=[PATHS["ef"] / f"dotnet/xml/FrameworksIndex/efcore-{v}.0.xml"],
                       roots=[PATHS["ef"] / "dotnet", PATHS["apidocs"]]),
    }


def docs_repo():
    return PATHS["docs"]


def csharp_src():
    return PATHS["docs"] / "docs/csharp"


# =========================================================================== API reference docsets

LEARN = "https://learn.microsoft.com/dotnet/api/"

CSS = """
body{font:15px/1.5 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1b1b1b;max-width:960px;margin:0 auto;padding:16px 24px 64px}
a{color:#0b63c5;text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:26px;margin:8px 0 4px}h2{font-size:20px;border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:32px}
h3{font-size:16px;margin:24px 0 6px}h4{font-size:14px;margin:14px 0 4px;color:#444}
.meta{color:#555;font-size:13px}
pre{background:#f5f5f5;border:1px solid #e3e3e3;border-radius:4px;padding:10px 12px;overflow-x:auto;font:13px/1.45 "JetBrains Mono",Consolas,monospace}
code{font:13px "JetBrains Mono",Consolas,monospace;background:#f1f1f1;padding:1px 4px;border-radius:3px}
pre code{background:none;padding:0}
.sig{background:#eef4fb;border-color:#d3e3f5}
table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #ddd;padding:4px 8px;vertical-align:top;text-align:left}
th{background:#fafafa}
td:first-child{width:32%;word-break:break-word}
.sig code{white-space:pre-wrap;word-break:break-word}
.member{border-top:1px solid #eee;padding-top:6px}
blockquote{border-left:4px solid #8ab4e8;margin:8px 0;padding:4px 12px;background:#f6f9fd}
dl dt{font-weight:600;margin-top:6px}dl dd{margin-left:18px}
.src{font-size:12px;color:#777;margin-top:40px}
@media (prefers-color-scheme: dark){
body{background:#1e1e1e;color:#ddd}a{color:#6cb0ff}pre{background:#252526;border-color:#333}
code{background:#2d2d2d}.sig{background:#1f2a38;border-color:#2b3d52}td,th{border-color:#444}th{background:#2a2a2a}
h2{border-color:#444}.meta,.src{color:#999}.member{border-color:#333}blockquote{background:#22272e;border-color:#3d6aa3}}
"""

KIND_RE = re.compile(r"\b(class|struct|interface|enum|delegate|record)\b")


# ----------------------------------------------------------------- helpers

def docid_to_learn(docid):
    """T:System.Collections.Generic.List`1 -> learn url (best effort)."""
    kind, _, rest = docid.partition(":")
    rest = rest.split("(")[0]
    rest = rest.rstrip("*")
    rest = re.sub(r"``?\d+", lambda m: "-" + m.group(0).lstrip("`"), rest)
    rest = rest.replace("+", ".").replace("#ctor", "-ctor").replace("#cctor", "-cctor")
    return LEARN + rest.lower()


def safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s.replace("`", "-").replace("+", "."))


class Snippets:
    def __init__(self, root):
        self.root = root
        self.cache = {}

    def get(self, rel, sid):
        rel = rel.replace("~/", "")
        path = self.root / rel
        if not path.is_file():
            return None
        key = str(path)
        if key not in self.cache:
            try:
                self.cache[key] = path.read_text(encoding="utf-8-sig", errors="replace")
            except Exception:
                return None
        text = self.cache[key]
        if sid:
            names = [sid, "Snippet" + sid] if not sid.lower().startswith("snippet") else [sid]
            for n in names:
                m = re.search(r"//\s*<" + re.escape(n) + r">\s*\n(.*?)//\s*</" + re.escape(n) + r">",
                              text, re.S | re.I)
                if m:
                    code = m.group(1)
                    # drop nested snippet markers
                    code = re.sub(r"^[ \t]*//\s*</?Snippet\w*>[ \t]*\n", "", code, flags=re.M | re.I)
                    return dedent(code)
            return None
        code = re.sub(r"^[ \t]*//\s*</?Snippet\w*>[ \t]*\n", "", text, flags=re.M | re.I)
        return dedent(code)


def gkey(name):
    """Member group key: drop generic arguments (Where<TSource> -> Where)."""
    return re.sub(r"<[^<>]*(<[^<>]*>[^<>]*)*>$", "", name or "")


def dedent(code):
    lines = code.rstrip().split("\n")
    ind = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    n = min(ind) if ind else 0
    return "\n".join(l[n:] for l in lines).strip("\n")


# ----------------------------------------------------------------- generator

class Gen:
    def __init__(self, cfg, outdir):
        self.cfg = cfg
        self.moniker = cfg["moniker"]
        self.out = Path(outdir) / (cfg["ident"] + ".docset")
        self.docs = self.out / "Contents/Resources/Documents"
        self.snip = Snippets(PATHS["apidocs"])
        self.type_ids = {}          # docid -> namespace
        self.member_ids = set()
        self.ns_types = defaultdict(list)
        self.type_files = {}        # docid -> path
        self.page_of = {}           # type docid -> relative page path
        self.member_anchor = {}     # member docid -> (type docid, anchor)
        self.entries = []
        self.md = markdown.Markdown(extensions=["fenced_code", "tables", "sane_lists"])

    # ---- index
    def load_index(self):
        for f in self.cfg["index"]:
            if not f.is_file():
                log("missing index", f)
                continue
            tree = etree.parse(str(f))
            for ns in tree.iter("Namespace"):
                nsname = ns.get("Name")
                if self.is_internal_ns(nsname):
                    continue
                for t in ns.iter("Type"):
                    tid = t.get("Id")
                    if tid in self.type_ids:
                        continue
                    self.type_ids[tid] = nsname
                    self.ns_types[nsname].append(tid)
                    for m in t.iter("Member"):
                        self.member_ids.add(m.get("Id"))
        log(f"index: {len(self.ns_types)} namespaces, {len(self.type_ids)} types, {len(self.member_ids)} members")

    @staticmethod
    def is_internal_ns(ns):
        return ns.endswith(".Internal") or ".Internal." in ns

    def is_internal_member(self, m):
        if ".Internal." in (m.get("MemberName") or ""):
            return True
        summ = m.find("Docs/summary")
        if summ is not None:
            t = " ".join("".join(summ.itertext()).split())
            if t.startswith("This is an internal API"):
                return True
        return False

    def locate_files(self):
        need = set(self.type_ids)
        for root in self.cfg["roots"]:
            xmlroot = root / "xml"
            for ns in {self.type_ids[t] for t in need}:
                d = xmlroot / ns
                if not d.is_dir():
                    continue
                for p in d.glob("*.xml"):
                    with open(p, "rb") as fh:
                        head = fh.read(6000).decode("utf-8", "replace")
                    m = re.search(r'Language="DocId" Value="(T:[^"]+)"', head)
                    if m and m.group(1) in need and m.group(1) not in self.type_files:
                        self.type_files[m.group(1)] = p
            need -= set(self.type_files)
        log(f"located {len(self.type_files)} type files, {len(need)} missing")
        for tid, p in self.type_files.items():
            ns = self.type_ids[tid]
            self.page_of[tid] = f"{safe(ns)}/{safe(p.stem)}.html"

    # ---- framework filter
    def applies(self, el):
        fa = el.get("FrameworkAlternate")
        return fa is None or self.moniker in fa.split(";")

    def pick(self, parent, tag, lang):
        cands = [e for e in parent.findall(tag) if e.get("Language") == lang]
        for e in cands:
            if self.applies(e) and e.get("FrameworkAlternate"):
                return e
        for e in cands:
            if self.applies(e):
                return e
        return cands[0] if cands else None

    # ---- links
    def link(self, cref, text=None, from_page=""):
        cref = cref.strip()
        if not re.match(r"^[TMPFEN]:", cref):
            # xref without prefix: try type then member
            for pre in ("T:", "M:", "P:", "F:", "E:"):
                if pre + cref in self.page_of or (pre + cref) in self.member_anchor:
                    cref = pre + cref
                    break
            else:
                cref_star = cref
                base = cref_star.rstrip("*")
                # Type.Member* overload group
                tdoc = "T:" + base.rsplit(".", 1)[0]
                if tdoc in self.page_of:
                    anchor = self.anchor_for(base.rsplit(".", 1)[1])
                    return self._a(self.page_of[tdoc] + "#" + anchor, text or self.pretty(cref), from_page)
                return self._ext(docid_to_learn("T:" + base), text or self.pretty(cref))
        disp = text or self.pretty(cref)
        if cref.startswith("N:"):
            ns = cref[2:]
            if ns in self.ns_types:
                return self._a(f"{safe(ns)}/index.html", disp, from_page)
            return self._ext(LEARN + ns.lower(), disp)
        if cref in self.page_of:
            return self._a(self.page_of[cref], disp, from_page)
        if cref in self.member_anchor:
            tdoc, anchor = self.member_anchor[cref]
            return self._a(self.page_of[tdoc] + "#" + anchor, disp, from_page)
        base = cref.rstrip("*")
        if base.endswith("*") or cref.endswith("*") or cref[0] in "MPFE":
            body = base[2:].split("(")[0]
            tpart, _, mname = body.rpartition(".")
            tdoc = "T:" + tpart
            if tdoc in self.page_of:
                return self._a(self.page_of[tdoc] + "#" + self.anchor_for(mname), disp, from_page)
        return self._ext(docid_to_learn(cref), disp)

    @staticmethod
    def anchor_for(mname):
        if mname in ("#ctor", "ctor", ".ctor"):
            return "m-ctor"
        if mname in ("#cctor", "cctor", ".cctor"):
            return "m-cctor"
        return "m-" + safe(mname.replace("#", "."))

    def _a(self, target, text, from_page):
        depth = from_page.count("/")
        prefix = "../" * depth
        return f'<a href="{prefix}{target}">{html.escape(text)}</a>'

    @staticmethod
    def _ext(url, text):
        if url.startswith("~/") or (url.startswith("/") and not url.startswith("//")):
            url = "https://learn.microsoft.com/" + url.lstrip("~/")
        return f'<a href="{url}">{html.escape(text)}</a>'

    @staticmethod
    def pretty(cref):
        s = cref[2:] if re.match(r"^[A-Z]:", cref) else cref
        s = s.rstrip("*")
        s = s.split("(")[0]
        s = re.sub(r"``?(\d+)", lambda m: "<" + ",".join("T" if int(m.group(1)) == 1 else f"T{i+1}" for i in range(int(m.group(1)))) + ">", s)
        s = s.replace("#ctor", "ctor")
        parts = s.split(".")
        # Type.Member -> keep last two segments for readability
        if cref.startswith(("M:", "P:", "F:", "E:")) or cref.endswith("*"):
            return ".".join(parts[-2:])
        return parts[-1] if len(parts) > 1 else s

    # ---- docs -> html
    def docs_html(self, el, page):
        if el is None:
            return ""
        out = [html.escape(el.text or "")]
        for ch in el:
            out.append(self.node_html(ch, page))
            out.append(html.escape(ch.tail or ""))
        return "".join(out)

    def node_html(self, n, page):
        tag = n.tag if isinstance(n.tag, str) else ""
        if tag == "see" or tag == "seealso":
            if n.get("langword"):
                return f"<code>{html.escape(n.get('langword'))}</code>"
            if n.get("cref"):
                txt = "".join(n.itertext()).strip() or None
                return self.link(n.get("cref"), txt, page)
            if n.get("href"):
                txt = "".join(n.itertext()).strip() or n.get("href")
                return self._ext(n.get("href"), txt)
            return ""
        if tag in ("paramref", "typeparamref"):
            return f"<code><i>{html.escape(n.get('name') or '')}</i></code>"
        if tag == "c":
            return f"<code>{html.escape(''.join(n.itertext()))}</code>"
        if tag == "code":
            lang = (n.get("language") or "").lower()
            if lang and lang not in ("csharp", "cs", "c#"):
                return ""
            return f"<pre><code>{html.escape(dedent(''.join(n.itertext())))}</code></pre>"
        if tag == "para":
            return f"<p>{self.docs_html(n, page)}</p>"
        if tag == "format":
            if n.get("type") == "text/markdown":
                return self.md_html("".join(n.itertext()), page)
            return self.docs_html(n, page)
        if tag == "list":
            t = n.get("type")
            if t == "table":
                rows = []
                hdr = n.find("listheader")
                if hdr is not None:
                    rows.append("<tr>" + "".join(f"<th>{self.docs_html(c, page)}</th>" for c in hdr) + "</tr>")
                for it in n.findall("item"):
                    rows.append("<tr>" + "".join(f"<td>{self.docs_html(c, page)}</td>" for c in it) + "</tr>")
                return "<table>" + "".join(rows) + "</table>"
            tagname = "ol" if t == "number" else "ul"
            items = []
            for it in n.findall("item"):
                term = it.find("term")
                desc = it.find("description")
                body = ""
                if term is not None:
                    body += f"<b>{self.docs_html(term, page)}</b>"
                    if desc is not None:
                        body += " – "
                if desc is not None:
                    body += self.docs_html(desc, page)
                if term is None and desc is None:
                    body = self.docs_html(it, page)
                items.append(f"<li>{body}</li>")
            return f"<{tagname}>{''.join(items)}</{tagname}>"
        if tag in ("b", "i", "em", "strong", "sub", "sup"):
            return f"<{tag}>{self.docs_html(n, page)}</{tag}>"
        if tag == "a":
            return self._ext(n.get("href", "#"), "".join(n.itertext()))
        if tag == "block":
            return f"<blockquote>{self.docs_html(n, page)}</blockquote>"
        if tag == "br":
            return "<br>"
        return self.docs_html(n, page)

    XREF = re.compile(r"<xref:([^>\s]+?)(\?[^>]*)?>")
    XREF_MD = re.compile(r"\[([^\]]*)\]\(xref:([^)\s]+?)(\?[^)]*)?\)")
    TRIPLE = re.compile(r':::code\s+language="([^"]+)"\s+source="([^"]+)"(?:[^:]*?id="([^"]+)")?[^:]*:::')
    OLDCODE = re.compile(r"\[!code-(\w+)\[[^\]]*\]\(([^)#]+)(?:#([^)]+))?\)\]")

    def md_html(self, text, page):
        code_blocks = []

        def stash(lang, src, sid):
            if lang.lower() not in ("csharp", "cs"):
                return ""
            code = self.snip.get(src, sid)
            if not code:
                return ""
            code_blocks.append(code)
            return f"\n\n@@CODE{len(code_blocks)-1}@@\n\n"

        text = self.TRIPLE.sub(lambda m: stash(m.group(1), m.group(2), m.group(3)), text)
        text = self.OLDCODE.sub(lambda m: stash(m.group(1), m.group(2), m.group(3)), text)
        text = re.sub(r"\[!INCLUDE[^\]]*\[[^\]]*\]\([^)]*\)\]", "", text, flags=re.I)
        text = re.sub(r">\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", lambda m: "> **" + m.group(1).capitalize() + ":**", text)
        # fenced code blocks in other languages -> drop
        text = re.sub(r"```(vb|fsharp|cpp|vbnet|powershell|xml)\b.*?```", "", text, flags=re.S | re.I)

        links = []

        def xref(m, label=None):
            uid = m.group(1) if label is None else m.group(2)
            q = (m.group(2) if label is None else m.group(3)) or ""
            uid = urllib.parse.unquote(html.unescape(uid))
            txt = label
            if txt is None:
                pretty = self.pretty(uid)
                if "nameWithType" in q:
                    txt = pretty
                elif "fullName" in q:
                    txt = uid.rstrip("*").split("(")[0]
                else:
                    txt = pretty.split(".")[-1] if not uid.endswith("*") else pretty.split(".")[-1]
            links.append(self.link(uid, txt, page))
            return f"@@LINK{len(links)-1}@@"

        text = self.XREF_MD.sub(lambda m: xref(m, m.group(1)), text)
        text = self.XREF.sub(xref, text)
        self.md.reset()
        out = self.md.convert(text)
        out = re.sub(r"@@LINK(\d+)@@", lambda m: links[int(m.group(1))], out)
        out = re.sub(r"(<p>)?@@CODE(\d+)@@(</p>)?",
                     lambda m: f"<pre><code>{html.escape(code_blocks[int(m.group(2))])}</code></pre>", out)
        out = re.sub(r'href="(?:~)?/(?!/)', 'href="https://learn.microsoft.com/', out)
        # demote headings inside remarks
        out = re.sub(r"<(/?)h2>", r"<\1h4>", out)
        out = re.sub(r"<(/?)h3>", r"<\1h4>", out)
        return out

    # ---- pages
    def type_kind(self, sig):
        m = KIND_RE.search(sig or "")
        k = m.group(1) if m else "class"
        if k == "record":
            k = "struct" if "record struct" in sig else "class"
        return {"class": "Class", "struct": "Struct", "interface": "Interface",
                "enum": "Enum", "delegate": "Delegate"}[k]

    def prepare(self):
        """first pass: member anchors"""
        self.parsed = {}
        for tid, path in self.type_files.items():
            try:
                tree = etree.parse(str(path), etree.XMLParser(remove_blank_text=False, recover=True))
            except Exception as e:
                log("parse fail", path, e)
                continue
            root = tree.getroot()
            self.parsed[tid] = root
            mem = root.find("Members")
            if mem is None:
                continue
            for m in mem.findall("Member"):
                did = self.pick(m, "MemberSignature", "DocId")
                if did is None:
                    continue
                d = did.get("Value")
                if d not in self.member_ids:
                    continue
                self.member_anchor[d] = (tid, self.anchor_for(gkey(m.get("MemberName"))))

    def member_group(self, m):
        mt = (m.findtext("MemberType") or "").strip()
        name = m.get("MemberName")
        if mt == "Constructor":
            return "Constructors", "Constructor"
        if mt == "Method" and name.startswith("op_"):
            return "Operators", "Operator"
        if mt == "Method":
            return "Methods", "Method"
        if mt == "Property":
            return "Properties", "Property"
        if mt == "Field":
            return "Fields", "Field"
        if mt == "Event":
            return "Events", "Event"
        return "Other", "Method"

    def write_type(self, tid, root):
        ns = self.type_ids[tid]
        page = self.page_of[tid]
        tname = html.unescape(root.get("Name"))
        sig_el = self.pick(root, "TypeSignature", "C#")
        sig = sig_el.get("Value") if sig_el is not None else ""
        kind = self.type_kind(sig)
        docs = root.find("Docs")
        asm = root.find("AssemblyInfo/AssemblyName")
        parts = [f"<h1>{html.escape(tname)} {kind.lower()}</h1>",
                 f'<div class="meta">Namespace: {self.link("N:" + ns, ns, page)}'
                 + (f" · Assembly: {html.escape(asm.text)}" if asm is not None else "") + "</div>"]
        parts.append(f'<a name="//apple_ref/cpp/{kind}/{html.escape(tname)}" class="dashAnchor"></a>')
        if docs is not None:
            parts.append(f"<p>{self.docs_html(docs.find('summary'), page)}</p>")
        if sig:
            parts.append(f'<pre class="sig"><code>{html.escape(sig)}</code></pre>')
        base = root.findtext("Base/BaseTypeName")
        if base and base not in ("System.Object",) and kind == "Class":
            parts.append(f'<div class="meta">Inheritance: {html.escape(base)}</div>')
        if docs is not None:
            tps = docs.findall("typeparam")
            if tps:
                parts.append("<h4>Type parameters</h4><dl>" + "".join(
                    f"<dt><code>{html.escape(t.get('name'))}</code></dt><dd>{self.docs_html(t, page)}</dd>" for t in tps) + "</dl>")
            rem = docs.find("remarks")
            rem_html = self.docs_html(rem, page).strip() if rem is not None else ""
            if rem_html and "To be added" not in rem_html[:40]:
                parts.append("<h2>Remarks</h2>" + rem_html)

        self.entries.append((tname, kind, page))

        groups = defaultdict(list)
        mem = root.find("Members")
        if mem is not None:
            for m in mem.findall("Member"):
                did = self.pick(m, "MemberSignature", "DocId")
                if did is None or did.get("Value") not in self.member_ids:
                    continue
                if self.is_internal_member(m):
                    continue
                g, etype = self.member_group(m)
                if kind == "Enum" and g == "Fields":
                    g, etype = "Values", "Value"
                groups[g].append((m, etype))

        order = ["Values", "Constructors", "Properties", "Methods", "Events", "Fields", "Operators", "Other"]
        if kind == "Enum" and groups.get("Values"):
            rows = []
            for m, _ in groups["Values"]:
                mdocs = m.find("Docs")
                rows.append(f"<tr id=\"m-{safe(m.get('MemberName'))}\"><td><code>{html.escape(m.get('MemberName'))}</code></td>"
                            f"<td>{html.escape((m.findtext('MemberValue') or ''))}</td>"
                            f"<td>{self.docs_html(mdocs.find('summary') if mdocs is not None else None, page)}</td></tr>")
                self.entries.append((f"{tname}.{m.get('MemberName')}", "Value", f"{page}#m-{safe(m.get('MemberName'))}"))
            parts.append("<h2>Values</h2><table><tr><th>Name</th><th>Value</th><th>Description</th></tr>"
                         + "".join(rows) + "</table>")
            groups.pop("Values")

        # summary tables
        for g in order:
            if g not in groups:
                continue
            seen = {}
            for m, et in groups[g]:
                nm = gkey(m.get("MemberName"))
                if nm not in seen:
                    seen[nm] = m
            rows = []
            for nm, m in seen.items():
                disp = tname.split("<")[0] if nm in (".ctor", ".cctor") else nm
                mdocs = m.find("Docs")
                anchor = self.anchor_for(nm)
                rows.append(f'<tr><td><a href="#{anchor}">{html.escape(disp)}</a></td>'
                            f"<td>{self.docs_html(mdocs.find('summary') if mdocs is not None else None, page)}</td></tr>")
            parts.append(f"<h2>{g}</h2><table>{''.join(rows)}</table>")

        # details
        if any(g in groups for g in order):
            parts.append("<h2>Member details</h2>")
        for g in order:
            if g not in groups:
                continue
            by_name = defaultdict(list)
            for m, et in groups[g]:
                by_name[gkey(m.get("MemberName"))].append((m, et))
            for nm, items in by_name.items():
                disp = tname.split("<")[0] if nm in (".ctor", ".cctor") else nm
                anchor = self.anchor_for(nm)
                et = items[0][1]
                parts.append(f'<div class="member"><a id="{anchor}"></a>'
                             f'<a name="//apple_ref/cpp/{et}/{html.escape(disp)}" class="dashAnchor"></a>'
                             f"<h3>{html.escape(disp)}</h3>")
                self.entries.append((f"{tname}.{disp}" if nm not in (".ctor", ".cctor") else f"{tname}.{disp}",
                                     et, f"{page}#{anchor}"))
                for m, _ in items:
                    s = self.pick(m, "MemberSignature", "C#")
                    if s is not None:
                        parts.append(f'<pre class="sig"><code>{html.escape(s.get("Value"))}</code></pre>')
                    mdocs = m.find("Docs")
                    if mdocs is None:
                        continue
                    parts.append(f"<p>{self.docs_html(mdocs.find('summary'), page)}</p>")
                    ps = mdocs.findall("param")
                    if ps:
                        parts.append("<h4>Parameters</h4><dl>" + "".join(
                            f"<dt><code>{html.escape(p.get('name') or '')}</code></dt><dd>{self.docs_html(p, page)}</dd>"
                            for p in ps) + "</dl>")
                    for tag, label in (("returns", "Returns"), ("value", "Value")):
                        r = mdocs.find(tag)
                        if r is not None:
                            rh = self.docs_html(r, page).strip()
                            if rh and rh != "To be added.":
                                parts.append(f"<h4>{label}</h4><p>{rh}</p>")
                    exs = mdocs.findall("exception")
                    if exs:
                        parts.append("<h4>Exceptions</h4><dl>" + "".join(
                            f"<dt>{self.link(e.get('cref'), None, page)}</dt><dd>{self.docs_html(e, page)}</dd>"
                            for e in exs if e.get("cref")) + "</dl>")
                    rem = mdocs.find("remarks")
                    if rem is not None:
                        rh = self.docs_html(rem, page).strip()
                        if rh and not rh.startswith("To be added"):
                            parts.append("<h4>Remarks</h4>" + rh)
                parts.append("</div>")

        parts.append(f'<div class="src">Source: <a href="{docid_to_learn(tid)}">learn.microsoft.com</a> · '
                     f"generated from the dotnet API docs (CC BY 4.0)</div>")
        self.write_page(page, tname, "".join(parts))

    def write_page(self, rel, title, body):
        depth = rel.count("/")
        path = self.docs / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        css = "../" * depth + "style.css"
        path.write_text(
            f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f'<link rel="stylesheet" href="{css}"></head><body>{body}</body></html>', encoding="utf-8")

    def write_namespaces(self):
        rows = []
        for ns in sorted(self.ns_types):
            tids = [t for t in self.ns_types[ns] if t in self.parsed]
            if not tids:
                continue
            page = f"{safe(ns)}/index.html"
            items = []
            for t in sorted(tids, key=lambda x: html.unescape(self.parsed[x].get("Name")).lower()):
                r = self.parsed[t]
                d = r.find("Docs")
                sig = self.pick(r, "TypeSignature", "C#")
                kind = self.type_kind(sig.get("Value") if sig is not None else "")
                items.append(f"<tr><td>{self.link(t, html.unescape(r.get('Name')), page)}</td><td>{kind}</td>"
                             f"<td>{self.docs_html(d.find('summary') if d is not None else None, page)}</td></tr>")
            self.write_page(page, ns, f"<h1>{html.escape(ns)} namespace</h1><table>{''.join(items)}</table>")
            self.entries.append((ns, "Namespace", page))
            rows.append(f'<li><a href="{page}">{html.escape(ns)}</a></li>')
        self.write_page("index.html", self.cfg["name"],
                        f"<h1>{html.escape(self.cfg['name'])} API reference</h1>"
                        f"<p class='meta'>Generated from the official .NET API docs (dotnet/dotnet-api-docs, "
                        f"AspNetApiDocs, EntityFramework.ApiDocs), framework moniker <code>{self.moniker}</code>.</p>"
                        f"<ul>{''.join(rows)}</ul>")

    def write_meta(self):
        (self.docs / "style.css").write_text(CSS)
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>{self.cfg['ident']}</string>
<key>CFBundleName</key><string>{self.cfg['name']}</string>
<key>DocSetPlatformFamily</key><string>{self.cfg['keyword']}</string>
<key>isDashDocset</key><true/>
<key>dashIndexFilePath</key><string>index.html</string>
<key>DashDocSetFamily</key><string>dashtoc</string>
<key>isJavaScriptEnabled</key><false/>
</dict></plist>
"""
        (self.out / "Contents/Info.plist").write_text(plist)
        db = self.out / "Contents/Resources/docSet.dsidx"
        if db.exists():
            db.unlink()
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT)")
        con.execute("CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path)")
        con.executemany("INSERT OR IGNORE INTO searchIndex(name, type, path) VALUES (?,?,?)", self.entries)
        con.commit()
        n = con.execute("select count(*) from searchIndex").fetchone()[0]
        con.close()
        log(f"index entries: {n}")

    def run(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.docs.mkdir(parents=True)
        self.load_index()
        self.locate_files()
        self.prepare()
        for i, (tid, root) in enumerate(self.parsed.items()):
            try:
                self.write_type(tid, root)
            except Exception as e:
                log("FAIL", tid, repr(e))
            if i % 500 == 0:
                log(f"  {i}/{len(self.parsed)}")
        self.write_namespaces()
        self.write_meta()
        return self.out



# =========================================================================== C# language docset

LEARN_ROOT = "https://learn.microsoft.com"
SKIP_DIRS = {"roslyn-sdk", "compiler-messages"}

OPS_CHARS = set("+-*/%&|^!~=<>?:.[]()@$,;")


def split_front(text):
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                meta = yaml.safe_load(text[3:end]) or {}
            except Exception:
                meta = {}
            text = text[end + 4:]
    return meta, text


def slugify(value, sep="-"):
    v = re.sub(r"<[^>]+>", "", value)
    v = html.unescape(v).strip().lower()
    v = re.sub(r"[^\w\s-]", "", v)
    return re.sub(r"\s", sep, v)


class CSharpGen:
    def __init__(self, outdir):
        self.out = Path(outdir) / "CSharp.docset"
        self.docs = self.out / "Contents/Resources/Documents"
        self.entries = []
        self.snip_cache = {}
        self.md = markdown.Markdown(extensions=["fenced_code", "tables", "sane_lists", "toc"],
                                    extension_configs={"toc": {"slugify": slugify}})

    # ---------------------------------------------------------------- files
    def articles(self):
        for p in sorted(csharp_src().rglob("*.md")):
            rel = p.relative_to(csharp_src())
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            if "includes" in rel.parts or "snippets" in rel.parts:
                continue
            yield p

    def out_rel(self, p):
        return str(p.relative_to(csharp_src()).with_suffix(".html"))

    # ---------------------------------------------------------------- snippets
    def snippet(self, base_dir, src, sid, rng):
        if src.startswith("~/"):
            path = docs_repo() / src[2:]
        else:
            path = (base_dir / src).resolve()
        if not path.is_file():
            return None
        key = str(path)
        if key not in self.snip_cache:
            self.snip_cache[key] = path.read_text(encoding="utf-8-sig", errors="replace")
        text = self.snip_cache[key]
        if sid:
            m = None
            for n in (sid, "Snippet" + sid, "snippet" + sid):
                m = re.search(r"(?://|#|<!--)\s*<" + re.escape(n) + r">[^\n]*\n(.*?)\n[^\n]*(?://|#|<!--)\s*</"
                              + re.escape(n) + r">", text, re.S)
                if m:
                    break
            if not m:
                m = re.search(r"#region\s+" + re.escape(sid) + r"[^\n]*\n(.*?)\n[^\n]*#endregion", text, re.S)
            if not m:
                return None
            text = m.group(1)
        elif rng:
            lines = text.split("\n")
            sel = []
            for part in rng.split(","):
                a, _, b = part.partition("-")
                a = int(a)
                b = int(b) if b else a
                sel.extend(lines[a - 1:b])
            text = "\n".join(sel)
        text = re.sub(r"^[ \t]*(//|#)\s*</?[A-Za-z0-9_-]+>[ \t]*\n", "", text, flags=re.M)
        return dedent(text)

    # ---------------------------------------------------------------- includes
    def resolve_include(self, base_dir, ref):
        path = docs_repo() / ref[2:] if ref.startswith("~/") else (base_dir / ref).resolve()
        if not path.is_file():
            return "", None
        _, body = split_front(path.read_text(encoding="utf-8-sig", errors="replace"))
        return body, path.parent

    # ---------------------------------------------------------------- link rewrite
    def rewrite_link(self, href, page_src, page_out):
        if href.startswith(("http://", "https://", "mailto:", "#")):
            return href
        if href.startswith("xref:"):
            uid = urllib.parse.unquote(href[5:].split("?")[0]).rstrip("*")
            return LEARN_ROOT + "/dotnet/api/" + uid.lower().replace("`", "-").replace("#ctor", "-ctor")
        path, _, frag = href.partition("#")
        path = path.split("?")[0]
        if path.startswith("/"):
            return LEARN_ROOT + path + (("#" + frag) if frag else "")
        if path.startswith("~/"):
            target = (docs_repo() / path[2:]).resolve()
        else:
            target = (page_src.parent / path).resolve()
        try:
            rel = target.relative_to(csharp_src().resolve())
        except ValueError:
            rel = None
        if rel is not None and target.suffix == ".md" and target.is_file() \
                and not any(part in SKIP_DIRS for part in rel.parts):
            rp = Path(*([".."] * (len(Path(page_out).parts) - 1)), rel.with_suffix(".html"))
            return str(rp) + (("#" + frag) if frag else "")
        if rel is not None and target.suffix in (".yml",):
            return LEARN_ROOT + "/dotnet/csharp/" + str(rel.with_suffix(""))
        # fall back to learn.microsoft.com (works online)
        try:
            repo_rel = target.relative_to((docs_repo() / "docs").resolve())
            return LEARN_ROOT + "/dotnet/" + str(repo_rel.with_suffix("")).replace("/index", "/")
        except ValueError:
            return LEARN_ROOT + "/dotnet/csharp/"

    # ---------------------------------------------------------------- markdown -> html
    CODE = re.compile(r':::code\s+([^\n]*?):::')
    ATTR = re.compile(r'(\w+)="([^"]*)"')
    INCLUDE = re.compile(r"\[!INCLUDE\s*\[[^\]]*\]\(([^)]+)\)\]", re.I)
    OLDCODE = re.compile(r"\[!code-(\w+)\[[^\]]*\]\(([^)#]+)(?:#([^)]+))?\)\]")

    def preprocess(self, text, base_dir, depth=0):
        def inc(m):
            if depth > 3:
                return ""
            body, d = self.resolve_include(base_dir, m.group(1).strip())
            return self.preprocess(body, d, depth + 1) if d else ""

        text = self.INCLUDE.sub(inc, text)

        blocks = self._blocks

        def code(m):
            a = dict(self.ATTR.findall(m.group(1)))
            lang = a.get("language", "csharp").lower()
            if lang not in ("csharp", "cs", "c#"):
                return ""
            c = self.snippet(base_dir, a.get("source", ""), a.get("id"), a.get("range"))
            if not c:
                return ""
            blocks.append(c)
            return f"\n\n@@CODE{len(blocks)-1}@@\n\n"

        text = self.CODE.sub(code, text)

        def oldcode(m):
            if m.group(1).lower() not in ("csharp", "cs"):
                return ""
            c = self.snippet(base_dir, m.group(2), m.group(3), None)
            if not c:
                return ""
            blocks.append(c)
            return f"\n\n@@CODE{len(blocks)-1}@@\n\n"

        text = self.OLDCODE.sub(oldcode, text)
        text = re.sub(r"^[ \t]*:::(row|row-end|column|column-end)[^\n]*:::?[ \t]*$", "", text, flags=re.M)
        text = re.sub(r":::image[^\n]*:::", "", text)
        text = re.sub(r':::no-loc text="([^"]*)":::', r"\1", text)
        text = re.sub(r"^>\s*\[!div[^\]]*\]\s*$", "", text, flags=re.M)
        text = re.sub(r">\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]",
                      lambda m: "> **" + m.group(1).capitalize() + ":**", text)
        # fenced code blocks (also indented inside lists) -> stash
        def fence(m):
            indent, lang, body = m.group(1), (m.group(2) or "").lower(), m.group(3)
            if lang and lang not in ("csharp", "cs", "c#", "csharp-interactive"):
                return ""
            lines = [l[len(indent):] if l.startswith(indent) else l for l in body.split("\n")]
            blocks.append(dedent("\n".join(lines)))
            return f"\n\n{indent}@@CODE{len(blocks)-1}@@\n\n"

        text = re.sub(r"^([ \t]*)```[ \t]*([\w#+-]*)[^\n]*\n(.*?)\n[ \t]*```[ \t]*$", fence, text, flags=re.S | re.M)

        # xref links -> html anchors (backticks in uids break markdown)
        def xlink(text_, uid, q=None):
            url = self.rewrite_link("xref:" + uid, None, None)
            label = html.escape(text_)
            label = re.sub(r"`([^`]+)`", r"<code>\1</code>", label)
            return f'<a href="{url}">{label}</a>'

        text = re.sub(r"\[([^\]]*)\]\(xref:([^)\s]+?)(\?[^)]*)?\)",
                      lambda m: xlink(m.group(1) or self.xref_text(m.group(2), m.group(3)), m.group(2)), text)
        text = re.sub(r"<xref:([^>\s]+?)(\?[^>]*)?>",
                      lambda m: xlink(self.xref_text(m.group(1), m.group(2)), m.group(1)), text)
        # strip leading indentation used inside :::column::: blocks
        text = re.sub(r"^ {8}(\[`)", r"\1", text, flags=re.M)
        return text

    @staticmethod
    def xref_text(uid, q):
        uid = urllib.parse.unquote(uid).rstrip("*").split("(")[0]
        parts = uid.replace("`1", "<T>").replace("`2", "<T1,T2>").split(".")
        if q and "fullName" in q:
            return uid
        if q and "nameWithType" in q and len(parts) > 1:
            return ".".join(parts[-2:])
        return parts[-1]

    def render(self, text, page_src, page_out):
        self._blocks = []
        text = self.preprocess(text, page_src.parent)
        text = text.replace("\\<", "&lt;").replace("\\>", "&gt;")
        self.md.reset()
        out = self.md.convert(text)
        blocks = self._blocks
        out = re.sub(r"(<p>)?@@CODE(\d+)@@(</p>)?",
                     lambda m: f"<pre><code>{html.escape(blocks[int(m.group(2))])}</code></pre>", out)
        out = re.sub(r'href="([^"]+)"',
                     lambda m: 'href="' + html.escape(self.rewrite_link(html.unescape(m.group(1)), page_src, page_out)) + '"',
                     out)
        return out

    # ---------------------------------------------------------------- index entries
    def collect_entries(self, page_out, title, out_html, rel):
        self.entries.append((title, "Guide", page_out))
        in_ref = rel.parts[0] == "language-reference"
        for m in re.finditer(r'<h([12]) id="([^"]+)">(.*?)</h\1>', out_html, re.S):
            level, hid, inner = m.groups()
            anchor = page_out if level == "1" else f"{page_out}#{hid}"
            if not in_ref:
                continue
            for code in re.findall(r"<code>(.*?)</code>", inner):
                tok = html.unescape(code).strip()
                if not tok or len(tok) > 24:
                    continue
                if re.fullmatch(r"[a-z@][a-z_ ]*[a-z]|[a-z]", tok):
                    self.entries.append((tok, "Keyword", anchor))
                elif all(c in OPS_CHARS or c.isspace() for c in tok) or re.fullmatch(r"[^\w\s]+\w*|\w+[^\w\s]+", tok):
                    self.entries.append((tok, "Operator", anchor))
            if "operators" in rel.parts:
                plain_h = html.unescape(re.sub(r"<[^>]+>", " ", inner))
                for tok in re.findall(r"(?<![\w\\])([+\-*/%&|^!~=<>?:.\[\]]{1,4})(?![\w])", plain_h):
                    if tok in ("-", ".", ":", "?:") and "operator" not in plain_h.lower():
                        continue
                    self.entries.append((tok, "Operator", anchor))
            if level == "2":
                plain = re.sub(r"<[^>]+>", "", inner).strip()
                if plain and plain.lower() not in ("see also", "c# language specification", "examples", "example"):
                    self.entries.append((f"{title} – {html.unescape(plain)}", "Section", anchor))

    def keyword_index(self):
        """Keyword entries from language-reference/keywords/index.md links."""
        p = csharp_src() / "language-reference/keywords/index.md"
        _, body = split_front(p.read_text(encoding="utf-8"))
        for kw, href in re.findall(r"\[`([^`]+)`\]\(([^)]+)\)", body):
            path, _, frag = href.partition("#")
            target = (p.parent / path).resolve()
            try:
                rel = target.relative_to(csharp_src().resolve()).with_suffix(".html")
            except ValueError:
                continue
            if (self.docs / rel).is_file():
                self.entries.append((kw, "Keyword", str(rel) + (("#" + frag) if frag else "")))

    # ---------------------------------------------------------------- toc
    def toc_html(self):
        data = yaml.safe_load((csharp_src() / "toc.yml").read_text(encoding="utf-8"))

        def walk(items):
            out = []
            for it in items or []:
                name = html.escape(str(it.get("name", "")))
                href = it.get("href")
                link = name
                if href and href.endswith(".md"):
                    rel = Path(href).with_suffix(".html")
                    if (self.docs / rel).is_file():
                        link = f'<a href="{rel}">{name}</a>'
                sub = walk(it.get("items"))
                if link == name and not sub:
                    continue
                out.append(f"<li>{link}{sub}</li>")
            return f"<ul>{''.join(out)}</ul>" if out else ""

        return walk(data.get("items"))

    # ---------------------------------------------------------------- main
    def page(self, rel_out, title, body):
        depth = len(Path(rel_out).parts) - 1
        path = self.docs / rel_out
        path.parent.mkdir(parents=True, exist_ok=True)
        css = "../" * depth + "style.css"
        path.write_text(f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
                        f'<link rel="stylesheet" href="{css}"></head><body>{body}</body></html>', encoding="utf-8")

    def run(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.docs.mkdir(parents=True)
        arts = list(self.articles())
        log(f"{len(arts)} articles")
        for i, p in enumerate(arts):
            rel = p.relative_to(csharp_src())
            rel_out = self.out_rel(p)
            meta, body = split_front(p.read_text(encoding="utf-8-sig", errors="replace"))
            try:
                out = self.render(body, p, rel_out)
            except Exception as e:
                log("FAIL", rel, repr(e))
                continue
            h1 = re.search(r"<h1[^>]*>(.*?)</h1>", out, re.S)
            title = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else str(meta.get("title", rel.stem))
            title = html.unescape(title)
            title = re.sub(r"\s*(-\s*C# (language )?reference|\(C# (language )?reference\))$", "", title)
            src_url = LEARN_ROOT + "/dotnet/csharp/" + str(rel.with_suffix("")).replace("\\", "/")
            # dash anchors for in-page TOC
            out = re.sub(r'(<h2 id="([^"]+)">(.*?)</h2>)',
                         lambda m: f'<a name="//apple_ref/cpp/Section/{urllib.parse.quote(re.sub("<[^>]+>", "", m.group(3)))}" '
                                   f'class="dashAnchor"></a>{m.group(1)}', out)
            self.page(rel_out, title, out + f'<div class="src">Source: <a href="{src_url}">learn.microsoft.com</a> · '
                                          f'dotnet/docs (CC BY 4.0)</div>')
            self.collect_entries(rel_out, title, out, rel)
            if i % 200 == 0:
                log(f"  {i}/{len(arts)}")
        self.keyword_index()
        self.page("index.html", "C#",
                  "<h1>C# documentation</h1><p class='meta'>Generated from dotnet/docs (docs/csharp). "
                  "Search keywords (<code>record</code>, <code>switch</code>), operators (<code>??=</code>) or topics.</p>"
                  + self.toc_html())
        (self.docs / "style.css").write_text(CSS)
        (self.out / "Contents/Info.plist").write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>CSharp</string>
<key>CFBundleName</key><string>C#</string>
<key>DocSetPlatformFamily</key><string>csharp</string>
<key>isDashDocset</key><true/>
<key>dashIndexFilePath</key><string>index.html</string>
<key>DashDocSetFamily</key><string>dashtoc</string>
<key>isJavaScriptEnabled</key><false/>
</dict></plist>
""")
        db = self.out / "Contents/Resources/docSet.dsidx"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT)")
        con.execute("CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path)")
        con.executemany("INSERT OR IGNORE INTO searchIndex(name,type,path) VALUES (?,?,?)", self.entries)
        con.commit()
        log("entries", con.execute("select type,count(*) from searchIndex group by type").fetchall())
        con.close()
        return self.out




# --------------------------------------------------------------------------- icons / packaging

ICONS = {"dotnet": ("#512BD4", ".N"), "aspnetcore": ("#0E7C86", "A"),
         "efcore": ("#B83280", "EF"), "csharp": ("#68217A", "C#")}


def write_icons(docset, key):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    col, txt = ICONS[key]
    font_path = None
    for cand in ("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(cand):
            font_path = cand
            break
    for size, name in ((16, "icon.png"), (32, "icon@2x.png")):
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        dr.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=col)
        f = (ImageFont.truetype(font_path, int(size * (0.5 if len(txt) > 1 else 0.7)))
             if font_path else ImageFont.load_default())
        b = dr.textbbox((0, 0), txt, font=f)
        dr.text(((size - (b[2] - b[0])) / 2 - b[0], (size - (b[3] - b[1])) / 2 - b[1]), txt, fill="white", font=f)
        im.save(docset / name)


def default_zeal_dir():
    flatpak = Path.home() / ".var/app/org.zealdocs.Zeal/data/Zeal/Zeal/docsets"
    if flatpak.is_dir():
        return flatpak
    xdg = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return xdg / "Zeal/Zeal/docsets"


def main():
    ap = argparse.ArgumentParser(description="Build Zeal/Dash docsets for .NET, ASP.NET Core, EF Core and C#.")
    ap.add_argument("--version", default="10", help=".NET version (default: 10)")
    ap.add_argument("--only", nargs="+", choices=list(NEEDS), default=list(NEEDS),
                    help="docsets to build (default: all)")
    ap.add_argument("--install-dir", type=Path, default=None,
                    help="Zeal docset folder (default: auto-detected)")
    ap.add_argument("--tgz", type=Path, default=None, help="write .tgz archives to this folder instead of installing")
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache/zeal-dotnet-docsets",
                    help="where to keep the source repositories")
    ap.add_argument("--no-update", action="store_true", help="use cached repositories, do not fetch from GitHub")
    args = ap.parse_args()

    if shutil.which("git") is None:
        sys.exit("git is not installed.")
    args.cache.mkdir(parents=True, exist_ok=True)
    for name in REPOS:
        PATHS[name] = args.cache / name
    for name in sorted({r for k in args.only for r in NEEDS[k]}):
        d = args.cache / name
        if args.no_update and (d / ".git").is_dir():
            PATHS[name] = d
        else:
            sync_repo(name, args.cache)

    configs = make_configs(args.version)
    for key in args.only:
        if key != "csharp":
            missing = [str(p) for p in configs[key]["index"][:1] if not p.is_file()]
            if missing:
                log(f"[{key}] no index for version {args.version} ({missing[0]}), skipping")
                continue

        with tempfile.TemporaryDirectory(prefix="docset-") as tmp:
            log(f"[{key}] generating...")
            docset = CSharpGen(tmp).run() if key == "csharp" else Gen(configs[key], tmp).run()
            write_icons(docset, key)
            if args.tgz:
                args.tgz.mkdir(parents=True, exist_ok=True)
                target = args.tgz / (docset.name.removesuffix(".docset") + ".tgz")
                with tarfile.open(target, "w:gz") as tf:
                    tf.add(docset, arcname=docset.name)
                log(f"[{key}] saved {target}")
            else:
                dest_dir = args.install_dir or default_zeal_dir()
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / docset.name
                staging = dest_dir / (docset.name + ".new")
                if staging.exists():
                    shutil.rmtree(staging)
                shutil.copytree(docset, staging)
                if dest.exists():
                    shutil.rmtree(dest)
                staging.rename(dest)
                log(f"[{key}] installed {dest}")

    if not args.tgz:
        log("Done. Restart Zeal to load the docsets:  pkill zeal; zeal &")


if __name__ == "__main__":
    main()
