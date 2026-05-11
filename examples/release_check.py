"""Gaia release readiness check spanning tests, security, changelog, and gatekeeping."""

from agentflow import Graph, gaia


with Graph("release-check", working_dir=".", concurrency=3) as dag:
    tests = gaia(
        task_id="tests",
        prompt="Run the test suite and report the results.",
    )
    security = gaia(
        task_id="security",
        prompt="Audit the codebase for security vulnerabilities.",
    )
    changelog = gaia(
        task_id="changelog",
        prompt="Generate a changelog from the recent git history.",
    )
    gate = gaia(
        task_id="gate",
        prompt=(
            "Make a go/no-go release decision based on the following checks.\n\n"
            "Tests:\n{{ nodes.tests.output }}\n\n"
            "Security:\n{{ nodes.security.output }}\n\n"
            "Changelog:\n{{ nodes.changelog.output }}"
        ),
    )

    [tests, security, changelog] >> gate

if __name__ == "__main__":
    print(dag.to_json())
