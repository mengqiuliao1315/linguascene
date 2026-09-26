"""词书定义与单词数据。

- BOOKS: 词书元数据（四级 / 六级 / 新概念三 / 雅思）
- WORDS: 按词书 code 分组的单词列表

字段说明：
    word   单词
    uk     英式音标
    us     美式音标
    pos    词性
    zh     中文释义
    en     英文释义
    ex     例句列表 [{en, zh}]
    unit   所属单元
    tags   标签（逗号分隔）

需要导入完整词表时，可用 `python -m app.import_words <文件.json>`，
文件格式为 {book_code: [单词对象, ...]}。
"""

BOOKS = [
    {
        "code": "cet4",
        "name": "CET-4 Vocabulary",
        "name_zh": "大学英语四级核心词汇",
        "description": "四级高频核心词，覆盖听力、阅读与写作常见表达。",
        "icon": "📗",
        "level": "B1",
        "order_index": 1,
    },
    {
        "code": "cet6",
        "name": "CET-6 Vocabulary",
        "name_zh": "大学英语六级核心词汇",
        "description": "六级进阶词汇，侧重学术与抽象表达。",
        "icon": "📘",
        "level": "B2",
        "order_index": 2,
    },
    {
        "code": "nce3",
        "name": "New Concept English 3",
        "name_zh": "新概念英语第三册词汇",
        "description": "新概念三册课文词汇，适合培养地道表达与语感。",
        "icon": "📙",
        "level": "B2",
        "order_index": 3,
    },
    {
        "code": "ielts",
        "name": "IELTS Vocabulary",
        "name_zh": "雅思核心词汇",
        "description": "雅思大纲词汇，覆盖听说读写的学术与生活场景表达。",
        "icon": "📕",
        "level": "B2",
        "order_index": 4,
    },
]

WORDS: dict[str, list[dict]] = {"cet4": [], "cet6": [], "nce3": [], "ielts": []}

WORDS["cet4"] += [
    {
        "word": "abandon",
        "uk": "/əˈbændən/",
        "us": "/əˈbændən/",
        "pos": "v.",
        "zh": "抛弃；放弃；离弃",
        "en": "to leave someone or something and not return",
        "ex": [
            {"en": "They had to abandon the car in the snow.", "zh": "他们不得不把车丢弃在雪地里。"},
            {"en": "She never abandoned hope of finding her brother.", "zh": "她从未放弃找到弟弟的希望。"},
        ],
        "unit": "Unit 1",
        "tags": "core,verb",
    },
    {
        "word": "absorb",
        "uk": "/əbˈzɔːb/",
        "us": "/əbˈzɔːrb/",
        "pos": "v.",
        "zh": "吸收；吸引；理解",
        "en": "to take in a liquid, gas, or information",
        "ex": [
            {"en": "Plants absorb water through their roots.", "zh": "植物通过根吸收水分。"},
            {"en": "It took me a while to absorb the news.", "zh": "我花了一会儿才消化这个消息。"},
        ],
        "unit": "Unit 1",
        "tags": "core,verb",
    },
    {
        "word": "academic",
        "uk": "/ˌækəˈdemɪk/",
        "us": "/ˌækəˈdemɪk/",
        "pos": "adj.",
        "zh": "学术的；学院的；纯理论的",
        "en": "relating to education, schools, or studying",
        "ex": [
            {"en": "Her academic record is excellent.", "zh": "她的学业成绩非常优秀。"},
            {"en": "The paper is written in an academic style.", "zh": "这篇论文是用学术风格写的。"},
        ],
        "unit": "Unit 1",
        "tags": "core,adjective",
    },
    {
        "word": "accompany",
        "uk": "/əˈkʌmpəni/",
        "us": "/əˈkʌmpəni/",
        "pos": "v.",
        "zh": "陪伴；伴随；为……伴奏",
        "en": "to go somewhere with someone",
        "ex": [
            {"en": "Her mother accompanied her to the interview.", "zh": "她妈妈陪她去面试。"},
            {"en": "Thunder is often accompanied by lightning.", "zh": "雷声常常伴随着闪电。"},
        ],
        "unit": "Unit 1",
        "tags": "core,verb",
    },
    {
        "word": "accurate",
        "uk": "/ˈækjərət/",
        "us": "/ˈækjərət/",
        "pos": "adj.",
        "zh": "准确的；精确的",
        "en": "correct and exact",
        "ex": [
            {"en": "Please give me an accurate description of the man.", "zh": "请给我那个人的准确描述。"},
            {"en": "The clock is accurate to within a second.", "zh": "这只钟的误差在一秒之内。"},
        ],
        "unit": "Unit 1",
        "tags": "core,adjective",
    },
    {
        "word": "achieve",
        "uk": "/əˈtʃiːv/",
        "us": "/əˈtʃiːv/",
        "pos": "v.",
        "zh": "达到；取得；实现",
        "en": "to succeed in doing something after effort",
        "ex": [
            {"en": "She achieved her goal of running a marathon.", "zh": "她实现了跑马拉松的目标。"},
            {"en": "You can achieve a lot with a clear plan.", "zh": "有了清晰的计划你能取得很大成就。"},
        ],
        "unit": "Unit 1",
        "tags": "core,verb",
    },
    {
        "word": "acquire",
        "uk": "/əˈkwaɪə(r)/",
        "us": "/əˈkwaɪər/",
        "pos": "v.",
        "zh": "获得；习得；购得",
        "en": "to get or gain something",
        "ex": [
            {"en": "Children acquire language very quickly.", "zh": "儿童习得语言非常快。"},
            {"en": "The company acquired three smaller firms.", "zh": "这家公司收购了三家小公司。"},
        ],
        "unit": "Unit 1",
        "tags": "core,verb",
    },
    {
        "word": "adapt",
        "uk": "/əˈdæpt/",
        "us": "/əˈdæpt/",
        "pos": "v.",
        "zh": "适应；改编；调整",
        "en": "to change to suit new conditions",
        "ex": [
            {"en": "It takes time to adapt to a new culture.", "zh": "适应新文化需要时间。"},
            {"en": "The novel was adapted for television.", "zh": "这部小说被改编成了电视剧。"},
        ],
        "unit": "Unit 1",
        "tags": "core,verb",
    },
]

WORDS["cet4"] += [
    {
        "word": "adequate",
        "uk": "/ˈædɪkwət/",
        "us": "/ˈædɪkwət/",
        "pos": "adj.",
        "zh": "足够的；适当的；胜任的",
        "en": "enough or good enough for a purpose",
        "ex": [
            {"en": "The room is adequate for two people.", "zh": "这个房间住两个人足够了。"},
            {"en": "His salary is adequate to support a family.", "zh": "他的薪水足以养家。"},
        ],
        "unit": "Unit 2",
        "tags": "core,adjective",
    },
    {
        "word": "adjust",
        "uk": "/əˈdʒʌst/",
        "us": "/əˈdʒʌst/",
        "pos": "v.",
        "zh": "调整；适应；校准",
        "en": "to change something slightly to make it better",
        "ex": [
            {"en": "You can adjust the seat height.", "zh": "你可以调整座椅高度。"},
            {"en": "It took him a month to adjust to night shifts.", "zh": "他花了一个月才适应夜班。"},
        ],
        "unit": "Unit 2",
        "tags": "core,verb",
    },
    {
        "word": "admire",
        "uk": "/ədˈmaɪə(r)/",
        "us": "/ədˈmaɪər/",
        "pos": "v.",
        "zh": "钦佩；欣赏；赞美",
        "en": "to respect and like someone or something",
        "ex": [
            {"en": "I admire her courage.", "zh": "我钦佩她的勇气。"},
            {"en": "We stopped to admire the view.", "zh": "我们停下来欣赏风景。"},
        ],
        "unit": "Unit 2",
        "tags": "core,verb",
    },
    {
        "word": "adopt",
        "uk": "/əˈdɒpt/",
        "us": "/əˈdɑːpt/",
        "pos": "v.",
        "zh": "采用；采纳；收养",
        "en": "to start to use a method, or to take a child into your family",
        "ex": [
            {"en": "The school adopted a new teaching method.", "zh": "学校采用了一种新教学法。"},
            {"en": "They adopted a girl from Vietnam.", "zh": "他们从越南收养了一个女孩。"},
        ],
        "unit": "Unit 2",
        "tags": "core,verb",
    },
    {
        "word": "advantage",
        "uk": "/ədˈvɑːntɪdʒ/",
        "us": "/ədˈvæntɪdʒ/",
        "pos": "n.",
        "zh": "优势；有利条件；好处",
        "en": "something that helps you or is useful",
        "ex": [
            {"en": "Speaking two languages is a real advantage.", "zh": "会说两门语言是很大的优势。"},
            {"en": "We should take advantage of the fine weather.", "zh": "我们应该好好利用这好天气。"},
        ],
        "unit": "Unit 2",
        "tags": "core,noun",
    },
    {
        "word": "affect",
        "uk": "/əˈfekt/",
        "us": "/əˈfekt/",
        "pos": "v.",
        "zh": "影响；感动；侵袭",
        "en": "to produce a change in someone or something",
        "ex": [
            {"en": "The weather affects my mood.", "zh": "天气会影响我的心情。"},
            {"en": "The disease mainly affects older people.", "zh": "这种疾病主要影响老年人。"},
        ],
        "unit": "Unit 2",
        "tags": "core,verb",
    },
    {
        "word": "afford",
        "uk": "/əˈfɔːd/",
        "us": "/əˈfɔːrd/",
        "pos": "v.",
        "zh": "买得起；负担得起；承受得起",
        "en": "to have enough money or time for something",
        "ex": [
            {"en": "We can't afford a new car right now.", "zh": "我们现在买不起新车。"},
            {"en": "I can't afford to waste any more time.", "zh": "我再也浪费不起时间了。"},
        ],
        "unit": "Unit 2",
        "tags": "core,verb",
    },
    {
        "word": "aggressive",
        "uk": "/əˈɡresɪv/",
        "us": "/əˈɡresɪv/",
        "pos": "adj.",
        "zh": "好斗的；有进取心的；攻势的",
        "en": "behaving in an angry or threatening way",
        "ex": [
            {"en": "The dog became aggressive when approached.", "zh": "有人靠近时那只狗变得具有攻击性。"},
            {"en": "They used an aggressive marketing strategy.", "zh": "他们采用了积极的营销策略。"},
        ],
        "unit": "Unit 2",
        "tags": "core,adjective",
    },
    {
        "word": "alternative",
        "uk": "/ɔːlˈtɜːnətɪv/",
        "us": "/ɔːlˈtɜːrnətɪv/",
        "pos": "n./adj.",
        "zh": "替代方案；供选择的",
        "en": "one of the things you can choose instead of another",
        "ex": [
            {"en": "Is there an alternative to this plan?", "zh": "这个方案有替代方案吗？"},
            {"en": "We took an alternative route to avoid traffic.", "zh": "我们走了另一条路避开交通拥堵。"},
        ],
        "unit": "Unit 2",
        "tags": "core,noun",
    },
    {
        "word": "ambitious",
        "uk": "/æmˈbɪʃəs/",
        "us": "/æmˈbɪʃəs/",
        "pos": "adj.",
        "zh": "有雄心的；野心勃勃的；耗资巨大的",
        "en": "determined to be successful",
        "ex": [
            {"en": "She is ambitious and works very hard.", "zh": "她很有抱负，工作非常努力。"},
            {"en": "It was an ambitious project for a small team.", "zh": "对一个小团队来说这是个宏大的项目。"},
        ],
        "unit": "Unit 2",
        "tags": "core,adjective",
    },
    {
        "word": "analyze",
        "uk": "/ˈænəlaɪz/",
        "us": "/ˈænəlaɪz/",
        "pos": "v.",
        "zh": "分析；解析",
        "en": "to examine something carefully to understand it",
        "ex": [
            {"en": "Scientists analyze the data carefully.", "zh": "科学家们仔细分析这些数据。"},
            {"en": "Let's analyze why the plan failed.", "zh": "让我们分析一下计划失败的原因。"},
        ],
        "unit": "Unit 2",
        "tags": "core,verb",
    },
    {
        "word": "ancient",
        "uk": "/ˈeɪnʃənt/",
        "us": "/ˈeɪnʃənt/",
        "pos": "adj.",
        "zh": "古代的；古老的",
        "en": "belonging to a time long ago",
        "ex": [
            {"en": "We visited an ancient temple.", "zh": "我们参观了一座古庙。"},
            {"en": "Ancient Greece produced many great thinkers.", "zh": "古希腊涌现了许多伟大的思想家。"},
        ],
        "unit": "Unit 2",
        "tags": "core,adjective",
    },
]

WORDS["cet6"] += [
    {
        "word": "abolish",
        "uk": "/əˈbɒlɪʃ/",
        "us": "/əˈbɑːlɪʃ/",
        "pos": "v.",
        "zh": "废除；取消",
        "en": "to officially end a law or system",
        "ex": [
            {"en": "The country abolished the death penalty.", "zh": "该国废除了死刑。"},
            {"en": "They voted to abolish the old rule.", "zh": "他们投票废除旧规定。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,verb",
    },
    {
        "word": "abrupt",
        "uk": "/əˈbrʌpt/",
        "us": "/əˈbrʌpt/",
        "pos": "adj.",
        "zh": "突然的；唐突的；陡峭的",
        "en": "sudden and unexpected",
        "ex": [
            {"en": "The meeting came to an abrupt end.", "zh": "会议突然结束了。"},
            {"en": "He has an abrupt manner.", "zh": "他举止唐突。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,adjective",
    },
    {
        "word": "absurd",
        "uk": "/əbˈsɜːd/",
        "us": "/əbˈsɜːrd/",
        "pos": "adj.",
        "zh": "荒谬的；可笑的",
        "en": "completely unreasonable or silly",
        "ex": [
            {"en": "It is absurd to blame her for the accident.", "zh": "把事故归咎于她很荒谬。"},
            {"en": "The idea sounded absurd at first.", "zh": "这个想法起初听起来很荒唐。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,adjective",
    },
    {
        "word": "accelerate",
        "uk": "/əkˈseləreɪt/",
        "us": "/əkˈseləreɪt/",
        "pos": "v.",
        "zh": "加速；促进",
        "en": "to go faster or make something happen sooner",
        "ex": [
            {"en": "The car accelerated smoothly.", "zh": "汽车平稳地加速。"},
            {"en": "New technology accelerated the process.", "zh": "新技术加速了这一进程。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,verb",
    },
    {
        "word": "accessible",
        "uk": "/əkˈsesəbl/",
        "us": "/əkˈsesəbl/",
        "pos": "adj.",
        "zh": "可接近的；可使用的；易理解的",
        "en": "able to be reached, used, or understood",
        "ex": [
            {"en": "The building is accessible to wheelchair users.", "zh": "这栋楼方便轮椅使用者进出。"},
            {"en": "The article is accessible to beginners.", "zh": "这篇文章初学者也能看懂。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,adjective",
    },
    {
        "word": "accommodate",
        "uk": "/əˈkɒmədeɪt/",
        "us": "/əˈkɑːmədeɪt/",
        "pos": "v.",
        "zh": "容纳；为……提供住宿；适应",
        "en": "to provide room for someone or something",
        "ex": [
            {"en": "The hall can accommodate 500 people.", "zh": "这个大厅可容纳500人。"},
            {"en": "We will try to accommodate your request.", "zh": "我们会尽量满足你的要求。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,verb",
    },
    {
        "word": "accumulate",
        "uk": "/əˈkjuːmjəleɪt/",
        "us": "/əˈkjuːmjəleɪt/",
        "pos": "v.",
        "zh": "积累；积聚；堆积",
        "en": "to gradually collect or increase",
        "ex": [
            {"en": "Dust had accumulated on the shelves.", "zh": "架子上积了灰。"},
            {"en": "He accumulated a large fortune.", "zh": "他积累了一大笔财富。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,verb",
    },
    {
        "word": "acute",
        "uk": "/əˈkjuːt/",
        "us": "/əˈkjuːt/",
        "pos": "adj.",
        "zh": "严重的；敏锐的；急性的",
        "en": "very serious or severe; sharp and sensitive",
        "ex": [
            {"en": "There is an acute shortage of water.", "zh": "水资源严重短缺。"},
            {"en": "Dogs have an acute sense of smell.", "zh": "狗有敏锐的嗅觉。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,adjective",
    },
    {
        "word": "adhere",
        "uk": "/ədˈhɪə(r)/",
        "us": "/ədˈhɪr/",
        "pos": "v.",
        "zh": "黏附；坚持；遵守",
        "en": "to stick to something, or to follow a rule",
        "ex": [
            {"en": "We must adhere to the safety rules.", "zh": "我们必须遵守安全规定。"},
            {"en": "The tape adheres firmly to the surface.", "zh": "胶带牢牢地粘在表面上。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,verb",
    },
    {
        "word": "advocate",
        "uk": "/ˈædvəkeɪt/",
        "us": "/ˈædvəkeɪt/",
        "pos": "v./n.",
        "zh": "提倡；拥护；倡导者",
        "en": "to publicly support an idea or plan",
        "ex": [
            {"en": "She advocates a plant-based diet.", "zh": "她提倡植物性饮食。"},
            {"en": "He is a strong advocate of free education.", "zh": "他大力倡导免费教育。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,verb",
    },
    {
        "word": "aesthetic",
        "uk": "/iːsˈθetɪk/",
        "us": "/esˈθetɪk/",
        "pos": "adj.",
        "zh": "审美的；美学的；美感的",
        "en": "relating to beauty or the appreciation of beauty",
        "ex": [
            {"en": "The design has great aesthetic appeal.", "zh": "这个设计极具美感。"},
            {"en": "Aesthetic judgments vary between cultures.", "zh": "审美判断因文化而异。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,adjective",
    },
    {
        "word": "aggregate",
        "uk": "/ˈæɡrɪɡət/",
        "us": "/ˈæɡrɪɡət/",
        "pos": "n./adj.",
        "zh": "总计；合计的；聚集的",
        "en": "a total formed by adding together many parts",
        "ex": [
            {"en": "The aggregate score was 3 to 1.", "zh": "总比分是3比1。"},
            {"en": "They analyzed the aggregate data.", "zh": "他们分析了汇总数据。"},
        ],
        "unit": "Unit 1",
        "tags": "advanced,noun",
    },
]

# 完整词表由脚本生成到 app/data/{code}.json，seed 时自动读取，这里不再维护示例数据：
# - 新概念三（1047 词，覆盖教材 60 课）：app/fetch_nce3_words.py
# - 雅思（ECDICT 的 ielts 标签）：app/fetch_cet_words.py
