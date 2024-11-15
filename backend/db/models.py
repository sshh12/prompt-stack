from sqlalchemy import Column, String, Integer, ForeignKey, Text, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from .database import Base


class TimestampMixin:
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    projects = relationship(
        "Project", back_populates="owner", cascade="all, delete-orphan"
    )
    team_memberships = relationship(
        "TeamMember", back_populates="user", cascade="all, delete-orphan"
    )
    chats = relationship("Chat", back_populates="owner", cascade="all, delete-orphan")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    description = Column(Text, nullable=True)

    modal_sandbox_last_used_at = Column(DateTime(timezone=True), nullable=True)
    modal_sandbox_id = Column(String, nullable=True)
    modal_volume_label = Column(String, nullable=True)

    team_id = Column(
        Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    stack_id = Column(Integer, ForeignKey("stacks.id"), nullable=False)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    owner = relationship("User", back_populates="projects")

    team = relationship("Team", back_populates="projects")
    stack = relationship("Stack", back_populates="projects")
    chats = relationship("Chat", back_populates="project", cascade="all, delete-orphan")


class Team(TimestampMixin, Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    # Relationships
    members = relationship(
        "TeamMember", back_populates="team", cascade="all, delete-orphan"
    )
    projects = relationship(
        "Project", back_populates="team", cascade="all, delete-orphan"
    )


class TeamRole(PyEnum):
    ADMIN = "admin"
    MEMBER = "member"


class TeamMember(Base):
    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(
        Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role = Column(Enum(TeamRole), nullable=False)

    # Relationships
    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_memberships")


class Stack(Base):
    __tablename__ = "stacks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, unique=True)
    description = Column(Text, nullable=False)
    prompt = Column(Text, nullable=False)
    from_registry = Column(String, nullable=False)
    sandbox_init_cmd = Column(Text, nullable=False)
    sandbox_start_cmd = Column(Text, nullable=False)

    # Relationships
    projects = relationship("Project", back_populates="stack")
    prepared_sandboxes = relationship(
        "PreparedSandbox", back_populates="stack", cascade="all, delete-orphan"
    )


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    project = relationship("Project", back_populates="chats")
    owner = relationship("User", back_populates="chats")
    messages = relationship(
        "Message", back_populates="chat", cascade="all, delete-orphan"
    )


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)

    chat_id = Column(
        Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    chat = relationship("Chat", back_populates="messages")


class PreparedSandbox(TimestampMixin, Base):
    __tablename__ = "prepared_sandboxes"

    id = Column(Integer, primary_key=True, index=True)
    modal_sandbox_id = Column(String, nullable=True)
    modal_volume_label = Column(String, nullable=True)

    stack_id = Column(Integer, ForeignKey("stacks.id"), nullable=False)
    stack = relationship("Stack", back_populates="prepared_sandboxes")
