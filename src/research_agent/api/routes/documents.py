"""文档上传、列表、详情和删除路由。"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from ...schemas.documents import DocumentDetail, DocumentListResponse
from ...schemas.retrieval import IndexDocumentResponse
from ...services.document_service import DocumentService, DocumentServiceError
from ...services.embedding_service import (
    EMBEDDING_UNAVAILABLE_DETAIL,
    EmbeddingModelUnavailableError,
)
from ...services.indexing_service import IndexingService

router = APIRouter(prefix="/documents", tags=["documents"])

_UPLOAD_CHUNK_SIZE = 1024 * 1024


def get_document_service(request: Request) -> DocumentService:
    """从应用状态中取出文档服务。"""
    service: DocumentService = request.app.state.document_service
    return service


def get_indexing_service(request: Request) -> IndexingService:
    """从应用状态中取出索引服务。"""
    service: IndexingService = request.app.state.indexing_service
    return service


async def _iter_upload(file: UploadFile) -> AsyncIterator[bytes]:
    """按固定大小分块读取上传内容，避免把整个文件读入内存。"""
    while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
        yield chunk


def _http_exception(exc: DocumentServiceError) -> HTTPException:
    """把领域异常转换为统一的 HTTP 错误响应。"""
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post(
    "",
    response_model=DocumentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="上传 PDF 文档",
    description="校验并保存 PDF，按页解析文本并保存本地元数据。",
)
async def upload_document(
    file: Annotated[UploadFile | str, File(description="待上传的 PDF 文件")],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentDetail:
    """上传并解析一个 PDF 文档。"""
    if isinstance(file, str):
        # 空文件名会被 multipart 解析器当作普通表单字段。
        raise HTTPException(status_code=400, detail="文件名不能为空")

    try:
        return await service.create_document(
            filename=file.filename,
            content_type=file.content_type,
            chunks=_iter_upload(file),
        )
    except DocumentServiceError as exc:
        raise _http_exception(exc) from exc
    finally:
        await file.close()


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="查询文档列表",
    description="分页返回已保存文档的摘要信息，按创建时间倒序排列。",
)
async def list_documents(
    service: Annotated[DocumentService, Depends(get_document_service)],
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始")] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=100, description="每页数量，最大 100"),
    ] = 20,
) -> DocumentListResponse:
    """返回分页文档列表。"""
    try:
        return service.list_documents(page=page, page_size=page_size)
    except DocumentServiceError as exc:
        raise _http_exception(exc) from exc


@router.get(
    "/{document_id}",
    response_model=DocumentDetail,
    summary="查询文档详情",
    description="返回文档元数据和按页保存的文本。",
)
async def get_document(
    document_id: str,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentDetail:
    """按文档 UUID 查询详情。"""
    try:
        return service.get_document(document_id)
    except DocumentServiceError as exc:
        raise _http_exception(exc) from exc


@router.post(
    "/{document_id}/index",
    response_model=IndexDocumentResponse,
    summary="为文档创建或重建索引",
    description="按页分块并生成本地向量索引；模型不可用时返回 503。",
)
def index_document(
    document_id: str,
    service: Annotated[IndexingService, Depends(get_indexing_service)],
) -> IndexDocumentResponse:
    """建立或重建单份文档的本地向量索引。"""
    try:
        return service.index_document(document_id)
    except EmbeddingModelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=EMBEDDING_UNAVAILABLE_DETAIL,
        ) from exc
    except DocumentServiceError as exc:
        raise _http_exception(exc) from exc


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除文档",
    description="同时删除文档 PDF、JSON 元数据、chunk 文件和向量索引记录。",
)
async def delete_document(
    document_id: str,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> Response:
    """删除指定文档。"""
    try:
        service.delete_document(document_id)
    except DocumentServiceError as exc:
        raise _http_exception(exc) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)
