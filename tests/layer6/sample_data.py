"""Layer6テスト用のサンプルdecision JSON（layer5_ai_judgment_design.md §9準拠）。"""


def sample_decision_document(gate="passed"):
    return {
        "run_meta": {
            "run_id": "20260718-0630",
            "layer5_started_at": "2026-07-18T06:30:05Z",
            "layer5_completed_at": "2026-07-18T06:34:40Z",
            "data_quality_gate": gate,
            "data_quality_gate_detail": {
                "blocking_errors_found": [{"code": "LAYER_PIPELINE_NOT_COMPLETED", "message": "未完了"}]
                if gate == "blocked" else [],
                "warning_errors_found": [{"code": "MINOR_SOURCE_TIMEOUT", "message": "一部遅延"}]
                if gate == "warning_continued" else [],
            },
            "score_meta_ref": {"scoring_version": "1.0.0", "weight_version": "2026-07"},
        },
        "proposals": [] if gate == "blocked" else [
            {
                "rank": 2, "asset_class": "us_equity", "ticker": "AMD", "name": "Advanced Micro Devices",
                "overall_assessment": "buy", "recommended_shares": 3, "entry_price_basis": 150.0,
                "position_amount": 450.0, "stop_loss_price": 135.0, "take_profit_target_pct": 12.0,
                "take_profit_price": 168.0, "take_profit_basis": "AI需要拡大",
                "expected_return_pct": 12.0, "expected_loss_pct": -10.0, "risk_reward_ratio": 1.2,
                "holding_period": "1〜3週間", "confidence": 70,
                "investment_reason": "AI需要拡大により堅調", "risk_factors": "競合激化",
                "score_summary": {
                    "technical": 75, "fundamental": 68, "supply_demand": 70, "macro": 60,
                    "news": {"score": 55, "uncertainty": 20}, "regime_fit": 80, "composite": 70,
                },
                "alternative_candidates": [],
            },
            {
                "rank": 1, "asset_class": "us_equity", "ticker": "NVDA", "name": "NVIDIA Corporation",
                "overall_assessment": "buy", "recommended_shares": 4, "entry_price_basis": 333.74,
                "position_amount": 1334.96, "stop_loss_price": 300.37, "take_profit_target_pct": 15.0,
                "take_profit_price": 383.80, "take_profit_basis": "決算成長期待と52週高値更新余地を考慮",
                "reference_price_type": "52_week_high", "reference_price": 350.0,
                "expected_return_pct": 15.0, "expected_loss_pct": -10.0, "risk_reward_ratio": 1.5,
                "holding_period": "2〜4週間", "confidence": 78,
                "investment_reason": "テクニカル・ファンダメンタル双方が良好",
                "risk_factors": "ニュース軸のuncertaintyが高い",
                "score_summary": {
                    "technical": 84, "fundamental": 71, "supply_demand": 78, "macro": 65,
                    "news": {"score": 63, "uncertainty": 35}, "regime_fit": 90, "composite": 79,
                },
                "alternative_candidates": ["AMD (rank 4)", "AVGO (rank 6)"],
            },
        ],
        "decision_log": [
            {"ticker": "NVDA", "decision": "adopted", "rank": 1, "reason_code": "ADOPTED_TOP_RANK"},
            {"ticker": "AMD", "decision": "adopted", "rank": 2, "reason_code": "ADOPTED_TOP_RANK"},
            {"ticker": "6723", "decision": "rejected", "reason_code": "DATA_DELAYED_12W", "reason": "データ品質ゲートで除外済み"},
            {"ticker": "TSM", "decision": "not_selected", "rank": 4, "reason_code": "DAILY_PROPOSAL_LIMIT_EXCEEDED", "reason": "3件制限のため見送り"},
        ],
        "rule_enforcement_log": [
            {"rule": "confidence_gate", "applied": False},
            {"rule": "daily_proposal_limit", "applied": True, "detail": "4件中1件を除外"},
        ],
    }
