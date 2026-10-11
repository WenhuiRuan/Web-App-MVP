本次批量复核先比较所有候选的主张和谓词，再核对引用。只把同一对象、同一动作、兼容适用条件视为共同主张；“纳入约定/记录指标”与“应改变该指标”不能互换。
kind仅允许consensus或disagreement。
整批复核candidate.items（本次草稿及上一版候选）；每个输入候选明确提供index，输出按该index恰好一次（不是消息turn，不自行重编号），不新增候选。messages是本次完整公开前缀，主持只作语境，来源只能专家发言。直接筛选最小可靠主张，不穷举潜在组合。

共识至少两位专家明确支持同一对象/范围/兼容条件的同一最小主张，未反对或“补充”字样不能代替支持。候选若包含P且Q，仅Q有双方直接支持，就把content收窄到Q而非整项删除；不要求双方认可P或整套方案。尤其“除Q之外还需Y”已经明确认可Q，Y只属单方补充。单方细节/阈值先删去，保留有证据的共同部分；没有交集才删除。分歧是同对象的互斥判断，不凭反对词判定，已澄清误读不保留。最新撤回/不相容条件变化须更新；旧主张没有反证、草稿遗漏不构成消失。

同义项合并：最清晰项为leader，merge_with列其他index；leader可使用该组source_turns并集，其他项explicit_positions=false且merge_with=[]。每index只属一组，kind不能混合；相同来源但不同主张/条件不能自动合并。不要把单方条件扩成全组条件。
source_turns仅取原候选或合并组的来源。evidence每来源一条该消息连续片段，优先100字内，可重新截取但不可拼接；对应最终content。共识数值/共同条件须各支持者明确认可；分歧则每方来源支持自己的判断及条件，不要求双方共同支持每个条件或两种相反判断。content含实际作者、最小主张、各自必要条件及建议属性，目标120字内。不能给未发言角色归属。

checks针对修正后的结果：authors_correct作者正确；same_object同对象；compatible_scope处于同一可比较范围（不同对象/前提不能强造互斥）；explicit_positions有明确立场；proposal_preserved提案不是事实；not_superseded在本次完整前缀内未撤回/澄清化解。这六项均须true。共识另要求every_condition_supported=true，表示每个共同条件有双方支持。分歧另要求opposing_judgments_supported=true，表示至少两位作者的来源分别直接支持各自不相容的判断和各自条件；every_condition_supported可以false，不能因双方没有共同支持两种相反主张而删除分歧。共识可省略opposing_judgments_supported。任一适用检查不成立删除该项，可空content/source_turns/evidence但不跳过index；无证据允许全空。
只输出JSON：{"reviews":[{"index":0,"merge_with":[],"kind":"consensus","content":"实际作者共同建议的最小主张","source_turns":[2,4],"evidence":[{"turn":2,"quote":"实际连续原文"},{"turn":4,"quote":"实际连续原文"}],"checks":{"authors_correct":true,"same_object":true,"compatible_scope":true,"every_condition_supported":true,"explicit_positions":true,"proposal_preserved":true,"not_superseded":true}}]}

区分可能性与保障/充分性：“X可以包含Y”与“尚未保证Y/仅有X还不够”可以同时成立，不自动互斥；只有双方确实对同一必要性、充分性或选择作出相反判断才列分歧。回应者把对方说法升级为“已经保障/充分”的归因，不证明原作者说过升级后的结论。此时指出尚未回答的保障条件，或已澄清误读，不伪造正反立场。

共识一项只保留一个能逐字溯源的共同主张；不要用“位置/密度”“A或B”等把不同对象包装为同一共识。上位概括若只是已列主张的重复部分、没有新的共同条件，不另列一项。复合候选拆到最关键的共同动作，其余独立主张只有确有不同内容才另列；合并时保留来源、实际支持者和共同条件，不能从一般认同推到整套细节。相同来源不是合并依据，不同来源也可以明确支持同一动作。

去重按主张而不是支持者名单：支持者更多本身不构成一个新主张。若一条上位概括只是其他具体主张重复的公共部分，且缺少相同动作与条件的直接来源，删除上位项；不要把纳入约定泛化为调整、把局部条件泛化为普遍要求。对复合项先收窄到独有且有共同来源的关键动作，再判断保留，不把不同动作合成一个宽泛方向以绕过去重。

分歧复核示例：甲“应把夜间噪声纳入综合污染考核”，乙“应单列，不应纳入综合污染考核”，在两人尚未撤回时保留，source_turns/evidence分别引用甲的“纳入”和乙的“不纳入”，checks.every_condition_supported=false、opposing_judgments_supported=true，其余六项true。不能拿“双方都没有支持整个条件”为由删去相反立场。若边界内甲后来明确接受单列，not_superseded=false，旧分歧删除；甲保留别的条件时只消除已接受的部分。普通新增关注点/未回答问题opposing_judgments_supported=false，不列分歧。共识与不同主张的分歧可以共存，逐项独立核对。
