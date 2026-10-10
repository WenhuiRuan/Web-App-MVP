本次执行观点的公开证据复核，不是重新提取议程。candidate是可能错误的草稿，不要为其找解释。逐项独立核对，输出格式改为reviews，不再返回items，不输出评语或推理过程。

对candidate.items按0开始的index逐项审核，每项恰好一次。只能使用该项source_turns对应的专家发言。可将content收窄为原来源明确支持的交集，source_turns只能保留或缩小，不能换作者、加来源或增添新候选。无充分支持的项删除（任一checks=false），不为了保留候选而猜测。

checks是对最终content的公开证据判断，全部true后台才保留：
- authors_correct：人物归属与来源作者对应。
- same_object：讨论同一种数据、同一指标、同一实施对象，而不只是措辞相似。
- compatible_scope：人群、范围、前提确实相同或明确互斥；分别适用于不同对象的口径可以并存。
- every_condition_supported：content每个数值、规则、限定词均分别有直接证据，不把单方条件归给另一方。
- explicit_positions：共识由至少两位专家明确支持同一主张，分歧由双方明确表达同一问题的互斥主张；沉默、补充细节、一般方向认同不算对完整方案认同。
- proposal_preserved：建议仍是提案、未知事实仍待核实，不认证为执行决策。

原引用真实但不能支持content时，false或收窄，不能另找一组来源。“同意选择某指标”不表示同意它的连续周期、数值门槛或暂停规则；这些条件未在每位支持者的引用中明确出现，必须从content删去，否则false。后台会保守检查共识中的常见带单位数量是否在所有保留quote中逐字出现（不同数字写法不会自动换算）；不要依靠“同意指标”补全量化条件。不同指标的分母不能当作同一指标的冲突。只输出JSON，格式：
{"reviews":[{"index":0,"source_turns":[2,4],"checks":{"authors_correct":true,"same_object":true,"compatible_scope":true,"every_condition_supported":false,"explicit_positions":false,"proposal_preserved":true},"content":"原候选或可核对的收窄表述"}]}
无候选返回{"reviews":[]}。这不是内心推理，只是公开来源校验结论。共同主张中的复合目的或备选项也逐项核对：双方只明确支持A，只有一方谈B时，不能写双方支持“A或B”，必须删B；不能靠扩展抽象含义补出共同用途。

特别核对分歧是否建立在缺席或沉默上：如果理由是“未支持”“未认可”“没有回答”，而来源没有明确拒绝对方主张或提出同一选择上互斥的方案，explicit_positions必须false。提出另一项补充前提、尚未接受对方条件，不等于反对。不能把甲主张X、乙补充Y自动解释为只能二选一。该项删除后，尚未回复的问题由总结保留为待澄清。
