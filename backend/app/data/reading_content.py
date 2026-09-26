"""平台六篇阅读材料的内置逐句讲解。

这些文章是站内固定内容，不依赖模型也应能直接精读，所以讲解随文章
一起写死在仓库里：重点单词、固定搭配、语法与整句翻译。seed 时按标题
写入 ArticleAnalysis.sentences_json，用户打开即命中缓存，模型不可用
也不影响体验。

结构与 reading_service.analyze_document 的产出保持一致，每句：
- translation 整句中文
- words       (word, lemma, part_of_speech, meaning)
- phrases     (phrase, meaning)
- grammar     (point, explanation, example)

句子顺序必须与 reading_service.split_sentences 切出的结果一一对应，
tests/test_reading_content.py 会逐句校验。
"""


def build_sentences(
    title: str, splits: list[tuple[int, str]]
) -> list[dict] | None:
    """把内置讲解拼成 sentences_json 的结构；这篇没有内置数据时返回 None。

    splits 是 reading_service.split_sentences 的结果：正文以实际切句为准，
    这里只负责挂上讲解，顺序与 READING_CONTENT 里的条目一一对应。
    条数与句子数对不上说明文章被改过，返回 None 让调用方回退到模型，
    免得把讲解错位地贴到别的句子上。
    """
    rows = READING_CONTENT.get(title)
    if not rows or len(rows) != len(splits):
        return None

    sentences: list[dict] = []
    for index, ((paragraph, text), row) in enumerate(zip(splits, rows)):
        sentences.append(
            {
                "index": index,
                "paragraph": paragraph,
                "text": text,
                "translation": row.get("translation", ""),
                "main_clause": "",
                "words": [
                    {
                        "word": word,
                        "lemma": lemma,
                        "meaning": meaning,
                        "phonetic": "",
                        "part_of_speech": part_of_speech,
                    }
                    for word, lemma, part_of_speech, meaning in row.get("words", [])
                ],
                "phrases": [
                    {"phrase": phrase, "meaning": meaning, "example": ""}
                    for phrase, meaning in row.get("phrases", [])
                ],
                "grammar": [
                    {"point": point, "explanation": explanation, "example": example}
                    for point, explanation, example in row.get("grammar", [])
                ],
                "explanation": "",
            }
        )
    return sentences


READING_CONTENT: dict[str, list[dict]] = {
    "AI Is Changing How Students Learn": [
        {
            "translation": "人工智能的快速发展已经显著改变了学生的学习方式。",
            "words": [
                ("development", "development", "n.", "发展；进展"),
                ("rapid", "rapid", "adj.", "迅速的；快速的"),
                ("significantly", "significantly", "adv.", "显著地；明显地"),
                ("change", "change", "v.", "改变；使不同"),
                ("way", "way", "n.", "方式；方法"),
            ],
            "phrases": [
                ("rapid development", "快速发展；迅速发展"),
                ("artificial intelligence", "人工智能"),
                ("change the way", "改变……的方式"),
                ("the development of", "……的发展"),
            ],
            "grammar": [
                (
                    "现在完成时 has changed",
                    "现在完成时表示过去发生并对现在有影响的动作。这里强调人工智能的发展已经改变了学生的学习方式，而且这种影响现在仍然存在。",
                    "The rapid development of artificial intelligence has significantly changed the way students learn.",
                ),
                (
                    "the way + 从句",
                    "the way 后面可以直接跟一个从句，相当于 the way in which/that...，表示“……的方式”。这里 students learn 修饰 the way。",
                    "the way students learn",
                ),
                (
                    "of 短语作后置定语",
                    "of artificial intelligence 放在 development 后面，说明是哪方面的发展，相当于“人工智能的发展”。",
                    "the development of artificial intelligence",
                ),
            ],
        },
        {
            "translation": "现在，学习者不必像其他人一样做同样的练习，而是可以使用能适应自己水平的工具来练习。",
            "words": [
                ("practise", "practise", "v.", "练习"),
                ("adapt", "adapt", "v.", "适应"),
                ("exercise", "exercise", "n.", "练习；习题"),
                ("learner", "learner", "n.", "学习者"),
            ],
            "phrases": [
                ("instead of", "代替；而不是"),
                ("adapt to", "适应……"),
                ("work through", "完成；逐一处理"),
                ("the same ... as", "和……一样"),
            ],
            "grammar": [
                (
                    "介词短语作状语",
                    "Instead of working through ... 放在句首，表示“不做某事，而是……”。instead of 后面接动名词 working。",
                    "Instead of working through the same exercises as everyone else",
                ),
                (
                    "定语从句 that adapt to their level",
                    "that 引导定语从句修饰 tools，说明是“能适应自己水平的”工具。",
                    "tools that adapt to their level",
                ),
                (
                    "情态动词 can",
                    "can now practise 表示现在有能力、有条件这样做。",
                    "learners can now practise",
                ),
            ],
        },
        {
            "translation": "这些系统会分析错误，并调整下一个任务的难度。",
            "words": [
                ("analyse", "analyse", "v.", "分析"),
                ("adjust", "adjust", "v.", "调整"),
                ("difficulty", "difficulty", "n.", "难度；困难"),
                ("system", "system", "n.", "系统"),
                ("mistake", "mistake", "n.", "错误"),
            ],
            "phrases": [
                ("the difficulty of", "……的难度"),
                ("the next task", "下一个任务"),
            ],
            "grammar": [
                (
                    "并列谓语",
                    "analyse mistakes 与 adjust the difficulty 由 and 连接，共用一个主语 These systems。",
                    "These systems analyse mistakes and adjust the difficulty of the next task.",
                ),
                (
                    "of 短语作后置定语",
                    "of the next task 修饰 difficulty，说明是“下一个任务的”难度。",
                    "the difficulty of the next task",
                ),
            ],
        },
        {
            "translation": "结果，学生把更多时间花在他们真正需要的材料上。",
            "words": [
                ("material", "material", "n.", "材料；素材"),
                ("actually", "actually", "adv.", "实际上；真正地"),
                ("result", "result", "n.", "结果"),
            ],
            "phrases": [
                ("as a result", "结果；因此"),
                ("spend time on", "在……上花时间"),
            ],
            "grammar": [
                (
                    "定语从句省略关系代词",
                    "the material they actually need 中，关系代词 that/which 作 need 的宾语被省略。",
                    "the material they actually need",
                ),
                (
                    "as a result 作连接性状语",
                    "As a result 放在句首，承接上文说明结果。",
                    "As a result, students spend more time on the material they actually need.",
                ),
            ],
        },
        {
            "translation": "然而，研究者提醒说，适应性工具无法取代对话。",
            "words": [
                ("researcher", "researcher", "n.", "研究者"),
                ("warn", "warn", "v.", "提醒；警告"),
                ("replace", "replace", "v.", "取代；代替"),
                ("adaptive", "adaptive", "adj.", "适应性的"),
                ("conversation", "conversation", "n.", "对话；交谈"),
            ],
            "phrases": [
                ("warn that", "提醒说……"),
                ("replace ... with", "用……取代"),
            ],
            "grammar": [
                (
                    "宾语从句 that ...",
                    "warn 后面接 that 引导的宾语从句，说明提醒的内容。",
                    "researchers warn that adaptive tools cannot replace conversation",
                ),
                (
                    "情态动词 cannot",
                    "cannot replace 表示“无法取代”，语气明确。",
                    "adaptive tools cannot replace conversation",
                ),
            ],
        },
        {
            "translation": "语言学习者仍然需要和真人交流来建立自信。",
            "words": [
                ("confidence", "confidence", "n.", "自信；信心"),
                ("build", "build", "v.", "建立；培养"),
                ("learner", "learner", "n.", "学习者"),
            ],
            "phrases": [
                ("build confidence", "建立自信"),
                ("speak with", "和……交谈"),
            ],
            "grammar": [
                (
                    "不定式作目的状语",
                    "to build confidence 说明“和真人交流”的目的。",
                    "to build confidence",
                ),
                (
                    "still 的位置",
                    "still 放在实义动词 need 之前，表示“仍然需要”。",
                    "Language learners still need to speak with real people",
                ),
            ],
        },
        {
            "translation": "最有效的方法是把个性化练习与实时互动结合起来。",
            "words": [
                ("effective", "effective", "adj.", "有效的"),
                ("approach", "approach", "n.", "方法；途径"),
                ("combine", "combine", "v.", "结合；把……结合起来"),
                ("interaction", "interaction", "n.", "互动；交流"),
                ("personalised", "personalised", "adj.", "个性化的"),
            ],
            "phrases": [
                ("combine A with B", "把 A 与 B 结合起来"),
                ("live interaction", "实时互动"),
            ],
            "grammar": [
                (
                    "最高级 the most effective",
                    "多音节形容词的最高级用 the most + 形容词，表示“最……的”。",
                    "The most effective approach",
                ),
                (
                    "combine A with B",
                    "combines personalised practice with live interaction 是“把个性化练习与实时互动结合起来”的固定结构。",
                    "combines personalised practice with live interaction",
                ),
            ],
        },
    ],
    "Why Remote Teams Still Struggle to Communicate": [
        {
            "translation": "远程办公承诺了灵活性，但许多分布式团队仍然难以有效沟通。",
            "words": [
                ("flexibility", "flexibility", "n.", "灵活性"),
                ("distributed", "distributed", "adj.", "分布式的"),
                ("struggle", "struggle", "v.", "挣扎；努力；艰难地做"),
                ("effectively", "effectively", "adv.", "有效地"),
                ("remote", "remote", "adj.", "远程的"),
            ],
            "phrases": [
                ("struggle to", "努力做……；难以……"),
                ("communicate effectively", "有效沟通"),
            ],
            "grammar": [
                (
                    "并列句 yet",
                    "yet 连接两个分句，表示转折，相当于 but。",
                    "Remote work promised flexibility, yet many distributed teams still struggle",
                ),
                (
                    "不定式作宾语",
                    "struggle to communicate 中，不定式说明努力/难以做到的事。",
                    "struggle to communicate effectively",
                ),
            ],
        },
        {
            "translation": "问题很少出在软件上。",
            "words": [
                ("rarely", "rarely", "adv.", "很少；难得"),
                ("software", "software", "n.", "软件"),
                ("problem", "problem", "n.", "问题"),
            ],
            "phrases": [],
            "grammar": [
                (
                    "副词 rarely 的位置",
                    "rarely 这类否定副词通常放在 be 动词之后、实义动词之前。",
                    "The problem is rarely the software.",
                ),
                (
                    "主系表结构",
                    "The problem is the software 是主系表结构，rarely 修饰整个判断。",
                    "The problem is rarely the software.",
                ),
            ],
        },
        {
            "translation": "问题在于缺少过去常在会议间隙发生的非正式交谈。",
            "words": [
                ("absence", "absence", "n.", "缺失；不存在"),
                ("informal", "informal", "adj.", "非正式的"),
                ("conversation", "conversation", "n.", "交谈；对话"),
                ("meeting", "meeting", "n.", "会议"),
            ],
            "phrases": [
                ("the absence of", "缺少……"),
                ("used to", "过去常常"),
            ],
            "grammar": [
                (
                    "强调句 It is ... that ...",
                    "It is the absence of informal conversation that ... 是强调句，强调“问题在于缺少非正式交谈”。",
                    "It is the absence of informal conversation that used to happen between meetings.",
                ),
                (
                    "used to do",
                    "used to happen 表示“过去常常发生”，暗示现在不再如此。",
                    "used to happen between meetings",
                ),
            ],
        },
        {
            "translation": "写得清楚、并把决定记录下来的团队往往表现更好。",
            "words": [
                ("document", "document", "v.", "记录；存档"),
                ("decision", "decision", "n.", "决定"),
                ("perform", "perform", "v.", "表现；执行"),
                ("tend", "tend", "v.", "往往；倾向于"),
            ],
            "phrases": [
                ("tend to", "倾向于；往往会"),
                ("perform better", "表现更好"),
            ],
            "grammar": [
                (
                    "定语从句 that write ... and document ...",
                    "that 引导定语从句修饰 Teams，从句里 write 与 document 并列。",
                    "Teams that write clearly and document decisions",
                ),
                (
                    "tend to do",
                    "tend to perform better 表示“往往表现更好”。",
                    "tend to perform better",
                ),
            ],
        },
        {
            "translation": "管理者在确立这些规范中起着重要作用。",
            "words": [
                ("manager", "manager", "n.", "管理者；经理"),
                ("role", "role", "n.", "角色；作用"),
                ("norm", "norm", "n.", "规范；准则"),
                ("set", "set", "v.", "确立；设定"),
            ],
            "phrases": [
                ("play an important role in", "在……中起重要作用"),
                ("set norms", "确立规范"),
            ],
            "grammar": [
                (
                    "play a role in + 动名词",
                    "in 是介词，后面接动名词 setting。",
                    "play an important role in setting these norms",
                ),
                (
                    "these 的指代",
                    "these norms 指上文提到的清晰写作、记录决定等做法。",
                    "these norms",
                ),
            ],
        },
        {
            "translation": "如果没有刻意的努力，信息会滞留在私人聊天里，新成员就会被落下。",
            "words": [
                ("deliberate", "deliberate", "adj.", "刻意的；有意的"),
                ("effort", "effort", "n.", "努力"),
                ("private", "private", "adj.", "私人的；私下的"),
                ("chat", "chat", "n.", "聊天；闲聊"),
                ("member", "member", "n.", "成员"),
            ],
            "phrases": [
                ("leave behind", "把……落下；使落后"),
                ("without effort", "不费力气；不加努力"),
            ],
            "grammar": [
                (
                    "介词短语表条件",
                    "Without deliberate effort 相当于 if there is no deliberate effort，表示条件。",
                    "Without deliberate effort",
                ),
                (
                    "被动语态 are left behind",
                    "new members are left behind 是被动语态，强调新成员“被落下”。",
                    "new members are left behind",
                ),
            ],
        },
    ],
    "The Quiet Rise of Urban Gardening": [
        {
            "translation": "城市园艺在大城市里变得越来越流行。",
            "words": [
                ("urban", "urban", "adj.", "城市的"),
                ("gardening", "gardening", "n.", "园艺"),
                ("increasingly", "increasingly", "adv.", "越来越；日益"),
                ("popular", "popular", "adj.", "流行的；受欢迎的"),
            ],
            "phrases": [
                ("become popular", "变得流行"),
                ("urban gardening", "城市园艺"),
            ],
            "grammar": [
                (
                    "现在完成时 has become",
                    "has become 强调从过去持续到现在的变化结果。",
                    "Urban gardening has become increasingly popular in large cities.",
                ),
                (
                    "副词修饰形容词",
                    "increasingly 修饰 popular，表示“越来越流行”。",
                    "increasingly popular",
                ),
            ],
        },
        {
            "translation": "居民在屋顶、阳台以及共享的社区地块上种植蔬菜。",
            "words": [
                ("resident", "resident", "n.", "居民"),
                ("vegetable", "vegetable", "n.", "蔬菜"),
                ("rooftop", "rooftop", "n.", "屋顶"),
                ("balconies", "balcony", "n.", "阳台"),
                ("plot", "plot", "n.", "小块土地；地块"),
            ],
            "phrases": [
                ("grow vegetables", "种菜；种植蔬菜"),
                ("community plot", "社区地块"),
            ],
            "grammar": [
                (
                    "并列介词短语",
                    "on rooftops, balconies, and in shared community plots 并列了多个地点状语，注意最后一个并列项前换用了介词 in。",
                    "on rooftops, balconies, and in shared community plots",
                ),
                (
                    "一般现在时",
                    "grow 用一般现在时，陈述普遍做法。",
                    "Residents grow vegetables",
                ),
            ],
        },
        {
            "translation": "支持者说，这种做法能改善心理健康，并降低食品开销。",
            "words": [
                ("supporter", "supporter", "n.", "支持者"),
                ("practice", "practice", "n.", "做法；实践"),
                ("improve", "improve", "v.", "改善；提高"),
                ("mental", "mental", "adj.", "心理的；精神的"),
                ("reduce", "reduce", "v.", "减少；降低"),
            ],
            "phrases": [
                ("mental health", "心理健康"),
                ("reduce costs", "降低成本"),
            ],
            "grammar": [
                (
                    "宾语从句省略 that",
                    "say 后面是宾语从句，口语中常省略 that。",
                    "Supporters say the practice improves mental health",
                ),
                (
                    "并列谓语 improves ... and reduces ...",
                    "两个动词共用一个主语 the practice。",
                    "improves mental health and reduces food costs",
                ),
            ],
        },
        {
            "translation": "它还能把邻里聚在一起。",
            "words": [
                ("neighbour", "neighbour", "n.", "邻居；邻里"),
                ("bring", "bring", "v.", "带来；使来到"),
            ],
            "phrases": [
                ("bring ... together", "把……聚在一起"),
            ],
            "grammar": [
                (
                    "bring sb together",
                    "bring 后接宾语 neighbours，再接 together 表示“聚到一起”。",
                    "It also brings neighbours together.",
                ),
            ],
        },
        {
            "translation": "批评者指出，它对环境的影响有限，但参与者说，社交上的好处和收成同样重要。",
            "words": [
                ("critic", "critic", "n.", "批评者"),
                ("impact", "impact", "n.", "影响；冲击"),
                ("environment", "environment", "n.", "环境"),
                ("participant", "participant", "n.", "参与者"),
                ("benefit", "benefit", "n.", "好处；益处"),
                ("harvest", "harvest", "n.", "收成；收获"),
            ],
            "phrases": [
                ("point out", "指出"),
                ("the impact on", "对……的影响"),
                ("as much as", "和……一样多"),
            ],
            "grammar": [
                (
                    "宾语从句 that ...",
                    "point out that ... 与 say (that) ... 都是宾语从句。",
                    "Critics point out that the impact on the environment is limited",
                ),
                (
                    "并列句 but",
                    "but 连接批评者与参与者两种相反的看法。",
                    "but participants say the social benefits matter just as much as the harvest",
                ),
                (
                    "as ... as 同级比较",
                    "as much as 表示“和……一样多”。",
                    "matter just as much as the harvest",
                ),
            ],
        },
    ],
    "What Makes a Habit Stick": [
        {
            "translation": "人们常常想一次改变太多。",
            "words": [
                ("try", "try", "v.", "尝试；试图"),
                ("change", "change", "v.", "改变"),
            ],
            "phrases": [
                ("at once", "一次；同时"),
                ("too much", "太多"),
            ],
            "grammar": [
                (
                    "try to do",
                    "try to change 表示“试图改变”，不定式作宾语。",
                    "People often try to change too much at once.",
                ),
            ],
        },
        {
            "translation": "关于习惯养成的研究表明，小而重复的行动更可能坚持下去。",
            "words": [
                ("research", "research", "n.", "研究"),
                ("formation", "formation", "n.", "形成；养成"),
                ("repeated", "repeated", "adj.", "重复的"),
                ("likely", "likely", "adj.", "可能的"),
                ("action", "action", "n.", "行动；行为"),
            ],
            "phrases": [
                ("habit formation", "习惯养成"),
                ("be likely to", "可能……"),
            ],
            "grammar": [
                (
                    "宾语从句 that ...",
                    "suggests that ... 引出研究结论。",
                    "suggests that small, repeated actions are more likely to last",
                ),
                (
                    "be likely to do",
                    "are more likely to last 表示“更可能持续下去”。",
                    "are more likely to last",
                ),
            ],
        },
        {
            "translation": "每天短时间的学习比每周一次的高强度学习更有效。",
            "words": [
                ("daily", "daily", "adj.", "每天的"),
                ("session", "session", "n.", "一段时间；练习时段"),
                ("effective", "effective", "adj.", "有效的"),
                ("intense", "intense", "adj.", "高强度的；剧烈的"),
                ("weekly", "weekly", "adj.", "每周的"),
            ],
            "phrases": [
                ("more ... than", "比……更……"),
            ],
            "grammar": [
                (
                    "比较级 more effective than",
                    "多音节形容词用 more + 形容词构成比较级。",
                    "A short daily session is more effective than an intense weekly one.",
                ),
                (
                    "one 代指前面名词",
                    "weekly one 中的 one 代指 session，避免重复。",
                    "an intense weekly one",
                ),
            ],
        },
        {
            "translation": "关键在于让这个行为容易开始、难以跳过。",
            "words": [
                ("key", "key", "n.", "关键；要点"),
                ("behaviour", "behaviour", "n.", "行为；举止"),
                ("skip", "skip", "v.", "跳过；略过"),
            ],
            "phrases": [
                ("make ... easy", "使……变得容易"),
                ("the key is to", "关键在于……"),
            ],
            "grammar": [
                (
                    "不定式作表语",
                    "is to make ... 中不定式作表语，说明“关键是什么”。",
                    "The key is to make the behaviour easy to start and hard to skip.",
                ),
                (
                    "make + 宾语 + 形容词",
                    "make the behaviour easy 表示“使这个行为变得容易”，形容词作宾补。",
                    "make the behaviour easy to start and hard to skip",
                ),
            ],
        },
        {
            "translation": "随着时间推移，这个动作会变得自动化，维持起来也更省力。",
            "words": [
                ("automatic", "automatic", "adj.", "自动的；无意识的"),
                ("require", "require", "v.", "需要；要求"),
                ("effort", "effort", "n.", "努力；力气"),
                ("maintain", "maintain", "v.", "维持；保持"),
            ],
            "phrases": [
                ("over time", "随着时间推移"),
                ("require effort", "需要付出努力"),
            ],
            "grammar": [
                (
                    "系动词 become + 形容词",
                    "becomes automatic 表示状态的变化。",
                    "the action becomes automatic",
                ),
                (
                    "不定式作定语",
                    "effort to maintain 中不定式修饰 effort，说明“用来维持的力气”。",
                    "less effort to maintain",
                ),
            ],
        },
    ],
    "How Cities Are Rethinking Public Space": [
        {
            "translation": "世界各地的城市正在重新思考公共空间该如何使用。",
            "words": [
                ("rethink", "rethink", "v.", "重新思考"),
                ("public", "public", "adj.", "公共的"),
                ("space", "space", "n.", "空间"),
            ],
            "phrases": [
                ("around the world", "世界各地"),
                ("public space", "公共空间"),
            ],
            "grammar": [
                (
                    "现在进行时 are rethinking",
                    "现在进行时表示正在发生的变化。",
                    "Cities around the world are rethinking",
                ),
                (
                    "宾语从句 how ... 含被动",
                    "how public space is used 是宾语从句，从句内部是被动语态。",
                    "how public space is used",
                ),
            ],
        },
        {
            "translation": "有些城市已经把车道改造成自行车道和步行区。",
            "words": [
                ("convert", "convert", "v.", "改造；转换"),
                ("lane", "lane", "n.", "车道；小路"),
                ("path", "path", "n.", "小路；通道"),
                ("pedestrian", "pedestrian", "adj.", "行人的"),
                ("zone", "zone", "n.", "区域；地带"),
            ],
            "phrases": [
                ("convert A into B", "把 A 改造成 B"),
                ("bike path", "自行车道"),
            ],
            "grammar": [
                (
                    "现在完成时 have converted",
                    "have converted 强调改造已经完成，结果保留到现在。",
                    "Some have converted car lanes into bike paths",
                ),
                (
                    "convert ... into ...",
                    "into 引出改造后的形态。",
                    "converted car lanes into bike paths and pedestrian zones",
                ),
            ],
        },
        {
            "translation": "另一些城市则在闲置土地上建小公园。",
            "words": [
                ("creating", "create", "v.", "创建；建造"),
                ("unused", "unused", "adj.", "未被使用的；闲置的"),
                ("land", "land", "n.", "土地"),
            ],
            "phrases": [
                ("unused land", "闲置土地"),
            ],
            "grammar": [
                (
                    "现在进行时 are creating",
                    "与上一句的现在完成时形成对照，表示正在进行的做法。",
                    "Others are creating small parks on unused land.",
                ),
            ],
        },
        {
            "translation": "规划者认为，这些改变提升了安全性，也支持了本地商业。",
            "words": [
                ("planner", "planner", "n.", "规划者"),
                ("argue", "argue", "v.", "主张；认为"),
                ("safety", "safety", "n.", "安全"),
                ("support", "support", "v.", "支持"),
                ("local", "local", "adj.", "本地的；当地的"),
            ],
            "phrases": [
                ("local business", "本地商业；本地企业"),
            ],
            "grammar": [
                (
                    "宾语从句 that ...",
                    "argue that ... 引出规划者的观点。",
                    "Planners argue that these changes improve safety",
                ),
                (
                    "并列谓语 improve ... and support ...",
                    "两个动词共用一个主语 these changes。",
                    "improve safety and support local businesses",
                ),
            ],
        },
        {
            "translation": "这一转变并不总是一帆风顺，一些居民担心交通和停车问题。",
            "words": [
                ("transition", "transition", "n.", "转变；过渡"),
                ("smooth", "smooth", "adj.", "顺利的；平滑的"),
                ("resident", "resident", "n.", "居民"),
                ("worry", "worry", "v.", "担心；担忧"),
                ("traffic", "traffic", "n.", "交通"),
                ("parking", "parking", "n.", "停车"),
            ],
            "phrases": [
                ("worry about", "担心……"),
                ("not always", "并不总是"),
            ],
            "grammar": [
                (
                    "并列句 and",
                    "and 连接“转变不顺利”与“居民担心”两件事。",
                    "The transition is not always smooth, and some residents worry about traffic and parking.",
                ),
                (
                    "worry about + 名词",
                    "about 是介词，后面接名词 traffic and parking。",
                    "worry about traffic and parking",
                ),
            ],
        },
        {
            "translation": "尽管如此，方向是明确的：街道是为行人而不是汽车设计的。",
            "words": [
                ("direction", "direction", "n.", "方向"),
                ("clear", "clear", "adj.", "明确的；清楚的"),
                ("design", "design", "v.", "设计"),
                ("rather", "rather", "adv.", "而不是；相当"),
            ],
            "phrases": [
                ("rather than", "而不是"),
                ("the direction of", "……的方向"),
            ],
            "grammar": [
                (
                    "过去分词作后置定语",
                    "streets designed for people 中 designed 是过去分词，修饰 streets，相当于 which are designed for people。",
                    "streets designed for people rather than cars",
                ),
                (
                    "冒号后的同位语",
                    "冒号后面的内容解释说明 the direction of travel。",
                    "the direction of travel is clear: streets designed for people rather than cars.",
                ),
            ],
        },
    ],
    "The Art of Asking Better Questions": [
        {
            "translation": "提出好问题是一项可以学会的技能。",
            "words": [
                ("skill", "skill", "n.", "技能；技巧"),
                ("question", "question", "n.", "问题"),
            ],
            "phrases": [
                ("ask a question", "提问；问问题"),
            ],
            "grammar": [
                (
                    "动名词作主语",
                    "Asking a good question 是动名词短语作主语，谓语用单数 is。",
                    "Asking a good question is a skill",
                ),
                (
                    "定语从句 that can be learned",
                    "that 引导定语从句修饰 a skill，从句用被动语态 can be learned。",
                    "a skill that can be learned",
                ),
            ],
        },
        {
            "translation": "开放性问题引出解释，而封闭性问题确认事实。",
            "words": [
                ("open", "open", "adj.", "开放的"),
                ("invite", "invite", "v.", "引出；招致"),
                ("explanation", "explanation", "n.", "解释；说明"),
                ("confirm", "confirm", "v.", "确认；证实"),
                ("fact", "fact", "n.", "事实"),
            ],
            "phrases": [
                ("open question", "开放性问题"),
                ("closed question", "封闭性问题"),
            ],
            "grammar": [
                (
                    "while 表对比",
                    "while 连接两个分句，表示“而、然而”的对比关系。",
                    "Open questions invite explanation, while closed questions confirm facts.",
                ),
            ],
        },
        {
            "translation": "善于沟通的人会注意提问的顺序，并认真听对方的回答。",
            "words": [
                ("skilled", "skilled", "adj.", "熟练的；有技巧的"),
                ("communicator", "communicator", "n.", "沟通者"),
                ("order", "order", "n.", "顺序；次序"),
                ("carefully", "carefully", "adv.", "认真地；仔细地"),
            ],
            "phrases": [
                ("pay attention to", "注意……"),
                ("listen to", "听……"),
            ],
            "grammar": [
                (
                    "并列谓语 pay ... and listen ...",
                    "两个动词共用一个主语 Skilled communicators。",
                    "pay attention to the order of their questions and listen carefully to the answers",
                ),
                (
                    "pay attention to + 名词",
                    "to 是介词，后面接名词短语 the order of their questions。",
                    "pay attention to the order of their questions",
                ),
            ],
        },
        {
            "translation": "在面试和会议中，问题的质量常常比答案本身更能说明问题。",
            "words": [
                ("interview", "interview", "n.", "面试；采访"),
                ("meeting", "meeting", "n.", "会议"),
                ("quality", "quality", "n.", "质量；品质"),
                ("reveal", "reveal", "v.", "揭示；显露"),
            ],
            "phrases": [
                ("more than", "比……更；不只是"),
                ("the quality of", "……的质量"),
            ],
            "grammar": [
                (
                    "比较级 more than",
                    "reveals more than the answer itself 表示“比答案本身透露得更多”。",
                    "reveals more than the answer itself",
                ),
                (
                    "介词短语作状语",
                    "In interviews and meetings 放在句首作地点/场合状语。",
                    "In interviews and meetings",
                ),
            ],
        },
        {
            "translation": "练习这项技能能同时提升对话能力和批判性思维。",
            "words": [
                ("practising", "practise", "v.", "练习"),
                ("improve", "improve", "v.", "提升；改善"),
                ("critical", "critical", "adj.", "批判性的"),
                ("thinking", "thinking", "n.", "思维；思考"),
            ],
            "phrases": [
                ("critical thinking", "批判性思维"),
                ("both ... and ...", "既……又……"),
            ],
            "grammar": [
                (
                    "动名词作主语",
                    "Practising this skill 是动名词短语作主语。",
                    "Practising this skill improves both conversation and critical thinking.",
                ),
                (
                    "both ... and ... 并列",
                    "both conversation and critical thinking 并列两个宾语。",
                    "both conversation and critical thinking",
                ),
            ],
        },
    ],
}
