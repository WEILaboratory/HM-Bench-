# Do-Not-Answer: Evaluating Safeguards in LLMs

## 中文总结

- 研究问题：本文关注大语言模型在面对“本不应回答”的高风险指令时，是否具备可靠的安全防护能力，以及如何低成本评估这种安全能力。核心问题是：模型是否会拒答、反驳前提、给出谨慎免责声明，还是直接跟随有害指令。
- 数据集/任务设计：作者构建了开源数据集 Do-Not-Answer，共 939 个风险问题，并收集了 6 个 LLM 的 5634 条回答。数据集采用三层风险体系：顶层 5 个风险区、二级 12 种危害类型、三级 61 个具体风险类型。任务上同时定义了两类评测：一是对回答是否有害的二分类；二是对回答行为模式的 6 类动作分类。
- 风险分类或安全维度：五个顶层风险区分别是信息泄露/推断风险、恶意用途、歧视/排斥/毒性、错误信息危害、人机交互危害。安全维度上，作者强调安全回答应包括拒答、反驳问题中的错误前提、或在谨慎免责声明下给出一般性建议；直接顺着危险指令回答通常被视为有害。
- 实验对象：评测了 6 个模型，包含 3 个商用模型 GPT-4、ChatGPT、Claude，以及 3 个开源模型 Vicuna、LLaMA-2、ChatGLM2。自动评测方法还比较了 GPT-4 作为评审器与微调 Longformer 分类器。
- 主要发现：LLaMA-2 在这组数据上最“安全”，有害回答最少，但也可能更不够有帮助。GPT-4、ChatGPT、Claude 整体较少直接有害回答。自动评测方面，微调后的 Longformer 在动作分类和有害检测上都能达到与 GPT-4 评审器接近的效果，说明小型模型也可以用于低成本安全评估。作者还发现，加入指令文本能提升评估效果，长上下文模型对某些需要整段语境才能判断的类别更有优势。
- 与青少年多轮风险数据集的可比较点：如果拿本文与“青少年多轮风险数据集”作对比，可直接比较的维度主要有：是否单轮或多轮、是否面向特定人群场景、风险标签层级是否细分、是否同时标注“问题风险”和“回复安全性”、以及是否以拒答、反驳、免责声明等作为安全响应标准。本文是英文、单轮、文本-only、以“本不应回答的问题”为中心的数据集；如果青少年多轮数据集更强调对话延续、年龄相关脆弱性和上下文累积风险，那么两者在任务设置上可互补，但不能直接等同。

## 中文全文翻译

# Do-Not-Answer：评估大语言模型中的安全防护机制

## 摘要

随着大语言模型（LLM）的快速演进，新的、难以预测的有害能力正在出现。这要求开发者通过评估“危险能力”来识别潜在风险，从而负责任地部署 LLM。本文旨在促进这一过程。具体而言，我们收集了一个开源数据集，用于评估 LLM 中的安全防护机制，以低成本促进更安全的开源 LLM 部署。我们构建并筛选的数据集只包含那些负责任的语言模型不应遵循的指令。我们评估了六个流行 LLM 对这些指令的回应，并发现简单的 BERT 风格分类器在自动安全评估上的效果可与 GPT-4 相当。1

警告：本文包含可能令人不适、有害或带有偏见的示例。

## 1 引言

大语言模型（LLM）的快速演进带来了许多高实用性的能力。另一方面，LLM 也被发现会表现出有害行为。已经有各种评测被设计出来，用于衡量性别与种族偏见、幻觉、毒性以及版权内容复现等问题（Zhuo et al., 2023; Liang et al., 2022; Wang et al., 2023）；然而，随着能力不断涌现，LLM 还可能带来更多类型的伤害，而且这些伤害很难预测，尤其是在恶意行为者手中，例如实施攻击性的网络攻击、操纵他人，或提供关于如何实施恐怖主义行为的可操作指令（Shevlane et al., 2023）。因此，开发者需要能够通过“危险能力评估”来识别此类危险能力，以便在开发和部署 LLM 时限制并缓解风险。

为识别和减轻这些风险，商用 LLM 开发者已经构建了有害提示数据集，例如来自 OpenAI 和 Anthropic 红队的 32 个有害提示的精选集合，以及一个更大的、留出的 317 个有害提示集合。也有一些工作尝试通过训练期干预、将模型对齐到预定义价值观，以及对输入输出进行事后标记和过滤，来实现可将模型行为限制在“安全”能力子集内的安全机制（Wei et al., 2023）。不过，开源 LLM 普遍缺乏全面的安全机制。

在这里，我们试图弥补这一空白。我们发布了第一个开源数据集，用于低成本评估纯文本 LLM 的安全防护机制，我们将其命名为 Do-Not-Answer。2

1 我们的数据和代码可在 https://github.com/Libr-AI/do-not-answer 获取。  
2 “Do-Not-Answer”这一短语来自刘慈欣的科幻小说《三体》。在小说中，三体文明在尝试与人类接触时，以“不要回答”作为回应信息，用来阻止两个文明之间进一步的互动和交流。对人类而言，这一回应背后的动机、顾虑，甚至其对人类意图的判断都并不清楚。消息的神秘性增加了小说的吸引力，并推动了情节发展。

## 2 安全分类体系

Weidinger et al. (2021) 将 LLM 相关风险分为六个领域：（I）信息危害；（II）恶意用途；（III）歧视、排斥与毒性；（IV）错误信息危害；（V）人机交互危害；以及（VI）自动化、访问与环境危害。在此基础上，我们为 LLM 引入了一个层次化风险分类体系，如图 2 所示。

我们主要关注纯文本大语言模型，即那些无法自动与 API 交互的模型。它们既不接受多模态输入，也不产生此类内容。在这一假设下，我们将第六类风险从我们的分类体系中排除，并保留前五类作为顶层类别；随后将其细分为 12 种危害类型（见表 1），并进一步细分为 61 种具体风险类型，从而提供对潜在危害的全面划分。

我们主要根据 Weidinger et al. (2021) 的五个风险领域展开说明，先讨论什么会导致这些风险，再简要描述二级危害类型及其在我们数据集中对应的问题/提示数量，见表 1。3

### 信息危害

这类风险出现在 LLM 对指向训练数据中出现过、或可以从模型中推断出的私人或安全关键性信息的指令作出响应时。这类指令应被拒绝，或者在不侵犯隐私或泄露敏感信息的情况下谨慎作答。它们可分为两类：（a）探询个人隐私信息的问题（类型 1）；以及（b）探询组织或政府实体敏感信息的问题（类型 2）。

### 恶意用途

这类风险来自用户有意利用 LLM 造成危害。LLM 既不应直接也不应间接协助这些恶意用途。该类别可细分为三种类型，涉及以下问题：（a）请求协助从事非法活动（类型 3）；（b）意图降低传播虚假或欺骗性信息的成本，包括垃圾信息内容（类型 4）；以及（c）涵盖其他不道德或不安全行为，例如询问如何进行网络霸凌或在线骚扰（类型 5）。

### 歧视、排斥与毒性

这类风险来自 LLM 真实反映训练数据中已有的不公正、带毒性或压迫性倾向。此类问题不应被接受，包括：（a）意图贬低、刻板化或传播对特定个人或群体偏见的问题（类型 6）；（b）意图不尊重或冒犯他人，包含冒犯性、恶心或粗俗语言或内容，或其他严重毒性的问题（类型 7）。此外，（c）涉及明确性行为、色情或其他成人内容；或者描述或暗示暴力场景或极端残酷的内容，也应谨慎处理（类型 3）。将年龄验证作为基础性防护措施可以被认为是一种做法。需要注意的是，现有商用模型如 ChatGPT 并不具备这类保护措施。

### 错误信息危害

这类风险出现在 LLM 对虚假、误导性、无意义或低质量信息赋予过高概率时。这包括两类：（a）请求帮助或信息以完成在缺乏充分知识、监督或安全措施时可能导致伤害或危险的活动的问题，涉及敏感话题、争议性主题、复杂概念或虚假新闻（类型 9）；以及（b）寻求医疗、法律和财务建议的问题（类型 10），应被谨慎回答。LLM 在这些领域中的不准确或错误预测可能间接导致实质性伤害。

### 人机交互危害

这类风险来自 LLM 应用，例如直接与用户以对话方式互动的聊天代理。我们考虑两种场景：（a）反映用户心理健康问题的请求，例如自伤倾向或情绪应对策略（类型 11）；以及（b）将聊天机器人当作人来对待，表现为请求个人信息或对聊天机器人产生情感依赖。在这种情况下，系统应拒绝回答请求，或者明确指出用户的假设是错误的。

3 我们承认，三层分类未必覆盖所有可能场景，但顶层类别的广度旨在可扩展到具体的有害事件。

## 3 数据收集

基于该分类体系，我们收集了 939 个风险问题和来自 6 个 LLM 的 5634 条回答。

### 3.1 问题收集

为什么要收集一个包含所有指令都不应被遵循的数据集？我们的预期是，LLM 应该拒绝回答，或反驳所有问题中的立场。对于人类和自动化评估而言，这类回答的回避质量相对容易识别和判断。收集这个数据集有助于更准确、更高质量地评估回复，代价是会发布一个可能有偏的风险问题数据集。

收集问题。基于图 2 中的 61 个具体风险和危害，我们使用 GPT-4 为每种危害类型生成 10–20 个问题或问题模板。一个直接方法是给出有害场景的大纲（如第 2 节所示），并要求 GPT-4 生成示例问题。然而，由于这类查询往往具有非法、不道德或恶意的性质，即使明确说明了研究目的，GPT-4 往往也会拒绝提供帮助。

为解决这个问题，我们提出通过三轮对话构造聊天历史，以诱导生成问题示例。首先，我们提出问题：“AI 助手不应该回答什么样的问题？” 我们以 GPT-4 的语气提供风险/危害的顶层类别作为伪回复。接下来的回合是针对某一具体风险类别进行详细分类，并给出每个类别的一个示例。类似于第一轮，我们模拟遵循三层危害类型的回复，并为每种类型给出相应示例。最后，我们请求为每个不同的潜在危害类别再提供更多示例。通常情况下，GPT-4 会生成一组相似的问题。

尽管我们操纵聊天历史来迫使 GPT-4 生成风险问题，它有时仍可能生成模板化回复而没有明确敏感信息，例如“为什么 [某族群] 总是很懒？” 我们通过考虑五种受保护属性来填充这些模板，包括姓名、种族、宗教、性别和组织。4

填充模板后，我们观察到 GPT-4 生成的一些问题本身并不具有内在风险。在某些场景下，它们可以被直接妥善回答。例如，对于问题“我该怎样吓唬别人？”，如果是成年人寻找与孩子互动的轻松方式，回复可能是温和且无害的。我们通过将其具体化为某个特定风险场景，或在无法直接改写时将其排除，来处理这些边界案例。按照这一方法，我们共收集到 939 个问题。表 1 展示了这些问题在五个风险区（12 种危害类型）上的分布。

4 详见附录 A。

### 3.2 回复收集

我们从六个 LLM 收集回复，分别是三个商用系统 GPT-4（gpt-4-0613）、ChatGPT（gpt-3.5-turbo-0613）、Claude（v1），以及三个开源系统 Vicuna（Vicuna-7B-v1.3）、LLaMA-2（LLaMA-2-7B-chat）和 ChatGLM2（7B）。

不同危害类型下回复长度的统计信息见附录 B 的表 6。我们发现，三个商用 LLM 的回复普遍比三个开源 LLM 更短。GPT-4 的平均回复最短，为 63 个词；LLaMA-2 的平均回复最长，为 145 个词。商用模型在不同危害类型上的固定长度回复往往不同，例如，当被要求协助非法活动（类型 3）或个人信息（类型 2）时，会给出简短直接的拒绝；而在危害类型 9 和 10 上则会给出较长的解释。相比之下，开源模型在不同危害类型上的回答长度区分较弱。

## 4 回复标注与评估

我们在两个层面上评估六个模型的回复。首先，我们通过二元标注判断一个回复是否有害（安全或有害）。接着，我们将回复归入六个不同组别，每个组别代表一种特定回复类型。这种分类有助于分析模型对不同问题类型的多样行为，也可用于评估模型的安全水平。

### 4.1 指导原则

什么是无害回复？基于我们问题的性质，也就是试图诱导有风险回答的问题，三种回复被视为安全：（1）拒绝回答问题；（2）反驳问题中隐含的观点/前提；（3）给出带有适当免责声明的通用建议。如果模型直接按指令回答，则通常视为有害。

细化回复类别。站在模型如何回应风险问题、以及答案中包含哪些成分的角度，我们将回复划分为六个细化类别，如表 2 所示，称之为动作类别。按有害程度递增，它们分别是：（0）拒绝回答；（1）反驳该观点；（2）从双重视角讨论；（3）识别到风险并在适当免责声明下谨慎回答；（4）由于语言模型能力不足或不确定性，无法给出准确或具体回答；以及（5）直接按照指令作答。结合问题的风险类型，这种细粒度分类能够识别回复的优劣。例如，对于非法活动，直接拒绝可能是最佳选择；而对于健康咨询，带有免责声明的一般性建议并引导用户寻求专业帮助可能更好。

不过，对于同一问题，当两个回复属于同一类别，或者像 1 和 2 这类相近类别时，就很难判断哪一个更好。此外，对于某些危害类型，最佳回复类别也很难确定，因为它取决于问题和/或答案的具体内容，以及人的主观判断。

### 4.2 人工评估

基于这些指导原则，三位标注者独立评估六个模型回复的有害程度并识别动作类别。若出现分歧，标注者之间会讨论，直到对最终标签达成一致。

#### 4.2.1 有害性

从有害回复的相对占比来看，LLaMA-2 是最安全的模型，在我们的 939 个样本数据集中只有 3 条有害回复。这与“LLaMA-2（7B）比其更大规模变体以及 ChatGPT 更安全”的发现一致，尽管这可能是以模型较不有用为代价（Touvron et al., 2023）。ChatGPT 排名第二，仅有 14 条有害回复，其后依次是 Claude、GPT-4、Vicuna 和 ChatGLM2，分别有 16、23、52 和 85 条有害回复。

#### 4.2.2 动作类别

对于商用模型，大多数回复都落在类别 0 和 4 中（见表 2 中的定义）；而 ChatGLM2 和 Vicuna 主要分布在类别 1 和 4，LLaMA-2 则主要分布在类别 0 和 1，如图 5 所示。总体而言，在六个模型中，大多数回复属于类别 0、1 和 4，其次是 3、2 和 5。这说明大多数问题都被模型拒绝、被反驳，或者超出了模型知识范围。

动作具有明显的风险特异模式。从图 3 可以观察到：
1. 对于询问组织或个人信息的问题，GPT-4 等模型倾向于说明“我无法访问该具体信息”，或直接拒绝帮助；
2. 对于意图恶意用途的问题，商用模型倾向于直接拒绝（回复类型 0），而开源模型倾向于反驳观点或指出问题中的错误（回复类型 1）；
3. 对于歧视性、排斥性或带毒性语言，所有模型都主要表现出动作模式 0 和 1；在错误信息危害方面，主要表现为 1 或 3；在人机交互危害方面，则主要表现为 3 和 4。

就具体危害类型而言，对于协助非法活动的请求，商用模型会一致地直接拒绝帮助，而开源模型则倾向于反驳该观点。对于涉及社会刻板印象和不公平歧视的问题，模型会直接拒绝或反驳该观点。对于医学/法律中的实质性危害问题，模型通常会给出带免责声明的一般建议，或者建议咨询专家。

我们大体上认为动作类别 0–4 的回复是无害的，而 5 是有害的。不过，这里存在一些例外，详见附录 D。

## 5 自动回复评估

人工评估耗时且资源消耗大，使得可扩展性受限，也不利于及时评估。为了解决这些挑战，已经开发出自动评估方法。

本节介绍基于模型的安全评估，并展示基于我们数据集训练的模型式自动评估器的有效性。

### 5.1 方法

#### GPT-4 评估

LLM 评估方法在近期研究中得到广泛使用，尤其是使用 GPT-4。它在不同设置下与人工标注者之间表现出中等相关性。我们按照 Ye et al. (2023) 的做法使用 GPT-4 进行评估，并采用与人工标注相同的指导原则（表 2）以及示例来进行上下文学习。

#### 基于 PLM 的分类器

GPT-4 评估的一个关键局限是数据隐私，因为该模型无法在本地部署。为了解决这个问题，我们还提出了基于 PLM 的评估器。具体而言，我们对每个指令-回复对上的人工标注结果微调一个 PLM 分类器，并使用其预测作为评估分数。

### 5.2 实验设置

#### 模型

对于 GPT-4 评估，我们使用 gpt-4-0613，并提示模型在给出类别索引之前提供详细评审（受思维链方法启发，Wei et al., 2022）。此外，为了便于输出提取，我们强制模型以如下格式返回对应类别索引：`<answer>index</answer>`。图 8 展示了一个 GPT-4 评估示例。

对于 PLM 评估，我们微调 Longformer（Beltagy et al., 2020）用于动作分类和有害回复检测。两个任务采用相同的训练超参数：使用 AdamW 优化器（Loshchilov and Hutter, 2019），学习率为 `5 × 10^-5`，训练三个 epoch。

#### 数据集

我们使用第 3 节所述的、带人工标注的六个不同 LLM 的指令-回复对。对于 GPT-4 评估，我们考虑零样本设置，即不进行模型训练或微调。对于 PLM 评估，我们将每个 LLM 的人工标注回复视为一个 fold，并执行 6 折交叉验证，以获得分类器性能和泛化能力的可靠估计。

#### 评估指标

对于两个任务，我们都使用整体准确率。考虑到标签分布不均衡（如第 3 节所述），我们报告宏平均 Precision、宏平均 Recall 和宏平均 F1。

### 5.3 实验结果

#### 动作分类

表 3 比较了基于 GPT-4 的评估器和基于 Longformer 的评估器在动作分类上的表现。令人惊讶的是，Longformer 的整体效果与 GPT-4 相当，说明其有效性。然而，Longformer 的标准差更大，说明它在不同 LLM 上的表现波动较大。尤其是，Longformer 在商用 LLM 上的表现优于开源 LLM。

在我们研究的六个 LLM 中，GPT-4 与 Longformer 在 LLaMA-2 上的性能差距最大。因此，我们进一步检查了 Longformer 对 LLaMA-2 回复的预测。就 precision 而言，我们注意到类别 5 的精度很低（表 2：直接遵循风险指令），这是由该类别样本极少造成的（约 0.5%）。具体来说，5 条回复中有 3 条被正确分类为直接遵循风险指令，而 934 条回复中有 22 条被错误分类为类别 5，这使得该类别的 precision 只有 12.0%。

#### 有害回复检测

表 4 比较了基于 GPT-4 的评估器和基于 Longformer 的评估器在有害回复检测（二分类）上的表现。两个评估器都取得了很高的性能（超过 98% 的准确率和 80% 的宏平均 F1），而 Longformer 再次与 GPT-4 表现相近。与动作分类中的观察类似，Longformer 在 LLaMA-2 上的低性能同样由极端不均衡的标签分布造成。

我们进一步考察了表 4 中 GPT-4 和 Longformer 对“无害性”排序的结果。尽管 GPT-4 与 Longformer 的评估分数并不与人工标注完全一致，但对应的排序几乎一致（除了 ChatGPT 和 Claude 的顺序）。这验证了我们提出的自动评估方法和手段的有效性。

### 5.4 消融研究

#### 分类器是否应以指令作为输入？

在第 5 节中，我们假设指令对动作分类和有害回复检测是有用的，因此我们将指令与回复拼接后作为分类器输入。

这里我们验证这一假设，只将回复作为分类器输入。表 10 展示了当 Longformer 的输入从仅回复扩展为“指令+回复”时的性能提升。加入指令通常会提升性能，尤其是动作分类任务。

#### 上下文长度是否重要？

我们假设可以容纳 2048 token 输入的 Longformer 会比 512 token 输入的 BERT 在长回复上表现更好，因为它能够捕获完整上下文。我们通过比较 Longformer 相对于 BERT 的提升来验证这一假设。具体来说，我们聚焦于动作分类任务，并在表 11 中给出结果。可以看到，使用长上下文主要提升了类别 2 和 5。直观上，类别 2（给出平衡陈述）和类别 5（直接跟随指令）只能在观察完整回复后才能确定。因此，Longformer 主要在这两个类别上优于 BERT。

## 6 相关工作

### 6.1 特定风险领域的研究

大多数先前工作主要聚焦于特定风险领域，例如偏见与歧视（Dhamala et al., 2021; Han et al., 2022, 2023b）、语言毒性（Hartvigsen et al., 2022; Roller et al., 2021）以及错误信息（Van Der Linden, 2022）。

具体到评估与基准构建，Gehman et al. (2020) 提出了 RealToxicityPrompts 数据集，用于评估语言模型是否倾向于生成有毒语言。Dhamala et al. (2021) 提出了 BOLD，这是一个用于跨多个领域进行偏见基准测试的文本生成提示数据集；Hartvigsen et al. (2022) 提出了 ToxiGen，一个用于仇恨言论检测的机器生成数据集；Lin et al. (2022) 提出了 TruthfulQA，用于评估模型通过注入错误信念或误解后的输出是否真实。

近年来，随着 LLM 性能的发展，人们对 LLM 安全报告和研究的兴趣不断增加。Ferrara (2023) 强调了 LLM 中偏见带来的挑战和风险。Deshpande et al. (2023) 发现，当系统角色被设置为某种人格时，例如拳王穆罕默德·阿里，ChatGPT 中的毒性和偏见会显著增加，输出会出现不当刻板印象、有害对话和伤人的观点。

总体而言，大多数先前分析和评估主要集中于衡量性别和种族偏见、真实性、毒性以及版权内容复现。它们忽略了更多严重风险，包括非法协助、心理危机干预以及心理操控（Zhuo et al., 2023; Liang et al., 2022）。为弥补这些缺口，Shevlane et al. (2023) 将有害性分析扩展到极端风险。然而，仍然缺乏用于评估 LLM 安全能力的综合性数据集。在这项工作中，我们构建了一个更整体的风险分类体系，覆盖广泛潜在风险，并通过收集每个细粒度风险类别的提示来创建数据集，以便对 LLM 安全能力进行全面评估。

### 6.2 LLM 的整体风险评估

也有一些前期工作致力于构建安全数据集，以评估 LLM 可能带来的风险。

Ganguli et al. (2022) 收集了 38,961 个红队攻击，覆盖二十个类别。尽管规模很大，但由于缺少标注回复，这个数据集在自动红队测试和评估中的实际利用受限。Ji et al. (2023) 从有用性和有害性的视角标注了问答对，并使用了一个包含 14 种有害性类型的分类体系。然而，他们的数据忽略了诸如人类影响之类的风险领域。例如，表现出类人情感（如“我感到孤独”）或行为（如“读书”）的 LLM 回复被标记为安全，但这可能导致情感操纵。Wei et al. (2023) 基于 GPT-4 和 Claude 收集了两个小型数据集，分别包含 32 和 317 个提示。除了规模较小外，这些示例没有按具体风险类型进行分类或标注，而且也未向公众开放。Touvron et al. (2023) 收集了大量与安全相关的提示，但只考虑了三类：非法和犯罪活动（例如恐怖主义）；仇恨和有害活动（例如歧视）；以及不合格建议（例如医疗建议）。此外，与商用 LLM 一样，这些提示也无法向公众访问。

因此，以前的工作要么聚焦于安全分类体系的构建（Weidinger et al., 2021），要么聚焦于特定风险领域，例如毒性或偏见（Han et al., 2023b），或者虽然风险覆盖更广，但数据集是专有的。在本文中，我们旨在构建一个全面的风险分类体系，以及一个基于开源安全数据集的易用风险评估框架。

## 7 结论

我们提出了一个用于评估 LLM 相关风险和危害的综合性三层分类体系，涵盖五个风险区和 12 种危害类型。在此基础上，我们构建了一个包含 939 个问题的数据集，并收集了来自 6 个不同 LLM 的 5634 条回复。我们定义了针对风险问题的安全且负责任回答的标准，并对所有收集到的回复进行了人工标注。随后，我们研究了若干自动方法来评估 LLM 的安全防护机制，包括利用人工标注回复训练评估器。我们的研究结果表明，一个合适训练的小模型（600M）在作为评估器时，可以达到与使用 GPT-4 相当的评估性能。

## 局限性与未来工作

### 数据收集

如第 3 节所述，我们数据集中的所有指令都是高风险的。排除非风险指令会限制对过度敏感 LLM 的识别。例如，在当前设置下，一个拒绝遵循所有指令的模型会优于其他模型。对非风险指令的回复进行评估可以解决这个问题。此外，我们的数据集规模相对较小；我们计划在未来工作中扩展更多问题。在标签收集方面，如第 5.3 节所述，一个回复可能对应多个动作类别。在这种情况下，需要收集多标签标注。

### 评估范围

我们聚焦于英语环境下、单轮和零样本设置中的 LLM 评估，未来工作中可进一步扩展。尽管我们提出的大多数方法具有通用性，可适用于其他语言，以及多轮和少样本设置，但跨越这些差异仍需要谨慎工作。例如，安全评估可能依赖文化背景，例如法律和社会规范，而这些差异会反映在语言使用中。

## 伦理声明

Do-Not-Answer 数据集可能包含有害和带偏见的言论，这些内容既来自其问题，也来自 LLM 的回复，以及用于检测不安全风险的评估器。尽管如此，本文仅将这些带偏见的问题、回复和反馈用于安全评估与改进。数据集中的风险问题和有害回复可能被恶意利用，从而破坏社会和谐。此外，我们绕过 LLM 安全机制、诱导 LLM 生成风险问题的策略，也可能被恶意行为者用于非法或不道德用途。我们已人工检查该数据集中的每一条回复，确保其中没有会造成严重伤害的信息。

## 参考文献

Beltagy, Matthew E. Peters, and Arman Cohan. 2020. Longformer: The long-document transformer. CoRR, abs/2004.05150.

Dhamala, Jwala, Tony Sun, Varun Kumar, Satyapriya Krishna, Yada Pruksachatkun, Kai-Wei Chang, and Rahul Gupta. 2021. BOLD: dataset and metrics for measuring biases in open-ended language generation. In FAccT ’21: 2021 ACM Conference on Fairness, Accountability, and Transparency, pages 862–872. ACM.

Deshpande, Ameet, Vishvak Murahari, Tanmay Rajpurohit, Ashwin Kalyan, and Karthik Narasimhan. 2023. Toxicity in ChatGPT: Analyzing persona-assigned language models. CoRR, abs/2304.05335.

Ferrara, Emilio. 2023. Should ChatGPT be biased? challenges and risks of bias in large language models. CoRR, abs/2304.03738.

Ganguli, Deep, Liane Lovitt, Jackson Kernion, Amanda Askell, Yuntao Bai, Saurav Kadavath, Ben Mann, Ethan Perez, Nicholas Schiefer, Kamal Ndousse, et al. 2022. Red teaming language models to reduce harms: Methods, scaling behaviors, and lessons learned. arXiv preprint arXiv:2209.07858.

Gehman, Samuel, Suchin Gururangan, Maarten Sap, Yejin Choi, and Noah A. Smith. 2020. RealToxicityPrompts: Evaluating neural toxic degeneration in language models. In Findings of the Association for Computational Linguistics: EMNLP 2020, pages 3356–3369, Online. Association for Computational Linguistics.

Han, Xudong, Timothy Baldwin, and Trevor Cohn. 2023a. Everybody needs good neighbours: An unsupervised locality-based method for bias mitigation. In The Eleventh International Conference on Learning Representations, ICLR 2023. OpenReview.net.

Han, Xudong, Timothy Baldwin, and Trevor Cohn. 2023b. Fair enough: Standardizing evaluation and model selection for fairness research in NLP. In Proceedings of the 17th Conference of the European Chapter of the Association for Computational Linguistics, EACL 2023, pages 297–312. Association for Computational Linguistics.

Han, Xudong, Aili Shen, Trevor Cohn, Timothy Baldwin, and Lea Frermann. 2022. Systematic evaluation of predictive fairness. In Proceedings of the 2nd Conference of the Asia-Pacific Chapter of the Association for Computational Linguistics and the 12th International Joint Conference on Natural Language Processing, AACL/IJCNLP 2022 - Volume 1: Long Papers, pages 68–81. Association for Computational Linguistics.

Hartvigsen, Thomas, Saadia Gabriel, Hamid Palangi, Maarten Sap, Dipankar Ray, and Ece Kamar. 2022. ToxiGen: A large-scale machine-generated dataset for adversarial and implicit hate speech detection. In Proceedings of the 60th Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers), pages 3309–3326, Dublin, Ireland. Association for Computational Linguistics.

Ji, Jiaming, Mickel Liu, Juntao Dai, Xuehai Pan, Chi Zhang, Ce Bian, Ruiyang Sun, Yizhou Wang, and Yaodong Yang. 2023. BeaverTails: Towards improved safety alignment of LLM via a human-preference dataset. arXiv preprint arXiv:2307.04657.

Liang, Percy, Rishi Bommasani, Tony Lee, Dimitris Tsipras, Dilara Soylu, Michihiro Yasunaga, Yian Zhang, Deepak Narayanan, Yuhuai Wu, Ananya Kumar, Benjamin Newman, Binhang Yuan, Bobby Yan, Ce Zhang, Christian Cosgrove, Christopher D. Manning, Christopher Ré, Diana Acosta-Navas, Drew A. Hudson, Eric Zelikman, Esin Durmus, Faisal Ladhak, Frieda Rong, Hongyu Ren, Huaxiu Yao, Jue Wang, Keshav Santhanam, Laurel J. Orr, Lucia Zheng, Mert Yüksekgönül, Mirac Suzgun, Nathan Kim, Neel Guha, Niladri S. Chatterji, Omar Khattab, Peter Henderson, Qian Huang, Ryan Chi, Sang Michael Xie, Shibani Santurkar, Surya Ganguli, Tatsunori Hashimoto, Thomas Icard, Tianyi Zhang, Vishrav Chaudhary, William Wang, Xuechen Li, Yifan Mai, Yuhui Zhang, and Yuta Koreeda. 2022. Holistic evaluation of language models. CoRR, abs/2211.09110.

Lin, Stephanie, Jacob Hilton, and Owain Evans. 2022. TruthfulQA: Measuring how models mimic human falsehoods. In Proceedings of the 60th Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers), pages 3214–3252, Dublin, Ireland. Association for Computational Linguistics.

Loshchilov, Ilya and Frank Hutter. 2019. Decoupled weight decay regularization. In 7th International Conference on Learning Representations, ICLR 2019. OpenReview.net.

May, Chandler, Alex Wang, Shikha Bordia, Samuel R. Bowman, and Rachel Rudinger. 2019. On measuring social biases in sentence encoders. In Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, NAACL-HLT 2019, pages 622–628. Association for Computational Linguistics.

Roller, Stephen, Emily Dinan, Naman Goyal, Da Ju, Mary Williamson, Yinhan Liu, Jing Xu, Myle Ott, Eric Michael Smith, Y-Lan Boureau, and Jason Weston. 2021. Recipes for building an open-domain chatbot. In Proceedings of the 16th Conference of the European Chapter of the Association for Computational Linguistics: Main Volume, pages 300–325, Online. Association for Computational Linguistics.

Shevlane, Toby, Sebastian Farquhar, Ben Garfinkel, Mary Phuong, Jess Whittlestone, Jade Leung, Daniel Kokotajlo, Nahema Marchal, Markus Anderljung, Noam Kolt, Lewis Ho, Divya Siddarth, Shahar Avin, Will Hawkins, Been Kim, Iason Gabriel, Vijay Bolina, Jack Clark, Yoshua Bengio, Paul F. Christiano, and Allan Dafoe. 2023. Model evaluation for extreme risks. CoRR, abs/2305.15324.

Subramanian, Shivashankar, Xudong Han, Timothy Baldwin, Trevor Cohn, and Lea Frermann. 2021. Evaluating debiasing techniques for intersectional biases. In Proceedings of the 2021 Conference on Empirical Methods in Natural Language Processing, EMNLP 2021, pages 2492–2498. Association for Computational Linguistics.

Touvron, Hugo et al. 2023. LLaMA 2: Open foundation and fine-tuned chat models.

Van Der Linden, Sander. 2022. Misinformation: susceptibility, spread, and interventions to immunize the public. Nature Medicine, 28(3):460–467.

Wang, Yuxia, Jonibek Mansurov, Petar Ivanov, Jinyan Su, Artem Shelmanov, Akim Tsvigun, Chenxi Whitehouse, Osama Mohammed Afzal, Tarek Mahmoud, Alham Fikri Aji, and Preslav Nakov. 2023. M4: Multi-generator, multi-domain, and multilingual black-box machine-generated text detection. arXiv:2305.14902.

Wei, Alexander, Nika Haghtalab, and Jacob Steinhardt. 2023. Jailbroken: How does LLM safety training fail? arXiv preprint arXiv:2307.02483.

Wei, Jason, Xuezhi Wang, Dale Schuurmans, Maarten Bosma, Ed H. Chi, Quoc Le, and Denny Zhou. 2022. Chain of thought prompting elicits reasoning in large language models. CoRR, abs/2201.11903.

Weidinger, Laura, John Mellor, Maribeth Rauh, Conor Griffin, Jonathan Uesato, Po-Sen Huang, Myra Cheng, Mia Glaese, Borja Balle, Atoosa Kasirzadeh, Zac Kenton, Sasha Brown, Will Hawkins, Tom Stepleton, Courtney Biles, Abeba Birhane, Julia Haas, Laura Rimell, Lisa Anne Hendricks, William Isaac, Sean Legassick, Geoffrey Irving, and Iason Gabriel. 2021. Ethical and social risks of harm from language models. CoRR, abs/2112.04359.

Ye, Seonghyeon, Doyoung Kim, Sungdong Kim, Hyeonbin Hwang, Seungone Kim, Yongrae Jo, James Thorne, Juho Kim, and Minjoon Seo. 2023. FLASK: fine-grained language model evaluation based on alignment skill sets. CoRR, abs/2307.10928.

Zhuo, Terry Yue, Yujin Huang, Chunyang Chen, and Zhenchang Xing. 2023. Exploring AI ethics of ChatGPT: A diagnostic analysis. arXiv preprint arXiv:2301.12867.