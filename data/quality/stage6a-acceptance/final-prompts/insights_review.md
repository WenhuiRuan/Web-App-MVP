复核candidate.items（本次草稿及上一版观点）。每个index恰好一次，不能增添候选。返回reviews，不返回items，不输出推理或评语。

每次只复核一项；messages是该项来源及其作者后续公开发言，后续仅用于检查撤回/变化，不能追加为source_turns。原kind可能误分类，最终kind应为consensus或disagreement：若原分歧实际只有共同建议/补充，收窄到有来源的共同部分并改consensus；没有双方共同或互斥主张则explicit_positions=false。引用双方不同条件的段落，不等于同一主张，不要把两段个人建议并排叫共识。

先从该项source_turns实际专家发言找双方明确认可的同一最小主张。单方条件、目的、阈值须从content删去，优先收窄，不能因附加条件有问题就删除有充分来源的共同部分。“共同采用指标及用途”等直接陈述是支持，不要求固定“同意”用语。不能把两条各自不同的建议并排抄写后叫共识。
source_turns只能保留或缩小。evidence重新选原来源消息连续片段，每个来源一条，优先不超过100字，必须覆盖最终content；不受草稿截句限制，不能换来源或拼接。所有数量/条件要在每位支持者引用中出现，不然删去该条件。询问“A还是B”不支持“同时A与B”；声称“接受某人方案”的发言，须检查被回应者确实说过同一方案，否则不能把被回应者也列支持者。

候选可能重复同一主张，只保留最清晰且来源充分的一项，其余explicit_positions=false。
checks针对收窄后的content：
- authors_correct：归属仅限实际来源作者。
- same_object：同一讨论对象或指标。
- compatible_scope：同一适用范围/前提，共识兼容，分歧确实互斥。
- every_condition_supported：每个条件分别有双方明确证据，单方条件已剔除。
- explicit_positions：共识有至少两位专家明确支持同一主张；分歧是同一选择的明确相反立场。沉默、未接受、另补前提不是反对。
- proposal_preserved：建议仍是共同提案，不是全体决定或已验证事实。
- not_superseded：核对全部messages，特别是previous_through_turn后的发言，旧主张未被作者撤回/不相容条件变化/反对。没有反证且原来源充分应保留；本次草稿遗漏或无人再提不构成消失。改变条件时删除不再成立旧主张，核对新候选。
作者明确撤回整个共同建议时，not_superseded=false，不从旧句截出一个未被重新认可的子主张来保留。仅当最新发言明确重新支持某个子主张时，才可与另一作者的实际支持取更小交集；不要把“未明确撤回细节”当成最新支持。
任一false后台删除。content至多120字，一项只写最小主张、支持者、共同条件及提案属性，不重复个人细节。不充分允许删除全部候选。
若双方只认同指标名称，不能附加一方的连续周期、暂停关系或方向条件，删去这些单方条件并留下名称交集；不要将原候选数值照抄进content。false项可返回空content和source_turns/evidence空数组，不跳过index。重复相同主张只保留一项。
只输出JSON：
{"reviews":[{"index":0,"kind":"consensus","source_turns":[2,4],"evidence":[{"turn":2,"quote":"实际来源连续片段"},{"turn":4,"quote":"实际来源连续片段"}],"checks":{"authors_correct":true,"same_object":true,"compatible_scope":true,"every_condition_supported":true,"explicit_positions":true,"proposal_preserved":true,"not_superseded":true},"content":"双方共同建议的最小交集，仍为提案。"}]}
