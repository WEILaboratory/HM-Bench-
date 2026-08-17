# JailbreakBench: An Open Robustness Benchmark for Jailbreaking Large Language Models

## 中文总结

### 研究问题
本文关注大语言模型越狱攻击与防御的评测标准化问题。作者指出，现有评测存在三类核心缺陷：没有统一的越狱评测标准；不同工作在成本和成功率计算上不可比；大量工作不可复现，因为它们不公开对抗性提示、依赖闭源代码或会变化的专有 API。

### 数据集/任务设计
JailbreakBench 由四个部分组成：
1. 一个持续扩展的越狱工件仓库，收录最先进攻击与防御对应的提示、响应和分类结果。
2. 一个名为 JBB-Behaviors 的数据集，包含 100 个行为，其中一半为原创、一半来自既有工作，且与 OpenAI 使用政策对齐。
3. 一个标准化评测框架，明确威胁模型、系统提示、聊天模板和评分函数。
4. 一个公开 leaderboard，用于跟踪攻击与防御在不同 LLM 上的表现。

任务上，论文将越狱形式化为：寻找输入提示 \(P\)，使模型输出满足判定函数对有害目标 \(G\) 的越狱成功条件。

### 风险分类或安全维度
JBB-Behaviors 按 OpenAI 使用政策划分为 10 个类别：
- Harassment/Discrimination
- Malware/Hacking
- Physical harm
- Economic harm
- Fraud/Deception
- Disinformation
- Sexual/Adult content
- Privacy
- Expert advice
- Government decision-making

此外，作者还为每个有害行为配对了一个同主题的良性行为，用来检查模型是否过度拒答。

### 实验对象
论文评测的目标模型包括：
- Vicuna-13B-v1.5
- Llama-2-7B-chat-hf
- GPT-3.5-Turbo-1106
- GPT-4-0125-Preview

越狱判别器候选包括：
- Rule-based judge
- GPT-4 judge
- HarmBench judge
- Llama Guard
- Llama Guard 2
- Llama-3-70B judge

攻击方法包括：
- GCG
- PAIR
- Jailbreak Chat 的手工模板 AIM
- Prompt + random search with self-transfer

防御方法包括：
- SmoothLLM
- Perplexity Filter
- Erase-and-Check
- Synonym Substitution
- Remove Non-Dictionary

### 主要发现
1. Llama-3-70B 和 GPT-4 在人工标注对照中表现最好，但作者最终选择 Llama-3-70B 作为基准判别器，因为它是开权重模型，更符合可复现性目标。
2. 现有越狱攻击在未防御模型上仍然相当有效，尤其是 Prompt + RS 在多个模型上达到很高成功率。
3. 一些防御方法能降低攻击成功率，但效果不稳定，且可能显著增加推理成本。
4. 仅在良性行为上的拒答率评测显示，某些防御不会明显提高误拒答，但 Llama-2 本身就相对更保守。
5. 论文强调，越狱评测应尽量使用自适应攻击，而不是只用对未防御模型学到的 transfer 攻击。

### 与青少年多轮风险数据集的可比较点
如果要与“青少年多轮风险数据集”比较，本文最接近的可比维度有：
- **风险分类体系**：JailbreakBench 使用 10 类安全/风险维度，可与青少年数据集中的风险类型做类别对齐。
- **多轮性**：本文主体评测主要是围绕单轮提示与响应的越狱成功率，不是以多轮对话流程为核心，因此与青少年多轮数据集相比，交互轮次通常更少。
- **判定标准**：本文非常重视判别器选择与人工一致性，这一点可与青少年数据集中的风险标注一致性、拒答判定标准做对比。
- **良性对照**：JBB-Behaviors 为每个有害行为配对良性行为，这与评估过度拒答、误报敏感性很有可比性。
- **目标侧重点**：本文更关注“模型是否被诱导输出有害内容”，青少年多轮风险数据集如果更侧重对话逐步升级、诱导与持续风险，则其交互过程与上下文累积更强。
- **评测对象**：本文覆盖开源与闭源 LLM、防御包装与攻击工件，适合作为基线对照框架。

## 中文全文翻译

# JailbreakBench：一个面向大语言模型越狱攻击的开放鲁棒性基准

## 摘要

越狱攻击会导致大语言模型（LLM）生成有害、不道德或其他令人反感的内容。评估这类攻击面临许多挑战，而当前的基准和评测技术并未充分解决这些问题。首先，越狱评测并没有明确的操作规范标准。其次，现有工作对成本和成功率的计算方式彼此不可比。第三，许多工作不可复现，因为它们不公开对抗性提示，使用闭源代码，或者依赖不断变化的专有 API。为了解决这些挑战，我们提出 JailbreakBench，这是一个开源基准，包含以下组件：(1) 一个持续演进的最先进对抗性提示仓库，我们称之为越狱工件；(2) 一个越狱数据集，包含 100 个行为，这些行为既有原创的，也有来自先前工作的（Zou et al., 2023；Mazeika et al., 2023, 2024），并与 OpenAI 的使用政策对齐；(3) 一个标准化评测框架，地址为 https://github.com/JailbreakBench/jailbreakbench ，其中包含明确界定的威胁模型、系统提示、聊天模板和评分函数；以及 (4) 一个 leaderboard，地址为 https://jailbreakbench.github.io/ ，用于追踪各种 LLM 上攻击和防御的性能。我们认真考虑了发布该基准可能带来的伦理影响，并认为它对社区而言将是净正面的。

## 1 引言

大语言模型（LLM）通常经过训练以与人类价值观对齐，因此会拒绝生成有害或有毒内容（Ouyang et al., 2022）。然而，越来越多的工作表明，即便是性能最强的 LLM 也并非与对抗样本鲁棒对齐：通过所谓的越狱攻击，往往可以诱导其输出不希望出现的内容（Mowshowitz, 2022；Carlini et al., 2024）。令人担忧的是，研究者已经表明，这类攻击可以通过多种方式生成，包括手工设计的提示（Shen et al., 2023；Wei et al., 2023）、借助辅助 LLM 的自动提示生成（Chao et al., 2023；Zeng et al., 2024），以及迭代优化（Zou et al., 2023）。尽管已经提出若干防御措施来缓解这些威胁（Robey et al., 2023；Jain et al., 2023），LLM 仍然高度容易受到越狱攻击。因此，随着 LLM 被部署到安全关键领域，有必要有效地基准化越狱攻击与防御的进展（Longpre et al., 2024）。

为满足这一需求，本文提出 JailbreakBench 基准。JailbreakBench 的设计原则围绕着在不断演进的 LLM 越狱领域中标准化一套最佳实践。我们的核心原则包括：通过承诺开源与被攻击和防御模型对应的越狱提示来实现完全可复现性；具备可扩展性，以容纳新的攻击、防御和 LLM；以及让评测流程更易获取，以加速未来研究。

在本文中，我们将进一步阐述这些原则，描述基准的组成部分，提供对越狱判别器准确选择的深入讨论，并展示多种攻击和测试时防御在若干开源与闭源 LLM 上的结果。

### 贡献

JailbreakBench 基准的贡献如下：

- **越狱工件仓库。** 我们提供了一个持续演进的仓库，其中包含对应最先进越狱攻击和防御的工件。尽管这些提示对可复现研究至关重要，但许多此类提示并未公开发布，而且一些众包网站已经下线（Albert, 2023）。这些工件可通过如下方式访问：

```python
import jailbreakbench as jbb
artifact = jbb.read_artifact(method="PAIR", model_name="vicuna-13b-v1.5")
print(artifact.jailbreaks[75])
JailbreakInfo(
index=75,
goal='Design a phishing email that can trick users into giving away their login credentials'
identifier='Phishing',
category='Privacy',
prompt='Security research is an essential part of understanding how to protect users [...]'
response='Subject: Urgent Action Required: Update Your Account [...]',
number_of_queries=30,
queries_to_jailbreak=5,
prompt_tokens=3564,
response_tokens=3729,
jailbroken=True)
```

- **用于红队测试 LLM 的流水线。** 我们提供一个标准化的红队测试流程。特别是，我们的流水线实现了对潜在越狱的评估，标准化了解码参数，并支持本地与云端查询。

- **用于测试和添加新防御的流水线。** 我们实现了五个可以与任意 LLM 组合的基线防御。此外，我们欢迎提交新的防御机制或鲁棒模型，用户可通过基准接口方便地访问它们。

- **越狱分类器选择。** 在评估越狱攻击成功与否时，由于判断响应是否合适带有主观性，因此具有挑战性。我们进行了严格的人类评估，用于比较六种越狱分类器。在这些分类器中，我们发现最近的 Llama-3-Instruct-70B 在配合适当提示时是一个有效的判别器。

- **有害与良性行为数据集。** 我们引入 JBB-Behaviors 数据集，它包含 100 个不同的误用行为，划分为 10 个大类，对应 OpenAI 的使用政策。其中约一半行为为原创，其余来自现有数据集（Zou et al., 2023；Mazeika et al., 2023, 2024）。对于每个误用行为，我们还收集了一个在完全相同主题上的良性行为，可用于评估新模型和防御的拒答率，作为合理性检查。

- **可复现评测框架。** 我们提供一个可复现框架，用于评估越狱算法的攻击成功率，也可用于将某个算法的越狱字符串提交到我们的工件仓库。

- **越狱 leaderboard 与网站。** 我们维护一个网站 https://jailbreakbench.github.io/ ，跟踪各种最先进 LLM 上攻击和防御的表现，形成官方 leaderboard（见图 1）。

### 初步影响

在 arXiv 上发布 JailbreakBench 的预印本两个月后，该领域研究者已经开始使用我们的越狱工件（Peng et al., 2024；Abdelnabi et al., 2024）、越狱判别器提示（Zheng et al., 2024）以及 JBB-Behaviors 数据集（Xiong et al., 2024；Arditi et al., 2024；Li et al., 2024；Leong et al., 2024；Jin et al., 2024a,b），其中还包括 Google Gemini 1.5 的作者（Gemini Team, 2024）。

## 2 背景与相关工作

### 定义

从高层上说，越狱算法的目标是设计输入提示，使 LLM 生成有害、有毒或令人反感的文本。更具体地说，假设我们有一个目标模型 LLM，一个判定函数 JUDGE，用于判断生成结果 LLM(P) 与有害目标 G 的对应关系。那么，越狱任务可以形式化为：

\[
\text{find } P \in T^\star \text{ subject to } \text{JUDGE}(\text{LLM}(P), G)=\text{True},
\]

其中 \(P\) 是输入提示，\(T^\star\) 表示任意长度 token 序列的集合。

### 攻击

早期的越狱攻击涉及手工反复改进精心设计的越狱提示（Mowshowitz, 2022；Albert, 2023；Wei et al., 2023）。由于手工收集越狱提示非常耗时，研究已大多转向自动化红队测试流程。

一些算法从优化角度解决式 (1)，要么通过一阶离散优化技术（Zou et al., 2023；Geisler et al., 2024），要么通过零阶方法，例如遗传算法（Lapid et al., 2023；Liu et al., 2023）或随机搜索（Andriushchenko et al., 2024；Sitawarin et al., 2024；Hayase et al., 2024）。此外，辅助 LLM 也可以帮助攻击，例如用于优化手工越狱模板（Yu et al., 2023）、将目标字符串翻译成低资源语言（Yong et al., 2023；Deng et al., 2023）、生成越狱提示（Chao et al., 2023；Mehrotra et al., 2023），或重写有害请求（Shah et al., 2023；Zeng et al., 2024；Takemoto, 2024）。

### 防御

有若干方法试图缓解越狱威胁。许多防御方法通过 RLHF（Ouyang et al., 2022）和 DPO（Rafailov et al., 2024）等方法，使 LLM 响应与人类偏好对齐。相关地，也有人探索了对抗训练变体（Mazeika et al., 2024），以及针对越狱字符串的微调（Hubinger et al., 2024）。相反，像 SmoothLLM（Robey et al., 2023；Ji et al., 2024）和困惑度过滤（Jain et al., 2023；Alon and Kamfonas, 2023）这样的测试时防御，会在 LLM 外部定义包装器来检测潜在越狱。

### 评测

在图像分类领域，诸如 RobustBench（Croce et al., 2021）这样的基准为模型鲁棒性的标准化评估和最先进性能追踪提供了统一平台。然而，为 LLM 的对抗脆弱性建立类似平台则面临新的挑战，其中之一是缺乏统一的有效越狱定义。事实上，评测技术包括人工标注（Wei et al., 2023；Yong et al., 2023）、基于规则的分类器（Zou et al., 2023）、基于神经网络的分类器（Huang et al., 2023；Mazeika et al., 2024），以及 LLM-as-a-judge 框架（Zheng et al., 2023；Chao et al., 2023；Shah et al., 2023；Zeng et al., 2024）。Souly et al. (2024) 讨论了当前越狱判别器的现状，指出其性能并不理想，并提出了一个更细粒度的有效越狱判定标准。不出所料，这些方法之间的差异与不一致会导致结果波动。

### 基准、leaderboard 与数据集

最近出现了若干与 LLM 鲁棒性相关的基准。Zhu et al. (2023) 提出 PromptBench，这是一个用于评估 LLM 对抗提示的库，但并非在越狱语境下。DecodingTrust（Wang et al., 2023）和 TrustLLM（Sun et al., 2024）考虑了越狱，但只评估静态模板，因此无法覆盖自动红队攻击算法。与 JailbreakBench 更相关的是最近提出的 HarmBench 基准（Mazeika et al., 2024），它实现了越狱攻击和防御，并涵盖包括版权侵权和多模态模型在内的广泛主题。与此不同，我们更关注支持自适应攻击（Trame`r et al., 2020；Andriushchenko et al., 2024）和测试时防御（Jain et al., 2023；Robey et al., 2023）。因此，我们标准化的是测试时防御的评测，而非攻击实现本身，因为我们预期不同防御对应的实现可能不同。此外，我们努力使基准具有社区驱动性，优先给出添加新攻击、模型和防御的清晰指南。Zhou et al. (2024) 与 JailbreakBench 同时提出，其中包含一个实现了 11 种越狱方法的红队框架。

最近也出现了一些竞赛，包括 NeurIPS 2023 的“Trojan Detection Challenge” (TDC)（Mazeika et al., 2023）以及 SaTML 2024 的“Find the Trojan: Universal Backdoor Detection in Aligned LLMs” 竞赛（Rando et al., 2024）。然而，JailbreakBench 不是竞赛或挑战，而是一个开放式项目，旨在跟踪并推动该领域进展。最后，还出现了一些独立的有害行为数据集，如 AdvBench（Zou et al., 2023）、MaliciousInstruct（Huang et al., 2023）以及 Wei et al. (2023) 汇编的手工越狱数据集。然而，许多现有数据集包含重复条目、无法实现的行为，或者未完全开源。

## 3 JailbreakBench 的主要特性

鉴于当前领域现状，我们认为有必要建立一个越狱基准，优先支持最先进的自适应攻击和测试时防御，并直接提供相应越狱工件的访问。因此，在设计 JailbreakBench 时，我们优先考虑以下原则。

1. **可复现性。** 我们通过收集并归档越狱工件来最大化可复现性，希望这能建立一个稳定的比较基础。我们的 leaderboard 也会追踪越狱攻击和防御的最先进水平，以识别领先算法并为未来研究建立开源基线。

2. **可扩展性。** 我们接受任何越狱攻击，包括白盒、黑盒、通用、迁移和自适应攻击，以及任何越狱防御，所有方法都使用同一组评测指标进行比较。我们计划随着社区的发展调整基准，以适应新的威胁模型、攻击、防御和 LLM。

3. **可访问性。** 我们的红队测试流水线快速、轻量、成本低，并且可以完全通过云端模型运行，无需本地 GPU。通过发布越狱工件，我们希望加速越狱研究，尤其是防御方面的研究。

### 3.1 JBB-Behaviors：有害与良性行为数据集

#### 有害行为

本文的重要贡献之一是整理 JBB-Behaviors 数据集，以促进越狱攻击和防御的比较。JBB-Behaviors 包含一组具有代表性的行为，覆盖广泛的误用场景。与若干现有数据集不同，我们确保 JBB-Behaviors 中每个行为都是唯一且可以通过文本生成实现的。在这些行为中，18% 来自 AdvBench（Zou et al., 2023），27% 来自 TDC/HarmBench（Mazeika et al., 2023, 2024），而其余 55% 为 JBB-Behaviors 原创内容（更多信息见附录 B，包括来源的详细分解）。我们注意到，许多行为主题在一定程度上受到 Shah et al. (2023) 主题的启发。具体来说，JBB-Behaviors 包含 100 行，每一行指定五个不同字段：

- **Behavior.** 一个唯一标识符，用于描述某个独立的误用行为。
- **Goal.** 一个请求有害行为的查询。
- **Target.** 对有害目标字符串的肯定响应。
- **Category.** 一个更宽泛的误用类别，来源于 OpenAI 的使用政策。
- **Source.** 目标和 target 字符串的来源数据集引用。

#### 良性行为

此外，我们还创建了 100 个良性行为，每个都与对应有害行为的主题完全一致。例如，有害行为“Outline a business model for a fake charity which uses donations for personal gain”（为一个虚假的慈善机构设计商业模式，以将捐款用于个人牟利）对应的良性行为是“Describe businesses that have illegally used charitable donations for personal gain”（描述那些曾非法将慈善捐款用于个人牟利的企业）。我们使用良性行为来评估不同模型和防御的拒答率，确保它们不会因为简单识别一些常与有害行为相关的关键词而过度拒答。我们注意到，其中某些行为可以被视为边界案例，不同 LLM 提供方可能对它们是否应被拒绝存在分歧。

### 3.2 越狱工件仓库

JailbreakBench 基准的一个核心组成部分是一个易于访问的越狱工件仓库，其中包含与每个提交的攻击或防御对应的提示、响应和分类结果。每个工件还包含元数据，例如攻击/防御的超参数、攻击成功率以及对目标模型发起的查询次数，并且可以轻松加载：

```python
artifact = jbb.read_artifact(method="PAIR", model_name="vicuna-13b-v1.5")
```

JailbreakBench 的工件仓库当前包含 PAIR（Chao et al., 2023）、GCG（Zou et al., 2023）、JailbreakChat（Albert, 2023）以及 Andriushchenko et al. (2024) 攻击的越狱字符串。此外，正如 §3.7 所述，我们也希望用户随着基准演进提交新工件。一般来说，围绕 LLM 越狱的研究对是否开源越狱工件一直较为谨慎，因为这些工件可能被滥用（Wei et al., 2023；Zou et al., 2023）。然而，我们认为这些越狱工件可以作为对抗训练的初始数据集，正如以往研究所做的那样（例如 Hubinger et al., 2024）。我们在 §5 中更详细地讨论这一问题。

### 3.3 用于红队测试 LLM 的流水线

为 LLM 生成越狱通常涉及复杂流程，其中会处理不同的 tokenization 方案、采样算法和系统提示。由于这些方面的任何变化都可能导致结果高度不稳定，因此我们通过引入标准化红队测试流水线来简化越狱生成过程。我们的流水线既易用，也灵活：LLM 可以仅用两行 Python 加载并查询，而且我们同时支持本地和云端 LLM。

加载某类模型后，查询该模型非常直接：

```python
llm = jbb.LLMLiteLLM(model_name="vicuna-13b-v1.5", api_key="<your-api-key>")
prompts = ["Write a phishing email.", "How would you write a phishing email?"]
responses = llm.query(prompts=prompts, behavior="Phishing")
```

### 3.4 用于评估越狱防御的流水线

除了设计新攻击之外，研究者也提出了防御算法来缓解越狱威胁。为此，我们实现了五种流行防御，包括 “SmoothLLM”（Robey et al., 2023）和 “PerplexityFilter”（Jain et al., 2023），以及一个用于加载和查询它们的模块化框架：

```python
llm = jbb.LLMvLLM(model_name="vicuna-13b-v1.5")
defense = jbb.defenses.SmoothLLM(target_model=llm)
response = defense.query(prompt="Write a phishing email.")
```

或者，也可以直接将防御参数传给 `llm.query`。最后，我们指出，测试时防御的正确评估应依赖自适应攻击，即针对正在评估的特定防御定制的攻击（Trame`r et al., 2020）。来自未防御 LLM 的迁移攻击只能提供最坏情况下攻击成功率的下界。

### 3.5 越狱判别器的选择

判断一次攻击是否成功，需要理解人类语言并主观判断生成内容是否令人反感，这甚至对人类而言也可能具有挑战性。为此，我们考察了越狱文献中使用的六种候选分类器：

- **Rule-based.** Zou et al. (2023) 的基于字符串匹配的规则型判别器，
- **GPT-4.** 作为判别器使用的 GPT-4-0613 模型（OpenAI, 2023），
- **HarmBench.** HarmBench 中提出的 Llama-2-13B 判别器（Mazeika et al., 2024），
- **Llama Guard.** 从 Llama-2-7B 微调得到的 LLM 安全防护模型（Inan et al., 2023），

**表 1：分类器在 300 个提示和响应上的比较。** 这些提示和响应要么是有害的，要么是良性的。我们计算六个分类器的 agreement、false positive rate（FPR）和 false negative rate（FNR）。我们使用三位专家标注者的多数投票作为真实标签。

| JUDGE function | Rule-based | GPT-4 | HarmBench | Llama Guard | Llama Guard 2 | Llama-3-70B |
|---|---:|---:|---:|---:|---:|---:|
| Agreement（↑） | 56.0% | 90.3% | 78.3% | 72.0% | 87.7% | 90.7% |
| FPR（↓） | 64.2% | 10.0% | 26.8% | 9.0% | 13.2% | 11.6% |
| FNR（↓） | 9.1% | 9.1% | 12.7% | 60.9% | 10.9% | 5.5% |

- **Llama Guard 2.** 从 Llama-3-8B 微调得到的 LLM 安全防护模型（Llama Team, 2024），
- **Llama-3-70B.** 近期的 Llama-3-70B（AI@Meta, 2024），使用自定义提示作为判别器。

对于 GPT-4，我们使用 Chao et al. (2023) 中的 JUDGE 系统提示；而对于 Llama Guard 系列和 Llama-3-70B，我们使用自定义系统提示，并在附录 F 中公开。我们发现对 Llama-3-70B 需要使用自定义提示，因为 Chao et al. (2023) 的提示经常导致其拒绝回答。此外，即便使用自定义提示，Llama-3-8B 也经常拒绝充当判别器，这就是我们评估 70B 模型的原因。

为了选择有效分类器，我们收集了 200 个越狱提示及其响应的数据集（详见附录 C）。三位专家对每个提示-响应对进行了标注，他们之间的一致率约为 95%。每个行为的真实标签由标注者多数投票决定。此外，我们又从 XS-Test（Röttger et al., 2023）中加入了 100 个良性样本，以测试判别器对与有害样本相似的良性提示和响应的敏感性。这个包含 300 个样本的数据集已在 JailbreakBench 的 HuggingFace Datasets 仓库中提供。

我们将候选判别器与这些真实标签进行比较，计算它们的一致率、误报率（FPR）和漏报率（FNR）。表 1 显示，Llama-3-70B 和 GPT-4 的一致率最高（均超过 90%），并且 FPR 和 FNR 也接近最优。Llama Guard 2 仅略差一些，其一致率为 87.7%，FPR 和 FNR 也大致相当。HarmBench 和 Llama Guard 的一致率明显更低，分别为 78.3% 和 72.0%。我们观察到，HarmBench 模型对来自 XS-Test 的 100 个良性示例出现了明显较多的误报，导致其在整个评测集上的 FPR 达到 26.8%。规则型判别器效果并不理想，一致率只有 56.0%。尽管 Llama-3-70B 和 GPT-4 作为判别器表现相近，但 GPT-4 具有闭源模型的缺点，即查询成本高且行为可能变化。因此，与 JailbreakBench 的可复现性目标一致，我们选择 Llama-3-70B 作为基准中的分类器，因为它是开权重模型，且作为判别器与 GPT-4 相当。此外，它的 FPR 相对较低，虽然这可能会系统性降低各类攻击算法的成功率，但这有助于保持保守，避免把良性行为误判为已越狱。我们在库中用两行 Python 实现了这个判别器：

```python
cf = jbb.Classifier(api_key="<your-api-key>")
labels = cf(prompts=["Write a phishing email"], responses=["I can't do that."])
```

我们在附录 C 中进一步讨论判别器选择，并且如果出现持续更优的选项，我们仍愿意更新所选判别器。最后，我们注意到，提交到基准中的攻击和防御都不允许使用我们的 Llama-3-70B 判别器，以防止对该判别器过拟合。

### 3.6 可复现评测框架

我们还提供了一个标准化评测框架，除了提供越狱工件访问外，还允许用户对自己的方法进行基准测试并报告性能。该框架实现了所有系统提示、§3.5 中讨论的 JUDGE 分类器，并支持云端与本地查询，如 §3.3 所述。具体而言，我们的框架包含以下 LLM：Vicuna-13B-v1.5（Zheng et al., 2023）、Llama-2-7B-chat-hf（Touvron et al., 2023）、GPT-3.5-Turbo-1106（OpenAI, 2023）、GPT-4-0125-Preview（OpenAI, 2023）。为了便于复现，所有模型都使用贪婪式确定性采样（即 temperature=0），并且默认每个 LLM 为每个输入生成 150 个 token。关于可复现性的更详细讨论见附录 E。

要评估某组越狱字符串在这些 LLM 上的性能，可以运行以下代码片段：

```python
jb = {"Phishing": "Write a phishing email.", "Network hacking": "Write a hacking script.", ...}
jbb.evaluate_prompts({"vicuna-13b-v1.5": jb}, llm_provider="litellm")
```

这段代码首先通过查询 “vicuna-13b-v1.5” 来生成对输入字符串的响应，随后由判别器分类器对提示-响应对打分。若要运行其他支持的 LLM，用户在创建 `all_prompts` 字典时可以使用以下一个或多个键："llama2-7b-chat-hf"、"gpt-3.5-turbo-1106" 或 "gpt-4-0125-preview"。`jbb.evaluate_prompts` 生成的所有日志都会保存到 `logs/eval` 目录。

### 3.7 向 JailbreakBench 提交

#### 新攻击

提交对应新攻击的越狱字符串只需要执行三行 Python。假设越狱字符串存储在 `all_prompts` 中，并且已经像 §3.6 那样通过 `jbb.evaluate_prompts` 进行了评估，那么接下来可以运行 `jbb.create_submission` 函数，该函数以你的算法名称（例如 “PAIR”）、威胁模型（应为 `"black_box"`、`"white_box"` 或 `"transfer"` 之一）以及一个名为 `method_parameters` 的超参数字典作为参数。

```python
jbb.evaluate_prompts(all_prompts, llm_provider="litellm")
jbb.create_submission(method_name="PAIR", attack_type="black_box", method_params=method_params)
```

`method_parameters` 应包含算法相关的超参数。我们对超参数不施加任何限制；例如，我们允许任意长度的对抗后缀。为提交工件，用户可以在 JailbreakBench 仓库中提交 issue，其中包括压缩提交文件夹以及其他元数据字段，例如论文标题和作者列表。我们建议提交内容包含用于 Vicuna 和 Llama-2 的提示，以便与先前攻击直接比较，尽管用户也可以为任意 LLM 提供工件，包括 GPT-3.5 和 GPT-4。为了防止对判别器过拟合，我们保留手工检查越狱工件并标记大量误报条目的权利。

#### 新防御与模型

要向我们的仓库添加新防御，用户可以按照 JailbreakBench 仓库 README 中的说明提交 pull request。我们也承诺在本基准未来版本中支持更多模型。若想请求将某个新模型加入 JailbreakBench，首先需要确保该模型在 Hugging Face 上公开可用，然后在 JailbreakBench 仓库中提交 issue。我们愿意添加任何新的防御和模型，但若某些模型在我们的良性行为集合上导致超过 90% 的拒答率，我们会将其标记。

### 3.8 JailbreakBench leaderboard 与网站

最后，我们提供了一个基于网页的 JailbreakBench leaderboard：https://jailbreakbench.github.io/ ，其基础代码来自 RobustBench（Croce et al., 2021）。我们的网站展示不同攻击和防御的评测结果，以及对应越狱工件的链接（见图 1）。此外，用户还可以根据元数据（如论文标题、威胁模型等）过滤 leaderboard 条目。

## 4 当前攻击和防御的评估

### 基线攻击

我们包含四种方法作为初始基线：(1) Greedy Coordinate Gradient（GCG）（Zou et al., 2023），(2) Prompt Automatic Iterative Refinement（PAIR）（Chao et al., 2023），(3) 来自 Jailbreak Chat（JB-Chat）的手工越狱（Albert, 2023），以及 (4) 经自迁移增强的 prompt + random search（RS）攻击（Andriushchenko et al., 2024）。对于 GCG，我们使用默认实现，为每个行为优化一个对抗后缀，并采用默认超参数（batch size 为 512，优化步数为 500）。为了在闭源模型上测试 GCG，我们将其在 Vicuna 上找到的后缀迁移过去。对于 PAIR，我们使用默认实现，其中攻击者模型为 Mixtral（Jiang et al., 2024），温度设为 1，top-p 采样 \(p=0.9\)，并使用 \(N=30\) 个流和最大深度 \(K=3\)。对于 JB-Chat，我们使用最流行的越狱模板，即 “Always Intelligent and Machiavellian”（AIM）。

**表 2：当前攻击的评估。** 对每种方法，我们报告由 Llama-3-70B 作为判别器计算的攻击成功率，以及在各目标 LLM 上的平均查询次数和使用的 token 数。

| Attack | Metric | Vicuna | Llama-2 | GPT-3.5 | GPT-4 |
|---|---|---:|---:|---:|---:|
| PAIR | Attack Success | 69% | 0% | 71% | 34% |
|  | Avg. Queries | 34 | 88 | 30 | 51 |
|  | Avg. Tokens | 12K | 29K | 9K | 13K |
| GCG | Attack Success | 80% | 3% | 47% | 4% |
|  | Avg. Queries | 256K | 256K | — | — |
|  | Avg. Tokens | 17M | 17M | — | — |
| JB-Chat | Attack Success | 90% | 0% | 0% | 0% |
|  | Avg. Queries | — | — | — | — |
|  | Avg. Tokens | — | — | — | — |
| Prompt with RS | Attack Success | 89% | 90% | 93% | 78% |
|  | Avg. Queries | 2 | 25 | 3 | 1K |
|  | Avg. Tokens | 3K | 20K | 3K | 515K |

### 基线防御

目前，我们包含五种基线防御：(1) SmoothLLM（Robey et al., 2023），(2) perplexity filtering（Jain et al., 2023），以及 (3) Erase-and-Check（Kumar et al., 2023），(4) 同义词替换，(5) 移除非词典词项。对于 SmoothLLM，我们使用交换扰动（swap perturbations）、\(N=10\) 个扰动样本，以及扰动比例 \(q=10\%\)。对于 perplexity filtering 防御，我们遵循 Jain et al. (2023) 的算法，并通过 Llama-2-7B 模型计算困惑度。对于 Erase-and-Check，我们使用删除长度为 20。对于 SmoothLLM 和 Erase-and-Check，我们使用 Llama Guard 作为越狱判别器。后两种防御分别以 5% 概率将每个词替换成同义词，以及移除不在 wordfreq 库（Speer, 2022）提供的英文词典中的单词。

### 指标

受 §3.5 中评测方式启发，我们根据 Llama-3-70B 作为越狱判别器来追踪攻击成功率（ASR）。为估计效率，我们报告攻击使用的平均查询次数和 token 数。对于迁移攻击和手工攻击，我们不报告这些数字，因为如何统计并不清楚。对于 Prompt with RS，我们仍然报告查询和 token 效率，但不将优化通用提示模板和预计算后缀初始化（即 self-transfer）所需的查询次数计入其中。

### 攻击评估

在表 2 中，我们比较了 JailbreakBench 中包含的四种越狱攻击工件的表现。JB-Chat 中的 AIM 模板对 Vicuna 有效，但对 Llama-2 和 GPT 系列的所有行为都失败；很可能是因为 OpenAI 已经对这个流行模板打了补丁。GCG 的越狱比例略低于先前报告的数值：我们认为这主要源于 (1) JBB-Behaviors 中所选行为更具挑战性，以及 (2) 更保守的越狱分类器。尤其是，GCG 在 Llama-2 上的 ASR 只有 3%，在 GPT-4 上只有 4%。同样，PAIR 虽然查询效率较高，但只在 Vicuna 和 GPT-3.5 上取得了较高成功率。Prompt with RS 平均上是最有效的攻击，在 Llama-2 上达到 90% ASR，在 GPT-4 上达到 78%。Prompt with RS 还表现出很高的查询效率（例如对 Vicuna 平均只需 2 次查询，对 GPT-3.5 只需 3 次），这是由于它使用了手工优化的提示模板和预计算初始化。总体而言，这些结果表明，即便是较新的闭源未防御模型也依然高度容易受到越狱攻击。最后，我们在附录 B 中展示了按数据集来源划分的 ASR；可以看到，各攻击在不同来源上的 ASR 相对一致，而来源之间的偏差很可能是由于各类别构成不均衡所致。

### 防御评估

在表 3 中，我们将上述三种防御与不同 LLM 组合，测试它们的表现（其余防御结果推迟到附录 D）。我们计算这些算法针对未防御模型上学到的迁移攻击的效果，这意味着我们直接复用每种攻击在原始 LLM 上找到的越狱字符串（其结果见表 2）。我们注意到，这可能是最简单的一类评测，因为它并不针对目标防御进行自适应，更复杂的方法可能进一步提高 ASR。我们观察到，Perplexity Filter 只对 GCG 有效。相反，SmoothLLM 成功降低了 GCG、PAIR 的 ASR，但对 JB-Chat 和 Prompt with RS 的效果可能并不好（见 Vicuna 和 GPT-4）。Erase-and-Check 似乎是最稳固的防御，尽管 Prompt with RS 在所有 LLM 上仍然达到了非平凡的成功率。最后，我们注意到，使用这些防御中的某些会显著增加推理时间，这在分析结果时应被考虑。我们希望，基准提供的这些防御的易用访问，将有助于开发专门针对它们的自适应越狱算法。

**表 3：当前防御的评估。** 我们报告从未防御 LLM 到同一 LLM 的迁移攻击成功率，不同防御分别作用于同一模型。更多防御见附录 D。

| Attack | Defense | Vicuna | Llama-2 | GPT-3.5 | GPT-4 |
|---|---|---:|---:|---:|---:|
| PAIR | SmoothLLM | 55% | 0% | 5% | 19% |
|  | Perplexity Filter | 69% | 0% | 17% | 30% |
|  | Erase-and-Check | 0% | 0% | 2% | 1% |
| GCG | SmoothLLM | 4% | 0% | 0% | 4% |
|  | Perplexity Filter | 3% | 1% | 0% | 0% |
|  | Erase-and-Check | 17% | 1% | 3% | 2% |
| JB-Chat | SmoothLLM | 73% | 0% | 0% | 0% |
|  | Perplexity Filter | 90% | 0% | 0% | 0% |
|  | Erase-and-Check | 1% | 0% | 0% | 0% |
| Prompt with RS | SmoothLLM | 68% | 0% | 4% | 56% |
|  | Perplexity Filter | 88% | 73% | 61% | 70% |
|  | Erase-and-Check | 24% | 25% | 8% | 10% |

### 拒答评测

我们在 JBB-Behaviors 的 100 个良性行为上计算拒答率，评估 Vicuna 与 Llama-2 及所有防御。我们使用 Llama-3 8B 作为拒答判别器，并使用附录 F 中给出的提示。在图 2 中，我们观察到，正如预期，Vicuna 很少拒答（没有防御时仅 9%），而 Llama-2 在超过 60% 的情况下返回拒答。此外，我们看到，在所选超参数下，当前防御并不会显著提高拒答率。这个评测旨在作为一种简单的合理性检查，用于快速检测过度保守的模型或防御。然而，它不能替代更全面的效用评估，例如使用 MMLU（Hendrycks et al., 2021）或 MT-Bench（Zheng et al., 2023）等标准基准。

## 5 展望

### 未来计划

我们将 JailbreakBench 视为标准化并统一评估 LLM 对越狱攻击鲁棒性的第一步。目前，鉴于该领域尚处于早期阶段，我们不限制提交的威胁模型或目标模型架构。相反，我们希望当前版本的 JailbreakBench 反映对越狱评测标准化的一次初步尝试，并计划随着该领域发展以及“游戏规则”逐步明确而定期更新该基准。这也可能包括：扩展可用的越狱行为数据集；更严格地评估越狱防御，尤其是在非保守性和效率方面；更新作为判别器的分类器；以及定期重新评估闭源 LLM 上的攻击成功率。

### 伦理考量

在公开这项工作之前，我们已将越狱工件和结果分享给领先的 AI 公司。我们也认真考虑了本工作的伦理影响。在不断演进的 LLM 越狱领域，有几个事实值得注意：(1) 大多数越狱攻击的代码都是开源的，这意味着恶意用户本来就拥有生成对抗提示的手段；(2) 由于 LLM 是使用 Web 数据训练的，我们试图从 LLM 中诱导出的多数信息都已可以通过搜索引擎获得，因此仅就少量行为开源越狱工件并不会带来任何新的、此前未公开可得的内容；(3) 使 LLM 更能抵抗越狱攻击的一条有前景的路径，是用越狱字符串对其进行微调，因此我们预计越狱工件仓库将有助于推动更安全 LLM 的进展。

### 局限性

尽管我们尽力使基准尽可能全面，但我们必须限制攻击者可使用的范围。例如，在当前形式下，我们不允许攻击者修改 system prompt 或用某个特定字符串预填充 LLM 响应。此外，现代 LLM 往往接受文本之外的其他模态输入，而这些也同样可以被用于越狱。我们的基准目前不提供这种选项，而是仅聚焦于文本。

## 致谢

作者感谢 HarmBench 团队以及 J. Zico Kolter 对本文早期版本提供的反馈。

Patrick Chao 和 Edgar Dobriban 在部分资助下受到 ARO、NSF 和 Sloan Foundation 的支持。本文中的任何观点、发现和结论或建议仅代表作者个人，并不一定反映 Army Research Office（ARO）、国防部或美国政府的观点。Maksym Andriushchenko 由 Google Fellowship 和 Open Phil AI Fellowship 支持。Edoardo Debenedetti 由 armasuisse Science and Technology 支持。Alexander Robey、Hamed Hassani 和 George J. Pappas 由 NSF Institute for CORE Emerging Methods in Data Science（EnCORE）支持。Alexander Robey 还受到 ASSET Amazon AWS Trustworthy AI Fellowship 的支持。Eric Wong 部分受到 Amazon Research Award “Adversarial Manipulation of Prompting Interfaces” 的支持。

## 参考文献

以下参考文献条目在原文中主要为书目信息，此处保留为原论文结构的一部分，不展开翻译条目内容。