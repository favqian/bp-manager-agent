"""聊天意图：轻量规则。Conversation Intent 管怎么聊，health slot 管问哪块。"""

from __future__ import annotations

from typing import Any

from contract import Assessment
from prompts.scenes import _mm, crisis_reading_fact

CONV_GREETING = "GREETING"
CONV_HEALTH = "HEALTH_QUERY"
CONV_EMOTION = "EMOTIONAL_SUPPORT"
CONV_OFF = "OFF_TOPIC"
CONV_MEDICAL = "MEDICAL_BOUNDARY"

_MED = ("停药", "减半", "减药", "加量", "加一片", "半片", "换药", "剂量", "改成")
_CURED = ("好了", "好没好", "好不好", "治愈", "痊愈", "恢复正常", "没病", "治好")
_MEASURE = ("忘了测", "忘记测", "漏测", "还要测", "要测吗", "没测", "补测", "今天测")
_PATTERN = ("早上", "早晨", "晨", "晚上", "晚间", "晨晚")
_TREND = ("好转", "趋势", "下降", "升高", "变好", "变差", "往下", "升了", "降了")
_FAMILY = ("我妈", "我爸", "她的", "他的数", "家属")
_FOLLOWUP = ("那", "所以", "那我", "那现在")
_EMOTION = ("好烦", "不想测", "懒得测", "太麻烦", "不想管", "好累", "烦死", "不想记")
_GREET = ("你好", "您好", "在吗", "嗨", "哈喽", "hello", "hi")
_OFF = ("笑话", "天气", "写代码", "代码", "唱歌", "讲个故事", "明星")
_GLOSSARY = ("依从率", "达标率", "收缩压", "舒张压")
_HEALTH_CUE = (
    "怎么样",
    "血压",
    "高压",
    "低压",
    "测",
    "药",
    "高吗",
    "低吗",
    "记录",
    "早上",
    "晚上",
    "趋势",
    "依从",
    "达标",
    "收缩",
    "舒张",
)


def _prior_user_text(history: list[dict[str, str]] | None) -> str:
    parts: list[str] = []
    for item in history or []:
        if item.get("role") == "user":
            parts.append(str(item.get("content") or ""))
    return " ".join(parts[-2:])


def _is_glossary(query: str) -> bool:
    if not any(term in query for term in _GLOSSARY):
        return False
    return any(cue in query for cue in ("什么", "意思", "啥", "是啥"))


def _is_pure_greeting(query: str) -> bool:
    text = query.strip("。！？!?，, ")
    if len(text) > 16:
        return False
    if not any(key in query for key in _GREET) and text not in ("教练", "教练好"):
        return False
    if any(cue in query for cue in _HEALTH_CUE):
        return False
    return True


def classify_conversation_intent(
    user_query: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    query = (user_query or "").strip()
    if any(key in query for key in _MED) or any(key in query for key in _CURED):
        return CONV_MEDICAL
    if any(key in query for key in _EMOTION):
        return CONV_EMOTION
    if _is_pure_greeting(query):
        return CONV_GREETING
    if any(key in query for key in _FAMILY) or any(key in query for key in _OFF):
        return CONV_OFF
    return CONV_HEALTH


def classify_health_slot(
    user_query: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    query = (user_query or "").strip()
    if _is_glossary(query):
        return "glossary"
    if any(key in query for key in _MEASURE):
        return "measure"
    if any(key in query for key in _PATTERN):
        return "pattern"
    if any(key in query for key in _TREND):
        return "trend"
    if query.startswith(_FOLLOWUP) or query.endswith("呢") or query.endswith("呢？"):
        prior = classify_health_slot(_prior_user_text(history), None)
        if prior != "overview":
            return prior
    return "overview"


def classify_intent(user_query: str, history: list[dict[str, str]] | None = None) -> str:
    """兼容旧接口：对话层优先，健康问句再落到 slot。"""
    conv = classify_conversation_intent(user_query, history)
    if conv != CONV_HEALTH:
        return conv
    return classify_health_slot(user_query, history)


def chat_turn_instruction(
    user_msg: str,
    history: list[dict[str, str]] | None = None,
    display_name: str | None = None,
) -> str:
    conv = classify_conversation_intent(user_msg, history)
    slot = classify_health_slot(user_msg, history) if conv == CONV_HEALTH else ""
    name_hint = ""
    if display_name:
        name_hint = f"必要时可称呼「{display_name}」，不要每句都叫名字。\n"
    common = (
        name_hint
        + "用短句。每句尽量不超过20个字。\n"
        "只引用【判读结果】已有数字，禁止自行计算。\n"
        "用户侧说人话：高压/低压、测得少、看不出变化。不要说依从率、达标率、目标范围、收缩压、内部状态名。\n"
        "不要把 140/90 说成治疗目标。默认不要报达标百分比。\n"
        "不要输出 CONNECT/STATUS 等标题。不要说系统、规则、Assessment、State。\n"
        "安全边界高于语气。escalation_required 时，健康问题必须保留就医动作。"
    )
    if conv == CONV_GREETING:
        extra = "这是打招呼。先问好并邀请聊血压，不要输出血压报表或那次高压数字。"
    elif conv == CONV_EMOTION:
        extra = "先接住烦或累。不要先报一串数字。行动只说今天先完成一次，不要说改测量计划。若需就医，补一句让医生看。"
    elif conv == CONV_OFF:
        extra = "短承接后说明你陪看血压和记录，给一个回到健康话题的入口。不要长答无关内容。"
    elif conv == CONV_MEDICAL:
        extra = "接住停药或好了没有的关切。不能决定停药，不能说已经好了。引导把记录带给医生。"
    elif slot == "glossary":
        extra = "用户在问专业词。先说人话解释，不要写成教科书。"
    elif slot == "measure":
        extra = "围绕漏测。不责备。今天先测一次就好。"
    elif slot == "pattern":
        extra = "回答早上和晚上。用人话说早上比晚上高多少。数字用已有 delta。"
    elif slot == "trend":
        extra = "只说最近变化大不大或往下走。数据不够就说看不出变化。"
    else:
        extra = (
            "先接住问题，再用1到2个人话事实，最后一步行动。"
            "记录少或看不清时：fact 只写「最近记录还少」，explain 写「最近是不是有点忙」「现在还看不出明显变化」。"
            "fact 不要写忙、忘、烦。"
            "不要说整体变化不大，那也是在判断趋势。"
            "不要推断变好或变差。"
            "JSON 的 disclaimers 必须包含策略卡已给的声明，不要漏、不要改成别的。"
            "若用户在汇报执行（测了/还没/去医院），围绕当前行动计划短答，不要重写周报。"
        )
    return "【本轮对话要求】\n" + extra + "\n" + common


def _pct_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 100))


def _hi(display_name: str | None, variant: int) -> str:
    if display_name:
        return f"你好呀，{display_name}。" if variant % 2 == 0 else f"{display_name}，你好。"
    return "你好呀。" if variant % 2 == 0 else "我在。"


def _state_action(assessment: Assessment) -> str:
    if assessment.escalation_required:
        return "先复测一次确认。尽快就医。"
    if assessment.sufficient is False:
        return "今天测一次就好。"
    if assessment.state == "MONITORING_GAP":
        return "今天早起后测一次就好。"
    if assessment.state == "MORNING_SURGE":
        return "把早晚记录留下来。用药别自己改。"
    if assessment.state == "SUSTAINED_HIGH":
        return "把这阵子记录留好。复诊时提出。"
    if assessment.state == "IMPROVING":
        return "继续观察。用药别自己改。"
    return "今天按平时测一次就好。"


def _crisis_sys(assessment: Assessment) -> str | None:
    maximum = assessment.bp.get("max_single") or {}
    value = maximum.get("sys")
    return _mm(value) if value is not None else None


def _gap_status(assessment: Assessment) -> tuple[str, str]:
    return "最近记录还少。", "最近是不是有点忙？现在还看不出明显变化。"


def _high_status(assessment: Assessment) -> tuple[str, str]:
    mean = _mm(assessment.bp.get("sys_mean_7d"))
    direction = (assessment.trend or {}).get("direction")
    if mean:
        fact = f"这周高压平均{mean}。"
    else:
        fact = "这周高压整体还偏高一些。"
    if direction == "improving":
        explain = "最近数字有往下走，但这周整体还是偏高。"
    else:
        explain = "最近测到的高压大多还在参考线以上。"
    return fact, explain


def _improve_status(assessment: Assessment) -> tuple[str, str]:
    compare = assessment.trend.get("compare_14d")
    if compare is not None:
        fact = f"近两周对比{float(compare):+.0f}。"
        explain = "这阵子数字在往下走。"
        return fact, explain
    return "最近整体变化不大。", "先按现在这样继续记。"


def _overview_status(assessment: Assessment) -> tuple[str, str]:
    if assessment.sufficient is False:
        return "目前数据不足，我无法判断趋势。", "最近记录还少。现在还看不出变化。"
    if assessment.escalation_required:
        return crisis_reading_fact(assessment), "这次需要优先处理。"
    if assessment.state == "MONITORING_GAP":
        return _gap_status(assessment)
    if assessment.state == "SUSTAINED_HIGH":
        return _high_status(assessment)
    if assessment.state == "IMPROVING":
        return _improve_status(assessment)
    if assessment.state == "MORNING_SURGE":
        return _pattern_status(assessment)
    mean = _mm(assessment.bp.get("sys_mean_7d"))
    if mean:
        return f"这周高压平均{mean}。", "最近整体变化不大。"
    return "先看最近的记录。", "有拿不准的直接问我就行。"


def _pattern_status(assessment: Assessment) -> tuple[str, str]:
    delta = assessment.pattern.get("delta")
    morning = _mm(assessment.pattern.get("morning_mean"))
    evening = _mm(assessment.pattern.get("evening_mean"))
    delta_txt = _mm(delta) if delta is not None else None
    if delta_txt is not None:
        return f"早上平均比晚上高{delta_txt}。", "早上的读数比晚上高一些。"
    if morning and evening:
        return f"早上{morning}，晚上{evening}。", "这是已记下的早晚读数。"
    return "没有成对的早晚记录。", "先把早晚都记下再看。"


def _measure_status(assessment: Assessment) -> tuple[str, str]:
    if assessment.sufficient is False:
        return "目前数据不足，我无法判断趋势。", "漏一次很常见。先把今天接上。"
    rate = _pct_int(assessment.adherence.get("rate_7d"))
    if rate is not None and rate < 50:
        return "这几天测得少了一些。", "漏一次很常见。先不用补很多。"
    return "这周基本都有测。", "漏一次也很常见。今天先接上。"


def _trend_status(assessment: Assessment) -> tuple[str, str]:
    if assessment.sufficient is False:
        return "目前数据不足，我无法判断趋势。", "最近记录还少。现在还看不出变化。"
    direction = (assessment.trend or {}).get("direction")
    compare = assessment.trend.get("compare_14d")
    if direction == "improving" and compare is not None:
        return f"近两周对比{float(compare):+.0f}。", "这阵子数字在往下走。"
    if compare is not None:
        return f"近两周对比{float(compare):+.0f}。", "最近整体变化不大。"
    return "最近整体变化不大。", "先继续按现在这样记。"


def _glossary_reply(query: str, assessment: Assessment | None = None) -> tuple[str, str, str]:
    if "依从率" in query:
        return (
            "就是该测的时候测了多少。",
            "也就是按计划完成测量的比例。",
            "想看你最近测得少不少，可以直接问我。",
        )
    if "达标率" in query:
        asking_number = any(key in query for key in ("多少", "几", "%", "比例", "具体"))
        rate = _pct_int((assessment.bp if assessment else {}).get("target_rate_30d"))
        if asking_number and rate is not None:
            return (
                "对照的是 Demo 参考线，不是治疗目标。",
                f"最近30天大约{rate}%的读数低于参考线。",
                "想看最近高压，直接问我就行。",
            )
        return (
            "就是记录里有多少次低于参考线。",
            "这不是给你定的治疗目标。",
            "想看最近高压怎么样，问我就行。",
        )
    if "收缩压" in query:
        return (
            "就是平时说的高压。",
            "第一次也可以叫高压（收缩压）。",
            "想看最近高压，直接问我就行。",
        )
    if "舒张压" in query:
        return (
            "就是平时说的低压。",
            "第一次也可以叫低压（舒张压）。",
            "想看最近低压，直接问我就行。",
        )
    return "这是记录里的说法。", "我可以用更直白的话讲。", "想看最近情况，问我就行。"


def query_fallback_draft(
    assessment: Assessment,
    user_query: str,
    history: list[dict[str, str]] | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    """确定性降级草稿。数字只读 Assessment。"""
    conv = classify_conversation_intent(user_query, history)
    slot = classify_health_slot(user_query, history)
    action = _state_action(assessment)
    extra_disclaimers: list[str] = []
    skip_escalation_prompt = conv in {CONV_GREETING, CONV_OFF}

    if conv == CONV_GREETING:
        variant = len((display_name or "") + (user_query or ""))
        fact = _hi(display_name, variant)
        explain = "今天想看看最近的血压？"
        action = "还是有别的健康问题想问我？"
    elif conv == CONV_OFF:
        query = user_query or ""
        if any(key in query for key in _FAMILY):
            fact = "我只能看当前这位的记录。"
            explain = "别人的数字我这边不能讲。"
            action = _state_action(assessment)
        elif "天气" in query:
            fact = "这类问题我这里不做判断。"
            explain = "我主要陪你看血压和记录。"
            action = "要不要看看最近的情况？"
        else:
            fact = "这个我先不展开啦。"
            explain = "我更擅长陪你看血压和记录。"
            action = "最近有哪里拿不准吗？"
    elif conv == CONV_EMOTION:
        fact = "天天记确实容易觉得烦。"
        explain = "先别给自己加很多任务。"
        if assessment.escalation_required:
            high = _crisis_sys(assessment)
            extra = f"那次高压{high}需要尽快让医生看看。" if high else "那次高压需要尽快让医生看看。"
            explain = extra
            action = "今天先把这次测上。尽快就医。"
        elif assessment.state == "MONITORING_GAP":
            action = "今天早起后测一次就好。"
        else:
            action = "今天先完成一次就好。"
    elif conv == CONV_MEDICAL:
        extra_disclaimers = ["非诊断声明", "非治愈声明"]
        if any(key in (user_query or "") for key in _MED):
            fact = "你是想确认能不能少吃药。"
            explain = "仅凭这些记录不能决定停药。"
            if assessment.escalation_required:
                action = "先别自己调整。尽快就医。"
            elif assessment.state == "MONITORING_GAP":
                action = "先别自己调整。今天早起后测一次就好。"
            else:
                action = "先别自己调整。复诊时带上记录。"
        else:
            fact = "现在还不能说已经好了。"
            explain = "数字有变化，也不能说明已经治好。"
            action = _state_action(assessment)
    elif slot == "glossary":
        fact, explain, action = _glossary_reply(user_query or "", assessment)
    elif slot == "measure":
        fact, explain = _measure_status(assessment)
        action = _state_action(assessment)
        if assessment.state == "MONITORING_GAP":
            action = "今天早起后测一次就好。"
    elif slot == "pattern":
        fact, explain = _pattern_status(assessment)
        action = _state_action(assessment)
    elif slot == "trend":
        fact, explain = _trend_status(assessment)
        action = _state_action(assessment)
    else:
        fact, explain = _overview_status(assessment)
        action = _state_action(assessment)

    if assessment.sufficient is False and "数据不足" not in (fact or "") + (explain or ""):
        fact = "目前数据不足，我无法判断趋势。"

    return {
        "intent": conv,
        "health_slot": slot if conv == CONV_HEALTH else "",
        "fact": (fact or "先看这次要做的事。").strip(),
        "explain": (explain or "按现在这样就好。").strip(),
        "action": action.strip(),
        "extra_disclaimers": extra_disclaimers,
        "skip_escalation_prompt": skip_escalation_prompt,
    }


# 兼容 loader 旧引用：默认健康问句指令。
CHAT_TURN_INSTRUCTION = chat_turn_instruction("我最近怎么样？")
