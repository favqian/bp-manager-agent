"""聊天意图：轻量规则，不改 State，不写死整段答案。"""

from __future__ import annotations

from typing import Any

from contract import Assessment
from prompts.scenes import _adherence_fact, _mm, _summary_fact, pattern_values_fact

CHAT_TURN_INSTRUCTION = """【本轮对话要求】
必须回应用户最后一句在问什么，不要只复述状态开场白。
策略卡只决定安全边界和必要行动，不替代用户问题。
只引用【判读结果】已有事实；没有的数据就说数据不足。
不诊断、不建议停药或改剂量。
超出本人血压记录/测量行为/当前状态/下一步时，说明做不到并拉回可答范围。"""

_MED = ("停药", "减半", "减药", "加量", "加一片", "半片", "换药", "剂量", "改成")
_CURED = ("好了", "好没好", "好不好", "治愈", "痊愈", "恢复正常", "没病")
_MEASURE = ("忘了测", "忘记测", "漏测", "还要测", "要测吗", "没测", "补测", "今天测")
_PATTERN = ("早上", "早晨", "晨", "晚上", "晚间", "晨晚")
_TREND = ("好转", "趋势", "下降", "升高", "变好", "变差", "往下", "升了", "降了")
_FAMILY = ("我妈", "我爸", "她的", "他的数", "家属")
_FOLLOWUP = ("那", "所以", "那我", "那现在")


def _prior_user_text(history: list[dict[str, str]] | None) -> str:
    parts: list[str] = []
    for item in history or []:
        if item.get("role") == "user":
            parts.append(str(item.get("content") or ""))
    return " ".join(parts[-2:])


def _match(query: str) -> str | None:
    if any(key in query for key in _FAMILY):
        return "oos"
    if any(key in query for key in _MED):
        return "med"
    if any(key in query for key in _CURED):
        return "cured"
    if any(key in query for key in _MEASURE):
        return "measure"
    if any(key in query for key in _PATTERN):
        return "pattern"
    if any(key in query for key in _TREND):
        return "trend"
    return None


def classify_intent(user_query: str, history: list[dict[str, str]] | None = None) -> str:
    query = (user_query or "").strip()
    matched = _match(query)
    if matched:
        return matched
    if query.startswith(_FOLLOWUP) or query.endswith("呢") or query.endswith("呢？"):
        prior = _match(_prior_user_text(history))
        if prior:
            return prior
    return "overview"


def _pattern_fact(assessment: Assessment) -> str:
    return pattern_values_fact(assessment)


def _trend_fact(assessment: Assessment) -> str:
    compare = assessment.trend.get("compare_14d")
    sys7 = _mm(assessment.bp.get("sys_mean_7d"))
    parts: list[str] = []
    if sys7:
        parts.append(f"近7天均值{sys7}。")
    if compare is not None:
        parts.append(f"近14天对比{float(compare):+.0f}。")
    return "".join(parts)


def _state_action(assessment: Assessment) -> str:
    if assessment.escalation_required:
        return "尽快就医。先复测一次确认。"
    if assessment.sufficient is False:
        return "今天测一次就行。"
    if assessment.state == "MONITORING_GAP":
        return "今天早起后测一次就行。"
    if assessment.state == "MORNING_SURGE":
        return "把晨晚差记录下来。用药别自己改。"
    if assessment.state == "SUSTAINED_HIGH":
        return "把近窗记录下来，复诊时提出。"
    if assessment.state == "IMPROVING":
        return "继续观察，用药别自己改。"
    return "照现在这样测就行。"


def query_fallback_draft(
    assessment: Assessment,
    user_query: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """按意图选事实与解释；行动仍交给 State 安全覆盖。不编造数字。"""
    intent = classify_intent(user_query, history)
    action = _state_action(assessment)
    extra_disclaimers: list[str] = []

    if intent == "measure":
        fact = _adherence_fact(assessment)
        explain = "忙忘了就补测一次。"
    elif intent == "pattern":
        fact = _pattern_fact(assessment)
        if fact:
            explain = "这是已有晨晚记录。"
        else:
            fact = _summary_fact(assessment)
            explain = "没有成对晨晚记录。"
    elif intent == "trend":
        fact = _trend_fact(assessment)
        if assessment.sufficient is False or not fact:
            explain = "目前数据不足，我无法判断趋势。"
        else:
            explain = "只看已有对比，不下结论。"
    elif intent == "cured":
        fact = _summary_fact(assessment)
        explain = "我不能下这个结论。"
    elif intent == "med":
        fact = _summary_fact(assessment)
        explain = "用药别自己改。"
        if assessment.escalation_required:
            action = "用药别自己改。尽快就医。"
    elif intent == "oos":
        fact = _adherence_fact(assessment)
        explain = "我只看当前这份记录。"
    else:
        fact = _summary_fact(assessment)
        explain = "这是近7天已有记录。"

    if assessment.sufficient is False and "数据不足" not in (fact or "") + explain:
        explain = "目前数据不足，我无法判断趋势。" + explain

    return {
        "intent": intent,
        "fact": (fact or "先看这次要做的事。").strip(),
        "explain": explain.strip(),
        "action": action,
        "extra_disclaimers": extra_disclaimers,
    }
