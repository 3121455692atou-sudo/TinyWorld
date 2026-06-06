每次写完后把本次修改写进交接文件。

# 交接记录

## 2026-06-07 04:18 CST

本次修改范围：

- 修复狼人杀角色夜间仍把白天已放逐者当成可讨论/可夜袭目标的问题。
- 投票结算为 `werewolf_exile` 后，现在会给所有仍存活居民写入高优先级狼人杀记忆：被放逐者已经出局，不能再发言、投票、被投票、被夜袭、被查验或被守护，也不能再作为可行动目标。
- 普通行动 prompt 新增“特殊状态”段；狼人杀公开后会列出当前存活者、已出局者及硬规则。未公开前不会出现“狼人杀/狼人/投票”等泄露词。
- 对狼人角色额外加入私密硬事实：当前存活狼人同伴是谁，以及今晚可夜袭目标只能从当前存活且非狼人同伴的人里选。
- 新增回归测试 `test_exiled_player_is_remembered_and_removed_from_wolf_targets`，覆盖被票死者会被写入记忆、夜间 prompt 的可夜袭目标列表不再包含已出局者。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest app/tests/test_werewolf_full_game_iteration.py -q` 通过，12 passed。
- `uv run pytest app/tests/test_werewolf_dialogue_survival_regression.py app/tests/test_event_ui_safety_and_worldviews.py -q` 通过，13 passed，3 warnings。

## 2026-06-07 04:03 CST

本次修改范围：

- 狼人杀最终发言的 `max_tokens` 从 2000 提高到 4000，用于覆盖推理模型/兼容接口把隐藏思考计入 completion 预算导致的正文截断。
- LLM provider 现在读取非流式和流式响应的 `finish_reason`；当接口返回 `length`、`max_tokens`、`token_limit`、`max_output_tokens` 等截断原因时，会将该次请求判为失败，不再把半截正文当作成功结果。
- 最终发言增加兜底完整性检查：如果正文末尾没有句末标点/省略号，视为疑似截断，不写入事件流、不推进最终发言队列。
- 新增回归测试 `test_werewolf_final_speech_truncated_text_is_retried`，覆盖“模型返回半截最终发言不能入库”。
- 再次修剪存档 `world_f87f24955337`（名称：`5.5跑狼人杀流式输出`）：删除 `9132` 到 `9138` 的 7 条最终发言/结束事件，清空 `final_speeches`，世界暂停在 `4238`，下一位仍为若叶睦。
- 修改数据库前已备份：`/mnt/COM/AIworld/data/world.sqlite3.bak-before-final-speech-4000-20260607-040314`。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest app/tests/test_werewolf_full_game_iteration.py -q` 通过，11 passed。
- 数据库确认 `world_f87f24955337` 最大事件回到 `9131`，`event_id > 9131` 为 0，状态为 `paused`。

## 2026-06-07 03:46 CST

本次修改范围：

- 取消上一轮狼人杀最终发言的“一人一句/80字以内”限制，改为 120 到 260 字左右的完整终局发言；狼人可自爆、炫耀、讽刺或说出伪装期间真实心情，人类根据狼人原话做更完整回应。
- 最终发言清洗不再截取第一句，只剥离代码块、行动编号和“正文：”这类外壳；保留长文本，仅在 900 字做防爆截断。
- 移除 `_fallback_final_speech` 静默托底。LLM 返回错误或空文本时，不再写固定假台词、不推进最终发言队列、不结束游戏；同一角色会保留为下一个最终发言者，供下次重试。
- 最终发言 LLM 请求恢复使用角色正常运行时重试配置，并将 `max_tokens` 提高到 700；后续 04:03 记录已继续提高到 4000。
- 新增回归测试 `test_werewolf_final_speech_empty_llm_does_not_use_fallback`，覆盖空输出/错误不能生成 `werewolf_final_speech`。
- 已再次修剪存档 `world_f87f24955337`（名称：`5.5跑狼人杀流式输出`）：删除 `9132` 到 `9138` 的 7 条短最终发言和结束事件，清空 `final_speeches`，世界暂停在 `4238`，下一位仍为若叶睦。
- 修改数据库前已备份：`/mnt/COM/AIworld/data/world.sqlite3.bak-before-final-speech-retry-20260607-034612`。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest app/tests/test_werewolf_full_game_iteration.py -q` 通过，10 passed。

## 2026-06-07 03:35 CST

本次修改范围：

- 修复狼人杀夜袭导致胜利后仍继续进入下一天的问题：夜袭写入 `night_kills` 后会先持久化，再进行胜负判定；判定后刷新调用方手里的 `werewolf_state`，避免后续旧 state 把 `winner/final_speech_order` 擦掉。
- `sync_werewolf_phase` 遇到已有 `winner` 且最终发言未完成时不再推进清晨/自由交流/普通行动，而是像圆桌阶段一样把幸存者拉到会议厅并稳定状态，随后交给最终发言队列。
- 最终发言提示词收紧为“一人一句”：狼人胜利时狼人先自爆/炫耀，人类再根据狼人原话回应；人类胜利时幸存人类逐个庆祝、庆幸或悼念。
- 最终发言清洗会优先截取第一句，避免 LLM 输出多段话。
- 新增回归测试 `test_wolf_night_kill_win_preserves_final_speech_state`，覆盖“夜袭结算触发狼人获胜后 winner 必须保留，后续同步不能再生成清晨尸体发现或阶段推进事件”。
- 已修剪最新存档 `world_f87f24955337`（名称：`5.5跑狼人杀流式输出`）：保留事件 `9130` 海铃夜间出局和 `9131` 胜负已定，删除 `9132` 之后错误推进到第 4 天的 12 条事件、对应对话、后续记忆和后续叙事摘要。
- 该存档已设为 `paused`，时间回到 `4238`；`werewolf_state.winner` 为 `狼人阵营`，最终发言队列为若叶睦、椎名立希、祐天寺若麦、要乐奈、三角初华、千早爱音；幸存者位置重置到会议厅。
- 修改数据库前已备份：`/mnt/COM/AIworld/data/world.sqlite3.bak-before-werewolf-final-speech-20260607-033252`。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest app/tests/test_werewolf_full_game_iteration.py -q` 通过，9 passed。
- 只读检查确认 `world_f87f24955337` 下一个最终发言者为若叶睦，提示词为狼人胜利后的自爆最终发言；未提前调用 LLM。

## 2026-06-07 00:18 CST

本次修改范围：

- 排查前端一直停在“正在读取本地游玩记录...”的问题：实际是后端 `8010` 多次不在监听，Vite 代理 `/api/worlds` 返回 `502/ECONNREFUSED`，浏览器页面卡在初始化状态。
- 将数据库里重启后遗留的孤儿 `running` 世界状态同步为 `paused`，避免后端重启后前端误以为模拟仍在内存里运行。
- 使用 `setsid` 重新脱离当前 shell 启动后端 `127.0.0.1:8010` 和前端 `127.0.0.1:5174`，前端启动时清除 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`，避免 Vite 本地代理受代理环境污染。
- 前端初始化读取本地世界列表增加 15 秒超时兜底；如果 `/api/worlds` 长时间无响应，会退出 loading 并显示“读取本地游玩记录超时”，不会永远停在启动卡片。

验证：

- `curl http://127.0.0.1:8010/api/health` 返回 200。
- `curl http://127.0.0.1:8010/api/worlds?limit=20&offset=0` 返回 200，约 9.5KB。
- `curl http://127.0.0.1:5174/api/worlds?limit=20&offset=0` 返回 200，约 9.5KB。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。

## 2026-06-06 23:52 CST

本次修改范围：

- 回答并定位 `ai.centos.hk/v1` provider 报错：key 和模型存在，但该接口在非流式请求下仍返回 `text/event-stream`，AIworld 旧非流式 JSON 解析会在 HTTP 外层失败；这不是行动头正则的问题。
- 隐藏低信息事件：`do_nothing` 新事件改为 system 可见性；公共事件接口非 debug 模式过滤 `nothing` 和 `tool_failed`，旧存档里“安静地什么也没做/试着做些什么但没完成”也不会再刷前端事件流。
- 狼人杀默认节奏调整为更像正常作息：08:00 自由交流，12:00 圆桌，18:00 投票，22:00 夜间行动；旧 18:00 夜间节奏和短 debug 节奏会按新默认读时迁移。
- 多狼人夜晚改为先强制狼人密会：所有存活狼人至少完成一次 `werewolf_wolf_discuss` 后才开放夜袭；狼人密会事件改为 observer 可见，玩家事件流可以看到狼队讨论，但不会作为普通公开事实塞给非狼人角色。
- 狼人杀胜负判定不再立刻结束世界：先写入胜负已定事件，再让幸存者按结局队列调用 LLM 生成 `werewolf_final_speech`；狼人胜利时狼人先自爆炫耀，人类再对狼人原话反应；人类胜利时幸存人类庆祝/庆幸/悼念。所有最终发言完成后才写 `werewolf_game_end` 并结束世界。
- 新增/更新回归测试，覆盖公共事件流隐藏无行动/失败占位、22:00 夜间节奏、多狼人先讨论再夜袭、结局发言调用 LLM 且发完才结束。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest -q backend/app/tests/test_werewolf_full_game_iteration.py backend/app/tests/test_event_ui_safety_and_worldviews.py` 通过，17 passed。
- `uv run pytest -q backend/app/tests/test_werewolf_dialogue_survival_regression.py backend/app/tests/test_turn_runner_survival.py backend/app/tests/test_tool_catalog_audit.py backend/app/tests/test_world_create_api.py` 通过，28 passed，3 warnings。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。

## 2026-06-06 19:39 CST

本次修改范围：

- 合入 `/home/atonelia/下载/aiworld_secret_tools_wolfpack_router_hotfix.patch`，应用参数为 `git apply -p5`。
- 狼人杀地点文案弱化明牌信息：预言家/守卫/验尸/狼人密会等地点改成更普通的村庄地点描述，避免居民开局直接知道隐藏身份机制。
- 狼人杀隐藏身份流程加强：居民触发规则前只知道普通村庄设定；夜袭/尸体发现/身份规则揭示用更清晰的隐藏事件、记忆和公开发现流程衔接。
- 狼人同伙路由加强：狼人获得同伴私有记忆，夜袭需要同伙目标一致；目标不一致会要求狼人先密会统一，避免反复机械提名。
- 工具候选/验证加强：隐藏系统工具、狼人专用工具、目标参数和已知姓名路由更严格，减少普通居民看到不该出现的秘密工具或角色身份信息。
- 新增/更新相关回归测试，覆盖秘密提示、狼人同伙、狼人杀对话生存和工具目录审计。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest -q backend/app/tests/test_secret_prompt_and_identity_regressions.py backend/app/tests/test_tool_catalog_audit.py backend/app/tests/test_werewolf_dialogue_survival_regression.py backend/app/tests/test_werewolf_full_game_iteration.py backend/app/tests/test_dynamic_tool_routing.py backend/app/tests/test_event_ui_safety_and_worldviews.py` 通过，40 passed。
- `uv run pytest -q backend/app/tests/test_world_create_api.py backend/app/tests/test_left_snapshot_refresh.py backend/app/tests/test_turn_runner_survival.py backend/app/tests/test_agent_simulation_repairs.py` 通过，24 passed，3 warnings。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。

## 2026-06-06 17:04 CST

本次修改范围：

- 修复“本地游玩记录”长时间卡在读取中的主要后端原因：`/api/worlds` 列表接口不再为了展示最近存档而写入运行状态，也不再返回完整世界 `settings`，只保留列表分组/难度/存档名需要的小字段。
- SQLite 数据库下，`parallel` 请求模式不再让同一轮多个角色各开独立 Session 并发提交 LLM 工具学习记录，改为顺序选择行动后再批量执行，避免 `database is locked` 把前端列表和刷新接口一起拖住。
- 修复左侧轻量快照的世界时间：现在会取最新事件时间，避免事件已推进但侧栏时钟仍停在旧 `world.current_world_time_minutes`。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest -q backend/app/tests/test_world_create_api.py backend/app/tests/test_event_ui_safety_and_worldviews.py backend/app/tests/test_dynamic_tool_routing.py backend/app/tests/test_left_snapshot_refresh.py` 通过，23 passed，3 warnings。

## 2026-06-06 17:03 CST

本次修改范围：

- 修复上一轮轻量化 `left-snapshot` 后，事件流/左侧居民列表等位置头像退化成姓名首字的问题。
- 原因：高频快照为了避免每 1.5 秒重复发送头像 base64，剥离了 `avatar_hint.image_data_url`；但首次进入世界时有些视图只拿到轻量快照，没有先拿到完整 `/agents` 响应。
- 前端 `frontend/src/app/App.tsx` 新增按世界一次性的完整头像补水逻辑：如果轻量快照里没有任何 `image_data_url`，就后台调用一次 `/api/worlds/{world_id}/agents` 拉完整头像。
- 新增 `mergeSnapshotAgents`/`hasAnyAgentImage` 相关合并逻辑，后续轻量快照刷新状态时会保留已有头像，不会再覆盖成空头像。
- 保留上一轮高频快照瘦身：`left-snapshot` 仍然不携带头像 base64，避免重新变回 700KB 级别。

验证：

- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- `python -m compileall -q backend/app` 通过。
- `uv run pytest backend/app/tests/test_world_create_api.py backend/app/tests/test_event_ui_safety_and_worldviews.py` 通过，13 passed。
- 只改前端逻辑，当前 Vite dev server 会热更新；后端无需重启。

## 2026-06-06 16:56 CST

本次修改范围：

- 排查前端卡顿和“两个世界同时跑”问题：后端实际只有一个 uvicorn 进程，但数据库里有两个 world 处于 `running`；同一后端进程可同时调度多个世界，但共享事件循环、SQLite、LLM/TTS provider 和前端轮询。
- 修复前端 API 请求层 `frontend/src/api/client.ts`：GET 请求不再默认带 `Content-Type: application/json`，避免跨端口开发模式下每个高频 GET 都触发 CORS `OPTIONS` 预检。
- 优化高频 `left-snapshot`：后端 `backend/app/api/worlds.py` 不再在 1.5 秒轮询接口里返回完整 `world.settings_json` 大包，改为返回轻量 world 字段。
- 优化高频 `left-snapshot`：后端从 agent/location occupant 的 `avatar_hint` 中剥离 `image_data_url`，避免每次轮询重复发送头像 base64。
- 前端 `frontend/src/app/App.tsx` 在应用轻量快照时保留当前 world 的完整 `settings`，并合并保留已有 agent 头像，避免 UI 丢失世界配置或头像。

验证：

- 修改前两个当前世界的 `left-snapshot` 约 `715KB`；修改并重启后降到约 `19-23KB`。
- 修改后后端日志中高频轮询不再出现成对的 `OPTIONS + GET`，只剩 GET。
- `uv run pytest backend/app/tests/test_world_create_api.py backend/app/tests/test_event_ui_safety_and_worldviews.py` 通过，13 passed。
- `python -m compileall -q backend/app` 通过。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 已重启后端 `http://127.0.0.1:8010`，健康检查返回 `{"ok":true}`。
- 前端 dev server 仍在 `http://127.0.0.1:5174` 运行。
- 因后端重启，内存中的模拟任务清空，当前两个原 running 世界已被同步为 paused；要继续双世界模拟需重新 start/resume。

## 2026-06-06 16:36 CST

本次修改范围：

- 合入用户提供的 `/home/atonelia/下载/aiworld_tool_relationship_routing_hotfix.patch`，使用 `git apply -p2` 应用。
- `/home/atonelia/下载/AIworld-core-code-20260606-tool-relationship-routing-hotfix.zip` 是同一热修的完整代码包，本次以 patch 为准合入，未直接覆盖整个项目。
- 新增 `backend/app/social/relationship_stage.py`，集中计算目标关系快照、关系阶段门槛、菜单上下文和排序权重。
- 行动菜单生成会对 `ask_date_visible_agent`、牵手、拥抱、告白、确认关系、分手、修复关系、成年亲密请求等工具按具体目标逐个过滤；陌生或低好感目标不会再显示确认交往/成年亲密类状态转移工具。
- 关系目标会按好感、信任、熟悉度、关系标签、冲突等排序，高关系阶段目标更靠前。
- `validate_tool` 增加关系阶段硬校验，防止 LLM 绕过菜单直接调用不该开放的关系/亲密工具。
- 成年亲密语义自动对齐不再因为世界开启生育系统就无条件转成成年亲密请求；必须当前菜单真的开放且关系阶段允许。
- 继续保留行动菜单 60 项上限，并给高关系阶段工具预留靠前位置。
- 保留并确认 LLM `request_timeout_ms` / `requestTimeoutMs` 配置链路，没有被热修覆盖或回退。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest backend/app/tests/test_dynamic_tool_routing.py backend/app/tests/test_tool_catalog_audit.py backend/app/tests/test_effects_and_knowledge.py backend/app/tests/test_agent_simulation_repairs.py backend/app/tests/test_event_ui_safety_and_worldviews.py backend/app/tests/test_werewolf_full_game_iteration.py` 通过，113 passed。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 已重启后端 `http://127.0.0.1:8010`，健康检查返回 `{"ok":true}`。
- 前端 dev server 仍在 `http://127.0.0.1:5174` 运行。

## 2026-06-06 15:27 CST

本次修改范围：

- 合入用户提供的 `/home/atonelia/下载/aiworld_werewolf_simple_roundtable_tools_hotfix.patch`，使用 `git apply -p5` 应用。
- `/home/atonelia/下载/world_3a444bbcb09f_events_start_end.zip` 是事件导出样本，包含 `index.html`、`events.json`、`README.txt`；本次仅作为参考查看，未放入项目。
- 狼人杀圆桌阶段改为更简单的主持队列：当前发言人完成后自动轮到下一人，减少反复反驳/插话工具导致的停滞。
- 狼人杀讨论、投票、夜间阶段进一步收窄行动菜单；投票阶段使用按已知姓名投票，夜间只给对应身份开放必要能力。
- 狼人杀阶段同步会在讨论/投票/夜间重新稳定玩家位置和状态，避免睡眠/地点状态让主持流程跳过。
- 前端地点面板改为后端快照驱动，增加手动刷新按钮和左侧快照时间；地点列表不再显示右侧人数数字。
- 运行设置里的行动编号上限默认从 `90` 降为 `60`，输入上限也改为 `60`，减少本地模型每轮菜单长度。
- 保留并确认上一轮新增的 LLM `request_timeout_ms` / `requestTimeoutMs` 配置链路，没有被 5.5pro 的旧版 patch 回退。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest backend/app/tests/test_werewolf_full_game_iteration.py backend/app/tests/test_turn_runner_survival.py backend/app/tests/test_event_ui_safety_and_worldviews.py backend/app/tests/test_tool_catalog_audit.py backend/app/tests/test_world_create_api.py` 通过，37 passed，只有 FastAPI/Starlette 既有弃用警告。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 已重启后端 `http://127.0.0.1:8010`，健康检查返回 `{"ok":true}`。
- 前端 dev server 仍在 `http://127.0.0.1:5174` 运行。

## 2026-06-06 14:07 CST

本次修改范围：

- 修复 OpenAI-compatible LLM 请求硬编码 60 秒超时的问题。
- 后端 `backend/app/llm/runtime.py` 新增 `request_timeout_ms` 运行时配置，默认 `300000` ms，最大 `86400000` ms，`0` 表示不主动超时。
- 后端 `backend/app/llm/openai_compatible.py` 改为按 `request_timeout_ms` 创建 `httpx.AsyncClient`，不再固定 `timeout=60`。
- 创建世界 provider、解说 provider、宝宝模型池、身份生成、运行中单角色 LLM 更新接口、角色详情序列化、人员配置导出都接入 `request_timeout_ms`。
- 前端 provider 配置新增“请求超时 ms”，默认 `300000`；旧 localStorage/导入配置缺字段时自动补默认值。
- 前端运行中 Agent 抽屉的 LLM 配置新增“请求超时 ms”，保存时会 PATCH `request_timeout_ms`，切换 provider 时也同步 provider 的超时设置。

验证：

- `uv run pytest backend/app/tests/test_world_create_api.py` 通过，5 passed。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 已重启后端 `http://127.0.0.1:8010`，健康检查返回 `{"ok":true}`。
- 前端 dev server 仍在 `http://127.0.0.1:5174` 运行。

## 2026-06-05 23:32 CST

本次修改范围：

- 修复人员配置导入时 `.zip.bak-before-5tts` 被误当作 JSON 解析的问题。
- 问题原因：前端 `importAgentArchive` 只用 `file.name.toLowerCase().endsWith(".zip")` 判断 zip；`少女乐队十人.zip.bak-before-5tts` 虽然内容是 zip，但后缀不是 `.zip`，因此走到 `JSON.parse(await file.text())`，报 `Unexpected token 'P', "PK "... is not valid JSON`。
- 在 `frontend/src/app/App.tsx` 新增 `isZipLikeFile(file)`：文件名以 `.zip` 结尾、文件名包含 `.zip.`，或文件头匹配 `PK\x03\x04 / PK\x05\x06 / PK\x07\x08` 时都按 zip 处理。
- `importAgentArchive` 改为使用 `await isZipLikeFile(file)` 分流，备份后缀 zip 也会读取 `manifest.json`，不再误走 JSON 解析。

验证：

- 确认 `/home/atonelia/下载/少女乐队十人.zip.bak-before-5tts` 是 zip 文件，前 8 字节为 `PK 03 04 ...`，压缩包内包含 `manifest.json` 和头像目录。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 已重启 AIworld 前端 dev server `http://127.0.0.1:5174/`。
- 后端 `http://127.0.0.1:8010/api/health` 返回 `{"ok":true}`。
- 确认 `frontend/tsconfig.tsbuildinfo` 不存在。
- 确认 5 个 GPT-SoVITS 端口 `9881-9885` 仍在监听。

## 2026-06-05 22:39 CST

本次修改范围：

- 合入用户提供的 `/home/atonelia/下载/AIworld-core-code-20260605-werewolf-dialogue-survival-hotfix.zip` 热修包，按原项目结构覆盖核心代码。
- 合入时排除了 `HANDOFF.md` 和 `frontend/tsconfig.tsbuildinfo`，避免覆盖本地交接记录或保留构建缓存。
- 狼人杀生存/对话热修：狼人杀夜晚结束后会给存活或临界玩家做隐式夜间恢复，避免第二天圆桌被饥饿、脱水、疲劳和昏迷吞掉。
- 修复狼人杀早晨同步反复把已去食堂等地点的玩家拉回广场的问题：同一 morning phase 内不再覆盖正常早餐移动。
- 修复旧存档已经处于第 2 天 morning phase 时没有做夜间恢复的问题，读取/同步阶段也会补恢复标记。
- 圆桌和投票等主持阶段会稳定存活玩家状态，并把圆桌阶段玩家同步到讨论地点，避免存活玩家昏迷导致无法发言。
- 新增回归测试 `test_werewolf_dialogue_survival_regression.py`，覆盖早餐移动不被拉回、旧 morning phase 恢复、LLM 行动解析失败仍产生圆桌台词、昏迷存活玩家可被恢复参与主持发言。

验证：

- `python -m compileall -q backend/app` 通过。
- `PYTHONPATH=backend uv run pytest -q backend/app/tests` 通过，161 passed，3 warnings。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 已重启 AIworld 后端 `http://127.0.0.1:8010`，`/api/health` 返回 `{"ok":true}`。
- 已重启 AIworld 前端 dev server `http://127.0.0.1:5174/`。
- 确认 `frontend/tsconfig.tsbuildinfo` 不存在。
- 确认 5 个 GPT-SoVITS 端口 `9881-9885` 仍在监听。

## 2026-06-05 19:14 CST

本次修改范围：

- 合入用户提供的 `/home/atonelia/下载/AIworld-core-code-20260605-werewolf-refresh-hotfix.zip` 热修包，按原项目结构覆盖核心代码。
- 合入时排除了 `HANDOFF.md` 和 `frontend/tsconfig.tsbuildinfo`，避免覆盖本地交接记录或保留构建缓存。
- 狼人杀调度热修：当所有普通 agent 暂无行动时，若狼人杀阶段结束时间早于下一次普通唤醒时间，调度器会推进到狼人杀阶段结束，避免卡在阶段中间。
- 狼人杀投票/夜晚阶段新增结构化行动选择：公开投票必须优先投票，夜间阶段优先执行狼人、预言家、验尸官、守卫等夜间能力，不再被睡觉、吃饭、闲逛或普通社交抢走回合。
- 新增狼人杀结构化行动兜底：LLM 格式失败或没有给出可执行选择时，会从当前菜单里选第一个可验证通过的狼人杀行动，并补默认台词/参数，避免流程空转。
- 更新狼人杀全局迭代测试和工具目录审计测试，覆盖单狼不需要狼队讨论、狼队讨论已完成、阶段推进等场景。

验证：

- `python -m compileall -q backend/app` 通过。
- `PYTHONPATH=backend uv run pytest -q backend/app/tests` 通过，157 passed，3 warnings。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 已重启 AIworld 后端 `http://127.0.0.1:8010`，`/api/health` 返回 `{"ok":true}`。
- 已重启 AIworld 前端 dev server `http://127.0.0.1:5174/`。
- 确认 `frontend/tsconfig.tsbuildinfo` 不存在。
- 确认 5 个 GPT-SoVITS 端口 `9881-9885` 仍在监听。

## 2026-06-05 16:46 CST

本次修改范围：

- 合入用户提供的 `/home/atonelia/下载/AIworld-core-code-20260605-tool-prune-llm-expression-fix.zip` 修复包，按原项目结构覆盖核心代码。
- 合入并保留 `TOOL_PRUNE_LLM_EXPRESSION_FIX_REPORT.md`，用于追踪本轮工具目录瘦身与 LLM 表达能力保留说明。
- 合入时排除了修复包里的 `HANDOFF.md`，避免覆盖本地交接记录；清理并确认 `frontend/tsconfig.tsbuildinfo` 不存在。
- 工具目录瘦身：减少纯情绪、喜好、态度、寒暄、气氛动作等低价值工具，避免动态工具菜单被这些工具挤占。
- 保留通用表达能力：`say_to_visible_agent`、`speak_to_nearby`、`write_private_note`、`add_memory`；纯情绪和态度应写进台词/正文，而不是占一个专门工具。
- 保留会改变世界状态或关系状态的工具路径：移动、生存、照护、医疗、工作、金融、法律、犯罪、狼人杀、关系确认、生育流程等。
- 动态菜单压缩：成人 agent 动态候选、最终展示上限、AOHP 普通菜单上限、reaction 菜单上限均下调，同时保底移动、生存、医疗、照护、关系/家庭状态变更类工具。
- 旧式软表达工具保留兼容但不进入 agent 菜单；旧输出调用时会提示改用说话、附近发言、私人笔记或记忆记录。

验证：

- `python -m compileall -q backend/app` 通过。
- `PYTHONPATH=backend uv run pytest -q backend/app/tests` 通过，155 passed，3 warnings。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 已重启 AIworld 后端 `http://127.0.0.1:8010`，`/api/health` 返回 `{"ok":true}`。
- 已重启 AIworld 前端 dev server `http://127.0.0.1:5174/`。
- 确认 `frontend/tsconfig.tsbuildinfo` 不存在。
- 确认 5 个 GPT-SoVITS 端口 `9881-9885` 仍在监听。

## 2026-06-05 12:08 CST

本次修改范围：

- 合入用户提供的 `/home/atonelia/下载/AIworld-core-code-20260605-werewolf-llm-ui-fix.zip` 修复包，按原项目结构覆盖核心代码。
- 合入并保留 `WEREWOLF_LLM_UI_REFRESH_FIX_REPORT.md` 和 `FRONTEND_REFRESH_FIX_REPORT.md`，用于追踪本轮外部修复说明。
- 合入时排除了修复包里的 `HANDOFF.md`，避免覆盖本地交接记录；排除了并清理 `frontend/tsconfig.tsbuildinfo`。
- 前端左侧栏刷新改为关键快照分批落地：世界、居民、地点、事件不再被慢接口整体阻塞；地点人数优先从 live agents 计算。
- 狼人杀机制调整：第 1 天白天只自由交流，第 1 天夜晚开始夜间能力，第 2 天开始正式圆桌和投票；圆桌发言不消耗世界分钟，显示为“第N天 圆桌讨论”。
- 狼人杀圆桌新增反驳/回怼流程，争论超过上限会自动暂停并回到主持流程；第 2 天起常规投票不再提供“不放逐任何人”选项。
- 角色详情可显示观察者可见的狼人杀身份。
- LLM 配置新增全局和单 Agent 生成设置：流式开关、temperature、top_p、max_tokens、presence_penalty、frequency_penalty；OpenAI-compatible 客户端支持 SSE 流式响应。
- 事件流多人讲话显示修复：payload 带多个 `addressed_agent_ids` 时按群体发言渲染，不再误显示成单一目标。

验证：

- `python -m compileall -q backend/app` 通过。
- `PYTHONPATH=backend uv run pytest -q backend/app/tests` 通过，138 passed，3 warnings。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 已重启 AIworld 后端 `http://127.0.0.1:8010`，`/api/health` 返回 `{"ok":true}`。
- 已重启 AIworld 前端 dev server `http://127.0.0.1:5174/`。
- 确认 `frontend/tsconfig.tsbuildinfo` 不存在。
- 确认 5 个 GPT-SoVITS 端口 `9881-9885` 仍在监听。

## 2026-06-05 02:04 CST

本次修改范围：

- 合入用户提供的 `/home/atonelia/下载/AIworld-core-code-20260605-repaired.zip` 修复包，按原项目结构覆盖核心代码。
- 同步保留 repaired 包中的 `FRONTEND_WEREWOLF_FIX_REPORT.md`，方便追踪 5.5pro 的修复说明。
- 合入时排除了 repaired 包里的 `HANDOFF.md`，避免覆盖本地交接记录；也排除了并清理 `frontend/tsconfig.tsbuildinfo` 构建缓存。
- 前端影响世界面板使用明确的 `expanded` 状态和 `data-expanded`：折叠显示“展开”，展开显示“收起”；展开后不再渲染右下角那组能力快捷按钮。
- 前端 WebSocket 刷新改为节流加 pending 队列，避免连续事件导致世界时间、地点人数、居民位置刷新长期被推迟。
- 后端候选工具调试事件改为 system 可见性，并在事件列表和导出中过滤旧的 `candidate_request`，减少机械调试文本漏到事件流。
- 狼人杀日程改为真实一天节奏：08:00-12:00 自由交流，12:00-16:00 圆桌发言，16:00-18:00 公开投票，18:00-次日 08:00 夜间行动；旧存档里的短调试周期会在读取时迁移。
- 狼人杀圆桌阶段只调度当前发言人；当前发言人至少说一次后才能结束发言，最多 10 次，可以提前结束；LLM 格式失败时会兜底生成自然发言，避免阶段空转。

验证：

- `python -m compileall -q backend/app` 通过。
- `PYTHONPATH=backend uv run pytest -q backend/app/tests` 通过，135 passed，3 warnings。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 已重启后端 `http://127.0.0.1:8010`，`/api/health` 返回 `{"ok":true}`。
- 已重启前端 dev server `http://127.0.0.1:5174/`。
- 确认 `frontend/tsconfig.tsbuildinfo` 不存在。

## 2026-06-05 01:18 CST

本次操作：

- 按用户要求打包当前前后端核心代码，保留 `AIworld/` 项目结构。
- 输出压缩包：`/home/atonelia/下载/AIworld-core-code-20260605-current.zip`。
- 包内包含：`backend/app`、`frontend/src`、前端入口/配置文件、`pyproject.toml`、`uv.lock`、README、`HANDOFF.md`。
- 包内排除：`.venv`、`node_modules`、`frontend/dist`、`.pytest_cache`、`__pycache__`、`*.pyc`、数据库、运行日志、debug/export 目录和大资源文件。
- 重新打包过一次，确认最终包不包含 `.pyc/__pycache__`。

验证：

- 压缩包大小约 `975K`。
- `unzip -l` 显示 164 个文件，总内容约 `3.06MB`。

## 2026-06-05 01:09 CST

本次修改范围：

- 修复影响世界面板展开按钮：按钮文字不再走翻译表，折叠时显示“展开”，展开时显示“收起”。
- 删除影响世界面板右下角 6 个能力快捷按钮，只保留上方“方式”下拉选择和右侧当前能力说明。
- 修复狼人杀世界卡住的真实原因：`backend/app/tools/registry.py` 漏导入 `werewolf_tool_allowed`，导致调度器在生成行动菜单时 `NameError`，前端表现为没有新事件、token 不消耗。
- 狼人杀阶段文案改为中性标签：`自由交流 / 圆桌发言 / 公开投票 / 夜间行动`，不再在 08:xx 显示“下午圆桌发言”。
- 狼人杀模式强制使用 fast 调度间隔，不受世界设置里误选 `slow` 拖慢。
- 狼人杀模式下普通对话不再套 2 分钟上限；默认每次普通对话至少 6 分钟，狼人杀专用工具按 `tool_time_scale=2.0` 推进局内时间。
- 狼人杀世界强制走 per-agent 执行，不再把同一批角色全部重置到同一个 `base_time` 后只取最大结束时间。这样每个人行动后时间会累加，事件流不会再全部挤在同一分钟。
- 更新狼人杀预设参数，新增 `conversation_minutes` 和 `tool_time_scale`。
- 重启后端和前端 dev server。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest -q backend/app/tests/test_agent_simulation_repairs.py backend/app/tests/test_event_ui_safety_and_worldviews.py backend/app/tests/test_turn_runner_survival.py backend/app/tests/test_repair_regressions.py` 通过，27 passed。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。
- 后端 `http://127.0.0.1:8010/api/health` 返回 `{"ok":true}`。
- 前端 dev server 运行在 `http://127.0.0.1:5174/`。
- 对暂停世界 `world_5832d1689d50` 手动执行 step 验证：调度不再 NameError；新事件时间从 `09:03`、`09:07`、`09:17`、`09:27` 逐步推进，不再全部压在同一分钟。
- 手动 step 的 HTTP 请求后半段疑似等待解说生成较久，但 per-agent 事件已提交并可被前端看到；本地 curl 验证进程已终止，未杀后端。

## 2026-06-05 00:25 CST

本次修改范围：

- 前端 `WorldInterventionPanel` 初始改为折叠，按钮第一眼显示“展开”；能力说明按当前选中能力稳定刷新，避免选择“相互心动”等能力时右侧仍显示移动居民说明。
- 狼人杀阶段从真实 24 小时日程改为短局内日程：默认 08:00 开始，20 分钟自由、45 分钟讨论、25 分钟投票、90 分钟夜间，180 分钟进入下一天。
- 狼人杀角色人数规则改为：5 人及以下 1 狼，6-8 人 2 狼，9-12 人 3 狼，13 人及以上 4 狼。
- 狼人杀投票规则改为：第 1 天投票阶段可选择“不放逐任何人”；第 2 天起必须放逐一名幸存者。新增 `werewolf_vote_no_execution` 工具。
- 狼人杀讨论、投票、夜间阶段的行动菜单聚焦狼人杀工具，只保留必要兜底/查看状态工具，减少跑去食堂、工作、普通闲聊等场外动作。
- 狼人杀工具耗时下调到 1-2 分钟级别，避免一局推进过慢。
- 修复合入优化包后遗留的医疗帮助回归：补回 `help_visible_agent` 用到的医疗转运/买饭水救急判断函数。
- 前端公开事件序列化对 `tool_failed` / `job_application_failed` 保持不暴露内部 payload，避免工具失败细节显示到事件流。
- 更新测试覆盖狼人杀短阶段、角色分配、首日不放逐、次日起强制放逐，并修正医疗帮助测试里的会话刷新。

验证：

- `python -m compileall -q backend/app` 通过。
- `uv run pytest -q backend/app/tests/test_agent_simulation_repairs.py backend/app/tests/test_event_ui_safety_and_worldviews.py backend/app/tests/test_turn_runner_survival.py` 通过，21 passed。
- 核心回归测试组通过，50 passed，只有 FastAPI/Starlette 既有弃用警告。
- `frontend`: `npm run build` 通过，仅保留 Vite 大 chunk 警告。

运行状态：

- 前端 dev server 已在 `http://127.0.0.1:5174` 运行。
- 后端已用 `setsid nohup uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010` 后台启动，`http://127.0.0.1:8010/api/health` 返回 `{"ok":true}`。
