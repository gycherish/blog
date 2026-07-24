---
media_subpath: /assets/img/notes
author: gycherish
title: "Senders/Receivers 入门"
tags:
  - c++
  - concurrency
  - sender-receiver
  - execution
categories:
date: 2026-07-22 21:00
original_author: Lucian Radu Teodorescu
original_url: https://accu.org/journals/overload/32/184/teodorescu/
original_date: 2024-12
---

> 译者说明：本文译自 Lucian Radu Teodorescu 发表于 ACCU *Overload* 184 的 [《Senders/Receivers: An Introduction》](https://accu.org/journals/overload/32/184/teodorescu/)。文章以 2024 年 6 月通过的 P2300R10 及当时的相关提案为准，后续提案与实现可能已经发生变化。译文保留原文的版本语境，同时校正了代码中明显的拼写和标点错误，并收紧了少数过强的技术结论。

2024 年 6 月，WG21 在圣路易斯召开全体会议，正式通过了 [P2300R10：`std::execution`](https://wg21.link/P2300R10)，也就是 Senders/Receivers，并将其纳入 C++26。提案内容很快进入了 [C++ 标准工作草案](https://eel.is/c++draft/#exec)。Herb Sutter 的[圣路易斯会议报告](https://herbsutter.com/2024/07/02/trip-report-summer-iso-c-standards-meeting-st-louis-mo-usa/)介绍了这次会议的主要进展。

Senders/Receivers 是 C++26 的重要新增特性之一。它提供了一套表达计算的基础模型，可用于并发、并行和异步任务。这套模型把任务依赖、完成方式和执行位置显式编码进工作图，有助于减少死锁和数据竞争，但不能代替正确的同步与生命周期管理。至少从理论上说，它适用于各种并发问题，而不只限于少数特定场景。Senders/Receivers 采用静态组合，允许实现消除不必要的抽象开销；任务链既能在 CPU、GPU 上执行，也可以表示非阻塞 I/O。

尽管这项提案有不少优点，仍有人认为此时将它加入 C++ 标准并不妥当。常见质疑包括功能复杂、编译时间长、成熟度不足以及难以教学。最后一点引起了我的注意。

本文将介绍 P2300 及几项相关提案所定义的 Senders/Receivers。重点不在罗列这套模型的所有优势，也不会深入复杂的实现细节。我希望从未读过提案、也没有看过相关演讲的读者，能够通过本文掌握 Senders/Receivers 的基本用法。

读完之后，读者应该可以动手编写使用 Senders/Receivers 的程序。文中的示例假定这些功能已经进入标准库。写作本文时，还没有标准库提供 Senders/Receivers，不过可以使用参考实现 [stdexec](https://github.com/NVIDIA/stdexec) 运行示例。

## 从一个简单例子开始

代码清单 1 使用 Senders/Receivers 输出 `Hello, world!`。Receiver 通常不会出现在用户代码里，它们藏在处理 Sender 的算法实现中。因此，也可以把这段代码看成一个最基本的 Sender 示例。

```cpp
namespace stdexec = std::execution;
stdexec::sender auto computation
  = stdexec::just("Hello, world!")
  | stdexec::then([](std::string_view s) {
    std::print(s);
  });
std::this_thread::sync_wait(
  std::move(computation));
```

*代码清单 1*

在一定程度上，这段代码等价于代码清单 2。我们先描述“把 `Hello, world!` 输出到标准输出”这个动作，并将描述保存在变量 `computation` 中，随后执行它。整个动作由两部分组成：一部分描述字符串值，另一部分接收字符串并将其输出。

```cpp
std::function<void()> computation = []{
  std::string_view s = "Hello, world!";
  std::print(s);
};
computation();
```

*代码清单 2*

`just(X) | then(f)` 所描述的工作相当于 `f(X)`。再接一个 `then`，`just(X) | then(f) | then(g)` 就相当于 `g(f(X))`。如果 `f` 和 `g` 都不产生值，那么这条工作链相当于 `f(X); g()`。**Sender 从设计之初就考虑了可组合性**，复杂计算可以由较简单的计算组合出来。

调用 `sync_wait` 时，`computation` 描述的工作才真正开始执行。去掉 `sync_wait`，程序不会执行任何工作。

代码清单 1 虽然简单，却展示了 Sender 的几个重要特征：

- Sender 描述计算；
- Sender 可以方便地组合；
- Sender 采用惰性执行，本例在调用 `sync_wait` 前什么都不会发生。

Sender 还有两个重要特点，后文会继续展开：

- Sender 可以描述并发或异步工作；
- Sender 支持结构化并发。

先看第一个特点。

## 表达并发

代码清单 3 展示了如何在另一个线程上执行代码。在 Senders/Receivers 模型中，我们不直接操作线程，而是使用**调度器（scheduler）**。调度器是执行上下文的句柄，可以访问一个或多个线程。具体工作在哪里执行，由调度器决定。

```cpp
stdexec::scheduler auto sch 
  = get_system_scheduler();
stdexec::sender auto computation
  = stdexec::schedule(sch)
  | stdexec::then([] {
    std::print("Hello, from a different thread");
  });
std::this_thread::sync_wait(
  std::move(computation));
```

*代码清单 3*

这里使用的是系统调度器。它不属于最初的 [P2300R10](https://wg21.link/P2300R10)，而是由 [P2079R5：System execution context](https://wg21.link/P2079R5) 提出的扩展。系统调度器被认为对 Senders/Receivers 十分重要，[P3109R0](https://wg21.link/P3109R0) 计划将它纳入标准。系统调度器描述一个供整个应用程序使用，甚至可由多个应用程序共享的执行上下文。

`schedule(sch)` 返回一个 Sender。它表示一项在系统执行上下文所属线程上开始的工作。这个 Sender 不向后续 Sender 发送任何值，只保证后续工作会在该线程上执行。

在一定程度上，`schedule(sch) | then(f)` 相当于 `std::thread([]{ f() })`。区别在于，新线程属于 `sch` 所代表的执行上下文。

`schedule()` 用于在某个执行上下文中启动工作。有时，我们还需要把执行从一个上下文转移到另一个上下文，这时可以使用 `continues_on()`。假设一段计算在原执行上下文中运行，后续计算需要切换到另一个上下文，可以用 `continues_on()` 将两段计算连接起来。下面这条工作链在原线程执行 `f`，然后转移到调度器 `sch` 所代表的另一个线程执行 `g`：

```cpp
just() | then(f) | continues_on(sch) | then(g)
```

使用 `schedule()` 和 `continues_on()`，可以表示各种线程间的工作转移。为了让某些场景写起来更方便，Senders/Receivers 还提供了 `starts_on()`。当一条工作链需要从指定调度器开始，但工作本身不想绑定调度器时，可以使用它。

代码清单 4 同时展示了 `starts_on()` 和 `continues_on()`。`read_data_snd` 描述从 socket 读取数据的工作，但没有规定在哪个调度器上运行。放进完整计算后，`starts_on(io_sched, std::move(read_data_snd))` 会让它从指定的 I/O 调度器开始执行。

```cpp
stdexec::sender auto read_data_snd
  = stdexec::just(connection, buffer)
  | stdexec::then(read_data);
stdexec::sender auto process_all_snd
  = stdexec::starts_on(io_sched,
    std::move(read_data_snd))
  | stdexec::continues_on(work_sched)
  | stdexec::then(process_data)
  | stdexec::continues_on(io_sched)
  | stdexec::then(write_result);
std::this_thread::sync_wait(
  std::move(process_all_snd));
```

*代码清单 4*

这段代码也展示了 `continues_on()`。读取 socket 的部分，也就是 `read_data_snd` 所表示的工作，运行在 I/O 调度器上。数据处理应当放在“工作调度器”中，因此需要明确切换线程，`continues_on(work_sched)` 正是为此而用。处理结束后，再次调用 `continues_on()` 并传入 I/O 调度器的句柄，切回 I/O 调度器写出响应。

只要把工作组织成 Sender 链，在不同执行上下文之间移动并不困难。

## 等待多个 Sender

前面的示例虽然让不同工作项运行在不同线程上，却都是顺序执行。我们还没有看过两个函数并发运行的情况。

代码清单 5 使用 `when_all()` 并发执行函数 `f` 和 `g`。这个算法接收多个 Sender，等所有 Sender 完成后汇集结果，再交给后续步骤输出。

```cpp
stdexec::sender auto s1 = 
  stdexec::schedule(sch) | stdexec::then(f);
stdexec::sender auto s2 = 
  stdexec::schedule(sch) | stdexec::then(g);
stdexec::sender auto both_results = stdexec::when_all(s1, s2);
stdexec::sender auto print_results
  = std::move(both_results)
  | stdexec::then([](auto... args) {
    std::print("Results: {}, {}", args...);
  });
```

*代码清单 5*

传给 `when_all()` 的两条分支会同时启动，彼此独立。有时我们希望先完成一段公共处理，再并发执行两项或更多工作，最后重新合并工作链。这可以通过 `split()` 实现。代码清单 6 中，工作启动后先调用 `p`，等 `p` 完成，再并发调用 `f` 和 `g`。

```cpp
sender auto common = 
  schedule(sch) | then(p) | split();
sender auto s1 = common | then(f);
sender auto s2 = common | then(g);
sender auto both_results = when_all(s1, s2);
sender auto print_results
  = std::move(both_results)
  | then([](auto... args) {
    std::print("Results: {}, {}", args...);
  });
```

*代码清单 6*

## 批量执行

目前看到的 Sender 每次只能处理一个元素。如果需要处理许多元素，可以使用 `bulk()` 描述这类计算。

代码清单 7 实现了基础线性代数中的 *axpy* 运算，也就是[“a x plus y”](https://en.wikipedia.org/wiki/Basic_Linear_Algebra_Subprograms#Level_1)运算。对于区间 `[0, x.size())` 中的每个索引 `i`，程序都会调用给定的 lambda。

```cpp
double a;
std::vector<double> x;
std::vector<double> y;
sender auto process_elements
  = just()
  | bulk(x.size(), [&](size_t i) {
    y[i] = a * x[i] + y[i];
  });
```

*代码清单 7*

如果 `bulk()` 前面的 Sender 会产生一个值，这个值会传给 `bulk()` 的函数对象。前一个 Sender 产生多个值时，这些值会全部传入。因此，同一个例子也可以写成代码清单 8。

```cpp
double some_value;
std::vector<double> x;
std::vector<double> y;
sender auto process_elements
  = just(some_value)
  | bulk(x.size(), [&](size_t i, double a) {
    y[i] = a * x[i] + y[i];
  });
```

*代码清单 8*

## Sender 的形态与结构化

Sender 还有一个尚未讨论的重要特征，也就是它的形态。正是这个特征让 Sender 易于组合、便于扩展，并能实现结构化并发。

与普通函数相似，Sender 表示的工作有一个入口和一个出口。这个出口通常称为**完成（completion）**或**完成信号（completion signal）**。函数可能返回一个值，也可能抛出异常，因此有两种完成方式。Sender 还多出第三种方式，用于表示取消。在 Senders/Receivers 中，这三种完成方式分别是：

- `set_value(auto... values)`：工作成功完成并产生输出值；
- `set_error(auto err)`：工作以错误 `err` 结束；
- `set_stopped()`：Sender 表示的工作被取消。

普通函数只能返回一个值，Sender 却可以产生多个值，所以 `set_value()` 的签名允许多个参数。普通函数要报告不同于返回值的错误，只能抛出异常；Sender 的错误可以是任意类型，例如 `std::exception_ptr`、`std::error_code` 或用户自定义类型。工作被取消时没有结果值，因此 `set_stopped()` 不接收参数。

普通函数只有一种返回类型，另外可能抛出异常。也就是说，函数 `T f(...)` 可以返回 `T`，也可以产生 `std::exception_ptr`，变化不多。Sender 表示的工作则能以多种值类型或错误类型完成。更准确地说，一个 Sender 可以支持任意组合的完成信号：有的 Sender 能产生多组不同的值类型，有的能产生多种错误类型。

例如，一个 Sender 可以具有下列完成信号：

- `set_value(int)`；
- `set_value(std::string)`；
- `set_value(int, std::string)`；
- `set_error(std::exception_ptr)`；
- `set_error(std::error_code)`；
- `set_stopped()`。

Sender 也可以只支持其中一部分。比如，`just()` 返回的 Sender 只会以 `set_value()` 完成，`just(2, 3.14)` 返回的 Sender 只会以 `set_value(int, double)` 完成。类似地，`just_error("some error string"s)` 只会产生 `set_error(std::string)`，而 `just_stopped()` 只会产生 `set_stopped()`。

从这个角度看，Sender 是函数的泛化，它可以支持多种完成类型。

用函数调用表示完成信号并非偶然，Sender 正是这样调用 Receiver 的。P2300 将 Receiver 定义为“**支持多个通道的回调**”。最终用户通常不需要关心 Receiver，它只是连接 Sender 的黏合层。这也是本文到目前为止一直讨论 Sender，却没有单独引入 Receiver 的原因。后文仍会把重点放在 Sender 上。

Sender 还有一点与普通函数不同。普通函数从进入到完成都在同一个线程上，Sender 表示的工作则没有这项要求。它可以在一个线程上启动，在另一个线程上完成。`schedule(sch)` 就描述了这样的工作：它从当前线程开始，把控制权交给由 `sch` 管理的线程。`continues_on()` 也是一个很好的例子。

因此，Sender 在执行位置上同样是函数的泛化，这一点十分重要。结构化编程教会我们用函数组织非并发代码；有了 Sender，并发程序也可以按同样的方式拆解。程序的各个部分都能用 Sender 表示，甚至整个程序也能由 Sender 组合而成。我曾在 ACCU 2022 的[《Structured Concurrency》](https://www.youtube.com/watch?v=Xq2IMOPjPs0)演讲中展示过一个例子。

Sender 描述的工作具有类似函数的行为，因此也继承了结构化属性。包含在另一个 Sender 中的 Sender 必须先于父 Sender 完成。Sender 可以隐藏实现细节，成为抽象边界；程序本身也能按 Sender 拆分。

这些结构化属性让代码更容易推理，不过结构化并不自动保证线程安全。共享可变状态仍然需要同步，对象生命周期也必须覆盖全部异步操作。Senders/Receivers 降低了推理难度，没有取消这些约束。

Sender 能抽象工作，因此可以表示各种并发或异步操作。例如：

- Sender 可以封装并发排序算法，底层既可以使用 GPU，也可以使用 CPU。这是利用 Sender 加速程序的例子；
- Sender 可以封装图像处理，具体工作可以在单线程、多线程或 GPU 上完成。并发细节被隐藏起来；
- Sender 可以封装 `sleep`。等待时间结束后 Sender 才完成，但不会一直占用线程。这是异步操作的例子；
- Sender 可以封装远程过程调用的结果等待，同时不占用本地线程。这也是异步操作。

## 标准中的 Sender 算法

已经进入 C++26 工作草案的 [P2300R10](https://wg21.link/P2300R10) 定义了一组操作 Sender 的算法。Sender 具有结构化属性，容易组合，因此较大的 Sender 可以由较小的 Sender 构造出来。

C++26 将提供若干 Sender 算法，作为构建复杂 Sender 的基础组件。这些算法分成三类：

- **Sender 工厂**：无需其他 Sender，直接产生 Sender。标准中的算法包括 `schedule()`、`just()`、`just_error()`、`just_stopped()` 和 `read_env()`；
- **Sender 适配器**：接收一个或多个 Sender，并以它们为基础返回新的 Sender。标准中的算法包括 `starts_on()`、`continues_on()`、`schedule_from()`、`on()`、`then()`、`upon_error()`、`upon_stopped()`、`let_value()`、`let_error()`、`let_stopped()`、`bulk()`、`split()`、`when_all()`、`into_variant()`、`stopped_as_optional()` 和 `stopped_as_error()`；
- **Sender 消费者**：消费 Sender，但不产生新的 Sender。标准中的算法包括 `sync_wait()` 和 `sync_wait_with_variant()`。

Sender 工厂和适配器都定义在 `std::execution` 命名空间中，Sender 消费者算法定义在 `std::this_thread` 命名空间中。

下面简要介绍这些算法。

### Sender 工厂

前面已经用过 `just()`。它创建一个 Sender，并以给定值完成。`just_error()` 创建以给定错误完成的 Sender。`just_stopped()` 则创建以 `set_stopped()` 信号完成的 Sender。

`read_env()` 更复杂一些。给它一个*标签（tag）*，它会尝试从执行环境中读取该标签对应的属性。假设一个父 Sender 内部包含子 Sender，子 Sender 就能通过 `read_env()` 取得父 Sender 提供的各种属性。

### Sender 适配器

在介绍具体算法前，需要先说明大多数适配器的两种语法形式：规范形式和可管道化形式。用 `then()` 最容易看清两者的区别。

`then()` 的规范形式是 `then(sndr, ftor)`。它返回一个 Sender；当 `sndr` 完成时，新 Sender 把 `ftor` 应用于输入值，并以转换后的值完成。这就是函数组合。

可管道化形式是 `then(ftor)`，只能放在管道中使用。`sndr | then(ftor)` 等价于 `then(sndr, ftor)`。管道形式通常更容易书写，因此很多人更喜欢它。

严格来说，`then(ftor)` 是 **Sender adaptor closure**，不是 Sender。Then Sender 还包含管道运算符左边的前一个 Sender。为了表达方便，人们在非正式讨论中也常把它直接叫作 Sender。

与 `then()` 类似，`upon_error()` 和 `upon_stopped()` 分别处理错误通道和停止通道。`upon_error()` 将给定函数对象应用于输入错误，并以函数调用的结果完成。`upon_stopped()` 在收到停止信号时调用给定函数对象。

前面已经见过 `starts_on()` 和 `continues_on()`。`on()` 将两者结合起来：它先在指定调度器上执行工作，效果类似 `starts_on()`；完成后再回到原调度器，效果类似 `continues_on()`。

`schedule_from()` 是 `continues_on()` 的基础操作。普通用户通常不会直接调用它，但某些调度器之间的转移可以对它做特化。

前文还简要介绍了 `bulk()`、`split()` 和 `when_all()`。`bulk()` 在一段索引区间内多次执行同一个函数；`split()` 让同一个 Sender 可以出现在同一条计算链中，同时避免重复执行工作；`when_all()` 汇集多个 Sender 的结果。

`let_*()` 系列十分重要，却经常被误解。`let_value()` 和 `then()` 相似，区别是传给它的函数对象应当返回 Sender。它是 Sender 的 monadic bind 操作，也就是构造 Sender 的基础组件之一，与 `optional<T>::and_then()` 这类 `std::optional` 单子操作相似。

用例子更容易理解。假设我们有一条自动增强图像的处理管线，希望把它抽象出来，于是编写函数 `enhance_image_sndr()`。这个函数接收图像，返回知道如何增强图像的 Sender。用伪类型表示，它的类型是 `Image -> Sender<Image>`。现在要把这条管线嵌入另一条管线，依次加载、增强并保存图像。这里不能使用 `then()`，因为它会产生 `Sender<Sender<Image>>`，而我们需要的是 `Sender<Image>`。`let_value()` 正是为此而用，代码清单 9 展示了大致写法。

```cpp
// Returns a sender that produces 'Image' values
auto enhance_image_sndr(Image img) {...}
Image load();
void save(Image);
sender auto complete_pipeline
  = just()
  | then(load)
  | let_value([](Image img) {
    return enhance_image_sndr(img); })
  | then(save);
```

*代码清单 9*

`let_error()` 与 `let_value()` 类似，只是它把函数对象应用于前一个 Sender 产生的错误；`let_stopped()` 则在收到停止信号时调用函数对象。

最后三个 Sender 适配器是 `into_variant()`、`stopped_as_optional()` 和 `stopped_as_error()`，用于简化不同完成信号的处理。

`into_variant()` 把可能具有多个值完成签名的 Sender 转换成只具有一个完成签名的 Sender。新签名由 `std::tuple` 组成的 `std::variant` 表示，错误和停止完成保持不变。例如，假设 `snd` 可以通过 `set_value(std::string)` 或 `set_value(int, double)` 完成，那么 `into_variant(snd)` 可以通过下列信号完成：

```cpp
set_value(std::variant<std::tuple<std::string>,
            std::tuple<int, double>>)
```

`stopped_as_optional()` 将停止完成转换为空的 optional，从而消除停止完成；与此同时，它把类型为 `T` 的值完成转换成 `std::optional<T>`。如果 `snd` 可以产生 `int` 或停止信号，那么 `stopped_as_optional(snd)` 只会产生 `std::optional<int>`。

`stopped_as_error()` 的行为相似，不过它把停止完成信号转换成错误完成。假如 `snd` 可以产生 `int` 或停止信号，`stopped_as_error(snd, err)` 只会产生 `int` 或错误 `err`。

### Sender 消费者

提案定义的主要 Sender 消费者是 `sync_wait()`。前面的例子已经多次使用它。这个算法接收一个 Sender，并执行以下操作：

- 提交 Sender 描述的工作；
- 阻塞当前线程，直至工作完成；
- 按照 Sender 的完成方式向调用者返回结果：
  - Sender 以 `set_value()` 完成时，返回包含这些值的 optional tuple；
  - Sender 以 `set_error()` 完成时，抛出收到的错误；
  - Sender 以停止信号完成时，返回空 optional。

如果 Sender `snd` 通过 `set_value(int, double)` 完成，`sync_wait(snd)` 的结果类型是：

```cpp
std::optional<std::tuple<int, double>>
```

如果 `snd` 只产生一个 `int`，`sync_wait(snd)` 仍然返回 `std::optional<std::tuple<int>>`，不会去掉 tuple。即使给定 Sender 不会发送停止信号，返回类型仍然包含 optional，尽管它一定有值。

这个算法有一项值得注意的限制：给定 Sender 不能具有多种 `set_value()` 信号，因为它定义的返回类型无法容纳多种值完成类型。

Sender 有多种值完成信号时，可以使用 `sync_wait_with_variant()`。它与 `sync_wait()` 类似，但返回类型是由 `std::tuple` 组成的 `std::variant`，外层再包一层 `std::optional`。例如，Sender `snd` 可以通过 `set_value(std::string)` 或 `set_value(int, double)` 完成，那么 `sync_wait_with_variant(snd)` 返回：

```cpp
std::optional<std::variant<std::tuple
    <std::string>, std::tuple<int, double>>>
```

乍看之下有些复杂，稍加练习后就很直接。考虑到 Sender 可能具有的完成类型，这也是顺理成章的结果。

## P2300 之外

上一节可能让人觉得 P2300 已经提出了大量算法，足以覆盖并发与异步的所有需求，实际远非如此。它只是为构建基础 Sender 打好了地基。标准委员会已经通过 [P3109R0：A plan for `std::execution` for C++26](https://wg21.link/P3109R0)，其中列出了一些希望加入 C++、却不属于 P2300 的工作。对最终用户影响较大的有三项：

- 系统执行上下文；
- 异步作用域；
- 协程 task 类型。

当时并入标准的 Senders/Receivers 提案没有定义任何调度器，因此用户可能需要自行编写调度器才能描述并发工作。较早版本曾定义线程池调度器，后来因为诸多问题被删除。[P2079R5](https://wg21.link/P2079R5) 提出的系统执行上下文利用操作系统提供的执行资源：Windows 上可使用 [Windows Thread Pool](https://learn.microsoft.com/en-us/windows/win32/procthread/thread-pools)，macOS 上可使用 [Grand Central Dispatch](https://swiftlang.github.io/swift-corelibs-libdispatch/)。系统调度器旨在减少 CPU [过度订阅](https://en.wikipedia.org/wiki/Resource_contention)，适合作为启动 CPU 密集型工作的默认选择。代码清单 3 已经展示过一个例子。

直到不久前，P2300 还包含 `start_detached()` 和 `ensure_started()`。这两个算法会立即提交 Sender 的工作，却没有等待工作完成的手段。这样启动的工作可能比启动它的作用域活得更久，因此会形成非结构化并发。当时提交工作的唯一方式是完全结构化的 `sync_wait()`。非结构化并发容易引入问题，但有时确实需要从一个很窄的作用域启动大量工作。

[P3149R6](https://wg21.link/P3149R6) 的异步作用域允许以弱结构化方式启动工作。提案定义一个异步作用域，可以在其中动态启动寿命超过当前词法作用域的任务。关键约束是，销毁异步作用域之前，必须等待其中启动的所有工作结束。它允许一定程度的非结构化，但把这种非结构化限制在清晰的边界内。

异步作用域除了允许有限的非结构化，还能动态启动数量不定的工作项，并在完全结构化的上下文中等待它们全部完成。

第三项重要设施是协程 task 类型。用户可以编写能与 Sender 无缝协作的 `std::execution::task<T>` 协程：既可以在其中 `co_await` Sender，也可以把协程本身视为 Sender。这样一来，用户除了组合 Sender 算法，还能使用协程表达并发和异步。Task 类型可能带来一些性能成本，但某些程序用协程写起来更易读。

还有一些值得加入 C++、但未包含在 P3109 中的 Senders/Receivers 功能：

- C++ 并行算法（同步，P2500）；
- C++ 异步并行算法（P3300）；
- I/O 和定时调度器；
- 基于 Senders/Receivers 的网络功能。

## 结论

Senders/Receivers 是 C++ 中用于表达计算的新模型，支持并发、并行和异步。它提供结构化并发，让并发代码更容易推理，也能避开一些常见陷阱。这项功能已经通过投票进入 C++，预计随 C++26 发布。

本文从计算的构造讲起，再逐步进入并发，没有一开始就陷入线程与执行上下文的细节。这正是该模型的优势之一：它能隐藏一部分并发细节，同时保留优化和安全推理所需的信息。

为了让读者掌握提案的关键内容并开始编写 Senders/Receivers 程序，本文用了较多篇幅解释 Sender 背后的思路，但没有深入复杂问题的具体实现。网上已经有一些演讲和示例涵盖这些内容，它们也很适合作为下一篇文章的主题。

## 参考资料

- [GCD] Apple, [Grand Central Dispatch](https://swiftlang.github.io/swift-corelibs-libdispatch/), 2016.
- [Microsoft] Microsoft, [Thread Pools](https://learn.microsoft.com/en-us/windows/win32/procthread/thread-pools), 2021.
- [P2300R10] Michał Dominiak 等，[`std::execution`](https://wg21.link/P2300R10), 2024.
- [P2079R5] Lucian Radu Teodorescu 等，[System execution context](https://wg21.link/P2079R5), 2024.
- [P3109R0] Lewis Baker 等，[A plan for `std::execution` for C++26](https://wg21.link/P3109R0), 2024.
- [P3149R6] Ian Petersen 等，[async_scope: Creating scopes for non-sequential concurrency](https://wg21.link/P3149R6).
- [stdexec] NVIDIA, [Senders: A Standard Model for Asynchronous Execution in C++](https://github.com/NVIDIA/stdexec).
- [Sutter24] Herb Sutter, [Trip report: Summer ISO C++ standards meeting](https://herbsutter.com/2024/07/02/trip-report-summer-iso-c-standards-meeting-st-louis-mo-usa/), 2024.
- [Teodorescu22] Lucian Radu Teodorescu, [Structured Concurrency](https://www.youtube.com/watch?v=Xq2IMOPjPs0), ACCU Conference, 2022.
- [WG21] WG21, [Execution control library](https://eel.is/c++draft/#exec), *Working Draft Programming Languages – C++*.
- [Wikipedia-1] Wikipedia, [Basic Linear Algebra Subprograms](https://en.wikipedia.org/wiki/Basic_Linear_Algebra_Subprograms#Level_1).
- [Wikipedia-2] Wikipedia, [Resource contention](https://en.wikipedia.org/wiki/Resource_contention).
