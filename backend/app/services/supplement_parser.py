"""补充材料解析服务（P1）

上传文件 → 提取文本 → LLM 识别内容类型 → 分发到对应报告版块 → 触发重新生成。

P0/P1 实现分层：
1. 文本提取：txt 直接读；docx/pdf 需要 python-docx/pypdf（requirements 已加）；失败降级标注
2. 类型识别：优先扩展名；其次 LLM（mock 可用）
3. 分发：将识别结果写入 report.supplements（JSON），由 report_builder 在重新生成时引用
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

# 文件类型 → 建议分发版块
TYPE_TARGET = {
    "判决书": ["claim_basic", "legal"],
    "裁定书": ["legal"],
    "执行裁定": ["legal"],
    "评估报告": ["collateral"],
    "评估": ["collateral"],
    "尽调说明": ["risk", "disposal"],
    "情况说明": ["risk"],
    "合同": ["claim_basic"],
    "债权转让": ["claim_basic"],
}


def extract_text_from_file(path: str, file_type: str | None) -> str | None:
    """提取文件文本。失败返回 None（调用方标注'无法解析'）。"""
    try:
        if file_type in ("txt", "text", "md"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()[:20000]
        if file_type in ("docx",):
            from docx import Document  # 延迟导入

            doc = Document(path)
            return "\n".join(p.text for p in doc.paragraphs)[:20000]
        if file_type in ("pdf",):
            return _extract_pdf(path)
        if file_type in ("jpg", "jpeg", "png", "webp", "bmp"):
            return _ocr_image(path)
    except Exception as e:  # noqa: BLE001
        logger.warning("extract text failed for %s: %s", path, e)
        return None
    return None


def _extract_pdf(path: str) -> str | None:
    """PDF 文本提取：优先文字层；扫描版（文字不足）时逐页渲染 OCR，支持多页。"""
    from pypdf import PdfReader  # 延迟导入

    try:
        reader = PdfReader(path)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:  # noqa: BLE001
        logger.warning("pypdf failed for %s: %s", path, e)
        text = ""
    if text and len(text.strip()) >= 100:
        return text[:20000]
    # 扫描版 PDF：逐页转图 OCR
    ocr_text = _ocr_pdf_pages(path)
    return ocr_text[:20000] if ocr_text else (text[:20000] if text else None)


def _ocr_pdf_pages(path: str) -> str | None:
    """扫描版 PDF 逐页渲染 + OCR（PyMuPDF + RapidOCR）。"""
    import os
    import uuid

    try:
        import pymupdf  # PyMuPDF
    except ImportError:
        logger.warning("pymupdf 未安装，扫描版 PDF 无法识别")
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR  # 延迟导入
    except ImportError:
        logger.warning("rapidocr 未安装，扫描版 PDF 无法识别")
        return None
    try:
        ocr = RapidOCR()
        doc = pymupdf.open(path)
        parts: list[str] = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=200)
            img_path = os.path.join(os.path.dirname(path), f"_ocr_{uuid.uuid4().hex}.png")
            try:
                pix.save(img_path)
                result, _ = ocr(str(img_path))
                if result:
                    parts.append("\n".join(text for _, text, _ in result))
            finally:
                if os.path.exists(img_path):
                    try:
                        os.remove(img_path)
                    except OSError:
                        pass
            if i >= 30:  # 页数上限保护
                break
        return "\n".join(parts)[:20000] if parts else None
    except Exception as e:  # noqa: BLE001
        logger.warning("PDF OCR failed for %s: %s", path, e)
        return None


def _ocr_image(path: str) -> str | None:
    """图片 OCR（RapidOCR 离线引擎，中文支持）。未安装时返回 None。"""
    try:
        from rapidocr_onnxruntime import RapidOCR  # 延迟导入
    except ImportError:
        logger.warning("rapidocr 未安装，图片识别不可用")
        return None
    try:
        ocr = RapidOCR()
        result, _ = ocr(str(path))
        if result:
            return "\n".join(text for _, text, _ in result)[:20000]
    except Exception as e:  # noqa: BLE001
        logger.warning("OCR failed for %s: %s", path, e)
    return None


def classify_content(text: str | None, filename: str = "") -> dict:
    """识别文件内容类型与目标版块。

    Returns:
        {"file_type": "判决书|评估报告|...", "target_sections": [...], "summary": "..."}
    """
    # 文件名关键词优先
    name_hint = ""
    for kw, target in TYPE_TARGET.items():
        if kw in filename:
            name_hint = kw
            break

    if text:
        for kw, target in TYPE_TARGET.items():
            if kw in text[:500]:
                return {
                    "file_type": kw,
                    "target_sections": target,
                    "summary": _make_summary(text),
                }

    if name_hint:
        return {
            "file_type": name_hint,
            "target_sections": TYPE_TARGET[name_hint],
            "summary": f"（文件名识别）{filename}",
        }

    return {
        "file_type": "其他材料",
        "target_sections": ["risk"],
        "summary": _make_summary(text) if text else "无法解析内容，请人工查看",
    }


def _make_summary(text: str, max_len: int = 300) -> str:
    """生成内容摘要（取前 N 字，去空白）"""
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean[:max_len] + ("…" if len(clean) > max_len else "")
