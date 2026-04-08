import logging

from src.application import create_app
from src.config import load_settings

logger = logging.getLogger(__name__)

settings = load_settings()

logging.basicConfig(
    level=settings.logging_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = create_app(settings)
