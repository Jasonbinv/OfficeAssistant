from pathlib import Path

from office_assistant.naming import (
    apply_extension,
    apply_template,
    build_new_filename,
    format_page_ranges,
    index_width,
    is_reserved_device_name,
    natural_sort_key,
    parse_name_list,
    parse_page_ranges,
    sanitize_stem,
    unique_path,
    unique_path_excluding,
)


def test_parse_name_list_skips_blank_and_bom_and_excel_tab():
    text = "\ufeff水施-01_封皮\n\n  \n水施-01_图纸目录\t备注列\r\n水施-02_说明 "
    assert parse_name_list(text) == [
        "水施-01_封皮",
        "水施-01_图纸目录",
        "水施-02_说明",
    ]


def test_sanitize_strips_illegal_and_trailing_dot_space():
    assert sanitize_stem('a<>:"/\\|?*b. ') == "ab"


def test_reserved_device_names():
    assert is_reserved_device_name("CON")
    assert is_reserved_device_name("com1")
    assert not is_reserved_device_name("合同")


def test_extension_not_doubled_when_same():
    assert apply_extension("封皮.pdf", ".PDF") == "封皮.PDF"
    assert apply_extension("封皮", ".pdf") == "封皮.pdf"


def test_other_extension_is_kept_then_original_appended():
    assert apply_extension("foo.dwg", ".pdf") == "foo.dwg.pdf"


def test_build_new_filename_empty_after_sanitize():
    assert build_new_filename("***", ".pdf") == ".pdf"


def test_natural_sort_orders_like_explorer():
    names = ["扫描10.pdf", "扫描2.pdf", "扫描1.pdf"]
    assert sorted(names, key=natural_sort_key) == [
        "扫描1.pdf",
        "扫描2.pdf",
        "扫描10.pdf",
    ]


def test_index_width_grows_with_count():
    assert index_width(8) == 2
    assert index_width(100) == 3


def test_apply_template_default_pattern():
    name = apply_template(
        "{原名}_{序号}",
        original_stem="扫描",
        date="20260919",
        index=3,
        width=2,
        prefix="",
        suffix="",
    )
    assert name == "扫描_03"


def test_unique_path_adds_numeric_suffix(tmp_path: Path):
    first = tmp_path / "合同_合并.pdf"
    first.write_bytes(b"x")
    second = unique_path(first)
    assert second == tmp_path / "合同_合并_2.pdf"
    second.write_bytes(b"y")
    third = unique_path(first)
    assert third == tmp_path / "合同_合并_3.pdf"


def test_unique_path_excluding_skips_source_names(tmp_path: Path):
    dest = tmp_path / "out.pdf"
    dest.write_bytes(b"x")
    source = tmp_path / "out_2.pdf"
    result = unique_path_excluding(dest, [source])
    assert result == tmp_path / "out_3.pdf"
    assert result.resolve() != source.resolve()


def test_parse_and_format_page_ranges():
    parsed = parse_page_ranges("1,3,5-8,3,99", page_count=10)
    assert parsed.pages == {1, 3, 5, 6, 7, 8}
    assert parsed.errors  # 99 越界
    assert format_page_ranges({1, 3, 5, 6, 7, 8}) == "1,3,5-8"


def test_parse_page_ranges_rejects_empty_delete_all():
    parsed = parse_page_ranges("1-3", page_count=3)
    assert parsed.pages == {1, 2, 3}
