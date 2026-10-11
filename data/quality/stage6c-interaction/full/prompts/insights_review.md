kind仅允许consensus或disagreement。
整批复核candidate.items（本次草稿及上一版候选）；每个输入候选明确提供index，输出按该index恰好一次（不是消息turn，不自行重编号），不新增候选。messages是本次完整公开前缀，主持只作语境，来源只能专家发言。直接筛选最小可靠主张，不穷举潜在组合。

共识至少两位专家明确支持同一对象/范围/兼容条件的同一最小主张，未反对或“补充”字样不能代替支持。候选若包含P且Q，仅Q有双方直接支持，就把content收窄到Q而非整项删除；不要求双方认可P或整套方案。尤其“除Q之外还需Y”已经明确认可Q，Y只属单方补充。单方细节/阈值先删去，保留有证据的共同部分；没有交集才删除。分歧是同对象的互斥判断，不凭反对词判定，已澄清误读不保留。最新撤回/不相容条件变化须更新；旧主张没有反证、草稿遗漏不构成消失。

同义项合并：最清晰项为leader，merge_with列其他index；leader可使用该组source_turns并集，其他项explicit_positions=false且merge_with=[]。每index只属一组，kind不能混合；相同来源但不同主张/条件不能自动合并。不要把单方条件扩成全组条件。
source_turns仅取原候选或合并组的来源。evidence每来源一条该消息连续片段，优先100字内，可重新截取但不可拼接；对应最终content，数值/条件必须各支持者明确认可。content只含实际支持者、最小主张、必要共同条件和建议属性，目标120字内。不能给未发言角色归属。

checks针对修正后的结果：authors_correct作者正确；same_object同对象；compatible_scope范围/条件兼容（分歧是真互斥）；every_condition_supported每个条件有双方来源；explicit_positions有明确支持/互斥立场；proposal_preserved提案不是事实；not_superseded未撤回/改变。任一false删除该项，false可空content/source_turns/evidence，不跳过index；无证据允许全空。
只输出JSON：{"reviews":[{"index":0,"merge_with":[],"kind":"consensus","content":"实际作者共同建议的最小主张","source_turns":[2,4],"evidence":[{"turn":2,"quote":"实际连续原文"},{"turn":4,"quote":"实际连续原文"}],"checks":{"authors_correct":true,"same_object":true,"compatible_scope":true,"every_condition_supported":true,"explicit_positions":true,"proposal_preserved":true,"not_superseded":true}}]}

区分可能性与保障/充分性：“X可以包含Y”与“尚未保证Y/仅有X还不够”可以同时成立，不自动互斥；只有双方确实对同一必要性、充分性或选择作出相反判断才列分歧。回应者把对方说法升级为“已经保障/充分”的归因，不证明原作者说过升级后的结论。此时指出尚未回答的保障条件，或已澄清误读，不伪造正反立场。
