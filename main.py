"""BrainGPS bot entry point."""

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from app.bot.handlers import init_handlers, router
from app.core.feedback_db import init_db
from app.core.analytics_db import init_analytics_db
from app.core.limits_db import init_limits_db
from app.core.graph import load_graph
from app.core.llm import LLMService

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize bot, load graph, and start polling."""
    import os

    token = os.getenv("TG_BOT_TOKEN")
    groq_key = os.getenv("GROQ_API_KEY")
    if not token:
        raise ValueError("TG_BOT_TOKEN is required in .env")
    if not groq_key:
        raise ValueError("GROQ_API_KEY is required in .env")

    graph_dir = Path(__file__).parent / "data" / "graph"
    graph = load_graph(graph_dir)
    logger.info("Loaded graph with %d nodes", len(graph))

    prompts_dir = Path(__file__).parent / "data" / "prompts"
    llm_service = LLMService(api_key=groq_key, template_dir=prompts_dir)
    init_handlers(graph, llm_service)

    await init_db()
    await init_analytics_db()
    await init_limits_db()

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
