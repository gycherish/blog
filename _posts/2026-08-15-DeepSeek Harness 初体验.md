---
media_subpath: /assets/img/notes
author: gycherish
title: "DeepSeek Harness 初体验"
tags:
  - ai
  - agent
  - deepseek
  - pixi
categories:
date: 2026-08-15 21:00
---

最近两天，关于 [dsh](https://www.deepseek.com/harness/)(DeepSeek Harness) 的文章铺天盖地，从安装、使用到插件机制基本上该讲的都讲了。作为已经重度依赖 AI 编程的我，趁着周末有些时间，也准备体验体验。

本文站在初学者的角度，简单记录下从安装、运行到使用的过程。至于其最吸引我的 "**Everything is a Plugin**" 机制后续我会单独详细写一篇。

## 优先看第一手资料

考虑到网上的文章特别多，很多人可能会选择直接参考网上第三方的教程。但是，作为具有 10 年以上开发经验的开发者，我依然强烈建议：**无论什么时候，都应当优先选择看官方第一手资料**。网上所有的教程都应当只是引导你去官网学习的引子，包括我这篇文章。只有当你阅读官方文章很吃力，或者确实有很多地方看的一知半解的时候，我才建议你去看第三方资料，并通过吸收别人的理解来达到掌握相关知识的目的。

> 网络环境问题不应当成为你前进路上的绊脚石！

## 开始之前

作为开发者，我相信大家一定遇到过随着开发的进行，个人电脑或开发机慢慢地被开发过程中安装的各种依赖搞得乱七八糟的情况。这种情况有多糟心，相信大家都有相应的体会，我就不再详述。

为了解决这种问题，现在各大编程语言、运行时基本都有自己的一套隔离依赖的机制，比如 python 的 venv，nodejs 的 node_modules 目录。

操作系统层面也为上层应用的隔离做了很多努力：Windows 的 msvcrt 作为系统的 libc 永远默认存在于所有版本中；python 的 [manylinux](https://github.com/pypa/manylinux) 项目确保几乎所有的 python 包能不依赖 Linux 内核版本；[NixOS](https://nixos.org/) 更是通过 nix 对系统所有的软件包进行了彻底的隔离...

整个软件世界为了兼容性、隔离性、可复现构建等特性做了太多太多的努力，也因此我们能够站在巨人的肩膀上从容地做着我们想做的事。

那么，回到本文的主题，通过阅读官方文档，dsh 依赖了 [nodejs](https://nodejs.org/)。虽然 nodejs 支持隔离 dsh 本身的依赖，但是不同软件可能依赖不同的 nodejs 版本（特别是现在基于前端技术栈的软件满天飞的时代！！！），如果将多份 nodejs 版本都安装在系统的默认路径下必然存在冲突。因此，软件本身也需要被管理、被隔离。

扯了那么多，现在我正式推荐一款软件来帮助大家解决这种问题，即 [pixi](https://pixi.prefix.dev/)。Pixi 是 Prefix.dev 开发的一款跨平台环境与包管理器。可以把它理解为一个更现代、速度更快、项目化程度更高的 [Conda](https://conda.io) 替代品。它最大的特点是，不仅能管理 Python 包，还能管理整个开发环境：

- 系统的 sysroot
- 编译工具链
- C/C++ 库
- CUDA 工具包
- Python、Node.js、Rust
- ...

理论上，只要你愿意，Pixi 可以管理几乎所有软件包，当然 Pixi 本身就不能再纳入管理了（chicken-and-egg problem）。不过好在 Pixi 本身静态链接且保持向后兼容，因此安装升级该软件特别方便。

Pixi 具体的安装过程不再详述，因此下文假设已经安装了该软件，并正确设置了环境变量。

## 安装运行

下文命令运行在 PowerShell 中，如果相关命令执行失败可以先执行该命令：

```bash
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

官方提供两种安装方式，第一种适合普通用户：

```bash
npx @deepseek-ai/dsh web
```

这需要先在系统上全局安装 nodejs，存在潜在的冲突问题，普通用户如果没有安装太多其他软件，可以使用该方式。不过，针对普通用户最好的方案还是等官方出 PC 版安装包，通过打包彻底隔绝依赖（好像有人做了）。

本文使用第二种源码安装的方式。第一步先克隆源码：

```bash
git clone https://github.com/deepseek-ai/deepseek-harness.git
cd deepseek-harness
```

第二步使用 pixi 安装依赖：

```bash
pixi init
pixi add nodejs pnpm
```

第三步进入 pixi shell 环境运行 dsh 官方命令，该 shell 环境会自动将添加的依赖加入 PATH 环境变量中，确保引入的依赖可用并与系统全局安装的版本相互隔离：

```bash
pixi shell
pnpm install
pnpm run build
pnpm dsh web
```

至此，所有依赖安装完成，并且除了 pixi 本身安装在系统路径下，dsh 项目的所有依赖都只存在于项目根目录，不会对系统环境产生任何影响。

根据命令输出的地址，在浏览器中打开该地址即可看到 dsh 运行界面：`http://127.0.0.1:3080`

首次运行会弹出一个输入 API Key 的模态窗口：

![dsh-first](dsh-first.png)

## 简要介绍

点击 “稍后配置”，我们便进入了 dsh 的主界面，可以看到 dsh 的界面非常简洁：

![dsh-main](dsh-main.png)

用过 Codex 或其他 AI 工具的人，对这种经典布局应该非常有感觉：左侧从上到下依次是新会话、工作区和会话列表，最下面是设置入口；中间是对话区，没有会话时只有一个输入框；输入框上方可以选择工作区以及运行模式。整体设计非常简洁明了。

### 接入自定义模型

首屏那个模态窗只能填 DeepSeek 官方的 Key。我手上是一个 OpenAI 兼容格式的自建端点，所以直接点了"稍后配置"，改从设置里加自定义提供方：设置 → 模型 → 自定义提供方。

![dsh-provider-config](dsh-provider-config.png)

填完点"创建提供方"，回到主界面就能在模型选择器里看到它了。

### 实现 2048

配置完 API Key 就可以干活了。我选了一个经典的 2048 小游戏作为测试任务。我给的提示词把要求写得比较细，因为这次想看的是它在一个多文件任务上的完整表现，而不是"能不能写出来"：

![dsh-2048-prompt](dsh-2048-prompt.png)

注意输入框下面多了两个按钮。左侧是权限模式，我保持默认的 **Workspace Write**，意思是它可以在工作区里自由读写，但出了工作区就要询问。右侧是当前支持的模型。

按下回车后，dsh 就开始干活了。大约三分半钟后任务结束，成功帮我实现了 2048 小游戏，经过测试，效果不错：

![dsh-2048](dsh-2048.png)

### 任务开始后的变化

提交提示词后，dsh 的会话区域就跟其他 AI 工具有了明显的区别：

![dsh-chat-main](dsh-chat-main.png)

我将整个对话区域划分为 5 个子区域，并将它们分别称为：

- A1: 标题栏
- A2: 菜单栏
- A3: 会话执行区
- A4: 任务控制区
- A5: 状态栏

其中状态栏包含本次任务的主要统计指标。

更令我惊艳的设计是“轨迹”界面：

![dsh-track](dsh-track.png)

该界面把 dsh 的整个执行流完整地展示出来了。

顶部是按时间排布的泳道图，Input、Model、Tools 三行分开，能清楚地看出什么时候输入提示词、什么时候调用模型、什么时候调用工具以及三者各自的耗时。选中任意一行后，右侧还会出现更详细的信息。

右上角还提供导出整个会话日志的功能，里面连注入的 `@deepseek-ai/dsh-system-prompt` 和每一条 CONTEXT 快照都在。官方架构文档里有条不变量叫 "**Model-visible means logged**"，任何进入模型请求的内容都必须能从会话日志里重建出来。

## 插件机制的体现

我们再回到设置界面：

![dsh-plugin](dsh-plugin.png)

可以看到右侧的“插件” 和 “Agent 预设” 功能。其中 “插件” 界面主要是插件配置和内置的插件列表。

这里的重点在 “Agent 预设” 界面，可以看到，内置的 4 个预设刚好就是聊天框中可以选择的运行模式：

![dsh-select-preset](dsh-select-preset.png)

“Agent 预设” 翻译成英文是 “Agent presets”。提到 preset，用过 CMake 的读者应该会想到 CMakePresets.json。它可以预定义一套项目配置。假设没有改文件，用户想使用 Ninja 编译 debug 版本并开启测试功能的项目需要这样做：

```bash
cmake -S . -B build/debug -G Ninja -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON
cmake --build build/debug
```

有了这个配置后，只需要这样：

```bash
cmake --build --preset debug
```

这极大地简化了配置流程。

我想 dsh 中的 “Agent presets” 应该也是如此：通过配置文件将一组 dsh 中的插件进行组合来实现特定的功能。

一旦 Agent Preset 配置完成，便可在 dsh 的会话界面中选择，之后任务会根据相应设置执行。

### 设计野心

至此，我已经可以想象到 DeepSeek 的设计野心：

- **让用户掌控一切**：界面对可观测性的设计达到了极致；用户可以对插件做任意组合。
- 做所有 AI Agent 的运行底座：**Everything is a Plugin** 设计理念让 dsh 的可组合性达到了极致，理论上可以像拼积木那样实现市面上所有 AI 工具的功能。

## 总结

说心里话，初次体验并了解插件机制后，我内心是非常激动的，我已经开始构想未来 AI Agent 的样子了。我甚至可以预言，这套机制未来一定是 AI Agent 的主流，并且通过 dsh 的 SDK，垂直行业也一定会引入这套架构来用 AI 解决各行各业的问题。

AI 的世界拼的本就是想象力，**Everything is a Plugin** 的机制会让想象力以各种不同的方式得以实现！