import logging

from src.application import create_app
from src.config import settings

logger = logging.getLogger(__name__)


logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = create_app(settings)
