# Tiny Living World 高自由度睡眠/记忆/社会秩序修复报告

本包目标不是把 agent 改成“到点自动睡觉”的保姆系统，而是修复当前世界里最致命的失真：agent 明明说自己困、想回家睡、甚至已经回家，却没有进入真实睡眠调度，最后因为代码和提示词断层而批量死亡。

## 1. 核心设计原则

1. **不强制日常睡眠**  
   22:00 后不会无条件覆盖 LLM 行动。agent 仍然可以熬夜、聊天、加班、偷窃、巡逻、发起会议、写日记或乱来。

2. **把“说想睡”转成“真的能睡”**  
   如果 LLM 的 `plan_summary`、`speech`、`content` 等字段明确表达“困了、想睡、回家睡、撑不住”，但工具却选成了 `speak_to_nearby` / `look_around` / 其他非睡眠工具，后端会做语义对齐：
   - 在 home：改成 `sleep`
   - 不在 home 且能回家：改成 `return_home` 并附加 `sleep_after_arrival=true`
   - 无法回家/无家可归/主动在外：改成 `sleep_rough`

3. **保留“我就是不睡”的自由**  
   如果文本里明确出现“不睡、熬夜、通宵、再撑、继续工作、守夜、偷、抢、攻击”等意图，系统不会修成睡觉。

4. **露宿是真睡眠，不是假加体力**  
   `sleep_rough` 和 v6 的 `v6_sleep_rough_when_homeless` 现在都进入真实睡眠调度，醒来才结算恢复、梦境整理、露宿惩罚和被偷/惊醒风险。

5. **物理崩溃是世界规则，不是保姆行为**  
   体力极低时会进入“身体撑不住”的急迫分支；48 小时不睡优先造成昏迷/强制昏睡，而不是健康状态下随机大批猝死。

## 2. 修改文件总览

- `backend/app/simulation/turn_runner.py`
  - 增加睡眠意图语义对齐。
  - 修复急迫生存分支缺少低体力睡眠处理的问题。
  - 低体力时优先真实睡眠/回家后睡/露宿，而不是继续空转。
  - 保留夜间 LLM 自由选择，不再添加普通 bedtime 硬强制。

- `backend/app/effects/effect_engine.py`
  - 新增 `sleep_rough` 硬效果。
  - 新增 `_start_sleep_schedule()` 统一登记真实睡眠。
  - `return_home` 支持 `sleep_after_arrival` 和 `sleep_hours`。
  - `complete_scheduled_sleep()` 支持 normal/rough 两种睡眠质量。
  - 露宿醒来有更脏、更紧张、心情下降，以及小概率钱被偷/被惊醒事件。
  - 新增社区会议/公共规则/宪法草案相关硬效果。

- `backend/app/effects/death.py`
  - 修复 `0` 世界时间被 `or` 误判的问题。
  - 连续清醒 48 小时后优先进入昏迷/强制昏睡。
  - 只有健康已经极低时才保留极小概率死亡。

- `backend/app/knowledge/perception.py`
  - 提示词新增内部动机/奖惩倾向。
  - 提示词新增社会秩序观察。
  - 明确告诉 agent：`rest` 不能代替睡眠；想睡必须用 `sleep` 或 `sleep_rough`。
  - 明确告诉 agent 可以提出社区规则、互助协议、宪法草案，但这些只是提议，不自动强制生效。

- `backend/app/memory/memory_service.py`
  - 优化做梦整理记忆。
  - 高重要度、创伤、犯罪、死亡、怀孕、孩子、恋爱、承诺、房租、驱逐、入狱、公共规则等记忆不会被随便归档。
  - 普通低重要短时记忆会在梦境总结后归档，减少记忆污染。

- `backend/app/tools/tool_specs.py`
  - 新增 `sleep_rough`。
  - 新增 `call_community_meeting`、`propose_social_rule`、`support_social_rule`、`oppose_social_rule`。
  - v5/v6 YAML 路径改为项目内置 `backend/app/data/`，并支持环境变量覆盖。

- `backend/app/tools/registry.py`
  - `sleep_rough` 按地点、夜晚、疲劳、无家可归状态动态显示。
  - 睡眠、露宿、回家在低体力/夜晚时提高候选优先级。
  - 社会失序、受害、犯罪、无家可归时提高公共治理工具优先级。

- `backend/app/economy/v6.py`
  - 修复首次经济 tick 可能跳过房租的问题。
  - v6 露宿改为真实睡眠调度。

- `backend/app/tests/test_effects_and_knowledge.py`
  - 新增睡眠意图对齐、露宿真实调度、回家后睡眠链式执行、公共规则提议、梦境记忆归档测试。

## 3. 睡眠行为现在如何运作

### 3.1 agent 明确不想睡

示例：

```json
{
  "tool_name": "work_overtime_shift",
  "params": {},
  "plan_summary": "我决定今晚继续加班，不睡了。"
}
```

系统尊重它。它会赚钱，但产生疲劳、睡眠债、健康/情绪代价。

### 3.2 agent 明确想睡但工具选错

示例：

```json
{
  "tool_name": "speak_to_nearby",
  "params": {"speech": "我困得不行，想回家睡觉。"},
  "plan_summary": "我准备回去睡觉。"
}
```

系统会把它对齐为：

```json
{
  "tool_name": "return_home",
  "params": {"sleep_after_arrival": true, "sleep_hours": 8},
  "plan_summary": "刚才已经明确想睡觉，所以回家后直接睡。"
}
```

到家后直接生成 `sleep_start`，登记 `sleep_until_world_time`。

### 3.3 agent 无家可归或不回家但想睡

它可以调用：

```json
{"tool_name": "sleep_rough", "params": {"sleep_hours": 8}}
```

这会进入真实睡眠。醒来时会：

- 按睡眠恢复体力、降低压力。
- 再结算露宿惩罚：更脏、更紧张、心情下降。
- 小概率发生 `rough_sleep_risk`，比如钱少了但不知道是谁做的。

## 4. 记忆和梦境整理

旧版梦境整理只是把最近几条记忆拼在一起。新版会分层：

- **不能随便忘掉的事**：高重要度、创伤、犯罪、死亡、关系承诺、怀孕孩子、驱逐、入狱、公共规则。
- **可以压缩成背景印象的日常**：普通聊天、走路、低重要日常。
- **醒来后仍悬着的问题**：低水、低饱腹、低体力、高压力、无家可归、债务。

这能让 agent 更像“睡觉后整理人生”，不是把所有东西都混成垃圾摘要。

## 5. 社会发散与宪法/规则提议

新增四个工具：

- `call_community_meeting`：召集公共会议。
- `propose_social_rule`：提出公共规则、宪法草案、互助协议。
- `support_social_rule`：支持规则。
- `oppose_social_rule`：反对或修正规则。

这些工具会写入 `world.settings_json["governance"]["proposals"]`，也会生成公共事件、触发反应链，但不会自动变成硬规则。也就是说 agent 可以发散出社会秩序，但不会破坏高自由度。

## 6. 奖惩/欲望机制增强

提示词现在会把 agent 的内部动机整理成清晰压力：

- 生存压力：吃喝睡能降低痛苦。
- 睡眠压力：睡觉恢复体力、降低压力；不睡可能换金钱/刺激，但有长期风险。
- 经济压力：工作、借贷、求助、节俭、犯罪各有收益和代价。
- 无聊/孤独：推动社交、娱乐、探索。
- 道德/内疚：影响帮助、守信、报警、补偿、犯罪后的心理代价。

数值变化仍由后端硬规则结算，LLM 只负责选择和表达。

## 7. 测试结果

已运行：

```bash
uv run pytest -q
```

结果：

```text
28 passed in 3.86s
```

已运行：

```bash
python -m compileall -q backend/app
```

结果：通过，没有语法错误。

## 8. 关键提醒

这版没有承诺真实 LLM 永远不会作死。高自由度意味着 agent 仍然可以选择熬夜、犯罪、拒绝求助、不工作、露宿、乱花钱。修复点是：

- 如果 agent 想睡，现在能真的睡。
- 如果 agent 回家准备睡，现在可以链式睡。
- 如果 agent 无家可归，现在能在街边真实露宿。
- 如果 agent 因长时间不睡崩溃，会先昏睡，而不是一群健康人随机猝死。
- 如果社会出问题，agent 有工具提出规则和宪法，不再只能闲聊或空转。
