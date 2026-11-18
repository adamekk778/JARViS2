"""3.12 Propojení: the tools of every connector (Google, Supabase, Spaceship, GitHub, Notion, Slack) – see connectors/."""
from .. import bizcompany, bizgoals, connectors  # noqa: F401 – bizcompany: the company tools (overview, the company brain)

connectors.load()
