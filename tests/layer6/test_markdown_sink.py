"""markdown_sink.pyのテスト（layer6_report_generation_design.md §7）。"""

from ai_investment_assistant.layer6_report_generation.presentation_model import build_presentation_model
from ai_investment_assistant.layer6_report_generation.sinks.markdown_sink import MarkdownSink, render_markdown
from .sample_data import sample_decision_document


def test_render_markdown_contains_all_required_sections():
    model = build_presentation_model(sample_decision_document())
    text = render_markdown(model)
    for section in ["## 市場環境", "## データ品質", "## 本日の提案", "## 除外・不採用候補",
                     "## ルール適用ログ", "## 実行ログ"]:
        assert section in text


def test_render_markdown_market_environment_is_honest_placeholder():
    model = build_presentation_model(sample_decision_document())
    text = render_markdown(model)
    assert "現在のLayer5出力には市場全体情報が含まれないため省略" in text


def test_render_markdown_zero_proposals_shows_no_proposal_message():
    model = build_presentation_model(sample_decision_document(gate="blocked"))
    text = render_markdown(model)
    assert "本日は提案なし（該当候補なし）" in text


def test_render_markdown_warning_continued_shows_warning_codes():
    model = build_presentation_model(sample_decision_document(gate="warning_continued"))
    text = render_markdown(model)
    assert "検知された警告" in text
    assert "MINOR_SOURCE_TIMEOUT" in text


def test_render_markdown_includes_disclaimer_footer():
    model = build_presentation_model(sample_decision_document())
    text = render_markdown(model)
    assert "投資成果を保証するものではありません" in text


def test_render_markdown_preserves_proposal_values_exactly():
    model = build_presentation_model(sample_decision_document())
    text = render_markdown(model)
    assert "NVIDIA Corporation" in text
    assert "383.8" in text  # take_profit_price


class FakeDriveClient:
    def __init__(self):
        self.saved = {}

    def write_markdown_report(self, file_name, text):
        self.saved[file_name] = text
        return f"reports/{file_name}"


def test_markdown_sink_render_and_save_uses_jst_date_filename():
    model = build_presentation_model(sample_decision_document())
    client = FakeDriveClient()
    sink = MarkdownSink(client)
    path = sink.render_and_save(model)
    assert path == "reports/report_20260718.md"
    assert "report_20260718.md" in client.saved
