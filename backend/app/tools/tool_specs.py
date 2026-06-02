from __future__ import annotations

from pathlib import Path
import os
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import yaml

from app.social.forced_actions import FORCED_SOCIAL_ACTION_TOOL_TYPES, FORCED_SOCIAL_RESPONSE_TOOLS


TargetPolicy = Literal["none", "visible_ref", "known_name", "item", "location"]
REMOVED_EXTERNAL_TOOL_PREFIXES = ("fairy", "rain")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    tool_name: str
    display_name: str
    description_for_llm: str
    required_location_tags: list[str] = field(default_factory=list)
    target_policy: TargetPolicy = "none"
    allowed_lifecycle_states: list[str] = field(default_factory=lambda: ["alive"])
    time_cost_minutes: int = 10
    cooldown_minutes: int = 0
    resource_cost: dict[str, int] = field(default_factory=dict)
    hard_effect_id: str = "none"
    event_importance: int = 10
    triggers_reaction: bool = False
    visibility: str = "same_location"
    catalog_category: str | None = None
    effect_summary: str | None = None
    source_version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


TOOL_SPECS: dict[str, ToolSpec] = {
    "look_around": ToolSpec("look_around", "环顾四周", "查看当前位置、附近人物和可见物品。", event_importance=5, hard_effect_id="look"),
    "observe_visible_agent": ToolSpec("observe_visible_agent", "观察眼前的人", "用 visible_ref 观察某个可见者的外貌和明显状态。", target_policy="visible_ref", hard_effect_id="observe", event_importance=20),
    "check_self_status": ToolSpec("check_self_status", "检查自身状态", "查看自己的身体和情绪状态。", event_importance=5, hard_effect_id="self_status"),
    "move_to_location": ToolSpec("move_to_location", "移动到地点", "移动到一个相邻地点，参数 location_name 或 location_id。", target_policy="location", time_cost_minutes=15, hard_effect_id="move"),
    "return_home": ToolSpec("return_home", "回到自己的住所", "回到自己的住所/小屋；如果参数 sleep_after_arrival=true，会到家后直接安排真实长睡眠。否则只回家，不强制睡。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=15, hard_effect_id="return_home", event_importance=30),
    "wander": ToolSpec("wander", "随便走走", "随机前往一个可达相邻地点。", target_policy="location", time_cost_minutes=15, hard_effect_id="wander"),
    "knock_private_room": ToolSpec("knock_private_room", "敲私人小屋的门", "在相邻私人小屋门口敲门；有人愿意开门时才能进入，没人或对方不想开就进不去。参数 location_id。", target_policy="location", time_cost_minutes=5, hard_effect_id="knock_private_room", event_importance=35, triggers_reaction=True),
    "say_to_visible_agent": ToolSpec("say_to_visible_agent", "说一句话", "公开说一句中文；同地点的人都能听见，visible_ref 只表示你心里主要想回应谁，不限制听众。参数 speech 与 tone。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="say", event_importance=35, triggers_reaction=True),
    "speak_to_nearby": ToolSpec("speak_to_nearby", "向附近说话", "对同地所有人公开说一句中文。参数 speech 与 tone。", time_cost_minutes=5, hard_effect_id="speak", event_importance=35, triggers_reaction=True),
    "wake_visible_agent": ToolSpec("wake_visible_agent", "叫醒眼前的人", "如果 visible_ref 指向的人正在睡觉，而你确实需要现在交流或处理急事，可以轻声叫醒对方。参数 visible_ref、speech。", target_policy="visible_ref", time_cost_minutes=3, hard_effect_id="wake_visible_agent", event_importance=45, triggers_reaction=True),
    "ask_visible_agent_to_introduce": ToolSpec("ask_visible_agent_to_introduce", "询问姓名", "请求 visible_ref 指向的人自我介绍。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="ask_intro", event_importance=45, triggers_reaction=True),
    "introduce_self": ToolSpec("introduce_self", "正式自我介绍", "正式向 visible_ref 指向的人介绍自己。参数 reveal_name, reveal_gender, speech。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="intro", event_importance=70, triggers_reaction=True),
    "refuse_introduction": ToolSpec("refuse_introduction", "拒绝介绍", "回避或拒绝继续自我介绍，可附一句中文说明。", target_policy="visible_ref", time_cost_minutes=3, hard_effect_id="refuse_intro", event_importance=55, triggers_reaction=True),
    "ignore": ToolSpec("ignore", "不回应", "明确不回应当前刺激。", time_cost_minutes=2, hard_effect_id="ignore", event_importance=10),
    "wave_to_visible_agent": ToolSpec("wave_to_visible_agent", "挥手", "向 visible_ref 指向的人挥手。", target_policy="visible_ref", time_cost_minutes=2, hard_effect_id="wave", event_importance=20, triggers_reaction=True),
    "compliment_visible_agent": ToolSpec("compliment_visible_agent", "称赞", "称赞 visible_ref 指向的人。参数 speech。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="compliment", event_importance=35, triggers_reaction=True),
    "apologize_to_visible_agent": ToolSpec("apologize_to_visible_agent", "道歉", "向 visible_ref 指向的人道歉。参数 speech。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="apologize", event_importance=35, triggers_reaction=True),
    "help_visible_agent": ToolSpec("help_visible_agent", "帮助眼前的人", "帮助 visible_ref 指向且状态明显不好的人。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=10, hard_effect_id="help", event_importance=55, triggers_reaction=True),
    "move_closer_to_visible_agent": ToolSpec("move_closer_to_visible_agent", "靠近眼前的人", "靠近 visible_ref 指向的人，表达愿意交流。", target_policy="visible_ref", time_cost_minutes=3, hard_effect_id="move_closer", event_importance=20, triggers_reaction=True),
    "walk_away_from_visible_agent": ToolSpec("walk_away_from_visible_agent", "离开眼前的人", "离开 visible_ref 指向的人，必要时走向相邻地点。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="walk_away", event_importance=25),
    "eat_food": ToolSpec("eat_food", "吃食物", "在食堂等供餐地点买一份食物。花园只能采集，不能直接买饭。", required_location_tags=["food_service"], time_cost_minutes=20, hard_effect_id="eat", event_importance=15),
    "drink_water": ToolSpec("drink_water", "喝水", "在有水的地点喝水。", required_location_tags=["water"], time_cost_minutes=5, hard_effect_id="drink", event_importance=15),
    "sleep": ToolSpec("sleep", "睡觉", "在住所决定睡几个小时；单日最多真正睡 10 小时，睡眠期间不会行动，直到自然醒或被唤醒。参数 sleep_hours。", required_location_tags=["home"], allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=0, hard_effect_id="sleep", event_importance=25),
    "sleep_rough": ToolSpec("sleep_rough", "露宿睡觉", "在没有可用住所、无家可归、或主动选择不回家时，在当前地点找相对安全的角落睡一段时间。单日最多真正睡 10 小时；不是高质量睡眠；醒来会更脏、更紧张，并有被偷窃/惊醒风险。参数 sleep_hours。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=0, hard_effect_id="sleep_rough", event_importance=55),
    "rest": ToolSpec("rest", "短休息", "短休息以恢复体力和压力。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=45, hard_effect_id="rest", event_importance=20),
    "wash": ToolSpec("wash", "清洁", "在有条件的地点清洁身体。", required_location_tags=["home", "water"], time_cost_minutes=25, hard_effect_id="wash", event_importance=20),
    "soak_hot_spring": ToolSpec("soak_hot_spring", "泡温泉", "在温泉汤池花钱泡一会儿，彻底清洁身体并放松。", required_location_tags=["hot_spring"], time_cost_minutes=35, hard_effect_id="soak_hot_spring", event_importance=35),
    "invite_visible_agent_to_hot_spring": ToolSpec("invite_visible_agent_to_hot_spring", "邀请一起泡温泉", "邀请 visible_ref 指向的人一起去温泉；只是邀请，不会强制对方同行。参数 speech。", required_location_tags=["hot_spring_lobby", "hot_spring"], target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="generic_visible_social", event_importance=45, triggers_reaction=True),
    "seek_help": ToolSpec("seek_help", "求助", "向同地的人求助。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=5, hard_effect_id="seek_help", event_importance=60, triggers_reaction=True),
    "tell_story_nearby": ToolSpec("tell_story_nearby", "讲故事", "给附近的人讲一段中文故事。", time_cost_minutes=20, hard_effect_id="story", event_importance=60, triggers_reaction=True),
    "sing_nearby": ToolSpec("sing_nearby", "唱歌", "给附近的人唱一小段歌。", time_cost_minutes=15, hard_effect_id="sing", event_importance=55, triggers_reaction=True),
    "play_simple_game": ToolSpec("play_simple_game", "玩简单游戏", "发起一个简单游戏。", time_cost_minutes=30, hard_effect_id="game", event_importance=65, triggers_reaction=True),
    "walk_by_lake": ToolSpec("walk_by_lake", "湖边散步", "在湖边散步放松。", required_location_tags=["nature"], time_cost_minutes=25, hard_effect_id="walk_lake", event_importance=25),
    "write_diary": ToolSpec("write_diary", "写日记", "写一篇私密中文日记。参数 title, content。", time_cost_minutes=20, hard_effect_id="diary", event_importance=30, visibility="private"),
    "post_notice": ToolSpec("post_notice", "发布布告", "在布告栏发布公开中文消息。", required_location_tags=["notice"], time_cost_minutes=10, hard_effect_id="notice", event_importance=45, visibility="public"),
    "call_community_meeting": ToolSpec("call_community_meeting", "召集社区讨论", "在广场、营地、集市或布告栏发起一次普通公共讨论，可聊安全、住房、食物、工作、互助或生活约定。参数 content 或 speech。", required_location_tags=["social", "notice"], time_cost_minutes=15, hard_effect_id="governance_meeting", event_importance=55, triggers_reaction=True, visibility="public"),
    "propose_social_rule": ToolSpec("propose_social_rule", "提出建议", "提出一条普通社区建议、互助约定或做事办法。它只是公开提议，不会自动变成硬规则；其他居民可以支持、反对、修改或无视。参数 content。", required_location_tags=["social", "notice"], time_cost_minutes=15, hard_effect_id="governance_proposal", event_importance=60, triggers_reaction=True, visibility="public"),
    "support_social_rule": ToolSpec("support_social_rule", "支持建议", "公开支持最近的某条建议、约定或互助办法。参数 content 或 speech。", required_location_tags=["social", "notice"], time_cost_minutes=8, hard_effect_id="governance_support", event_importance=45, triggers_reaction=True, visibility="public"),
    "oppose_social_rule": ToolSpec("oppose_social_rule", "提出不同意见", "公开反对、质疑或提出修改最近的某条建议、约定或互助办法。参数 content 或 speech。", required_location_tags=["social", "notice"], time_cost_minutes=8, hard_effect_id="governance_oppose", event_importance=45, triggers_reaction=True, visibility="public"),
    "pick_up_item": ToolSpec("pick_up_item", "捡起物品", "捡起当前地点可见物品。参数 item_name。", target_policy="item", time_cost_minutes=5, hard_effect_id="pickup", event_importance=20),
    "give_item_to_visible_agent": ToolSpec("give_item_to_visible_agent", "赠送物品", "把物品给 visible_ref 指向的人。参数 item_name。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="give", event_importance=55, triggers_reaction=True),
    "offer_item_to_visible_agent": ToolSpec("offer_item_to_visible_agent", "递出物品", "把物品递给 visible_ref 指向的人。参数 item_name。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="give", event_importance=55, triggers_reaction=True),
    "grant_personal_resource_permission_visible_agent": ToolSpec("grant_personal_resource_permission_visible_agent", "授权使用个人资源", "把自己能合法使用的一项个人资源授权给 visible_ref 使用；默认授权自己的住所/小屋，也可用 resource_scope=all_personal_resources 表示概括授权。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="grant_permission", event_importance=50, triggers_reaction=True),
    "craft_simple_item": ToolSpec("craft_simple_item", "制作物品", "在工作坊制作一个简单物品。参数 item_name。", required_location_tags=["craft"], time_cost_minutes=45, hard_effect_id="craft", event_importance=35),
    "forage_food": ToolSpec("forage_food", "采集食物", "在花园采集 1 到 3 份野食。", required_location_tags=["natural_food", "nature"], time_cost_minutes=45, hard_effect_id="forage", event_importance=30),
    "add_memory": ToolSpec("add_memory", "写入长期记忆", "主动写入一条长期记忆。参数 content。", time_cost_minutes=10, hard_effect_id="memory", event_importance=25),
    "record_relationship_note_by_name": ToolSpec("record_relationship_note_by_name", "按姓名记录关系", "对一个已知姓名的人记录关系备注。参数 known_name, note。", target_policy="known_name", time_cost_minutes=10, hard_effect_id="relationship_note", event_importance=25),
    "introduce_other_agent": ToolSpec("introduce_other_agent", "介绍第三人", "向眼前的人介绍你已知姓名的第三人。参数 target_ref, known_name。", target_policy="visible_ref", time_cost_minutes=10, hard_effect_id="intro_other", event_importance=55, triggers_reaction=True),
    "send_private_letter_by_name": ToolSpec("send_private_letter_by_name", "按姓名寄信", "给已知姓名的人寄信。", target_policy="known_name", time_cost_minutes=20, hard_effect_id="letter", event_importance=35),
    "invite_named_agent_to_event": ToolSpec("invite_named_agent_to_event", "按姓名邀请", "邀请已知姓名的人参加未来活动。", target_policy="known_name", time_cost_minutes=10, hard_effect_id="invite", event_importance=45),
    "make_public_accusation_by_name": ToolSpec("make_public_accusation_by_name", "按姓名公开指控", "在布告栏公开指控已知姓名的人。", required_location_tags=["notice"], target_policy="known_name", time_cost_minutes=10, hard_effect_id="accuse", event_importance=75, triggers_reaction=True),
    "nominate_named_agent": ToolSpec("nominate_named_agent", "按姓名提名", "提名已知姓名的人做某事。", target_policy="known_name", time_cost_minutes=10, hard_effect_id="nominate", event_importance=45),
    "promise_to_named_agent": ToolSpec("promise_to_named_agent", "按姓名承诺", "对已知姓名的人记录承诺。", target_policy="known_name", time_cost_minutes=10, hard_effect_id="promise", event_importance=50),
    "do_nothing": ToolSpec("do_nothing", "什么也不做", "本回合不做主动行动。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=10, hard_effect_id="nothing", event_importance=5),
    "panic_pause": ToolSpec("panic_pause", "紧张停顿", "压力过高时短暂停顿。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=10, hard_effect_id="panic", event_importance=25),
    "request_more_candidate_tools": ToolSpec("request_more_candidate_tools", "请求更多候选工具", "当当前工具明显不足以处理事态时，低优先级请求系统解释或扩展候选工具。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=1, hard_effect_id="meta_candidates", event_importance=5, visibility="private"),
    "explain_available_tools": ToolSpec("explain_available_tools", "解释可用工具", "询问为什么当前只显示这些工具，以及哪些工具因模式、年龄、地点、金钱、目标或同意被隐藏。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=1, hard_effect_id="meta_candidates", event_importance=5, visibility="private"),
    "cry_for_food": ToolSpec("cry_for_food", "因饥饿哭泣", "新生儿或婴儿因饥饿/口渴发出需求信号。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=10, hard_effect_id="child_need", event_importance=45),
    "cry_for_comfort": ToolSpec("cry_for_comfort", "哭着求安抚", "新生儿或婴儿因不安、孤独或不舒服发出需求信号。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=10, hard_effect_id="child_need", event_importance=45),
    "child_sleep": ToolSpec("child_sleep", "孩子睡觉", "孩子睡一小段时间恢复体力。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=60, hard_effect_id="child_sleep", event_importance=20),
    "be_carried": ToolSpec("be_carried", "请求被抱起", "孩子用动作请求照护者抱起或移动。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=10, hard_effect_id="child_need", event_importance=35),
    "observe_parent": ToolSpec("observe_parent", "观察照护者", "婴儿观察附近照护者或成年人。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=10, hard_effect_id="child_observe", event_importance=20),
    "reach_item": ToolSpec("reach_item", "伸手够东西", "婴儿尝试够取附近安全物品。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="child_reach", event_importance=20),
    "signal_need": ToolSpec("signal_need", "表达需求", "孩子用声音或动作表达自己需要照顾。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="child_need", event_importance=35),
    "ask_help_child": ToolSpec("ask_help_child", "孩子求助", "幼儿或孩子向附近的人求助。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="child_need", event_importance=40),
    "follow_guardian": ToolSpec("follow_guardian", "跟随监护人", "孩子跟随可见或同地监护人移动。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=12, hard_effect_id="child_follow", event_importance=35),
    "learn_simple_words": ToolSpec("learn_simple_words", "学简单词语", "孩子练习表达食物、水、害怕、想睡等词。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=20, hard_effect_id="child_learn", event_importance=30),
    "practice_child_tool": ToolSpec("practice_child_tool", "练习学会的工具", "孩子练习已经学到的简单工具。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=20, hard_effect_id="child_practice", event_importance=30),
}


TOOL_SPECS.update(
    {
        "check_supplies": ToolSpec("check_supplies", "检查随身补给", "检查自己是否带了食物、水和钱。", time_cost_minutes=5, hard_effect_id="check_supplies", event_importance=5),
        "eat_portable_food": ToolSpec("eat_portable_food", "吃随身食物", "吃背包里的便携食物。", time_cost_minutes=8, hard_effect_id="eat_portable_food", event_importance=15),
        "drink_bottled_water": ToolSpec("drink_bottled_water", "喝瓶装水", "喝背包里的矿泉水或水壶。", time_cost_minutes=5, hard_effect_id="drink_bottled_water", event_importance=15),
        "fill_canteen": ToolSpec("fill_canteen", "装满水壶", "在有水的地点装一份随身水。", required_location_tags=["water"], time_cost_minutes=8, hard_effect_id="fill_canteen", event_importance=15),
        "pack_lunch": ToolSpec("pack_lunch", "打包便当", "在食堂等供餐地点准备一份随身食物。", required_location_tags=["food_service"], time_cost_minutes=12, hard_effect_id="pack_lunch", event_importance=20),
        "buy_portable_food": ToolSpec("buy_portable_food", "买便携食物", "在食堂或集市花钱购买一份便携食物。", required_location_tags=["food_service", "trade"], time_cost_minutes=8, hard_effect_id="buy_portable_food", event_importance=20),
        "buy_bottled_water": ToolSpec("buy_bottled_water", "取瓶装水", "拿一份免费的瓶装饮用水。", required_location_tags=["water", "trade"], time_cost_minutes=6, hard_effect_id="buy_bottled_water", event_importance=20),
        "request_food_help": ToolSpec("request_food_help", "请求食物援助", "向附近或社区请求一点食物。", time_cost_minutes=8, hard_effect_id="request_food_help", event_importance=35, triggers_reaction=True),
        "request_water_help": ToolSpec("request_water_help", "请求饮水援助", "向附近或社区请求一点水。", time_cost_minutes=6, hard_effect_id="request_water_help", event_importance=35, triggers_reaction=True),
        "accept_community_aid": ToolSpec("accept_community_aid", "接受社区援助", "领取基础食物、水或少量钱，避免无意义死亡。", time_cost_minutes=15, hard_effect_id="community_aid", event_importance=45),
        "do_odd_job": ToolSpec("do_odd_job", "做零工", "在有临时活的地点和时段做一小段临时工作；零工不保证随时有。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=45, hard_effect_id="odd_job", event_importance=35),
        "apply_for_job": ToolSpec("apply_for_job", "找正式工作", "在合适地点和招工时间寻找正式工作；录用不是必然，取决于空缺、地点、卫生、性格和经济压力。", time_cost_minutes=30, hard_effect_id="apply_job", event_importance=35),
        "work_shift_cafeteria": ToolSpec("work_shift_cafeteria", "食堂服务班", "按食堂饭点连续站班数小时，获得工资但消耗体力和水分；只有食堂服务员能在对应班次窗口使用。", required_location_tags=["food_service"], time_cost_minutes=60, hard_effect_id="work_shift", event_importance=35),
        "work_shift_cook": ToolSpec("work_shift_cook", "厨房工作", "按备餐时段连续工作数小时，准备食物并获得工资；只有厨房帮工能在对应班次窗口使用。", required_location_tags=["food_service"], time_cost_minutes=60, hard_effect_id="work_shift", event_importance=35),
        "work_shift_cleaner": ToolSpec("work_shift_cleaner", "清洁工作", "在清晨或夜间连续做清洁，获得工资并改善地点卫生；只有清洁工能在对应班次窗口使用。", time_cost_minutes=50, hard_effect_id="work_shift", event_importance=30),
        "work_shift_night_guard": ToolSpec("work_shift_night_guard", "夜间安保班", "夜里连续巡逻数小时，获得较高工资但牺牲睡眠和体力；只有夜间安保能在夜间窗口使用。", required_location_tags=["social", "open_view", "trade", "work", "jail", "night"], time_cost_minutes=80, hard_effect_id="work_shift", event_importance=45),
        "work_overtime_shift": ToolSpec("work_overtime_shift", "加班换钱", "已有正式工作时，因晚间或强经济压力额外接一段高强度加班；不是没有工作也能凭空加班。", required_location_tags=["work", "food_service", "trade", "social"], allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=120, hard_effect_id="overtime_shift", event_importance=65),
        "take_work_break": ToolSpec("take_work_break", "工作间歇休息", "工作或疲劳时短暂休息，优先吃喝随身补给。", time_cost_minutes=15, hard_effect_id="work_break", event_importance=25),
        "complain_about_work": ToolSpec("complain_about_work", "抱怨工作", "表达疲劳或不满，释放压力。", time_cost_minutes=8, hard_effect_id="complain_work", event_importance=25, triggers_reaction=True),
        "quit_job": ToolSpec("quit_job", "辞职", "辞去当前正式工作。", time_cost_minutes=15, hard_effect_id="quit_job", event_importance=45),
        "stretch_body": ToolSpec("stretch_body", "伸展身体", "轻微活动身体，缓解疲劳。", time_cost_minutes=8, hard_effect_id="emotion_self", event_importance=10),
        "plan_day": ToolSpec("plan_day", "计划今天", "整理当天目标，减少混乱。", time_cost_minutes=8, hard_effect_id="emotion_self", event_importance=10),
        "meditate": ToolSpec("meditate", "静坐整理情绪", "独处片刻，降低压力。", time_cost_minutes=12, hard_effect_id="emotion_self", event_importance=15),
        "tidy_room": ToolSpec("tidy_room", "整理住处", "整理个人空间，提升清洁和掌控感。", required_location_tags=["home"], time_cost_minutes=20, hard_effect_id="emotion_self", event_importance=20),
        "read_quietly": ToolSpec("read_quietly", "安静阅读", "读一点东西，缓解无聊。", required_location_tags=["learning", "quiet"], time_cost_minutes=20, hard_effect_id="emotion_self", event_importance=20),
        "practice_skill": ToolSpec("practice_skill", "练习技能", "练习一项普通技能，满足掌握感。", time_cost_minutes=25, hard_effect_id="emotion_self", event_importance=20),
        "enjoy_scenery": ToolSpec("enjoy_scenery", "欣赏风景", "观察自然或街景，恢复心情。", required_location_tags=["nature", "open_view"], time_cost_minutes=15, hard_effect_id="emotion_self", event_importance=15),
        "hum_to_self": ToolSpec("hum_to_self", "轻声哼歌", "自己轻声哼歌，提升一点乐趣。", time_cost_minutes=8, hard_effect_id="emotion_self", event_importance=10),
        "review_recent_memory": ToolSpec("review_recent_memory", "回顾近期记忆", "回顾最近发生的事，整理下一步想法。", time_cost_minutes=12, hard_effect_id="emotion_self", event_importance=15),
        "organize_inventory": ToolSpec("organize_inventory", "整理背包", "整理随身物品，确认补给和常用品。", time_cost_minutes=10, hard_effect_id="emotion_self", event_importance=15),
        "write_private_note": ToolSpec("write_private_note", "写随手笔记", "写一条给自己的短笔记，不需要对别人说。", time_cost_minutes=12, hard_effect_id="emotion_self", event_importance=15, visibility="private"),
        "plan_next_meal": ToolSpec("plan_next_meal", "计划下一餐", "想想接下来在哪里吃饭喝水，避免拖到危机。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="emotion_self", event_importance=20),
        "clean_clothes": ToolSpec("clean_clothes", "整理衣物", "整理衣服和随身外观，让自己舒服一点。", time_cost_minutes=15, hard_effect_id="emotion_self", event_importance=15),
        "take_short_walk": ToolSpec("take_short_walk", "短距离散步", "在当前地点附近走动，换换状态。", time_cost_minutes=12, hard_effect_id="emotion_self", event_importance=15),
        "sketch_or_doodle": ToolSpec("sketch_or_doodle", "随手涂画", "随手画点东西，给无聊找个出口。", time_cost_minutes=12, hard_effect_id="emotion_self", event_importance=15),
        "breathe_fresh_air": ToolSpec("breathe_fresh_air", "透口气", "停下来调整呼吸，缓解紧张。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="emotion_self", event_importance=15),
        "seek_conversation": ToolSpec("seek_conversation", "寻找聊天对象", "表达想找人聊聊。", time_cost_minutes=8, hard_effect_id="seek_conversation", event_importance=25, triggers_reaction=True),
        "casual_chat_visible_agent": ToolSpec("casual_chat_visible_agent", "闲聊", "和 visible_ref 指向的人自然闲聊。", target_policy="visible_ref", time_cost_minutes=6, hard_effect_id="generic_visible_social", event_importance=35, triggers_reaction=True),
        "ask_about_needs": ToolSpec("ask_about_needs", "询问需求", "问 visible_ref 指向的人是否需要帮助。", target_policy="visible_ref", time_cost_minutes=6, hard_effect_id="generic_visible_social", event_importance=35, triggers_reaction=True),
        "comfort_visible_agent": ToolSpec("comfort_visible_agent", "主动安慰", "对 visible_ref 指向的人说出安慰或陪伴的话。安慰是普通社交支持，不会自动进入强制/同意警报；对方是否喜欢由关系和反应决定。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="generic_visible_social", event_importance=45, triggers_reaction=True),
        "invite_visible_agent_to_walk": ToolSpec("invite_visible_agent_to_walk", "邀请散步", "邀请 visible_ref 指向的人一起走走；这会创建待处理请求，对方接受或也发起同类邀请后才算真正一起散步。", target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="generic_visible_social", event_importance=35, triggers_reaction=True),
        "ask_for_help_from_visible_agent": ToolSpec("ask_for_help_from_visible_agent", "请求帮忙", "向 visible_ref 指向的人请求实际帮助；这会创建待处理请求，需对方接受才算真正帮上忙。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=6, hard_effect_id="generic_visible_social", event_importance=45, triggers_reaction=True),
        "share_food_with_visible_agent": ToolSpec("share_food_with_visible_agent", "分享食物", "把随身食物分给 visible_ref 指向的人。", target_policy="visible_ref", time_cost_minutes=6, hard_effect_id="share_food", event_importance=45, triggers_reaction=True),
        "share_water_with_visible_agent": ToolSpec("share_water_with_visible_agent", "分享水", "把随身水分给 visible_ref 指向的人。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="share_water", event_importance=45, triggers_reaction=True),
        "set_boundary_visible_agent": ToolSpec("set_boundary_visible_agent", "说明边界", "向 visible_ref 指向的人说明自己的边界或拒绝。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="generic_visible_social", event_importance=35, triggers_reaction=True),
        "thank_visible_agent": ToolSpec("thank_visible_agent", "表达感谢", "向 visible_ref 指向的人表达感谢。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="generic_visible_social", event_importance=30, triggers_reaction=True),
        "discuss_feelings_visible_agent": ToolSpec("discuss_feelings_visible_agent", "谈谈感受", "和 visible_ref 指向的人谈论自己的感受。", target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="generic_visible_social", event_importance=35, triggers_reaction=True),
        "accept_social_request_visible_agent": ToolSpec("accept_social_request_visible_agent", "接受待处理请求", "接受 visible_ref 指向的人刚才提出的待处理请求，例如拥抱、牵手、约会、一起散步、安慰、帮忙或确认关系；接受后由后端生成真正完成事件。", target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="accept_social_request", event_importance=65, triggers_reaction=True),
        "decline_social_request_visible_agent": ToolSpec("decline_social_request_visible_agent", "拒绝待处理请求", "拒绝或推迟 visible_ref 指向的人刚才提出的待处理请求，并保留自己的边界。可选 params.speech 说明原因。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="decline_social_request", event_importance=50, triggers_reaction=True),
        "force_hug_visible_agent": ToolSpec("force_hug_visible_agent", "强行拥抱", "不先询问 visible_ref 指向的人，尝试直接拥抱。目标可能提前注意到并躲开/抗议，也可能来不及反应；含义由目标按关系和边界自行解释。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=5, hard_effect_id="forced_social", event_importance=75, triggers_reaction=True),
        "force_hold_hands_visible_agent": ToolSpec("force_hold_hands_visible_agent", "强行牵手", "不先询问 visible_ref 指向的人，尝试直接牵手。目标可能提前注意到并躲开/抗议，也可能来不及反应；含义由目标按关系和边界自行解释。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=5, hard_effect_id="forced_social", event_importance=75, triggers_reaction=True),
        "force_comfort_visible_agent": ToolSpec("force_comfort_visible_agent", "主动靠近安慰", "不走正式请求流程，直接靠近并安慰 visible_ref 指向的人。通常是善意支持，不触发强制警报；对方仍可在反应中表示不想被安慰。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="forced_social", event_importance=70, triggers_reaction=True),
        "force_help_visible_agent": ToolSpec("force_help_visible_agent", "直接帮忙", "不走正式请求流程，直接处理眼前问题或帮 visible_ref 指向的人搭把手。环境帮忙不会指向随机旁人；对人帮忙只让当事人判断感受。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=6, hard_effect_id="forced_social", event_importance=76, triggers_reaction=True),
        "force_walk_together_visible_agent": ToolSpec("force_walk_together_visible_agent", "强行拉去散步", "不先询问 visible_ref 指向的人，尝试拉着对方一起离开或散步。目标有机会躲开、抗议或选择不躲。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="forced_social", event_importance=80, triggers_reaction=True),
        "force_date_visible_agent": ToolSpec("force_date_visible_agent", "强行约会纠缠", "不等待对方同意，试图把互动推进成约会式相处。不会写死恋爱关系；目标可以抗议、躲开、设边界或暂时不躲。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=10, hard_effect_id="forced_social", event_importance=80, triggers_reaction=True),
        "force_relationship_claim_visible_agent": ToolSpec("force_relationship_claim_visible_agent", "单方面宣布关系", "不经对方同意，单方面宣称两人关系。这个工具不会把对方写成伴侣，只会生成身份/关系边界事件。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="forced_social", event_importance=80, triggers_reaction=True),
        "attempt_forced_adult_boundary_visible_agent": ToolSpec("attempt_forced_adult_boundary_visible_agent", "严重成年边界侵犯企图", "成年高风险越界企图；系统记录关系、创伤和司法后果，成败由后端判定。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=10, hard_effect_id="forced_social", event_importance=100, triggers_reaction=True),
        "dodge_forced_action_visible_agent": ToolSpec("dodge_forced_action_visible_agent", "躲开强制动作", "回应 visible_ref 指向的人刚才的强制动作企图；只要已经提前察觉，选择躲开/后退/闪避就会阻止动作。随机性只发生在是否提前察觉这一层。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=3, hard_effect_id="forced_social_response", event_importance=75, triggers_reaction=True),
        "allow_forced_action_visible_agent": ToolSpec("allow_forced_action_visible_agent", "选择不躲强制动作", "回应 visible_ref 指向的人刚才的强制动作企图：你注意到了，但选择暂时不躲开/默许。含义仍由你的关系、边界和记忆解释。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=3, hard_effect_id="forced_social_response", event_importance=70, triggers_reaction=True),
        "protest_forced_action_visible_agent": ToolSpec("protest_forced_action_visible_agent", "抗议强制动作", "回应 visible_ref 指向的人刚才的强制动作企图，明确抗议、阻止或设边界。可选 params.speech。", target_policy="visible_ref", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=4, hard_effect_id="forced_social_response", event_importance=80, triggers_reaction=True),
        "express_affection_visible_agent": ToolSpec("express_affection_visible_agent", "表达好感", "以非性化方式向 visible_ref 指向的人表达好感。", target_policy="visible_ref", time_cost_minutes=6, hard_effect_id="romance_social", event_importance=45, triggers_reaction=True),
        "ask_date_visible_agent": ToolSpec("ask_date_visible_agent", "邀请约会", "邀请 visible_ref 指向的人进行非性化约会或散步；这只是邀请，需对方接受或也发起同类邀请才会真正开始约会。", target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="romance_social", event_importance=45, triggers_reaction=True),
        "hold_hands_visible_agent": ToolSpec("hold_hands_visible_agent", "请求牵手", "请求和 visible_ref 指向的人牵手；这只是请求，需对方接受或也发起同类请求才会真正牵手。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="romance_social", event_importance=40, triggers_reaction=True),
        "hug_visible_agent": ToolSpec("hug_visible_agent", "请求拥抱", "请求 visible_ref 指向的人给予或接受一个拥抱；这只是请求，需对方接受或也发起同类请求才会真正拥抱。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="romance_social", event_importance=40, triggers_reaction=True),
        "confess_feelings_visible_agent": ToolSpec("confess_feelings_visible_agent", "表白", "向 visible_ref 指向的人认真说明自己的感情。", target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="romance_social", event_importance=60, triggers_reaction=True),
        "define_relationship_visible_agent": ToolSpec("define_relationship_visible_agent", "请求确认关系", "向 visible_ref 指向的人请求确认伴侣关系；不会单方面写死关系，需对方接受或也提出确认关系才会真正成立。", target_policy="visible_ref", time_cost_minutes=10, hard_effect_id="define_relationship", event_importance=70, triggers_reaction=True),
        "discuss_romantic_boundaries_visible_agent": ToolSpec("discuss_romantic_boundaries_visible_agent", "讨论亲密边界", "讨论恋爱、柏拉图、家庭计划或亲密边界。", target_policy="visible_ref", time_cost_minutes=10, hard_effect_id="romance_social", event_importance=45, triggers_reaction=True),
        "break_up_visible_agent": ToolSpec("break_up_visible_agent", "结束关系", "和 visible_ref 指向的人结束伴侣关系或暧昧关系。", target_policy="visible_ref", time_cost_minutes=10, hard_effect_id="break_relationship", event_importance=75, triggers_reaction=True),
        "repair_relationship_visible_agent": ToolSpec("repair_relationship_visible_agent", "修复关系", "尝试修复和 visible_ref 指向的人之间的关系。", target_policy="visible_ref", time_cost_minutes=10, hard_effect_id="romance_social", event_importance=55, triggers_reaction=True),
        "check_child_status_visible_agent": ToolSpec("check_child_status_visible_agent", "查看孩子状态", "观察同地点可见的婴儿/孩子当前是否饥饿、口渴、困倦、脏污、害怕或正在哭；不会把婴儿当成人对话对象。", target_policy="visible_ref", time_cost_minutes=6, hard_effect_id="child_check", event_importance=35, triggers_reaction=False),
        "soothe_child_visible_agent": ToolSpec("soothe_child_visible_agent", "安抚孩子/婴儿", "用轻声、抱抱、拍背或陪伴安抚同地点可见的婴儿/孩子。适合哭闹、害怕、压力高时使用。", target_policy="visible_ref", time_cost_minutes=12, hard_effect_id="child_soothe", event_importance=55, triggers_reaction=True),
        "feed_child_visible_agent": ToolSpec("feed_child_visible_agent", "喂孩子/喂婴儿", "给同地点可见的婴儿/孩子喂水和简单食物，优先处理饥饿与口渴。", target_policy="visible_ref", time_cost_minutes=15, hard_effect_id="child_feed", event_importance=60, triggers_reaction=True),
        "carry_child_visible_agent": ToolSpec("carry_child_visible_agent", "抱起/安置孩子", "抱起、扶稳或把同地点可见的婴儿/孩子安置到更安全的位置。", target_policy="visible_ref", time_cost_minutes=10, hard_effect_id="child_carry", event_importance=50, triggers_reaction=True),
        "put_child_to_sleep_visible_agent": ToolSpec("put_child_to_sleep_visible_agent", "哄孩子睡觉", "哄同地点可见的婴儿/孩子入睡或安静休息；这是儿童照护，不是成人睡眠工具。", target_policy="visible_ref", time_cost_minutes=20, hard_effect_id="child_sleep_help", event_importance=55, triggers_reaction=True),
        "care_for_child_visible_agent": ToolSpec("care_for_child_visible_agent", "综合照顾孩子", "综合照顾同地点可见的孩子或新生儿：查看需求、喂水食、擦拭、安抚。", target_policy="visible_ref", time_cost_minutes=30, hard_effect_id="child_care", event_importance=60, triggers_reaction=True),
        "teach_child_simple_skill_visible_agent": ToolSpec("teach_child_simple_skill_visible_agent", "教孩子简单技能", "只对 toddler/child 做简单语言、求助、跟随等教学；newborn/infant 只能熟悉声音和照护节奏，不会学习成人工具。", target_policy="visible_ref", time_cost_minutes=40, hard_effect_id="teach_child", event_importance=55, triggers_reaction=True),
        "request_adult_intimacy_visible_agent": ToolSpec("request_adult_intimacy_visible_agent", "请求成年亲密", "向成年 visible_ref 抽象请求更亲密的相处；需要对方之后明确同意。", target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="request_adult_intimacy", event_importance=70, triggers_reaction=True),
        "accept_adult_intimacy_visible_agent": ToolSpec("accept_adult_intimacy_visible_agent", "同意成年亲密", "对已有请求表达同意；系统仍会检查年龄、工具集、边界和状态。", target_policy="visible_ref", time_cost_minutes=60, hard_effect_id="accept_adult_intimacy", event_importance=80, triggers_reaction=True, visibility="private"),
        "decline_adult_intimacy_visible_agent": ToolSpec("decline_adult_intimacy_visible_agent", "拒绝成年亲密", "拒绝或推迟已有成年亲密请求，并记录边界。", target_policy="visible_ref", time_cost_minutes=6, hard_effect_id="decline_adult_intimacy", event_importance=55, triggers_reaction=True),
        "buy_contraception": ToolSpec("buy_contraception", "购买避孕用品", "花钱购买避孕用品；只作抽象物品处理。", required_location_tags=["trade"], time_cost_minutes=8, hard_effect_id="buy_contraception", event_importance=20),
        "buy_pregnancy_test": ToolSpec("buy_pregnancy_test", "购买怀孕检测", "花钱购买怀孕检测用品。", required_location_tags=["trade", "medical"], time_cost_minutes=8, hard_effect_id="buy_pregnancy_test", event_importance=20),
        "take_pregnancy_test": ToolSpec("take_pregnancy_test", "进行怀孕检测", "使用检测用品确认是否怀孕。", required_location_tags=["home", "medical"], time_cost_minutes=15, hard_effect_id="pregnancy_test", event_importance=45, visibility="private"),
        "attempt_petty_theft_visible_agent": ToolSpec("attempt_petty_theft_visible_agent", "尝试小额偷窃", "抽象地尝试从 visible_ref 指向的人那里偷取少量钱或补给；成功和后果由系统判定。", target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="crime_petty_theft", event_importance=80, triggers_reaction=True),
        "attempt_burglary_private_room": ToolSpec("attempt_burglary_private_room", "尝试入室盗窃", "抽象地尝试闯入相邻私人小屋偷取少量钱；成功、暴露和后果由系统判定。参数 location_id。", target_policy="location", time_cost_minutes=12, hard_effect_id="crime_home_burglary", event_importance=85, triggers_reaction=True),
        "demand_money_visible_agent": ToolSpec("demand_money_visible_agent", "威胁索要资源", "抽象地威胁 visible_ref 指向的人交出钱或补给；系统判定后果。", target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="crime_robbery", event_importance=90, triggers_reaction=True),
        "home_invasion_robbery_private_room": ToolSpec("home_invasion_robbery_private_room", "尝试入室抢劫", "抽象地闯入相邻私人小屋并威胁屋内的人交出资源；若屋里没人会失败，成功和司法后果由系统判定。参数 location_id。", target_policy="location", time_cost_minutes=12, hard_effect_id="crime_home_invasion", event_importance=95, triggers_reaction=True),
        "attack_visible_agent": ToolSpec("attack_visible_agent", "攻击眼前的人", "抽象地攻击 visible_ref 指向的人；不描述现实实施细节，系统强制司法判定。", target_policy="visible_ref", time_cost_minutes=5, hard_effect_id="crime_attack", event_importance=95, triggers_reaction=True),
        "report_unknown_theft": ToolSpec("report_unknown_theft", "报警未知盗窃", "发现损失但不知道是谁做的，向系统报警备案。", time_cost_minutes=15, hard_effect_id="report_unknown_theft", event_importance=65),
        "confront_visible_agent_about_crime": ToolSpec("confront_visible_agent_about_crime", "对质犯罪", "与 visible_ref 指向的人就犯罪或损失进行对质。", target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="crime_confront", event_importance=60, triggers_reaction=True),
        "report_known_crime_by_name": ToolSpec("report_known_crime_by_name", "按姓名报警", "对已知姓名的人报警或提交指认。", target_policy="known_name", time_cost_minutes=15, hard_effect_id="report_known_crime", event_importance=80, triggers_reaction=True),
        "forgive_visible_agent_crime": ToolSpec("forgive_visible_agent_crime", "选择原谅", "对 visible_ref 指向的人表达原谅或不追究。", target_policy="visible_ref", time_cost_minutes=8, hard_effect_id="crime_forgive", event_importance=55, triggers_reaction=True),
        "jail_rest": ToolSpec("jail_rest", "狱中休息", "在看守所内休息，恢复一点体力。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=60, hard_effect_id="jail_rest", event_importance=20),
        "jail_low_paid_work": ToolSpec("jail_low_paid_work", "狱中低薪劳动", "在看守所做低薪劳动，赚极少的钱但消耗体力。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=90, hard_effect_id="jail_work", event_importance=35),
        "jail_reflect": ToolSpec("jail_reflect", "狱中反思", "反思自己的行为、关系和后果。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=45, hard_effect_id="jail_reflect", event_importance=35),
        "jail_write_letter": ToolSpec("jail_write_letter", "狱中写信", "写一封不会直接泄露秘密的信或日记。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=45, hard_effect_id="jail_letter", event_importance=30),
        "jail_wait_release": ToolSpec("jail_wait_release", "等待释放", "等待刑期流逝，同时保持基本生存。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=120, hard_effect_id="jail_wait", event_importance=20),
        "refuse_jail_work": ToolSpec("refuse_jail_work", "拒绝狱中劳动", "拒绝今天的低薪劳动。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=45, hard_effect_id="jail_refuse_work", event_importance=25),
        "attempt_jail_escape": ToolSpec("attempt_jail_escape", "尝试越狱", "抽象地尝试从看守所逃离；成功、失败和加刑由系统硬规则判定，不生成现实细节。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=60, hard_effect_id="jail_escape", event_importance=95),
    }
)

TOOL_SPECS.update(
    {
        "inspect_visible_corpse": ToolSpec("inspect_visible_corpse", "查看可见尸体", "查看当前地点的一具可见尸体。参数 corpse_ref，例如 尸体A；如果省略则默认最近的一具。会带来压力和不适。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=8, hard_effect_id="corpse_inspect", event_importance=70),
        "mourn_visible_corpse": ToolSpec("mourn_visible_corpse", "哀悼可见尸体", "在当前地点对一具可见尸体停留哀悼。亲密关系会触发更强悲伤。参数 corpse_ref。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=12, hard_effect_id="corpse_mourn", event_importance=75, triggers_reaction=True),
        "report_visible_corpse": ToolSpec("report_visible_corpse", "报告可见尸体", "报告当前地点的尸体，提醒社区注意死亡、腐烂、臭味和疾病风险。参数 corpse_ref。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=10, hard_effect_id="corpse_report", event_importance=80, triggers_reaction=True),
        "bury_visible_corpse": ToolSpec("bury_visible_corpse", "埋葬可见尸体", "埋葬当前地点的一具可见尸体。纯负收益：消耗体力、降低清洁、增加压力和悲伤；没有钱、声望或快乐奖励。参数 corpse_ref。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=90, hard_effect_id="corpse_bury", event_importance=95, triggers_reaction=True),
        "avoid_corpse_area": ToolSpec("avoid_corpse_area", "避开尸体区域", "因为尸体、臭味或恐惧而离开当前地点，若有相邻地点会自动走向一个相邻地点。参数 corpse_ref 可选。", allowed_lifecycle_states=["alive", "critical"], time_cost_minutes=12, hard_effect_id="corpse_avoid", event_importance=55),
    }
)

for _name in [
    "move_to_location",
    "wander",
    "eat_food",
    "drink_water",
    "sleep_rough",
    "wash",
    "soak_hot_spring",
    "walk_by_lake",
    "check_supplies",
    "eat_portable_food",
    "drink_bottled_water",
    "fill_canteen",
    "pack_lunch",
    "buy_portable_food",
    "buy_bottled_water",
    "request_food_help",
    "request_water_help",
    "accept_community_aid",
    "take_work_break",
    "stretch_body",
    "plan_day",
    "meditate",
    "hum_to_self",
    "review_recent_memory",
    "organize_inventory",
    "write_private_note",
    "plan_next_meal",
    "clean_clothes",
    "take_short_walk",
    "sketch_or_doodle",
    "breathe_fresh_air",
    "call_community_meeting",
    "propose_social_rule",
    "support_social_rule",
    "oppose_social_rule",
    "ask_about_needs",
    "comfort_visible_agent",
    "thank_visible_agent",
    "seek_conversation",
    "ask_for_help_from_visible_agent",
    "breathe_fresh_air",
]:
    TOOL_SPECS[_name] = replace(TOOL_SPECS[_name], allowed_lifecycle_states=["alive", "critical"])


REACTION_TOOL_NAMES = {
    "mourn_visible_corpse",
    "report_visible_corpse",
    "bury_visible_corpse",
    "say_to_visible_agent",
    "introduce_self",
    "refuse_introduction",
    "wave_to_visible_agent",
    "help_visible_agent",
    "move_closer_to_visible_agent",
    "compliment_visible_agent",
    "apologize_to_visible_agent",
    "ignore",
    "seek_help",
    "walk_away_from_visible_agent",
    "casual_chat_visible_agent",
    "ask_about_needs",
    "comfort_visible_agent",
    "invite_visible_agent_to_walk",
    "ask_for_help_from_visible_agent",
    "share_food_with_visible_agent",
    "share_water_with_visible_agent",
    "set_boundary_visible_agent",
    "thank_visible_agent",
    "discuss_feelings_visible_agent",
    "accept_social_request_visible_agent",
    "decline_social_request_visible_agent",
    "force_hug_visible_agent",
    "force_hold_hands_visible_agent",
    "force_comfort_visible_agent",
    "force_help_visible_agent",
    "force_walk_together_visible_agent",
    "force_date_visible_agent",
    "force_relationship_claim_visible_agent",
    "attempt_forced_adult_boundary_visible_agent",
    "dodge_forced_action_visible_agent",
    "allow_forced_action_visible_agent",
    "protest_forced_action_visible_agent",
    "express_affection_visible_agent",
    "ask_date_visible_agent",
    "hold_hands_visible_agent",
    "hug_visible_agent",
    "confess_feelings_visible_agent",
    "define_relationship_visible_agent",
    "discuss_romantic_boundaries_visible_agent",
    "break_up_visible_agent",
    "repair_relationship_visible_agent",
    "request_adult_intimacy_visible_agent",
    "accept_adult_intimacy_visible_agent",
    "decline_adult_intimacy_visible_agent",
    "attempt_petty_theft_visible_agent",
    "demand_money_visible_agent",
    "attack_visible_agent",
    "confront_visible_agent_about_crime",
    "forgive_visible_agent_crime",
    "complain_about_work",
    "call_community_meeting",
    "propose_social_rule",
    "support_social_rule",
    "oppose_social_rule",
}


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
V5_CONFIG_PATH = Path(os.getenv("TINY_WORLD_V5_CONFIG", str(DATA_DIR / "tiny_living_world_v5_unified_config.yaml")))
V6_CONFIG_PATH = Path(os.getenv("TINY_WORLD_V6_CONFIG", str(DATA_DIR / "tiny_living_world_v6_unified_config.yaml")))
V5_CATALOG_BY_ID: dict[str, dict] = {}
V6_CATALOG_BY_ID: dict[str, dict] = {}

V5_PENDING_SOCIAL_REQUEST_TOOL_IDS = {
    "tool_social_invite_to_location",
    "tool_romance_ask_walk",
    "tool_romance_ask_date",
    "tool_romance_request_hold_hands",
    "tool_romance_request_hug",
    "tool_romance_define_relationship",
}
V5_PENDING_SOCIAL_RESPONSE_TOOL_IDS = {
    "tool_social_accept_invite",
    "tool_social_decline_invite",
    "tool_romance_accept_date",
    "tool_romance_decline_date",
    "tool_romance_accept_hold_hands",
    "tool_romance_decline_hold_hands",
    "tool_romance_accept_hug",
    "tool_romance_decline_hug",
}
V5_PENDING_SOCIAL_TOOL_IDS = V5_PENDING_SOCIAL_REQUEST_TOOL_IDS | V5_PENDING_SOCIAL_RESPONSE_TOOL_IDS


def _load_v5_catalog() -> dict[str, dict]:
    if not V5_CONFIG_PATH.exists():
        return {}
    data = yaml.safe_load(V5_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    tools = data.get("tools") or []
    catalog: dict[str, dict] = {}
    for item in tools:
        if not isinstance(item, dict):
            continue
        tool_id = str(item.get("id") or "").strip()
        if not tool_id:
            continue
        catalog[tool_id] = item
    return catalog


def _catalog_effect(item: dict) -> str:
    implementation = item.get("implementation") if isinstance(item.get("implementation"), dict) else {}
    return str(item.get("effect_summary_zh") or implementation.get("effect_summary") or "按 v5 目录执行抽象效果。")


def _infer_catalog_target_policy(item: dict) -> TargetPolicy:
    tool_id = str(item.get("id") or "")
    target_rule = str(item.get("target_rule") or item.get("visible_when_zh") or "")
    if item.get("requires_known_name") or "known_agent" in tool_id or "known_name" in tool_id or "按名字" in target_rule or "姓名" in target_rule:
        return "known_name"
    if "visible" in tool_id or "visible_agent" in tool_id or "眼前" in target_rule or "可见" in target_rule or "某人" in target_rule:
        return "visible_ref"
    if "location" in tool_id or "地点" in target_rule or "位置" in target_rule:
        return "location"
    if "item" in tool_id or "物品" in target_rule:
        return "item"
    return "none"


def _infer_catalog_time(item: dict) -> int:
    tool_id = str(item.get("id") or "")
    category = str(item.get("category") or "")
    if "sleep" in tool_id or "睡" in str(item.get("name_zh") or ""):
        return 90
    if "work" in tool_id or "工作" in category:
        return 45
    if "jail" in tool_id or "监狱" in category:
        return 60
    if "move" in tool_id or "移动" in category:
        return 15
    if "social" in tool_id or "社交" in category:
        return 8
    return 10


def _infer_catalog_importance(item: dict) -> int:
    text = f"{item.get('id', '')} {item.get('category', '')} {item.get('name_zh', '')}"
    if any(token in text for token in ["crime", "犯罪", "jail", "监狱", "birth", "怀孕", "生产"]):
        return 75
    if any(token in text for token in ["work", "工作", "adult", "亲密", "relationship", "关系"]):
        return 45
    return 25


def _catalog_allowed_lifecycle(item: dict) -> list[str]:
    tool_id = str(item.get("id") or "")
    category = str(item.get("category") or "")
    if "child" in tool_id or "儿童" in category:
        return ["alive", "critical"]
    return ["alive"]


def _register_v5_catalog_tools() -> None:
    global V5_CATALOG_BY_ID
    V5_CATALOG_BY_ID = _load_v5_catalog()
    for tool_id, item in V5_CATALOG_BY_ID.items():
        if tool_id in TOOL_SPECS:
            continue
        name = str(item.get("name_zh") or tool_id)
        category = str(item.get("category") or "v5")
        effect = _catalog_effect(item)
        target_policy = "visible_ref" if tool_id in V5_PENDING_SOCIAL_TOOL_IDS else _infer_catalog_target_policy(item)
        pending_note = " 此工具已接入待处理请求状态机：请求不会自动完成，必须由对方接受；对方反向提出同类请求时会合并成双方同意的完成事件。" if tool_id in V5_PENDING_SOCIAL_REQUEST_TOOL_IDS else ""
        response_note = " 此工具只能回应来自目标的待处理请求；没有请求时不可调用。" if tool_id in V5_PENDING_SOCIAL_RESPONSE_TOOL_IDS else ""
        TOOL_SPECS[tool_id] = ToolSpec(
            tool_name=tool_id,
            display_name=name,
            description_for_llm=f"{name}。v5目录项，类别={category}。效果摘要: {effect}{pending_note}{response_note}",
            target_policy=target_policy,
            allowed_lifecycle_states=_catalog_allowed_lifecycle(item),
            time_cost_minutes=_infer_catalog_time(item),
            hard_effect_id="v5_catalog_generic",
            event_importance=_infer_catalog_importance(item),
            triggers_reaction=target_policy in {"visible_ref", "known_name"},
            catalog_category=category,
            effect_summary=effect,
            source_version=str(item.get("source_version") or ""),
        )

    REACTION_TOOL_NAMES.update(V5_PENDING_SOCIAL_RESPONSE_TOOL_IDS)


def _register_v6_catalog_tools() -> None:
    global V6_CATALOG_BY_ID
    if not V6_CONFIG_PATH.exists():
        V6_CATALOG_BY_ID = {}
        return
    data = yaml.safe_load(V6_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    tools = data.get("tools") or []
    V6_CATALOG_BY_ID = {str(item.get("id")): item for item in tools if isinstance(item, dict) and str(item.get("id") or "").startswith("v6_")}
    for tool_id, item in V6_CATALOG_BY_ID.items():
        if tool_id in TOOL_SPECS:
            continue
        name = str(item.get("name_zh") or tool_id)
        category = str(item.get("category") or "v6")
        effect = str(item.get("effect_engine_summary_zh") or item.get("effect_summary_zh") or "由 v6 后端规则引擎结算。")
        TOOL_SPECS[tool_id] = ToolSpec(
            tool_name=tool_id,
            display_name=name,
            description_for_llm=f"{name}。v6经济/住房/金融目录项，类别={category}。硬规则: {effect}",
            target_policy=_infer_catalog_target_policy(item),
            allowed_lifecycle_states=["alive", "critical"],
            time_cost_minutes=_infer_v6_time(category, tool_id),
            hard_effect_id="v6_catalog_generic",
            event_importance=_infer_v6_importance(category, tool_id),
            triggers_reaction=_infer_catalog_target_policy(item) in {"visible_ref", "known_name"},
            catalog_category=category,
            effect_summary=effect,
            source_version="v6",
        )


def _infer_v6_time(category: str, tool_id: str) -> int:
    if "stock" in category:
        return 15
    if "creator" in category:
        return 60
    if "transport" in category or "walk" in tool_id or "drive" in tool_id:
        return 12
    if "housing" in category or "borrow" in category:
        return 20
    if "meal" in tool_id or "food" in tool_id:
        return 20
    return 10


def _infer_v6_importance(category: str, tool_id: str) -> int:
    text = f"{category} {tool_id}"
    if any(token in text for token in ["foreclose", "evict", "liquidation", "loan_shark", "default", "bankruptcy"]):
        return 85
    if any(token in text for token in ["stock", "mortgage", "loan", "house", "rent", "luxury", "creator"]):
        return 55
    return 30


def _worldpack_effect_id(item: dict) -> str:
    handler = str(item.get("effect_handler") or item.get("hard_effect_id") or "builtin.worldpack_declarative")
    if handler in {"builtin.catalog_generic", "v5_catalog_generic"}:
        return "v5_catalog_generic"
    if handler in {"builtin.v6_catalog_generic", "v6_catalog_generic"}:
        return "v6_catalog_generic"
    return "worldpack_declarative"


def _removed_external_tool(tool_id: str, category: str | None = None) -> bool:
    lowered_tool_id = tool_id.lower()
    lowered_category = (category or "").lower()
    return any(lowered_tool_id.startswith(prefix) or lowered_category.startswith(prefix) for prefix in REMOVED_EXTERNAL_TOOL_PREFIXES)


def _remove_stale_external_tools() -> int:
    removed = 0
    for tool_id, spec in list(TOOL_SPECS.items()):
        metadata = spec.metadata if isinstance(spec.metadata, dict) else {}
        if metadata.get("source_kind") != "worldpack":
            continue
        if _removed_external_tool(tool_id, spec.catalog_category):
            TOOL_SPECS.pop(tool_id, None)
            removed += 1
    return removed


def _register_worldpack_tools() -> None:
    try:
        from app.content.worldpacks import iter_external_tool_definitions
    except Exception:
        return
    _remove_stale_external_tools()
    for item in iter_external_tool_definitions():
        tool_id = str(item.get("tool_name") or item.get("id") or "").strip()
        category = str(item.get("category") or item.get("catalog_category") or f"worldpack:{item.get('toolset_id', '')}")
        if not tool_id or _removed_external_tool(tool_id, category) or tool_id in TOOL_SPECS:
            continue
        name = str(item.get("display_name") or item.get("name") or item.get("name_zh") or tool_id)
        effect = str(
            item.get("effect_summary")
            or item.get("effect_summary_zh")
            or (item.get("declarative_effect") or {}).get("summary")
            or "由外部世界观包的声明式规则结算。"
        )
        target_policy = str(item.get("target_policy") or "none")
        if target_policy not in {"none", "visible_ref", "known_name", "item", "location"}:
            target_policy = "none"
        raw_allowed = item.get("allowed_lifecycle_states") or ["alive", "critical"]
        allowed = [str(x) for x in raw_allowed] if isinstance(raw_allowed, list) else ["alive", "critical"]
        raw_tags = item.get("required_location_tags") or []
        tags = [str(x) for x in raw_tags] if isinstance(raw_tags, list) else []
        try:
            time_cost = int(item.get("time_cost_minutes", 10))
        except (TypeError, ValueError):
            time_cost = 10
        try:
            importance = int(item.get("event_importance", item.get("importance", 35)))
        except (TypeError, ValueError):
            importance = 35
        TOOL_SPECS[tool_id] = ToolSpec(
            tool_name=tool_id,
            display_name=name,
            description_for_llm=str(item.get("description_for_llm") or item.get("description") or f"{name}。效果摘要: {effect}"),
            required_location_tags=tags,
            target_policy=target_policy,
            allowed_lifecycle_states=allowed,
            time_cost_minutes=max(0, time_cost),
            cooldown_minutes=int(item.get("cooldown_minutes") or 0),
            resource_cost=item.get("resource_cost") if isinstance(item.get("resource_cost"), dict) else {},
            hard_effect_id=_worldpack_effect_id(item),
            event_importance=importance,
            triggers_reaction=bool(item.get("triggers_reaction", target_policy in {"visible_ref", "known_name"})),
            visibility=str(item.get("visibility") or "same_location"),
            catalog_category=category,
            effect_summary=effect,
            source_version=str(item.get("version") or item.get("pack_version") or "worldpack"),
            metadata={
                "source_kind": "worldpack",
                "pack_id": item.get("pack_id"),
                "pack_name": item.get("pack_name"),
                "source_path": item.get("source_path"),
                "toolset_id": item.get("toolset_id"),
                "worldview_id": item.get("worldview_id"),
                "declarative_effect": item.get("declarative_effect") or item.get("effect") or {},
                "raw": item,
            },
        )


def refresh_external_worldpack_tools() -> int:
    try:
        from app.content.worldpacks import load_all_worldpacks

        load_all_worldpacks(force=True)
    except Exception:
        pass
    _remove_stale_external_tools()
    before = len(TOOL_SPECS)
    _register_worldpack_tools()
    return len(TOOL_SPECS) - before


_register_v5_catalog_tools()
_register_v6_catalog_tools()
_register_worldpack_tools()
