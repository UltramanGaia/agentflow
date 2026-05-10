"""Dependency-focused audit pipeline across a fixed package list."""

from agentflow import Graph, claude, codex, fanout


dependencies = [
    {"dep": "boto3"},
    {"dep": "fastapi"},
    {"dep": "httpx"},
    {"dep": "jinja2"},
    {"dep": "pydantic"},
    {"dep": "typer"},
    {"dep": "uvicorn"},
]


with Graph("dependency-audit", working_dir=".", concurrency=7) as dag:
    dependency_audit = fanout(
        codex(
            task_id="dependency_audit",
            prompt=(
                "Audit the Python dependency `{{ item.dep }}` from pyproject.toml.\n\n"
                "Check for:\n"
                "- security issues\n"
                "- outdated version\n"
                "- license compatibility\n"
                "- better alternatives\n\n"
                "Return a concise dependency report with findings, risk level, and recommended next steps."
            ),
        ),
        dependencies,
    )

    executive_summary = claude(
        task_id="executive_summary",
        prompt=(
            "Synthesize these dependency audit findings into an executive summary for engineering leadership.\n"
            "Include a brief overall assessment, the highest-priority issues, and concrete action items.\n\n"
            "Dependencies reviewed from pyproject.toml:\n"
            "{% for finding in fanouts.dependency_audit.nodes %}\n"
            "## {{ finding.dep }}\n"
            "{{ finding.output or '(no output)' }}\n\n"
            "{% endfor %}"
        ),
    )

    dependency_audit >> executive_summary

print(dag.to_json())
