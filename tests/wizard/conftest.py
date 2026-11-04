"""Stand-ins for the human and the CLI: scripted answers, recorded commands."""

from incognito_sql.wizard.prompts import LinePrompter


class Script:
    """Answers questions in order; ``shown`` holds every prompt and line written."""

    def __init__(self, *answers: str) -> None:
        """Queue the answers a human would type."""
        self.answers = list(answers)
        self.shown: list[str] = []

    def read(self, prompt: str) -> str:
        """Record the prompt, return the next answer; running out is a test's fault."""
        self.shown.append(prompt)
        return self.answers.pop(0)

    def write(self, text: str) -> None:
        """Record a line written."""
        self.shown.append(text)

    def terminal(self) -> LinePrompter:
        """Return a prompter over this script."""
        return LinePrompter(self.read, self.write)

    def text(self) -> str:
        """Return everything shown, joined."""
        return "".join(self.shown)


class Calls:
    """Stands in for `incognito_sql.cli.main`: records each argv, returns ``code``."""

    def __init__(self, code: int = 0) -> None:
        """Answer every call with ``code``."""
        self.code = code
        self.argvs: list[list[str]] = []

    def __call__(self, argv: list[str]) -> int:
        """Record the argv."""
        self.argvs.append(argv)
        return self.code
