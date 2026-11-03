"""文档上传、解析、查询和删除接口测试。"""

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pymupdf
import pytest

from research_agent.core.config import Settings

pytestmark = pytest.mark.anyio

DOCUMENTS_URL = "/api/v1/documents"


def make_pdf_bytes(page_texts: Sequence[str]) -> bytes:
    """动态创建包含指定页面文本的最小有效 PDF。"""
    document = pymupdf.open()
    try:
        for text in page_texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text, fontsize=12)
        return document.tobytes()
    finally:
        document.close()


async def upload_pdf(
    client: httpx.AsyncClient,
    *,
    filename: str = "paper.pdf",
    content: bytes | None = None,
    content_type: str = "application/pdf",
) -> httpx.Response:
    """通过 multipart/form-data 上传 PDF 字节。"""
    pdf_bytes = content if content is not None else make_pdf_bytes(["Test page"])
    return await client.post(
        DOCUMENTS_URL,
        files={"file": (filename, pdf_bytes, content_type)},
    )


async def test_upload_valid_pdf(
    client: httpx.AsyncClient,
    test_settings: Settings,
) -> None:
    """有效 PDF 应返回 201，并保存 PDF、元数据和基本信息。"""
    pdf_bytes = make_pdf_bytes(["First page"])
    response = await upload_pdf(client, content=pdf_bytes)

    assert response.status_code == 201
    document = response.json()
    UUID(document["id"])
    assert document["original_filename"] == "paper.pdf"
    assert document["stored_filename"] == f"{document['id']}.pdf"
    assert document["file_size"] == len(pdf_bytes)
    assert document["page_count"] == 1
    assert document["status"] == "processed"
    assert document["pages"][0]["page_number"] == 1

    created_at = datetime.fromisoformat(document["created_at"])
    assert created_at.utcoffset() == timedelta(0)

    assert (
        test_settings.documents_dir / document["stored_filename"]
    ).is_file()
    assert (
        test_settings.metadata_dir / f"{document['id']}.json"
    ).is_file()


async def test_get_document_detail(client: httpx.AsyncClient) -> None:
    """上传后应能按 ID 查询完整文档详情。"""
    upload_response = await upload_pdf(
        client,
        content=make_pdf_bytes(["Page one", "Page two"]),
    )
    document_id = upload_response.json()["id"]

    response = await client.get(f"{DOCUMENTS_URL}/{document_id}")

    assert response.status_code == 200
    document = response.json()
    assert document["id"] == document_id
    assert document["page_count"] == 2
    assert len(document["pages"]) == 2


async def test_page_numbers_start_at_one(client: httpx.AsyncClient) -> None:
    """页面页码必须从 1 开始连续递增。"""
    upload_response = await upload_pdf(
        client,
        content=make_pdf_bytes(["First", "Second", "Third"]),
    )
    document_id = upload_response.json()["id"]

    response = await client.get(f"{DOCUMENTS_URL}/{document_id}")

    page_numbers = [page["page_number"] for page in response.json()["pages"]]
    assert page_numbers == [1, 2, 3]


async def test_page_text_and_character_count(
    client: httpx.AsyncClient,
) -> None:
    """每页文本应被保留，character_count 应与文本长度一致。"""
    upload_response = await upload_pdf(
        client,
        content=make_pdf_bytes(["Alpha page content", "Beta page content"]),
    )
    document_id = upload_response.json()["id"]

    response = await client.get(f"{DOCUMENTS_URL}/{document_id}")
    pages = response.json()["pages"]

    assert "Alpha page content" in pages[0]["text"]
    assert "Beta page content" in pages[1]["text"]
    assert pages[0]["character_count"] == len(pages[0]["text"])
    assert pages[1]["character_count"] == len(pages[1]["text"])


async def test_list_documents_total(
    client: httpx.AsyncClient,
    test_settings: Settings,
) -> None:
    """文档列表应返回正确的 total、分页信息和摘要字段。"""
    first = await upload_pdf(
        client,
        filename="first.pdf",
        content=make_pdf_bytes(["First document"]),
    )
    second = await upload_pdf(
        client,
        filename="second.pdf",
        content=make_pdf_bytes(["Second document"]),
    )
    assert first.status_code == 201
    assert second.status_code == 201

    response = await client.get(DOCUMENTS_URL)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert len(payload["items"]) == 2
    assert all("pages" not in item for item in payload["items"])
    assert all(
        (test_settings.metadata_dir / f"{item['id']}.json").is_file()
        for item in payload["items"]
    )


async def test_get_missing_document_returns_404(
    client: httpx.AsyncClient,
) -> None:
    """不存在的文档 ID 应返回 404。"""
    response = await client.get(f"{DOCUMENTS_URL}/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"detail": "文档不存在"}


async def test_delete_document_returns_204(
    client: httpx.AsyncClient,
    test_settings: Settings,
) -> None:
    """删除文档应返回 204，并删除 PDF 和元数据文件。"""
    upload_response = await upload_pdf(client)
    document = upload_response.json()

    response = await client.delete(f"{DOCUMENTS_URL}/{document['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert not (
        test_settings.documents_dir / document["stored_filename"]
    ).exists()
    assert not (
        test_settings.metadata_dir / f"{document['id']}.json"
    ).exists()


async def test_deleted_document_returns_404(
    client: httpx.AsyncClient,
) -> None:
    """删除后查询详情应返回 404。"""
    upload_response = await upload_pdf(client)
    document_id = upload_response.json()["id"]
    await client.delete(f"{DOCUMENTS_URL}/{document_id}")

    response = await client.get(f"{DOCUMENTS_URL}/{document_id}")

    assert response.status_code == 404


async def test_upload_txt_rejected(
    client: httpx.AsyncClient,
    test_settings: Settings,
) -> None:
    """非 PDF 扩展名应返回 400，且不留下文件。"""
    response = await client.post(
        DOCUMENTS_URL,
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "只支持 PDF 文件"}
    assert list(test_settings.documents_dir.iterdir()) == []
    assert list(test_settings.metadata_dir.iterdir()) == []


async def test_non_pdf_content_type_rejected(
    client: httpx.AsyncClient,
) -> None:
    """扩展名正确但 Content-Type 明确为非 PDF 时应返回 400。"""
    response = await upload_pdf(
        client,
        content=make_pdf_bytes(["Valid PDF bytes"]),
        content_type="text/plain",
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "只支持 PDF 文件"}


async def test_empty_filename_rejected(
    client: httpx.AsyncClient,
) -> None:
    """文件名为空时应返回 400，而不是进入 PDF 解析。"""
    response = await client.post(
        DOCUMENTS_URL,
        files={"file": ("", b"%PDF-1.7\n", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "文件名不能为空"}


async def test_forged_pdf_rejected(
    client: httpx.AsyncClient,
    test_settings: Settings,
) -> None:
    """伪造或损坏的 PDF 应返回 400，不留下成功元数据或 PDF。"""
    response = await upload_pdf(
        client,
        content=b"%PDF-1.7\nthis is not a valid pdf",
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "PDF 文件损坏或无法解析"}
    assert list(test_settings.documents_dir.iterdir()) == []
    assert list(test_settings.metadata_dir.iterdir()) == []


async def test_oversized_upload_rejected(
    client: httpx.AsyncClient,
    test_settings: Settings,
) -> None:
    """超过 1 MB 测试限制的上传应返回 413，并清理临时文件。"""
    oversized = b"%PDF-1.7\n" + b"0" * (1024 * 1024)
    response = await upload_pdf(client, content=oversized)

    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]
    assert list(test_settings.documents_dir.iterdir()) == []
    assert list(test_settings.metadata_dir.iterdir()) == []


async def test_path_traversal_filename_is_sanitized(
    client: httpx.AsyncClient,
    test_settings: Settings,
) -> None:
    """带路径的用户文件名不能决定保存路径。"""
    response = await upload_pdf(
        client,
        filename="../../evil.pdf",
        content=make_pdf_bytes(["Traversal test"]),
    )

    assert response.status_code == 201
    document = response.json()
    assert document["original_filename"] == "evil.pdf"
    assert document["stored_filename"] == f"{document['id']}.pdf"

    stored_files = [
        path.name for path in test_settings.documents_dir.iterdir()
    ]
    assert stored_files == [document["stored_filename"]]
    assert not (test_settings.documents_dir / "evil.pdf").exists()


async def test_blank_pdf_page_is_preserved(
    client: httpx.AsyncClient,
) -> None:
    """空白 PDF 页面不应导致服务崩溃，文本应为空字符串。"""
    upload_response = await upload_pdf(
        client,
        content=make_pdf_bytes([""]),
    )

    assert upload_response.status_code == 201
    document = upload_response.json()
    assert document["page_count"] == 1
    assert document["pages"] == [
        {
            "page_number": 1,
            "text": "",
            "character_count": 0,
        }
    ]


async def test_delete_does_not_remove_other_documents(
    client: httpx.AsyncClient,
    test_settings: Settings,
) -> None:
    """删除一个文档不能影响同一目录中的其他文档。"""
    first = await upload_pdf(
        client,
        filename="first.pdf",
        content=make_pdf_bytes(["First"]),
    )
    second = await upload_pdf(
        client,
        filename="second.pdf",
        content=make_pdf_bytes(["Second"]),
    )
    first_document = first.json()
    second_document = second.json()

    delete_response = await client.delete(
        f"{DOCUMENTS_URL}/{first_document['id']}"
    )
    assert delete_response.status_code == 204

    detail_response = await client.get(
        f"{DOCUMENTS_URL}/{second_document['id']}"
    )
    assert detail_response.status_code == 200
    assert (
        test_settings.documents_dir / second_document["stored_filename"]
    ).is_file()
    assert not (
        test_settings.documents_dir / first_document["stored_filename"]
    ).exists()


async def test_metadata_json_uses_utf8(
    client: httpx.AsyncClient,
    test_settings: Settings,
) -> None:
    """元数据应以 UTF-8 保存，中文文件名不能被 ASCII 转义。"""
    response = await upload_pdf(
        client,
        filename="论文.pdf",
        content=make_pdf_bytes(["UTF-8 metadata"]),
    )

    assert response.status_code == 201
    document = response.json()
    metadata_path = test_settings.metadata_dir / f"{document['id']}.json"
    raw_text = metadata_path.read_text(encoding="utf-8")

    assert "论文.pdf" in raw_text
    assert "\\u8bba\\u6587" not in raw_text
    payload = json.loads(raw_text)
    assert payload["original_filename"] == "论文.pdf"


async def test_list_pagination(
    client: httpx.AsyncClient,
) -> None:
    """列表接口应正确处理 page 和 page_size。"""
    for index in range(3):
        response = await upload_pdf(
            client,
            filename=f"paper-{index}.pdf",
            content=make_pdf_bytes([f"Page {index}"]),
        )
        assert response.status_code == 201

    response = await client.get(
        DOCUMENTS_URL,
        params={"page": 1, "page_size": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert len(payload["items"]) == 2
