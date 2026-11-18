"""Static analysis of Android project files (regex/XML based; no code execution).

Input is a mapping of project-relative POSIX path -> bytes, so the analyzer is
independent of where files are stored (object storage, temp dir, ...)."""

from __future__ import annotations

import hashlib
import posixpath
import re

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from ..providers.redaction import is_sensitive_path
from .models import (
    ApiEndpoint,
    FileInfo,
    GradleInfo,
    ManifestInfo,
    ProjectProfile,
    Symbol,
)

MAX_FILE_BYTES = 512 * 1024
SKIP_DIRS = {"build", ".gradle", ".git", ".idea", "node_modules", ".cxx", "captures"}
TEXT_SUFFIXES = (".kt", ".kts", ".java", ".xml", ".gradle", ".properties", ".pro", ".json", ".md", ".toml")
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

_PKG = re.compile(r"^\s*package\s+([\w.]+)", re.M)
_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.*]+)", re.M)
_CLASS = re.compile(
    r"^\s*(?:(?:public|private|internal|protected|abstract|open|final|sealed|data|enum|annotation|inner|static)\s+)*"
    r"(class|interface|object)\s+(\w+)(?:\s*(?:<[^>{]*>)?\s*(?:\([^)]*\))?\s*(?::|extends|implements)\s*([^{\n]+))?",
    re.M,
)
_KT_FUN = re.compile(r"^\s*(?:(?:public|private|internal|protected|override|suspend|inline|open|abstract)\s+)*fun\s+(?:<[^>]*>\s*)?(?:[\w.<>?]+\.)?(\w+)\s*\(", re.M)
_JAVA_METHOD = re.compile(r"^\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?[\w<>\[\],? ]+\s+(\w+)\s*\([^)]*\)\s*(?:throws [\w, ]+)?\s*\{", re.M)
_COMPOSABLE = re.compile(r"@Composable\s*(?:\n\s*)*(?:(?:private|internal|public)\s+)?fun\s+(\w+)")
_RETROFIT = re.compile(r"@(GET|POST|PUT|DELETE|PATCH|HEAD)\(\s*\"([^\"]*)\"\s*\)\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:suspend\s+)?fun\s+(\w+)")
_ROOM = re.compile(r"@(Entity|Dao|Database)\b")

# (tag, regexes over imports+content)
_TAG_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("auth", re.compile(r"FirebaseAuth|GoogleSignIn|SignInClient|CredentialManager|AuthRepository|OAuth|androidx\.biometric|\bLoginViewModel\b|AccountManager", re.I)),
    ("payment", re.compile(r"BillingClient|com\.stripe|razorpay|PaymentSheet|paypal|braintree|GooglePay|PaymentsClient", re.I)),
    ("network", re.compile(r"retrofit2|okhttp3|io\.ktor\.client|HttpURLConnection|volley", re.I)),
    ("database", re.compile(r"androidx\.room|SQLiteOpenHelper|io\.realm|app\.cash\.sqldelight|DataStore", re.I)),
    ("navigation", re.compile(r"androidx\.navigation|NavHost|NavController|FragmentTransaction|startActivity\(", re.I)),
    ("ui", re.compile(r"androidx\.compose|@Composable|android\.view|android\.widget", re.I)),
    ("di", re.compile(r"dagger\.hilt|@Inject|org\.koin", re.I)),
]


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def normalize_path(path: str) -> str | None:
    """POSIX-normalise; reject absolute paths and traversal. Returns None if unsafe."""
    p = path.replace("\\", "/")
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        return None
    n = posixpath.normpath(p)
    if n == "." or n.startswith("../") or n == ".." or "\x00" in n:
        return None
    return n


def _language(path: str) -> str:
    if path.endswith((".kt", ".kts")):
        return "gradle" if path.endswith(".gradle.kts") else "kotlin"
    return {"java": "java", "xml": "xml", "gradle": "gradle"}.get(path.rsplit(".", 1)[-1], "other")


def should_skip_dir(path: str) -> bool:
    return any(part in SKIP_DIRS for part in path.split("/")[:-1])


def _line_of(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def analyze_source(path: str, content: str) -> FileInfo:
    lang = _language(path)
    info = FileInfo(path=path, sha256="", size=len(content), language=lang)
    if lang not in ("kotlin", "java"):
        return info
    m = _PKG.search(content)
    info.package = m.group(1) if m else None
    info.imports = sorted(set(_IMPORT.findall(content)))
    syms: list[Symbol] = []
    for m in _CLASS.finditer(content):
        kind, name, sup = m.group(1), m.group(2), (m.group(3) or "").strip()
        k = kind
        if re.search(r"\b(AppCompatActivity|ComponentActivity|FragmentActivity|Activity)\b", sup):
            k = "activity"
        elif re.search(r"\bFragment\b|DialogFragment", sup):
            k = "fragment"
        elif re.search(r"\b(ViewModel|AndroidViewModel)\b", sup):
            k = "viewmodel"
        preceding = content[max(0, m.start() - 120): m.start()]
        if "@Entity" in preceding:
            k = "entity"
        elif "@Dao" in preceding:
            k = "dao"
        syms.append(Symbol(name=name, kind=k, path=path, line=_line_of(content, m.start()), detail=sup[:120] or None))
    for m in _COMPOSABLE.finditer(content):
        syms.append(Symbol(name=m.group(1), kind="composable", path=path, line=_line_of(content, m.start())))
    fun_re = _KT_FUN if lang == "kotlin" else _JAVA_METHOD
    composables = {s.name for s in syms if s.kind == "composable"}
    for m in fun_re.finditer(content):
        if m.group(1) not in composables:
            syms.append(Symbol(name=m.group(1), kind="function", path=path, line=_line_of(content, m.start())))
    info.symbols = syms
    haystack = "\n".join(info.imports) + "\n" + content
    info.tags = [tag for tag, rx in _TAG_RULES if rx.search(haystack)]
    if _ROOM.search(content) and "database" not in info.tags:
        info.tags.append("database")
    return info


def extract_endpoints(path: str, content: str) -> list[ApiEndpoint]:
    return [ApiEndpoint(method=m.group(1), path=m.group(2), file=path, function=m.group(3)) for m in _RETROFIT.finditer(content)]


def parse_manifest(path: str, content: bytes) -> ManifestInfo | None:
    try:
        root = SafeET.fromstring(content)
    except (SafeET.ParseError, DefusedXmlException, ValueError):
        return None
    info = ManifestInfo(path=path, package=root.get("package"))
    info.permissions = sorted({e.get(f"{ANDROID_NS}name", "") for e in root.iter("uses-permission") if e.get(f"{ANDROID_NS}name")})
    app = root.find("application")
    if app is not None:
        info.application_class = app.get(f"{ANDROID_NS}name")
        for tag, target in (("activity", info.activities), ("service", info.services), ("receiver", info.receivers)):
            for e in app.iter(tag):
                n = e.get(f"{ANDROID_NS}name")
                if n:
                    target.append(n)
        for act in app.iter("activity"):
            for f in act.iter("intent-filter"):
                if any(c.get(f"{ANDROID_NS}name") == "android.intent.category.LAUNCHER" for c in f.iter("category")):
                    info.launcher_activity = act.get(f"{ANDROID_NS}name")
    return info


def _int(rx: str, text: str) -> int | None:
    m = re.search(rx, text)
    return int(m.group(1)) if m else None


def parse_gradle(path: str, content: str) -> GradleInfo:
    g = GradleInfo(path=path)
    m = re.search(r"""namespace\s*=?\s*["']([\w.]+)["']""", content)
    g.namespace = m.group(1) if m else None
    m = re.search(r"""applicationId\s*=?\s*["']([\w.]+)["']""", content)
    g.application_id = m.group(1) if m else None
    g.min_sdk = _int(r"minSdk(?:Version)?\s*=?\s*(\d+)", content)
    g.target_sdk = _int(r"targetSdk(?:Version)?\s*=?\s*(\d+)", content)
    g.compile_sdk = _int(r"compileSdk(?:Version)?\s*=?\s*(\d+)", content)
    g.plugins = sorted(set(re.findall(r"""id\s*\(?\s*["']([\w.\-]+)["']""", content))
                       | set(re.findall(r"alias\(\s*libs\.plugins\.([\w.]+)\s*\)", content)))
    deps = re.findall(r"""(?:implementation|api|kapt|ksp|annotationProcessor|testImplementation|androidTestImplementation|debugImplementation)\s*\(?\s*(?:platform\()?\s*["']([^"']+)["']""", content)
    deps += [f"libs.{d}" for d in re.findall(r"(?:implementation|api|ksp|kapt)\s*\(?\s*libs\.([\w.]+)", content)]
    g.dependencies = sorted(set(deps))
    return g


def analyze_project(files: dict[str, bytes]) -> tuple[ProjectProfile, list[FileInfo], dict[str, str]]:
    """Returns (profile, per-file infos, {path: text}) for indexable files.

    Unsafe paths, build outputs, binaries, oversized and sensitive files are
    recorded in `profile.skipped` and their content is never read into the index."""
    profile = ProjectProfile()
    infos: list[FileInfo] = []
    texts: dict[str, str] = {}
    for raw_path, data in sorted(files.items()):
        path = normalize_path(raw_path)
        if path is None:
            profile.skipped[raw_path] = "unsafe_path"
            continue
        if should_skip_dir(path):
            continue
        digest = sha256(data)
        base = FileInfo(path=path, sha256=digest, size=len(data), language=_language(path))
        reason = None
        if is_sensitive_path(path):
            reason = "sensitive"
        elif not path.endswith(TEXT_SUFFIXES):
            reason = "non_text"
        elif len(data) > MAX_FILE_BYTES:
            reason = "too_large"
        elif b"\x00" in data[:4096]:
            reason = "binary"
        if reason:
            base.skipped_reason = reason
            profile.skipped[path] = reason
            infos.append(base)
            continue
        text = data.decode("utf-8", errors="replace")
        texts[path] = text
        info = analyze_source(path, text)
        info.sha256 = digest
        info.size = len(data)
        infos.append(info)

        name = path.rsplit("/", 1)[-1]
        if name == "AndroidManifest.xml":
            mi = parse_manifest(path, data)
            if mi:
                profile.manifests.append(mi)
        elif name in ("build.gradle", "build.gradle.kts"):
            profile.gradle.append(parse_gradle(path, text))
        elif path.endswith(".xml"):
            if "/res/layout" in path:
                profile.layouts.append(path)
                info.tags.append("ui")
            elif "/res/navigation/" in path:
                profile.navigation_graphs.append(path)
                info.tags.append("navigation")
        if info.language in ("kotlin", "java"):
            profile.api_endpoints.extend(extract_endpoints(path, text))

    for info in infos:
        for s in info.symbols:
            if s.kind == "activity":
                profile.activities.append(s.name)
            elif s.kind == "fragment":
                profile.fragments.append(s.name)
            elif s.kind == "composable":
                profile.composables.append(s.name)
        if "database" in info.tags:
            profile.database_files.append(info.path)
        if "auth" in info.tags:
            profile.auth_files.append(info.path)
        if "payment" in info.tags:
            profile.payment_files.append(info.path)

    # project-level facts from the first app-like gradle module that declares them
    for g in profile.gradle:
        profile.namespace = profile.namespace or g.namespace
        profile.application_id = profile.application_id or g.application_id
        profile.min_sdk = profile.min_sdk or g.min_sdk
        profile.target_sdk = profile.target_sdk or g.target_sdk
        profile.compile_sdk = profile.compile_sdk or g.compile_sdk
    for m in profile.manifests:
        profile.permissions = sorted(set(profile.permissions) | set(m.permissions))
    profile.languages = sorted({i.language for i in infos if i.language in ("kotlin", "java")})
    toolkits = []
    if profile.composables or any("compose" in d.lower() for g in profile.gradle for d in g.dependencies):
        toolkits.append("compose")
    if profile.layouts:
        toolkits.append("xml")
    profile.ui_toolkits = toolkits
    profile.root_modules = sorted({p.split("/")[0] for p in texts if p.count("/") >= 1 and p.endswith(("build.gradle", "build.gradle.kts"))})
    profile.file_count = len(infos)
    for lst in (profile.activities, profile.fragments, profile.composables, profile.database_files,
                profile.auth_files, profile.payment_files):
        lst[:] = sorted(set(lst))
    return profile, infos, texts
