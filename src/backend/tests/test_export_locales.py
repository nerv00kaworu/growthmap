import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace
from api.routes import _render_content_blocks, _render_bound_docs, EXPORT_LABELS


def block(kind, **content):
    return SimpleNamespace(block_type=kind, content=content)


def test_markdown_export_chrome_has_three_real_locales():
    blocks = [block("note", title="T", body="B"), block("resource", title="D", url="https://example.test")]
    expected = {
        "en": ("Content blocks", "Note", "Attached documents"),
        "zh-CN": ("内容区块", "笔记", "绑定文件"),
        "zh-TW": ("內容區塊", "筆記", "綁定文件"),
    }
    for locale, labels in expected.items():
        rendered = "\n".join(_render_content_blocks(blocks, locale=locale) + _render_bound_docs(blocks, locale=locale))
        assert all(label in rendered for label in labels)
    assert EXPORT_LABELS["en"]["spec"] == "Specification"
    assert EXPORT_LABELS["zh-CN"]["spec"] == "规格文档"
    assert EXPORT_LABELS["zh-TW"]["spec"] == "規格文件"
