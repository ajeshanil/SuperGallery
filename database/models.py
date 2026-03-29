from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, Text, LargeBinary
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Photo(Base):
    __tablename__ = "photos"

    id = Column(Integer, primary_key=True)
    file_path = Column(String, unique=True, nullable=False)
    filename = Column(String, nullable=False)
    date_taken = Column(DateTime, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    camera_model = Column(String, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    file_size = Column(Integer, nullable=True)   # bytes
    is_favorite = Column(Boolean, nullable=False, default=False, server_default='0')
    imported_at = Column(DateTime, default=datetime.utcnow)
    dhash = Column(String(16), nullable=True)   # 64-bit perceptual hash (16-char hex)

    tags = relationship("Tag", back_populates="photo", cascade="all, delete-orphan")
    people = relationship("PhotoPerson", back_populates="photo", cascade="all, delete-orphan")
    location = relationship("Location", back_populates="photo", uselist=False, cascade="all, delete-orphan")
    detections = relationship("ObjectDetection", back_populates="photo", cascade="all, delete-orphan")


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)           # "Person 1" or "Ajesh"
    embedding_vector = Column(LargeBinary, nullable=True)   # stored as bytes (numpy .tobytes())
    thumbnail_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    photos = relationship("PhotoPerson", back_populates="person", cascade="all, delete-orphan")


class PhotoPerson(Base):
    __tablename__ = "photo_people"

    id = Column(Integer, primary_key=True)
    photo_id = Column(Integer, ForeignKey("photos.id"), nullable=False)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)
    confidence = Column(Float, nullable=True)
    # Bounding box as fractional coords (0.0–1.0)
    bbox_x = Column(Float, nullable=True)
    bbox_y = Column(Float, nullable=True)
    bbox_w = Column(Float, nullable=True)
    bbox_h = Column(Float, nullable=True)

    photo = relationship("Photo", back_populates="people")
    person = relationship("Person", back_populates="photos")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    photo_id = Column(Integer, ForeignKey("photos.id"), nullable=False)
    label = Column(String, nullable=False)
    # category: People | Objects | Scenes | PhotoType | Location | Date
    category = Column(String, nullable=False)
    confidence = Column(Float, nullable=True)
    is_manual = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    photo = relationship("Photo", back_populates="tags")


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True)
    photo_id = Column(Integer, ForeignKey("photos.id"), nullable=False, unique=True)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    cluster_id = Column(Integer, nullable=True)

    photo = relationship("Photo", back_populates="location")


class ObjectDetection(Base):
    """Stores object bounding boxes from YOLO detection (one row per detected object)."""
    __tablename__ = "object_detections"

    id = Column(Integer, primary_key=True)
    photo_id = Column(Integer, ForeignKey("photos.id"), nullable=False)
    label = Column(String, nullable=False)
    confidence = Column(Float, nullable=True)
    # Fractional bounding box coords (0.0–1.0) relative to image dimensions
    bbox_x = Column(Float, nullable=False)
    bbox_y = Column(Float, nullable=False)
    bbox_w = Column(Float, nullable=False)
    bbox_h = Column(Float, nullable=False)

    photo = relationship("Photo", back_populates="detections")


class Album(Base):
    __tablename__ = "albums"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    filter_query = Column(Text, nullable=True)   # JSON-encoded filter criteria
    is_smart = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    cover_photo_id = Column(Integer, ForeignKey("photos.id"), nullable=True)


class AlbumPhoto(Base):
    __tablename__ = "album_photos"

    id = Column(Integer, primary_key=True)
    album_id = Column(Integer, ForeignKey("albums.id"), nullable=False)
    photo_id = Column(Integer, ForeignKey("photos.id"), nullable=False)
    sort_order = Column(Integer, nullable=True, default=0)


class DuplicateGroup(Base):
    __tablename__ = "duplicate_groups"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DuplicateMember(Base):
    __tablename__ = "duplicate_members"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("duplicate_groups.id"), nullable=False)
    photo_id = Column(Integer, ForeignKey("photos.id"), nullable=False)
