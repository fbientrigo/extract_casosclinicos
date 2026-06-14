from scanbook.cli import build_parser


def test_cli_includes_required_commands() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    for command in [
        "split",
        "render-pages",
        "ocr",
        "qa",
        "extract-cases",
        "build-index",
        "query",
        "audit-env",
    ]:
        assert command in help_text
