from novel_app.chapters import chapter_title, parse_novel_chapters


def test_chinese_chapter_headings_split_preface_and_bodies():
    text = (
        "作品简介。\n\n"
        "第一章 雨夜\n"
        "林舟走进雨里。\n\n"
        "第2章：来客\n"
        "门外响起敲门声。"
    )

    chapters = parse_novel_chapters(text, "测试小说")

    assert [chapter.title for chapter in chapters] == [
        "序章",
        "第一章 雨夜",
        "第2章：来客",
    ]
    assert chapters[1].content == "林舟走进雨里。"
    assert chapters[2].content == "门外响起敲门声。"


def test_markdown_and_english_headings_are_supported():
    text = "## Chapter 1\nFirst body.\n\n# 第二章 归途\n第二段。"

    chapters = parse_novel_chapters(text, "测试小说")

    assert [chapter.title for chapter in chapters] == ["Chapter 1", "第二章 归途"]
    assert chapter_title("Chapter IV: Return") == "Chapter IV: Return"


def test_text_without_headings_remains_one_chapter():
    chapters = parse_novel_chapters("没有章节标题的原稿。", "旧宅")

    assert len(chapters) == 1
    assert chapters[0].title == "旧宅"
    assert chapters[0].content == "没有章节标题的原稿。"
