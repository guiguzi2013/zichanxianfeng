"""文件上传校验：指纹去重 + 魔数双重校验（技术文档 5.8）

- 指纹 = 文件名 + 大小 + lastModified（前端提供 lastModified，后端计算大小）
- 魔数：按扩展名校验文件头字节，防伪装文件
"""
import hashlib
import logging

logger = logging.getLogger(__name__)

# 扩展名 → 魔数（文件头字节，十六进制前缀）
MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    ".xlsx": [b"PK\x03\x04"],                       # zip (xlsx/docx)
    ".xls": [b"\xd0\xcf\x11\xe0"],                  # OLE2
    ".docx": [b"PK\x03\x04"],
    ".doc": [b"\xd0\xcf\x11\xe0"],
    ".pdf": [b"%PDF"],
    ".txt": [b"", b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"],  # 纯文本/带BOM
    ".md": [b"", b"\xef\xbb\xbf"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".webp": [b"RIFF"],
    ".bmp": [b"BM"],
}


def compute_fingerprint(filename: str, size: int, last_modified: int | None = None) -> str:
    """文件指纹 = md5(文件名 + 大小 + lastModified)"""
    raw = f"{filename}|{size}|{last_modified or 0}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def check_magic(ext: str, content: bytes) -> bool:
    """魔数校验：文件头是否匹配扩展名对应的签名"""
    ext = ext.lower()
    sigs = MAGIC_SIGNATURES.get(ext)
    if sigs is None:
        # 未登记扩展名：只做大小校验，不拒绝
        return True
    head = content[:16]
    for sig in sigs:
        if not sig:  # 空签名表示任何内容均可（txt/md）
            return True
        if head.startswith(sig):
            return True
    return False


def validate_upload(filename: str, content: bytes, last_modified: int | None = None) -> dict:
    """上传文件校验：返回 {ok, fingerprint, ext, error}"""
    import os
    ext = os.path.splitext(filename)[1].lower()
    if ext not in MAGIC_SIGNATURES:
        return {"ok": False, "error": f"不支持的文件格式 {ext or '(无扩展名)'}"}
    if len(content) > 10 * 1024 * 1024:
        return {"ok": False, "error": "文件过大（超过 10MB）"}
    if not check_magic(ext, content):
        return {"ok": False, "error": f"文件内容与扩展名 {ext} 不符，可能为伪装文件"}
    return {
        "ok": True,
        "ext": ext,
        "size": len(content),
        "fingerprint": compute_fingerprint(filename, len(content), last_modified),
    }
