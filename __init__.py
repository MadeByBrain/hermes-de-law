"""de-law: German federal law, EU law and German federal court decisions for Hermes Agent.

Read-only lookups against the official sources: gesetze-im-internet.de and
rechtsprechung-im-internet.de (German Federal Office of Justice) and the
Publications Office of the European Union (CELLAR). No API key. Texts are cached
under <HERMES_HOME>/plugin-data/de-law/cache/. The plugin returns legal texts,
not legal advice.
"""

import logging
from pathlib import Path

from . import schemas
from .client import Store
from .tools import Tools, make_handlers

logger = logging.getLogger(__name__)

_SKILL = Path(__file__).resolve().parent / "skills" / "read-law" / "SKILL.md"
_SKILL_DESCRIPTION = (
    "German or EU law question (§, Art., StGB, BGB, DSGVO/GDPR, AI Act, BGH, BVerfG)? Before web_search, "
    "use tool_search for the de-law tools and quote source.attribution."
)


def register(ctx):
    """Register the five read-only tools, then the quoting skill."""

    def setting(key, default=None):
        try:
            return ctx.get_config(key, default)
        except Exception:
            return default

    handlers = make_handlers(Tools(Store(settings=setting)))
    for schema in schemas.ALL_SCHEMAS:
        ctx.register_tool(
            name=schema["name"],
            toolset="de_law",
            schema=schema,
            handler=handlers[schema["name"]],
            emoji="⚖️",
        )
    try:
        ctx.register_skill("read-law", _SKILL, description=_SKILL_DESCRIPTION)
    except Exception:
        logger.warning("de-law skill was not registered", exc_info=True)
