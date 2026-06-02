from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LocationSpec:
    location_id: str
    public_name: str
    description: str
    neighbors: list[str]
    available_tools: list[str] = field(default_factory=list)
    visibility_radius: int = 0
    capacity: int | None = None
    tags: list[str] = field(default_factory=list)


INITIAL_LOCATIONS: list[LocationSpec] = [
    LocationSpec(
        "central_square",
        "中央广场",
        "一片开阔的石板广场，四周能看见通往各处的小路，适合观察、聊天和发起活动。",
        ["cafeteria", "cabin", "library", "garden", "market", "notice_board", "hot_spring_lobby"],
        ["look_around", "speak_to_nearby", "play_simple_game"],
        0,
        tags=["social", "open_view"],
    ),
    LocationSpec(
        "cafeteria",
        "公共食堂",
        "有长桌、热水壶和简单餐食的公共空间，空气里有温和的饭菜气味。",
        ["central_square", "medical_room", "market"],
        ["eat_food", "drink_water", "speak_to_nearby"],
        tags=["food_service", "food", "water", "social"],
    ),
    LocationSpec(
        "cabin",
        "林间小屋",
        "木墙、窄床和几张书桌构成的安静住所，适合睡觉、自我照料和写日记。",
        ["central_square", "lake", "campfire"],
        ["sleep", "rest", "wash", "drink_water", "write_diary"],
        tags=["home", "quiet", "water"],
    ),
    LocationSpec(
        "library",
        "图书馆",
        "低矮书架和旧木桌围出一片安静角落，适合阅读、学习和整理长期记忆。",
        ["central_square", "workshop", "notice_board"],
        ["write_diary", "add_memory", "tell_story_nearby"],
        tags=["quiet", "learning"],
    ),
    LocationSpec(
        "lake",
        "湖边",
        "湖水贴着芦苇轻轻晃动，岸边有石头小径，适合散步、独处和谈心。",
        ["cabin", "garden", "campfire"],
        ["walk_by_lake", "rest", "speak_to_nearby"],
        tags=["quiet", "nature", "water"],
    ),
    LocationSpec(
        "workshop",
        "工作坊",
        "摆着木料、布料和工具箱的工坊，适合制作简单物品、修理和合作。",
        ["library", "market"],
        ["craft_simple_item", "add_memory"],
        tags=["craft", "work"],
    ),
    LocationSpec(
        "medical_room",
        "医务室",
        "白色帘子和药柜让这里显得克制而可靠，适合休息、检查健康和处理受伤。",
        ["cafeteria", "garden"],
        ["rest", "drink_water", "seek_help"],
        tags=["medical", "water", "quiet"],
    ),
    LocationSpec(
        "garden",
        "花园",
        "花圃、果树和窄窄的泥路组成一处明亮地方，能采集、种植和观察自然。",
        ["central_square", "lake", "medical_room"],
        ["forage_food", "walk_by_lake", "play_simple_game"],
        tags=["nature", "natural_food", "fun"],
    ),
    LocationSpec(
        "market",
        "集市",
        "几排小摊摆着工具和杂物，适合交换物品、赠送和闲逛。",
        ["central_square", "cafeteria", "workshop"],
        ["give_item_to_visible_agent", "pick_up_item", "speak_to_nearby"],
        tags=["trade", "social"],
    ),
    LocationSpec(
        "hot_spring_lobby",
        "温泉前厅",
        "木质前厅里挂着暖帘，能买票进入不同汤池，也适合约人一起泡温泉。",
        ["central_square", "hot_spring_men", "hot_spring_women", "hot_spring_mixed"],
        ["speak_to_nearby", "invite_visible_agent_to_hot_spring"],
        tags=["trade", "social", "hot_spring_lobby"],
    ),
    LocationSpec(
        "hot_spring_men",
        "男汤",
        "热气慢慢升起的温泉汤池，适合清洁身体、放松和安静交谈。",
        ["hot_spring_lobby"],
        ["soak_hot_spring", "wash", "speak_to_nearby"],
        tags=["water", "social", "hot_spring", "male_bath"],
    ),
    LocationSpec(
        "hot_spring_women",
        "女汤",
        "热气慢慢升起的温泉汤池，适合清洁身体、放松和安静交谈。",
        ["hot_spring_lobby"],
        ["soak_hot_spring", "wash", "speak_to_nearby"],
        tags=["water", "social", "hot_spring", "female_bath"],
    ),
    LocationSpec(
        "hot_spring_mixed",
        "混浴温泉",
        "更开放的公共汤池，水声和雾气让谈话显得轻柔，但也更需要彼此尊重边界。",
        ["hot_spring_lobby"],
        ["soak_hot_spring", "wash", "speak_to_nearby"],
        tags=["water", "social", "hot_spring", "mixed_bath"],
    ),
    LocationSpec(
        "campfire",
        "篝火营地",
        "圆木围着火坑摆成一圈，夜里尤其适合群聊、讲故事和唱歌。",
        ["cabin", "lake"],
        ["tell_story_nearby", "sing_nearby", "play_simple_game"],
        tags=["social", "fun", "night"],
    ),
    LocationSpec(
        "notice_board",
        "布告栏",
        "木制公告板立在路口，上面可以发布公开消息，也能阅读他人留下的字条。",
        ["central_square", "library"],
        ["post_notice", "add_memory"],
        tags=["notice", "public_record"],
    ),
    LocationSpec(
        "jail",
        "临时看守所",
        "一处只用于司法后果的封闭小楼，里面有窄床、简易书架和低薪劳动安排。这里不适合自由社交，只能等待、反思、写信或做狱中劳动。",
        ["central_square"],
        ["jail_rest", "jail_low_paid_work", "jail_reflect", "jail_write_letter", "jail_wait_release", "refuse_jail_work"],
        tags=["jail", "quiet", "work"],
    ),
]


LOCATION_BY_ID = {location.location_id: location for location in INITIAL_LOCATIONS}
