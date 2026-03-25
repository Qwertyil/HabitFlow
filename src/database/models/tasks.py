from sqlalchemy import (
    UUID,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .base import BaseModel, OwnedModel


class Priority(BaseModel):
    __tablename__ = "priorities"

    name = Column(String(20), nullable=False, unique=True)  # низкий, средний, высокий
    weight = Column(Integer, nullable=False)  # для сортировки: 1, 2, 3
    color = Column(String(7), nullable=True)  # цвет для UI: #FF0000

    __table_args__ = (CheckConstraint("LENGTH(color) >= 7", name="min_color_length"),)


class Task(OwnedModel):
    __tablename__ = "tasks"

    name = Column(String(46), nullable=False)
    theme_id = Column(UUID, ForeignKey("themes.id", ondelete="SET NULL"), nullable=True)
    description = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True, default=None)
    priority_id = Column(UUID, ForeignKey("priorities.id"), nullable=False)

    theme = relationship("Theme", back_populates="tasks")
    priority = relationship("Priority")
    owner = relationship("User", back_populates="tasks")
