主持人复核冻结messages及输入insights，candidate是可能错误草稿。重新核对人物、范围、条件、提案性质，不输出推理/评语。返回下述JSON材料，后台组装自然语言。

introduction一两句概括议题和实际进展，最多180字，目标50–80字。不新增事实或全体认可结论。
consensus_indices/disagreement_indices只能选择输入insights对应kind的index，逐一回到原文核对同一主张/对象/条件。多位支持仍是共同建议。原文“A还是B”不表示“A与B并记”；某人错误指认另一人支持，也不证明另一人实际支持。同一主张不能又说共同认可又说无人表态。不新增观点，缺充分证据选空。

输入观点已经本边界独立复核，来源真实且仍成立的项应全部选入对应indices，不因省字、重提遗漏或不同条件而将有效共同主张说成不存在。后台要求覆盖输入全部index，以避免现场有共识而总结无共识。若原文确不能支持某项，不要盲目选入；遗漏会使总结有限失败并保留原消息/观点供复核，不可用不实正文完成讨论。

positions是共识/分歧之外的关键个人建议或观点，最多3项，通常1–2项；每个content优先40–80字、最多160字，必须是对应speaker_slot实际作者source_turns中一条消息的逐字连续片段，不能改写/拼接。保留条件关联词。共同部分集中写共识即可，不必再摘录每位支持者，不逐角色重排Transcript。

pending最多2项且可以[]。只保留本场明确提出且后来没有解决的关键问题，或原话明确承认未验证且影响判断的关键条件。每项turn/quote须为原文连续片段。不能把个人建议或“需要资料”陈述自动标成追问；无需重复列出全部提案，不与positions重复摘录。
issue定义：UNANSWERED_QUESTION仅实际问句（有?或？或明确“是否/由谁/哪张/还是”等疑问表达）且尚未回答；UNVERIFIED_PROPOSAL仅原文明确说没有验证的关键条件；SCOPE_UNCLEAR仅原讨论真实提出而未明确的范围；UNIT_OR_DIRECTION_UNCLEAR仅实际规则存在尚未澄清的单位/方向疑点。普通明确建议属于positions，不必pending。量纲不同不能认证为正确公式。没有真实待澄清问题就返回[]，不用凑栏目。

目标全文250–450字，优先短引文、单项主张；不要重复源消息或输出JSON正文给用户。格式：
{"introduction":"本场比较……，执行细则尚未确定。","positions":[{"speaker_slot":1,"source_turns":[2],"content":"该专家原消息短片段"}],"consensus_indices":[],"disagreement_indices":[],"pending":[{"turn":4,"quote":"原文实际尚未回答的问题？","issue":"UNANSWERED_QUESTION"}]}
字段名称严格使用issue（不能写reason或省略issue），pending为空时用[]。所有对象不增加额外字段。不要以“尚未判断/需要先看记录”等无问号陈述充当UNANSWERED_QUESTION；此时可放positions或省略，不要为了凑问题使用别的错误标签。
