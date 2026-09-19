from office_assistant.naming import (
    apply_extension,
    build_new_filename,
    is_reserved_device_name,
    parse_name_list,
    sanitize_stem,
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
