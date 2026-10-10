本次复核最终总结。candidate是不可信总结草稿，请独立回到冻结的messages核对，纠正人物、对象、范围、条件及提案性质。不要复用错误结论。返回下述结构化正文材料，后端组装可读自然语言；不输出评语或推理过程。

introduction简述本场议题与讨论结果，不新增共识、数值、人物判断或未讨论事实。
positions最多6项，选择各专家最关键的观点原句/连续片段，每项优先不超过200字，避免复制整个Transcript。speaker_slot必须是该专家实际slot，source_turns必须是该专家的实际发言序号，content必须逐字复制其中一条源消息的连续片段（不可改写、拼接、加标点或修正词语）。保留“或”“且”“若”等原条件关联词，不能把单方备选条件改成共同要求。正文不用重新标作者，后端绑定姓名并以“提出”呈现原文精选，另用introduction与pending完成简短综合。无实际观点的人可省略。引用自身仍可能有错误，不认证为现实事实。

consensus_indices仅选择输入insights中kind=consensus且经messages再次核对仍支持的index；不能新增共识或改写结论。证据不足选空数组，后端显示尚无充分共识。后台原样呈现被选择观点，因此不要一面选中一项完整规则、一面又在其他段落判它未确认或相反；遇到这种情况不选它，待澄清段解释条件疑点。
disagreement_indices仅选择输入kind=disagreement且同一对象/范围的相反主张有证据的index。没有已确认两方分歧选空，不把主持提问或单方没有回应当分歧。
pending改为0–3项公开来源片段数组，每项turn与quote必须对应本场原文中的连续片段（不能改写、拼接或增添归纳）。只选择已经提出、确实仍需核对的追问/条件，已明确回应的方向不要当作未表态。不要自行列未提过的新问题。每项issue选择UNANSWERED_QUESTION（追问待核对）、UNVERIFIED_PROPOSAL（提案待验证）、SCOPE_UNCLEAR（范围或前提待核对）、UNIT_OR_DIRECTION_UNCLEAR（单位或方向待核对）。后台绑定实际作者和有限标签，不能在本段新增共识、分歧或将不同对象合并成冲突。单方建议未回应只是待核对，执行细则未决定不代表方向未回答。不同指标的分母、不同对象的处理可并存。没有明确待核对内容可返回[]。

检查执行规则的逻辑与量纲：比例、费用、人数、时长等不同单位不能直接相加或无换算地比较；多个指标的变好/变坏方向不能统一假定。有此类疑点时在pending选择有问题的原规则片段，issue=UNIT_OR_DIRECTION_UNCLEAR，不认证规则，也不推导新公式。不要将“尚未取得基线”夸大成现实中肯定没有基线，保持发言者主张属性。
全文通常300–600字，不逐条复制Transcript。不输出检验过程、Markdown或字面反斜杠n。严格JSON格式：
{"introduction":"本场围绕……展开，尚未确定整体方案。","positions":[{"speaker_slot":1,"source_turns":[2],"content":"输入第2条内逐字复制的公开片段"}],"consensus_indices":[],"disagreement_indices":[],"pending":[{"turn":4,"quote":"输入第4条内逐字复制的公开片段","issue":"UNANSWERED_QUESTION"}]}
