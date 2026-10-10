任务：actor_slot 对应专家根据公开 messages 和自身 stance 决定是否参与。只生成公开参与决策，不生成发言或推理。
PASS=暂不发言，REQUEST=举手提出新观点，INTERRUPT=抢答纠正重要问题，SUPPLEMENT=补充已有具体观点，REBUT=反驳已有具体观点。没有新的具体内容时选择 PASS。补充、反驳必须 target_turn 引用别人已提交的相关发言，不能回应自己的发言；PASS 的 target_turn 必须 null。举手可 null。不要只回应主持人开场，优先回应已有专家观点。
relevance 为0–100整数，表示当前参与与话题的相关性；不要一律100。public_focus 1–140字，具体指出拟补充/反驳的公开问题，不含隐藏思考。
{"kind":"REBUT","target_turn":2,"relevance":85,"public_focus":"回应第二条提出的执行成本估计"}
