# 工具逻辑复查说明

用户当前重点问题：角色 A 向 B 请求拥抱，B 也向 A 请求拥抱，但系统没有把双方同意合并成一次实际拥抱事件。这说明当前社交/亲密工具仍偏向“请求动作”，缺少“待处理请求 + 对方同意/拒绝 + 成功执行”的二阶段或握手机制。

请重点检查：

- `hug_visible_agent`、`hold_hands_visible_agent`、`ask_date_visible_agent`、`comfort_visible_agent` 等 visible_ref 社交工具是否只生成泛化社交事件，没有建立可被回应的 pending intent。
- `effect_engine.py` 中 `romance_social`、`generic_visible_social`、`define_relationship`、`request_adult_intimacy`/`accept_adult_intimacy` 的处理差异。
- `reaction_queue.py` 与 `turn_runner.py` 的反应链是否能让目标 agent 看见“有人向我提出请求”，并在同意时触发实际完成事件。
- 工具描述是否需要明确区分“请求/邀请/试探”和“执行/接受/完成”。
- 前端事件文本应显示自然语言结果，不要把硬规则、资源 delta 或内部机制说明直接暴露给玩家。

建议方向：为非露骨亲密和普通互动建立统一的 pending interaction 结构，例如 `pending_social_requests`，包含 requester、target、request_type、created_world_time、expires_at、message、consent_required。对方选择接受时由后端硬规则生成一次实际拥抱/牵手/一起散步事件；选择拒绝则生成拒绝事件并调整关系/情绪。双方同时互相请求时，应可合并为一次双方同意的实际事件。
