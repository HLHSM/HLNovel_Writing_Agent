from novel_app.memory import parse_memory, split_text


def test_split_text_respects_chunk_limit():
    text = "第一段。\n\n第二段很长。" * 20
    chunks = split_text(text, 30)
    assert "".join(chunks) == text
    assert all(len(chunk) <= 30 for chunk in chunks)


def test_parse_memory_handles_markdown_fence():
    memory = parse_memory('```json\n{"overview":"故事"}\n```')
    assert memory["overview"] == "故事"
    assert "characters" in memory


def test_context_budget_keeps_global_memory_and_recent_end(app):
    manager = app.extensions["novel_service"].memory
    context = manager.context_for(
        "开头" + "原文" * 300 + "必须保留的结尾",
        ["续写" * 100],
        {"overview": "必须保留的全局记忆", "characters": []},
    )
    assert "必须保留的全局记忆" in context
    assert "必须保留的结尾" in context
    assert "续写" in context
