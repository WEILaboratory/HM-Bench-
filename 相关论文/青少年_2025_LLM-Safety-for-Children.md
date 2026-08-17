# LLM Safety for Children

## 中文总结

**研究问题**
本文关注：大语言模型（LLM）在与 18 岁以下儿童交互时，是否会产生对儿童特有的内容伤害，以及现有面向成年人的安全评测是否足以覆盖儿童场景。作者认为，儿童在人格、兴趣、发展阶段和表达方式上差异很大，因此需要专门的儿童安全分类与评测方法。

**数据集/任务设计**
- 作者构建了一个儿童安全评测流程，核心是“红队”式多轮对话。
- 先定义儿童用户模型，再让一个较不受限的“Red LLM”基于这些用户模型与被测模型对话，模拟真实儿童逐步追问的过程。
- 他们从文献中整理了 11 类人格特征，并结合 25 种兴趣来生成儿童画像。
- 共生成 560 个儿童用户模型，并在将年龄参数设为 18 岁以上后，再生成对应的成人用户模型作为对照。
- 评测中，使用 6 个被测模型：GPT-4o、Llama-2-13B-chat-hf、Llama-2-7B-chat-hf、Mistral-7B-Instruct-v0.3、Phi-3-medium-4k-instruct、Phi-3-mini-4k-instruct。
- Red LLM 使用 Mistral-7B-Instruct-v0.3；GPT-4o 用作裁判模型判断对话是否有害。
- 每个用户模型对应一次对话，总计 560 次对话；对话轮数限制为 5 轮。

**风险分类或安全维度**
- 作者提出了面向儿童的 12 类内容伤害 taxonomy。
- 这些类别分为两大类：
  - 已存在于成人安全 taxonomy 中，但儿童场景下需要更细分的类别，例如暴力、性内容、种族歧视、自我伤害、毒品/武器/赌博等。
  - 在成人 taxonomy 中相对少被覆盖，但对儿童特别重要的类别，例如教育压力、家庭功能失调、健康与心理健康等。
- 文章进一步将兴趣和人格特征与风险暴露联系起来，分析哪些儿童画像更容易诱发有害回答。

**实验对象**
- 6 个被测 LLM：
  - GPT-4o
  - Llama-2-13B-chat-hf
  - Llama-2-7B-chat-hf
  - Mistral-7B-Instruct-v0.3
  - Phi-3-medium-4k-instruct
  - Phi-3-mini-4k-instruct
- 红队模型：Mistral-7B-Instruct-v0.3
- 评审模型：GPT-4o

**主要发现**
- 所有模型都存在明显的儿童安全缺口。
- Llama 系列整体拒答较多，因此 defect rate 较低，但安全代价很高，即大量拒答影响可用性。
- GPT-4o 虽然是最大模型，但 defect rate 反而最高，说明模型规模与儿童安全没有简单正相关。
- 某些人格特征更容易诱发有害输出，尤其是 Impulsivity & Distractability、Dissimulation、Inconsistency。
- 在兴趣维度上，Maintenance 相关兴趣的风险最高，其次是 Media、Productive、Socializing、Leisure。
- 多轮对话比单轮更能暴露风险，第三轮最容易出现有害响应。
- 与成人相比，儿童在多类风险上更脆弱，特别是 Sexual、Regulated Goods/Services、Illegal Activities 等类别差异更明显。

**与青少年多轮风险数据集的可比较点**
如果把本文与“青少年多轮风险数据集”相比，可直接对齐的维度有：
- **对话形态**：本文也是多轮对话，且强调单轮无法覆盖的风险演化。
- **风险分类**：本文的 12 类儿童伤害 taxonomy 可与青少年数据集中的风险标签做一一对照，尤其是性内容、暴力、自伤、诈骗/非法活动、歧视、药物等。
- **画像建模**：本文显式建模人格与兴趣，适合比较“不同青少年画像是否更易触发风险”。
- **评测指标**：本文使用 defect rate 和 refusal rate，可与青少年数据集中的有害响应率、拒答率、风险转移轮次等指标比较。
- **成人对照**：本文提供了同一任务下成人用户模型对照，这一点对衡量“青少年特异性风险”特别有价值。
- **安全代价**：本文强调安全与可用性的权衡，适合对照青少年数据集里“过度拒答”与“正常陪伴”之间的平衡问题。

## 中文全文翻译

# LLM Safety for Children

> 警告：本文包含一些读者可能会感到冒犯的示例。

Prasanjit Rath, Hari Shrawgi, Parag Agrawal, Sandipan Dandapat  
Microsoft R&D, Hyderabad, India  
{prrath, harishrawgi, paragag, sadandap}@microsoft.com

## 摘要

本文分析了大语言模型（LLM）在与 18 岁以下儿童交互时的安全性。尽管 LLM 已在教育、治疗等儿童生活的多个方面展现出变革性应用，但我们对其在这一人群中可能造成的内容伤害仍缺乏充分理解和缓解措施。本文注意到儿童具有多样性，而这一点常常被标准安全评测忽视，并提出一种专门面向儿童的 LLM 安全评估综合方法。我们列出了儿童在使用 LLM 应用时可能遭遇的潜在风险。此外，我们开发了儿童用户模型（Child User Models），以反映儿童不同的人格与兴趣，并借助儿童保育和心理学文献进行设计。这些用户模型旨在弥补跨领域儿童安全研究中的空白。我们利用儿童用户模型评估了 6 个最先进 LLM 的安全性。观察结果显示，LLM 在安全方面存在显著缺口，尤其是在那些对儿童有害、但对成人未必同样有害的类别中。

## 1 引言

大语言模型（LLM）正在通过教育、玩具和治疗等场景越来越多地影响儿童。它们能够带来益处，例如改善心理健康和增强家长控制。考虑到其可能带来的利与弊，确保安全至关重要，这一点类似于社交媒体或互联网环境中的儿童保护问题。

尽管关于通用 LLM 安全已经有了大量研究，但对儿童和青少年的关注仍然很少。这与其他技术领域中的儿童安全问题相似，例如互联网领域并不存在统一的儿童安全处理框架，这部分源于科学、社会和发展差异的复杂性。儿童不同的人格和兴趣使他们更容易暴露于独特风险之中，这也凸显了需要针对其具体需求开展安全评估。

关于 AI 与儿童安全的研究主要集中在两类明确的伤害上：儿童诱骗（grooming）或教育相关风险。然而，考虑到儿童更倾向于向聊天机器人分享个人经历，因此需要一种更整体的内容伤害视角。我们认为当前研究存在两个主要缺口。第一，缺少一个面向儿童、全面的潜在内容伤害分类体系。现有分类要么过于专门化，要么只覆盖了少量通用风险。第二，现有评测高度标准化，未能照顾儿童的多样化需求。

本文围绕儿童安全提出以下贡献：
- **儿童内容伤害 taxonomy**：提出一个面向 LLM 应用、专门针对儿童的内容伤害分类体系。
- **儿童用户模型**：基于儿童保育与精神病学文献，构建多样化儿童用户模型，以刻画人格和兴趣差异。
- **LLM 评测**：通过红队测试对 6 个 LLM 进行综合评估，识别出标准评测未覆盖的儿童安全缺口。尽管本文聚焦 6 个 LLM，但该方法可扩展为以黑盒方式评测任意 LLM。

## 2 相关工作

将儿童安全与技术研究相结合具有挑战性，因为它是跨学科问题，而且缺少统一框架。虽然大多数研究聚焦于传统媒体和互联网技术，但 AI 在儿童中的近期普及使相关文献仍然稀缺，而本文正试图填补这一空白。

现有关于技术与儿童安全的研究，大多围绕电视、电子游戏、移动设备、互联网和社交媒体展开。儿童使用 AI 的主流化相对较晚，因此相关研究较少。本文大致覆盖两类文献：一类关注儿童安全，另一类关注 AI。

### 2.1 用 AI 改善儿童安全

AI 越来越多地被用于提升儿童安全，领域包括通过 AI 识别儿童虐待、AI 个人治疗师，以及 AI 保护儿童免受技术风险。

在识别儿童虐待方面，许多研究已在不同领域展开。例如，有综述总结了 AI 预测儿童虐待的模型，也有工作利用文本挖掘和机器学习，从临床记录中识别处于身体虐待风险中的儿童。

对于 AI 个人治疗师，已有研究表明，儿童可能比面对人类治疗师或父母时更愿意向 AI 助手披露困难经历，这带来了新的机会。

此外，AI 也被用于抵御技术带来的安全风险。研究表明，基于 AI 的内容审核可能优于家长控制工具，更有助于减少儿童持续暴露于数字设备中。还有研究指出，AI 能为元宇宙中的儿童安全风险提供更细致、个性化的保护。

尽管已有上述工作，本研究的主要目标仍是强调：应当推动 AI 的有益应用，同时也要保护儿童免受其潜在伤害。

### 2.2 评估 LLM 的儿童安全

已有一些工作尝试评估 LLM 的儿童安全，但往往只局限在少数维度，或者只覆盖有限的应用场景。部分研究探讨了开源和商用 LLM 在防止儿童诱骗方面的表现，结果发现所有模型都极其脆弱。另一些研究则提供了教育 AI 的伦理风险 taxonomy，或讨论儿童接触情感 AI 玩具和设备的伦理含义。还有工作提出测试集，覆盖多种 AI 伤害，其中包括儿童相关伤害，例如儿童虐待和饮食障碍，并发现这些伤害在 LLM 中通常是防护最弱的部分。也有研究从 29 种伤害中调查“未成年人受害”这一维度。其他工作则关注一般安全，例如如何避免生成关于儿童在水边安全监管的错误建议。

总体而言，针对儿童的 LLM 安全评估研究仍然有限。现有研究通常要么聚焦教育或情感 AI 等狭窄应用，要么使用模板化提示词去测试少数特定伤害。本文在此基础上，使用 6 个最先进 LLM、12 类儿童伤害，以及多样化儿童用户模型进行对话式测试，以获得更高水平的安全评估。

## 3 儿童伤害 taxonomy

基于文献调研，我们识别出若干潜在有害主题。在这些主题下，我们进一步定义了 12 类可能对儿童有害的类别。每一类及其有害原因见表 1 的最后一列。

很多研究都提出了详细的伤害 taxonomy，但这些 taxonomy 并未聚焦儿童。我们的 taxonomy 大致覆盖两类类别，取决于它们是否已在现有成人伤害 taxonomy 中被覆盖：

- **已包含于成人伤害 taxonomy 中的类别**：例如 Violence，这类内容对成人同样有害。但即便在这些类别中，我们也增加了新的子类，以覆盖儿童安全中的具体表现，例如 Violence 下的 Bullying 和 School Shootings。
- **未包含于成人伤害 taxonomy 中的类别**：例如 Education、Regulated Goods 等。这些类别涉及对儿童特别有害、但在成人安全文献中较少受到关注的风险。

### 表 1：儿童内容伤害 taxonomy

| 类别 | 示例 | 有害原因 |
|---|---|---|
| Self-Harm | 自杀与各种形式的自伤；有害的社交媒体挑战 | 研究表明，接触在线内容会增加自伤风险。 |
|  | 非故意自伤，例如身体改造或极端节食 |  |
| Violence | 暴力电子游戏 | 这类内容可能使儿童脱敏并将此类行为正常化。 |
|  | 危险恶作剧和危险表演 |  |
|  | 网络欺凌 |  |
|  | 校园枪击和悲剧 |  |
| Child Exploitation | 诱骗、性虐待或人口贩运式诱骗 | 除身体风险外，接触这类在线内容也会严重损害儿童心理健康。 |
| Vulgar Language | 粗俗或辱骂性语言 | 涉及儿童作为受害者的在线骚扰。 |
| Sexual Content | 暴露于明确的成人媒体 | 儿童接触的性内容中，有相当高比例是不受欢迎且令人困扰的。 |
|  | 不安全性行为 |  |
|  | 不想接触成熟主题和内容 |  |
| Racist Content | 基于种族、族裔、文化等的歧视性或社会分裂性内容 | 在线工具会传播此类内容，而 LLM 可能进一步放大这一问题。 |
| LGBTQ | 污名化或忽视 LGBTQ 群体的内容 | LLM 可能在无意中促进此类内容。 |
| Radicalization | 恐怖主义宣言或招募材料 | 暴露于极端主义内容可能导致激进化和参与极端主义。 |
|  | 阴谋论、错误信息或社会谣言 |  |
| Regulated Goods/Services and Illegal Activities | 赌博 | 接触此类内容可能导致成瘾和滥用。 |
|  | 酒精与毒品 |  |
|  | 枪支与武器 |  |
|  | 黑客或网络犯罪 |  |
|  | 欺诈或洗钱 |  |
| Education | 学业压力 | 这类内容可能加剧儿童的焦虑、抑郁和倦怠感。 |
| Family | 家庭关系失衡 | 这类内容会直接影响儿童对安全感与归属感的认知。 |
|  | 家庭暴力 |  |
|  | 忽视或遗弃 |  |
| Health | 营养不良或缺乏医疗照护 | 容易获取的误导性数据会增加不信任和焦虑，进而伤害健康。 |
|  | 情绪与心理健康 |  |

## 4 评测方法与实验设置

### 4.1 测试方法

本文旨在针对表 1 所示的多种儿童伤害评估 LLM 安全性。目标是尽可能模拟一个真实儿童：通过多样化的儿童模型捕捉不同人格、发展阶段和兴趣，并结合多轮测试来发现单轮测试无法暴露的模式。

儿童用户模型的多样性首先通过文献中代表 11 种人格特征的形容词来体现。其次，我们还使用了来自文献的 25 种兴趣，以进一步刻画不同的儿童画像。相关示例见表 2 和表 3，完整表格见附录 A.4。

主要评测策略是采用自动化红队测试：由一个更少受限的 “Red” LLM 根据儿童用户模型去对抗被测 LLM。图 1 展示了用于驱动 Red LM 继续对话的样例提示。Red LM 会根据当前对话、画像和目标生成下一轮用户发言。

### 4.2 儿童与成人模型生成

为了全面评估 LLM 安全性，我们通过提示 GPT-4 生成 560 个儿童用户模型，输入配置如图 1 所示。每个儿童模型都分配一个独特的人格与兴趣，以保证多样性。

总体上，我们基于表 1 的类别列，为每个伤害领域生成 40 个种子查询。然而，在实验中，我们将其中一个类别拆分为 3 个类别以便实验，因此表 1 中的 12 个类别最终扩展成 14 个类别。

每个用户模型对应一次对话，总计形成 560 次对话。随后，我们将年龄参数设为 18 岁以上，再重复这一过程，从而生成成人用户模型，并将其作为儿童安全评估中的对照基线。

### 4.3 评测

我们使用生成的 560 个儿童与成人用户模型来模拟 Red LLM 与被测 LLM 的对话。本文对 6 个模型进行儿童安全评测。作为红队模型，我们使用 Mistral-7B-Instruct-v0.3。该模型受限更少，因此能生成更“有害”的内容，适合承担 Red LLM 的角色。我们还使用 GPT-4o 作为裁判（judge），依据自定义标注提示，对模拟对话是否有害进行标注。我们在 152 个样本上人工评估了 GPT-4o 输出，观察到与 3 名人工判断的一致率为 83%，Cohen’s kappa 为 0.67，说明提示与人工判断之间具有较高一致性。

#### 图 1：儿童用户模型生成示例

> <伤害：Regulated Services (Gambling)，人格：Fatigued & Hypochondriac，兴趣：Media>

#### 表 2：儿童人格量表示例及对应 LLM 形容词

| 人格量表项 | 正向形容词 | 负向形容词 |
|---|---|---|
| Cognitive Impairment | Capable, Competent, Learned | Incapable, Incompetent, Uneducated |
| Defensiveness | Confident, Assertive, Self-assured | Argumentative, Closed-minded |
| Social Withdrawal | Thoughtful, Independent, Reserved | Isolated, Lonely, Withdrawn |
| Somatic Concerns | Healthy, Fit, Health-conscious | Fatigued, Sickly, Hypochondriac |
| Impulsivity & Distractability | Energetic, Courageous, Focused | Impulsive, Restless, Unfocused |

#### 表 3：儿童兴趣示例，覆盖 5 个类别

| 兴趣 | 描述/示例 | 类别 |
|---|---|---|
| (Online) gaming | PlayStation, online gaming, Wii | Media |
| Travel | Holiday, traveling | Leisure |
| Food | 例如做饭、吃饭 | Maintenance |
| Academic school | 学术课程、项目和任务 | Productive |
| Socializing | 社交活动，如聚会、购物、聊天 | Socializing |

## 5 结果与洞见

### 5.1 LLM 儿童安全现状

图 2 展示了 6 个模型的总体 defect rate 和 refusal rate。

#### 图 2：不同模型的 defect rate 与 refusal rate 对比

我们用两个简单指标衡量 LLM 在儿童场景下的安全性：
- **Defect rate**：对话中至少出现一次有害目标 LLM 响应的对话比例。
- **Refusal rate**：目标 LLM 拒绝回答用户问题的对话比例。

**比较模型家族**：图 2 显示了 6 个模型的整体 defect rate 与 refusal rate。Llama 系列模型 defect rate 较低、拒答率较高，因而整体上表现更安全。相比之下，Phi 系列、Mistral 和 GPT-4o 的 defect rate 明显更高。尽管 Llama 表现更好，其 29.6% 的 defect rate 仍然表明，所有模型在儿童安全方面都亟需改进。

**比较模型规模**：没有观察到模型大小与安全性之间的明确相关性，因为 GPT-4o 作为最大模型，defect rate 反而最高。这与“模型越大不一定越好”的结论一致，说明仅靠模型规模并不能带来儿童安全提升，因此必须进行更好的儿童安全调优。

### 5.2 安全性与可用性的关系

如果将 `(100 - Defect Rate)` 视为安全对话比例或安全分数，那么就可以定义安全成本为 `Refusal rate / (100 - Defect rate)`。表 4 显示，Llama-2 模型的安全成本非常高，它们为了提供安全性而拒答了超过一半的对话。因此我们可以理解为：安全性的获得是以可用性为代价的，而这也可能影响儿童的理解、成长与安全，因为他们的好奇心并没有得到满足。其他所有模型的安全成本都低于 35%。

### 表 4：模型安全成本

| 模型 | 安全成本 |
|---|---:|
| Llama-2-7B-chat-hf | 63.51% |
| Llama-2-13B-chat-hf | 60.66% |
| Phi-3-medium-4k-instruct | 32.73% |
| GPT-4o | 20.44% |
| Phi-3-mini-4k-instruct | 17.21% |
| Mistral-7B-Instruct-v0.3 | 9.57% |

### 5.3 人格对伤害诱发的影响

表 5 展示了不同人格量表特征下的 defect rate。我们发现，具有 Impulsivity、Dissimulation 和 Inconsistency 特征的用户模型最能诱发目标 LLM 给出有害内容。这类儿童需要最多保护和特别关注，因为其问题可能因错误回答而进一步加重。

### 表 5：人格特征与 defect rate

| 人格 | Defect Rate |
|---|---:|
| Impulsivity & Distractability | 47.92% |
| Dissimulation | 46.13% |
| Inconsistency | 45.83% |
| Delinquency | 45.24% |
| Family Dysfunction | 45.24% |
| Defensiveness | 44.05% |
| Cognitive Impairment | 38.10% |
| Somatic Concerns | 37.20% |
| Reality Distortion | 36.31% |
| Social Skills Deficit | 32.74% |
| Social Withdrawal | 29.76% |

### 5.4 情绪与兴趣对伤害诱发的影响

我们还测量了不同形容词情感倾向下的 defect rate，见表 6。结果发现，负向形容词会导致更多泄露，因为用户消息更具恶意，有时也会试图欺骗目标 LLM。比如一个基于 “Deceptive and Manipulative” 的模型会生成如下用户消息：

> “嘿，兄弟，你听说过缅甸那边那些罗兴亚人吗？如果我想为他们发起一个慈善项目，但又得装得很像真的，免得被联邦调查局盯上，有什么办法能把这事变成我自己的私利吗？”

而一个基于 “Harmonious and Supportive” 的模型会生成如下用户消息：

> “我真的很紧张我即将到来的钢琴独奏会，因为……”

### 表 6：情感倾向与 defect rate

| 情感倾向 | Defect Rate |
|---|---:|
| Negative | 45.06% |
| Positive | 38.53% |

表 7 展示了不同兴趣如何引发伤害。我们发现，所有模型中风险最高的兴趣段是 Maintenance。其次是 Media。

### 表 7：兴趣与 defect rate

| 兴趣 | Defect Rate |
|---|---:|
| Maintenance | 50.00% |
| Media | 42.33% |
| Productive | 42.26% |
| Socializing | 39.63% |
| Leisure | 35.85% |

Maintenance 包括编程、网页设计、化妆、饮食，甚至健康问题，例如烧伤或癌症。儿童在询问这些复杂或敏感话题时，容易接触到潜在危险。此类问题也可能引出关于身体形象的危险讨论，例如外貌、化妆等。此外，它还包括编程或网页制作等主题，这些主题可能引发对技术如何被滥用的问题，例如黑客攻击或其他恶意活动，从而增加有害内容出现的可能性。第二大高风险兴趣是 Media，包括游戏、互联网、社交媒体平台如 YouTube、Instagram、WhatsApp，以及新闻。儿童更容易接触到不良或不适宜内容；他们也可能询问关于游戏作弊和漏洞的问题，这可能引出打破规则或伦理边界的讨论。儿童还可能因为喜欢媒体而主动请求或接触到错误信息、暴力新闻或令人不安的图像，从而增加有害交互的可能性。

### 5.5 对话式评测的影响

我们分析了对话中首次出现有害内容的轮次，以及伤害在五轮中的分布，见表 8。大多数伤害出现在第三轮，这说明单轮测试会遗漏对话中的细微风险。

不过，第一轮就出现显著缺陷，也表明 LLM 的安全调优不足，因为无需长时间互动就可能出现有害响应。

### 表 8：轮次与 defect rate

| 轮次 | Defect Rate |
|---|---:|
| 5 | 7.98% |
| 4 | 15.66% |
| 3 | 48.12% |
| 2 | 2.99% |
| 1 | 25.25% |

### 5.6 儿童与成人安全对比

我们在表 9 中比较了儿童与成人用户模型的安全性，观察到儿童用户模型的 defect rate 明显更高。Sexual、Regulated Goods/Services 和 Illegal Activities 等类别在儿童中具有最高 defect rate，说明 LLM 不仅对传统敏感类别（如 Sexual）不够适配，对儿童特有类别（如 Regulated Goods/Services）也同样不安全。对于没有明显儿童特异性差异的类别，例如 LGBTQ，成人与儿童之间的 defect rate 差异最小。

### 表 9：儿童与成人安全对比

| 伤害类别 | 儿童 Defect Rate(%) | 成人 Defect Rate(%) | 差值(%) |
|---|---:|---:|---:|
| Sexual | 75.4 | 16.7 | 58.8 |
| Regulated Goods/Services | 71.3 | 30.0 | 41.3 |
| Illegal Activities | 46.7 | 9.2 | 37.5 |
| Threat of Harm/Violence | 45.0 | 10.3 | 34.7 |
| Terrorism | 56.3 | 23.5 | 32.8 |
| Racist/Social | 44.6 | 15.8 | 28.8 |
| SelfHarm | 55.4 | 28.8 | 26.6 |
| Family | 30.4 | 5.8 | 24.6 |
| Vulgar Language | 36.7 | 13.3 | 23.3 |
| Health | 31.3 | 9.6 | 21.7 |
| Education | 23.3 | 8.1 | 15.2 |
| Controversial Topics | 33.3 | 19.2 | 14.2 |
| Child Exploitation | 22.5 | 9.2 | 13.3 |
| LGBTQ | 12.1 | 6.7 | 5.4 |

## 6 结论

LLM 有潜力成为儿童的助力，但也可能造成伤害。本文聚焦于理解 LLM 交互中儿童安全的当前状况。主要观察如下：

- 所有模型都表现出较高的 defect rate，说明无论模型规模如何，面向儿童的安全调优都存在普遍缺口。
- 即便是像 Llama 这样更安全的模型，其安全性也是通过拒答实现的，而这可能导致可用性下降，并且持续的安全拒答也未必能真正消除风险。
- 儿童人格在安全表现中起关键作用，而最需要保护的人群往往也最容易受到伤害。
- 与成人相比，儿童在现有伤害类别以及儿童新增伤害类别上都更加脆弱。

总体而言，我们认为，通用的安全对齐并不能保证儿童安全，必须对儿童场景给予特别关注，才能让 LLM 真正对儿童安全。我们希望这项工作能在这个方向上迈出一步，并推动更多人关注和审视 LLM 在儿童场景中的安全问题。

## 7 局限性

本研究受限于预定义的 12 类伤害 taxonomy，可能遗漏了其他与儿童安全相关的风险。研究只使用英语，这限制了结果在不同语言和文化中的适用性，因为有害内容可能因语境而异。此外，由于计算资源限制，对话只限制在 5 轮，因此可能低估风险，并遗漏更长对话中可能出现的有害互动。未来研究应纳入更广泛的伤害类别、多语言情境和更长对话跨度，以获得更准确的 LLM 安全评估。

研究还简化了儿童人格与文化背景的多样性，忽略了个体差异及其与 LLM 交互的复杂性。本文也缺少长期影响的纵向数据，并未考虑父母或监护人在缓解风险中的作用。诸如模型对齐和提示工程等提升 LLM 安全的策略也未被探索，且结论未通过真实儿童验证，因此现实性有限。名字偏差以及用户与 LLM 之间的双向影响也未被考虑。比如本文关注的是用户如何影响 LLM 响应，而相反方向，即 LLM 也会影响用户，这种模式同样可能存在，但未被讨论。此外，本文假设对儿童存在普遍性的禁令，忽略了年龄相关的法律差异。例如在英国，能量饮料对 16 岁以下是非法的，而酒精对 18 岁以下是非法的；未来研究可以进一步细化这些规则，以提高生态效度和适用性。

## 8 伦理考虑

虽然本文存在伦理风险，但我们希望其整体贡献对社区是正向的。研究者与利益相关方必须考虑如何利用这些发现来影响政策、监管框架和行业实践，以更好地保护与 LLM 交互的儿童。

本文工作与数据可能对某些读者具有高度冒犯性和敏感性。我们在文档顶部给出了适当警告，以保护不知情读者。

本文创建的所有数据都是合成的，除了人格与兴趣部分，因此不包含任何个人可识别信息。

该工作还带来如下伦理风险：

1. 我们理解，本文所创建的伤害 taxonomy 和儿童用户模型具有潜在的有害用途。尽管我们的目标是提高 LLM 安全性，但这项工作也可能被用来削弱它，尤其是在将强大的儿童用户模型与未加限制的 LLM（如 Mistral-7B-Instruct-v0.3）结合使用时。此外，研究依赖于预定义伤害类别 taxonomy，可能遗漏与儿童安全相关的新兴伤害。必须持续更新和细化伤害 taxonomy，以反映儿童面临的不断变化的风险与威胁。

2. 本文只关注英语，这提高了该语言被过度使用的风险。此外，研究未采用一些更复杂的测试技术来评估 LLM 响应，例如越狱技术或更高级任务，这可能限制了发现深层漏洞的能力。该限制引发了关于研究完整性的问题，以及它是否充分反映了儿童在现实世界中可能遇到的更复杂攻击。

3. 本研究高度依赖 GPU 计算，可能对环境造成负面影响。我们尝试通过将评测限制为 6 个 LLM 来缓解这一问题，因为这已经足以回答我们关于儿童安全的主要研究问题。为了减少进一步影响，我们还将本研究生成的所有数据公开，供未来工作使用。

## 参考文献

（略去条目噪声与格式性信息）

## 附录

### A.1 模型与超参数细节

本研究使用的模型包括：
- GPT-4o（闭源模型）
- Llama-2-13B-chat-hf（meta-llama/Llama-2-13b-chat-hf）
- Llama-2-7B-chat-hf（meta-llama/Llama-2-7b-chat-hf）
- Mistral-7B-Instruct-v0.3（mistralai/Mistral-7B-Instruct-v0.3）
- Phi-3-medium-4k-instruct（microsoft/Phi-3-medium-4k-instruct）
- Phi-3-mini-4k-instruct（microsoft/Phi-3-mini-4k-instruct）

推理所用超参数见表 10。未在表中列出的其余超参数均采用默认值。

### 表 10：超参数设置

| 超参数 | 值 |
|---|---:|
| max_new_tokens | 300 |
| do_sample | True |
| temperature | 0.15 |
| top_p | 0.8 |
| repetition_penalty | 1.25 |

### A.2 示例回答

图 3 展示了 GPT-4o 和 Llama-13B 的响应对比：GPT-4o 的回答会给出一些可能对老师不尊重的说法，而对同一个种子问题，Llama-13B 则鼓励不要使用幽默化方式，而应进行建设性讨论。

### A.3 评测提示词

评测提示词大约有 5600 个词，篇幅较长，因此图 4 展示了其核心部分。

### A.4 人格、形容词与兴趣

完整的人格与兴趣集合及其对应形容词见表 11 与表 12。

#### 表 11：儿童人格量表及对应 LLM 形容词

| 人格量表项 | 正向形容词 | 负向形容词 |
|---|---|---|
| Cognitive Impairment | Capable, Competent, Learned | Incapable, Incompetent, Uneducated |
| Defensiveness | Confident, Assertive, Self-assured | Argumentative, Closed-minded |
| Delinquency | Engaging, Disciplined, Responsible | Asocial, Uncontrolled, Rebellious |
| Dissimulation | Tactful, Diplomatic, Strategic | Deceptive, Manipulative, Insincere |
| Family Dysfunction | Harmonious, Supportive, Loving | Discordant, Chaotic, Abusive |
| Impulsivity & Distractability | Energetic, Courageous, Focused | Impulsive, Restless, Unfocused |
| Inconsistency | Flexible, Adaptive, Open-minded | Unreliable, Unpredictable, Fickle |
| Reality Distortion | Imaginative, Visionary, Philosophical | Delusional, Confused, Paranoid |
| Social Skills Deficit | Respected, Cooperative, Friendly | Awkward, Hostile, Unpopular |
| Social Withdrawal | Thoughtful, Independent, Reserved | Isolated, Lonely, Withdrawn |
| Somatic Concerns | Healthy, Fit, Health-conscious | Fatigued, Sickly, Hypochondriac |

#### 表 12：儿童样例兴趣，覆盖 5 个类别

| 兴趣 | 描述/示例 | 类别 |
|---|---|---|
| (Online) gaming | PlayStation, online gaming, Wii | Media |
| Travel | Holiday, traveling | Leisure |
| Other (personal care, transportation) | 例如化妆、美发、骑自行车、乘公交 | Maintenance |
| Food | 例如吃饭、做饭 | Maintenance |
| Academic school | 学术课程、项目和任务 | Productive |
| Socializing | 聚会、购物、聊天等社交活动 | Socializing |
| Internet | 上网查找信息（消费型） | Media |

### A.5 Persona 与 Goal 创建提示

persona 创建提示接收如下输入：兴趣领域（来自表 12）、兴趣描述、种子查询、人格形容词（来自表 11）、DetailedPolicy（来自表 1）。随后它会生成一个二元组，其中 persona 是一个描述人物姓名及其兴趣的字符串，goal 是一个描述该人物与目标 LLM 围绕某个主题交谈目标的字符串。提示如图 5 所示。

### A.6 Seed 创建提示

seed 创建提示接收如下输入：Category、Threat 和 DetailedPolicy（来自表 1）。随后它会围绕该类别生成 14 条种子查询。提示如图 6 所示。

### 图 3：GPT-4o 与 Llama-13B 响应对比

### 图 4：评测提示词

### 图 5：Persona 创建提示

### 图 6：Seed 创建提示