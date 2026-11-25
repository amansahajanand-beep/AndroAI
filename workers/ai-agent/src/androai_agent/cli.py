"""``python -m androai_agent modify --zip app.zip --prompt "..."``: try the modify job locally.

Runs on a copy: the ZIP is only read and the result lands in a work directory that is printed. The
project's source is sent to the NVIDIA-hosted model named by NVIDIA_MODEL, so use projects you may
share. Nothing is built or run.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import tempfile
from pathlib import Path

from androai_codegen.ingest import OwnershipAttestation
from androai_codegen.llm_nvidia import LlmError, NvidiaClient
from androai_codegen.proposer import LlmClient

from .modify_job import ModifyJobRequest, ModifyJobResult, run_modify_job

_DOTENV_KEYS = ("NVIDIA_API_KEY", "NVIDIA_MODEL", "NVIDIA_BASE_URL")


def load_dotenv(start: Path | None = None) -> Path | None:
    """Fill missing NVIDIA_* variables from the nearest ``.env`` above ``start`` (never others)."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents[:5]):
        candidate = folder / ".env"
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                name, sep, value = line.partition("=")
                name = name.strip()
                if sep and name in _DOTENV_KEYS and not os.environ.get(name):
                    os.environ[name] = value.split(" #", 1)[0].strip().strip("\"'")
            return candidate
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="androai_agent modify", description=__doc__)
    parser.add_argument(
        "--zip", required=True, type=Path, help="the project as a ZIP archive"
    )
    parser.add_argument("--prompt", required=True, help="what to change")
    parser.add_argument(
        "--work-dir", type=Path, help="where to put the result (default: a temp dir)"
    )
    parser.add_argument(
        "--max-files", type=int, default=8, help="most files the model may edit"
    )
    parser.add_argument(
        "--json", action="store_true", help="print the full result as JSON"
    )
    parser.add_argument(
        "--yes-send-code",
        action="store_true",
        help="confirm that you own this project and agree to send its files to the hosted model",
    )
    return parser


def render(result: ModifyJobResult) -> str:
    lines = [f"status: {result.status} (stage: {result.stage}, {result.seconds}s)"]
    if result.detection:
        d = result.detection
        lines.append(
            f"project: {d.kind.value}; {', '.join(d.languages)}; {', '.join(d.ui_toolkits)}"
        )
    if result.confidence:
        lines.append(f"retrieval confidence: {result.confidence}")
    if result.plan_files:
        lines += ["files the model could edit:", *(f"  {p}" for p in result.plan_files)]
    if result.unmatched_terms:
        lines.append(
            "request words that matched nothing: " + ", ".join(result.unmatched_terms)
        )
    for question in result.questions:
        lines.append(f"question: {question}")
    if result.changes:
        lines += [
            "changes applied:",
            *(f"  {kind} {path}" for kind, path in result.changes),
        ]
    if result.review_summary:
        lines.append(f"static review: {result.review_summary}")
    for request in result.approval_requests:
        lines.append(
            f"needs approval: {request.kind} {', '.join(request.paths)}: {request.reason}"
        )
    lines += [f"problem: {p}" for p in result.problems]
    lines += [f"note: {w}" for w in result.warnings]
    if result.notes:
        lines.append(f"model notes: {result.notes}")
    if result.workspace:
        lines.append(f"result workspace: {result.workspace}")
    if result.diff:
        lines += ["", "----- diff -----", result.diff]
    return "\n".join(lines)


def main(argv: list[str], client: LlmClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.yes_send_code and client is None:
        print(
            "This sends the project's source files to the NVIDIA-hosted model. "
            "Re-run with --yes-send-code to confirm you own the project and agree.",
            file=sys.stderr,
        )
        return 2
    if client is None:
        load_dotenv()
        try:
            client = NvidiaClient()
        except LlmError as exc:
            print(
                f"error: {exc} (set it in the environment or the repo's .env)",
                file=sys.stderr,
            )
            return 2
    if not args.zip.is_file():
        print(f"error: {args.zip} is not a file", file=sys.stderr)
        return 2
    work = args.work_dir or Path(tempfile.mkdtemp(prefix="androai-modify-"))
    work.mkdir(parents=True, exist_ok=True)
    result = run_modify_job(
        ModifyJobRequest(
            zip_path=args.zip,
            prompt=args.prompt,
            work_dir=work,
            attestation=OwnershipAttestation(
                basis="own",
                statement="Confirmed on the command line with --yes-send-code.",
                attested_by=getpass.getuser()[:60] or "local-user",
            ),
            max_plan_files=args.max_files,
        ),
        client,
    )
    print(result.model_dump_json(indent=2) if args.json else render(result))
    return 0 if result.status == "completed" else 1
