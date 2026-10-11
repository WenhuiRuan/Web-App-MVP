任务：根据 topic 生成一位主持人及恰好 expert_count 位专家。姓名唯一，使用虚构中文姓名。主持人中立串联；专家职业、利益视角与立场应贴合该话题且有实质区分，不是同一观点更换姓名。每个立场简洁地指出支持/担忧及理由或条件；不假称真实名人的观点。name 1–40字，title 1–80字，stance 1–300字。
仅返回以下 JSON 结构，participants 的第一位为 HOST，其余为 EXPERT：
{"participants":[{"kind":"HOST","name":"陈序","title":"圆桌主持人","stance":"澄清问题与证据"},{"kind":"EXPERT","name":"林禾","title":"与话题相关的专业身份","stance":"具体、有区别的立场"}]}
示例人数仅说明格式，实际必须按 expert_count 生成。
