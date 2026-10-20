from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.document import Document, DocumentChunk, DocumentPage


class MaterialRepository:
    def create_document(
        self,
        session: Session,
        *,
        course_id: str,
        filename: str,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        status: str,
        error_code: str | None = None,
    ) -> Document:
        document = Document(
            course_id=course_id,
            filename=filename,
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=size_bytes,
            status=status,
            error_code=error_code,
        )
        session.add(document)
        session.flush()
        session.refresh(document)
        return document

    def get_document(self, session: Session, document_id: str) -> Document | None:
        statement = (
            select(Document)
            .where(Document.id == document_id)
            .options(selectinload(Document.pages), selectinload(Document.chunks))
        )
        return session.scalar(statement)

    def list_documents(self, session: Session, course_id: str) -> list[Document]:
        statement = (
            select(Document)
            .where(Document.course_id == course_id)
            .order_by(Document.created_at.desc())
            .options(selectinload(Document.pages), selectinload(Document.chunks))
        )
        return list(session.scalars(statement))

    def list_active_documents(self, session: Session, course_id: str) -> list[Document]:
        statement = (
            select(Document)
            .where(Document.course_id == course_id)
            .where(Document.archived_at.is_(None))
            .order_by(Document.created_at.desc())
            .options(selectinload(Document.pages), selectinload(Document.chunks))
        )
        return list(session.scalars(statement))

    def replace_pages_and_chunks(
        self,
        session: Session,
        *,
        document_id: str,
        pages: list[DocumentPage],
        chunks: list[DocumentChunk],
    ) -> None:
        session.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        for page in pages:
            session.add(page)
        for chunk in chunks:
            session.add(chunk)

    def delete_document(self, session: Session, document: Document) -> None:
        session.delete(document)

    def search_chunks(
        self, session: Session, *, course_id: str, query: str
    ) -> list[DocumentChunk]:
        statement = (
            select(DocumentChunk)
            .join(Document)
            .where(Document.course_id == course_id)
            .where(Document.archived_at.is_(None))
            .where(DocumentChunk.text.ilike(f"%{query}%"))
            .options(selectinload(DocumentChunk.document))
            .order_by(Document.created_at.desc(), DocumentChunk.page_start.asc())
        )
        return list(session.scalars(statement))

    def get_chunk(self, session: Session, chunk_id: str) -> DocumentChunk | None:
        statement = (
            select(DocumentChunk)
            .where(DocumentChunk.id == chunk_id)
            .options(selectinload(DocumentChunk.document))
        )
        return session.scalar(statement)
