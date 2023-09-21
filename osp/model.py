import enum

from sqlalchemy import (
    BigInteger, Enum, String, Text,
    ForeignKey, UniqueConstraint,
    text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from quirck.auth.model import User
from quirck.db.base import Base

User.password = mapped_column(String(255), nullable=True)


class Assignment(Base):
    __tablename__ = "assignment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    repo: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(BigInteger, nullable=False)

    repositories: Mapped[list["Repository"]] = relationship("Repository", back_populates="assignment")


class RepoStatus(enum.Enum):
    IN_PROGRESS = 1
    FINISHED = 2
    FAILED = 3


class Repository(Base):
    __tablename__ = "repository"
    __table_args__ = (
        UniqueConstraint("user_id", "assignment_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False
    )
    assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assignment.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False
    )
    repo_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[RepoStatus] = mapped_column(Enum(RepoStatus), nullable=False, server_default=text("'IN_PROGRESS'"))

    user: Mapped[User] = relationship("User", back_populates="repositories")
    assignment: Mapped[Assignment] = relationship("Assignment", back_populates="repositories")


User.repositories = relationship("Repository", back_populates="user")


__all__ = ["Assignment", "Repository"]
