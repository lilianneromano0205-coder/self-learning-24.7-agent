#!/usr/bin/env python3
"""THE SOURCE LEDGER — every claim knows where it came from, and what that
source is worth.

Feed an expert forty 500-page PDFs, ten hour-long videos and a pile of blog
posts and one thing is guaranteed: they will not agree. An agent that treats
every sentence it ingested as equally true has not learned a subject, it has
averaged one — which is exactly how confident nonsense gets produced.

So ingestion is not just extraction: every piece of material is recorded with
an AUTHORITY TIER, and the tier is what decides who wins when two sources
contradict each other (see conflicts.py).

  tier 1  normative   the thing itself: specs and standards, a language's
                      own reference, peer-reviewed studies, primary records
  tier 2  professional  recognised practitioner references: vendor product
                      documentation, design systems, established research
                      groups, published books, package registries
  tier 3  instructional  courses, tutorials, conference talks, videos,
                      technical blog posts -- useful, not authoritative
  tier 4  anecdotal   forums, comment threads, content farms, anything
                      whose origin cannot be established

READING is not LEARNING. Tier 3-4 material may be read for context; only
tier 2 and better may become a CITED atom, which is what `learnable()`
decides. The bar is LEARN_MIN_TIER and it moves only when the owner moves
it, in [agent] learn_min_tier -- a lowered bar is always named in the
verdict, so it can never be mistaken for a source that earned its place.

Nothing here is guessed by a model. The tier comes from the URL, the file
kind and an owner-editable table; the owner can always overrule a specific
source, and the overrule is recorded with a reason.

    python sources.py --root <expert> --course design            # the ledger
    python sources.py --root <expert> --classify https://...     # one URL
    python sources.py --learn https://...    # may this become a cited
                                             # atom, or only be read?
    python sources.py --prove                # the built-in table of real
                                             # URLs, and what each is worth
    python sources.py --root <expert> --course design --set S-3 --tier 1 \
        --why "this is the published spec"
"""

import json
import os
import re
import time
from urllib.parse import urlsplit

LEDGER = "sources.json"
TIER_NAMES = {1: "normative", 2: "professional", 3: "instructional",
              4: "anecdotal"}
TIER_WEIGHT = {1: 1.0, 2: 0.8, 3: 0.55, 4: 0.3}

# --------------------------------------------------------------- the registry
#
# Domain -> tier, grouped so every entry carries the REASON it is trusted.
# classify() quotes that reason back verbatim, because a bare number is not
# an explanation, and nothing in this file asks a model to adjudicate.
#
# WHERE THE LINE BETWEEN TIER 1 AND TIER 2 FALLS, so that adding a domain is
# a decision and not a mood:
#
#   tier 1  the DEFINING record -- the document produced by the body that
#           gets to say what the thing IS: a standards body's specification,
#           a language's own reference, the paper itself, the primary record
#           of a vulnerability. Citing it settles the question.
#   tier 2  a PROFESSIONAL DESCRIBING something -- vendor product manuals,
#           design systems, established practitioner references. Excellent
#           material, and still someone's account of a thing rather than the
#           thing itself.
#
# That is why python.org is tier 1 while learn.microsoft.com is tier 2 even
# though both are "official docs": one defines a language through a public
# process, the other is a product manual that can change with a release.
#
# Everything absent from this table falls through to the kind-based default
# rather than pretending to know. An unrecognised origin is not a distrusted
# one, it is an UNKNOWN one, and unknown may not be cited.
REGISTRY = (
    (1, "a standards or treaty body: the document that defines the thing", (
        "w3.org", "whatwg.org", "ietf.org", "rfc-editor.org", "iana.org",
        "iso.org", "iec.ch", "ecma-international.org", "tc39.es",
        "unicode.org", "nist.gov", "itu.int", "khronos.org",
        "oasis-open.org", "openid.net", "who.int")),
    (1, "the primary public record of a vulnerability or weakness", (
        "cve.org", "cwe.mitre.org", "capec.mitre.org", "first.org")),
    (1, "the language or runtime's own reference: the definition of the "
        "thing, not a description of it", (
        "python.org", "nodejs.org", "rust-lang.org", "go.dev", "golang.org",
        "typescriptlang.org", "openjdk.org", "kotlinlang.org", "swift.org",
        "dart.dev", "php.net", "ruby-lang.org", "ruby-doc.org", "perl.org",
        "haskell.org", "isocpp.org", "scala-lang.org", "julialang.org",
        "r-project.org", "llvm.org", "gnu.org", "kernel.org", "git-scm.com",
        "sqlite.org", "postgresql.org", "openssl.org", "curl.se")),
    (1, "peer-reviewed research, or the primary index of it", (
        "doi.org", "acm.org", "ieee.org", "nature.com", "science.org",
        "sciencedirect.com", "springer.com", "wiley.com", "plos.org",
        "jstor.org", "pnas.org", "cell.com", "thelancet.com", "bmj.com",
        "nejm.org", "nih.gov", "ncbi.nlm.nih.gov",
        "pubmed.ncbi.nlm.nih.gov", "europepmc.org")),
    (1, "a preprint server: the paper itself, but NOT peer reviewed -- "
        "demote it in [agent.source_tier] if your field needs review", (
        "arxiv.org", "biorxiv.org", "medrxiv.org", "ssrn.com")),
    (2, "primary vendor documentation for the vendor's own product", (
        "developer.mozilla.org", "web.dev", "developer.chrome.com",
        "developer.apple.com", "developers.google.com", "cloud.google.com",
        "developer.android.com", "firebase.google.com", "microsoft.com",
        "docs.microsoft.com", "learn.microsoft.com", "aws.amazon.com",
        "docker.com", "kubernetes.io", "cloudflare.com", "hashicorp.com",
        "redhat.com", "ubuntu.com", "debian.org", "apache.org", "nginx.org",
        "mongodb.com", "redis.io", "elastic.co", "grafana.com",
        "prometheus.io", "opentelemetry.io", "istio.io", "helm.sh",
        "grpc.io", "protobuf.dev", "stripe.com", "twilio.com",
        "anthropic.com", "openai.com", "vercel.com", "netlify.com",
        "jetbrains.com", "gradle.org", "docs.oracle.com", "docs.gitlab.com",
        "mysql.com", "terraform.io", "ansible.com", "djangoproject.com",
        "flask.palletsprojects.com", "react.dev", "vuejs.org",
        "angular.dev", "svelte.dev", "pytorch.org", "tensorflow.org",
        "scikit-learn.org", "numpy.org", "pandas.pydata.org", "scipy.org",
        "jupyter.org")),
    (2, "an established practitioner reference with editorial standing", (
        "nngroup.com", "a11yproject.com", "material.io", "m3.material.io",
        "carbondesignsystem.com", "polaris.shopify.com", "atlassian.design",
        "primer.style", "spectrum.adobe.com", "smashingmagazine.com",
        "css-tricks.com", "webaim.org", "deque.com", "caniuse.com",
        "cppreference.com", "oreilly.com", "owasp.org", "sans.org",
        "alistapart.com", "martinfowler.com", "refactoring.com")),
    (2, "the official registry of record for a package: authoritative for "
        "WHAT was published, while the page text is publisher-supplied and "
        "unreviewed", (
        "pypi.org", "npmjs.com", "crates.io", "pkg.go.dev", "rubygems.org",
        "nuget.org", "packagist.org", "hex.pm", "hub.docker.com",
        "huggingface.co", "search.maven.org")),
    (3, "instructional material: worth reading, not worth citing", (
        "youtube.com", "youtu.be", "vimeo.com", "udemy.com", "coursera.org",
        "edx.org", "udacity.com", "pluralsight.com", "khanacademy.org",
        "frontendmasters.com", "egghead.io", "medium.com", "dev.to",
        "substack.com", "hashnode.com", "freecodecamp.org", "w3schools.com",
        "digitalocean.com", "baeldung.com", "realpython.com",
        "sitepoint.com", "hackernoon.com")),
    (4, "a content farm: aggregated, SEO-shaped, no editorial review and no "
        "attribution chain to follow", (
        "geeksforgeeks.org", "tutorialspoint.com", "javatpoint.com",
        "guru99.com", "educba.com", "w3resource.com", "codegrepper.com",
        "answers.com", "chegg.com", "coursehero.com", "brainly.com")),
    (4, "an unvetted public forum or social feed: no author of record", (
        "reddit.com", "news.ycombinator.com", "quora.com", "x.com",
        "twitter.com", "facebook.com", "instagram.com", "tiktok.com",
        "linkedin.com", "discord.com", "stackexchange.com", "tumblr.com",
        "pinterest.com", "t.me")),
)

# The old two-column view, kept so anything that walked the table still can.
# REGISTRY above is the single source of truth; this is derived, never edited.
DOMAIN_TIERS = tuple((tier, domains) for tier, _why, domains in REGISTRY)

# domain -> (tier, why). setdefault, so a domain accidentally listed twice
# takes its LOWEST-numbered group deterministically instead of depending on
# which line a later editor happened to add. `--prove` reports duplicates.
_DOMAIN_INDEX = {}
for _tier, _why, _domains in REGISTRY:
    for _domain in _domains:
        _DOMAIN_INDEX.setdefault(_domain, (_tier, _why))

# GitHub is two things wearing one domain: where the CPython team keeps
# CPython, and where anyone keeps anything. Rating github.com as a whole
# would either trust every stranger's repository or distrust the primary
# home of half the software in existence -- so the ORG SEGMENT decides.
#
# Reading a path segment is safe HERE for the same reason the host rule is
# safe: github.com owns its own namespace, so /python/ really is the Python
# organisation and no stranger can spell their way into this set. It is only
# consulted once the HOST is confirmed to be github.com itself, so
# evil.example/github.com/python still never reaches it.
GITHUB_ORGS = frozenset((
    "python", "psf", "nodejs", "denoland", "rust-lang", "golang", "google",
    "googleapis", "googlechrome", "googlecloudplatform", "microsoft",
    "dotnet", "azure", "aws", "awslabs", "awsdocs", "apple", "swiftlang",
    "mozilla", "w3c", "whatwg", "tc39", "ietf", "unicode-org", "kubernetes",
    "docker", "moby", "cloudflare", "hashicorp", "apache", "torvalds",
    "git", "curl", "openssl", "nginx", "redis", "postgres", "mysql",
    "mongodb", "elastic", "grafana", "prometheus", "opentelemetry", "cncf",
    "istio", "helm", "argoproj", "etcd-io", "grpc", "protocolbuffers",
    "facebook", "meta-llama", "reactjs", "vuejs", "angular", "sveltejs",
    "vercel", "django", "pallets", "numpy", "pandas-dev", "scipy",
    "scikit-learn", "pytorch", "tensorflow", "huggingface", "openai",
    "anthropics", "jupyter", "ipython", "rails", "ruby", "php", "laravel",
    "spring-projects", "jetbrains", "kotlin", "gradle", "llvm", "ziglang",
    "systemd", "gnome", "kde", "debian", "canonical", "openshift",
    "ansible", "nixos", "rustsec", "github",
))
# Path segments that turn a repository page into a conversation. A
# maintainer's answer in an issue is still an unreviewed comment thread, and
# an official organisation's issue tracker is not that organisation's
# documentation -- rating it as such is how "someone said so on the internet"
# would enter the ledger wearing a tier-2 badge.
GITHUB_TALK = ("issues", "discussions", "pull", "pulls", "wiki")

# An institutional TLD counts only as the SUFFIX of a host. `.gov` matched
# ANYWHERE in the host let a lookalike inherit the trust it merely names --
# phish.gov.cdn-mirror.io read as institutional -- which is the same
# "trust carried in a component a stranger controls" failure the host rule
# in classify() exists to prevent, one field over.
# Public institutions, by the suffix their country actually uses.
#
# The old pattern was `\.(gov|edu|mil|int)$|\.(ac|edu|gov)\.[a-z]{2}$`, which
# is the United States plus the Commonwealth and nothing else. Measured
# against real bodies, `ec.europa.eu` — the European Commission — came back
# tier 3 with the reason "unrecognised origin", the SAME rating as
# `someseoblog.example/top-10`. A learner told to prefer government and
# university sources could not tell the two apart, which is the whole
# problem it was supposed to solve.
#
# So the suffixes are the ones governments and universities really use:
# France (.gouv.fr), Canada (.gc.ca), New Zealand (.govt.nz), Switzerland
# (.admin.ch), Germany (.bund.de), Japan and Korea (.go.jp/.go.kr), the
# Spanish- and Portuguese-speaking .gob/.gov variants, and the EU's own
# europa.eu. Plus the research-institute suffix families (.ac.*, .edu.*,
# .res.in) that the two-letter rule already half-covered.
# Every branch is anchored with (^|\.), NOT a bare \. — because classify()
# strips a leading "www.", so `www.gouv.fr` arrives as `gouv.fr` with no
# leading dot at all. The first version required one, and France, New
# Zealand, Switzerland and Japan all came back tier 3 for that reason alone.
INSTITUTIONAL = re.compile(
    r"(^|\.)europa\.eu$"                         # EU institutions
    r"|\.(gov|edu|mil|int|cern)$"                # US, international, CERN
    r"|(^|\.)(ac|edu|gov|gob|res|qc)\.[a-z]{2,3}$"   # .ac.uk .edu.au .gob.mx
    r"|(^|\.)(gouv\.fr|gc\.ca|govt\.nz|admin\.ch|bund\.de|go\.jp|go\.kr"
    r"|gov\.uk|gouv\.qc\.ca)$")

# Public research organisations, national labs and intergovernmental bodies.
# None of these sit on a .gov or .edu suffix, and every one of them is a
# primary producer of the material this platform is meant to learn from.
PUBLIC_RESEARCH = (
    # national and international laboratories
    "cern.ch", "esa.int", "embl.de", "esrf.eu", "ill.eu", "mpg.de",
    "fraunhofer.de", "helmholtz.de", "leibniz-gemeinschaft.de",
    "cnrs.fr", "inria.fr", "cea.fr", "ifremer.fr",
    "riken.jp", "jaxa.jp", "aist.go.jp",
    "csiro.au", "nrc-cnrc.gc.ca", "tno.nl", "sintef.no", "vtt.fi",
    "csic.es", "cnr.it", "infn.it",
    # intergovernmental and treaty organisations
    "un.org", "oecd.org", "worldbank.org", "imf.org", "wto.org",
    "unesco.org", "unicef.org", "fao.org", "iaea.org", "wipo.int",
    "europarl.europa.eu", "eea.europa.eu", "ecdc.europa.eu",
    # professional and standards bodies
    "ieee.org", "acm.org", "iso.org", "iec.ch", "etsi.org", "itu.int",
    "astm.org", "ansi.org", "din.de", "bsigroup.com",
)

# OPEN SCHOLARLY INFRASTRUCTURE — the registries and repositories that
# discover.py queries. These are not publishers; they are the curated indexes
# and archives that sit in front of publishers, and every one of them is
# keyless, public, and run by a non-profit or a public body.
#
# They were landing at tier 3 ("unrecognised origin, capped at instructional")
# because none of them sits on .edu/.gov and none was in PUBLIC_RESEARCH. That
# put DOAJ — which indexes only peer-reviewed open-access journals — on the
# same rung as a personal blog, and below LEARN_MIN_TIER, so nothing found
# through them could ever become a cited atom. The discovery rails would have
# worked perfectly and produced nothing learnable.
#
# Tier 1 (normative/peer-reviewed): the index only admits reviewed work, or
# the identifier IS the citation.
SCHOLARLY_REVIEWED = (
    "doaj.org",                 # only peer-reviewed open-access journals
    "doi.org", "dx.doi.org",    # the DOI resolver: the citation itself
    "crossref.org", "api.crossref.org",
    "datacite.org", "api.datacite.org",
    "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "europepmc.org",
    "arxiv.org", "export.arxiv.org",
)
# Tier 2 (professional): curated aggregators and archives. Real provenance,
# but they index preprints and datasets alongside reviewed work, so the
# CONTAINER cannot promise review the way the ones above can.
SCHOLARLY_ARCHIVE = (
    "openalex.org", "api.openalex.org",
    "semanticscholar.org", "api.semanticscholar.org",
    "core.ac.uk", "openaire.eu", "explore.openaire.eu",
    "zenodo.org",               # CERN's research repository
    "osf.io", "hal.science", "biorxiv.org", "medrxiv.org",
    "repec.org", "ideas.repec.org",
    "softwareheritage.org", "archive.softwareheritage.org",
    "loc.gov",                  # Library of Congress
)

# A SEARCH ENGINE IS NOT A SOURCE. It is a pointer to one, and citing it
# cites nothing: the result set changes hourly and is personalised. Anything
# reached THROUGH a search engine must be judged on where it landed, so the
# engine's own host is pinned to the bottom tier and can never be learned
# from. This is the mechanical form of "not generic internet trash".
SEARCH_ENGINE = (
    "duckduckgo.com", "api.duckduckgo.com", "google.com", "www.google.com",
    "bing.com", "www.bing.com", "search.yahoo.com", "yandex.com",
    "baidu.com", "searx.be", "search.marcia.cc", "startpage.com",
    "ecosia.org", "brave.com", "search.brave.com",
)

# The bar a source must clear to be LEARNED from -- to become a cited atom --
# as opposed to merely read. Tier 2 by default: professional or better.
LEARN_MIN_TIER = 2

KIND_TIERS = {"spec": 1, "study": 1, "docs": 2, "book": 2, "course": 3,
              "video": 3, "article": 3, "forum": 4, "unknown": 4}
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".webm", ".mp3", ".wav", ".m4a")
BOOK_EXT = (".pdf", ".epub", ".mobi", ".djvu")


def _dir(root, course):
    d = os.path.join(root, "courses", str(course))
    os.makedirs(d, exist_ok=True)
    return d


def path(root, course):
    return os.path.join(_dir(root, course), LEDGER)


def load(root, course):
    try:
        with open(path(root, course), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save(root, course, rows):
    p = path(root, course)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
    for attempt in range(8):
        try:
            os.replace(tmp, p)
            return p
        except PermissionError:            # OneDrive holds the target briefly
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, p)
    return p


def _host_and_path(low):
    """-> (host, [path segments]). One parse, so every rule below reasons
    about the same host the browser would connect to."""
    if "://" not in low:
        return "", []
    parts = urlsplit(low)
    host = parts.hostname or ""
    if host.startswith("www."):              # NOT lstrip: it strips chars,
        host = host[4:]                      # and would turn w3.org into 3.org
    return host, [s for s in (parts.path or "").split("/") if s]


def _owner_rule(host, segs, owner):
    """The owner's [agent.source_tier] table -> (key, tier) or None.

    A key is a host ("w3.org"), or a host and its first path segment
    ("github.com/my-org"), which is how an owner blesses one organisation on
    a shared host without blessing the host. Matching stays anchored to the
    HOST: matching the whole reference let any URL inherit a trusted rule by
    carrying the domain in its path, so evil.example/?ref=w3.org became
    tier 1.

    The MOST SPECIFIC key wins rather than whichever the dict yields first,
    so "github.com/my-org" beats "github.com" no matter what order the TOML
    listed them in -- an override's meaning must not depend on line order.
    """
    best = None
    if not host:
        return None
    for dom, tier in (owner or {}).items():
        key = str(dom).lower().strip().strip("/")
        if not key:
            continue
        d, _, seg = key.partition("/")
        if not (host == d or host.endswith("." + d)):
            continue
        if seg and (not segs or segs[0] != seg):
            continue
        try:
            t = int(tier)
        except (TypeError, ValueError):
            continue
        # A tier outside 1-4 is a typo, not an instruction. It used to be
        # returned verbatim and then crash record() at TIER_NAMES[tier];
        # an unusable rule is skipped and the registry answers instead.
        if t not in TIER_NAMES:
            continue
        if best is None or len(key) > len(best[0]):
            best = (key, t)
    return best


def _registry_match(host):
    """-> (domain, tier, why) or None. The MOST SPECIFIC registered domain
    wins, not the first one the table happens to list. Scanning in table
    order let a broad entry shadow a narrow one that disagreed with it:
    pkg.go.dev, which serves any third party's package page, would have
    inherited go.dev's tier 1 and posed as the Go language reference. The
    longest matching suffix is the one closest to the actual publisher."""
    best = None
    if not host:
        return None
    for d, (tier, why) in _DOMAIN_INDEX.items():
        if (host == d or host.endswith("." + d)) and \
                (best is None or len(d) > len(best[0])):
            best = (d, tier, why)
    return best


def _github(host, segs, kind):
    """-> (kind, tier, why) for the GitHub family, or None if not GitHub.

    It reads a path segment only after confirming the HOST is GitHub's, so
    the org it reads is one GitHub's own namespace assigned -- see the
    comment on GITHUB_ORGS for why that is not the path-trust bug.
    """
    if host == "gist.github.com":
        return (kind, 4, "a gist is one person's scratch file: no "
                         "repository, no review, no organisation behind it")
    if host == "github.io" or host.endswith(".github.io"):
        org = host[:-len("github.io")].rstrip(".").rsplit(".", 1)[-1]
        if org in GITHUB_ORGS:
            return (kind, 2, f"{org}.github.io is the {org} organisation's "
                             f"own published pages")
        return (kind, 3, "github.io publishes whatever the account holder "
                         "pushed: a subdomain is not an editor")
    if not (host in ("github.com", "raw.githubusercontent.com")
            or host.endswith(".githubusercontent.com")):
        return None
    org = segs[0] if segs else ""
    official = org in GITHUB_ORGS
    if any(s in GITHUB_TALK for s in segs[1:]):
        # High signal, zero editorial review -- rated exactly like
        # stackoverflow below, and for the same reason.
        return ("forum", 3 if official else 4,
                f"a github.com/{org or '?'} issue, PR or wiki thread is a "
                f"conversation, not a publication"
                + ("" if official else "; and the org is unrecognised"))
    if official:
        return (kind, 2, f"github.com/{org} is the official {org} "
                         f"organisation's own repository -- primary vendor "
                         f"material, though a repo is code and README prose "
                         f"rather than a reviewed publication")
    return (kind, 3, f"github.com/{org or '?'} is an unrecognised account: a "
                     f"repository belongs to whoever opened it, and ownership "
                     f"is not authority")


def _in(host, table):
    """Host matches a domain in `table`, exactly or as a subdomain.

    One helper, because `host == d or host.endswith("." + d)` written out
    four times is four chances to write `in` instead and match `evil.com`
    against `ilo.com`.
    """
    return any(host == d or host.endswith("." + d) for d in table)


def classify(ref, kind_hint="", cfg=None):
    """-> (kind, tier, why). Deterministic, and it says why."""
    ref = str(ref or "")
    low = ref.lower()
    owner = ((cfg or {}).get("agent", {}) or {}).get("source_tier", {}) or {}
    host, segs = _host_and_path(low)
    kind = kind_hint or _kind(_kind_subject(low, host), host)
    rule = _owner_rule(host, segs, owner)             # owner table wins
    if rule:
        return kind, rule[1], f"owner's [agent.source_tier] rule for {rule[0]}"
    if host:
        gh = _github(host, segs, kind)                # before the registry:
        if gh:                                        # one host, many owners
            return gh
        hit = _registry_match(host)
        if hit:
            d, tier, why = hit
            return kind, tier, f"{d}: {why} -- tier {tier} " \
                               f"({TIER_NAMES[tier]})"
        if "stackoverflow.com" in host:
            return "forum", 3, "stackoverflow: high signal, no editorial review"
        if _in(host, SEARCH_ENGINE):
            return "forum", 4, (
                f"{host} is a SEARCH ENGINE, not a source. Its results are "
                f"personalised and change hourly, so a citation to it cites "
                f"nothing. Follow the link and rate where it lands.")
        if _in(host, SCHOLARLY_REVIEWED):
            return kind, 1, (f"{host} is open scholarly infrastructure that "
                             f"admits only reviewed work, or is the citation "
                             f"identifier itself -- tier 1 (normative)")
        if _in(host, SCHOLARLY_ARCHIVE):
            return kind, 2, (f"{host} is a curated scholarly index or public "
                             f"research archive -- tier 2 (professional). It "
                             f"carries preprints and datasets beside reviewed "
                             f"work, so the container cannot promise review.")
        if any(host == d or host.endswith("." + d) for d in PUBLIC_RESEARCH):
            return kind, 2, (f"{host} is a public research body, national "
                             f"laboratory, treaty organisation or standards "
                             f"institute -- tier 2 (professional)")
        if INSTITUTIONAL.search(host):
            return kind, 2, f"{host} is an institutional domain"
    # An UNRECOGNISED origin can never buy professional or normative rank
    # from words in its own URL. `spec`, `study` and `docs` keywords in a
    # path are chosen by whoever wrote the link, so they are a hint about
    # SHAPE, not evidence of AUTHORITY: anything a blog can name itself is
    # capped at instructional. A real spec earns tier 1 by being on a
    # recognised domain, or by the owner saying so in [agent.source_tier].
    tier = KIND_TIERS.get(kind, 4)
    if not kind_hint:
        tier = max(tier, 3)
    return kind, tier, (f"unrecognised origin; rated by kind '{kind}'"
                        + ("" if kind_hint else
                           " (capped at instructional: an unknown source "
                           "cannot rank itself)"))


def _kind_subject(low, host=""):
    """The part of a reference that may decide its KIND: the host and the
    final path segment. Middle path segments are the caller's to choose."""
    if "://" not in low:
        return low
    from urllib.parse import urlsplit
    parts = urlsplit(low)
    tail = (parts.path or "").rstrip("/").rsplit("/", 1)[-1]
    return f"{parts.netloc}/{tail}"


def _kind(low, host=""):
    """Judged on the host plus the LAST path segment. Scanning the whole
    reference meant a path keyword inflated authority: any unrecognised
    domain with `api`, `guide` or `docs` anywhere in its path was rated
    tier 2 (professional) on the strength of its URL."""
    if any(low.endswith(e) for e in VIDEO_EXT) or "youtube" in host or \
            "youtu.be" in host:
        return "video"
    if any(low.endswith(e) for e in BOOK_EXT):
        return "book"
    if re.search(r"\b(rfc|spec|standard|w3c|iso)\b", low):
        return "spec"
    if re.search(r"\b(doi|arxiv|pubmed|study|paper|journal)\b", low):
        return "study"
    if re.search(r"\b(docs?|documentation|reference|api|guide)\b", low):
        return "docs"
    if re.search(r"\b(course|tutorial|lesson|lecture|workshop)\b", low):
        return "course"
    if host:
        return "article"
    return "unknown"


def learn_bar(cfg=None, min_tier=None):
    """-> (tier, where the bar came from). The bar moves only on purpose.

    An unreadable value is never silently honoured: a caller or a settings
    file asking for tier 9 (or "two") would otherwise switch the gate off by
    accident, which is the loudest failure this module can have.
    """
    owner = ((cfg or {}).get("agent", {}) or {})
    for value, who in ((min_tier, "the caller"),
                       (owner.get("learn_min_tier"),
                        "the owner's [agent] learn_min_tier")):
        if value is None:
            continue
        try:
            t = int(value)
        except (TypeError, ValueError):
            t = None
        if t in TIER_NAMES:
            return t, f"set by {who}"
        return LEARN_MIN_TIER, (f"{who} gave an unusable bar ({value!r}), "
                                f"so the default stands")
    return LEARN_MIN_TIER, "the default"


def learnable(ref, kind_hint="", cfg=None, min_tier=None):
    """Is this reference good enough to LEARN from? -> a dict that says why.

    Reading is not learning. Tier 3-4 material can be read for context all
    day -- what it may never do is become a CITED ATOM, because a claim is
    worth exactly the source behind it, and an expert built on SEO blogs is
    an expert in what ranks, not in the subject.

    So this is the gate to ask before a reference earns an atom, and it
    defaults to LEARN_MIN_TIER (2, professional or better). Lowering it is
    the owner's deliberate act -- `min_tier=` at the call site, or
    [agent] learn_min_tier in settings.toml -- and the verdict below always
    names which one did it, so a lowered bar can never be mistaken for a
    source that earned its place.

    Nothing here consults a model: the answer is the URL, the registry and
    the owner's table, and it is the same answer every time.
    """
    kind, tier, why = classify(ref, kind_hint, cfg)
    bar, origin = learn_bar(cfg, min_tier)
    ok = tier <= bar
    if ok:
        verdict = (f"LEARN: tier {tier} ({TIER_NAMES[tier]}) meets the "
                   f"tier-{bar} bar [{origin}] -- {why}")
    else:
        verdict = (f"CONTEXT ONLY: tier {tier} ({TIER_NAMES[tier]}) is below "
                   f"the tier-{bar} bar [{origin}] -- {why}. Read it for "
                   f"background; it may not become a cited atom unless the "
                   f"owner lowers [agent] learn_min_tier or rates this source "
                   f"in [agent.source_tier].")
    return {"ref": str(ref or ""), "ok": ok, "kind": kind, "tier": tier,
            "tier_name": TIER_NAMES[tier], "weight": TIER_WEIGHT[tier],
            "min_tier": bar, "bar_from": origin, "why": verdict}


def record(root, course, ref, title="", kind="", lesson="", date="",
           by="ingest", cfg=None):
    """Add (or refresh) one source. Idempotent on `ref`."""
    rows = load(root, course)
    ref = str(ref or "").strip()
    for r in rows:
        if r.get("ref") == ref:
            if lesson and lesson not in (r.get("lessons") or []):
                r.setdefault("lessons", []).append(lesson)
                save(root, course, rows)
            return r
    k, tier, why = classify(ref, kind, cfg)
    rec = {"id": f"S-{len(rows) + 1}", "ref": ref,
           "title": (title or os.path.basename(ref) or ref)[:200],
           "kind": k, "tier": tier, "tier_name": TIER_NAMES[tier],
           "weight": TIER_WEIGHT[tier], "why": why,
           "date": date or "", "added": time.strftime("%Y-%m-%d"),
           "by": by, "lessons": [lesson] if lesson else [], "override": None}
    rows.append(rec)
    save(root, course, rows)
    return rec


def set_tier(root, course, sid, tier, why="", by="owner"):
    """The owner overrules a rating. Recorded, never silent."""
    tier = int(tier)
    if tier not in TIER_NAMES:
        raise ValueError(f"tier must be 1-4, not {tier}")
    rows = load(root, course)
    for r in rows:
        if r.get("id") == sid or r.get("ref") == sid:
            r["override"] = {"from": r["tier"], "to": tier, "by": by,
                             "why": why or "no reason given",
                             "at": time.strftime("%Y-%m-%d")}
            r["tier"], r["tier_name"] = tier, TIER_NAMES[tier]
            r["weight"] = TIER_WEIGHT[tier]
            r["why"] = f"owner override: {why or 'no reason given'}"
            save(root, course, rows)
            return r
    raise KeyError(f"no source {sid} in course {course}")


def by_ref(root, course, ref):
    """EXACT match only. Substring matching returned another source's tier
    whenever one reference contained another ("a.md" matched "data.md"),
    which silently mis-rated the authority a conflict ruling depends on."""
    ref = str(ref or "")
    for r in load(root, course):
        if r.get("ref") == ref or r.get("id") == ref:
            return r
    return None


def tier_of(root, course, ref, default=4):
    r = by_ref(root, course, ref)
    return int(r["tier"]) if r else default


def courses(root):
    d = os.path.join(root, "courses")
    try:
        return sorted(n for n in os.listdir(d)
                      if os.path.isdir(os.path.join(d, n)))
    except OSError:
        return []


def summary(root, course=None):
    out = {"courses": {}, "total": 0, "by_tier": {1: 0, 2: 0, 3: 0, 4: 0}}
    for c in ([course] if course else courses(root)):
        rows = load(root, c)
        if not rows:
            continue
        counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for r in rows:
            counts[int(r.get("tier", 4))] += 1
            out["by_tier"][int(r.get("tier", 4))] += 1
        out["courses"][c] = {"n": len(rows), "by_tier": counts,
                             "overridden": sum(1 for r in rows if r.get("override"))}
        out["total"] += len(rows)
    return out


def render(root, course, cap=12):
    """The context block: what this course actually rests on."""
    rows = load(root, course)
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: (r.get("tier", 4), r.get("title", "")))
    lines = ["SOURCE AUTHORITY — what this course rests on. When two sources "
             "disagree, the lower tier number wins; when they are the SAME "
             "tier, say so instead of picking one."]
    for r in rows[:cap]:
        lines.append(f"- [tier {r['tier']} {r['tier_name']}] {r['title'][:80]} "
                     f"({r['kind']}{', ' + r['date'] if r.get('date') else ''})")
    if len(rows) > cap:
        by_tier = {}
        for r in rows[cap:]:
            by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
        lines.append("- ...and " + ", ".join(
            f"{n} more tier-{t}" for t, n in sorted(by_tier.items())))
    return "\n".join(lines)


# The table that proves it, and it RUNS: each row is a real reference and the
# tier it must get. A future edit that quietly re-rates the web fails here,
# in one second, instead of six weeks later inside an expert's citations.
# Deliberately evaluated with NO owner config, so it proves what this file
# decides on its own rather than what one machine's settings.toml decides.
PROOF = (
    ("https://www.w3.org/TR/WCAG22/", 1),
    ("https://datatracker.ietf.org/doc/html/rfc9110", 1),
    ("https://docs.python.org/3/library/asyncio-task.html", 1),
    ("https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html", 1),
    ("https://go.dev/ref/spec", 1),
    ("https://arxiv.org/abs/1706.03762", 1),
    ("https://www.nature.com/articles/s41586-021-03819-2", 1),
    ("https://nvd.nist.gov/vuln/detail/CVE-2021-44228", 1),
    ("https://developer.mozilla.org/en-US/docs/Web/API/fetch", 2),
    ("https://docs.aws.amazon.com/lambda/latest/dg/welcome.html", 2),
    ("https://kubernetes.io/docs/concepts/workloads/pods/", 2),
    ("https://learn.microsoft.com/en-us/dotnet/csharp/", 2),
    ("https://github.com/python/cpython/blob/main/README.rst", 2),
    ("https://pypi.org/project/requests/", 2),
    ("https://pkg.go.dev/github.com/spf13/cobra", 2),
    ("https://www.mit.edu/~amini/lectures/notes.pdf", 2),
    ("https://stackoverflow.com/questions/11227809", 3),
    ("https://medium.com/@someone/10-python-tricks-2f4a", 3),
    ("https://www.w3schools.com/python/python_intro.asp", 3),
    ("https://www.youtube.com/watch?v=8aGhZQkoFbQ", 3),
    ("https://github.com/randomuser42/awesome-python-tips", 3),
    ("https://someconsultancy.io/blog/the-definitive-spec-for-css", 3),
    ("https://evil.example/?ref=https://www.w3.org/TR/WCAG22/", 3),
    ("https://phish.gov.cdn-mirror.io/wcag/quick-guide", 3),
    ("https://github.com/python/cpython/issues/103092", 3),
    ("https://gist.github.com/randomuser42/9f2c1a4e", 4),
    ("https://www.geeksforgeeks.org/python-oops-concepts/", 4),
    ("https://www.reddit.com/r/Python/comments/abc123/", 4),
    ("https://x.com/someone/status/1234567890", 4),
)


def _clip(text, width):
    text = str(text)
    return text if len(text) <= width else text[:width - 3] + "..."


def duplicates():
    """Domains listed in more than one REGISTRY group. A duplicate is not
    fatal -- _DOMAIN_INDEX keeps the lowest tier deterministically -- but it
    means two comments claim the same domain for different reasons, and the
    one you read is not necessarily the one that applied."""
    seen, dupes = {}, []
    for tier, _why, domains in REGISTRY:
        for d in domains:
            if d in seen and seen[d] != tier:
                dupes.append((d, seen[d], tier))
            seen.setdefault(d, tier)
    return dupes


def prove(min_tier=None):
    """Run PROOF -> (rows, mismatches). No cfg: built-in behaviour only."""
    rows, bad = [], []
    for ref, want in PROOF:
        verdict = learnable(ref, "", None, min_tier)
        kind, tier, why = classify(ref, "", None)
        rows.append({"ref": ref, "kind": kind, "tier": tier, "want": want,
                     "learn": verdict["ok"], "min_tier": verdict["min_tier"],
                     "why": why})
        if tier != want:
            bad.append((ref, want, tier, why))
    return rows, bad


def main():
    import argparse
    import tomllib
    ap = argparse.ArgumentParser(description="the source authority ledger")
    ap.add_argument("--root", default=".")
    ap.add_argument("--course")
    ap.add_argument("--classify", help="rate one URL or path and explain why")
    ap.add_argument("--learn", help="may this reference be LEARNED from "
                                    "(cited), or only read for context?")
    ap.add_argument("--min-tier", dest="min_tier", type=int,
                    help="lower the learn bar on purpose "
                         "(default: tier %d)" % LEARN_MIN_TIER)
    ap.add_argument("--prove", action="store_true",
                    help="run the built-in table of real URLs and check "
                         "that every one still gets the tier it must")
    ap.add_argument("--add", help="record a source (needs --course)")
    ap.add_argument("--title", default="")
    ap.add_argument("--kind", default="")
    ap.add_argument("--set", dest="sid", help="source id to overrule")
    ap.add_argument("--tier", type=int)
    ap.add_argument("--why", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    cfg = {}
    try:
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            cfg = tomllib.loads(f.read().decode("utf-8-sig"))
    except OSError:
        pass
    if a.prove:
        rows, bad = prove(a.min_tier)
        bar = rows[0]["min_tier"] if rows else LEARN_MIN_TIER
        if a.json:
            print(json.dumps({"rows": rows, "mismatches": bad,
                              "duplicate_domains": duplicates()}, indent=1))
            raise SystemExit(1 if bad else 0)
        print(f"{len(rows)} reference(s), rated with NO owner config. "
              f"LEARN = may become a cited atom (tier {bar} or better); "
              f"ctx = readable, never citable.")
        print(f"{'tier':<5}{'kind':<8}{'learn':<7}{'reference':<46}why")
        for r in rows:
            print(f"{r['tier']:<5}{r['kind']:<8}"
                  f"{('LEARN' if r['learn'] else 'ctx'):<7}"
                  f"{_clip(r['ref'], 45):<46}{_clip(r['why'], 62)}")
        for d, t1, t2 in duplicates():
            print(f"  ! {d} is listed in tier {t1} AND tier {t2}")
        for ref, want, got, why in bad:
            print(f"  ! {ref}\n    expected tier {want}, got {got} -- {why}")
        print("FAIL" if bad else "PASS: every reference got the tier it must")
        raise SystemExit(1 if bad else 0)
    if a.learn:
        v = learnable(a.learn, a.kind, cfg, a.min_tier)
        print(json.dumps(v, indent=1) if a.json else
              f"{a.learn}\n  {'LEARN' if v['ok'] else 'CONTEXT ONLY'} · kind "
              f"{v['kind']} · tier {v['tier']} ({v['tier_name']}), bar tier "
              f"{v['min_tier']} [{v['bar_from']}]\n  {v['why']}")
        return
    if a.classify:
        k, t, why = classify(a.classify, a.kind, cfg)
        print(json.dumps({"kind": k, "tier": t, "tier_name": TIER_NAMES[t],
                          "weight": TIER_WEIGHT[t], "why": why}, indent=1)
              if a.json else
              f"{a.classify}\n  kind {k} · tier {t} ({TIER_NAMES[t]}, "
              f"weight {TIER_WEIGHT[t]})\n  {why}")
        return
    if a.add:
        if not a.course:
            raise SystemExit("--add needs --course")
        r = record(root, a.course, a.add, a.title, a.kind, cfg=cfg)
        print(json.dumps(r, indent=1) if a.json else
              f"{r['id']} {r['title']} -> tier {r['tier']} ({r['why']})")
        return
    if a.sid:
        if not (a.course and a.tier):
            raise SystemExit("--set needs --course and --tier")
        r = set_tier(root, a.course, a.sid, a.tier, a.why)
        print(f"{r['id']} -> tier {r['tier']} ({r['tier_name']}); "
              f"was tier {r['override']['from']}")
        return
    if a.json:
        print(json.dumps({"summary": summary(root, a.course),
                          "rows": load(root, a.course) if a.course else None},
                         indent=1))
        return
    s = summary(root, a.course)
    print(f"{s['total']} source(s) across {len(s['courses'])} course(s)")
    for t in (1, 2, 3, 4):
        print(f"  tier {t} {TIER_NAMES[t]:<14} {s['by_tier'][t]}")
    for c, info in sorted(s["courses"].items()):
        print(f"  {c:<22} {info['n']:>4} sources, "
              f"{info['overridden']} owner-rated")


if __name__ == "__main__":
    main()
